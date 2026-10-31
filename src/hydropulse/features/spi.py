"""Standardized Precipitation Index (SPI) computation using 2-parameter Gamma distribution.

Implements McKee et al. (1993) WMO standard methodology for SPI-1 (30d), SPI-3 (90d), and SPI-6 (180d)
with zero-precipitation adjustment and standard normal quantile transformation.
"""

from __future__ import annotations

import logging
from typing import Literal

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)

SPICategory = Literal[
    "Extremely Wet",
    "Very Wet",
    "Moderately Wet",
    "Near Normal",
    "Moderately Dry",
    "Severely Dry",
    "Extremely Dry",
]


def classify_spi(val: float | None) -> SPICategory | None:
    """Classify SPI numerical score into standard meteorological drought category."""
    if val is None or np.isnan(val):
        return None
    if val >= 2.0:
        return "Extremely Wet"
    if val >= 1.5:
        return "Very Wet"
    if val >= 1.0:
        return "Moderately Wet"
    if val > -1.0:
        return "Near Normal"
    if val > -1.5:
        return "Moderately Dry"
    if val > -2.0:
        return "Severely Dry"
    return "Extremely Dry"


def fit_spi_gamma(
    accumulated: np.ndarray,
) -> tuple[float, float, float]:
    """Fit 2-parameter Gamma distribution parameters on non-zero accumulated precipitation.

    Returns:
        tuple[float, float, float]: (alpha_shape, beta_scale, q_zero_fraction)
    """
    valid = accumulated[~np.isnan(accumulated)]
    if len(valid) < 10:
        return 1.0, 1.0, 0.0

    n_total = len(valid)
    zeros = valid <= 1e-4
    n_zeros = np.sum(zeros)
    q = float(n_zeros / n_total)

    nonzero = valid[~zeros]
    if len(nonzero) < 5:
        return 1.0, 1.0, q

    # Fit Gamma distribution with location fixed to 0
    alpha, _, scale = stats.gamma.fit(nonzero, floc=0)
    return float(alpha), float(scale), q


def transform_accumulated_to_spi(
    accumulated: np.ndarray,
    alpha: float,
    beta: float,
    q: float,
) -> np.ndarray:
    """Transform accumulated rainfall to SPI using fitted Gamma parameters and norm.ppf."""
    spi_out = np.full_like(accumulated, np.nan, dtype=float)

    valid_mask = ~np.isnan(accumulated)
    vals = accumulated[valid_mask]

    # Cumulative distribution H(x) = q + (1 - q) * G(x)
    g_x = stats.gamma.cdf(vals, a=alpha, scale=beta)
    h_x = q + (1.0 - q) * g_x

    # Clip to prevent infinite quantiles
    eps = 1e-6
    h_clipped = np.clip(h_x, eps, 1.0 - eps)

    spi_vals = stats.norm.ppf(h_clipped)
    spi_out[valid_mask] = spi_vals
    return spi_out


def _compute_expanding_spi(acc_array: np.ndarray) -> np.ndarray:
    """Compute SPI using expanding-window Thom MLE estimation to guarantee zero future leakage.

    For any index t, parameters are fit strictly on historical observations in acc_array[:t+1].
    """
    valid_mask = ~np.isnan(acc_array)
    val_clean = np.where(valid_mask, acc_array, 0.0)
    zeros = valid_mask & (val_clean <= 1e-4)
    pos = valid_mask & (val_clean > 1e-4)

    n_valid = np.cumsum(valid_mask)
    n_zeros = np.cumsum(zeros)
    n_pos = np.cumsum(pos)

    sum_pos = np.cumsum(np.where(pos, val_clean, 0.0))
    sum_log_pos = np.cumsum(np.where(pos, np.log(np.maximum(val_clean, 1e-9)), 0.0))

    out = np.full_like(acc_array, np.nan, dtype=float)
    compute_mask = valid_mask & (n_valid >= 10) & (n_pos >= 5)

    if not np.any(compute_mask):
        return out

    mean_pos = np.divide(sum_pos, n_pos, out=np.zeros_like(sum_pos), where=n_pos > 0)
    mean_log_pos = np.divide(sum_log_pos, n_pos, out=np.zeros_like(sum_log_pos), where=n_pos > 0)

    A = np.where(
        compute_mask,
        np.maximum(np.log(np.maximum(mean_pos, 1e-9)) - mean_log_pos, 1e-5),
        1.0,
    )
    alpha = (1.0 / (4.0 * A)) * (1.0 + np.sqrt(1.0 + 4.0 * A / 3.0))
    beta = np.divide(mean_pos, alpha, out=np.ones_like(mean_pos), where=alpha > 0)
    q = np.divide(n_zeros, n_valid, out=np.zeros_like(n_zeros, dtype=float), where=n_valid > 0)

    vals_eval = acc_array[compute_mask]
    g_x = stats.gamma.cdf(vals_eval, a=alpha[compute_mask], scale=beta[compute_mask])
    q_eval = q[compute_mask]
    h_x = q_eval + (1.0 - q_eval) * g_x
    h_clipped = np.clip(h_x, 1e-6, 1.0 - 1e-6)
    out[compute_mask] = stats.norm.ppf(h_clipped)
    return out


def compute_spi(
    df: pd.DataFrame,
    precip_col: str = "precipitation_mm",
    windows: tuple[int, ...] = (30, 90, 180),
    reference_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Calculate SPI-1 (30d), SPI-3 (90d), and SPI-6 (180d) columns and categories.

    Uses reference_df to fit distribution if provided (e.g. historical baseline or train split).
    When reference_df is None, uses expanding-window estimation strictly over past data to
    guarantee zero look-ahead / future data leakage.
    Uses strictly past precipitation (shifted by 1) so SPI at time t represents moisture state
    accumulated up to the start of t.
    """
    df_out = df.copy()
    if precip_col not in df_out.columns:
        return df_out

    # Shift by 1 to prevent target leakage
    shifted_precip = df_out[precip_col].shift(1)

    for w in windows:
        col_acc = f"precip_acc_{w}d"
        spi_col = f"spi_{w}d"
        cat_col = f"spi_{w}d_category"

        # Rolling accumulation
        acc_series = shifted_precip.rolling(window=w, min_periods=max(5, w // 4)).sum()
        df_out[col_acc] = acc_series

        if reference_df is not None and precip_col in reference_df.columns:
            ref_shifted = reference_df[precip_col].shift(1)
            ref_acc = ref_shifted.rolling(window=w, min_periods=max(5, w // 4)).sum()
            alpha, beta, q = fit_spi_gamma(ref_acc.dropna().to_numpy())
            spi_vals = transform_accumulated_to_spi(acc_series.to_numpy(), alpha, beta, q)
        else:
            spi_vals = _compute_expanding_spi(acc_series.to_numpy())

        df_out[spi_col] = np.round(spi_vals, 3)
        df_out[cat_col] = [classify_spi(v) for v in spi_vals]

    return df_out
