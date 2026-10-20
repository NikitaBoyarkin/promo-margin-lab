from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from config import Config  # noqa: E402
from dgp import simulate  # noqa: E402
from panel import build_panel  # noqa: E402


@pytest.fixture(scope="session")
def cfg() -> Config:
    """Full config: the claims being tested are about the shipped dataset."""
    return Config()


@pytest.fixture(scope="session")
def sim(cfg: Config):
    return simulate(cfg)


@pytest.fixture(scope="session")
def panel(cfg: Config, sim):
    return build_panel(cfg, sim.facts, sim.dim_price)


@pytest.fixture(scope="session")
def counterfactual(cfg: Config, panel, sim):
    from baseline import run as run_baseline

    return run_baseline(panel, sim.truth, cfg)["counterfactual"]
