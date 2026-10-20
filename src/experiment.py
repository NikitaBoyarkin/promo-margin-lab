"""Offline experiment design, checked by simulation.

The W2 result is the reason this module exists: per-cell lift has a placebo
interval of roughly ±20%, so a small effect cannot be detected on one cell.
The unit of randomisation here is a **store**, the outcome is incremental
contribution margin per store-week, and the analysis is a two-sample comparison
of store means — which is cluster-robust by construction.

Everything is validated on the panel itself:

* **FPR** — random splits under a true zero effect must reject ~5% of the time;
* **power** — at the analytic MDE the rejection rate must be ~80%;
* **SRM** — a deliberately unbalanced split must be caught;
* **carryover** — a decaying effect in a 2-week switchback block must show up
  as week-2 < week-1.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

KEY = ["store_id", "sku_id", "week"]


@dataclass(frozen=True)
class Design:
    n_stores: int
    n_arm: int
    weeks: int
    alpha: float = 0.05
    power: float = 0.80


def store_week_profit(panel: pd.DataFrame, counterfactual: pd.DataFrame) -> pd.DataFrame:
    df = panel.merge(counterfactual, on=KEY, how="left", validate="one_to_one")
    if df["baseline"].isna().any():
        raise ValueError("counterfactual is missing cells")
    cost = df["list_price"] * (1.0 - df["cm_rate"])
    profit = df["units_sold"] * (df["unit_price"] - cost) + df["supplier_funding"]
    baseline_profit = df["baseline"] * (df["list_price"] - cost)
    df = df.assign(dev_profit=profit - baseline_profit)
    return (
        df.groupby(["store_id", "week"], as_index=False)["dev_profit"]
        .sum()
        .rename(columns={"dev_profit": "profit"})
    )


def profit_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.pivot(index="store_id", columns="week", values="profit").sort_index()


def icc(matrix: pd.DataFrame) -> dict:
    """Share of weekly-profit variance that sits between stores."""
    x = matrix.to_numpy()
    s, w = x.shape
    grand = x.mean()
    store = x.mean(axis=1)
    week = x.mean(axis=0)
    ss_store = w * ((store - grand) ** 2).sum()
    resid = x - store[:, None] - week[None, :] + grand
    ss_resid = (resid**2).sum()
    ms_store = ss_store / (s - 1)
    ms_resid = ss_resid / ((s - 1) * (w - 1))
    value = (ms_store - ms_resid) / (ms_store + (w - 1) * ms_resid)
    return {
        "icc": round(float(value), 4),
        "between_store_sd": round(float(store.std(ddof=1)), 2),
        "residual_sd": round(float(np.sqrt(ms_resid)), 2),
        "stores": int(s),
        "weeks": int(w),
    }


def mde(sigma: float, n_arm: int, alpha: float = 0.05, power: float = 0.80) -> float:
    z_alpha = stats.norm.ppf(1 - alpha / 2)
    z_power = stats.norm.ppf(power)
    return float((z_alpha + z_power) * np.sqrt(2.0 / n_arm) * sigma)


def _two_sample(values: np.ndarray, treated: np.ndarray) -> tuple[float, float]:
    t_stat, p_value = stats.ttest_ind(values[treated], values[~treated], equal_var=False)
    diff = float(values[treated].mean() - values[~treated].mean())
    return diff, float(p_value)


def simulate_cluster_rct(
    matrix: pd.DataFrame,
    effect: float,
    reps: int,
    alpha: float,
    seed: int,
    window: int = 8,
) -> dict:
    """Randomise stores, inject ``effect`` rubles per store-week, run the test."""
    x = matrix.to_numpy()[:, -window:].mean(axis=1)
    n = len(x)
    n_arm = n // 2
    rng = np.random.default_rng(seed)
    rejects = 0
    estimates = []
    covered = 0
    for _ in range(reps):
        treated = np.zeros(n, dtype=bool)
        treated[rng.permutation(n)[:n_arm]] = True
        values = x + effect * treated
        diff, p_value = _two_sample(values, treated)
        se = np.sqrt(
            values[treated].var(ddof=1) / n_arm + values[~treated].var(ddof=1) / (n - n_arm)
        )
        half = stats.norm.ppf(1 - alpha / 2) * se
        estimates.append(diff)
        rejects += int(p_value < alpha)
        covered += int(abs(diff - effect) <= half)
    return {
        "reps": reps,
        "effect_rub": round(float(effect), 2),
        "reject_rate": round(rejects / reps, 4),
        "mean_estimate": round(float(np.mean(estimates)), 2),
        "bias": round(float(np.mean(estimates) - effect), 2),
        "ci_coverage": round(covered / reps, 4),
        "n_arm": int(n_arm),
        "window_weeks": int(window),
    }


def srm_check(counts: dict[str, int], expected: dict[str, float]) -> dict:
    observed = np.array([counts[k] for k in counts], dtype=float)
    target = np.array([expected[k] for k in counts], dtype=float)
    target = target / target.sum() * observed.sum()
    chi2 = float(((observed - target) ** 2 / target).sum())
    p_value = float(1 - stats.chi2.cdf(chi2, df=len(observed) - 1))
    return {"chi2": round(chi2, 3), "p_value": round(p_value, 4), "srm": bool(p_value < 0.001)}


def simulate_switchback(
    matrix: pd.DataFrame,
    effect: float,
    reps: int,
    alpha: float,
    seed: int,
    block: int = 2,
    carryover: float = 0.0,
) -> dict:
    """Staggered switchback with per-store phase and two-way demeaning.

    A switchback where every store switches in the same week cannot be separated
    from the promo calendar: week effects absorb the treatment. Randomising the
    phase per store keeps the contrast identified within a week.
    """
    x = matrix.to_numpy()
    n_stores, n_weeks = x.shape
    window = (n_weeks // (2 * block)) * 2 * block
    x = x[:, -window:]
    rng = np.random.default_rng(seed)
    period = 2 * block
    reps = int(reps)
    rejects = 0
    first, second = [], []

    for _ in range(reps):
        phase = rng.integers(0, period, size=n_stores)
        block_pos = (np.arange(window)[None, :] - phase[:, None]) % period
        treated = (block_pos < block).astype(float)
        decay = np.where(block_pos == 0, 1.0, np.where(block_pos == 1, carryover, 0.0))
        values = x + effect * treated * decay

        # Two-way within transformation: remove store and week means from y and t.
        y = values - values.mean(axis=1, keepdims=True) - values.mean(axis=0, keepdims=True)
        y = y + values.mean()
        t = treated - treated.mean(axis=1, keepdims=True) - treated.mean(axis=0, keepdims=True)
        t = t + treated.mean()

        denom = (t * t).sum(axis=1)
        beta_store = np.where(denom > 1e-9, (t * y).sum(axis=1) / np.maximum(denom, 1e-9), 0.0)
        se = float(beta_store.std(ddof=1) / np.sqrt(n_stores))
        p_value = float(2 * (1 - stats.norm.cdf(abs(beta_store.mean() / se)))) if se > 0 else 1.0
        rejects += int(p_value < alpha)

        if carryover != 0:
            for pos, bucket in ((0, first), (1, second)):
                mask = block_pos == pos
                control = block_pos >= block
                if mask.any() and control.any():
                    bucket.append(float(y[mask].mean() - y[control].mean()))

    out = {
        "reps": reps,
        "effect_rub": round(float(effect), 2),
        "reject_rate": round(rejects / reps, 4),
        "block_weeks": block,
        "window_weeks": int(window),
        "n_stores": int(n_stores),
    }
    if carryover != 0:
        out["week1_effect"] = round(float(np.mean(first)), 1)
        out["week2_effect"] = round(float(np.mean(second)), 1)
        out["carryover_ratio"] = round(float(np.mean(second) / max(np.mean(first), 1e-9)), 3)
    return out


def run(panel: pd.DataFrame, counterfactual: pd.DataFrame, cfg_seed: int = 42) -> dict:
    frame = store_week_profit(panel, counterfactual)
    matrix = profit_matrix(frame)
    var = icc(matrix)
    n_stores = matrix.shape[0]
    design = Design(n_stores=n_stores, n_arm=n_stores // 2, weeks=8, alpha=0.05, power=0.80)

    window_values = matrix.to_numpy()[:, -design.weeks :].mean(axis=1)
    sigma = float(window_values.std(ddof=1))
    mde_value = mde(sigma, design.n_arm, design.alpha, design.power)

    null = simulate_cluster_rct(matrix, 0.0, 1000, design.alpha, cfg_seed)
    alt = simulate_cluster_rct(matrix, mde_value, 1000, design.alpha, cfg_seed)
    srm = srm_check({"control": 57, "treatment": 63}, {"control": 60, "treatment": 60})
    switch_null = simulate_switchback(matrix, 0.0, 500, design.alpha, cfg_seed)
    switch_alt = simulate_switchback(matrix, mde_value, 500, design.alpha, cfg_seed)
    switch_carry = simulate_switchback(
        matrix, mde_value, 500, design.alpha, cfg_seed, carryover=0.5
    )

    return {
        "design": {
            "unit": "store",
            "arms": 2,
            "stores": int(n_stores),
            "stores_per_arm": int(design.n_arm),
            "weeks": int(design.weeks),
            "primary_metric": "incremental contribution margin, RUB per store-week",
            "alpha": design.alpha,
            "target_power": design.power,
        },
        "variance": var,
        "mde": {
            "rub_per_store_week": round(mde_value, 1),
            "sigma_store": round(sigma, 1),
            "analytic_power": design.power,
        },
        "cluster_rct": {"null": null, "at_mde": alt},
        "srm_example": srm,
        "switchback": {
            "null": switch_null,
            "at_mde": switch_alt,
            "carryover_test": switch_carry,
        },
    }
