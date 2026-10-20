"""Three counterfactuals, scored against the answer key.

The task is always the same: predict what a cell would have sold **without any
promo**, then read lift as ``actual - counterfactual``.

    naive_mean       mean of the previous 4 non-promo weeks (the anti-pattern)
    forecast         log-linear ridge: store + SKU effects, seasonality, price
    matched_control  DiD against non-promoted stores, same SKU and format

Promo assignment is confounded, so ``naive_mean`` is expected to be biased;
the size of that bias is the first finding of the project.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.linear_model import Ridge
from sklearn.preprocessing import OneHotEncoder

from config import Config

KEY = ["store_id", "sku_id", "week"]
EPS = 1e-9


@dataclass(frozen=True)
class Grid:
    """Balanced store x SKU x week cube plus the code maps."""

    shape: tuple[int, int, int]
    store: np.ndarray
    sku: np.ndarray
    week: np.ndarray
    format_of_store: np.ndarray
    category_of_sku: np.ndarray

    @property
    def size(self) -> int:
        return int(np.prod(self.shape))


def make_grid(panel: pd.DataFrame) -> Grid:
    stores = pd.Index(sorted(panel["store_id"].unique()))
    skus = pd.Index(sorted(panel["sku_id"].unique()))
    weeks = pd.Index(sorted(panel["week"].unique()))
    s = stores.get_indexer(panel["store_id"])
    k = skus.get_indexer(panel["sku_id"])
    w = weeks.get_indexer(panel["week"])
    shape = (len(stores), len(skus), len(weeks))
    if len(panel) != int(np.prod(shape)):
        raise ValueError("panel is not a balanced store x SKU x week grid")
    fmt = panel.drop_duplicates("store_id").sort_values("store_id")["format"].to_numpy()
    cat = panel.drop_duplicates("sku_id").sort_values("sku_id")["category"].to_numpy()
    return Grid(shape, s, k, w, fmt, cat)


def to_cube(grid: Grid, values: np.ndarray, fill: float = np.nan) -> np.ndarray:
    cube = np.full(grid.shape, fill, dtype=float)
    cube[grid.store, grid.sku, grid.week] = values
    return cube


def from_cube(grid: Grid, cube: np.ndarray) -> np.ndarray:
    return cube[grid.store, grid.sku, grid.week]


def _rolling_prior_mean(cube: np.ndarray, valid: np.ndarray, window: int) -> np.ndarray:
    """Mean of the previous ``window`` valid weeks, never the current week."""
    total = np.zeros_like(cube)
    count = np.zeros_like(cube)
    for lag in range(1, window + 1):
        shifted = np.full_like(cube, np.nan)
        shifted[:, :, lag:] = cube[:, :, :-lag]
        ok = valid[:, :, lag:] & ~np.isnan(shifted[:, :, lag:])
        clean = np.nan_to_num(shifted)
        total[:, :, lag:] += clean[:, :, lag:]
        count[:, :, lag:] += ok
    return np.divide(total, count, out=np.full_like(cube, np.nan), where=count > 0)


def _fill_fallback(
    estimate: np.ndarray, observed: np.ndarray, valid: np.ndarray, grid: Grid
) -> np.ndarray:
    """Fill gaps: store x category x week, then category x week, then week."""
    out = estimate.copy()
    s, k, w = np.nonzero(valid)
    known = pd.DataFrame(
        {
            "store": s,
            "cat": grid.category_of_sku[k],
            "week": w,
            "y": observed[s, k, w],
        }
    )
    miss = np.isnan(out)
    ms, mk, mw = np.nonzero(miss)
    pending = pd.DataFrame(
        {"store": ms, "cat": grid.category_of_sku[mk], "week": mw, "row": np.arange(len(ms))}
    )
    for cols in (["store", "cat", "week"], ["cat", "week"], ["week"]):
        todo = pending[np.isnan(out[ms, mk, mw])] if len(pending) else pending
        if todo.empty:
            break
        means = known.groupby(cols)["y"].mean().rename("fill")
        filled = todo.merge(means, left_on=cols, right_index=True, how="left")
        ok = filled["fill"].notna().to_numpy()
        rows = filled["row"].to_numpy()[ok]
        out[ms[rows], mk[rows], mw[rows]] = filled["fill"].to_numpy()[ok]
    out[np.isnan(out)] = float(np.nanmean(observed[valid]))
    return out


def naive_counterfactual(panel: pd.DataFrame, grid: Grid, window: int = 4) -> np.ndarray:
    units = to_cube(grid, panel["units_sold"].to_numpy())
    promo = to_cube(grid, panel["promo_flag"].to_numpy()).astype(bool)
    prior = _rolling_prior_mean(units, ~promo, window)
    filled = _fill_fallback(prior, units, ~promo, grid)
    return from_cube(grid, filled)


def history_features(panel: pd.DataFrame, grid: Grid) -> pd.DataFrame:
    """Promo-free history: the last clean level, how stale it is, and a smoothed carry.

    Promo weeks are excluded from the carry so the counterfactual is not fed the
    effect it is supposed to measure; ``gap`` tells the model how fast to decay it.
    """
    units = to_cube(grid, panel["units_sold"].to_numpy())
    promo = to_cube(grid, panel["promo_flag"].to_numpy()).astype(bool)
    n_w = grid.shape[2]
    level = np.full(grid.shape, np.nan)
    smooth = np.full(grid.shape, np.nan)
    gap = np.full(grid.shape, np.nan)

    for w in range(1, n_w):
        was_promo = promo[:, :, w - 1]
        level[:, :, w] = np.where(was_promo, level[:, :, w - 1], units[:, :, w - 1])
        smooth[:, :, w] = np.where(
            was_promo,
            smooth[:, :, w - 1],
            0.6 * units[:, :, w - 1] + 0.4 * np.nan_to_num(smooth[:, :, w - 1]),
        )
        gap[:, :, w] = np.where(was_promo, gap[:, :, w - 1] + 1, 1)

    level_flat = from_cube(grid, level)
    smooth_flat = from_cube(grid, smooth)
    gap_flat = from_cube(grid, gap)
    has_history = (~np.isnan(level_flat)).astype(float)
    fill = np.nanmedian(level_flat) if np.isfinite(level_flat).any() else 0.0
    return pd.DataFrame(
        {
            "log_last_clean": np.log1p(np.nan_to_num(level_flat, nan=fill)),
            "log_smooth": np.log1p(np.nan_to_num(smooth_flat, nan=fill)),
            "gap": np.nan_to_num(gap_flat, nan=8.0),
            "has_history": has_history,
        },
        index=panel.index,
    )


def _calendar_features(weeks: np.ndarray) -> np.ndarray:
    w = weeks.astype(float)
    season = 2 * np.pi * w / 52.0
    holiday = np.isin(weeks % 52, (0, 1, 51)).astype(float)
    return np.column_stack(
        [
            w,
            np.sin(season),
            np.cos(season),
            np.sin(2 * season),
            np.cos(2 * season),
            holiday,
        ]
    )


def _design(
    frame: pd.DataFrame, encoder: OneHotEncoder | None = None, fit: bool = False
) -> tuple[sparse.csr_matrix, OneHotEncoder, list[str]]:
    cats = frame[["store_id", "sku_id"]].astype(str)
    if encoder is None:
        encoder = OneHotEncoder(handle_unknown="ignore", sparse_output=True)
    dummies = encoder.fit_transform(cats) if fit else encoder.transform(cats)
    calendar = _calendar_features(frame["week"].to_numpy())
    numeric = np.column_stack(
        [
            calendar,
            np.log(frame["list_price"].to_numpy()),
            np.log(frame["list_price"].to_numpy())
            / frame.groupby("sku_id")["list_price"].transform("mean").to_numpy(),
            frame["log_last_clean"].to_numpy(),
            frame["log_smooth"].to_numpy(),
            frame["gap"].to_numpy(),
            frame["has_history"].to_numpy(),
        ]
    )
    design = sparse.hstack([dummies, sparse.csr_matrix(numeric)], format="csr")
    names = [f"cat_{i}" for i in range(dummies.shape[1])] + [
        "week",
        "sin1",
        "cos1",
        "sin2",
        "cos2",
        "holiday",
        "log_price",
        "log_price_rel",
        "log_last_clean",
        "log_smooth",
        "gap",
        "has_history",
    ]
    return design, encoder, names


def forecast_counterfactual(
    panel: pd.DataFrame, grid: Grid, holdout_weeks: int = 16
) -> tuple[np.ndarray, dict]:
    """Log-linear ridge trained only on non-promo cells; predicts the promo-free level."""
    hist = history_features(panel, grid)
    frame = pd.concat(
        [panel.loc[~panel["promo_flag"]].copy(), hist.loc[~panel["promo_flag"]]], axis=1
    )
    frame["y"] = np.log1p(frame["units_sold"])
    last_week = int(panel["week"].max())
    train = frame[frame["week"] <= last_week - holdout_weeks]
    holdout = frame[frame["week"] > last_week - holdout_weeks]

    x_train, encoder, names = _design(train, fit=True)
    model = Ridge(alpha=1.0, solver="lsqr")
    model.fit(x_train, train["y"].to_numpy())

    x_hold, _, _ = _design(holdout, encoder)
    pred_hold = np.clip(np.expm1(model.predict(x_hold)), 0.0, None)
    y_hold = holdout["units_sold"].to_numpy()
    wape = float(np.abs(y_hold - pred_hold).sum() / max(y_hold.sum(), EPS))

    x_all, _, _ = _design(frame, encoder)
    full = Ridge(alpha=1.0, solver="lsqr").fit(x_all, frame["y"].to_numpy())

    scoring = pd.concat([panel, hist], axis=1)
    pred = np.clip(np.expm1(full.predict(_design(scoring, encoder)[0])), 0.0, None)
    info = {
        "model": "ridge_log1p",
        "alpha": 1.0,
        "n_features": int(len(names)),
        "train_rows": int(len(train)),
        "holdout_rows": int(len(holdout)),
        "holdout_wape": round(wape, 4),
        "holdout_weeks": holdout_weeks,
    }
    return pred, info


def matched_control_counterfactual(panel: pd.DataFrame, grid: Grid, window: int = 4) -> np.ndarray:
    """DiD: event store's pre-level x growth of non-promoted peers (same SKU + format)."""
    units = to_cube(grid, panel["units_sold"].to_numpy())
    promo = to_cube(grid, panel["promo_flag"].to_numpy()).astype(bool)
    pre = _rolling_prior_mean(units, ~promo, window)
    pre = _fill_fallback(pre, units, ~promo, grid)

    n_s, n_k, n_w = grid.shape
    fmt_codes = pd.Categorical(grid.format_of_store).codes
    estimate = np.full(grid.shape, np.nan)

    for f in np.unique(fmt_codes):
        stores_f = np.where(fmt_codes == f)[0]
        control_mask = np.zeros(n_s, dtype=bool)
        control_mask[stores_f] = True
        control_post = np.full((n_k, n_w), np.nan)
        control_pre = np.full((n_k, n_w), np.nan)
        for k in range(n_k):
            block_post = units[control_mask, k, :]
            block_pre = pre[control_mask, k, :]
            clean = ~promo[control_mask, k, :]
            with np.errstate(invalid="ignore"):
                control_post[k] = (
                    np.where(clean, block_post, np.nan).mean(axis=0) if clean.any() else np.nan
                )
                control_pre[k] = (
                    np.where(clean, block_pre, np.nan).mean(axis=0) if clean.any() else np.nan
                )
        delta = control_post - control_pre
        block = pre[control_mask, :, :] + delta[None, :, :]
        estimate[control_mask] = block

    # Fallback: delta across all formats, then the naive pre-level.
    delta_all = np.full((n_k, n_w), np.nan)
    for k in range(n_k):
        clean = ~promo[:, k, :]
        post = np.where(clean, units[:, k, :], np.nan)
        pre_clean = np.where(clean, pre[:, k, :], np.nan)
        with np.errstate(invalid="ignore"):
            delta_all[k] = np.nanmean(post, axis=0) - np.nanmean(pre_clean, axis=0)
    missing = np.isnan(estimate)
    estimate[missing] = (pre + delta_all[None, :, :])[missing]
    estimate[np.isnan(estimate)] = pre[np.isnan(estimate)]
    return np.clip(from_cube(grid, estimate), 0.0, None)


def promo_placebo_mask(panel: pd.DataFrame, grid: Grid, window: int = 2) -> np.ndarray:
    """Non-promo cells with no promo for this store-SKU within +/- ``window`` weeks."""
    promo = to_cube(grid, panel["promo_flag"].to_numpy()).astype(bool)
    near = promo.copy()
    for lag in range(1, window + 1):
        near[:, :, lag:] |= promo[:, :, :-lag]
        near[:, :, :-lag] |= promo[:, :, lag:]
    return from_cube(grid, ~near)


def evaluate(
    name: str,
    panel: pd.DataFrame,
    grid: Grid,
    baseline_hat: np.ndarray,
    truth_base: np.ndarray,
    rng: np.random.Generator,
    placebo_size: int = 20000,
) -> dict:
    actual = panel["units_sold"].to_numpy()
    promo = panel["promo_flag"].to_numpy().astype(bool)
    truth_lift = actual - truth_base
    lift_hat = actual - baseline_hat

    # Baseline accuracy where the promo-free level is directly observable.
    quiet = ~promo
    wape = float(np.abs(baseline_hat[quiet] - truth_base[quiet]).sum() / truth_base[quiet].sum())
    wape_sold = float(np.abs(baseline_hat[quiet] - actual[quiet]).sum() / actual[quiet].sum())

    diff = lift_hat[promo] - truth_lift[promo]
    bias_units = float(diff.mean())
    bias_pct = float(diff.sum() / max(truth_lift[promo].sum(), EPS))

    placebo_idx = np.flatnonzero(promo_placebo_mask(panel, grid))
    if len(placebo_idx) > placebo_size:
        placebo_idx = rng.choice(placebo_idx, size=placebo_size, replace=False)
    rel = lift_hat[placebo_idx] / np.maximum(baseline_hat[placebo_idx], EPS)
    within = float(np.mean(np.abs(rel) <= 0.02))

    by_category = {}
    for cat in sorted(panel["category"].unique()):
        mask = promo & (panel["category"].to_numpy() == cat)
        if mask.sum() == 0:
            continue
        d = lift_hat[mask] - truth_lift[mask]
        by_category[cat] = {
            "bias_units": round(float(d.mean()), 3),
            "bias_pct": round(float(d.sum() / max(truth_lift[mask].sum(), EPS)), 4),
        }

    return {
        "estimator": name,
        "baseline_wape_vs_truth": round(wape, 4),
        "baseline_wape_vs_sales": round(wape_sold, 4),
        "promo_bias_units": round(bias_units, 3),
        "promo_bias_pct": round(bias_pct, 4),
        "placebo_cells": int(len(placebo_idx)),
        "placebo_within_2pct": round(within, 4),
        "placebo_p05": round(float(np.percentile(rel, 5)), 4),
        "placebo_p50": round(float(np.percentile(rel, 50)), 4),
        "placebo_p95": round(float(np.percentile(rel, 95)), 4),
        "by_category": by_category,
    }


def run(panel: pd.DataFrame, truth: pd.DataFrame, cfg: Config) -> dict:
    grid = make_grid(panel)
    truth_base = truth.sort_values(KEY).reset_index(drop=True)["truth_base_units"].to_numpy()
    rng = np.random.default_rng(cfg.seed)

    naive = naive_counterfactual(panel, grid)
    forecast, forecast_info = forecast_counterfactual(panel, grid)
    matched = matched_control_counterfactual(panel, grid)

    results = {}
    for name, hat in (
        ("naive_mean", naive),
        ("forecast", forecast),
        ("matched_control", matched),
    ):
        results[name] = evaluate(name, panel, grid, hat, truth_base, rng)
        results[name]["baseline_units"] = round(float(hat.sum()), 1)

    best = min(
        ("naive_mean", "forecast", "matched_control"),
        key=lambda n: (abs(results[n]["promo_bias_pct"]), results[n]["baseline_wape_vs_truth"]),
    )
    headline = {
        "best_by_abs_bias": best,
        "bias_pct": {
            "naive_mean": results["naive_mean"]["promo_bias_pct"],
            "forecast": results["forecast"]["promo_bias_pct"],
            "matched_control": results["matched_control"]["promo_bias_pct"],
        },
        "wape": {
            "naive_mean": results["naive_mean"]["baseline_wape_vs_truth"],
            "forecast": results["forecast"]["baseline_wape_vs_truth"],
            "matched_control": results["matched_control"]["baseline_wape_vs_truth"],
        },
        "bias_gap_pp": round(
            results["naive_mean"]["promo_bias_pct"] - results["forecast"]["promo_bias_pct"], 4
        ),
        "bias_reduction_x": round(
            abs(results["naive_mean"]["promo_bias_pct"])
            / max(abs(results["forecast"]["promo_bias_pct"]), EPS),
            2,
        ),
        "wape_reduction_x": round(
            results["naive_mean"]["baseline_wape_vs_truth"]
            / max(results["forecast"]["baseline_wape_vs_truth"], EPS),
            2,
        ),
        "promo_cells": int(panel["promo_flag"].sum()),
        "true_lift_units": round(
            float((panel["units_sold"] - truth_base)[panel["promo_flag"]].sum()), 1
        ),
    }
    counterfactual = panel[KEY].copy()
    counterfactual["baseline"] = forecast
    return {
        "forecast_model": forecast_info,
        "estimators": results,
        "headline": headline,
        "counterfactual": counterfactual,
    }
