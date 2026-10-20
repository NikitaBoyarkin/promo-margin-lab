# Metric definitions

One definition per number, with its denominator. A number without a denominator
is an advert.

## Money

**Incremental revenue** = `Σ (revenue − baseline × unit_price)` over the cells in
scope. Baseline is the W2 forecast counterfactual, not the pre-period mean.

**Incremental contribution margin (CM)** = `units_sold × (unit_price − cost) +
supplier_funding − baseline × (list_price − cost)`, where `cost = list_price ×
(1 − cm_rate)`. Note the second term: the units that would have sold at full price
also lose margin when they sell at a discount. Dropping it overstates promo profit
by roughly the discount rate (this was a real bug, fixed in W3).

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

**ICC** = between-store share of weekly-profit variance, from a two-way
decomposition of the store × week matrix.

**MDE** = `(z_{1−α/2} + z_power) × √(2/n_arm) × σ_store`, expressed in ₽ per
store-week, with σ the SD of store means over the experiment window.

**SRM** = χ² of observed arm sizes against the planned split; flagged at
p < 0.001. It is a data-integrity check, not a test of the treatment.
