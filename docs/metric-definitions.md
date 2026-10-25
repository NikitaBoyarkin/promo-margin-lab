# Metric definitions

One definition per number, with its denominator. A number without a denominator
is an advert.

## Money

**Incremental revenue** = `Σ (revenue − baseline × unit_price)` over the cells in
scope. Baseline is the W2 forecast counterfactual, not the pre-period mean.

**Incremental contribution margin (CM)** = `net_units × (unit_price − cost) +
supplier_funding − baseline × (list_price − cost)`, where `cost = list_price ×
(1 − cm_rate)` and `net_units = units_sold − units_returned`. Note the second
term: the units that would have sold at full price also lose margin when they
sell at a discount. Dropping it overstates promo profit by roughly the discount
rate (this was a real bug, fixed in W3).

The units base is `net_units`, because a returned unit earns no margin. **Known
gap:** `src/experiment.py:43` computes the primary metric on `units_sold`, so the
headline incremental CM in `reports/simulation.json` is on a gross base. On the
current panel the gross base overstates incremental CM by **3.51 mn ₽ (17.2% of
the −20.39 mn ₽ total)**. Until `store_week_profit` is switched to `net_units`,
any primary-metric figure quoted from that module carries this bias — PENDING.

**Breakeven depth** = the largest `d` for which
`(1 + m(d)) × (cm − d × (1 − funding)) > cm`, with `m(d) = A × (1 − e^(−k·d))`
fitted per category. Denominator: one baseline unit.

**Policy value** = total incremental CM of the cells a policy selects, at a fixed
capacity `k` or a fixed spend. Always report `k` and the number of cells actually
selected: a policy that selects 285 of 1 538 cells is not comparable to one that
fills the budget.

## Measurement

**WAPE** = `Σ|baseline − truth| / Σ truth` on non-promo cells. Symmetric, unlike
MAPE, and does not explode on near-zero demand.

**Lift bias** = `Σ(lift_hat − lift_true) / Σ lift_true` over promoted cells.
Signed: negative means lift is understated.

**Placebo lift** = lift estimated on non-promo cells with no promo within ±2 weeks.
Report the median and the p05–p95 interval, never a single tail.

**Qini coefficient** = area between the cumulative-gain curve sorted by score and
the random line, divided by the same area for the perfect ranking. It measures
ranking only; it says nothing about the level of the score, and therefore nothing
about whether the selected cells make money.

**Uplift@k** = mean realised outcome in the top-k minus the overall mean. k is the
campaign capacity, not a round number chosen after the fact.

## Experiment

**ICC** = between-store share of variance in **incremental CM deviation**
(`dev_profit` = realised CM − baseline CM), from a two-way decomposition of the
store × week matrix. It is *not* the ICC of raw profit: store size dominates raw
CM (between-store SD 27 046 ₽) and the raw ICC is 0.95–0.99, which would imply no
experiment can ever be powered. The design number applies to the deviation.

Report the window it was computed on. ICC over all 78 weeks and ICC over the
8-week experiment window are different quantities: on the current panel they are
**0.2197** and **0.3572**. Power and MDE use the window value.

**MDE** = `(z_{1−α/2} + z_power) × √(2/n_arm) × σ_store`, expressed in ₽ per
store-week, with σ the SD of store means over the experiment window (not the
weekly SD, and not the SD of the whole panel).

Two qualifications, both required when quoting an MDE:

- **Exposure.** The 8-week window currently contains promo in 4 weeks (70, 71,
  74, 75); weeks 72, 73, 76, 77 have `promo_flag = 0`. An MDE quoted per
  store-week averages over exposed and unexposed weeks, so the MDE per *exposed*
  week is roughly double it.
- **Window.** An MDE is only comparable to another MDE computed on the same
  window length and the same dataset version.

**SRM** = χ² of observed arm sizes against the planned split; flagged at
p < 0.001. It is a data-integrity check, not a test of the treatment. Check it
**per stratum** as well as overall: with 120 stores stratified by format, a
global 60/60 can hide a 9/3 split inside a 12-store stratum.

## Guardrails

A guardrail is a decision rule, not a claim, so it needs a statistic and an α
budget like any other test — "no peeking" applies only to the primary metric.

**Revenue guardrail** = relative change in weekly store revenue,
`mean(treatment) / mean(control) − 1`, at the store-week grain. It fires when the
decline exceeds the threshold for two consecutive weeks. The statistic is a
one-sided z on the weekly contrast, and the threshold must be stated in SE units:
a fixed 2% point estimate is not a test. On the current panel the weekly revenue
SD is 51% of the level, so the SE of the contrast is ~9% and a 2% rule fires
under the null in **41.8% of 1 000 random splits**. The rule must be recalibrated
until the simulated false-stop rate is ≤5%.

**Cannibalization ratio** = `cannibalized units / own incremental units` on a
wave. The cap policy is supposed to **reduce** it, so the guardrail fires when the
ratio rises above 35%; the direction matters and must be written down. The
current `reports/ledger.json` reports 0.19 for a different quantity — it is not
this guardrail.

**α budget** = 0.001 per guardrail read (Bonferroni over 8 weeks × 2 guardrails),
separate from the primary α = 0.05. Spending the primary α on weekly guardrail
reads would inflate the false-stop rate without bound.
