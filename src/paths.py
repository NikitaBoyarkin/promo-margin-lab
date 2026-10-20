"""Filesystem paths, deterministic hashing and JSON writers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
PANEL = DATA / "panel"
TRUTH = DATA / "truth"
REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"

for _p in (RAW, PANEL, TRUTH, REPORTS):
    _p.mkdir(parents=True, exist_ok=True)


def frame_hash(df: pd.DataFrame) -> str:
    """Order-sensitive hash of values, stable across runs and machines."""
    payload = pd.util.hash_pandas_object(df.reset_index(drop=True), index=False)
    return hashlib.sha256(payload.to_numpy().tobytes()).hexdigest()[:16]


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
