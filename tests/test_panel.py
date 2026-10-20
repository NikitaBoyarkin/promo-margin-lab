"""Panel contract: grain, as-of price join, returns, money columns."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from panel import KEY, attach_price, feature_columns, validate


def test_grain_is_unique(panel) -> None:
    assert not panel.duplicated(subset=KEY).any()


def test_net_units_subtract_returns(panel) -> None:
    assert np.allclose(panel["net_units"], panel["units_sold"] - panel["units_returned"])
    assert (panel["units_returned"] > 0).any(), "test data must contain returns"


def test_unit_price_uses_promo_depth(panel) -> None:
    expected = panel["list_price"] * (1.0 - panel["promo_depth"])
    assert np.allclose(panel["unit_price"], expected, atol=0.02)


def test_revenue_uses_net_units(panel) -> None:
    expected = panel["net_units"] * panel["unit_price"]
    assert np.allclose(panel["revenue"], expected, atol=0.05)


def test_asof_join_picks_the_effective_price_version() -> None:
    facts = pd.DataFrame(
        {
            "store_id": ["S000"] * 10,
            "sku_id": ["K000"] * 10,
            "week": list(range(10)),
            "promo_flag": False,
            "promo_depth": 0.0,
            "mechanic": 0,
            "units_sold": 10.0,
            "units_returned": 0,
            "format": "convenience",
            "category": "dairy",
        }
    )
    dim = pd.DataFrame(
        {
            "store_id": ["S000", "S000"],
            "sku_id": ["K000", "K000"],
            "valid_from": [0, 5],
            "valid_to": [4, 9],
            "list_price": [100.0, 120.0],
        }
    )
    joined = attach_price(facts, dim)
    assert (joined.loc[joined["week"] < 5, "list_price"] == 100.0).all()
    assert (joined.loc[joined["week"] >= 5, "list_price"] == 120.0).all()


def test_asof_join_does_not_multiply_rows(panel, sim) -> None:
    assert len(panel) == len(sim.facts)


def test_asof_join_rejects_missing_version() -> None:
    facts = pd.DataFrame(
        {
            "store_id": ["S000"],
            "sku_id": ["K000"],
            "week": [3],
            "promo_flag": False,
            "promo_depth": 0.0,
            "mechanic": 0,
            "units_sold": 1.0,
            "units_returned": 0,
            "format": "convenience",
            "category": "dairy",
        }
    )
    dim = pd.DataFrame(
        {
            "store_id": ["S000"],
            "sku_id": ["K000"],
            "valid_from": [5],
            "valid_to": [9],
            "list_price": [100.0],
        }
    )
    with pytest.raises(ValueError, match="without a price version"):
        attach_price(facts, dim)


def test_features_exclude_truth_and_outcomes(panel) -> None:
    cols = feature_columns(panel)
    assert not [c for c in cols if c.startswith("truth_")]
    for banned in ("net_units", "revenue", "units_sold", "discount_cost"):
        assert banned not in cols


def test_features_reject_leaked_truth(panel) -> None:
    leaked = panel.copy()
    leaked["truth_base_units"] = 0.0
    with pytest.raises(ValueError, match="truth columns leaked"):
        feature_columns(leaked)


def test_validate_rejects_broken_returns(panel) -> None:
    broken = panel.copy()
    broken.loc[0, "units_returned"] = int(np.ceil(broken.loc[0, "units_sold"])) + 1
    with pytest.raises(ValueError, match="returns exceed sales"):
        validate(broken)


def test_validate_rejects_duplicate_grain(panel) -> None:
    broken = pd.concat([panel, panel.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="grain is not unique"):
        validate(broken)
