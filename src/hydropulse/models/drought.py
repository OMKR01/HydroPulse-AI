"""Drought and low-flow stress modeling for Jharkhand river basins.

Implements:
1. Low-flow threshold computation (Q90 / 10th percentile historic discharge).
2. Meteorological drought classification based on SPI-30d, SPI-90d, and SPI-180d.
3. Combined drought severity status (integrating meteorological and hydrological stress).
4. 30-day forward drought outlook incorporating short-term forecasts and climatology.
5. Batch station evaluator with leak-free threshold fitting.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd

from src.hydropulse.features.spi import classify_spi

logger = logging.getLogger(__name__)

DroughtSeverity = Literal["Normal", "Watch", "Moderate", "Severe", "Extreme"]
OutlookTrend = Literal["Improving", "Persistent Low Flow", "Deteriorating", "Normal"]


@dataclass(frozen=True)
class DroughtAssessment:
    """Snapshot assessment of drought and low-flow conditions for a station."""

    station_id: str
    date: str
    severity: DroughtSeverity
    composite_score: float  # Scale from 0.0 (Normal) to 1.0 (Extreme)
    spi_30d: float | None
    spi_90d: float | None
    spi_180d: float | None
    spi_category: str
    current_discharge: float | None
    low_flow_threshold: float
    is_low_flow: bool
    primary_stressor: str
    advisory_message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DroughtOutlook:
    """30-day forward drought outlook combining forecast signals and seasonal normals."""

    station_id: str
    as_of_date: str
    current_severity: DroughtSeverity
    projected_deficit_pct: float
    forecast_low_flow_days_7d: int
    outlook_trend: OutlookTrend
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_low_flow_threshold(
    discharge_series: pd.Series | np.ndarray,
    quantile: float = 0.10,
    min_samples: int = 30,
) -> float:
    """Compute low-flow threshold (Q90 low-flow = 10th percentile of historic discharge).

    In hydrological engineering, the 90% exceedance flow (Q90) corresponds to the
    discharge that is exceeded 90% of the time, which equals the 10th percentile
    of the cumulative frequency distribution.

    Args:
        discharge_series: Historical discharge measurements or reanalysis (m3/s).
        quantile: Cumulative percentile corresponding to low flow (default 0.10).
        min_samples: Minimum valid observations required to compute threshold.

    Returns:
        float: Low-flow threshold in m3/s (>= 0.0). Defaults to 0.0 if insufficient data.
    """
    if isinstance(discharge_series, pd.Series):
        vals = discharge_series.dropna().to_numpy(dtype=float)
    else:
        arr = np.asarray(discharge_series, dtype=float)
        vals = arr[~np.isnan(arr)]

    if len(vals) < min_samples:
        logger.warning(
            "Insufficient discharge samples (%d < %d) to compute robust low-flow threshold",
            len(vals),
            min_samples,
        )
        return float(np.nanpercentile(vals, quantile * 100)) if len(vals) > 0 else 0.0

    threshold = float(np.percentile(vals, quantile * 100))
    return max(0.0, threshold)


def is_low_flow_stress(discharge: float | None, threshold: float) -> bool:
    """Check if instantaneous or daily discharge indicates low-flow hydrological stress."""
    if discharge is None or np.isnan(discharge):
        return False
    return float(discharge) < float(threshold)


def evaluate_drought_status(
    station_id: str,
    date: str,
    discharge: float | None,
    low_flow_threshold: float,
    spi_30d: float | None = None,
    spi_90d: float | None = None,
    spi_180d: float | None = None,
) -> DroughtAssessment:
    """Evaluate combined drought and low-flow severity status.

    Synthesizes meteorological drought (SPI-30/90/180) and hydrological drought
    (discharge < station Q90 threshold).

    Severity rules:
        - Extreme: SPI <= -2.0 OR (SPI <= -1.5 AND low_flow)
        - Severe:  SPI <= -1.5 OR (SPI <= -1.0 AND low_flow)
        - Moderate: SPI <= -1.0 OR low_flow
        - Watch:   (-1.0 < SPI <= -0.5) OR (discharge < 1.5 * low_flow_threshold)
        - Normal:  All indicators within safe ranges.
    """
    low_flow = is_low_flow_stress(discharge, low_flow_threshold)

    # Use the most severe available SPI index among 30d, 90d, 180d
    valid_spis = [s for s in (spi_30d, spi_90d, spi_180d) if s is not None and not np.isnan(s)]
    min_spi = min(valid_spis) if valid_spis else None
    spi_cat = classify_spi(min_spi) or "Near Normal"

    # Determine severity
    severity: DroughtSeverity = "Normal"
    composite_score = 0.0
    primary_stressor = "None"

    if min_spi is not None:
        if min_spi <= -2.0 or (min_spi <= -1.5 and low_flow):
            severity = "Extreme"
            composite_score = 0.95 if low_flow else 0.85
            primary_stressor = "Compound Meteorological & Hydrological Drought" if low_flow else "Severe Rainfall Deficit"
        elif min_spi <= -1.5 or (min_spi <= -1.0 and low_flow):
            severity = "Severe"
            composite_score = 0.75 if low_flow else 0.65
            primary_stressor = "Coupled Low Flow & Rainfall Deficit" if low_flow else "Sub-seasonal Rainfall Deficit"
        elif min_spi <= -1.0 or low_flow:
            severity = "Moderate"
            composite_score = 0.55 if low_flow else 0.45
            primary_stressor = "Critical River Low-Flow (Q < Q90)" if low_flow else "Moderate Meteorological Drought"
        elif min_spi <= -0.5 or (
            discharge is not None and discharge < 1.5 * low_flow_threshold
        ):
            severity = "Watch"
            composite_score = 0.30
            primary_stressor = "Low Flow Proximity / Mild Precipitation Deficit"
        else:
            severity = "Normal"
            composite_score = 0.10
            primary_stressor = "Adequate Flow & Rainfall"
    elif low_flow:
        severity = "Moderate"
        composite_score = 0.55
        primary_stressor = "Hydrological Low Flow (Discharge < Q90)"
    elif discharge is not None and discharge < 1.5 * low_flow_threshold:
        severity = "Watch"
        composite_score = 0.25
        primary_stressor = "Approaching Low-Flow Threshold"

    advisory_map: dict[DroughtSeverity, str] = {
        "Extreme": "Emergency: Extreme drought and river low-flow stress. Restrict non-essential abstraction.",
        "Severe": "Warning: Severe drought conditions. Water conservation protocols advised across catchment.",
        "Moderate": "Advisory: Moderate drought/low-flow stress detected. Monitor intake reservoirs.",
        "Watch": "Notice: Approaching low-flow stress or mild dry spell. Routine surveillance active.",
        "Normal": "Status: River discharge and moisture levels within seasonal bounds.",
    }

    return DroughtAssessment(
        station_id=station_id,
        date=str(date),
        severity=severity,
        composite_score=round(composite_score, 3),
        spi_30d=round(spi_30d, 2) if spi_30d is not None and not np.isnan(spi_30d) else None,
        spi_90d=round(spi_90d, 2) if spi_90d is not None and not np.isnan(spi_90d) else None,
        spi_180d=round(spi_180d, 2) if spi_180d is not None and not np.isnan(spi_180d) else None,
        spi_category=spi_cat,
        current_discharge=round(float(discharge), 2) if discharge is not None and not np.isnan(discharge) else None,
        low_flow_threshold=round(float(low_flow_threshold), 2),
        is_low_flow=low_flow,
        primary_stressor=primary_stressor,
        advisory_message=advisory_map[severity],
    )


def compute_30d_drought_outlook(
    station_id: str,
    as_of_date: str,
    current_assessment: DroughtAssessment,
    forecast_precip_7d: list[float] | float,
    normal_monthly_precip: float,
    forecast_discharge_7d: list[float] | np.ndarray | None = None,
) -> DroughtOutlook:
    """Compute a forward 30-day drought and low-flow outlook.

    Args:
        station_id: Identifier of the station.
        as_of_date: Reference evaluation date.
        current_assessment: Current DroughtAssessment snapshot.
        forecast_precip_7d: Next 7-day cumulative precipitation forecast (mm), or list of daily rain.
        normal_monthly_precip: Climatological normal monthly rainfall for this calendar window (mm).
        forecast_discharge_7d: Optional 7-day lead discharge forecast array (m3/s).
    """
    if isinstance(forecast_precip_7d, list):
        precip_7d_sum = float(sum(forecast_precip_7d))
    else:
        precip_7d_sum = float(forecast_precip_7d)

    # Expected 7-day portion of monthly precipitation
    expected_7d = max(1.0, normal_monthly_precip * (7.0 / 30.0))
    deficit_pct = max(-100.0, min(100.0, ((expected_7d - precip_7d_sum) / expected_7d) * 100.0))

    # Evaluate forecasted low-flow days
    low_flow_days = 0
    if forecast_discharge_7d is not None and len(forecast_discharge_7d) > 0:
        for q in forecast_discharge_7d:
            if q is not None and not np.isnan(q) and q < current_assessment.low_flow_threshold:
                low_flow_days += 1

    # Trend determination
    if current_assessment.severity in ("Moderate", "Severe", "Extreme"):
        if precip_7d_sum >= 1.5 * expected_7d or low_flow_days == 0:
            trend: OutlookTrend = "Improving"
            summary = (
                f"Anticipated rainfall ({precip_7d_sum:.1f} mm) is expected to alleviate "
                f"low-flow stress over the coming 7-30 days."
            )
        elif low_flow_days >= 4 or deficit_pct > 40.0:
            trend = "Persistent Low Flow"
            summary = (
                f"Low-flow stress projected to persist with {low_flow_days}/7 days below Q90 "
                f"and a {deficit_pct:.1f}% precipitation deficit."
            )
        else:
            trend = "Deteriorating"
            summary = "Moisture deficits indicate sustained hydrological stress across the basin reach."
    else:
        if deficit_pct > 60.0 and low_flow_days >= 3:
            trend = "Deteriorating"
            summary = (
                f"Severe forward rain deficit ({deficit_pct:.1f}%) may tip river discharge "
                f"into low-flow stress within the next 30 days."
            )
        else:
            trend = "Normal"
            summary = "Discharge and rainfall outlook remain consistent with seasonal baselines."

    return DroughtOutlook(
        station_id=station_id,
        as_of_date=as_of_date,
        current_severity=current_assessment.severity,
        projected_deficit_pct=round(deficit_pct, 1),
        forecast_low_flow_days_7d=low_flow_days,
        outlook_trend=trend,
        summary=summary,
    )


class StationDroughtEvaluator:
    """Manages threshold estimation and continuous drought tracking for a river station."""

    def __init__(
        self,
        station_id: str,
        low_flow_quantile: float = 0.10,
    ) -> None:
        self.station_id = station_id
        self.low_flow_quantile = low_flow_quantile
        self.threshold: float | None = None
        self._fitted = False

    def fit(self, historical_df: pd.DataFrame, discharge_col: str = "discharge_m3s") -> StationDroughtEvaluator:
        """Fit low-flow threshold on historical training/reference period without future data."""
        if discharge_col not in historical_df.columns:
            raise ValueError(f"Column '{discharge_col}' not found in dataframe")

        self.threshold = compute_low_flow_threshold(
            historical_df[discharge_col],
            quantile=self.low_flow_quantile,
        )
        self._fitted = True
        logger.info(
            "Station %s: fitted low-flow Q%d threshold = %.2f m3/s",
            self.station_id,
            int(self.low_flow_quantile * 100),
            self.threshold,
        )
        return self

    def transform(
        self,
        df: pd.DataFrame,
        discharge_col: str = "discharge_m3s",
        date_col: str = "date",
    ) -> pd.DataFrame:
        """Annotate dataframe with low-flow flags and drought severity classifications."""
        if not self._fitted or self.threshold is None:
            raise RuntimeError("Evaluator must be fit on reference data before transform()")

        out = df.copy()
        thresh = self.threshold

        out["is_low_flow"] = out[discharge_col].apply(lambda q: is_low_flow_stress(q, thresh))
        out["low_flow_threshold"] = thresh

        # Vectorized drought classification
        severities: list[str] = []
        composite_scores: list[float] = []

        has_spi_30 = "spi_30d" in out.columns
        has_spi_90 = "spi_90d" in out.columns
        has_spi_180 = "spi_180d" in out.columns

        for _, row in out.iterrows():
            spi_30 = row.get("spi_30d") if has_spi_30 else None
            spi_90 = row.get("spi_90d") if has_spi_90 else None
            spi_180 = row.get("spi_180d") if has_spi_180 else None
            q_val = row.get(discharge_col)
            d_val = row.get(date_col, "")

            assessment = evaluate_drought_status(
                station_id=self.station_id,
                date=str(d_val),
                discharge=q_val,
                low_flow_threshold=thresh,
                spi_30d=spi_30,
                spi_90d=spi_90,
                spi_180d=spi_180,
            )
            severities.append(assessment.severity)
            composite_scores.append(assessment.composite_score)

        out["drought_severity"] = severities
        out["drought_composite_score"] = composite_scores
        return out
