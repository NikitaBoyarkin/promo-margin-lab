-- Mart 4: breakeven depth vs the depth actually used.
-- Source tables: breakeven (fitted response curve) and promo_waves (realised depth).
-- Used by: "Guardrails" dashboard, ceiling card.
SELECT
    b.category,
    b.cm_rate,
    b.supplier_funding,
    b.breakeven_depth,
    ROUND(AVG(w.depth_mean), 4) AS actual_depth,
    ROUND(AVG(w.depth_mean) - b.breakeven_depth, 4) AS depth_over_ceiling,
    CASE WHEN AVG(w.depth_mean) > b.breakeven_depth THEN 1 ELSE 0 END AS beyond_ceiling
FROM breakeven b
JOIN promo_waves w ON w.category = b.category
GROUP BY b.category, b.cm_rate, b.supplier_funding, b.breakeven_depth
ORDER BY depth_over_ceiling DESC;
