-- Mart 1: promo P&L by category.
-- Source table: promo_waves (one row per store x week x category with a promo).
-- Used by: "Promo P&L" dashboard.
SELECT
    category,
    COUNT(*)                                   AS waves,
    ROUND(SUM(own_units), 1)                   AS own_units,
    ROUND(SUM(net_units), 1)                   AS net_units,
    ROUND(SUM(revenue_delta), 1)               AS revenue_delta,
    ROUND(SUM(discount_cost), 1)               AS discount_cost,
    ROUND(SUM(supplier_funding), 1)            AS supplier_funding,
    ROUND(SUM(net_profit), 1)                  AS net_profit,
    ROUND(AVG(depth_mean), 4)                  AS avg_depth,
    ROUND(AVG(CASE WHEN net_profit < 0 THEN 1.0 ELSE 0.0 END), 4) AS share_negative
FROM promo_waves
GROUP BY category
ORDER BY net_profit ASC;
