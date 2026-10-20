"""W5 claims: the design is calibrated, not just described."""

from __future__ import annotations

import pytest

from experiment import (
    icc,
    mde,
    profit_matrix,
    run,
    simulate_cluster_rct,
    simulate_switchback,
    srm_check,
    store_week_profit,
)


@pytest.fixture(scope="module")
def result(cfg, panel, sim, counterfactual):
    return run(panel, counterfactual, cfg.seed)


def test_false_positive_rate_is_calibrated(result) -> None:
    assert 0.03 <= result["cluster_rct"]["null"]["reject_rate"] <= 0.07


def test_power_at_mde_is_close_to_target(result) -> None:
    assert 0.70 <= result["cluster_rct"]["at_mde"]["reject_rate"] <= 0.90


def test_confidence_intervals_cover_the_truth(result) -> None:
    assert 0.90 <= result["cluster_rct"]["at_mde"]["ci_coverage"] <= 0.98


def test_estimator_is_unbiased(result) -> None:
    assert abs(result["cluster_rct"]["at_mde"]["bias"]) < 0.1 * result["mde"]["rub_per_store_week"]


def test_icc_is_in_range(result) -> None:
    assert 0 < result["variance"]["icc"] < 1


def test_srm_catches_a_broken_split() -> None:
    ok = srm_check({"control": 57, "treatment": 63}, {"control": 60, "treatment": 60})
    broken = srm_check({"control": 30, "treatment": 90}, {"control": 60, "treatment": 60})
    assert ok["srm"] is False
    assert broken["srm"] is True


def test_switchback_is_calibrated_under_null(result) -> None:
    assert result["switchback"]["null"]["reject_rate"] <= 0.08


def test_switchback_recovers_carryover(result) -> None:
    ratio = result["switchback"]["carryover_test"]["carryover_ratio"]
    assert 0.35 <= ratio <= 0.65, f"injected 0.5, recovered {ratio}"


def test_mde_scales_with_sigma() -> None:
    assert mde(1000, 60) > mde(500, 60)
    assert mde(1000, 120) < mde(1000, 60)


def test_profit_matrix_is_balanced(panel, counterfactual) -> None:
    matrix = profit_matrix(store_week_profit(panel, counterfactual))
    assert matrix.notna().all().all()
    assert matrix.shape == (panel["store_id"].nunique(), panel["week"].nunique())


def test_design_run_is_deterministic(cfg, panel, counterfactual) -> None:
    first = run(panel, counterfactual, cfg.seed)["cluster_rct"]["null"]
    second = run(panel, counterfactual, cfg.seed)["cluster_rct"]["null"]
    assert first == second


def test_icc_and_mde_ignore_tiny_samples() -> None:
    import numpy as np
    import pandas as pd

    frame = pd.DataFrame(
        np.arange(12, dtype=float).reshape(3, 4),
        index=["a", "b", "c"],
        columns=[0, 1, 2, 3],
    )
    stats = icc(frame)
    assert stats["stores"] == 3 and stats["weeks"] == 4


def test_simulation_shapes(panel, counterfactual) -> None:
    matrix = profit_matrix(store_week_profit(panel, counterfactual))
    out = simulate_cluster_rct(matrix, 0.0, 25, 0.05, 7)
    assert out["reps"] == 25
    assert 0 <= out["reject_rate"] <= 1
    sw = simulate_switchback(matrix, 0.0, 25, 0.05, 7)
    assert sw["reps"] == 25
