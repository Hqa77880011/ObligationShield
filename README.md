# ObligationShield

Implementation of **Finite-game admission for joint usage-control obligations**.

## Installation

Requires Python `>=3.11`. Run from the repository root in an activated environment.

```bash
python -m pip install -e .
```

Inspection environment: Python 3.13.5; numpy 2.1.3, matplotlib 3.10.0. Checks: Python syntax, configuration parsing and CLI/source argument matching. Training and full evaluation were not run.

## Data

The generator constructs finite workloads from the formal problem. It writes one JSON object per line. Import recorded or independently constructed cases with the same schema.

The bundled generator writes synthetic finite-model scenarios as JSONL. Fix the seed and keep the generated input for paired comparisons.

```bash
python -m obligationshield prepare --count 200 --seed 17 --output data/generated.jsonl
```

## Execution and evaluation

```bash
python -m obligationshield run --data data/generated.jsonl --output runs/main
```

Execute the included two-audit finite example with a durable ledger:

```bash
python -m obligationshield.runtime --case examples/two_audits.json --ledger runs/ledger.sqlite --executor finite --effects runs/effects.sqlite --bucket 1 --output runs/execution.json
```

## Comparisons and ablations

```bash
python -m obligationshield suite --data data/generated.jsonl --output runs/comparison
```

Use `--methods` to select: `obligationshield`, `exact_game`, `individual_edf`, `monitor`, `no_global_debt`, `average_failures`, `round_later`.

## Outputs

`runs/main/obligationshield/records.jsonl` stores per-case results; `metrics.json` stores aggregate measurements. Comparison outputs use one directory per method.

```bash
python -m obligationshield plot --inputs runs/comparison/obligationshield --output figures
```

Plotting writes `figures/summary.csv` and metric PNGs. Statistical intervals can be computed from a retained record file:

```bash
python -m obligationshield.statistics --records runs/main/obligationshield/records.jsonl --output results/intervals.json
```
