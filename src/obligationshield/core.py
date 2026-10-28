import functools
import itertools
import json


METHODS = [
    "obligationshield",
    "exact_game",
    "quotient_game",
    "no_antichain",
    "no_quotient",
    "individual_edf",
    "monitor",
    "no_global_debt",
    "average_failures",
    "round_later",
]


def validate(jobs, horizon, handlers):
    ids = [j["id"] for j in jobs]
    if len(ids) != len(set(ids)):
        raise ValueError("Job IDs must be distinct")
    known = set(ids)
    for job in jobs:
        if (
            type(job["work"]) is not int
            or job["work"] <= 0
            or type(job["deadline"]) is not int
            or not 0 < job["deadline"] <= horizon
        ):
            raise ValueError(
                "Integer positive work and deadline within the fixed horizon required"
            )
        if not set(job["handlers"]) <= set(handlers):
            raise ValueError("Unknown eligible handler")
        if not set(job.get("predecessors", [])) <= known:
            raise ValueError("Unknown predecessor")
    closed = set()
    while len(closed) < len(jobs):
        ready = [
            j["id"]
            for j in jobs
            if j["id"] not in closed and set(j.get("predecessors", [])) <= closed
        ]
        if not ready:
            raise ValueError("Cyclic obligation dependencies")
        closed.update(ready)


def winning(
    jobs,
    horizon,
    handlers,
    max_failures=1,
    bucket=1,
    optimistic=False,
    start=0,
    remaining=None,
    streak=None,
    quotient=False,
    antichains=False,
):
    """Solve exists-control/forall-legal-failures over a shared finite resource pool."""
    if (
        type(horizon) is not int
        or horizon < 1
        or type(bucket) is not int
        or bucket < 1
        or type(max_failures) is not int
        or max_failures < 0
        or not handlers
        or len(set(handlers)) != len(handlers)
    ):
        raise ValueError(
            "Positive horizon/bucket, distinct handlers and nonnegative failure bound required"
        )
    validate(jobs, horizon, handlers)
    ids = {j["id"]: i for i, j in enumerate(jobs)}
    deadlines = [int(j["deadline"]) for j in jobs]
    if bucket > 1:
        deadlines = [(d // bucket) * bucket for d in deadlines]
    predecessors = [tuple(ids[k] for k in j.get("predecessors", [])) for j in jobs]
    eligible = [[i for i, j in enumerate(jobs) if h in j["handlers"]] for h in handlers]
    strategy = {}
    # A sufficient colored-DAG equivalence: only isolated, identically specified
    # jobs can be permuted. Every other job retains its concrete identity.
    referenced = {parent for job in jobs for parent in job.get("predecessors", [])}
    colors = {}
    if quotient:
        for i, job in enumerate(jobs):
            if job.get("predecessors") or job["id"] in referenced:
                continue
            color = json.dumps(
                {key: value for key, value in job.items() if key != "id"},
                sort_keys=True,
            )
            colors.setdefault(color, []).append(i)
    groups = [indices for indices in colors.values() if len(indices) > 1]

    def canonical(work):
        result = list(work)
        origin = list(range(len(work)))
        for group in groups:
            ordered = sorted(group, key=lambda i: (work[i], i))
            for target, concrete in zip(group, ordered):
                result[target], origin[target] = work[concrete], concrete
        return tuple(result), origin

    boundaries = {}

    def record(t, work, failure, safe):
        if antichains:
            wins, losses = boundaries.setdefault((t, failure), ([], []))
            if safe:
                wins[:] = [
                    bound
                    for bound in wins
                    if not all(a <= b for a, b in zip(bound, work))
                ]
                wins.append(work)
            else:
                losses[:] = [
                    bound
                    for bound in losses
                    if not all(a >= b for a, b in zip(bound, work))
                ]
                losses.append(work)
        return safe

    @functools.lru_cache(None)
    def solve(t, remaining, streak):
        if any(work > 0 and t >= deadlines[i] for i, work in enumerate(remaining)):
            return False
        if not any(remaining):
            return True
        if t >= horizon:
            return False
        if antichains:
            wins, losses = boundaries.get((t, streak), ([], []))
            if any(all(a <= b for a, b in zip(remaining, bound)) for bound in wins):
                return True
            if any(all(a >= b for a, b in zip(remaining, bound)) for bound in losses):
                return False
        choices = [
            [-1]
            + [
                i
                for i in indices
                if remaining[i] > 0 and all(remaining[p] == 0 for p in predecessors[i])
            ]
            for indices in eligible
        ]
        for assignment in itertools.product(*choices):
            if any(
                assignment.count(i) > remaining[i] for i in set(assignment) if i >= 0
            ):
                continue
            outcomes = [
                [False] if optimistic or streak[h] >= max_failures else [False, True]
                for h in range(len(handlers))
            ]
            successors = []
            for failures in itertools.product(*outcomes):
                after = list(remaining)
                for h, job in enumerate(assignment):
                    if job >= 0 and not failures[h]:
                        after[job] -= 1
                next_streak = tuple(
                    streak[h] + 1 if failed else 0 for h, failed in enumerate(failures)
                )
                successors.append((t + 1, canonical(tuple(after))[0], next_streak))
            if all(solve(*state) for state in successors):
                strategy[(t, remaining, streak)] = assignment
                return record(t, remaining, streak, True)
        return record(t, remaining, streak, False)

    work = tuple(j["work"] for j in jobs) if remaining is None else tuple(remaining)
    failures = (0,) * len(handlers) if streak is None else tuple(streak)
    if (
        type(start) is not int
        or not 0 <= start <= horizon
        or len(work) != len(jobs)
        or len(failures) != len(handlers)
        or any(
            type(value) is not int or not 0 <= value <= j["work"]
            for value, j in zip(work, jobs)
        )
        or any(type(value) is not int or value < 0 for value in failures)
    ):
        raise ValueError("Invalid current debt, clock or handler failure state")
    initial = (start, work, failures)
    representative, origin = canonical(work)
    safe = solve(start, representative, failures)
    if safe and any(work):
        assignment = strategy[(start, representative, failures)]
        strategy[initial] = tuple(
            origin[index] if index >= 0 else -1 for index in assignment
        )
    return safe, solve.cache_info().currsize, strategy


def generate(rng, count):
    for index in range(count):
        horizon = rng.randint(3, 7)
        handlers = ["audit", "notify"]
        jobs = []
        for i in range(rng.randint(1, 5)):
            jobs.append(
                {
                    "id": str(i),
                    "work": rng.randint(1, 2),
                    "deadline": rng.randint(2, horizon),
                    "handlers": rng.sample(handlers, rng.randint(1, 2)),
                    "predecessors": [str(i - 1)] if i and rng.random() < 0.25 else [],
                }
            )
        split = rng.randrange(len(jobs))
        yield {
            "id": str(index),
            "family": f"jobs-{len(jobs)}",
            "horizon": horizon,
            "handlers": handlers,
            "jobs": jobs,
            "existing_count": split,
            "max_consecutive_failures": rng.randint(0, 1),
        }


def run_case(case, method):
    jobs = case["jobs"]
    horizon = case["horizon"]
    handlers = case["handlers"]
    maximum = case["max_consecutive_failures"]
    if case.get("base_permit", True) is not True:
        return {"admitted": False, "states": 0}
    if method == "monitor":
        return {"admitted": True, "states": 0}
    if method in ("individual_edf", "no_global_debt"):
        selected = (
            jobs[case["existing_count"] :] if method == "no_global_debt" else jobs
        )
        outcomes = [
            winning([{**j, "predecessors": []}], horizon, handlers, maximum)
            for j in selected
        ]
        return {
            "admitted": all(x[0] for x in outcomes),
            "states": sum(x[1] for x in outcomes),
        }
    if method == "round_later":
        jobs = [
            {**j, "deadline": min(horizon, ((j["deadline"] + 1) // 2) * 2)}
            for j in jobs
        ]
    safe, states, _ = winning(
        jobs,
        horizon,
        handlers,
        maximum,
        bucket=2
        if method in ("obligationshield", "no_antichain", "no_quotient")
        else 1,
        optimistic=method == "average_failures",
        quotient=method in ("obligationshield", "quotient_game", "no_antichain"),
        antichains=method in ("obligationshield", "no_quotient"),
    )
    return {"admitted": safe, "states": states}


def oracle(case):
    jobs = case["jobs"]
    horizon = case["horizon"]
    handlers = case["handlers"]
    maximum = case["max_consecutive_failures"]
    positions = {j["id"]: i for i, j in enumerate(jobs)}

    def visit(t, work, streak):
        if any(work[i] and t >= j["deadline"] for i, j in enumerate(jobs)):
            return False
        if not any(work):
            return True
        if t == horizon:
            return False
        ready = [
            i
            for i, j in enumerate(jobs)
            if work[i]
            and all(not work[positions[p]] for p in j.get("predecessors", []))
        ]
        commands = []
        for handler in handlers:
            commands.append(
                [None] + [i for i in ready if handler in jobs[i]["handlers"]]
            )
        for command in itertools.product(*commands):
            if any(command.count(i) > work[i] for i in ready):
                continue
            safe = True
            for fail in itertools.product([0, 1], repeat=len(handlers)):
                if any(fail[h] and streak[h] >= maximum for h in range(len(handlers))):
                    continue
                next_work = list(work)
                for h, i in enumerate(command):
                    if i is not None and not fail[h]:
                        next_work[i] -= 1
                if not cached(
                    t + 1,
                    tuple(next_work),
                    tuple(
                        streak[h] + 1 if fail[h] else 0 for h in range(len(handlers))
                    ),
                ):
                    safe = False
                    break
            if safe:
                return True
        return False

    cached = functools.lru_cache(None)(visit)
    return cached(0, tuple(j["work"] for j in jobs), (0,) * len(handlers))


def score(case, result):
    feasible = oracle(case)
    admitted = result["admitted"]
    return {
        "admission": int(admitted) if case.get("base_permit", True) else None,
        "false_safe": int(not feasible) if admitted else None,
        "obligation_violation": result.get("obligation_violation")
        if admitted
        else None,
        "false_denial": int(not admitted)
        if feasible and case.get("base_permit", True)
        else None,
        "exact_feasible": int(feasible),
        "visited_states": result["states"],
        "legal_effects": int(admitted and feasible),
        "debt_bytes": len(json.dumps(case["jobs"]).encode()),
    }
