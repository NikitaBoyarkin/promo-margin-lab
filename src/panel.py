"""Build the analysis panel: as-of price join, returns, derived money columns.

Frozen contract (see docs/data-contract.md):
    grain  = (store_id, sku_id, week)
    net_units = units_sold - units_returned
    unit_price = list_price * (1 - promo_depth)
    revenue = net_units * unit_price

Truth columns live in a separate file and are never joined here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config import Config

KEY = ["store_id", "sku_id", "week"]

# Numeric columns that are not features: keys, outcomes, and money derived from outcomes.
NON_FEATURE = {
    *KEY,
    "units_sold",
    "units_returned",
    "net_units",
    "unit_price",
    "revenue",
    "cm",
    "discount_cost",
    "promo_cost",
}


def attach_price(facts: pd.DataFrame, dim_price: pd.DataFrame) -> pd.DataFrame:
    """As-of join: the price version effective in the fact's week.

    Same shape as the Magnit test assignment (key = item + update_date): a join
    on store/SKU alone would multiply rows and pick the wrong price version.
    """
    left = facts.sort_values("week", kind="stable").copy()
    right = dim_price.sort_values("valid_from", kind="stable").copy()
    left["week"] = left["week"].astype("int64")
    right["valid_from"] = right["valid_from"].astype("int64")
    right["valid_to"] = right["valid_to"].astype("int64")
    merged = pd.merge_asof(
        left,
        right,
        left_on="week",
        right_on="valid_from",
        by=["store_id", "sku_id"],
        direction="backward",
        allow_exact_matches=True,
    )
    if merged["list_price"].isna().any():
        raise ValueError("as-of join produced rows without a price version")
    if (merged["week"] > merged["valid_to"]).any():
        raise ValueError("as-of join picked a version that ends before the fact week")
    return merged.drop(columns=["valid_from", "valid_to"])


def build_panel(cfg: Config, facts: pd.DataFrame, dim_price: pd.DataFrame) -> pd.DataFrame:
    panel = attach_price(facts, dim_price)
    panel["week_start"] = pd.Timestamp(cfg.start) + pd.to_timedelta(panel["week"] * 7, unit="D")
    panel["net_units"] = panel["units_sold"] - panel["units_returned"]
    panel["unit_price"] = (panel["list_price"] * (1.0 - panel["promo_depth"])).round(2)
    panel["revenue"] = (panel["net_units"] * panel["unit_price"]).round(2)
    panel["discount_cost"] = (
        panel["units_sold"] * panel["promo_depth"] * panel["list_price"]
    ).round(2)
    panel["promo_cost"] = panel["discount_cost"]
    panel["supplier_funding"] = (panel["discount_cost"] * panel["funded_share"]).round(2)
    cm_rate = panel["category"].map(_cm_by_category()).astype(float)
    panel["cm_rate"] = cm_rate
    panel["cm"] = (panel["revenue"] * cm_rate).round(2)
    panel = panel.sort_values(KEY, kind="stable").reset_index(drop=True)
    validate(panel)
    return panel


def _cm_by_category() -> dict[str, float]:
    from config import CATEGORIES, CM_RATE

    return dict(zip(CATEGORIES, CM_RATE, strict=True))


def feature_columns(panel: pd.DataFrame) -> list[str]:
    """Columns a model is allowed to see. Fails loudly if truth leaked in."""
    leaked = [c for c in panel.columns if c.startswith("truth_")]
    if leaked:
        raise ValueError(f"truth columns leaked into the panel: {leaked}")
    numeric = panel.select_dtypes(include=[np.number, "bool"]).columns
    return [c for c in numeric if c not in NON_FEATURE]


def validate(panel: pd.DataFrame) -> None:
    if panel.duplicated(subset=KEY).any():
        raise ValueError("grain is not unique on (store_id, sku_id, week)")
    if (panel["units_returned"] < 0).any():
        raise ValueError("negative returns")
    if (panel["units_returned"] > panel["units_sold"]).any():
        raise ValueError("returns exceed sales")
    expected_net = panel["units_sold"] - panel["units_returned"]
    if not np.allclose(panel["net_units"], expected_net):
        raise ValueError("net_units != units_sold - units_returned")
    expected_price = panel["list_price"] * (1.0 - panel["promo_depth"])
    if not np.allclose(panel["unit_price"], expected_price, atol=0.02):
        raise ValueError("unit_price != list_price * (1 - depth)")
    if (panel["units_sold"] < 0).any():
        raise ValueError("negative sales")
    if panel["promo_depth"].lt(0).any() or panel["promo_depth"].gt(1).any():
        raise ValueError("promo_depth outside [0, 1]")
