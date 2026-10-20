"""Promo response model, scored as a decision, not as a curve.

The target is incremental contribution margin per promoted cell (store x SKU x
week). The question is not "how good is Qini" but "which policy makes more money
at the same capacity":

    random        k random cells
    qini_rank     top-k by model score (rank only)
    threshold     only cells the model says are profitable, capped at k
    oracle        top-k by the true outcome (the ceiling)
    none          do not promote

A ranking metric can prefer a policy that loses money, because rank ignores the
level. That hypothesis is tested here, not asserted.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from baseline import history_features, make_grid

KEY = ["store_id", "sku_id", "week"]
CAT_FEATURES = ["store_id", "sku_id", "category", "format"]
NUM_FEATURES = [
    "promo_depth",
    "mechanic",
    "cm_rate",
    "funded_share",
    "list_price",
    "week",
    "sin1",
    "cos1",
    "sin2",
    "cos2",
    "holiday",
    "log_last_clean",
    "log_smooth",
    "gap",
    "has_history",
]
FEATURES = CAT_FEATURES + NUM_FEATURES


def build_frame(panel: pd.DataFrame, counterfactual: pd.DataFrame) -> pd.DataFrame:
    df = panel.merge(counterfactual, on=KEY, how="left", validate="one_to_one")
    if df["baseline"].isna().any():
        raise ValueError("counterfactual is missing cells")
    cost = df["list_price"] * (1.0 - df["cm_rate"])
    profit = df["units_sold"] * (df["unit_price"] - cost) + df["supplier_funding"]
    baseline_profit = df["baseline"] * (df["list_price"] - cost)
    df["dev_profit"] = profit - baseline_profit

    hist = history_features(panel, make_grid(panel))
    week = df["week"].to_numpy().astype(float)
    season = 2 * np.pi * week / 52.0
    df["sin1"] = np.sin(season)
    df["cos1"] = np.cos(season)
    df["sin2"] = np.sin(2 * season)
    df["cos2"] = np.cos(2 * season)
    df["holiday"] = np.isin(df["week"].to_numpy() % 52, (0, 1, 51)).astype(float)
    for column in ("log_last_clean", "log_smooth", "gap", "has_history"):
        df[column] = hist[column].to_numpy()
    return df.loc[df["promo_flag"]].reset_index(drop=True)


def _matrix(frame: pd.DataFrame) -> tuple[np.ndarray, list[int], dict[str, dict[int, str]]]:
    x = pd.DataFrame(index=frame.index)
    maps: dict[str, dict[int, str]] = {}
    for column in CAT_FEATURES:
        codes = frame[column].astype("category").cat.codes.to_numpy()
        x[column] = codes
        maps[column] = dict(enumerate(frame[column].astype("category").cat.categories))
    for column in NUM_FEATURES:
        x[column] = frame[column].to_numpy(dtype=float)
    cat_idx = [x.columns.get_loc(c) for c in CAT_FEATURES]
    return x.to_numpy(dtype=float), cat_idx, maps


def fit_predict(train: pd.DataFrame, test: pd.DataFrame, seed: int) -> np.ndarray:
    x_train, cat_idx, _ = _matrix(train)
    x_test, _, _ = _matrix(test)
    model = HistGradientBoostingRegressor(
        max_iter=400,
        learning_rate=0.05,
        max_leaf_nodes=31,
        l2_regularization=1.0,
        categorical_features=cat_idx,
        random_state=seed,
    )
    model.fit(x_train, train["dev_profit"].to_numpy())
    return model.predict(x_test)


def qini(y: np.ndarray, score: np.ndarray) -> dict:
    n = len(y)
    order = np.argsort(-score)
    cum = np.cumsum(y[order])
    frac = np.arange(1, n + 1) / n
    total = float(y.sum())
    random_curve = frac * total
    gain = cum - random_curve
    area = float(np.trapezoid(gain, frac))
    perfect_order = np.argsort(-y)
    perfect = np.cumsum(y[perfect_order]) - np.arange(1, n + 1) / n * total
    perfect_area = float(np.trapezoid(perfect, frac))
    coefficient = area / abs(perfect_area) if perfect_area else 0.0
    k = max(int(0.2 * n), 1)
    uplift_at_k = float(cum[k - 1] / k - total / n)
    return {
        "qini_coefficient": round(coefficient, 4),
        "auuc_rub": round(area, 1),
        "uplift_at_20pct_rub": round(uplift_at_k, 1),
        "test_total_rub": round(total, 1),
        "test_mean_rub": round(total / n, 1),
    }


def calibration(y: np.ndarray, score: np.ndarray, bins: int = 10) -> dict:
    frame = pd.DataFrame({"y": y, "score": score})
    frame["bucket"] = pd.qcut(frame["score"], bins, duplicates="drop", labels=False)
    table = (
        frame.groupby("bucket", observed=True)
        .agg(predicted=("score", "mean"), actual=("y", "mean"), cells=("y", "size"))
        .reset_index()
    )
    slope = float(np.polyfit(frame["score"], frame["y"], 1)[0])
    return {
        "slope": round(slope, 4),
        "bias_rub": round(float(frame["score"].mean() - frame["y"].mean()), 1),
        "deciles": [
            {
                "bucket": int(row.bucket),
                "predicted": round(float(row.predicted), 1),
                "actual": round(float(row.actual), 1),
                "cells": int(row.cells),
            }
            for row in table.itertuples()
        ],
    }


def policies(y: np.ndarray, score: np.ndarray, k: int, rng: np.random.Generator) -> dict:
    n = len(y)
    k = min(k, n)
    order = np.argsort(-score)
    rank_total = float(y[order[:k]].sum())
    oracle_topk = float(y[np.argsort(-y)[:k]].sum())
    positive = score > 0
    threshold_idx = np.where(positive)[0]
    if len(threshold_idx) > k:
        threshold_idx = threshold_idx[np.argsort(-score[threshold_idx])[:k]]
    threshold_total = float(y[threshold_idx].sum())
    oracle_idx = np.where(y > 0)[0]
    if len(oracle_idx) > k:
        oracle_idx = oracle_idx[np.argsort(-y[oracle_idx])[:k]]
    oracle_threshold = float(y[oracle_idx].sum())

    draws = [float(y[rng.choice(n, size=k, replace=False)].sum()) for _ in range(200)]
    random_total = float(np.mean(draws))
    random_ci = (float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5)))

    return {
        "capacity_cells": int(k),
        "capacity_share": round(k / n, 3),
        "random": {
            "total_rub": round(random_total, 1),
            "ci95": [round(random_ci[0], 1), round(random_ci[1], 1)],
            "cells": int(k),
        },
        "qini_rank": {
            "total_rub": round(rank_total, 1),
            "per_cell_rub": round(rank_total / k, 1),
            "cells": int(k),
        },
        "threshold": {
            "total_rub": round(threshold_total, 1),
            "per_cell_rub": round(threshold_total / max(len(threshold_idx), 1), 1),
            "cells": int(len(threshold_idx)),
        },
        "oracle_threshold": {
            "total_rub": round(oracle_threshold, 1),
            "per_cell_rub": round(oracle_threshold / max(len(oracle_idx), 1), 1),
            "cells": int(len(oracle_idx)),
        },
        "oracle_topk": {
            "total_rub": round(oracle_topk, 1),
            "per_cell_rub": round(oracle_topk / k, 1),
            "cells": int(k),
        },
        "none": {"total_rub": 0.0, "cells": 0},
    }


def bootstrap(y: np.ndarray, score: np.ndarray, reps: int, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    n = len(y)
    qs, thr, rank = [], [], []
    k = max(int(0.2 * n), 1)
    for _ in range(reps):
        idx = rng.integers(0, n, size=n)
        yb, sb = y[idx], score[idx]
        qs.append(qini(yb, sb)["qini_coefficient"])
        order = np.argsort(-sb)
        rank.append(float(yb[order[:k]].sum()))
        positive = np.where(sb > 0)[0]
        if len(positive) > k:
            positive = positive[np.argsort(-sb[positive])[:k]]
        thr.append(float(yb[positive].sum()))
    return {
        "qini_ci95": [
            round(float(np.percentile(qs, 2.5)), 4),
            round(float(np.percentile(qs, 97.5)), 4),
        ],
        "threshold_ci95": [
            round(float(np.percentile(thr, 2.5)), 1),
            round(float(np.percentile(thr, 97.5)), 1),
        ],
        "qini_rank_ci95": [
            round(float(np.percentile(rank, 2.5)), 1),
            round(float(np.percentile(rank, 97.5)), 1),
        ],
        "threshold_minus_rank_ci95": [
            round(float(np.percentile(np.array(thr) - np.array(rank), 2.5)), 1),
            round(float(np.percentile(np.array(thr) - np.array(rank), 97.5)), 1),
        ],
    }


def run(panel: pd.DataFrame, counterfactual: pd.DataFrame, seed: int = 42) -> dict:
    frame = build_frame(panel, counterfactual)
    last_week = int(frame["week"].max())
    holdout = 16
    train = frame[frame["week"] <= last_week - holdout]
    test = frame[frame["week"] > last_week - holdout]
    if len(test) < 500:
        raise ValueError("holdout is too small for a decision evaluation")

    score = fit_predict(train, test, seed)
    y = test["dev_profit"].to_numpy()

    residual = y - score
    ss_res = float((residual**2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    k = max(int(0.2 * len(y)), 1)
    rng = np.random.default_rng(seed)

    head = qini(y, score)
    head["rho_score_effect"] = round(
        float(pd.Series(score).corr(pd.Series(y), method="spearman")), 4
    )
    pol = policies(y, score, k, rng)
    hyp = {
        "threshold_beats_rank": bool(pol["threshold"]["total_rub"] > pol["qini_rank"]["total_rub"]),
        "difference_rub": round(pol["threshold"]["total_rub"] - pol["qini_rank"]["total_rub"], 1),
        "threshold_beats_none": bool(pol["threshold"]["total_rub"] > 0),
    }
    return {
        "model": {
            "algo": "HistGradientBoostingRegressor",
            "target": "incremental contribution margin, RUB per promoted cell",
            "train_cells": int(len(train)),
            "test_cells": int(len(test)),
            "holdout_weeks": holdout,
            "features": FEATURES,
            "r2": round(1 - ss_res / max(ss_tot, 1e-9), 4),
            "mae_rub": round(float(np.abs(residual).mean()), 1),
            "bias_rub": round(float(residual.mean()), 1),
        },
        "ranking": head,
        "calibration": calibration(y, score),
        "policies": pol,
        "bootstrap": bootstrap(y, score, 200, seed),
        "hypothesis": hyp,
    }
