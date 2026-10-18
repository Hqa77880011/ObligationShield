# ObligationShield

Implementation of **Finite-game admission for joint usage-control obligations**.

Implements the finite-horizon winning-region recursion with existential scheduling and universal legal handler failures. It preserves job multiplicity, predecessor order, shared handler capacity and absolute deadlines. An independent explicit game interpreter computes evaluation labels.

## Install

Use Python 3.11 or newer. Create and activate a virtual environment, then install the package:

```bash
git clone https://github.com/Hqa77880011/ObligationShield.git
cd ObligationShield
python -m venv .venv
```

Activate with `source .venv/bin/activate` on Linux/macOS or `.venv\Scripts\Activate.ps1` in PowerShell.

```bash
python -m pip install -e .
```

## Prepare data

```bash
python -m obligationshield prepare --count 200 --seed 17 --output data/workload.jsonl
```

The generator constructs finite workloads from the formal problem. It writes one JSON object per line. Import recorded or independently constructed cases with the same schema.

`jobs` contains distinct IDs, positive integer work, absolute deadline ticks, eligible handlers and predecessor IDs. `horizon` is fixed for the episode. Each handler executes at most one work unit per tick; `max_consecutive_failures` defines its failure automaton. `existing_count` partitions old and newly requested debt.

## Admission-only comparisons

```bash
python -m obligationshield run --data data/workload.jsonl --output runs/main
python -m obligationshield suite --data data/workload.jsonl --methods obligationshield exact_game --output runs/comparison
```

Omit `--methods` in `suite` to include every comparison method and ablation.

`obligationshield` uses conservative earlier deadline buckets; `exact_game` retains exact deadlines; `individual_edf` checks each job independently; `monitor` admits without feasibility; `no_global_debt` omits accepted debt; `average_failures` removes worst-case failures; `round_later` rounds deadlines in the unsafe direction.

These are algorithmic workloads without learned parameters. `--count` controls scenario count and `--seed` controls generation. Repeat with independent seeds for comparisons.

## Evaluate and visualize

Each method writes `records.jsonl` with per-case outputs and measurements, plus `metrics.json` with counts, means, sample standard deviations and quantiles. Rates are fractions. Conditional metrics exclude cases outside their denominator. Timers cover method execution; independent scoring is outside this timer.

Admission, false-safe admission, false denial conditional on exact feasibility, state count, debt serialization bytes and measured solver runtime. The legacy `obligation_violation` field is an independent oracle's infeasibility label conditional on admission, not a measured handler execution violation. Use the runtime below for executed actions and receipts.

```bash
python -m obligationshield plot --inputs runs/comparison/obligationshield runs/comparison/exact_game --output figures
```

Plotting creates `summary.csv` and one PNG per numeric metric. RSS includes the Python runtime and imported libraries. Output bytes measure JSON serialization size.

## Implementation conventions

Jobs require authenticated completion in deployment; the finite solver models a successful handler step as the trusted completion event. The implementation covers finite DAG jobs and bounded consecutive failures. The exact solver memoizes full debt states; earlier buckets provide a conservative approximation. Resource-creating and canceling obligations need an explicit transition model and are not encoded by this job schema.

## Durable execution of the winning strategy

`obligationshield.runtime` binds the game to SQLite admission/debt/outbox state and an explicit executor. `BEGIN IMMEDIATE` serializes one resource pool: an admitted request commits its new debt and one release record together. Request IDs are idempotent and cannot be reused with different arguments. Deadlines are absolute from the episode's durable authorization clock; restarts or late releases do not extend them.

The runtime solves from the current clock, remaining debt and failure streaks. Its stored winning control becomes actual handler commands. After further admission it solves the augmented debt again. Each handler produces an authenticated outcome for every logical tick, including an idle health probe; this keeps the observed failure automaton identical to the game. Each handler has at most one work unit per tick, and predecessors must have confirmed completion before dispatch.

Run the hand-defined two-audit example (a mechanism check, not measured deployment evidence):

```bash
python -m obligationshield.runtime --case examples/two_audits.json --ledger state.sqlite --executor finite --effects effects.sqlite --bucket 1 --output execution.json
```

The explicit finite executor commits local effects and receipts in a separate SQLite database under the supplied failure trace. It is a runnable state machine, with durable one-time release/work effects keyed by command ID. It does not represent a real audit server. Repeating the command with the same inputs/database files reconciles outstanding commands without creating another release or another work effect. Use new databases for a new episode.

The runtime accepts one JSON episode with this schema:

```json
{
  "id": "two-audits", "horizon": 4, "handlers": ["audit"],
  "max_consecutive_failures": 1, "existing_count": 0,
  "base_permit": true, "release": {"object": "example-record"},
  "jobs": [
    {"id": "a", "work": 1, "deadline": 4, "handlers": ["audit"], "predecessors": []},
    {"id": "b", "work": 1, "deadline": 4, "handlers": ["audit"], "predecessors": []}
  ],
  "execution_model": {"kind": "finite", "failures": {"0": ["audit"], "2": ["audit"]}}
}
```

`work`/`deadline` are positive integers and tick indices start at zero. A deadline of four allows work in slots 0, 1, 2, 3. Each handler appears once in `handlers`; failure-map keys are slot indices and values are failing handlers. The first `existing_count` jobs import already accepted debt; `Ledger.admit` submits subsequent requests while retaining all previous debt. Optional job fields such as a handler `payload` pass through to the selected command's `obligation`. A work unit is one independently countable discharge step; do not represent an indivisible once-only effect with multiple arbitrary units.

An external trusted executor is selected explicitly:

```bash
python -m obligationshield.runtime --case episode.json --ledger state.sqlite --executor application_adapter:create_executor --output execution.json
```

`create_executor(case)` supplies four methods: `lookup(command)` returns a previously committed outcome or `None`; `execute(command)` invokes/reconciles the effect and returns its receipt or `None` when unknown; `verify(receipt)` authenticates a receipt against the trusted handler/effect store; `close()` releases resources. Configure real handler endpoints/credentials inside that application adapter. An untrusted JSON success flag is not an authenticated receipt.

Commands and receipts are JSON-serializable. A release command contains `id`, `kind: "release"`, `request`, `authorized_tick`, and `payload`. A handler command contains `id`, `kind: "handler"`, `tick`, `handler`, `job`, `origin`, full `obligation`, `work_units` (one, or zero for an idle probe), and `strategy`. Its receipt contains the exact `command`, Boolean `success`, Boolean `effect_committed`, and any adapter authentication material. `success: false` must establish that no effect occurred; an unknown outcome returns `None`, never a guessed failure. A successful work/release receipt must confirm effect commitment, while a successful idle probe has `effect_committed: false`.

The adapter must enforce persistent idempotency by full command ID and argument binding, atomic recording of effect plus its receipt, and trusted lookup after crashes. The ledger records dispatch before invocation, checks release validity under the pool transaction, and reconciles a committed effect after a crash. This contract is necessary for one-time physical effects; SQLite cannot roll back an external server. Tick completion waits for all handler receipts. A missing receipt retains debt and blocks new admission/release; duplicate verified receipts do not discharge twice. A failure run beyond the declared bound freezes new releases and uses best-effort EDF for already accepted debt.

The provided clock is logical. An application adapter must bind these slots and authenticated availability probes to its real timing contract before making wall-clock deadline claims. The finite model does not add XACML parsing, primary/fallback branches, cancellation, certified quotient/antichain compression, or hardware measurements. Admission-only benchmarks and finite execution records therefore do not establish those paper-wide deployment metrics.


## Uncertainty and paired comparisons

```bash
python -m obligationshield.statistics --records runs/main/obligationshield/records.jsonl --output results/intervals.json
```

Supply --reference with a matched record file for paired differences. Resampling uses independent case IDs, or explicit cluster IDs when provided. Repeated observations from one source unit must share cluster. Zero-event bounds refer to an event in an independent cluster.

## Fixed reproduction setting

Finite DAG admission plus persisted winning-control execution of the hand-defined two-audit episode, exact deadlines and declared bounded failures.

The checked-in entry point fixes data seeds, methods, budgets and output paths. Inspect its commands without starting any computation:

```bash
python reproduce.py --plan
```

Remove `--plan` to execute the registered pipeline in a fresh output directory. The entry point calls the existing implementation; it does not insert paper results. Installation uses the package instructions above.
