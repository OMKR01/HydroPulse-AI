"""Data cleaning, gap detection, non-destructive outlier tagging, and train-only scaling.

Adheres strictly to AGENTS.md rules:
- Outliers are explicitly flagged with boolean flags and reasons; never silently deleted.
- Missing values within short intervals (<= 3 days) are flagged with is_interpolated=True.
- Feature scaling is fit strictly on training splits to prevent data leakage.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def detect_gaps(
    df: pd.DataFrame,
    date_col: str = "date",
    freq: str = "D",
) -> list[dict[str, Any]]:
    """Detect missing dates and contiguous gap periods in a time-series dataframe.

    Returns a list of dicts describing each gap: start_date, end_date, gap_days.
    """
    if df.empty or len(df) < 2:
        return []

    df_sorted = df.sort_values(by=date_col).copy()
    dates = pd.to_datetime(df_sorted[date_col])
    expected_range = pd.date_range(start=dates.min(), end=dates.max(), freq=freq)

    missing_dates = expected_range.difference(dates)
    if missing_dates.empty:
        return []

    # Group contiguous missing dates
    gaps: list[dict[str, Any]] = []
    gap_start = missing_dates[0]
    prev_date = missing_dates[0]

    for d in missing_dates[1:]:
        if (d - prev_date).days == 1:
            prev_date = d
        else:
            gap_days = (prev_date - gap_start).days + 1
            gaps.append(
                {
                    "start_date": gap_start.strftime("%Y-%m-%d"),
                    "end_date": prev_date.strftime("%Y-%m-%d"),
                    "gap_days": gap_days,
                }
            )
            gap_start = d
            prev_date = d

    gap_days = (prev_date - gap_start).days + 1
    gaps.append(
        {
            "start_date": gap_start.strftime("%Y-%m-%d"),
            "end_date": prev_date.strftime("%Y-%m-%d"),
            "gap_days": gap_days,
        }
    )

    logger.info("Detected %d date gap intervals in time-series.", len(gaps))
    return gaps


def fill_small_gaps(
    df: pd.DataFrame,
    max_gap_days: int = 3,
    date_col: str = "date",
    numeric_cols: list[str] | None = None,
) -> pd.DataFrame:
    """Reindex to continuous daily frequency and interpolate small gaps (<= max_gap_days).

    Flagged with `is_interpolated=True` to maintain provenance integrity.
    """
    if df.empty:
        return df.copy()

    df_clean = df.copy()
    df_clean[date_col] = pd.to_datetime(df_clean[date_col])
    df_clean = df_clean.sort_values(by=date_col).drop_duplicates(subset=[date_col])

    # Mark original rows
    if "is_interpolated" not in df_clean.columns:
        df_clean["is_interpolated"] = False

    full_dates = pd.date_range(
        start=df_clean[date_col].min(),
        end=df_clean[date_col].max(),
        freq="D",
        name=date_col,
    )
    df_reindexed = df_clean.set_index(date_col).reindex(full_dates)

    # Missing rows flagged
    missing_mask = df_reindexed["is_interpolated"].isna()
    df_reindexed.loc[missing_mask, "is_interpolated"] = True

    # Identify numeric columns to interpolate
    target_cols = numeric_cols or [
        c
        for c in [
            "precipitation_mm",
            "temperature_max_c",
            "temperature_min_c",
            "relative_humidity_mean",
            "discharge_m3s",
            "discharge_mean_m3s",
        ]
        if c in df_reindexed.columns
    ]

    for col in target_cols:
        # Interpolate only up to max_gap_days
        df_reindexed[col] = df_reindexed[col].interpolate(
            method="linear", limit=max_gap_days, limit_direction="forward"
        )

    # Forward fill metadata strings
    for meta_col in ["station_id", "provenance"]:
        if meta_col in df_reindexed.columns:
            df_reindexed[meta_col] = df_reindexed[meta_col].ffill()

    # Stamp interpolated provenance if filled
    if "provenance" in df_reindexed.columns:
        df_reindexed.loc[df_reindexed["is_interpolated"], "provenance"] = "interpolated"

    df_out = df_reindexed.reset_index()
    df_out[date_col] = df_out[date_col].dt.strftime("%Y-%m-%d")
    return df_out


def detect_outliers(
    df: pd.DataFrame,
    precip_col: str = "precipitation_mm",
    discharge_col: str = "discharge_m3s",
    precip_upper_bound: float = 600.0,
    zscore_threshold: float = 4.0,
) -> pd.DataFrame:
    """Identify potential physical and statistical outliers without deleting any observations.

    Adds boolean flags:
    - is_outlier_precip
    - is_outlier_discharge
    - outlier_reason (pipe-delimited string explaining why flagged)
    """
    df_out = df.copy()

    df_out["is_outlier_precip"] = False
    df_out["is_outlier_discharge"] = False
    df_out["outlier_reason"] = ""

    # 1. Precipitation Bounds (monsoon records in Jharkhand rarely exceed 500-600 mm/day)
    if precip_col in df_out.columns:
        neg_p = df_out[precip_col] < 0.0
        extreme_p = df_out[precip_col] > precip_upper_bound

        df_out.loc[neg_p, "is_outlier_precip"] = True
        df_out.loc[extreme_p, "is_outlier_precip"] = True

        for idx in df_out[neg_p | extreme_p].index:
            reason = (
                "negative_rainfall" if df_out.loc[idx, precip_col] < 0 else "exceeds_physical_max"
            )
            curr = df_out.loc[idx, "outlier_reason"]
            df_out.loc[idx, "outlier_reason"] = f"{curr}|{reason}".strip("|")

    # 2. Discharge Outliers (negative flow or extreme rolling Z-scores)
    if discharge_col in df_out.columns:
        q_series = df_out[discharge_col].dropna()
        neg_q = df_out[discharge_col] < 0.0
        df_out.loc[neg_q, "is_outlier_discharge"] = True

        for idx in df_out[neg_q].index:
            curr = df_out.loc[idx, "outlier_reason"]
            df_out.loc[idx, "outlier_reason"] = f"{curr}|negative_discharge".strip("|")

        if len(q_series) > 14:
            q_mean = q_series.mean()
            q_std = q_series.std()
            if q_std > 1e-6:
                z_scores = (df_out[discharge_col] - q_mean).abs() / q_std
                stat_outliers = z_scores > zscore_threshold
                df_out.loc[stat_outliers, "is_outlier_discharge"] = True

                for idx in df_out[stat_outliers].index:
                    curr = df_out.loc[idx, "outlier_reason"]
                    df_out.loc[idx, "outlier_reason"] = f"{curr}|extreme_zscore".strip("|")

    return df_out


@dataclass
class TrainOnlyScaler:
    """Robust or Standard scaler fitted strictly on training partition to prevent leakage."""

    method: str = "robust"  # "robust" (median/IQR) or "standard" (mean/std)
    center_: dict[str, float] = field(default_factory=dict)
    scale_: dict[str, float] = field(default_factory=dict)
    feature_names_: list[str] = field(default_factory=list)

    def fit(self, df: pd.DataFrame, feature_cols: list[str]) -> TrainOnlyScaler:
        """Compute scaling parameters on train split only."""
        self.feature_names_ = [c for c in feature_cols if c in df.columns]
        self.center_.clear()
        self.scale_.clear()

        for col in self.feature_names_:
            series = df[col].dropna()
            if series.empty:
                continue

            if self.method == "robust":
                med = float(series.median())
                q75 = float(series.quantile(0.75))
                q25 = float(series.quantile(0.25))
                iqr = q75 - q25
                scale_val = iqr if iqr > 1e-6 else float(series.std() or 1.0)
                self.center_[col] = med
                self.scale_[col] = scale_val if scale_val > 1e-6 else 1.0
            else:
                mean_val = float(series.mean())
                std_val = float(series.std() or 1.0)
                self.center_[col] = mean_val
                self.scale_[col] = std_val if std_val > 1e-6 else 1.0

        return self

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply fitted scaling parameters to any partition."""
        df_scaled = df.copy()
        for col in self.feature_names_:
            if col in df_scaled.columns and col in self.center_:
                c = self.center_[col]
                s = self.scale_[col]
                df_scaled[f"{col}_scaled"] = (df_scaled[col] - c) / s
        return df_scaled

    def inverse_transform(self, df: pd.DataFrame) -> pd.DataFrame:
        """Invert scaled features back to physical units."""
        df_inv = df.copy()
        for col in self.feature_names_:
            scaled_col = f"{col}_scaled"
            if scaled_col in df_inv.columns and col in self.center_:
                c = self.center_[col]
                s = self.scale_[col]
                df_inv[col] = (df_inv[scaled_col] * s) + c
        return df_inv
