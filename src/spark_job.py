"""PySpark parity job: the same features, two engines.

The claim is deliberately narrow: on the real panel, Spark and pandas produce
the same store-week aggregate. Scale is demonstrated separately on generated
rows, with no throughput promise — this is ``local[*]``, one JVM, no cluster.

Spark is an optional dependency group: ``uv sync --group spark``. It needs a
JDK; on macOS Homebrew's openjdk is auto-detected if ``java`` is not on PATH.
"""

from __future__ import annotations

import glob
import os
import shutil
import time
from pathlib import Path

import pandas as pd

KEY = ["store_id", "sku_id", "week"]
SAMPLE_STORES = 10
SCALE_ROWS = 16_600_000


def _java_works(path: str) -> bool:
    import subprocess

    try:
        return subprocess.run([path, "-version"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def ensure_java() -> str:
    java = shutil.which("java")
    if java and _java_works(java):
        return java
    # macOS ships /usr/bin/java as a stub that fails until a JDK is installed.
    candidates = sorted(glob.glob("/opt/homebrew/opt/openjdk*/bin/java"), reverse=True)
    for candidate in candidates:
        if _java_works(candidate):
            os.environ["JAVA_HOME"] = str(Path(candidate).parent.parent)
            os.environ["PATH"] = f"{Path(candidate).parent}:{os.environ.get('PATH', '')}"
            return candidate
    raise RuntimeError(
        "no working java found: install a JDK and/or set JAVA_HOME "
        "(e.g. JAVA_HOME=/opt/homebrew/opt/openjdk@25)"
    )


def session(app: str = "promo-margin-lab", threads: int = 4):
    ensure_java()
    from pyspark.sql import SparkSession

    spark = (
        SparkSession.builder.master(f"local[{threads}]")
        .appName(app)
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "16")
        .config("spark.driver.memory", "4g")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")
    return spark


def pandas_reference(panel: pd.DataFrame, stores: list[str]) -> pd.DataFrame:
    """Window features and the store-week aggregate, computed with pandas."""
    frame = panel.loc[
        panel["store_id"].isin(stores), KEY + ["units_sold", "revenue", "promo_flag", "promo_depth"]
    ].copy()
    frame = frame.sort_values(KEY)
    grouped = frame.groupby(["store_id", "sku_id"], sort=False)
    frame["lag_units"] = grouped["units_sold"].shift(1)
    frame["roll4_units"] = grouped["units_sold"].transform(
        lambda s: s.rolling(4, min_periods=1).mean()
    )
    return (
        frame.groupby(["store_id", "week"], as_index=False)
        .agg(
            units_sum=("units_sold", "sum"),
            revenue_sum=("revenue", "sum"),
            promo_cells=("promo_flag", "sum"),
            max_depth=("promo_depth", "max"),
            mean_lag=("lag_units", "mean"),
            mean_roll4=("roll4_units", "mean"),
        )
        .sort_values(["store_id", "week"])
        .reset_index(drop=True)
    )


def spark_aggregate(spark, panel_path: Path, stores: list[str]) -> tuple[pd.DataFrame, str]:
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    df = spark.read.parquet(str(panel_path)).filter(F.col("store_id").isin(stores))
    dim = spark.createDataFrame(
        [(c, c.upper()) for c in sorted(df.select("category").distinct().toPandas()["category"])],
        ["category", "category_label"],
    )
    df = df.join(F.broadcast(dim), on="category", how="left")

    by_series = Window.partitionBy("store_id", "sku_id").orderBy("week")
    rolling = by_series.rowsBetween(-3, 0)
    features = df.select(
        "store_id",
        "sku_id",
        "week",
        "units_sold",
        "revenue",
        "promo_flag",
        "promo_depth",
        F.lag("units_sold").over(by_series).alias("lag_units"),
        F.avg("units_sold").over(rolling).alias("roll4_units"),
    )
    aggregated = features.groupBy("store_id", "week").agg(
        F.sum("units_sold").alias("units_sum"),
        F.sum("revenue").alias("revenue_sum"),
        F.sum(F.col("promo_flag").cast("int")).alias("promo_cells"),
        F.max("promo_depth").alias("max_depth"),
        F.avg("lag_units").alias("mean_lag"),
        F.avg("roll4_units").alias("mean_roll4"),
    )
    plan = aggregated._jdf.queryExecution().toString()
    out = aggregated.orderBy("store_id", "week").toPandas()
    return out, plan


def scale_evidence(spark, rows: int = SCALE_ROWS, target: Path | None = None) -> dict:
    """Generated rows at scale: materialise partitioned parquet, then read it back."""
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    target = target or (Path(__file__).resolve().parent.parent / "data" / "spark" / "scale")
    started = time.perf_counter()
    base = spark.range(rows).select(
        (F.col("id") % 2000).cast("int").alias("store_num"),
        ((F.col("id") / 2000) % 100).cast("int").alias("sku_num"),
        ((F.col("id") / 200_000) % 83).cast("int").alias("week"),
    )
    with_measures = base.select(
        "store_num",
        "sku_num",
        "week",
        F.when(F.col("week") % 4 == 2, F.lit(0.2)).otherwise(F.lit(0.0)).alias("depth"),
    )
    window = Window.partitionBy("store_num", "sku_num").orderBy("week")
    features = with_measures.select(
        "*",
        F.avg("depth").over(window.rowsBetween(-3, 0)).alias("roll4_depth"),
        F.lag("depth").over(window).alias("lag_depth"),
    )
    dim = spark.createDataFrame([(i, f"cat_{i}") for i in range(6)], ["cat", "label"])
    joined = features.withColumn("cat", (F.col("sku_num") % 6).cast("int")).join(
        F.broadcast(dim), on="cat", how="left"
    )
    result = joined.groupBy("store_num", "week").agg(
        F.sum("depth").alias("depth_sum"), F.avg("roll4_depth").alias("roll4")
    )
    result.write.mode("overwrite").partitionBy("week").parquet(str(target))
    output_rows = spark.read.parquet(str(target)).count()
    elapsed = time.perf_counter() - started
    plan = result._jdf.queryExecution().toString()
    return {
        "rows": int(rows),
        "output_rows": int(output_rows),
        "seconds": round(elapsed, 1),
        "partitions": int(spark.sparkContext.defaultParallelism),
        "written_to": str(target.relative_to(target.parents[2])),
        "broadcast_join_in_plan": "BroadcastHashJoin" in plan,
        "window_in_plan": "Window" in plan,
        "shuffle_in_plan": "Exchange" in plan,
    }


def run(panel_path: Path, stores: list[str] | None = None, scale_rows: int = SCALE_ROWS) -> dict:
    panel = pd.read_parquet(panel_path)
    sample = stores or sorted(panel["store_id"].unique())[:SAMPLE_STORES]
    spark = session()
    try:
        spark_out, plan = spark_aggregate(spark, panel_path, sample)
        reference = pandas_reference(panel, sample)
        merged = reference.merge(
            spark_out, on=["store_id", "week"], suffixes=("_pandas", "_spark"), how="outer"
        )
        numeric = ["units_sum", "revenue_sum", "promo_cells", "max_depth", "mean_lag", "mean_roll4"]
        diffs = {}
        mismatched_sides = 0
        for column in numeric:
            left = merged[f"{column}_pandas"]
            right = merged[f"{column}_spark"]
            diffs[column] = float((left - right).abs().max())
            mismatched_sides += int((left.isna() != right.isna()).sum())
        scale = scale_evidence(spark, scale_rows)
        return {
            "spark_version": spark.version,
            "java": os.environ.get("JAVA_HOME", "system"),
            "parity": {
                "stores": len(sample),
                "rows_compared": int(len(merged)),
                "max_abs_diff": {k: round(v, 9) for k, v in diffs.items()},
                "max_abs_diff_overall": round(max(diffs.values()), 9),
                "rows_with_missing_side": mismatched_sides,
                "ok": max(diffs.values()) < 1e-6 and mismatched_sides == 0,
            },
            "plan": {
                "broadcast_join": "BroadcastHashJoin" in plan,
                "window": "Window" in plan,
                "shuffle": "Exchange" in plan,
            },
            "scale": scale,
            "honest_scope": "local[*], single JVM; runtime is not a cluster throughput claim",
        }
    finally:
        spark.stop()
