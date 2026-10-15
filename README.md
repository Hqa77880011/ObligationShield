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

## Execute and compare

```bash
python -m obligationshield run --data data/workload.jsonl --output runs/main
python -m obligationshield suite --data data/workload.jsonl --methods obligationshield exact_game --output runs/comparison
```

Omit `--methods` in `suite` to include every comparison method and ablation.

`obligationshield` uses conservative earlier deadline buckets; `exact_game` retains exact deadlines; `individual_edf` checks each job independently; `monitor` admits without feasibility; `no_global_debt` omits accepted debt; `average_failures` removes worst-case failures; `round_later` rounds deadlines in the unsafe direction.

These are algorithmic workloads without learned parameters. `--count` controls scenario count and `--seed` controls generation. Repeat with independent seeds for comparisons.

## Evaluate and visualize

Each method writes `records.jsonl` with per-case outputs and measurements, plus `metrics.json` with counts, means, sample standard deviations and quantiles. Rates are fractions. Conditional metrics exclude cases outside their denominator. Timers cover method execution; independent scoring is outside this timer.

Admission, false-safe admission, obligation violation conditional on admission, false denial conditional on exact feasibility, state count, debt serialization bytes and measured runtime.

```bash
python -m obligationshield plot --inputs runs/comparison/obligationshield runs/comparison/exact_game --output figures
```

Plotting creates `summary.csv` and one PNG per numeric metric. RSS includes the Python runtime and imported libraries. Output bytes measure JSON serialization size.

## Implementation conventions

Jobs require authenticated completion in deployment; the finite solver models a successful handler step as the trusted completion event. The implementation covers finite DAG jobs and bounded consecutive failures. The exact solver memoizes full debt states; earlier buckets provide a conservative approximation. Resource-creating and canceling obligations need an explicit transition model and are not encoded by this job schema.


## Uncertainty and paired comparisons

```bash
python -m obligationshield.statistics --records runs/main/obligationshield/records.jsonl --output results/intervals.json
```

Supply --reference with a matched record file for paired differences. Resampling uses independent case IDs, or explicit cluster IDs when provided. Repeated observations from one source unit must share cluster. Zero-event bounds refer to an event in an independent cluster.
