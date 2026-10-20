# Experiment design — pre-registration

Written before the analysis; the numbers below are the design's, not results of
a running test. Everything is validated by simulation on the panel from W1.

## Question

Does capping promo depth at the category breakeven (W3) improve incremental
contribution margin, without losing more revenue than the category owner accepts?

## Unit and arms

| | |
|---|---|
| Unit of randomisation | **store** (cluster), not store-week |
| Arms | 2: capped depth vs current practice |
| Stores | 120 total, 60 per arm |
| Duration | 8 weeks, no washout inside the window |
| Assignment | simple randomisation of stores, stratified by format (convenience / supermarket / hyper) |
| Primary metric | incremental contribution margin, ₽ per store-week |
| Secondary | revenue, units, share of unprofitable waves |
| Guardrails | revenue decline > 2% vs control for 2 consecutive weeks; cannibalization ratio > 35% |

Cluster randomisation is required: the intervention is a category-level decision,
so stores are the smallest independent unit and store-week observations are not
independent (ICC below).

## Power

| | |
|---|---|
| ICC (between-store share of weekly-profit variance) | **0.138** |
| Between-store SD | 884 ₽ |
| SD of store means over 8 weeks | 1 196 ₽ |
| MDE at α = 0.05, power = 0.80 | **612 ₽ / store-week** |
| Same MDE as % of weekly revenue per store | 0.29% |

The MDE is 612 ₽ per store-week, i.e. a third of the average weekly promo loss
(−1 878 ₽). The cap policy is expected to move profit by more than that, so the
design is adequately powered for the decision at hand — but not for a 100 ₽
effect, and the report must say so.

## Analysis plan

1. **SRM** — χ² of store counts against 50/50, threshold p < 0.001. Stop if it fires.
2. **Primary** — Welch t-test on store means over the 8 weeks (cluster-robust by
   construction), two-sided α = 0.05. Report the effect in ₽ with a 95% CI.
3. **Secondary** — same contrast on revenue and units, no multiplicity
   correction (they are guardrails, not claims).
4. **Guardrails** — week-by-week cumulative revenue and cannibalization ratio;
   the stopping rule is evaluated weekly.
5. **No peeking for the primary metric** — the test is read once, at 8 weeks.
   Guardrails are allowed to stop the test early; that is a decision, not a test.

## Simulation validation

1 000 random splits of the 120 stores, outcome = store mean over the last 8 weeks:

| Scenario | Result |
|---|---|
| Null (no effect) rejection rate | **4.7%** (target 5%) |
| Power at the MDE | **77.8%** (target 80%) |
| CI coverage of the true effect | **95.0%** |

A deliberately unbalanced split (57/63) is **not** flagged by SRM (p = 0.58);
a broken split (30/90) is (p < 1e-7). That is the intended sensitivity.

Switchback is offered as an alternative with per-store phase offsets (a common
switch week is not identifiable: week effects absorb the treatment):

| Scenario | Result |
|---|---|
| Null rejection rate | 4.0% |
| Power at the MDE | 100% |
| Injected carryover 0.5 recovered as | **0.49** |

The switchback is far more powerful because it uses store-weeks, not store means;
it is also more fragile, since it assumes no time-varying confounder other than
the week effect. The cluster RCT stays the primary design; the switchback is the
fallback when the MDE is too coarse.

## Threats to validity (stated up front)

- **Spillover between formats** — a customer who switches store moves volume, not
  demand; the primary metric is margin, which still counts the sale, so the bias
  is small but non-zero.
- **Promo calendar** — national campaigns hit both arms in the same weeks; this
  attenuates the contrast, it does not bias it.
- **Compliance** — a store that does not apply the cap is effectively control;
  the analysis is intention-to-treat.
- **Synthetic data** — the DGP has no competitor reaction and no weather. A real
  test would add both as covariates, and the MDE would rise.

## What would make us stop

- SRM p < 0.001 at any read.
- Revenue guardrail breached for two consecutive weeks.
- Fewer than 45 analysable stores per arm (attrition > 25%).
