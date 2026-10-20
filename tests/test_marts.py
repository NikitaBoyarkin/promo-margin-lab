"""W4 claims: the dashboard numbers are the SQL numbers, and SQL is reproducible."""

from __future__ import annotations

import json

import pytest

from baseline import run as run_baseline
from ledger import run as run_ledger
from marts import build_database, headline, run_marts
from render import render

SQL_DIR = __import__("pathlib").Path(__file__).resolve().parent.parent / "sql" / "marts"


@pytest.fixture(scope="module")
def bundle(cfg, panel, sim, tmp_path_factory):
    baseline = run_baseline(panel, sim.truth, cfg)
    counterfactual = baseline.pop("counterfactual")
    ledger = run_ledger(panel, counterfactual, sim.truth)
    summary = ledger["summary"]
    margin = {
        "breakeven": summary["breakeven"],
        "pnl": {
            "net_profit_rub": summary["net_profit_rub"],
            "revenue_delta_rub": summary["revenue_delta_rub"],
        },
    }
    path = tmp_path_factory.mktemp("marts") / "promo.db"
    build_database(panel, ledger["waves"], counterfactual, baseline, margin, path)
    results = run_marts(path, SQL_DIR)
    return {"results": results, "headline": headline(results), "summary": summary, "path": path}


def test_all_marts_return_rows(bundle) -> None:
    results = bundle["results"]
    assert len(results["promo_pnl"]) == 6
    assert len(results["model_quality"]) == 3
    assert len(results["guardrails"]) > 20
    assert len(results["breakeven_vs_actual"]) == 6


def test_mart_profit_matches_ledger(bundle) -> None:
    pnl = bundle["results"]["promo_pnl"]
    assert abs(pnl["net_profit"].sum() - bundle["summary"]["net_profit_rub"]) < 1.0


def test_mart_revenue_matches_ledger(bundle) -> None:
    pnl = bundle["results"]["promo_pnl"]
    assert abs(pnl["revenue_delta"].sum() - bundle["summary"]["revenue_delta_rub"]) < 1.0


def test_model_quality_picks_the_forecast(bundle) -> None:
    assert bundle["headline"]["best_estimator"] == "forecast"


def test_breakeven_gap_is_bounded(bundle) -> None:
    gap = bundle["results"]["breakeven_vs_actual"]
    assert 0 <= bundle["headline"]["categories_beyond_ceiling"] <= 6
    assert gap["breakeven_depth"].between(0, 0.5).all()


def test_render_is_self_contained(bundle, tmp_path) -> None:
    path = render(bundle["results"], bundle["headline"], tmp_path / "dash.html", 42, "deadbeef")
    html = path.read_text(encoding="utf-8")
    assert "статический рендер" in html
    assert "superset/docker-compose.yml" in html
    assert "http://" not in html and "https://" not in html
    assert "deadbeef" in html


def test_marts_json_shape(tmp_path, bundle) -> None:
    payload = json.dumps(bundle["headline"])
    assert "net_profit_rub" in payload
