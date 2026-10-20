-- Mart 3: weekly guardrail — is the promo calendar paying for itself?
-- Source table: promo_waves.
-- Used by: "Guardrails" dashboard.
SELECT
    week,
    COUNT(*)                                        AS waves,
    ROUND(SUM(revenue_delta), 1)                    AS revenue_delta,
    ROUND(SUM(net_profit), 1)                       AS net_profit,
    ROUND(SUM(net_profit) / NULLIF(SUM(revenue_delta), 0), 4) AS profit_per_revenue,
    ROUND(AVG(CASE WHEN net_profit < 0 THEN 1.0 ELSE 0.0 END), 4) AS share_negative
FROM promo_waves
GROUP BY week
ORDER BY week ASC;
