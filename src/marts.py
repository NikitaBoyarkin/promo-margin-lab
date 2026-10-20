"""Materialise the panel into a SQLite marts database that Superset can query.

Superset supports SQLite natively, so the demo does not need a second database
for data: one file (`data/marts/promo.db`) is mounted into the container. Mart
queries live in `sql/marts/*.sql` and are the only source of dashboard numbers.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

KEY = ["store_id", "sku_id", "week"]
MARTS = {
    "promo_pnl": "01_promo_pnl.sql",
    "model_quality": "02_model_quality.sql",
    "guardrails": "03_guardrails.sql",
    "breakeven_vs_actual": "04_breakeven_vs_actual.sql",
}


def build_database(
    panel: pd.DataFrame,
    waves: pd.DataFrame,
    counterfactual: pd.DataFrame,
    baseline_report: dict,
    margin_report: dict,
    path: Path,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    cells = panel[
        [
            "store_id",
            "sku_id",
            "week",
            "category",
            "format",
            "promo_flag",
            "promo_depth",
            "units_sold",
            "units_returned",
            "net_units",
            "list_price",
            "unit_price",
            "revenue",
            "cm",
            "cm_rate",
            "discount_cost",
            "supplier_funding",
        ]
    ].merge(counterfactual, on=KEY, how="left")
    cells["dev_units"] = cells["units_sold"] - cells["baseline"]

    model_eval = pd.DataFrame(
        [
            {
                "estimator": name,
                "baseline_wape_vs_truth": row["baseline_wape_vs_truth"],
                "promo_bias_pct": row["promo_bias_pct"],
                "placebo_p05": row["placebo_p05"],
                "placebo_p50": row["placebo_p50"],
                "placebo_p95": row["placebo_p95"],
            }
            for name, row in baseline_report["estimators"].items()
        ]
    )
    breakeven = pd.DataFrame(
        [{"category": cat, **row} for cat, row in margin_report["breakeven"].items()]
    )

    with sqlite3.connect(path) as conn:
        cells.to_sql("promo_cells", conn, index=False, if_exists="replace")
        waves.to_sql("promo_waves", conn, index=False, if_exists="replace")
        model_eval.to_sql("model_eval", conn, index=False, if_exists="replace")
        breakeven.to_sql("breakeven", conn, index=False, if_exists="replace")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cells_week ON promo_cells(week)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_waves_week ON promo_waves(week)")
    return path


def run_marts(db_path: Path, sql_dir: Path) -> dict[str, pd.DataFrame]:
    results: dict[str, pd.DataFrame] = {}
    with sqlite3.connect(db_path) as conn:
        for name, filename in MARTS.items():
            query = (sql_dir / filename).read_text(encoding="utf-8")
            results[name] = pd.read_sql_query(query, conn)
    return results


def headline(results: dict[str, pd.DataFrame]) -> dict:
    pnl = results["promo_pnl"]
    quality = results["model_quality"]
    guard = results["guardrails"]
    gap = results["breakeven_vs_actual"]
    return {
        "categories": int(len(pnl)),
        "net_profit_rub": round(float(pnl["net_profit"].sum()), 1),
        "revenue_delta_rub": round(float(pnl["revenue_delta"].sum()), 1),
        "share_negative": round(
            float((pnl["share_negative"] * pnl["waves"]).sum() / pnl["waves"].sum()), 4
        ),
        "best_estimator": str(quality.iloc[0]["estimator"]),
        "weeks": int(len(guard)),
        "categories_beyond_ceiling": int(gap["beyond_ceiling"].sum()),
    }
