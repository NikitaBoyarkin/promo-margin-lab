-- Mart 2: model quality — baseline error, lift bias, placebo interval.
-- Source table: model_eval (one row per counterfactual estimator).
-- Used by: "Model quality" dashboard.
SELECT
    estimator,
    ROUND(baseline_wape_vs_truth, 4) AS wape,
    ROUND(promo_bias_pct, 4)         AS lift_bias,
    ROUND(placebo_p05, 4)            AS placebo_p05,
    ROUND(placebo_p50, 4)            AS placebo_p50,
    ROUND(placebo_p95, 4)            AS placebo_p95
FROM model_eval
ORDER BY ABS(promo_bias_pct) ASC;
