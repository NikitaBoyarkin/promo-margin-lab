# promo-margin-lab

How much does a promo rouble actually earn? A measurement-and-allocation lab for
offline grocery trade spend: counterfactual lift, a cannibalization ledger in
roubles, incremental margin, and a budget-constrained allocation checked against
a known ground truth.

> **Status: W0–W9 complete.** Data, panel, counterfactual, ledger + P&L, Superset,
> experiment design, response model, allocation, Spark parity and the narrative are
> in place. The live Superset instance runs locally without Docker (Python 3.11 +
> pinned requirements); its export bundle is committed at
> `superset/export/superset-assets.zip`.

## Result in 60 seconds

| | |
|---|---:|
| Incremental revenue | **+70.5 m ₽** |
| Incremental contribution margin | **−17.6 m ₽** |
| Waves that lose money | **95.3%** of 9,053 |
| Breakeven depth (by category) | **2.0–20.5%** vs actual 25.4% |
| Naive vs forecast lift bias | **−15.6%** vs **−0.9%** |

**Decision:** cap depth at the category breakeven and spend only where expected
margin is positive — on a tight budget that earns **+222,301 ₽** against
**+147,472 ₽** for top-15% and **+21,460 ₽** for random, while blanket 15% loses
**−772,224 ₽**. Full reasoning: [`docs/decision-memo.md`](docs/decision-memo.md).

## Why this exists

A promo changes units, revenue, margin and neighbouring SKUs at the same time.
"Revenue grew 18%" is not an answer: the discount is a cost, part of the lift is
pulled forward from later weeks, part is stolen from the same category, and the
margin line can move the opposite way to the revenue line. This lab separates
those components, prices them, and then decides where the next rouble of trade
spend should go.

The data are synthetic **on purpose**: the generating process stores the true
baseline, lift, pantry drag, cannibalization and halo per cell, so an estimator
can be scored against the answer key instead of against a story.

## Quick start

```bash
uv sync
uv run python run.py --stage all          # 561,600 cells, seed 42
uv run python run.py --stage all --fast   # CI profile: 9,360 cells
uv run pytest -q
```

Stages: `data`, `panel`, `baseline`, `ledger`, `all`. Outputs:
`data/panel/store_sku_week.parquet`, `data/truth/effects.parquet`,
`reports/w0_summary.json`, `reports/baseline.json`, `reports/ledger.json`,
`reports/margin.json`. The `--fast` profile writes `*_fast` siblings and never
overwrites the headline artefacts.

## Current numbers (descriptive, not claims)

| | |
|---|---|
| cells | 561,600 (120 stores × 60 SKUs × 78 weeks) |
| promo cells | 37,016 (**6.6%**) |
| mean depth | 25.5% (range 5–40%) |
| units | 20.58M sold, 0.47% returned |
| revenue | 1.97 bn ₽ (synthetic) |
| contribution margin | 492 m ₽ |

These describe the dataset, not a finding.

## W2 finding: the naive baseline hides a fifth of the lift

All three estimators predict what each store-SKU-week would have sold **without a
promo**; lift is `actual - counterfactual`. Scored against the answer key on the
37,016 promoted cells (`seed = 42`):

| estimator | baseline WAPE | lift bias | per-category bias range |
|---|---:|---:|---|
| naive 4-week mean | 12.1% | **−15.6%** | −38.6% … −0.9% |
| log-linear forecast | **7.7%** | **−0.9%** | −5.3% … +2.0% |
| matched-control DiD | 10.3% | −19.6% | — |

The naive baseline *understates* lift by a sixth: a 4-week pre-period mean lags
the demand dip that triggered the promo, so it sits above the true counterfactual.
The sign matters — this is not the familiar "promo looks better than it is".

Two more honest results:

- **Matched control does not rescue it.** DiD against non-promoted peers in the
  same SKU and format removes a *common* trend; this confounder is
  store-SKU-specific, so DiD inherits the pre-level bias and adds variance.
- **A single cell cannot resolve a small effect.** Placebo lift (non-promo cells,
  no promo within ±2 weeks) has a median of +0.2% for the forecast, but a 90%
  interval of roughly −16% … +22%. Per-cell lift is a noisy object; detecting a
  2% effect needs a cluster design, which is W5.

## W3 finding: growth in units, destruction in margin

The ledger is built per **wave** — one store, one week, one category — so a
non-promo cell is attributed exactly once. Every bucket is valued at its own
realised price; supplier funding is added back explicitly.

| bucket | units | vs oracle |
|---|---:|---:|
| own lift (promoted cells) | 959,699 | −0.9% |
| post-promo window (+1…3 weeks) | +28,344 | — (bucket ≈ 0) |
| same-category other SKUs | −206,780 | −6.0% |
| complementary category | +215,160 | +5.7% |
| **net** | **996,423** | **+1.5%** |

So halo more than offsets cannibalization: net lift is **3.8% higher** than own
lift. And yet, on the money side (`reports/margin.json`, 9,053 waves):

| | |
|---|---:|
| incremental revenue | **+70.5 m ₽** |
| discount cost | 60.0 m ₽ |
| supplier funding | +15.6 m ₽ |
| incremental profit | **−17.6 m ₽** (oracle −18.0 m) |
| waves with negative profit | **95.3%** (oracle 96.2%) |
| median wave profit | −1,542 ₽ |

The mechanism is the accounting that a "ROI = lift × margin" slide skips: the
units that would have sold at full price also lose margin when they sell at a
discount. Volume can grow while profit falls.

**Depth has a ceiling.** Fitted response `m(d) = A·(1 − e^(−k·d))` (R² 0.93–0.97
on depth bins) gives the depth at which incremental contribution margin hits zero:

| category | CM | supplier funding | breakeven depth |
|---|---:|---:|---:|
| non-food | 35% | 26% | 20.5% |
| bakery / grocery | 30% / 22% | 28% / 24% | 10.0% |
| drinks | 26% | 25% | 4.5% |
| dairy / frozen | 12% / 18% | 27% / 25% | 2.5% / 2.0% |

Actual mean depth is **25.4%**, i.e. above the ceiling for every category but
non-food. That is the decision the project exists to produce.

Two honesty notes. Each bucket is a *net effect on a cell set*, not an isolated
mechanism — the within-category bucket is cannibalization net of any halo inside
the category. And the `network_shift` diagnostic (same SKU, other stores) is
excluded from net: cross-format traffic cancels across the chain, so what is left
there is baseline error, not a leak.

## W4: the dashboard is SQL, not a screenshot

Four mart queries in `sql/marts/` produce every number on the dashboard, against
`data/marts/promo.db` (SQLite, mounted read-only into the container):

| mart | grain | feeds |
|---|---|---|
| `01_promo_pnl.sql` | category | revenue, discount, funding, profit, share unprofitable |
| `02_model_quality.sql` | estimator | WAPE, lift bias, placebo interval |
| `03_guardrails.sql` | week | weekly profit, profit per revenue, share negative |
| `04_breakeven_vs_actual.sql` | category | actual depth vs breakeven ceiling |

The chart layer computes nothing: `tests/test_marts.py` pins the mart totals to
`reports/ledger.json` (profit within 1 ₽), so a drifting dashboard fails CI.

Delivered: `superset/docker-compose.yml`, `superset/superset_config.py`,
`superset/dashboards.md` (3 dashboards with chart specs), and a self-contained
render at `reports/superset/dashboard.html` — labelled *static render*, generated
from the same SQL, with the live stack named in its footer.

**The live instance is verified.** Docker Hub is unreachable from this machine
(`TLS handshake timeout` through Docker Desktop's proxy), so Superset runs from a
Python 3.11 venv instead: `superset/bootstrap_local.sh` installs the pinned
requirements, upgrades the metadata DB, creates the admin and serves on `:8088`.
`superset/provision.py` registers the mart database, four datasets, four charts
and a dashboard, then exports them to `superset/export/superset-assets.zip`.

Proof it is not just config: SQL Lab on the live instance returns
`COUNT(*)=9053`, `SUM(net_profit)=−17 584 046.0`, `SUM(revenue_delta)=70 502 772.5`
— the same numbers as `reports/margin.json`. The Docker compose stack stays in
the repo as the alternative path.

## W5: a design that survives its own simulation

Cluster RCT: 120 stores, 60 per arm, 8 weeks, primary metric incremental
contribution margin per store-week. Pre-registration and threats:
[`docs/experiment-design.md`](docs/experiment-design.md).

| | |
|---|---:|
| ICC (between-store share of variance) | 0.138 |
| MDE at α=0.05, power 0.80 | **612 ₽ / store-week** (0.29% of weekly revenue) |
| False-positive rate, 1 000 null splits | **4.7%** |
| Power at the MDE | **77.8%** |
| CI coverage of the injected effect | **95.0%** |

The design check that mattered: a **common switch week** (classic switchback)
rejects **100% of the time under the null** — week effects absorb the treatment,
and the promo calendar leaks in as an effect. Randomising the phase per store and
demeaning store and week fixes it: 4.0% false positives, 100% power at the MDE,
and an injected carryover of 0.5 recovered as **0.49**. Which is why the cluster
RCT is primary and the switchback is the fallback for a finer MDE.

## W6: a great ranking, a losing decision

The model predicts incremental CM per promoted cell (store × SKU × week) on a
chronological holdout of the last 16 weeks. Features: depth, mechanic, margin,
supplier funding, price, store, SKU, format, seasonality and promo-free history.

| | |
|---|---:|
| R² / MAE | **0.925** / 89.7 ₽ per cell |
| Qini coefficient (bootstrap CI) | **0.963** [0.958; 0.967] |
| Spearman(score, realised effect) | 0.95 |
| Calibration slope / bias | 1.10 / +25.9 ₽ |

Now the decision, at a 20% capacity of 1 538 cells out of 7 691:

| policy | cells used | total ₽ |
|---|---:|---:|
| random | 1 538 | −812 833 |
| **qini_rank** (top-k by score) | 1 538 | **−55 396** |
| **threshold** (score > 0) | 285 | **+54 361** |
| none | 0 | 0 |
| oracle threshold | 446 | +98 280 |
| oracle top-k (budget filled) | 1 538 | −2 356 |

The ranking is nearly perfect and the policy it implies still loses 55 thousand
roubles: Qini measures order, not level. The calibrated threshold earns +54 k by
spending on **3.7%** of the cells — and even the oracle loses money if it is
forced to fill the budget. The hypothesis stated in the PRD holds: threshold
minus rank = **+109 757 ₽**, bootstrap CI [97 505; 121 569].

One caveat, stated because it is easy to hide: a Qini of 0.96 is high partly
because the data-generating process is smooth and the features include depth and
margin. On real scanner data this number will be lower; the decision rule, not
the coefficient, is the transferable part.

## W7: the budget is not the constraint, the ceiling is

Allocation instance: one planning week, 4 756 candidates after the spacing rule
(no promo on the SKU in the previous 6 weeks), depth grid 5–40%, depth capped at
the category breakeven, budget = a share of what blanket 15% would cost.

| tight budget (450.7 k ₽, 10% of blanket) | profit ₽ | spend ₽ |
|---|---:|---:|
| random 15% | 21 460 | 450 652 |
| top profit-per-rouble at 15% | 147 472 | 450 646 |
| **optimised (depth + selection)** | **222 301** | 450 620 |

| loose budget (2.25 m ₽, 50%) | profit ₽ | spend ₽ |
|---|---:|---:|
| random 15% | 118 322 | 2 038 474 |
| top profit-per-rouble at 15% | 225 836 | 1 271 923 |
| **optimised** | **223 645** | **486 955** |

Blanket 15% across all candidates loses **−772 224 ₽** on 4.51 m of spend
(−0.17 ₽ per rouble). The optimised policy earns **+0.46 ₽ per rouble**, i.e.
+995 869 ₽ versus blanket while spending 4.0 m less.

Two results worth saying out loud:

- **The loose budget is not binding.** At 2.25 m the optimiser stops at 487 k and
  leaves 1.77 m unspent: after the breakeven cap, there are only ~1.8 k cells
  with positive expected margin. Spending the rest would buy losses.
- **Depth choice is where the money is.** At the same 450 k budget, choosing the
  depth adds 75 k ₽ over a fixed 15% depth (+51%), because the cap is 2–20%
  depending on the category and 15% is already above it for four of six.

Constraints checked: budget never exceeded; spacing honoured (test asserts no
candidate had a promo in the previous 6 weeks); depths inside the cap; greedy
matches brute force on a 5-cell instance (gap 0%). Under a ±15% shock to the
response multiplier, the selection changes by 12% / 9% and profit moves to
150 k / 302 k — the decision is sensitive to the curve, which is why W5 exists.

**Not modelled:** supplier funding tiers. The dataset has a flat per-SKU funding
rate, so a tiered contract would be an invented assumption, not a result. Stated
as out of scope rather than simulated.

## W8: the same numbers from two engines

Spark 4.2 in `local[4]` with Java 25. The job reads the panel, broadcasts a
six-row category dimension, computes `lag` and a rolling-4 window per store-SKU,
and aggregates to store-week.

| | |
|---|---:|
| stores compared | 10 |
| store-week rows compared | 780 |
| max absolute difference, 6 metrics | **0.0** |
| rows present on one side only | 0 |
| physical plan | `BroadcastHashJoin` + `Window` + `Exchange` |

Scale: a generated 2 000 × 100 × 83 cube — **16.6 M rows** — materialised to
parquet partitioned by week and read back in **~14 s** on four local threads.

Honest scope: `local[*]` is one JVM with four threads. The runtime is evidence
that the plan executes at that size, not a cluster throughput claim, and the
scale run uses generated rows — the parity claim is the one made on the real
panel.

## Layout

```
run.py                 # --stage {data,panel,baseline,all} [--fast]
src/config.py          # every knob in one frozen Config
src/dgp.py             # generator + the eight-component answer key
src/panel.py           # as-of price join, returns, money columns, validations
src/baseline.py        # naive / forecast / matched control + placebo scoring
src/ledger.py          # wave ledger, promo P&L, response curve, breakeven
src/marts.py           # SQLite mart database + mart runner
src/experiment.py      # ICC, MDE, cluster RCT and switchback simulation
src/response.py        # response model, Qini/calibration, policy evaluation
src/allocation.py      # budget-constrained depth and cell selection
src/spark_job.py       # PySpark parity + scale evidence
src/render.py          # static render of the Superset dashboard
src/paths.py           # paths, deterministic hashing, JSON/parquet writers
tests/                 # 83 tests: grain, identity, as-of, truth isolation, W2–W8 claims
sql/marts/*.sql        # four queries the dashboard is built from
superset/              # compose, config, dashboard spec, honest status
docs/data-contract.md  # schemas, formulas, guaranteed identity, known limits
docs/metric-definitions.md  # every number with its denominator
docs/experiment-design.md  # pre-registration: unit, MDE, analysis plan, threats
reports/w0_summary.json, reports/baseline.json, reports/ledger.json,
reports/margin.json, reports/marts.json, reports/experiment_design.json,
reports/simulation.json, reports/response.json, reports/policy.json,
reports/spark_parity.json, reports/superset/dashboard.html
```

## What the tests protect

- grain is unique on `(store_id, sku_id, week)`;
- the eight truth components sum to `units_sold`;
- pantry drag is never positive and spikes right after a promo wave;
- cannibalization never lands on the promoted SKU itself;
- the as-of join picks the price version effective in the fact's week, and fails
  loudly when no version covers the week;
- `feature_columns()` refuses any `truth_` column;
- the same seed reproduces the same panel hash, a different seed does not;
- the forecast must beat the naive mean on both WAPE and lift bias, or the suite
  fails — the W2 claim is executable;
- the ledger must reconcile to the oracle within 5% on net units and 10% on
  profit, or the W3 claim fails;
- breakeven depth must rise when margin rises — the W3 decision rule is testable;
- mart totals must equal the ledger within 1 ₽ — the dashboard cannot drift from
  the code;
- the render must be self-contained and must say that it is a static render;
- the experiment design must hold its nominal error rate under 1 000 null splits
  and reach ~80% power at its own MDE — the W5 claim is executable;
- the response model must rank (Qini CI excludes 0) and the policy table must
  follow from the numbers, not from the prose — the W6 claim is executable;
- allocation must never exceed its budget, must beat the simple policies on a
  tight budget, and must match brute force on a small instance — the W7 claim is
  executable;
- Spark and pandas must agree to 0.0 on the real panel, and the plan must contain
  the broadcast join and the window — the W8 claim is executable, and the test
  skips only when no JDK is available.

## Status and gates

W0–W9 are complete. The live Superset instance was verified through the
Docker-free path (`superset/bootstrap_local.sh`); the compose stack stays as the
alternative for machines that can reach Docker Hub.

The full plan, including acceptance criteria and the honest refusals, is the PRD:
[`reports/prd/promo-margin-lab.md`](https://github.com/NikitaBoyarkin/obsidian/blob/main/reports/prd/promo-margin-lab.md).
