"""W3 claims: the ledger reconciles to the oracle, and depth has a breakeven."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from config import CATEGORIES, CM_RATE
from ledger import _truth_component, breakeven_table, build_waves, fit_response, run

REPORT = Path(__file__).resolve().parents[1] / "reports" / "ledger.json"

# The artefact is generated on macOS/arm64, CI runs linux/x86_64: uv.lock resolves the same
# pandas/numpy/scikit-learn versions, but BLAS sums in a different order. Observed drift on this
# report is 28 RUB out of 24.4M (1.2e-6 relative). A real drift (bug, changed parameter) moves the
# headline by at least 0.1%, so this band still turns red on anything that matters.
REPORT_REL = 1e-4


@pytest.fixture(scope="module")
def result(cfg, panel, sim, counterfactual):
    return run(panel, counterfactual, sim.truth)


def test_net_equals_sum_of_buckets(result) -> None:
    waves = result["waves"]
    total = waves[["own_units", "pantry_units", "cannibalization_units", "halo_units"]].sum(axis=1)
    assert np.allclose(waves["net_units"], total, atol=1e-6)


def test_ledger_reconciles_to_the_oracle(result) -> None:
    rec = result["summary"]["reconciliation"]
    # own-lift error tracks the documented forecast bias (−3.7%), so 5% is the band
    assert abs(rec["own_units"]["error_pct"]) < 0.05
    assert abs(rec["net_units"]["error_pct"]) < 0.05
    assert abs(rec["net_profit_rub"]["error_pct"]) < 0.10
    assert abs(rec["cannibalization_units"]["error_pct"]) < 0.15
    assert abs(rec["halo_units"]["error_pct"]) < 0.15


def test_negative_profit_share_is_not_degenerate(result) -> None:
    share = result["summary"]["share_waves_negative_profit"]
    assert 0.0 < share < 1.0


def test_post_promo_bucket_matches_the_answer_key(result, panel, sim) -> None:
    """Sign and scale against the answer key — "small relative to own" hid a sign flip."""
    summary = result["summary"]
    truth_pantry = _truth_component(panel, sim.truth, "truth_pantry_units", "pantry")
    assert truth_pantry < 0
    assert summary["pantry_units"] < 0
    assert abs(summary["pantry_units"]) > 0.02 * abs(summary["own_lift_units"])
    assert abs(summary["pantry_units"] - truth_pantry) / abs(truth_pantry) < 0.85


def test_pnl_bridge_sums_to_net_profit(result) -> None:
    summary = result["summary"]
    bridge = summary["pnl_bridge"]
    assert (
        abs(
            bridge["margin_on_incremental_units_rub"]
            + bridge["discount_net_of_supplier_funding_rub"]
            - bridge["promo_cells_profit_rub"]
        )
        < 1.0
    )
    # the bridge re-derives profit from rounded panel columns, so allow kopecks of drift
    assert abs(bridge["net_profit_rub"] - summary["net_profit_rub"]) < 50.0


def test_committed_ledger_report_matches_fresh_run(result) -> None:
    """Bind the headline number to the code: a silent drift turns this red."""
    report = json.loads(REPORT.read_text())
    assert report["summary"]["net_profit_rub"] == pytest.approx(
        result["summary"]["net_profit_rub"], rel=REPORT_REL
    )
    assert report["summary"]["pnl_bridge"] == pytest.approx(
        result["summary"]["pnl_bridge"], rel=REPORT_REL
    )
    # the artefact is internally consistent regardless of the machine that produced it
    assert (
        abs(report["summary"]["pnl_bridge"]["net_profit_rub"] - report["summary"]["net_profit_rub"])
        < 50.0
    )


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
