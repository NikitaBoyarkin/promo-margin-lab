"""Reproducibility: the same seed must produce the same bytes, a new one must not."""

from __future__ import annotations

from dataclasses import replace

from config import Config
from dgp import simulate
from panel import build_panel
from paths import frame_hash


def test_same_seed_same_panel(cfg: Config) -> None:
    a = build_panel(cfg, simulate(cfg).facts, simulate(cfg).dim_price)
    b = build_panel(cfg, simulate(cfg).facts, simulate(cfg).dim_price)
    assert frame_hash(a) == frame_hash(b)


def test_different_seed_different_panel(cfg: Config) -> None:
    other = replace(cfg, seed=cfg.seed + 1)
    a = simulate(cfg)
    b = simulate(other)
    assert frame_hash(a.facts) != frame_hash(b.facts)


def test_larger_panel_scales_cells(cfg: Config) -> None:
    bigger = replace(cfg, n_stores=cfg.n_stores * 2)
    sim = simulate(bigger)
    assert len(sim.facts) == 2 * cfg.n_stores * cfg.n_skus * cfg.n_weeks
