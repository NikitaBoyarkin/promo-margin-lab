# Data contract — promo-margin-lab

Frozen at W1. Anything below is a promise to the estimators built in W2+.

## Grain

`(store_id, sku_id, week)` — one row per store, SKU and ISO week. A model never
sees a receipt; the decision unit is a store-week promo, which is what an offline
retailer actually schedules.

`week` is an integer index from 0; `week_start` is the Monday date
(`config.start + 7 * week`).

## Tables

### `data/raw/facts.parquet` — observed sales

| column | type | meaning |
|---|---|---|
| `store_id`, `sku_id` | str | dimensions |
| `week` | int16 | week index |
| `promo_flag` | bool | the SKU was on promo this week in this store |
| `promo_depth` | float | discount depth in [0.05, 0.40], 0 when not promoted |
| `mechanic` | int8 | 0 price cut, 1 second at a discount, 2 multi-buy |
| `units_sold` | float | gross units sold, after non-negativity clipping |
| `units_returned` | int | units returned by customers |
| `format`, `category` | str | store format, product category |

### `data/raw/dim_price.parquet` — SCD-2 price list

`(store_id, sku_id, valid_from, valid_to, list_price)`. Several versions per
store-SKU. Joining on `(store_id, sku_id)` alone multiplies rows and picks the
wrong version; the panel uses an **as-of join** on `week` (same shape as the
Magnit test assignment keyed by `item_id + update_date`).

### `data/truth/effects.parquet` — answer key

Same grain as facts, plus the eight components of the generating process. **Never
joined into the panel, never a model feature.** `panel.feature_columns()` raises if
a `truth_` column appears.

### `data/panel/store_sku_week.parquet` — analysis panel

Facts + price + derived money:

| column | formula |
|---|---|
| `net_units` | `units_sold - units_returned` |
| `unit_price` | `list_price * (1 - promo_depth)` |
| `revenue` | `net_units * unit_price` |
| `discount_cost` | `units_sold * promo_depth * list_price` |
| `supplier_funding` | `discount_cost * funded_share` (share of the discount funded by the supplier, 0–50% per SKU) |
| `cm_rate`, `cm` | category contribution-margin rate and `revenue * cm_rate` |

`cm_rate` by category: dairy 12%, bakery 30%, grocery 22%, drinks 26%, frozen
18%, non-food 35% — the 12–35% band the vacancy names.

## The identity the generator guarantees

For every cell, before returns:

```
units_sold = truth_base_units
           + truth_gross_lift_units
           + truth_pantry_units            (<= 0)
           + truth_cannibalization_units   (<= 0, from other SKUs in the category)
           + truth_halo_units              (>= 0, from the complementary category)
           + truth_cross_format_units      (<= 0, traffic pulled from other formats)
           + truth_noise_units
           + truth_clip_units              (explicit non-negativity residual)
```

`truth_clip_units` is named on purpose: clipping at zero is a real residual, so
hiding it inside noise would make the ledger look cleaner than the data is.
Test: `tests/test_dgp.py::test_ledger_identity_holds` (`atol=2e-3`, the rounding
of the committed parquet).

## Confounding by construction

Promo assignment is not random: the logit rises when recent demand (a weighted
average of the previous three weeks) was weak, and when the SKU's margin is
higher. The signal is deliberately backward-looking, so a history-aware baseline
*can* recover it — while the current week's own shock stays unpredictable. A
naive pre-period mean therefore measures the manager's reaction as well as the
promo; W2 reports the size of that bias rather than assuming it away.

## Returns

Returns are a per-cell binomial draw, 0.4% of units (1.5% for non-food). They are
subtracted from units and revenue and **kept as a separate column**, never
silently dropped — the panel tests assert `net = sold - returned` and that a
corrupted return count fails validation.

## Reproducibility

`uv run python run.py --stage all` on a clean clone reproduces every number in
the README from `seed = 42`. `--fast` uses 40 stores / 30 SKUs / 52 weeks (62,400
cells): same code path, CI only, **never cited as a headline number**. `paths.frame_hash`
hashes values, not parquet bytes, so it is stable across machines.

## Known limits (honest)

- Weekly grain cannot see within-week switching or day-of-week effects.
- Demand is a smooth seasonal process; no weather, competitor price or stockouts yet.
- Substitution is a category-level matrix, not SKU-level from baskets.
- The truth is synthetic. It is a feature (an estimator can be scored), not a
  substitute for validation on real scanner data; W9 may add an external check.
