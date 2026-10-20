"""W8 claim: Spark and pandas agree on the real panel, and the plan is at scale."""

from __future__ import annotations

import pytest

pyspark = pytest.importorskip("pyspark", reason="optional group: uv sync --group spark")

from spark_job import ensure_java, run, session  # noqa: E402


@pytest.fixture(scope="module")
def result(cfg, panel, tmp_path_factory):
    try:
        ensure_java()
    except RuntimeError as exc:  # pragma: no cover - environment dependent
        pytest.skip(str(exc))
    path = tmp_path_factory.mktemp("spark") / "panel.parquet"
    panel.to_parquet(path, index=False)
    return run(path, stores=sorted(panel["store_id"].unique())[:5], scale_rows=1_000_000)


def test_parity_is_exact(result) -> None:
    parity = result["parity"]
    assert parity["ok"] is True
    assert parity["max_abs_diff_overall"] == 0.0
    assert parity["rows_with_missing_side"] == 0
    assert parity["rows_compared"] > 300


def test_plan_uses_broadcast_window_and_shuffle(result) -> None:
    plan = result["plan"]
    assert plan["broadcast_join"] is True
    assert plan["window"] is True
    assert plan["shuffle"] is True


def test_scale_run_materialises(result) -> None:
    scale = result["scale"]
    assert scale["rows"] == 1_000_000
    assert scale["output_rows"] > 0
    assert scale["seconds"] > 0
    assert scale["written_to"].startswith("data/spark")


def test_scope_is_stated(result) -> None:
    assert "not a cluster throughput claim" in result["honest_scope"]


def test_session_can_restart() -> None:
    spark = session(app="restart-check", threads=2)
    try:
        assert spark.range(3).count() == 3
    finally:
        spark.stop()
