"""Readiness analysis for the W5 cluster RCT (pre-launch, no results yet).

The experiment in ``docs/experiment-design.md`` has not run: there is no
assignment artifact and no readout. What can be checked today is whether the
declared design, as implemented in ``src/experiment.py``, would deliver what the
pre-registration promises:

* SRM against the *planned* split, globally and per format stratum;
* power / MDE on the metric the document defines (net units) and the one the
  code uses (gross units);
* calibration of the revenue guardrail that is written down as a 2% point rule;
* the attrition failure mode (NaN passing ``ttest_ind`` as "not rejected");
* the expected effect size of the decision at stake, against the MDE.

Run:  .venv/bin/python scripts/ab_test_analyzer.py --all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

WINDOW = 8
ALPHA = 0.05
POWER = 0.80
SRM_ALPHA = 0.001
PLANNED_STRATA = {"convenience": 62, "supermarket": 46, "hyper": 12}
PLANNED_ARMS = {"control": 60, "treatment": 60}


# ---------------------------------------------------------------- data loading
def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    panel = pd.read_parquet(ROOT / "data/panel/store_sku_week.parquet")
    baseline = pd.read_parquet(ROOT / "data/panel/baseline.parquet")
    return panel, baseline


def store_week_profit(
    panel: pd.DataFrame, baseline: pd.DataFrame, base: str = "net"
) -> pd.DataFrame:
    """Incremental contribution margin per store-week, in roubles.

    ``base`` selects the unit column: ``net`` (the pre-registered metric) or
    ``gross`` (what ``src/experiment.py:43`` actually uses).
    """
    unit_col = "net_units" if base == "net" else "units_sold"
    df = panel.merge(baseline, on=["store_id", "sku_id", "week"], how="left", validate="one_to_one")
    if df["baseline"].isna().any():
        raise ValueError("baseline is missing cells")
    cost = df["list_price"] * (1.0 - df["cm_rate"])
    realised = df[unit_col] * (df["unit_price"] - cost) + df["supplier_funding"]
    counterfactual = df["baseline"] * (df["list_price"] - cost)
    out = df.assign(dev_profit=realised - counterfactual)
    return (
        out.groupby(["store_id", "week"], as_index=False)["dev_profit"]
        .sum()
        .rename(columns={"dev_profit": "profit"})
    )


def to_matrix(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.pivot(index="store_id", columns="week", values="profit").sort_index()


# ----------------------------------------------------------------------- stats
def mde_analytic(sigma: float, n_arm: int, alpha: float = ALPHA, power: float = POWER) -> dict:
    z_a = stats.norm.ppf(1 - alpha / 2)
    z_b = stats.norm.ppf(power)
    value = (z_a + z_b) * np.sqrt(2.0 / n_arm) * sigma
    # The test is Welch's t; the analytic z version is what the repo quotes.
    t_a = stats.t.ppf(1 - alpha / 2, df=2 * n_arm - 2)
    t_b = stats.t.ppf(power, df=2 * n_arm - 2)
    return {
        "sigma": round(float(sigma), 2),
        "n_arm": int(n_arm),
        "mde_z": round(float(value), 1),
        "mde_t": round(float((t_a + t_b) * np.sqrt(2.0 / n_arm) * sigma), 1),
        "z_alpha_plus_beta": round(float(z_a + z_b), 4),
    }


def analytic_power(effect: float, sigma: float, n_arm: int, alpha: float = ALPHA) -> float:
    se = sigma * np.sqrt(2.0 / n_arm)
    ncp = effect / se
    crit = stats.norm.ppf(1 - alpha / 2)
    return float(stats.norm.cdf(ncp - crit) + stats.norm.cdf(-ncp - crit))


def icc(matrix: pd.DataFrame) -> dict:
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


def welch(values: np.ndarray, treated: np.ndarray, alpha: float = ALPHA) -> dict:
    a, b = values[treated], values[~treated]
    t_stat, p_value = stats.ttest_ind(a, b, equal_var=False)
    diff = float(a.mean() - b.mean())
    se = float(np.sqrt(a.var(ddof=1) / a.size + b.var(ddof=1) / b.size))
    t_crit = stats.t.ppf(1 - alpha / 2, df=a.size + b.size - 2)
    return {
        "diff": diff,
        "p_value": float(p_value),
        "ci95": [round(diff - t_crit * se, 1), round(diff + t_crit * se, 1)],
        "se": round(se, 1),
        "n_treated": int(a.size),
        "n_control": int(b.size),
    }


# ------------------------------------------------------------------------ SRM
def srm(counts: dict[str, int], expected_share: dict[str, float]) -> dict:
    """Chi-squared against the *planned* share, not against 50/50 by assumption."""
    keys = list(counts)
    observed = np.array([counts[k] for k in keys], dtype=float)
    share = np.array([expected_share[k] for k in keys], dtype=float)
    target = share / share.sum() * observed.sum()
    chi2 = float(((observed - target) ** 2 / target).sum())
    return {
        "observed": counts,
        "expected": {k: round(float(v), 2) for k, v in zip(keys, target, strict=True)},
        "chi2": round(chi2, 3),
        "p_value": float(stats.chi2.sf(chi2, df=len(observed) - 1)),
        "srm": bool(stats.chi2.sf(chi2, df=len(observed) - 1) < SRM_ALPHA),
    }


def srm_block(stores: pd.DataFrame, reps: int = 10_000, seed: int = 42) -> dict:
    """SRM on the designed allocation and on the allocation the code produces.

    The pre-registration requires stratified assignment; ``simulate_cluster_rct``
    permutes all 120 stores flat. The stratum structure of a flat permutation is
    a hypergeometric draw, so the designed table is not what a run would produce.
    """
    fmt = stores.set_index("store_id")["format"]

    designed_counts = {}
    for name, size in PLANNED_STRATA.items():
        designed_counts[name] = size
    designed = srm(
        {"control": PLANNED_ARMS["control"], "treatment": PLANNED_ARMS["treatment"]},
        {"control": 0.5, "treatment": 0.5},
    )
    designed_strata = {
        name: srm(
            {"control": PLANNED_STRATA[name] // 2, "treatment": PLANNED_STRATA[name] - size // 2},
            {"control": 0.5, "treatment": 0.5},
        )
        for name, size in PLANNED_STRATA.items()
    }

    rng = np.random.default_rng(seed)
    ids = fmt.index.to_numpy()
    n = ids.size
    n_arm = n // 2
    per_stratum_fail = dict.fromkeys(PLANNED_STRATA, 0)
    exact_match = 0
    hyper_splits: dict[str, int] = {}
    for _ in range(reps):
        treated_ids = rng.permutation(ids)[:n_arm]
        treated = pd.Series(False, index=ids)
        treated.loc[treated_ids] = True
        ok = True
        for name, size in PLANNED_STRATA.items():
            k = int(treated[fmt.values == name].sum())
            hyper_splits[f"{name}_{k}"] = hyper_splits.get(f"{name}_{k}", 0) + 1
            target = size / 2
            chi2 = (k - target) ** 2 / target + ((size - k) - target) ** 2 / target
            if stats.chi2.sf(chi2, df=1) < SRM_ALPHA:
                per_stratum_fail[name] += 1
            if k != round(target):
                ok = False
        exact_match += int(ok)

    flat_strata = {
        name: {
            "planned": f"{size // 2}/{size - size // 2}",
            "flat_permutation_most_common": sorted(
                (
                    (int(key.rsplit("_", 1)[1]), cnt)
                    for key, cnt in hyper_splits.items()
                    if key.startswith(name + "_")
                ),
                key=lambda kv: -kv[1],
            )[:3],
            "p_any_imbalance_gt_0": round(
                1.0 - hyper_splits.get(f"{name}_{size // 2}", 0) / reps, 3
            ),
            "p_srm_at_0.001": round(per_stratum_fail[name] / reps, 4),
        }
        for name, size in PLANNED_STRATA.items()
    }
    return {
        "planned_split": PLANNED_ARMS,
        "aggregate_designed": designed,
        "aggregate_flat_permutation_p_srm": "see per_stratum below",
        "per_stratum_designed": designed_strata,
        "per_stratum_under_implemented_flat_permutation": flat_strata,
        "p_all_strata_exact": round(exact_match / reps, 5),
        "reps": reps,
    }


# ------------------------------------------------------------------- guardrail
def revenue_matrix(panel: pd.DataFrame) -> pd.DataFrame:
    frame = panel.groupby(["store_id", "week"], as_index=False)["revenue"].sum()
    return frame.pivot(index="store_id", columns="week", values="revenue").sort_index()


def guardrail_block(panel: pd.DataFrame, reps: int = 1_000, seed: int = 7) -> dict:
    """False-stop rate of the written 2% point rule vs a calibrated z rule.

    The guardrail is a **revenue** decline, so the matrix here is store-week
    revenue, not the profit matrix used for the primary metric.
    """
    matrix = revenue_matrix(panel)
    x = matrix.to_numpy()[:, -WINDOW:]
    n = x.shape[0]
    n_arm = n // 2
    rng = np.random.default_rng(seed)
    point_stops = 0
    z_stops = 0
    alpha_bonf = SRM_ALPHA / (WINDOW * 2)
    z_crit = stats.norm.ppf(1 - alpha_bonf)
    for _ in range(reps):
        treated = np.zeros(n, dtype=bool)
        treated[rng.permutation(n)[:n_arm]] = True
        control_mean = x[~treated].mean(axis=0)
        treat_mean = x[treated].mean(axis=0)
        rel = (treat_mean - control_mean) / np.abs(control_mean)
        hits = rel <= -0.02
        if any(hits[i] and hits[i + 1] for i in range(len(hits) - 1)):
            point_stops += 1
        se = np.sqrt(
            x[treated].var(axis=0, ddof=1) / n_arm + x[~treated].var(axis=0, ddof=1) / n_arm
        )
        z = (treat_mean - control_mean) / se
        if (z <= -z_crit).any():
            z_stops += 1
    sigma_rev = float(x.mean(axis=1).std(ddof=1))
    guard_mde = mde_analytic(sigma_rev, n_arm)["mde_z"]
    # A 2% guardrail is a *relative* statement; a raw-rouble contrast is dominated
    # by store size. The relative test is per-store window vs pre-period ratio.
    rev = matrix.to_numpy()
    pre = rev[:, -2 * WINDOW : -WINDOW].mean(axis=1)
    cur = rev[:, -WINDOW:].mean(axis=1)
    ratio = cur / pre
    sigma_rel = float(ratio.std(ddof=1))
    rel_mde = float(
        (stats.norm.ppf(1 - ALPHA / 2) + stats.norm.ppf(POWER)) * np.sqrt(2.0 / n_arm) * sigma_rel
    )
    return {
        "metric": "weekly revenue per store",
        "rule_point_2pct_two_weeks": {
            "false_stop_rate": round(point_stops / reps, 4),
            "target": 0.05,
            "verdict": "not a test",
        },
        "rule_z_bonferroni_0.001_two_sided": {
            "false_stop_rate": round(z_stops / reps, 4),
            "alpha_per_read": round(alpha_bonf, 6),
            "reads": WINDOW * 2,
            "verdict": "calibrated" if z_stops / reps <= 0.05 else "still too loose",
        },
        "mde_level_rub": round(guard_mde, 1),
        "mde_level_pct_of_revenue": round(100 * guard_mde / float(rev[:, -WINDOW:].mean()), 4),
        "mde_relative_pct": round(100 * rel_mde, 4),
        "mde_relative_note": "per-store window/pre-period revenue ratio; the scale a 2% rule lives on",
        "reps": reps,
    }


# ---------------------------------------------------------------- assignment
def assignment_block(
    matrix: pd.DataFrame, stores: pd.DataFrame, sigma: float, effect: float, reps: int, seed: int
) -> dict:
    """What the missing stratification costs: balance of the arm contrast.

    The pre-registration stratifies by format; the code permutes flat. Both are
    valid randomisations, so SRM does not flag either — the difference shows up
    as variance in the estimated effect.
    """
    fmt = stores.set_index("store_id").loc[matrix.index, "format"].to_numpy()
    x = matrix.to_numpy()[:, -WINDOW:].mean(axis=1)
    n = x.size
    n_arm = n // 2
    rng = np.random.default_rng(seed)
    strata = {name: np.flatnonzero(fmt == name) for name in np.unique(fmt)}

    def draw(stratified: bool) -> np.ndarray:
        treated = np.zeros(n, dtype=bool)
        if stratified:
            for idx in strata.values():
                take = idx.size // 2
                treated[rng.choice(idx, size=take, replace=False)] = True
        else:
            treated[rng.permutation(n)[:n_arm]] = True
        return treated

    out = {}
    for label, stratified in (("flat_permutation", False), ("stratified_by_format", True)):
        diffs, rejects, powered = [], 0, 0
        for _ in range(reps):
            treated = draw(stratified)
            diff = float(x[treated].mean() - x[~treated].mean())
            diffs.append(diff)
            rejects += int(welch(x, treated)["p_value"] < ALPHA)
            powered += int(welch(x + effect * treated, treated)["p_value"] < ALPHA)
        out[label] = {
            "sd_of_estimated_diff": round(float(np.std(diffs, ddof=1)), 1),
            "p95_abs_diff": round(float(np.percentile(np.abs(diffs), 95)), 1),
            "false_positive_rate": round(rejects / reps, 4),
            "power_at_mde": round(powered / reps, 4),
        }
    out["variance_reduction_pct"] = round(
        100
        * (
            1
            - (
                out["stratified_by_format"]["sd_of_estimated_diff"]
                / out["flat_permutation"]["sd_of_estimated_diff"]
            )
            ** 2
        ),
        2,
    )
    out["reps"] = reps
    return out


def attrition_block(matrix: pd.DataFrame) -> dict:
    """NaN stores pass ``ttest_ind`` as 'not rejected' — confirm the failure mode."""
    x = matrix.to_numpy()[:, -WINDOW:].mean(axis=1)
    n = x.shape[0]
    values = x.copy()
    values[:10] = np.nan  # 10 stores lost — 8.3% attrition
    treated = np.zeros(n, dtype=bool)
    treated[n // 2 :] = True
    t_stat, p_value = stats.ttest_ind(values[treated], values[~treated], equal_var=False)
    return {
        "stores_dropped": 10,
        "ttest_statistic": float(t_stat),
        "p_value": float(p_value),
        "p_is_nan": bool(np.isnan(p_value)),
        "rejected_at_0.05": bool(not np.isnan(p_value) and p_value < 0.05),
        "note": "NaN p-value is counted as 'not rejected', i.e. as evidence of no effect",
    }


# --------------------------------------------------------------------- assemble
def run_all(reps_mc: int = 1_000) -> dict:
    panel, baseline = load()
    gross = to_matrix(store_week_profit(panel, baseline, "gross"))
    net = to_matrix(store_week_profit(panel, baseline, "net"))
    stores = (
        panel[["store_id", "format"]]
        .drop_duplicates()
        .sort_values("store_id")
        .reset_index(drop=True)
    )
    revenue_store_week = float(
        panel.groupby(["store_id", "week"])["revenue"].sum().groupby("store_id").mean().mean()
    )

    x_net = net.to_numpy()[:, -WINDOW:].mean(axis=1)
    sigma = float(x_net.std(ddof=1))
    n = x_net.size
    n_arm = n // 2
    mde = mde_analytic(sigma, n_arm)

    rng = np.random.default_rng(42)
    null_rejects = 0
    power_rejects = 0
    for _ in range(reps_mc):
        treated = np.zeros(n, dtype=bool)
        treated[rng.permutation(n)[:n_arm]] = True
        null_rejects += int(welch(x_net, treated)["p_value"] < ALPHA)
        power_rejects += int(welch(x_net + mde["mde_z"] * treated, treated)["p_value"] < ALPHA)

    # Gross vs net: the size of the metric-base error the code carries.
    incr_gross = float(gross.to_numpy()[:, -WINDOW:].sum())
    incr_net = float(net.to_numpy()[:, -WINDOW:].sum())

    promo_share_weeks = (
        panel[panel["week"] >= panel["week"].max() - WINDOW + 1]
        .groupby("week")["promo_flag"]
        .mean()
        .round(3)
        .to_dict()
    )
    exposed_weeks = int(sum(1 for v in promo_share_weeks.values() if v > 0))

    # Effect the decision trades on: the W7 optimised policy vs blanket, per store-week.
    policy = json.loads((ROOT / "reports/policy.json").read_text())
    policy_delta = float(policy["vs_blanket"]["profit_delta_rub"])

    window = net.to_numpy()
    store_means = window[:, -WINDOW:].mean(axis=1)
    return {
        "status": "pre-launch audit — no experiment has run, no assignment artifact exists",
        "design": {
            "unit": "store",
            "stores": int(n),
            "stores_per_arm": int(n_arm),
            "weeks": WINDOW,
            "primary_metric": "incremental contribution margin, RUB per store-week, net units",
            "alpha": ALPHA,
            "target_power": POWER,
            "formats": stores["format"].value_counts().to_dict(),
        },
        "variance": {
            "full_panel": icc(net),
            "experiment_window": icc(net.iloc[:, -WINDOW:]),
            "gross_base_window": icc(gross.iloc[:, -WINDOW:]),
            "sigma_store_window_net": round(sigma, 2),
            "sigma_store_window_gross": round(
                float(gross.to_numpy()[:, -WINDOW:].mean(axis=1).std(ddof=1)), 2
            ),
        },
        "mde": {
            **mde,
            "as_pct_of_weekly_revenue": round(100 * mde["mde_z"] / revenue_store_week, 3),
            "revenue_per_store_week": round(revenue_store_week, 1),
            "exposed_weeks_in_window": exposed_weeks,
            "mde_per_exposed_store_week": round(mde["mde_z"] * WINDOW / exposed_weeks, 1),
            "analytic_power_at_mde": round(analytic_power(mde["mde_z"], sigma, n_arm), 4),
            "mde_gross_base": round(
                mde_analytic(float(gross.to_numpy()[:, -WINDOW:].mean(axis=1).std(ddof=1)), n_arm)[
                    "mde_z"
                ],
                1,
            ),
        },
        "monte_carlo": {
            "reps": reps_mc,
            "false_positive_rate": round(null_rejects / reps_mc, 4),
            "power_at_mde": round(power_rejects / reps_mc, 4),
            "binomial_se_pp": round(100 * float(np.sqrt(POWER * (1 - POWER) / reps_mc)), 2),
        },
        "metric_base_error": {
            "incremental_cm_gross_window_rub": round(incr_gross, 1),
            "incremental_cm_net_window_rub": round(incr_net, 1),
            "overstatement_rub": round(incr_gross - incr_net, 1),
            "overstatement_share_of_gross_pct": round(
                100 * (incr_gross - incr_net) / abs(incr_gross), 2
            ),
            "note": "gross base is what src/experiment.py:43 uses; net is the pre-registered metric",
        },
        "srm": srm_block(stores, reps=10_000),
        "assignment": assignment_block(net, stores, sigma, mde["mde_z"], reps=reps_mc, seed=11),
        "guardrail": guardrail_block(panel, reps=reps_mc),
        "attrition": attrition_block(net),
        "effect_vs_mde": {
            "mde_rub_per_store_week": mde["mde_z"],
            "policy_gain_per_week_rub": round(policy_delta, 1),
            "if_gain_repeats_weekly_rub_per_store_week": round(policy_delta / n, 1),
            "if_gain_lands_once_per_window_rub_per_store_week": round(
                policy_delta / (n * WINDOW), 1
            ),
            "ratio_weekly": round(policy_delta / n / mde["mde_z"], 2),
            "ratio_diluted": round(policy_delta / (n * WINDOW) / mde["mde_z"], 2),
            "evidence_class": "Inferred — W7 one-week planning instance rescaled to 120 stores",
        },
        "n_per_arm_required_for_2pct_revenue_effect": int(
            np.ceil(
                2
                * (stats.norm.ppf(0.975) + stats.norm.ppf(POWER)) ** 2
                * sigma**2
                / (0.02 * revenue_store_week) ** 2
            )
        ),
        "mde_by_n_arm": {str(k): mde_analytic(sigma, k)["mde_z"] for k in (30, 60, 120, 240, 480)},
        "store_mean_spread": {
            "p10": round(float(np.percentile(store_means, 10)), 1),
            "p50": round(float(np.percentile(store_means, 50)), 1),
            "p90": round(float(np.percentile(store_means, 90)), 1),
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true", help="run every check")
    ap.add_argument("--check-srm", action="store_true")
    ap.add_argument("--power", action="store_true")
    ap.add_argument("--guardrail", action="store_true")
    ap.add_argument("--reps", type=int, default=1_000)
    ap.add_argument("--out", type=Path, default=ROOT / "reports/ab_test_readiness.json")
    args = ap.parse_args()

    panel, baseline = load()
    net = to_matrix(store_week_profit(panel, baseline, "net"))
    if args.check_srm:
        stores = panel[["store_id", "format"]].drop_duplicates().sort_values("store_id")
        print(json.dumps(srm_block(stores.reset_index(drop=True), reps=10_000), indent=2))
    elif args.power:
        x = net.to_numpy()[:, -WINDOW:].mean(axis=1)
        print(json.dumps(mde_analytic(float(x.std(ddof=1)), x.size // 2), indent=2))
    elif args.guardrail:
        print(json.dumps(guardrail_block(panel, reps=args.reps), indent=2))
    elif args.all:
        result = run_all(reps_mc=args.reps)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
