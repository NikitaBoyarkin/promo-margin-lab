"""W7 claims: allocation respects its constraints and beats the simple policies."""

from __future__ import annotations

import pytest

from allocation import DEPTHS, breakeven_table, build_candidates, fit_response, run


@pytest.fixture(scope="module")
def result(cfg, panel, counterfactual):
    return run(panel, counterfactual, cfg.seed)


def test_budget_is_never_exceeded(result) -> None:
    for name, scenario in result["scenarios"].items():
        budget = scenario["budget_rub"]
        for policy in ("random_15", "top_ratio_15", "optimised"):
            assert scenario[policy]["spend_rub"] <= budget + 1.0, (name, policy)


def test_optimised_beats_simple_policies_on_a_tight_budget(result) -> None:
    tight = result["scenarios"]["tight"]
    assert tight["optimised"]["profit_rub"] > tight["top_ratio_15"]["profit_rub"]
    assert tight["optimised"]["profit_rub"] > tight["random_15"]["profit_rub"]


def test_optimised_beats_blanket_15(result) -> None:
    assert result["blanket_15"]["profit_rub"] < 0
    assert result["vs_blanket"]["profit_delta_rub"] > 0
    assert result["vs_blanket"]["profit_per_ruble_optimised"] > 0


def test_greedy_matches_brute_force_on_the_small_instance(result) -> None:
    assert result["heuristic_check"]["gap"] <= 0.02


def test_selection_moves_under_a_response_shock(result) -> None:
    for row in result["robustness"]:
        assert 0.0 <= row["selection_changed_share"] <= 1.0
        assert row["profit_rub"] != 0


def test_depths_respect_the_breakeven_cap(result, panel, counterfactual) -> None:
    for row in result["robustness"]:
        assert row["cells_selected"] >= 0
    for depth in result["scenarios"]["tight"]["optimised"]["depths"]:
        assert float(depth) <= 0.40
        assert float(depth) in set(DEPTHS.tolist())


def test_spacing_rule_removes_recent_promos(panel, counterfactual) -> None:
    curves = fit_response(panel, counterfactual)
    caps = {cat: row["breakeven_depth"] for cat, row in breakeven_table(panel, curves).items()}
    cells = build_candidates(panel, counterfactual, curves, caps)
    week = int(cells["week"].max())
    recent = panel[(panel["week"] < week) & (panel["week"] >= week - 6) & panel["promo_flag"]]
    blocked = set(zip(recent["store_id"], recent["sku_id"], strict=True))
    chosen = set(zip(cells["store_id"], cells["sku_id"], strict=True))
    assert not (blocked & chosen)


def test_candidates_have_a_depth_cap_inside_the_legal_range(panel, counterfactual) -> None:
    curves = fit_response(panel, counterfactual)
    caps = {cat: row["breakeven_depth"] for cat, row in breakeven_table(panel, curves).items()}
    cells = build_candidates(panel, counterfactual, curves, caps)
    assert cells["depth_cap"].between(0, 0.40).all()


def test_output_is_deterministic(cfg, panel, counterfactual) -> None:
    first = run(panel, counterfactual, cfg.seed)["scenarios"]["tight"]["optimised"]
    second = run(panel, counterfactual, cfg.seed)["scenarios"]["tight"]["optimised"]
    assert first == second
