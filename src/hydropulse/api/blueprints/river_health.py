"""River health endpoints: Water Quality Index (WQI) and Drought/Low-flow stress."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import numpy as np
import pandas as pd
from flask import Blueprint, abort, jsonify

from config.settings import DATA_DIR
from src.hydropulse.api.blueprints.stations import _get_station_by_id
from src.hydropulse.api.middleware import cached
from src.hydropulse.api.schemas import DroughtResponse, WaterQualityResponse
from src.hydropulse.models.drought import (
    compute_30d_drought_outlook,
    compute_low_flow_threshold,
    evaluate_drought_status,
)
from src.hydropulse.models.wqi import (
    calculate_wqi,
    detect_pollution_hotspots,
)

logger = logging.getLogger(__name__)

river_health_bp = Blueprint("river_health", __name__, url_prefix="/api/v1")


@river_health_bp.route("/water-quality/<station_id>", methods=["GET"])
@cached(ttl_seconds=60)
def get_water_quality(station_id: str):
    """Retrieve Weighted-Arithmetic WQI, CPCB class (A-E), sub-indices, and industrial hotspot status."""
    station = _get_station_by_id(station_id)
    if not station:
        abort(404, description=f"Station '{station_id}' not found in registry.")

    # 1. Search WQ CSV in data/raw/wq/
    wq_csv = DATA_DIR / "raw" / "wq" / "historical_monthly_wq_synthetic.csv"
    record = None
    provenance = "synthetic"

    if wq_csv.exists():
        try:
            df = pd.read_csv(wq_csv)
            sub = df[df["station_id"] == station_id].sort_values("date")
            if len(sub) > 0:
                record = sub.iloc[-1].to_dict()
                provenance = str(record.get("provenance", "synthetic"))
        except Exception as err:
            logger.warning("Error reading WQ CSV for %s: %s", station_id, err)

    if not record:
        # Generate default realistic representative reading
        rng = np.random.default_rng(abs(hash(station_id)) % (2**32))
        is_industrial = "bokaro" in station_id or "dhanbad" in station_id
        record = {
            "station_id": station_id,
            "date": datetime.now(UTC).strftime("%Y-%m-15"),
            "ph": round(float(rng.uniform(7.1, 7.8)), 2),
            "dissolved_oxygen_mg_l": round(
                float(rng.uniform(3.8, 5.8) if is_industrial else rng.uniform(6.2, 7.5)), 2
            ),
            "bod_mg_l": round(
                float(rng.uniform(3.5, 6.5) if is_industrial else rng.uniform(1.8, 2.8)), 2
            ),
            "cod_mg_l": round(
                float(rng.uniform(25.0, 55.0) if is_industrial else rng.uniform(12.0, 20.0)), 1
            ),
            "conductivity_us_cm": round(
                float(rng.uniform(600.0, 1100.0) if is_industrial else rng.uniform(350.0, 500.0)), 1
            ),
            "turbidity_ntu": round(float(rng.uniform(4.0, 12.0)), 1),
            "fecal_coliform_mpn_100ml": round(
                float(rng.uniform(600.0, 2200.0) if is_industrial else rng.uniform(150.0, 450.0)), 1
            ),
            "provenance": "synthetic",
        }

    score = calculate_wqi(record)
    hotspot = detect_pollution_hotspots(
        record,
        station_id=station_id,
        date=str(record.get("date", "")),
        provenance=provenance,
    )

    resp = WaterQualityResponse(
        generated_at=datetime.now(UTC).isoformat(),
        data_provenance=provenance if provenance in ("observed", "synthetic") else "synthetic",
        is_stale=False,
        station_id=station_id,
        date=str(record.get("date", datetime.now(UTC).strftime("%Y-%m-%d"))),
        wqi=score.wqi,
        rating=score.rating,
        cpcb_class=score.cpcb_class,
        sub_indices=score.sub_indices,
        weights_used=score.weights_used,
        parameters_present=score.parameters_present,
        is_hotspot=hotspot.is_hotspot,
        hotspot_severity=hotspot.severity,
        hotspot_summary=hotspot.summary,
        status_label=hotspot.status_label,
    )
    return jsonify(resp.model_dump())


@river_health_bp.route("/drought/<station_id>", methods=["GET"])
@cached(ttl_seconds=60)
def get_drought_status(station_id: str):
    """Retrieve SPI drought categories, low-flow Q90 status, and 30-day forward outlook."""
    station = _get_station_by_id(station_id)
    if not station:
        abort(404, description=f"Station '{station_id}' not found in registry.")

    # Check parquet for discharge and SPI
    parquet_path = DATA_DIR / "processed" / f"{station_id}.parquet"
    discharge_series: list[float] = []
    current_q: float | None = None
    spi_30: float | None = None
    spi_90: float | None = None
    spi_180: float | None = None
    provenance = "model_reanalysis"

    if parquet_path.exists():
        try:
            df = pd.read_parquet(parquet_path)
            if "discharge_m3s" in df.columns:
                valid_q = df["discharge_m3s"].dropna().tolist()
                if valid_q:
                    discharge_series = valid_q
                    current_q = float(valid_q[-1])
            if "spi_30d" in df.columns:
                v = df["spi_30d"].dropna().tolist()
                spi_30 = float(v[-1]) if v else None
            if "spi_90d" in df.columns:
                v = df["spi_90d"].dropna().tolist()
                spi_90 = float(v[-1]) if v else None
            if "spi_180d" in df.columns:
                v = df["spi_180d"].dropna().tolist()
                spi_180 = float(v[-1]) if v else None
            if "provenance" in df.columns and len(df) > 0:
                provenance = str(df["provenance"].iloc[-1])
        except Exception as err:
            logger.warning(
                "Error reading drought features from parquet for %s: %s", station_id, err
            )

    if not discharge_series:
        rng = np.random.default_rng(abs(hash(station_id)) % (2**32))
        discharge_series = list(rng.uniform(4.0, 50.0, 100))
        current_q = float(discharge_series[-1])
        spi_30 = float(rng.normal(-0.2, 0.8))
        spi_90 = float(rng.normal(-0.1, 0.7))
        spi_180 = float(rng.normal(0.0, 0.6))
        provenance = "synthetic"

    q90 = compute_low_flow_threshold(discharge_series, quantile=0.10)
    current_date = datetime.now(UTC).strftime("%Y-%m-%d")

    assessment = evaluate_drought_status(
        station_id=station_id,
        date=current_date,
        discharge=current_q,
        low_flow_threshold=q90,
        spi_30d=spi_30,
        spi_90d=spi_90,
        spi_180d=spi_180,
    )

    outlook = compute_30d_drought_outlook(
        station_id=station_id,
        as_of_date=current_date,
        current_assessment=assessment,
        forecast_precip_7d=8.5,
        normal_monthly_precip=45.0,
        forecast_discharge_7d=[current_q * 0.95 for _ in range(7)] if current_q else None,
    )

    resp = DroughtResponse(
        generated_at=datetime.now(UTC).isoformat(),
        data_provenance=provenance
        if provenance in ("observed", "model_reanalysis", "forecast")
        else "synthetic",
        is_stale=False,
        station_id=station_id,
        date=current_date,
        severity=assessment.severity,
        composite_score=assessment.composite_score,
        spi_30d=assessment.spi_30d,
        spi_90d=assessment.spi_90d,
        spi_180d=assessment.spi_180d,
        spi_category=assessment.spi_category,
        current_discharge_m3s=assessment.current_discharge,
        low_flow_threshold_m3s=assessment.low_flow_threshold,
        is_low_flow=assessment.is_low_flow,
        primary_stressor=assessment.primary_stressor,
        advisory_message=assessment.advisory_message,
        outlook_trend=outlook.outlook_trend,
        projected_deficit_pct=outlook.projected_deficit_pct,
        forecast_low_flow_days_7d=outlook.forecast_low_flow_days_7d,
        outlook_summary=outlook.summary,
    )
    return jsonify(resp.model_dump())
