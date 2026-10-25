"""Single entry point for promo-margin-lab.

    uv run python run.py --stage all
    uv run python run.py --stage panel --fast

Stages are idempotent: the same seed reproduces the same bytes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from allocation import run as run_allocation  # noqa: E402
from baseline import run as run_baseline  # noqa: E402
from config import Config  # noqa: E402
from dgp import simulate  # noqa: E402
from experiment import run as run_experiment  # noqa: E402
from ledger import run as run_ledger  # noqa: E402
from marts import build_database, run_marts  # noqa: E402
from marts import headline as marts_headline  # noqa: E402
from panel import build_panel, feature_columns  # noqa: E402
from paths import (  # noqa: E402
    DATA,
    PANEL,
    RAW,
    REPORTS,
    TRUTH,
    frame_hash,
    write_json,
    write_parquet,
)
from render import render  # noqa: E402
from response import run as run_response  # noqa: E402

STAGES = (
    "data",
    "panel",
    "baseline",
    "ledger",
    "experiment",
    "response",
    "allocation",
    "marts",
    "spark",
    "all",
)


def _suffix(cfg: Config) -> str:
    """Fast-profile artefacts never share a path with headline artefacts."""
    return "_fast" if cfg.n_stores < 120 else ""


def stage_data(cfg: Config) -> dict:
    suffix = _suffix(cfg)
    sim = simulate(cfg)
    write_parquet(sim.facts, RAW / f"facts{suffix}.parquet")
    write_parquet(sim.dim_price, RAW / f"dim_price{suffix}.parquet")
    write_parquet(sim.truth, TRUTH / f"effects{suffix}.parquet")
    return {
        "rows": int(len(sim.facts)),
        "price_versions": int(len(sim.dim_price)),
        "facts_hash": frame_hash(sim.facts),
        "truth_hash": frame_hash(sim.truth),
    }


def stage_panel(cfg: Config) -> dict:
    suffix = _suffix(cfg)
    facts = pd.read_parquet(RAW / f"facts{suffix}.parquet")
    dim = pd.read_parquet(RAW / f"dim_price{suffix}.parquet")
    panel = build_panel(cfg, facts, dim)
    write_parquet(panel, PANEL / f"store_sku_week{suffix}.parquet")

    promo = panel[panel["promo_flag"]]
    summary = {
        "config": {
            "seed": cfg.seed,
            "stores": cfg.n_stores,
            "skus": cfg.n_skus,
            "weeks": cfg.n_weeks,
            "fast": cfg.n_stores < 120,
        },
        "rows": int(len(panel)),
        "promo_cells": int(len(promo)),
        "promo_share": round(float(len(promo) / len(panel)), 4),
        "depth_mean": round(float(promo["promo_depth"].mean()), 4) if len(promo) else 0.0,
        "depth_max": round(float(promo["promo_depth"].max()), 4) if len(promo) else 0.0,
        "units_sold": round(float(panel["units_sold"].sum()), 1),
        "units_returned": round(float(panel["units_returned"].sum()), 1),
        "return_share": round(float(panel["units_returned"].sum() / panel["units_sold"].sum()), 5),
        "revenue_rub": round(float(panel["revenue"].sum()), 1),
        "cm_rub": round(float(panel["cm"].sum()), 1),
        "discount_cost_rub": round(float(panel["discount_cost"].sum()), 1),
        "panel_hash": frame_hash(panel),
        "features": feature_columns(panel),
        "n_features": int(len(feature_columns(panel))),
    }
    write_json(REPORTS / f"w0_summary{suffix}.json", summary)
    return summary


def stage_baseline(cfg: Config) -> dict:
    suffix = _suffix(cfg)
    panel = pd.read_parquet(PANEL / f"store_sku_week{suffix}.parquet")
    truth = pd.read_parquet(TRUTH / f"effects{suffix}.parquet")
    result = run_baseline(panel, truth, cfg)
    counterfactual = result.pop("counterfactual")
    write_parquet(counterfactual, PANEL / f"baseline{suffix}.parquet")
    write_json(REPORTS / f"baseline{suffix}.json", result)
    return result


def stage_ledger(cfg: Config) -> dict:
    suffix = _suffix(cfg)
    panel = pd.read_parquet(PANEL / f"store_sku_week{suffix}.parquet")
    counterfactual = pd.read_parquet(PANEL / f"baseline{suffix}.parquet")
    truth = pd.read_parquet(TRUTH / f"effects{suffix}.parquet")
    result = run_ledger(panel, counterfactual, truth)
    waves = result["waves"]
    summary = result["summary"]
    write_parquet(waves, PANEL / f"waves{suffix}.parquet")

    breakeven = summary.pop("breakeven")
    ledger_report = {
        "config": {"seed": cfg.seed, "fast": cfg.n_stores < 120},
        "summary": summary,
        "top_waves_by_profit": waves.nlargest(5, "net_profit")[
            ["store_id", "week", "category", "own_units", "net_units", "net_profit"]
        ].to_dict(orient="records"),
        "worst_waves_by_profit": waves.nsmallest(5, "net_profit")[
            ["store_id", "week", "category", "own_units", "net_units", "net_profit"]
        ].to_dict(orient="records"),
    }
    margin_report = {
        "breakeven": breakeven,
        "pnl": {
            "revenue_delta_rub": summary["revenue_delta_rub"],
            "net_profit_rub": summary["net_profit_rub"],
            "discount_cost_rub": summary["discount_cost_rub"],
            "supplier_funding_rub": summary["supplier_funding_rub"],
            "share_waves_negative_profit": summary["share_waves_negative_profit"],
            "share_revenue_up_profit_down": summary["share_revenue_up_profit_down"],
        },
    }
    write_json(REPORTS / f"ledger{suffix}.json", ledger_report)
    write_json(REPORTS / f"margin{suffix}.json", margin_report)
    return summary


def stage_marts(cfg: Config) -> dict:
    suffix = _suffix(cfg)
    panel = pd.read_parquet(PANEL / f"store_sku_week{suffix}.parquet")
    waves = pd.read_parquet(PANEL / f"waves{suffix}.parquet")
    counterfactual = pd.read_parquet(PANEL / f"baseline{suffix}.parquet")
    baseline_report = json.loads((REPORTS / f"baseline{suffix}.json").read_text(encoding="utf-8"))
    margin_report = json.loads((REPORTS / f"margin{suffix}.json").read_text(encoding="utf-8"))

    db_path = DATA / "marts" / f"promo{suffix}.db"
    build_database(panel, waves, counterfactual, baseline_report, margin_report, db_path)
    results = run_marts(db_path, ROOT / "sql" / "marts")
    head = marts_headline(results)
    write_json(
        REPORTS / f"marts{suffix}.json",
        {"headline": head, "rows": {name: int(len(frame)) for name, frame in results.items()}},
    )
    if suffix == "":
        render(
            results,
            head,
            REPORTS / "superset" / "dashboard.html",
            seed=cfg.seed,
            panel_hash=frame_hash(panel),
        )
    return head


def stage_experiment(cfg: Config) -> dict:
    suffix = _suffix(cfg)
    panel = pd.read_parquet(PANEL / f"store_sku_week{suffix}.parquet")
    counterfactual = pd.read_parquet(PANEL / f"baseline{suffix}.parquet")
    result = run_experiment(panel, counterfactual, cfg.seed)
    design_report = {
        "design": result["design"],
        "variance": result["variance"],
        "mde": result["mde"],
    }
    write_json(REPORTS / f"experiment_design{suffix}.json", design_report)
    write_json(
        REPORTS / f"simulation{suffix}.json",
        {
            "cluster_rct": result["cluster_rct"],
            "srm_example": result["srm_example"],
            "switchback": result["switchback"],
        },
    )
    return {"design": result["design"], "mde": result["mde"], "cluster_rct": result["cluster_rct"]}


def stage_response(cfg: Config) -> dict:
    suffix = _suffix(cfg)
    panel = pd.read_parquet(PANEL / f"store_sku_week{suffix}.parquet")
    counterfactual = pd.read_parquet(PANEL / f"baseline{suffix}.parquet")
    result = run_response(panel, counterfactual, cfg.seed)
    write_json(REPORTS / f"response{suffix}.json", result)
    return result


def stage_allocation(cfg: Config) -> dict:
    suffix = _suffix(cfg)
    panel = pd.read_parquet(PANEL / f"store_sku_week{suffix}.parquet")
    counterfactual = pd.read_parquet(PANEL / f"baseline{suffix}.parquet")
    result = run_allocation(panel, counterfactual, cfg.seed)
    write_json(REPORTS / f"policy{suffix}.json", result)
    return result


def stage_spark(cfg: Config) -> dict:
    suffix = _suffix(cfg)
    from spark_job import run as run_spark

    panel_path = PANEL / f"store_sku_week{suffix}.parquet"
    rows = 2_000_000 if suffix else 16_600_000
    result = run_spark(panel_path, scale_rows=rows)
    write_json(REPORTS / f"spark_parity{suffix}.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=STAGES, default="all")
    parser.add_argument("--fast", action="store_true", help="CI profile: fewer cells, not headline")
    args = parser.parse_args(argv)

    cfg = Config().fast() if args.fast else Config()
    print(f"stage={args.stage} seed={cfg.seed} panel={cfg.path} fast={args.fast}")

    if args.stage in ("data", "all"):
        info = stage_data(cfg)
        print(
            f"  data : {info['rows']:,} rows, {info['price_versions']:,} price versions, "
            f"hash={info['facts_hash']}"
        )
    if args.stage in ("panel", "all"):
        info = stage_panel(cfg)
        print(
            f"  panel: {info['rows']:,} rows, promo={info['promo_share']:.1%}, "
            f"depth~{info['depth_mean']:.1%}, hash={info['panel_hash']}"
        )
    if args.stage in ("baseline", "all"):
        info = stage_baseline(cfg)
        head = info["headline"]
        bias = head["bias_pct"]
        print(
            f"  base : best={head['best_by_abs_bias']} "
            f"bias naive={bias['naive_mean']:+.1%} "
            f"forecast={bias['forecast']:+.1%} "
            f"matched={bias['matched_control']:+.1%} "
            f"({head['bias_reduction_x']:.1f}x better)"
        )
    if args.stage in ("ledger", "all"):
        info = stage_ledger(cfg)
        print(
            f"  ledger: waves={info['waves']:,} net/own={1 - info['leak_share']:.1%} "
            f"neg-profit={info['share_waves_negative_profit']:.1%} "
            f"rev-up-profit-down={info['share_revenue_up_profit_down']:.1%} "
            f"net={info['net_profit_rub'] / 1e6:+.1f}m RUB"
        )
    if args.stage in ("marts", "all"):
        info = stage_marts(cfg)
        print(
            f"  marts : categories={info['categories']} weeks={info['weeks']} "
            f"net={info['net_profit_rub'] / 1e6:+.1f}m RUB "
            f"above-ceiling={info['categories_beyond_ceiling']}/6"
        )
    if args.stage in ("experiment", "all"):
        info = stage_experiment(cfg)
        sim = info["cluster_rct"]
        print(
            f"  design: stores={info['design']['stores']} "
            f"arms={info['design']['stores_per_arm']} "
            f"MDE={info['mde']['rub_per_store_week']:.0f} RUB/store-week "
            f"fpr={sim['null']['reject_rate']:.1%} "
            f"power={sim['at_mde']['reject_rate']:.1%} "
            f"cover={sim['at_mde']['ci_coverage']:.1%}"
        )
    if args.stage in ("response", "all"):
        info = stage_response(cfg)
        pol = info["policies"]
        print(
            f"  policy: r2={info['model']['r2']:.3f} qini={info['ranking']['qini_coefficient']:+.3f} "
            f"rank={pol['qini_rank']['total_rub']:,.0f} "
            f"thr={pol['threshold']['total_rub']:,.0f} "
            f"oracle={pol['oracle_threshold']['total_rub']:,.0f} RUB"
        )
    if args.stage in ("allocation", "all"):
        info = stage_allocation(cfg)
        tight = info["scenarios"]["tight"]
        print(
            f"  alloc : candidates={info['candidates']} "
            f"tight={tight['optimised']['profit_rub']:,.0f} RUB "
            f"vs top15={tight['top_ratio_15']['profit_rub']:,.0f} "
            f"vs random={tight['random_15']['profit_rub']:,.0f} "
            f"gap={info['heuristic_check']['gap']:.2%}"
        )
    if args.stage in ("spark", "all"):
        try:
            info = stage_spark(cfg)
        except ModuleNotFoundError as exc:
            # pyspark lives in the optional `spark` group; `--stage all` must not
            # die on the last stage for a reader who ran a plain `uv sync`
            if args.stage == "spark":
                raise
            print(f"  spark: skipped ({exc.name} missing — uv sync --group spark)")
        else:
            parity = info["parity"]
            scale = info["scale"]
            print(
                f"  spark: parity={'OK' if parity['ok'] else 'FAIL'} "
                f"diff={parity['max_abs_diff_overall']:.1e} "
                f"rows={parity['rows_compared']} "
                f"scale={scale['rows']:,} in {scale['seconds']:.1f}s"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
