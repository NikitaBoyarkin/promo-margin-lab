"""W3 claims: the ledger reconciles to the oracle, and depth has a breakeven."""

from __future__ import annotations

import numpy as np
import pytest

from config import CATEGORIES, CM_RATE
from ledger import breakeven_table, build_waves, fit_response, run


@pytest.fixture(scope="module")
def result(cfg, panel, sim, counterfactual):
    return run(panel, counterfactual, sim.truth)


def test_net_equals_sum_of_buckets(result) -> None:
    waves = result["waves"]
    total = waves[["own_units", "pantry_units", "cannibalization_units", "halo_units"]].sum(axis=1)
    assert np.allclose(waves["net_units"], total, atol=1e-6)


def test_ledger_reconciles_to_the_oracle(result) -> None:
    rec = result["summary"]["reconciliation"]
    assert abs(rec["own_units"]["error_pct"]) < 0.03
    assert abs(rec["net_units"]["error_pct"]) < 0.05
    assert abs(rec["net_profit_rub"]["error_pct"]) < 0.10
    assert abs(rec["cannibalization_units"]["error_pct"]) < 0.15
    assert abs(rec["halo_units"]["error_pct"]) < 0.15


def test_negative_profit_share_is_not_degenerate(result) -> None:
    share = result["summary"]["share_waves_negative_profit"]
    assert 0.0 < share < 1.0


def test_post_promo_bucket_is_small_relative_to_own(result) -> None:
    summary = result["summary"]
    assert abs(summary["pantry_units"]) < 0.10 * abs(summary["own_lift_units"])


def test_response_curves_fit_the_binned_data(result) -> None:
    for cat, curve in result["summary"]["response_curves"].items():
        assert curve["amplitude"] > 0, cat
        assert curve["r2"] > 0.5, f"{cat} curve r2={curve['r2']}"


def test_breakeven_is_monotone_in_margin(panel, counterfactual) -> None:
    curves = fit_response(panel, counterfactual)
    base = dict(zip(CATEGORIES, CM_RATE, strict=True))
    richer = {cat: cm + 0.10 for cat, cm in base.items()}
    low = breakeven_table(panel, curves, base)
    high = breakeven_table(panel, curves, richer)
    for cat in curves:
        assert high[cat]["breakeven_depth"] >= low[cat]["breakeven_depth"], cat


def test_breakeven_depth_is_inside_the_grid(result) -> None:
    for cat, row in result["summary"]["breakeven"].items():
        assert 0.0 <= row["breakeven_depth"] <= 0.5, cat
        assert row["best_depth"] <= 0.5, cat


def test_waves_have_no_missing_components(cfg, panel, sim, counterfactual) -> None:
    waves = build_waves(panel, counterfactual)
    columns = [
        "own_units",
        "pantry_units",
        "cannibalization_units",
        "halo_units",
        "net_units",
        "net_profit",
    ]
    assert not waves[columns].isna().any().any()
    assert len(waves) > 0


def test_summary_shape(cfg, panel, sim, counterfactual) -> None:
    summary = run(panel, counterfactual, sim.truth)["summary"]
    for key in ("own_lift_units", "net_lift_units", "net_profit_rub", "breakeven"):
        assert key in summary
