"""Durable admission/outbox and receipt-driven finite-game execution."""

import argparse
import importlib
import json
import sqlite3
from pathlib import Path

from .core import validate, winning


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class Ledger:
    """One resource pool; BEGIN IMMEDIATE serializes debt admission and updates."""

    def __init__(self, path, horizon, handlers, max_failures=1, bucket=1, existing=()):
        if (
            type(horizon) is not int
            or horizon < 1
            or type(max_failures) is not int
            or max_failures < 0
            or type(bucket) is not int
            or bucket < 1
            or not handlers
            or len(set(handlers)) != len(handlers)
        ):
            raise ValueError("Use a positive horizon/bucket and distinct handlers")
        validate(list(existing), horizon, handlers)
        self.horizon, self.handlers = horizon, list(handlers)
        self.max_failures, self.bucket = max_failures, bucket
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS state (
                id INTEGER PRIMARY KEY CHECK(id=1), config TEXT NOT NULL,
                tick INTEGER NOT NULL, streak TEXT NOT NULL, frozen TEXT
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, spec TEXT NOT NULL,
                remaining INTEGER NOT NULL, origin TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS requests (
                id TEXT PRIMARY KEY, spec TEXT NOT NULL, decision TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS outbox (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL,
                command TEXT NOT NULL, receipt TEXT
            );
        """)
        config = encode(
            dict(
                horizon=horizon,
                handlers=handlers,
                max_failures=max_failures,
                bucket=bucket,
                existing=list(existing),
            )
        )
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT config FROM state WHERE id=1").fetchone()
            if row and row[0] != config:
                raise ValueError(
                    "Ledger is bound to a different resource/episode contract"
                )
            if not row:
                self.db.execute(
                    "INSERT INTO state VALUES (1,?,0,?,NULL)",
                    (config, encode([0] * len(handlers))),
                )
                for job in existing:
                    self.db.execute(
                        "INSERT INTO jobs VALUES (?,?,?,?)",
                        (job["id"], encode(job), job["work"], "existing"),
                    )

    def close(self):
        self.db.close()

    def _state(self):
        tick, streak, frozen = self.db.execute(
            "SELECT tick,streak,frozen FROM state WHERE id=1"
        ).fetchone()
        rows = self.db.execute(
            "SELECT spec,remaining,origin FROM jobs ORDER BY id"
        ).fetchall()
        return tick, tuple(json.loads(streak)), frozen, rows

    def _pending_handlers(self):
        return bool(
            self.db.execute(
                "SELECT 1 FROM outbox WHERE kind='handler' AND receipt IS NULL LIMIT 1"
            ).fetchone()
        )

    def _solve(self, tick, streak, rows):
        jobs = [json.loads(row[0]) for row in rows]
        work = tuple(row[1] for row in rows)
        safe, states, strategy = winning(
            jobs,
            self.horizon,
            self.handlers,
            self.max_failures,
            self.bucket,
            start=tick,
            remaining=work,
            streak=streak,
            quotient=True,
            antichains=True,
        )
        return safe, states, strategy, jobs, work

    def admit(self, request_id, jobs, release, base_permit):
        """Atomically reserve the augmented debt and exactly one release command."""
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("Request ID must be a nonempty string")
        spec = encode(dict(jobs=jobs, release=release, base_permit=base_permit))
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            prior = self.db.execute(
                "SELECT spec,decision FROM requests WHERE id=?", (request_id,)
            ).fetchone()
            if prior:
                if prior[0] != spec:
                    raise ValueError("Request ID replayed with different arguments")
                return prior[1]
            tick, streak, frozen, rows = self._state()
            if frozen or self._pending_handlers():
                return "DEFER"
            if type(base_permit) is not bool:
                raise ValueError("Base policy permit must be an explicit Boolean")
            existing = {json.loads(row[0])["id"] for row in rows}
            if any(job["id"] in existing for job in jobs):
                raise ValueError("New job IDs must not reuse an existing obligation")
            proposed = rows + [(encode(job), job["work"], request_id) for job in jobs]
            safe, _, _, _, _ = self._solve(tick, streak, proposed)
            decision = "ADMITTED" if base_permit and safe else "DENIED"
            self.db.execute(
                "INSERT INTO requests VALUES (?,?,?)", (request_id, spec, decision)
            )
            if decision == "ADMITTED":
                for job in jobs:
                    self.db.execute(
                        "INSERT INTO jobs VALUES (?,?,?,?)",
                        (job["id"], encode(job), job["work"], request_id),
                    )
                command = dict(
                    id="release:" + request_id,
                    kind="release",
                    request=request_id,
                    authorized_tick=tick,
                    payload=release,
                )
                self.db.execute(
                    "INSERT INTO outbox VALUES (?,?,?,NULL)",
                    (command["id"], "release", encode(command)),
                )
            return decision

    def releases(self):
        """List pending committed records; emit_release validates at invocation."""
        return [
            json.loads(row[0])
            for row in self.db.execute(
                "SELECT command FROM outbox WHERE kind='release' AND receipt IS NULL ORDER BY id"
            )
        ]

    def emit_release(self, command, executor):
        """Keep clock/debt validation and release invocation in one serialized gate."""
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute(
                "SELECT command,receipt FROM outbox WHERE id=? AND kind='release'",
                (command["id"],),
            ).fetchone()
            if row is None or row[0] != encode(command):
                raise ValueError("Release is not a committed admission outbox record")
            if row[1] is not None:
                return True
            # Reconcile an effect committed before a crash without invoking it again.
            receipt = executor.lookup(command)
            if receipt is None:
                tick, streak, frozen, rows = self._state()
                if (
                    frozen
                    or self._pending_handlers()
                    or not self._solve(tick, streak, rows)[0]
                ):
                    return False
                receipt = executor.execute(command)
            if receipt is None:
                return False
            if (
                not executor.verify(receipt)
                or receipt.get("command") != command
                or receipt.get("success") is not True
                or receipt.get("effect_committed") is not True
            ):
                raise ValueError(
                    "Release needs an authenticated committed-effect receipt"
                )
            self.db.execute(
                "UPDATE outbox SET receipt=? WHERE id=?",
                (encode(receipt), command["id"]),
            )
            return True

    def dispatch(self):
        """Persist the stored winning control before any handler invocation."""
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            tick, streak, frozen, rows = self._state()
            pending = [
                json.loads(row[0])
                for row in self.db.execute(
                    "SELECT command FROM outbox WHERE kind='handler' AND receipt IS NULL ORDER BY id"
                )
            ]
            if pending:
                return pending
            if frozen:
                # Recovery serves accepted debt without certifying an invalid game state.
                safe, strategy = False, {}
                jobs = [json.loads(row[0]) for row in rows]
                work = tuple(row[1] for row in rows)
            else:
                safe, _, strategy, jobs, work = self._solve(tick, streak, rows)
            if not any(work) or tick >= self.horizon:
                return []
            if safe and not frozen:
                assignment = strategy[(tick, work, streak)]
                source = "winning"
            else:
                # Assumption failures freeze new releases; accepted debt still gets service.
                source, assignment, assigned = "recovery_edf", [], [0] * len(jobs)
                index = {job["id"]: i for i, job in enumerate(jobs)}
                for handler in self.handlers:
                    ready = [
                        i
                        for i, job in enumerate(jobs)
                        if handler in job["handlers"]
                        and work[i] > assigned[i]
                        and all(
                            work[index[p]] == 0 for p in job.get("predecessors", [])
                        )
                    ]
                    chosen = (
                        min(ready, key=lambda i: (jobs[i]["deadline"], jobs[i]["id"]))
                        if ready
                        else -1
                    )
                    assignment.append(chosen)
                    if chosen >= 0:
                        assigned[chosen] += 1
                if not frozen:
                    self.db.execute("UPDATE state SET frozen='losing_debt' WHERE id=1")
            commands = []
            for handler, job_index in zip(self.handlers, assignment):
                job = jobs[job_index] if job_index >= 0 else None
                command = dict(
                    id=f"tick:{tick}:{handler}",
                    kind="handler",
                    tick=tick,
                    handler=handler,
                    job=job["id"] if job else None,
                    origin=rows[job_index][2] if job else None,
                    obligation=job,
                    work_units=1 if job else 0,
                    strategy=source,
                )
                self.db.execute(
                    "INSERT INTO outbox VALUES (?,?,?,NULL)",
                    (command["id"], "handler", encode(command)),
                )
                commands.append(command)
            return commands

    def receipt(self, receipt, verify):
        """Apply only a trusted adapter-verified, command-bound, idempotent receipt."""
        if not verify(receipt):
            raise ValueError("Receipt failed the configured trusted verifier")
        command = receipt["command"]
        success, committed = receipt.get("success"), receipt.get("effect_committed")
        if type(success) is not bool or type(committed) is not bool:
            raise ValueError(
                "Receipt needs explicit success and effect_committed Booleans"
            )
        expected_effect = success and (
            command["kind"] == "release" or command.get("job") is not None
        )
        if committed != expected_effect or command["kind"] == "release" and not success:
            raise ValueError(
                "Unresolved effects cannot be treated as confirmed discharge"
            )
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute(
                "SELECT command,receipt FROM outbox WHERE id=?", (command["id"],)
            ).fetchone()
            if row is None or row[0] != encode(command):
                raise ValueError("Receipt does not match a persisted command")
            if row[1] is not None:
                if row[1] != encode(receipt):
                    raise ValueError(
                        "Conflicting receipt for an already settled command"
                    )
                return
            self.db.execute(
                "UPDATE outbox SET receipt=? WHERE id=?",
                (encode(receipt), command["id"]),
            )
            if command["kind"] != "handler":
                return
            tick, streak, frozen, rows = self._state()
            if command["tick"] != tick:
                raise ValueError("Receipt belongs to a different clock layer")
            current = [
                json.loads(row[0])
                for row in self.db.execute(
                    "SELECT receipt FROM outbox WHERE kind='handler' AND id LIKE ? ORDER BY id",
                    (f"tick:{tick}:%",),
                )
                if row[0] is not None
            ]
            if len(current) != len(self.handlers):
                return  # A missing receipt retains debt and blocks further admissions.
            outcomes = {item["command"]["handler"]: item for item in current}
            for item in current:
                if item["effect_committed"]:
                    self.db.execute(
                        "UPDATE jobs SET remaining=remaining-1 WHERE id=?",
                        (item["command"]["job"],),
                    )
            following = [
                0 if outcomes[h]["success"] else streak[i] + 1
                for i, h in enumerate(self.handlers)
            ]
            if any(value > self.max_failures for value in following):
                frozen = "failure_contract"
            overdue = any(
                remaining > 0 and tick + 1 >= json.loads(spec)["deadline"]
                for spec, remaining, _ in self._state()[3]
            )
            if overdue and not frozen:
                frozen = "overdue"
            self.db.execute(
                "UPDATE state SET tick=?,streak=?,frozen=? WHERE id=1",
                (tick + 1, encode(following), frozen),
            )

    def snapshot(self):
        tick, streak, frozen, rows = self._state()
        outbox = [
            dict(command=json.loads(c), receipt=json.loads(r) if r else None)
            for c, r in self.db.execute(
                "SELECT command,receipt FROM outbox ORDER BY rowid"
            )
        ]
        return dict(
            tick=tick,
            streak=list(streak),
            frozen=frozen,
            debt=[
                dict(job=json.loads(spec), remaining=work, origin=origin)
                for spec, work, origin in rows
            ],
            outbox=outbox,
        )


class FiniteExecutor:
    """Explicit local model: committed effects and receipts survive process restarts."""

    def __init__(self, path, failures):
        self.failures = {
            int(tick): set(handlers) for tick, handlers in failures.items()
        }
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS model (config TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS commands (id TEXT PRIMARY KEY, receipt TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS effects (id TEXT PRIMARY KEY, command TEXT NOT NULL);
        """)
        config = encode(failures)
        previous = self.db.execute("SELECT config FROM model").fetchone()
        if previous and previous[0] != config:
            raise ValueError("Finite executor trace changed on restart")
        self.db.execute("INSERT OR IGNORE INTO model VALUES (?)", (config,))

    def close(self):
        self.db.close()

    def lookup(self, command):
        row = self.db.execute(
            "SELECT receipt FROM commands WHERE id=?", (command["id"],)
        ).fetchone()
        if row is None:
            return None
        receipt = json.loads(row[0])
        if receipt["command"] != command:
            raise ValueError("Executor idempotency key reused with different arguments")
        return receipt

    def execute(self, command):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            prior = self.db.execute(
                "SELECT receipt FROM commands WHERE id=?", (command["id"],)
            ).fetchone()
            if prior:
                receipt = json.loads(prior[0])
                if receipt["command"] != command:
                    raise ValueError(
                        "Executor idempotency key reused with different arguments"
                    )
                return receipt
            success = command["kind"] == "release" or command[
                "handler"
            ] not in self.failures.get(command["tick"], set())
            committed = success and (
                command["kind"] == "release" or command["job"] is not None
            )
            receipt = dict(
                command=command,
                success=success,
                effect_committed=committed,
                mode="finite_model",
            )
            if committed:
                self.db.execute(
                    "INSERT INTO effects VALUES (?,?)", (command["id"], encode(command))
                )
            self.db.execute(
                "INSERT INTO commands VALUES (?,?)", (command["id"], encode(receipt))
            )
            return receipt

    def verify(self, receipt):
        row = self.db.execute(
            "SELECT receipt FROM commands WHERE id=?",
            (receipt.get("command", {}).get("id"),),
        ).fetchone()
        return row is not None and row[0] == encode(receipt)


def drive(ledger, executor):
    """Run confirmed logical ticks; leave unknown outcomes outstanding for reconciliation."""
    for command in ledger.releases():
        ledger.emit_release(command, executor)
    while True:
        before = ledger.snapshot()["tick"]
        commands = ledger.dispatch()
        if not commands:
            break
        for command in commands:
            receipt = executor.lookup(command)
            if receipt is None:
                receipt = executor.execute(command)
            if receipt is not None:
                ledger.receipt(receipt, executor.verify)
        if ledger.snapshot()["tick"] == before:
            break
    return ledger.snapshot()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--case",
        required=True,
        help="One JSON episode with jobs and explicit execution model",
    )
    parser.add_argument("--ledger", required=True)
    parser.add_argument(
        "--executor", required=True, help="finite or trusted module:factory"
    )
    parser.add_argument("--effects", help="Persistent finite-model effect database")
    parser.add_argument("--bucket", type=int, default=1)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    case = json.loads(Path(args.case).read_text(encoding="utf-8"))
    if args.executor == "finite":
        model = case["execution_model"]
        if model["kind"] != "finite" or not args.effects:
            parser.error("finite requires execution_model.kind=finite and --effects")
        executor = FiniteExecutor(args.effects, model["failures"])
    else:
        module, factory = args.executor.rsplit(":", 1)
        executor = getattr(importlib.import_module(module), factory)(case)
    count = case.get("existing_count", 0)
    ledger = Ledger(
        args.ledger,
        case["horizon"],
        case["handlers"],
        case["max_consecutive_failures"],
        args.bucket,
        case["jobs"][:count],
    )
    try:
        decision = ledger.admit(
            case["id"], case["jobs"][count:], case["release"], case["base_permit"]
        )
        state = drive(ledger, executor)
        debt = [item for item in state["debt"] if item["origin"] == case["id"]]
        missed = sum(
            item["remaining"] > 0 and state["tick"] >= item["job"]["deadline"]
            for item in debt
        )
        resolved = all(item["remaining"] == 0 for item in debt)
        ov = (
            int(missed > 0) if decision == "ADMITTED" and (resolved or missed) else None
        )
        result = dict(
            decision=decision,
            execution_mode=args.executor,
            state=state,
            metrics=dict(
                obligation_violation=ov,
                missed_jobs=missed,
                job_violation_rate=missed / len(debt)
                if debt and (resolved or missed)
                else None,
                functional_success=int(
                    decision == "ADMITTED" and resolved and not ledger.releases()
                ),
            ),
        )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, indent=2, allow_nan=False), encoding="utf-8"
        )
    finally:
        ledger.close()
        executor.close()


if __name__ == "__main__":
    main()
