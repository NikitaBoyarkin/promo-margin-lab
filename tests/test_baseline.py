"""W2 claim, encoded: a forecast beats the naive pre-period mean on lift bias."""

from __future__ import annotations

import numpy as np
import pytest

from baseline import (
    forecast_counterfactual,
    history_features,
    make_grid,
    matched_control_counterfactual,
    naive_counterfactual,
    run,
)


@pytest.fixture(scope="module")
def result(cfg, panel, sim):
    return run(panel, sim.truth, cfg)


def test_forecast_is_the_best_estimator(result) -> None:
    assert result["headline"]["best_by_abs_bias"] == "forecast"


def test_forecast_halves_the_bias_at_least(result) -> None:
    bias = result["headline"]["bias_pct"]
    assert abs(bias["forecast"]) < abs(bias["naive_mean"])
    assert abs(bias["forecast"]) < 0.10
    assert result["headline"]["bias_reduction_x"] > 2.0


def test_naive_is_materially_biased(result) -> None:
    assert abs(result["headline"]["bias_pct"]["naive_mean"]) > 0.05


def test_forecast_has_the_lowest_baseline_error(result) -> None:
    wape = result["headline"]["wape"]
    assert wape["forecast"] < wape["naive_mean"]
    assert wape["forecast"] < 0.15


def test_placebo_is_centred_near_zero(result) -> None:
    for name in ("naive_mean", "forecast", "matched_control"):
        median = result["estimators"][name]["placebo_p50"]
        assert abs(median) < 0.05, f"{name} placebo median {median:+.3f} is not centred"


def test_all_baselines_are_finite_and_non_negative(panel, sim, cfg) -> None:
    grid = make_grid(panel)
    estimates = {
        "naive": naive_counterfactual(panel, grid),
        "forecast": forecast_counterfactual(panel, grid)[0],
        "matched": matched_control_counterfactual(panel, grid),
    }
    for name, values in estimates.items():
        assert np.isfinite(values).all(), f"{name} produced non-finite values"
        assert (values >= 0).all(), f"{name} produced negative demand"


def test_history_features_have_no_gaps(panel) -> None:
    grid = make_grid(panel)
    hist = history_features(panel, grid)
    assert not hist.isna().any().any()
    assert (hist["gap"] >= 0).all()
    assert set(hist["has_history"].unique()) <= {0.0, 1.0}


def test_baseline_run_is_deterministic(cfg, panel, sim) -> None:
    first = run(panel, sim.truth, cfg)["headline"]
    second = run(panel, sim.truth, cfg)["headline"]
    assert first == second
