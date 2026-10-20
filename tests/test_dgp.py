"""The generator's promise: every unit is accounted for by a named component."""

from __future__ import annotations

import numpy as np
import pandas as pd

from dgp import TRUTH_COLUMNS


def test_ledger_identity_holds(sim) -> None:
    components = sim.truth[list(TRUTH_COLUMNS)].sum(axis=1)
    assert np.allclose(components, sim.facts["units_sold"], atol=2e-3)


def test_no_negative_sales(sim) -> None:
    assert (sim.facts["units_sold"] >= 0).all()
    assert (sim.facts["units_returned"] >= 0).all()


def test_returns_do_not_exceed_sales(sim) -> None:
    assert (sim.facts["units_returned"] <= sim.facts["units_sold"]).all()


def test_promo_share_and_depth_are_realistic(sim) -> None:
    share = sim.facts["promo_flag"].mean()
    assert 0.03 < share < 0.25, f"promo share {share:.3f} outside a believable range"
    promo = sim.facts[sim.facts["promo_flag"]]
    assert promo["promo_depth"].between(0.05, 0.40).all()
    assert (promo["promo_depth"] > 0).all()


def test_non_promo_cells_have_zero_depth(sim) -> None:
    quiet = sim.facts[~sim.facts["promo_flag"]]
    assert (quiet["promo_depth"] == 0).all()


def test_pantry_drag_is_negative_and_follows_promo(sim) -> None:
    truth = sim.truth
    assert (truth["truth_pantry_units"] <= 0).all()
    assert truth["truth_pantry_units"].sum() < 0
    # A week right after a promo wave must carry more drag than a random week.
    drag = truth.groupby("week")["truth_pantry_units"].sum()
    worst = drag.idxmin()
    assert drag.loc[worst] < drag.median()


def test_cannibalization_hits_non_promoted_skus(sim) -> None:
    frame = sim.facts[["store_id", "sku_id", "week", "promo_flag", "category"]].merge(
        sim.truth, on=["store_id", "sku_id", "week"]
    )
    quiet = frame[~frame["promo_flag"]]
    assert (quiet["truth_cannibalization_units"] <= 1e-9).all()
    assert quiet["truth_cannibalization_units"].sum() < 0


def test_ground_truth_is_isolated_from_facts(sim) -> None:
    assert not [c for c in sim.facts.columns if c.startswith("truth_")]
    assert all(c.startswith("truth_") for c in TRUTH_COLUMNS)


def test_truth_has_same_grain_as_facts(sim) -> None:
    keys = ["store_id", "sku_id", "week"]
    assert len(sim.truth) == len(sim.facts)
    pd.testing.assert_frame_equal(
        sim.truth[keys].reset_index(drop=True), sim.facts[keys].reset_index(drop=True)
    )
