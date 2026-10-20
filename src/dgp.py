"""Synthetic grocery promo panel with known ground truth.

The generator is the contract: every observed unit is decomposed into named
components, so an estimator can be scored against the truth it never sees.

Data-generating process (one cell = store x SKU x week):

    units_sold = base
               + gross_lift                 (own promo, saturating in depth)
               + pantry                     (post-promo pull-forward, <= 0)
               + cannibalization            (other SKUs in the category, <= 0)
               + halo                       (complementary category, >= 0)
               + cross_format               (traffic pulled from other formats)
               + noise
               + clip                       (non-negativity residual, explicit)

Promo assignment is deliberately confounded: a category manager promotes a SKU
more often when its recent demand is weak, so a naive pre-period baseline is
biased. ``truth_*`` columns are the answer key and must never reach a model.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from config import BASE_PRICE, BASE_UNITS, CANNIB_ALPHA, CATEGORIES, CM_RATE, FORMATS, Config

# Complementary category pairs, index-based against CATEGORIES.
COMPLEMENTS = {0: 1, 1: 0, 2: 3, 3: 2, 4: 5, 5: 4}

TRUTH_COLUMNS = (
    "truth_base_units",
    "truth_gross_lift_units",
    "truth_pantry_units",
    "truth_cannibalization_units",
    "truth_halo_units",
    "truth_cross_format_units",
    "truth_noise_units",
    "truth_clip_units",
)


@dataclass(frozen=True)
class Simulation:
    facts: pd.DataFrame
    truth: pd.DataFrame
    dim_price: pd.DataFrame


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _ar1(rng: np.random.Generator, shape: tuple[int, int, int], rho: float = 0.6) -> np.ndarray:
    """Persistent demand shock, so a manager can observe a run of weak weeks."""
    eps = rng.normal(size=shape)
    out = np.empty(shape)
    out[..., 0] = eps[..., 0]
    scale = np.sqrt(1.0 - rho**2)
    for w in range(1, shape[-1]):
        out[..., w] = rho * out[..., w - 1] + scale * eps[..., w]
    return out


def _seasonality(n_weeks: int) -> np.ndarray:
    w = np.arange(n_weeks)
    seasonal = 1.0 + 0.12 * np.sin(2 * np.pi * (w - 6) / 52) + 0.03 * np.cos(4 * np.pi * w / 52)
    holiday = np.isin(w % 52, (0, 1, 51))
    seasonal[holiday] *= 1.18
    return seasonal


def simulate(cfg: Config) -> Simulation:
    rng = np.random.default_rng(cfg.seed)
    n_s, n_k, n_w = cfg.n_stores, cfg.n_skus, cfg.n_weeks
    shape = (n_s, n_k, n_w)

    # ---- dimensions -----------------------------------------------------
    fmt = rng.choice(len(FORMATS), size=n_s, p=(0.5, 0.35, 0.15))
    size_mult = np.array((0.6, 1.0, 1.8))[fmt] * np.exp(rng.normal(0, 0.15, n_s))
    store_fe = rng.normal(0, 0.12, n_s)
    promo_intensity = np.exp(rng.normal(0, 0.2, n_s))

    category = np.arange(n_k) % len(CATEGORIES)
    sku_base = np.array(BASE_UNITS)[category] * np.exp(rng.normal(0, 0.35, n_k))
    cm_rate = np.array(CM_RATE)[category] + rng.normal(0, 0.015, n_k)
    cm_rate = np.clip(cm_rate, 0.10, 0.38)
    deal_prone = rng.beta(2, 3, n_k)
    list_price = np.array(BASE_PRICE)[category] * np.exp(rng.normal(0, 0.12, n_k))
    # Share of the discount funded by the supplier: 0–50%, stable per SKU.
    funded_share = rng.beta(2, 2, n_k) * 0.5

    # ---- base demand ----------------------------------------------------
    seasonal = _seasonality(n_w)
    trend = 1.0 + 0.0015 * np.arange(n_w)
    shock = _ar1(rng, shape)

    base = (
        sku_base[None, :, None]
        * size_mult[:, None, None]
        * seasonal[None, None, :]
        * trend[None, None, :]
        * np.exp(store_fe)[:, None, None]
        * np.exp(0.10 * shock)
    )

    # ---- promo assignment (confounded by recent demand) -----------------
    wave = np.arange(n_w) // cfg.promo_wave_every
    active_a = (wave * 2) % len(CATEGORIES)
    active_b = (wave * 2 + 1) % len(CATEGORIES)
    in_wave = np.isin(np.arange(n_w) % cfg.promo_wave_every, (2, 3))
    available = np.zeros((n_k, n_w), dtype=bool)
    for k in range(n_k):
        c = category[k]
        available[k] = in_wave & ((active_a == c) | (active_b == c))

    # A category manager acts on recent sales, not on this week's unobserved shock:
    # the signal is a short backward-looking average, so a history-aware baseline
    # can in principle recover it.
    signal = np.zeros_like(shock)
    for lag, weight in ((1, 0.5), (2, 0.3), (3, 0.2)):
        signal[:, :, lag:] += weight * shock[:, :, :-lag]
    z_signal = -(signal - signal.mean()) / signal.std()
    logit = -0.55 + 1.10 * z_signal + 0.40 * (cm_rate[None, :, None] - 0.22) / 0.10
    promo = (rng.random(shape) < _sigmoid(logit)) & available[None, :, :]

    depth = np.clip(
        0.05 + 0.30 * rng.beta(2, 2, shape) + 0.10 * (cm_rate[None, :, None] - 0.12) / 0.23,
        0.05,
        0.40,
    )
    depth = np.where(promo, depth, 0.0)
    mechanic = np.where(promo, rng.integers(0, 3, shape), 0)

    # ---- response -------------------------------------------------------
    responsiveness = (
        1.10
        * np.exp(rng.normal(0, 0.35, (n_s, n_k)))
        * (0.5 + 1.2 * deal_prone)[None, :]
        * promo_intensity[:, None]
    )
    lift_mult = responsiveness[:, :, None] * (1.0 - np.exp(-3.5 * depth))
    gross_lift = base * lift_mult * promo

    # ---- pantry loading: next weeks give back part of the lift ----------
    decay = np.array((0.5, 0.3, 0.2))[: cfg.pantry_lags]
    pantry = np.zeros(shape)
    for lag, weight in enumerate(decay, start=1):
        pantry[..., lag:] -= cfg.pantry_share * weight * gross_lift[..., :-lag]

    # ---- within-category cannibalization --------------------------------
    sub_w = {c: rng.dirichlet(np.ones(int((category == c).sum()))) for c in range(len(CATEGORIES))}
    cannib = np.zeros(shape)
    for c in range(len(CATEGORIES)):
        idx = np.where(category == c)[0]
        category_lift = gross_lift[:, idx, :].sum(axis=1)  # (S, W)
        others = category_lift[:, None, :] - gross_lift[:, idx, :]
        cannib[:, idx, :] = -CANNIB_ALPHA[c] * others * sub_w[c][None, :, None]

    # ---- halo from complementary category -------------------------------
    halo = np.zeros(shape)
    halo_w = rng.uniform(0.6, 1.4, n_k)
    for c in range(len(CATEGORIES)):
        idx = np.where(category == c)[0]
        comp_idx = np.where(category == COMPLEMENTS[c])[0]
        complement_lift = gross_lift[:, comp_idx, :].sum(axis=1)
        halo[:, idx, :] = cfg.halo_rate * complement_lift[:, None, :] * halo_w[None, idx, None]

    # ---- cross-format traffic shift -------------------------------------
    cross = np.zeros(shape)
    for c in range(len(CATEGORIES)):
        idx = np.where(category == c)[0]
        category_lift = gross_lift[:, idx, :].sum(axis=1)  # (S, W)
        weights = sub_w[c]
        for f in range(len(FORMATS)):
            mask = fmt == f
            n_other = int((~mask).sum())
            if n_other == 0:
                continue
            pulled = category_lift[~mask].sum(axis=0) / n_other  # (W,)
            block = cross[mask]
            block[:, idx, :] += (
                -cfg.cross_format_rate * pulled[None, None, :] * weights[None, :, None]
            )
            cross[mask] = block

    # ---- noise, clipping, returns ---------------------------------------
    noise_sd = cfg.noise_sd * (base + 0.5 * np.abs(gross_lift))
    noise = rng.normal(0, 1, shape) * noise_sd
    raw = base + gross_lift + pantry + cannib + halo + cross + noise
    sold = np.clip(raw, 0.0, None)
    clip_adj = sold - raw

    return_rate = np.where(category == 5, 0.015, 0.004)[None, :, None]
    returned = rng.binomial(np.floor(sold).astype(np.int64), return_rate)

    # ---- flatten --------------------------------------------------------
    s_idx, k_idx, w_idx = np.meshgrid(np.arange(n_s), np.arange(n_k), np.arange(n_w), indexing="ij")
    keys = pd.DataFrame(
        {
            "store_id": [f"S{i:03d}" for i in s_idx.ravel()],
            "sku_id": [f"K{i:03d}" for i in k_idx.ravel()],
            "week": w_idx.ravel().astype("int16"),
        }
    )

    facts = keys.copy()
    facts["promo_flag"] = promo.ravel()
    facts["promo_depth"] = depth.ravel().round(4)
    facts["mechanic"] = mechanic.ravel().astype("int8")
    facts["units_sold"] = sold.ravel().round(3)
    facts["units_returned"] = returned.ravel()
    facts["format"] = np.array(FORMATS)[fmt][s_idx.ravel()]
    facts["category"] = np.array(CATEGORIES)[category][k_idx.ravel()]
    facts["funded_share"] = np.broadcast_to(funded_share[None, :, None], shape).ravel().round(3)

    truth = keys.copy()
    truth["truth_base_units"] = base.ravel().round(4)
    truth["truth_gross_lift_units"] = gross_lift.ravel().round(4)
    truth["truth_pantry_units"] = pantry.ravel().round(4)
    truth["truth_cannibalization_units"] = cannib.ravel().round(4)
    truth["truth_halo_units"] = halo.ravel().round(4)
    truth["truth_cross_format_units"] = cross.ravel().round(4)
    truth["truth_noise_units"] = noise.ravel().round(4)
    truth["truth_clip_units"] = clip_adj.ravel().round(4)

    dim_price = _price_dimension(rng, cfg, fmt, list_price, s_idx, k_idx)

    return Simulation(facts=facts, truth=truth, dim_price=dim_price)


def _price_dimension(
    rng: np.random.Generator,
    cfg: Config,
    fmt: np.ndarray,
    list_price: np.ndarray,
    s_idx: np.ndarray,
    k_idx: np.ndarray,
) -> pd.DataFrame:
    """SCD-2 price list: several versions per store-SKU over the horizon."""
    stores = np.array([f"S{i:03d}" for i in range(cfg.n_stores)])
    skus = np.array([f"K{i:03d}" for i in range(cfg.n_skus)])
    zone = np.exp(rng.normal(0, 0.05, cfg.n_stores))
    rows = []
    for s in range(cfg.n_stores):
        for k in range(cfg.n_skus):
            n_versions = int(rng.integers(3, 6))
            starts = np.concatenate(
                ([0], np.sort(rng.choice(np.arange(1, cfg.n_weeks), n_versions - 1, replace=False)))
            )
            level = list_price[k] * zone[s] * (1.0 if fmt[s] != 2 else 1.02)
            for i, start in enumerate(starts):
                level *= np.exp(rng.normal(0, 0.03))
                end = int(starts[i + 1] - 1) if i + 1 < len(starts) else cfg.n_weeks - 1
                rows.append((stores[s], skus[k], int(start), end, round(float(level), 2)))
    return pd.DataFrame(
        rows, columns=["store_id", "sku_id", "valid_from", "valid_to", "list_price"]
    )
