# ObligationShield implementation

Implementation of **Finite-game admission for joint usage-control obligations**.

The existing finite-model algorithms are retained. This revision adds base-policy gating, correctly conditioned safety rates, sufficient isolated-job quotienting with multiplicity/origin preservation, same-clock/failure-state antichain pruning, and receipt-based observed obligation metrics. These are implementation and functional-validation artifacts; they are not the raw experimental code or evidence behind the manuscript's reported numbers.

## Installation

Requires Python >=3.11. From the repository root in an activated environment:

```bash
python -m pip install -e .
python -m unittest discover -s tests
```

Installed validation environment: Windows, Python 3.13.5, numpy 2.1.3, scipy 1.15.3, matplotlib 3.10.0, psutil 7.1.0. Existing CI installs dependencies and runs the regression checks on Python 3.11.

## Data

The bundled generator produces synthetic finite-model scenarios for functional checks. It does not download a native benchmark, reproduce manuscript result tables or fit any parameters. Retain one generated input for paired comparisons:

```bash
python -m obligationshield prepare --count 6 --seed 17 --output data/generated.jsonl
```

Each UTF-8 JSONL line has a unique `id`, optional `family`, and `cluster` identifying the actual independent policy/history family. The generator records `generation_seed` and conservatively clusters repeated examples by family. Imported independent data should supply its reviewed cluster IDs. Input fields are:

`jobs`: distinct IDs, positive integer `work`, absolute integer `deadline`, eligible `handlers` and optional `predecessors`; `horizon`, `handlers`, `max_consecutive_failures` define the shared finite environment. `existing_count` separates prior debt. Optional explicit `base_permit=False` always blocks admission. Runtime episodes additionally supply `release` and a declared `execution_model` (see examples/two_audits.json).

`core.generate` is an executable complete schema example. Use the same schema for reviewed recorded cases; keep native, mutation-derived and synthetic strata separate. No private data, manuscript, pretrained weights or original server logs are distributed. The algorithms use explicit policy/configuration inputs rather than learned models, and do not tune on test labels.

## Execution

```bash
python -m obligationshield run --data data/generated.jsonl --output runs/main
```

Run the existing hand-defined two-audit execution, including durable debt/outbox admission and receipt reconciliation:

```bash
python -m obligationshield.runtime --case examples/two_audits.json --ledger runs/ledger.sqlite --executor finite --effects runs/effects.sqlite --bucket 1 --output runs/execution.json
```

Repeating this exact runtime command resumes the same episode and returns existing receipts. A different episode/model requires fresh database paths. Admission-suite `obligationshield` uses conservative bucket 2; this runtime example explicitly uses exact deadline bucket 1. Both preserve the same job semantics.

## Evaluation

```bash
python -m obligationshield evaluate --records runs/main/obligationshield/records.jsonl --output runs/evaluated.json
```

`admission` uses base-permitted requests. `false_safe` uses admitted states; `false_denial` uses exact-winning base-permitted states. Static losing admission is not an observed missed obligation: `obligation_violation` remains null without an execution. The runtime computes access- and job-level observed misses from persisted debt and confirmed receipts, retaining unresolved execution as undefined. `exact_feasible` and `visited_states` describe the finite game, not a measured server job campaign.

Rates are fractions in [0,1]. `null` means an inapplicable or unresolved denominator, not zero failures. `metrics.json` gives conditional per-case means, SD and quantiles; rate fields with explicit `metric_counts` also contain pooled `micro` numerator/denominator/rate. Whole-case `latency_ms` includes local construction and audits; stage metrics identify the narrower compilation/runtime path. `rss_mib` is a sampled resident value, not a measured peak. Throughput is local finite-model useful effects per whole-case wall second, not the manuscript's server throughput.

The same `evaluate` command accepts independently recorded JSONL with `id`, `method`, `cluster`, numerical-or-null `metrics`, and optional `metric_counts` mapping each rate name to `[numerator, denominator]`. Thus backend-only paper measurements can be aggregated when genuinely collected; missing lock waits, network latency, maintenance, attacker recovery or native task outcomes are not assigned invented values.

## Comparisons and ablations

```bash
python -m obligationshield suite --data data/generated.jsonl --output runs/comparison
python -m obligationshield.statistics --records runs/comparison/obligationshield/records.jsonl --reference runs/comparison/exact_game/records.jsonl --resamples 10000 --seed 17 --primary false_safe --output runs/paired.json
```

Select a subset with `--methods`. Implemented configurations: `obligationshield`, `exact_game`, `quotient_game`, `no_antichain`, `no_quotient`, `individual_edf`, `monitor`, `no_global_debt`, `average_failures`, `round_later`. Deliberately lossy, unbound, feasibility-disabled and race variants are sandbox diagnostic controls, not safe deployments. The comparison implementations use this repository's declared finite semantics; they are not unmodified upstream systems.

Statistics first aggregate within each independent family and then bootstrap whole families. Paired analysis requires identical case IDs and excludes metrics undefined on either side. One eligible family yields no bootstrap interval. The zero-event bound concerns an event in an independent eligible cluster, not an iid per-request rate. McNemar is used only for independent single-record binary pairs; other paired summaries use Wilcoxon. Holm correction applies only to explicitly selected `--primary` endpoints. Small synthetic examples are not a source of experimental confidence intervals.

## Outputs and visualizations

```bash
python -m obligationshield plot --inputs runs/comparison/obligationshield runs/comparison/exact_game --metrics false_safe latency_ms --output runs/figures
```

Each method directory contains `records.jsonl` (actual outcomes and conditional metrics), `metrics.json`, and `config.json` (command, environment and seeds). Plotting writes `summary.csv` plus selected metric PNGs; undefined metrics produce no misleading empty plot. All paths are configurable. Choose fresh output directories for reruns; generation/evaluation do not silently overwrite retained inputs or records.

## Paper-to-code map

| Paper module or metric | Code entry | Configuration / command |
|---|---|---|
| Shared debt game: exists control / forall failures | `core.winning; core.oracle` | exact_game; horizon and failure bound |
| Behavior-preserving sufficient quotient | `core.winning(quotient=True)` | quotient_game; identical isolated jobs |
| Hardness antichains and conservative buckets | `core.winning(antichains=True)` | obligationshield; deadlines round earlier to bucket 2 |
| Atomic debt/outbox and authenticated receipts | `runtime.Ledger; FiniteExecutor; drive` | python -m obligationshield.runtime |
| Admission and observed obligation violations | `core.score; runtime.main` | admission records / execution.json metrics |
| Aggregation, paired intervals and visualization | `cli.summarize; statistics.analyze; cli.plot` | evaluate / statistics / plot |

## Validation and implementation scope

Validated locally: editable installation, syntax/import and regression checks, six seed-17 cases through every suite configuration, retained-record re-evaluation, 10,000-resample paired analysis, selected metric PNG/CSV output, and wheel/source-distribution builds. No full paper campaign was run. Local functional records are retained under `runs/smoke/` (Git-ignored).

Regression checks cover hand-computable rates and eligible denominators, the algorithm's safety boundary, and applicable replay/serialization paths. The documented small-data preparation, execution, suite, evaluation, statistics and plotting commands are the validation entry points. No complete training or large experimental campaign is required for these checks.

Quotienting is deliberately sufficient: only isolated jobs identical in every non-ID field can exchange origins. Other DAG jobs retain identity. Antichains apply to componentwise remaining work within the fixed monotone job/failure model; no cancellation or resource-creating transitions are admitted. The runtime uses SQLite and explicit logical-tick executors; arbitrary fallback branch contracts, PostgreSQL server performance and external authenticated handlers are not implemented. A handler plugin must supply execute, lookup, verify and close; its trust contract requires separate validation.

The source retains its existing MIT license. Data and external systems remain subject to their own licenses and access rules.
