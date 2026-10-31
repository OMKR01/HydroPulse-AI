"""Temporal, lag, rolling window, and basin topology feature extraction.

CRITICAL LEAKAGE RULE:
No feature computed at row t may observe values at t or t+k. All lags and rolling aggregations
use strictly past values (shifted by >= 1 step) to ensure zero look-ahead bias.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_rainfall_lags(
    df: pd.DataFrame,
    precip_col: str = "precipitation_mm",
    max_lags: int = 14,
) -> pd.DataFrame:
    """Generate lagged precipitation features from t-1 to t-max_lags."""
    df_out = df.copy()
    if precip_col not in df_out.columns:
        return df_out

    for lag in range(1, max_lags + 1):
        df_out[f"precip_lag_{lag}"] = df_out[precip_col].shift(lag)

    return df_out


def compute_rolling_rainfall(
    df: pd.DataFrame,
    precip_col: str = "precipitation_mm",
    windows: tuple[int, ...] = (3, 7, 14, 30),
) -> pd.DataFrame:
    """Generate rolling cumulative precipitation sums using strictly past observations (shifted by 1)."""
    df_out = df.copy()
    if precip_col not in df_out.columns:
        return df_out

    # Shift by 1 first to prevent target leakage at time t
    shifted = df_out[precip_col].shift(1)

    for w in windows:
        df_out[f"precip_roll_sum_{w}d"] = shifted.rolling(window=w, min_periods=1).sum()

    return df_out


def compute_api(
    df: pd.DataFrame,
    precip_col: str = "precipitation_mm",
    decay: float = 0.88,
    max_lookback: int = 14,
) -> pd.DataFrame:
    """Compute Antecedent Precipitation Index (API / wetness proxy).

    API_t = sum_{k=1..max_lookback} (decay^k * P_{t-k})
    """
    df_out = df.copy()
    if precip_col not in df_out.columns:
        df_out["antecedent_precipitation_index"] = 0.0
        return df_out

    api_series = pd.Series(0.0, index=df_out.index)
    for k in range(1, max_lookback + 1):
        weight = decay**k
        lagged_rain = df_out[precip_col].shift(k).fillna(0.0)
        api_series += weight * lagged_rain

    df_out["antecedent_precipitation_index"] = api_series
    return df_out


def compute_cyclical_calendar(
    df: pd.DataFrame,
    date_col: str = "date",
) -> pd.DataFrame:
    """Generate cyclical day-of-year and month sin/cos calendar encodings."""
    df_out = df.copy()
    dt_series = pd.to_datetime(df_out[date_col])

    doy = dt_series.dt.dayofyear
    df_out["doy_sin"] = np.sin(2.0 * np.pi * doy / 365.25)
    df_out["doy_cos"] = np.cos(2.0 * np.pi * doy / 365.25)

    month = dt_series.dt.month
    df_out["month_sin"] = np.sin(2.0 * np.pi * month / 12.0)
    df_out["month_cos"] = np.cos(2.0 * np.pi * month / 12.0)

    # Monsoon season indicator (June to October: months 6, 7, 8, 9, 10)
    df_out["is_monsoon"] = month.isin([6, 7, 8, 9, 10]).astype(int)

    return df_out


def compute_discharge_lags(
    df: pd.DataFrame,
    discharge_col: str = "discharge_m3s",
    max_lags: int = 7,
    windows: tuple[int, ...] = (3, 7),
) -> pd.DataFrame:
    """Generate discharge auto-lags and past rolling mean flows."""
    df_out = df.copy()
    if discharge_col not in df_out.columns:
        return df_out

    for lag in range(1, max_lags + 1):
        df_out[f"discharge_lag_{lag}"] = df_out[discharge_col].shift(lag)

    shifted = df_out[discharge_col].shift(1)
    for w in windows:
        df_out[f"discharge_roll_mean_{w}d"] = shifted.rolling(window=w, min_periods=1).mean()

    return df_out


def compute_upstream_features(
    df_target: pd.DataFrame,
    df_upstream: pd.DataFrame | None,
    date_col: str = "date",
) -> pd.DataFrame:
    """Propagate upstream basin discharge and precipitation to downstream station.

    Uses strictly past values from upstream station.
    """
    df_out = df_target.copy()
    if df_upstream is None or df_upstream.empty:
        df_out["upstream_discharge_lag_1"] = np.nan
        df_out["upstream_discharge_lag_2"] = np.nan
        df_out["upstream_precip_roll_3d"] = np.nan
        return df_out

    up_df = df_upstream.copy().sort_values(by=date_col)
    up_sub = pd.DataFrame()
    up_sub[date_col] = up_df[date_col]

    if "discharge_m3s" in up_df.columns:
        up_sub["upstream_discharge_lag_1"] = up_df["discharge_m3s"].shift(1)
        up_sub["upstream_discharge_lag_2"] = up_df["discharge_m3s"].shift(2)
    else:
        up_sub["upstream_discharge_lag_1"] = np.nan
        up_sub["upstream_discharge_lag_2"] = np.nan

    if "precipitation_mm" in up_df.columns:
        up_sub["upstream_precip_roll_3d"] = (
            up_df["precipitation_mm"].shift(1).rolling(3, min_periods=1).sum()
        )
    else:
        up_sub["upstream_precip_roll_3d"] = np.nan

    merged = pd.merge(df_out, up_sub, on=date_col, how="left")
    return merged


def extract_all_features(
    df: pd.DataFrame,
    df_upstream: pd.DataFrame | None = None,
    date_col: str = "date",
) -> pd.DataFrame:
    """Master feature extraction pipeline applying all lag, rolling, API, and calendar transformations."""
    df_features = df.sort_values(by=date_col).copy()

    df_features = compute_rainfall_lags(df_features, max_lags=14)
    df_features = compute_rolling_rainfall(df_features, windows=(3, 7, 14, 30))
    df_features = compute_api(df_features, decay=0.88, max_lookback=14)
    df_features = compute_cyclical_calendar(df_features, date_col=date_col)
    df_features = compute_discharge_lags(df_features, max_lags=7, windows=(3, 7))
    df_features = compute_upstream_features(df_features, df_upstream, date_col=date_col)

    return df_features
