# Dashboard spec

Three dashboards, four datasets, one rule: every number comes from
`sql/marts/*.sql`. Nothing is computed in the chart layer.

## 1. Promo P&L — «где деньги»

Dataset: `promo_pnl` (category grain).

| Chart | Type | Metrics / dimensions | Question it answers |
|---|---|---|---|
| Incremental revenue vs discount cost | grouped bar | `revenue_delta`, `discount_cost` by `category` | сколько выручки купили и сколько за неё заплатили |
| Net profit by category | bar, diverging | `net_profit` by `category`, red below zero | какие категории субсидируют промо |
| Share of unprofitable waves | big number + sparkline | `share_negative` | как часто промо не окупается |
| Depth vs breakeven | scatter | x=`avg_depth`, y=`breakeven_depth`, size=`waves` | насколько пробит потолок |

Cards: total `revenue_delta`, total `net_profit`, `supplier_funding`.

## 2. Model Quality — «почему этим числам можно верить»

Dataset: `model_quality` (estimator grain).

| Chart | Type | Metrics | Question |
|---|---|---|---|
| Baseline error | bar | `wape` by `estimator` | насколько точна база |
| Lift bias | bar, diverging | `lift_bias` by `estimator` | в какую сторону врёт каждый оценщик |
| Placebo interval | range/error bar | `placebo_p05`, `placebo_p50`, `placebo_p95` | что оценщик видит там, где эффекта нет |

Note on the dashboard: per-cell placebo is ±16–22%, so a single cell cannot
resolve a small effect — that is the argument for the cluster design (W5), and
it belongs on the dashboard, not only in the README.

## 3. Guardrails — «что остановит раскатку»

Dataset: `guardrails` (week grain) + `breakeven_vs_actual`.

| Chart | Type | Metrics | Guardrail |
|---|---|---|---|
| Weekly profit | bar, diverging | `net_profit` by `week` | отрицательная неделя — повод остановить волну |
| Profit per revenue | line | `profit_per_revenue` | не ниже порога, заданного владельцем категории |
| Share of negative waves | line | `share_negative` | авто-стоп, если > 90% две недели подряд |
| Categories beyond ceiling | table | `actual_depth` vs `breakeven_depth`, `beyond_ceiling` | потолок глубины |

## Row-level security demo

Role `store_format_filter`, filter `format = 'hyper'` on `promo_cells`.
Purpose: show that a category manager sees only their format, without
duplicating the dashboard. Requires the live instance; not applied yet.

## What is deliberately absent

- No "lift over time" chart: weekly lift is a noisy series and would invite
  reading noise as trend.
- No pie charts and no dual axes.
- No computed metrics inside charts (Superset calculated columns) — SQL owns
  definitions, otherwise the dashboard and `check_claims` drift apart.
