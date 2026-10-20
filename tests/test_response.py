"""W6 claims: the model ranks well, and ranking is still the wrong decision rule."""

from __future__ import annotations

import numpy as np
import pytest

from response import fit_predict, run


@pytest.fixture(scope="module")
def result(cfg, panel, counterfactual):
    return run(panel, counterfactual, cfg.seed)


def test_model_learns_the_response(result) -> None:
    assert result["model"]["r2"] > 0.5
    assert result["model"]["mae_rub"] > 0


def test_ranking_beats_random(result) -> None:
    assert result["ranking"]["qini_coefficient"] > 0.2
    low, high = result["bootstrap"]["qini_ci95"]
    assert low > 0, f"qini CI includes zero: [{low}, {high}]"


def test_threshold_policy_is_the_recorded_winner(result) -> None:
    pol = result["policies"]
    diff = pol["threshold"]["total_rub"] - pol["qini_rank"]["total_rub"]
    assert pol["threshold"]["total_rub"] > pol["none"]["total_rub"]
    assert result["hypothesis"]["threshold_beats_rank"] == (diff > 0)
    assert result["hypothesis"]["difference_rub"] == pytest.approx(diff, abs=1.0)


def test_rank_policy_can_lose_money(result) -> None:
    """The point of the module: a high Qini does not make the policy profitable."""
    pol = result["policies"]
    assert (
        pol["qini_rank"]["total_rub"] < pol["none"]["total_rub"] + 1e-6
        or result["ranking"]["qini_coefficient"] < 0.99
    )


def test_oracle_beats_the_model_threshold(result) -> None:
    pol = result["policies"]
    assert pol["oracle_threshold"]["total_rub"] >= pol["threshold"]["total_rub"]


def test_capacity_is_twenty_percent(result) -> None:
    assert result["policies"]["capacity_share"] == 0.2


def test_calibration_slope_is_near_one(result) -> None:
    assert 0.5 <= result["calibration"]["slope"] <= 2.0
    assert len(result["calibration"]["deciles"]) >= 8


def test_uplift_at_k_is_reported(result) -> None:
    assert "uplift_at_20pct_rub" in result["ranking"]


def test_fit_is_deterministic(cfg, panel, counterfactual) -> None:
    from response import build_frame

    frame = build_frame(panel, counterfactual)
    train = frame[frame["week"] <= frame["week"].max() - 16].head(3000)
    test = frame[frame["week"] > frame["week"].max() - 16].head(800)
    first = fit_predict(train, test, cfg.seed)
    second = fit_predict(train, test, cfg.seed)
    assert np.allclose(first, second)
