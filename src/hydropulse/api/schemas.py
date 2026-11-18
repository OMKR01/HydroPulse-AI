"""Pydantic v2 schemas for HydroPulse AI API payloads and response envelopes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ─────────────────────── 1. Common Envelopes & Error Models ───────────────────────


class ErrorDetail(BaseModel):
    status_code: int = Field(..., description="HTTP status code")
    title: str = Field(..., description="Short error summary")
    detail: str = Field(..., description="Detailed description of the error")


class ErrorEnvelope(BaseModel):
    error: ErrorDetail
    generated_at: str = Field(..., description="ISO 8601 UTC timestamp")
    service: str = Field(default="hydropulse-ai", description="Microservice identifier")
    version: str = Field(default="0.1.0", description="API version")
    request_id: str | None = Field(default=None, description="Unique trace identifier")


class BaseEnvelope(BaseModel):
    generated_at: str = Field(..., description="ISO 8601 UTC timestamp of response generation")
    data_provenance: Literal["observed", "model_reanalysis", "forecast", "synthetic"] = Field(
        ..., description="Provenance classification of underlying data"
    )
    is_stale: bool = Field(default=False, description="Whether data exceeds freshness window")


# ─────────────────────── 2. Station Models ───────────────────────────────────────


class StationItem(BaseModel):
    id: str = Field(..., description="Unique station slug identifier")
    name: str = Field(..., description="Human-readable station title")
    river: str = Field(..., description="River name")
    basin: str = Field(..., description="River basin name (Damodar or Subarnarekha)")
    state: str = Field(default="Jharkhand")
    district: str = Field(...)
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    verified: bool = Field(default=False, description="Whether station code is officially verified")
    snap_to_river: bool = Field(default=True)
    cwc_code: str | None = None
    notes: str | None = None


class StationsListResponse(BaseEnvelope):
    count: int = Field(..., ge=0)
    stations: list[StationItem]


# ─────────────────────── 3. Forecast & History Models ────────────────────────────


class ForecastPoint(BaseModel):
    date: str = Field(..., description="Forecast date YYYY-MM-DD")
    horizon_days: int = Field(..., ge=1, le=7, description="Lead time horizon in days")
    discharge_p10_m3s: float = Field(..., ge=0.0, description="10th percentile lower quantile")
    discharge_p50_m3s: float = Field(..., ge=0.0, description="50th percentile median forecast")
    discharge_p90_m3s: float = Field(..., ge=0.0, description="90th percentile upper quantile")
    raw_glofas_m3s: float | None = Field(default=None, description="Uncorrected GloFAS reference")
    alert_level: Literal["Normal", "Watch", "Warning", "Danger"] = Field(
        default="Normal", description="Alert severity level"
    )
    alert_color: str = Field(default="#10b981", description="HEX color code for UI rendering")


class StationForecastResponse(BaseEnvelope):
    station_id: str
    station_name: str
    river: str
    basin: str
    forecast_days: int
    forecast_points: list[ForecastPoint]
    thresholds: dict[str, float]


class HistoryPoint(BaseModel):
    date: str
    discharge_m3s: float | None = None
    precipitation_mm: float | None = None
    temperature_max_c: float | None = None
    temperature_min_c: float | None = None
    relative_humidity_mean: float | None = None
    is_interpolated: bool = False
    is_outlier: bool = False


class StationHistoryResponse(BaseEnvelope):
    station_id: str
    days_returned: int
    history: list[HistoryPoint]


# ─────────────────────── 4. Risk Map & Alerts Models ─────────────────────────────


class GeoJSONGeometry(BaseModel):
    type: Literal["Point"] = "Point"
    coordinates: list[float] = Field(
        ..., min_length=2, max_length=2, description="[longitude, latitude]"
    )


class GeoJSONProperties(BaseModel):
    station_id: str
    station_name: str
    river: str
    basin: str
    current_discharge_m3s: float | None = None
    alert_level: Literal["Normal", "Watch", "Warning", "Danger"]
    alert_color: str
    alert_message_en: str
    alert_message_hi: str
    verified: bool
    data_provenance: str
    is_stale: bool


class GeoJSONFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: GeoJSONGeometry
    properties: GeoJSONProperties


class RiskMapResponse(BaseEnvelope):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[GeoJSONFeature]


class AlertItem(BaseModel):
    station_id: str
    station_name: str
    river: str
    basin: str
    alert_level: Literal["Watch", "Warning", "Danger"]
    alert_color: str
    lead_time_days: int
    peak_forecast_discharge_m3s: float
    threshold_value_m3s: float
    message_en: str
    message_hi: str
    reasons: list[str] = Field(
        default_factory=list, description="Top causal features from SHAP attribution"
    )


class AlertsResponse(BaseEnvelope):
    active_alerts_count: int
    alerts: list[AlertItem]


# ─────────────────────── 5. River Health (WQI & Drought) ─────────────────────────


class WaterQualityResponse(BaseEnvelope):
    station_id: str
    date: str
    wqi: float
    rating: Literal["Excellent", "Good", "Poor", "Very Poor", "Unfit"]
    cpcb_class: Literal["A", "B", "C", "D", "E", "Below_E"]
    sub_indices: dict[str, float]
    weights_used: dict[str, float]
    parameters_present: list[str]
    is_hotspot: bool
    hotspot_severity: Literal["None", "Moderate", "Critical"]
    hotspot_summary: str
    status_label: str  # "indicative" or "verified"


class DroughtResponse(BaseEnvelope):
    station_id: str
    date: str
    severity: Literal["Normal", "Watch", "Moderate", "Severe", "Extreme"]
    composite_score: float
    spi_30d: float | None
    spi_90d: float | None
    spi_180d: float | None
    spi_category: str
    current_discharge_m3s: float | None
    low_flow_threshold_m3s: float
    is_low_flow: bool
    primary_stressor: str
    advisory_message: str
    outlook_trend: Literal["Improving", "Persistent Low Flow", "Deteriorating", "Normal"]
    projected_deficit_pct: float
    forecast_low_flow_days_7d: int
    outlook_summary: str


# ─────────────────────── 6. Model Governance Models ──────────────────────────────


class ModelMetricsResponse(BaseEnvelope):
    system: str
    metrics_generated_at: str
    git_commit: str | None
    metrics_data: dict[str, Any]
