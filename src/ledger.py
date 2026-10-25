"""Lift ledger and promo P&L.

Unit of accounting: a **wave** = (store, week, category) with at least one
promoted SKU. Waves avoid double counting when several SKUs in one category are
promoted in the same store-week: each non-promo cell is attributed once.

    net_units = own            (promoted SKUs, promo week, vs counterfactual)
              + pantry         (same SKUs, next 1-3 weeks, <= 0)
              + cannibalization(non-promo SKUs, same category-week, <= 0)
              + halo           (non-promo SKUs, complementary category, >= 0)
              + network_shift  (same SKUs, other stores, allocated by lift share)

``network_shift`` is where cross-format traffic lands; it also absorbs any
same-format cross-store effect, which is why it is not called "cross-format".

Money: every unit is valued at its own realised price, so a discount is a price
cut, not a separate subtraction. Supplier funding is added back explicitly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import CATEGORIES, CM_RATE
from dgp import COMPLEMENTS

KEY = ["store_id", "sku_id", "week"]
WAVE = ["store_id", "week", "category"]
PAIR = {CATEGORIES[i]: CATEGORIES[j] for i, j in COMPLEMENTS.items()}
EPS = 1e-9


def build_waves(panel: pd.DataFrame, counterfactual: pd.DataFrame) -> pd.DataFrame:
    df = panel.merge(counterfactual, on=KEY, how="left", validate="one_to_one")
    if df["baseline"].isna().any():
        raise ValueError("counterfactual is missing cells")
    df["dev_units"] = df["units_sold"] - df["baseline"]
    df["cost_unit"] = df["list_price"] * (1.0 - df["cm_rate"])
    df["dev_revenue"] = df["revenue"] - df["baseline"] * df["unit_price"]
    # Profit is not "incremental units x margin": the units that would have sold
    # at full price also lose margin when they sell at a discount.
    profit_actual = df["units_sold"] * (df["unit_price"] - df["cost_unit"]) + df["supplier_funding"]
    profit_baseline = df["baseline"] * (df["list_price"] - df["cost_unit"])
    df["dev_profit"] = profit_actual - profit_baseline

    waves = (
        df[df["promo_flag"]]
        .groupby(WAVE, as_index=False)
        .agg(
            own_units=("dev_units", "sum"),
            own_profit=("dev_profit", "sum"),
            revenue_delta=("dev_revenue", "sum"),
            discount_cost=("discount_cost", "sum"),
            supplier_funding=("supplier_funding", "sum"),
            promoted_skus=("sku_id", "nunique"),
            depth_mean=("promo_depth", "mean"),
        )
        .reset_index(drop=True)
    )
    for column in ("pantry_units", "cannibalization_units", "halo_units", "network_units"):
        waves[column] = 0.0
    for column in ("pantry_profit", "cannibalization_profit", "halo_profit", "network_profit"):
        waves[column] = 0.0

    # --- pantry: same store-SKU, next 1..3 weeks, no new promo --------------
    # The drag is booked on the *origin* wave, not on the lagged week: grouping
    # by the shifted week silently dropped every lag-2/lag-3 row (no wave exists
    # there) and flipped the bucket's sign.
    promo = df.loc[df["promo_flag"], ["store_id", "sku_id", "week", "category"]].copy()
    for lag in (1, 2, 3):
        q = promo.copy()
        q["origin_week"] = q["week"]
        q["week"] = q["week"] + lag
        q = q.merge(df[KEY + ["dev_units", "dev_profit", "promo_flag"]], on=KEY, how="left")
        q["promo_flag"] = q["promo_flag"].fillna(False).astype(bool)
        q = q[~q["promo_flag"]]
        q["week"] = q["origin_week"]
        agg = (
            q.groupby(WAVE, as_index=False)[["dev_units", "dev_profit"]]
            .sum()
            .rename(columns={"dev_units": "u", "dev_profit": "p"})
        )
        merged = waves[WAVE].merge(agg, on=WAVE, how="left").fillna({"u": 0.0, "p": 0.0})
        waves["pantry_units"] += merged["u"].to_numpy()
        waves["pantry_profit"] += merged["p"].to_numpy()

    quiet = df.loc[~df["promo_flag"]]

    # --- cannibalization: non-promo SKUs in the same category-week ----------
    cannib = (
        quiet.groupby(WAVE, as_index=False)[["dev_units", "dev_profit"]]
        .sum()
        .rename(columns={"dev_units": "u", "dev_profit": "p"})
    )
    merged = waves[WAVE].merge(cannib, on=WAVE, how="left").fillna({"u": 0.0, "p": 0.0})
    waves["cannibalization_units"] = -merged["u"].to_numpy()
    waves["cannibalization_profit"] = -merged["p"].to_numpy()

    # --- halo: non-promo SKUs in the complementary category -----------------
    halo = (
        quiet.groupby(WAVE, as_index=False)[["dev_units", "dev_profit"]]
        .sum()
        .rename(columns={"dev_units": "u", "dev_profit": "p"})
    )
    halo["category"] = halo["category"].map(PAIR)
    halo = halo.dropna(subset=["category"])
    merged = waves[WAVE].merge(halo, on=WAVE, how="left").fillna({"u": 0.0, "p": 0.0})
    waves["halo_units"] = merged["u"].to_numpy()
    waves["halo_profit"] = merged["p"].to_numpy()

    # --- network shift: same SKU-week in other stores, share = lift share ---
    promoted = df.loc[df["promo_flag"], ["store_id", "sku_id", "week", "category"]].copy()
    promoted["own_pos"] = df.loc[df["promo_flag"], "dev_units"].clip(lower=0).to_numpy()
    total_pos = promoted.groupby(["sku_id", "week"])["own_pos"].transform("sum")
    promoted["share"] = np.where(total_pos > 0, promoted["own_pos"] / total_pos, 0.0)

    loss = (
        quiet.groupby(["sku_id", "week"], as_index=False)[["dev_units", "dev_profit"]]
        .sum()
        .rename(columns={"dev_units": "loss_units", "dev_profit": "loss_profit"})
    )
    promoted = promoted.merge(loss, on=["sku_id", "week"], how="left").fillna(
        {"loss_units": 0.0, "loss_profit": 0.0}
    )
    promoted["network_units"] = -promoted["loss_units"] * promoted["share"]
    promoted["network_profit"] = -promoted["loss_profit"] * promoted["share"]
    network = promoted.groupby(WAVE, as_index=False)[["network_units", "network_profit"]].sum()
    merged = (
        waves[WAVE]
        .merge(network, on=WAVE, how="left")
        .fillna({"network_units": 0.0, "network_profit": 0.0})
    )
    waves["network_units"] = merged["network_units"].to_numpy()
    waves["network_profit"] = merged["network_profit"].to_numpy()

    waves["net_units"] = waves[
        ["own_units", "pantry_units", "cannibalization_units", "halo_units"]
    ].sum(axis=1)
    waves["net_profit"] = waves[
        ["own_profit", "pantry_profit", "cannibalization_profit", "halo_profit"]
    ].sum(axis=1)
    # ``network_units`` stays as a diagnostic: cross-format traffic nets to zero
    # across the chain, so any residual here is baseline error, not a real leak.
    return waves.sort_values(WAVE).reset_index(drop=True)


def _truth_component(panel: pd.DataFrame, truth: pd.DataFrame, column: str, scope: str) -> float:
    df = panel.merge(truth, on=KEY, how="left", validate="one_to_one")
    promo = df["promo_flag"]
    if scope == "own":
        return float(df.loc[promo, column].sum())
    if scope == "pantry":
        total = 0.0
        src = df.loc[promo, ["store_id", "sku_id", "week"]]
        for lag in (1, 2, 3):
            q = src.copy()
            q["week"] = q["week"] + lag
            q = q.merge(df[KEY + ["promo_flag", column]], on=KEY, how="left")
            q["promo_flag"] = q["promo_flag"].fillna(False).astype(bool)
            q = q[~q["promo_flag"]]
            total += float(q[column].sum())
        return total
    if scope in ("cannibalization", "halo", "network"):
        return float(df.loc[~promo, column].sum())
    raise ValueError(f"unknown scope {scope}")


def fit_response(panel: pd.DataFrame, counterfactual: pd.DataFrame) -> dict:
    """Relative lift m(d) = A * (1 - exp(-k d)), fitted per category on promo cells."""
    cells = panel.loc[panel["promo_flag"], ["category", "promo_depth"]].copy()
    baseline = (
        counterfactual.set_index(KEY)["baseline"]
        .reindex(pd.MultiIndex.from_frame(panel.loc[panel["promo_flag"], KEY]))
        .to_numpy()
    )
    cells["rel_lift"] = panel.loc[panel["promo_flag"], "units_sold"].to_numpy() / baseline - 1.0
    curves = {}
    for cat in CATEGORIES:
        block = cells[(cells["category"] == cat) & (cells["rel_lift"].between(-0.5, 5.0))]
        if len(block) < 50:
            continue
        # Bin by depth before fitting: per-cell lift is too noisy for a curve.
        block = block.assign(bucket=pd.qcut(block["promo_depth"], 20, duplicates="drop"))
        binned = block.groupby("bucket", observed=True).agg(
            depth=("promo_depth", "median"), lift=("rel_lift", "mean")
        )
        x = binned["depth"].to_numpy()
        y = binned["lift"].to_numpy()
        best = None
        for k in np.linspace(1.5, 8.0, 27):
            f = 1.0 - np.exp(-k * x)
            amplitude = float(f @ y / max(f @ f, EPS))
            sse = float(((y - amplitude * f) ** 2).sum())
            if best is None or sse < best[0]:
                best = (sse, k, amplitude)
        assert best is not None
        _, k, amplitude = best
        ss_tot = float(((y - y.mean()) ** 2).sum())
        curves[cat] = {
            "k": round(float(k), 3),
            "amplitude": round(float(amplitude), 4),
            "r2": round(1.0 - best[0] / max(ss_tot, EPS), 4),
            "n": int(len(block)),
            "bins": int(len(binned)),
        }
    return curves


def breakeven_table(panel: pd.DataFrame, curves: dict, cm_by_cat: dict | None = None) -> dict:
    """Depth at which incremental contribution margin stops being positive."""
    table = {}
    grid = np.round(np.arange(0.01, 0.51, 0.005), 4)
    cm_by_cat = cm_by_cat or dict(zip(CATEGORIES, CM_RATE, strict=True))
    for cat, curve in curves.items():
        funded = float(panel.loc[panel["category"] == cat, "funded_share"].median())
        cm = float(cm_by_cat[cat])
        profit = np.array(
            [
                (1.0 + curve["amplitude"] * (1.0 - np.exp(-curve["k"] * d)))
                * (cm - d * (1.0 - funded))
                - cm
                for d in grid
            ]
        )
        profitable = grid[profit > 0]
        table[cat] = {
            "cm_rate": round(cm, 3),
            "supplier_funding": round(funded, 3),
            "breakeven_depth": round(float(profitable.max()), 3) if len(profitable) else 0.0,
            "best_depth": round(float(grid[int(profit.argmax())]), 3),
            "best_profit_per_base_unit": round(float(profit.max()), 4),
            "profit_at_10pct": round(float(np.interp(0.10, grid, profit)), 4),
            "profit_at_25pct": round(float(np.interp(0.25, grid, profit)), 4),
        }
    return table


def summarise(waves: pd.DataFrame, panel: pd.DataFrame, curves: dict) -> dict:
    own = float(waves["own_units"].sum())
    net = float(waves["net_units"].sum())
    return {
        "waves": int(len(waves)),
        "promoted_cells": int(panel["promo_flag"].sum()),
        "own_lift_units": round(own, 1),
        "net_lift_units": round(net, 1),
        "pantry_units": round(float(waves["pantry_units"].sum()), 1),
        "cannibalization_units": round(float(waves["cannibalization_units"].sum()), 1),
        "halo_units": round(float(waves["halo_units"].sum()), 1),
        "network_shift_units": round(float(waves["network_units"].sum()), 1),
        "revenue_delta_rub": round(float(waves["revenue_delta"].sum()), 1),
        "net_profit_rub": round(float(waves["net_profit"].sum()), 1),
        "discount_cost_rub": round(float(waves["discount_cost"].sum()), 1),
        "supplier_funding_rub": round(float(waves["supplier_funding"].sum()), 1),
        "share_waves_negative_profit": round(float((waves["net_profit"] < 0).mean()), 4),
        "share_revenue_up_profit_down": round(
            float(((waves["revenue_delta"] > 0) & (waves["net_profit"] < 0)).mean()), 4
        ),
        "median_net_profit_rub": round(float(waves["net_profit"].median()), 1),
        "leak_share": round(float(1.0 - net / own) if own else 0.0, 4),
        "response_curves": curves,
    }


def pnl_bridge(panel: pd.DataFrame, counterfactual: pd.DataFrame, waves: pd.DataFrame) -> dict:
    """Exact decomposition of net profit into volume margin and discount cost.

    ``own_profit = sum[(U - B) p c] - sum[U d (1 - f) p]`` holds per cell, so the
    two lines below add up to the promo-cell profit by construction, and adding
    the spillover buckets reproduces ``net_profit_rub``.
    """
    df = panel.merge(counterfactual, on=KEY, how="left", validate="one_to_one")
    cell = df[df["promo_flag"]]
    units = cell["units_sold"].to_numpy()
    base = cell["baseline"].to_numpy()
    price = cell["list_price"].to_numpy()
    cm = cell["cm_rate"].to_numpy()
    depth = cell["promo_depth"].to_numpy()
    funded = cell["funded_share"].to_numpy()

    volume = float((((units - base) * price) * cm).sum())
    discount = -float((((units * depth) * price) * (1.0 - funded)).sum())
    spillover = float(
        waves[["pantry_profit", "cannibalization_profit", "halo_profit"]].sum().sum()
    )
    return {
        "margin_on_incremental_units_rub": round(volume, 1),
        "discount_net_of_supplier_funding_rub": round(discount, 1),
        "promo_cells_profit_rub": round(volume + discount, 1),
        "spillover_profit_rub": round(spillover, 1),
        "net_profit_rub": round(volume + discount + spillover, 1),
    }


def run(panel: pd.DataFrame, counterfactual: pd.DataFrame, truth: pd.DataFrame) -> dict:
    waves = build_waves(panel, counterfactual)
    curves = fit_response(panel, counterfactual)
    summary = summarise(waves, panel, curves)
    summary["breakeven"] = breakeven_table(panel, curves)
    summary["pnl_bridge"] = pnl_bridge(panel, counterfactual, waves)

    oracle_cf = panel[KEY].copy()
    oracle_cf["baseline"] = truth.sort_values(KEY)["truth_base_units"].to_numpy()
    oracle = build_waves(panel, oracle_cf)

    buckets = {
        "own_units": "own_units",
        "pantry_units": "pantry_units",
        "cannibalization_units": "cannibalization_units",
        "halo_units": "halo_units",
        "net_units": "net_units",
    }
    reconciliation = {}
    for label, column in buckets.items():
        estimated = float(waves[column].sum())
        true_value = float(oracle[column].sum())
        reconciliation[label] = {
            "estimated": round(estimated, 1),
            "oracle": round(true_value, 1),
            "error_pct": round((estimated - true_value) / abs(true_value), 4)
            if true_value
            else 0.0,
        }
    estimated_profit = float(waves["net_profit"].sum())
    true_profit = float(oracle["net_profit"].sum())
    reconciliation["net_profit_rub"] = {
        "estimated": round(estimated_profit, 1),
        "oracle": round(true_profit, 1),
        "error_pct": round((estimated_profit - true_profit) / abs(true_profit), 4)
        if true_profit
        else 0.0,
    }
    reconciliation["share_waves_negative_profit"] = {
        "estimated": round(float((waves["net_profit"] < 0).mean()), 4),
        "oracle": round(float((oracle["net_profit"] < 0).mean()), 4),
    }
    summary["reconciliation"] = reconciliation
    summary["network_shift_units"] = round(float(waves["network_units"].sum()), 1)
    return {"waves": waves, "summary": summary}
