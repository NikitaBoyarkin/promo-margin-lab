"""Configuration for the synthetic promo panel.

Every knob lives here so a run is described by one object, not by scattered
constants. ``Config.fast()`` is the CI profile: same code path, fewer cells,
explicitly not headline numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

# Category order matters: complementary pairs are index-based (see dgp.COMPLEMENTS).
CATEGORIES = ("dairy", "bakery", "grocery", "drinks", "frozen", "nonfood")
FORMATS = ("convenience", "supermarket", "hyper")

# Contribution margin by category: 12%..35%, the range the vacancy calls out.
CM_RATE = (0.12, 0.30, 0.22, 0.26, 0.18, 0.35)
# Base weekly units per store-SKU before size/seasonality multipliers.
BASE_UNITS = (40.0, 55.0, 30.0, 45.0, 20.0, 12.0)
# List price, RUB.
BASE_PRICE = (65.0, 45.0, 120.0, 80.0, 150.0, 350.0)
# Within-category substitution intensity.
CANNIB_ALPHA = (0.18, 0.22, 0.15, 0.20, 0.12, 0.10)


@dataclass(frozen=True)
class Config:
    seed: int = 42
    n_stores: int = 120
    n_skus: int = 60
    n_weeks: int = 78
    start: str = "2024-01-01"
    promo_wave_every: int = 4
    pantry_lags: int = 3
    pantry_share: float = 0.25
    halo_rate: float = 0.06
    cross_format_rate: float = 0.03
    noise_sd: float = 0.05

    @property
    def path(self) -> str:
        return f"stores{self.n_stores}_skus{self.n_skus}_weeks{self.n_weeks}"

    def fast(self) -> Config:
        """CI profile: ~9x fewer cells, same generator, same qualitative behaviour."""
        return replace(self, n_stores=40, n_skus=30, n_weeks=52)
