"""Budget allocation: which cells, at which depth, for a fixed trade-spend budget.

Candidates are (store, SKU) cells of one planning week, filtered by the spacing
rule (no promo on that SKU in the previous 6 weeks). Expected profit at depth
``d`` comes from the W3 category response curve, scaled by a shrunk per-cell
multiplier estimated on the training period:

    m(d) = A_category * multiplier_cell * (1 - exp(-k_category * d))
    profit = baseline_units * list_price * ((1 + m) * (cm - d * (1 - funding)) - cm)
    cost   = baseline_units * (1 + m) * list_price * d

Depth is capped at the category breakeven (W3) and at 40%. Selection is a greedy
knapsack by profit per rouble, checked against brute force on a small instance.
"""

from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

from config import CATEGORIES, CM_RATE
from ledger import breakeven_table, fit_response

KEY = ["store_id", "sku_id", "week"]
# 0.01 floor: category breakeven floors reach 2.0%, a 5% grid silently drops them
DEPTHS = np.round(np.arange(0.01, 0.401, 0.01), 2)


def _multipliers(
    panel: pd.DataFrame, counterfactual: pd.DataFrame, curves: dict, upto: int
) -> dict:
    """Shrunk per-cell response multiplier vs its category curve (train period only)."""
    df = panel.merge(counterfactual, on=KEY, how="left", validate="one_to_one")
    train = df[(df["promo_flag"]) & (df["week"] < upto)].copy()
    train["rel_lift"] = train["units_sold"] / train["baseline"] - 1.0
    train = train[train["rel_lift"].between(-0.5, 5.0)]
    train["expected"] = [
        curves[row.category]["amplitude"]
        * (1 - np.exp(-curves[row.category]["k"] * row.promo_depth))
        for row in train.itertuples()
    ]
    train = train[train["expected"] > 1e-3]
    train["ratio"] = train["rel_lift"] / train["expected"]
    agg = train.groupby(["store_id", "sku_id"])["ratio"].agg(["mean", "size"])
    shrink = 3.0
    shrunk = (agg["mean"] * agg["size"] + shrink) / (agg["size"] + shrink)
    return shrunk.clip(0.3, 3.0).to_dict()


def build_candidates(
    panel: pd.DataFrame, counterfactual: pd.DataFrame, curves: dict, depth_caps: dict
) -> pd.DataFrame:
    week = int(panel["week"].max())
    recent = panel[(panel["week"] < week) & (panel["week"] >= week - 6) & panel["promo_flag"]]
    blocked = set(zip(recent["store_id"], recent["sku_id"], strict=True))

    cf = counterfactual.rename(columns={"baseline": "baseline_units"})
    cells = panel[panel["week"] == week].merge(cf, on=KEY, how="left")
    cells = cells[
        [(s, k) not in blocked for s, k in zip(cells["store_id"], cells["sku_id"], strict=True)]
    ]
    cells = cells.copy()
    mult = _multipliers(panel, counterfactual, curves, upto=week - 16)
    cells["multiplier"] = [
        mult.get((s, k), 1.0) for s, k in zip(cells["store_id"], cells["sku_id"], strict=True)
    ]
    cells["depth_cap"] = cells["category"].map(depth_caps).clip(upper=0.40)
    cells["cm_rate"] = cells["category"].map(dict(zip(CATEGORIES, CM_RATE, strict=True)))
    return cells.reset_index(drop=True)


def _profit(
    cells: pd.DataFrame, depth: float | np.ndarray, curves: dict
) -> tuple[np.ndarray, np.ndarray]:
    depth = np.asarray(depth, dtype=float)
    curve = cells["category"].map(curves)
    amplitude = np.array([c["amplitude"] for c in curve], dtype=float)
    k = np.array([c["k"] for c in curve], dtype=float)
    m = amplitude * cells["multiplier"].to_numpy() * (1 - np.exp(-k * depth))
    m = np.clip(m, 0.0, 3.0)
    price = cells["list_price"].to_numpy()
    base = cells["baseline_units"].to_numpy()
    cm = cells["cm_rate"].to_numpy()
    funding = cells["funded_share"].to_numpy()
    profit = base * price * ((1 + m) * (cm - depth * (1 - funding)) - cm)
    cost = base * (1 + m) * price * depth
    return profit, cost


def option_table(cells: pd.DataFrame, curves: dict) -> pd.DataFrame:
    rows = []
    for depth in DEPTHS:
        profit, cost = _profit(cells, depth, curves)
        rows.append(
            pd.DataFrame(
                {
                    "row": np.arange(len(cells)),
                    "depth": depth,
                    "profit": profit,
                    "cost": cost,
                }
            )
        )
    table = pd.concat(rows, ignore_index=True)
    table = table[table["depth"] <= cells["depth_cap"].to_numpy()[table["row"]]]
    return table


def greedy(table: pd.DataFrame, budget: float) -> dict:
    """Marginal greedy: every cell starts unpromoted and is deepened only when
    the next step pays for itself. Ranking whole options instead lets the
    shallowest depth win every cell and leaves the budget unspent.
    """
    import heapq

    g = table.sort_values(["row", "depth"]).reset_index(drop=True)
    prof = g["profit"].to_numpy()
    cost = g["cost"].to_numpy()
    depths = g["depth"].to_numpy()
    rows = g["row"].to_numpy()
    row_index = pd.factorize(rows)[0]
    n_rows = int(row_index.max()) + 1
    counts = np.bincount(row_index, minlength=n_rows)
    starts = np.searchsorted(row_index, np.arange(n_rows))

    prev_prof = g.groupby("row")["profit"].shift(1).fillna(0.0).to_numpy()
    prev_cost = g.groupby("row")["cost"].shift(1).fillna(0.0).to_numpy()
    gain = prof - prev_prof
    dcost = cost - prev_cost

    pos = np.zeros(n_rows, dtype=int)
    chosen: list[tuple[int, float]] = []
    spent = 0.0
    total = 0.0

    def push(r: int) -> None:
        k = pos[r]
        if k >= counts[r]:
            return
        i = starts[r] + k
        step = dcost[i]
        ratio = gain[i] / max(step, 1e-6)
        heapq.heappush(heap, (-ratio, int(rows[i]), r))

    heap: list[tuple[float, int, int]] = []
    for r in range(n_rows):
        push(r)
    while heap and spent < budget:
        _, _, r = heapq.heappop(heap)
        i = starts[r] + pos[r]
        if gain[i] <= 0:
            continue
        if spent + dcost[i] > budget:
            continue
        spent += float(dcost[i])
        total += float(gain[i])
        pos[r] += 1
        chosen.append((int(rows[i]), float(depths[i])))
        push(r)
    return {"choices": chosen, "spend": spent, "profit": total, "cells": len(chosen)}


def blanket(cells: pd.DataFrame, depth: float, curves: dict) -> dict:
    profit, cost = _profit(cells, np.full(len(cells), depth), curves)
    return {"spend": float(cost.sum()), "profit": float(profit.sum()), "cells": int(len(cells))}


def top_ratio(cells: pd.DataFrame, budget: float, curves: dict, depth: float = 0.15) -> dict:
    depth_vec = np.minimum(depth, cells["depth_cap"].to_numpy())
    profit, cost = _profit(cells, depth_vec, curves)
    order = np.argsort(-(profit / np.clip(cost, 1e-6, None)))
    spent, total, used = 0.0, 0.0, 0
    for idx in order:
        if profit[idx] <= 0:
            continue
        if spent + cost[idx] <= budget:
            spent += cost[idx]
            total += profit[idx]
            used += 1
    return {"spend": float(spent), "profit": float(total), "cells": int(used)}


def brute_force(
    cells: pd.DataFrame,
    budget: float,
    curves: dict,
    max_cells: int = 5,
    depths=(0.0, *DEPTHS),
) -> dict:
    subset = cells.head(max_cells)
    caps = subset["depth_cap"].to_numpy()
    allowed = [tuple(d for d in depths if d <= cap) or (0.0,) for cap in caps]
    best = (0.0, None)
    for combo in itertools.product(*allowed):
        profit, cost = _profit(subset, np.array(combo), curves)
        if cost.sum() <= budget:
            value = float(profit.sum())
            if value > best[0]:
                best = (value, combo)
    return {
        "budget": float(budget),
        "cells": int(len(subset)),
        "profit": best[0],
        "depths": best[1],
    }


def _policy_table(cells: pd.DataFrame, curves: dict, budget: float, rng) -> dict:
    table = option_table(cells, curves)
    optimised = greedy(table, budget)
    top15 = top_ratio(cells, budget, curves)
    depth_vec = np.minimum(0.15, cells["depth_cap"].to_numpy())
    profit15, cost15 = _profit(cells, depth_vec, curves)
    order = rng.permutation(len(cells))
    spent, total, used = 0.0, 0.0, 0
    for idx in order:
        if spent + cost15[idx] <= budget:
            spent += cost15[idx]
            total += profit15[idx]
            used += 1
    return {
        "budget_rub": round(budget, 1),
        "random_15": {
            "spend_rub": round(float(spent), 1),
            "profit_rub": round(float(total), 1),
            "cells": int(used),
            "unspent_rub": round(budget - float(spent), 1),
        },
        "top_ratio_15": {
            "spend_rub": round(top15["spend"], 1),
            "profit_rub": round(top15["profit"], 1),
            "cells": int(top15["cells"]),
            "unspent_rub": round(budget - top15["spend"], 1),
        },
        "optimised": {
            "spend_rub": round(optimised["spend"], 1),
            "profit_rub": round(optimised["profit"], 1),
            "cells": int(optimised["cells"]),
            "unspent_rub": round(budget - optimised["spend"], 1),
            "depths": {
                str(k): int(v)
                for k, v in pd.Series([d for _, d in optimised["choices"]])
                .value_counts()
                .sort_index()
                .items()
            },
        },
        "_choices": optimised["choices"],
    }


def run(panel: pd.DataFrame, counterfactual: pd.DataFrame, seed: int = 42) -> dict:
    curves = fit_response(panel, counterfactual)
    caps = {cat: row["breakeven_depth"] for cat, row in breakeven_table(panel, curves).items()}
    cells = build_candidates(panel, counterfactual, curves, caps)
    reference = blanket(cells, 0.15, curves)
    rng = np.random.default_rng(seed)

    scenarios = {}
    for name, share in (("tight", 0.10), ("loose", 0.50)):
        scenarios[name] = _policy_table(cells, curves, share * reference["spend"], rng)

    loose = scenarios["loose"]
    vs_blanket = {
        "profit_delta_rub": round(loose["optimised"]["profit_rub"] - reference["profit"], 1),
        "spend_delta_rub": round(loose["optimised"]["spend_rub"] - reference["spend"], 1),
        "profit_per_ruble_blanket": round(reference["profit"] / max(reference["spend"], 1e-9), 4),
        "profit_per_ruble_optimised": round(
            loose["optimised"]["profit_rub"] / max(loose["optimised"]["spend_rub"], 1e-9), 4
        ),
    }

    small_budget = 0.25 * loose["budget_rub"]
    small_subset = cells.head(5)
    greedy_small = greedy(option_table(small_subset, curves), small_budget)
    brute = brute_force(small_subset, small_budget, curves)
    gap = (
        (brute["profit"] - greedy_small["profit"]) / abs(brute["profit"])
        if brute["profit"]
        else 0.0
    )

    robustness = []
    base_choices = {row for row, _ in loose["_choices"]}
    for shock in (0.85, 1.15):
        shocked = cells.copy()
        shocked["multiplier"] = shocked["multiplier"] * shock
        alt = greedy(option_table(shocked, curves), loose["budget_rub"])
        alt_choices = {row for row, _ in alt["choices"]}
        changed = len(base_choices ^ alt_choices) / max(len(base_choices), 1)
        robustness.append(
            {
                "shock": shock,
                "cells_selected": int(alt["cells"]),
                "profit_rub": round(float(alt["profit"]), 1),
                "selection_changed_share": round(float(changed), 4),
            }
        )

    for scenario in scenarios.values():
        scenario.pop("_choices", None)

    return {
        "planning_week": int(cells["week"].max()),
        "candidates": int(len(cells)),
        "depth_cap_by_category": {k: round(float(v), 3) for k, v in caps.items()},
        "blanket_15": {
            "spend_rub": round(reference["spend"], 1),
            "profit_rub": round(reference["profit"], 1),
            "cells": reference["cells"],
            "profit_per_ruble": round(reference["profit"] / max(reference["spend"], 1e-9), 4),
        },
        "scenarios": scenarios,
        "vs_blanket": vs_blanket,
        "heuristic_check": {
            "budget_rub": round(small_budget, 1),
            "cells": 5,
            "greedy_profit_rub": round(float(greedy_small["profit"]), 1),
            "brute_force_profit_rub": round(float(brute["profit"]), 1),
            "gap": round(float(gap), 4),
        },
        "robustness": robustness,
    }
