"""Unit tests for Phase 1 Data Ingestion layer.

Tests cover:
- Mocked Open-Meteo Weather API (ERA5 archive + 7-day forecast)
- Mocked Open-Meteo Flood API (GloFAS v4 + forecast)
- River snapping algorithm across fixture grid
- CPCB Water Quality Pydantic schema validation & bounds checking
- Non-blocking WRIS/CWC adapter
- SQLite storage and staleness detection
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from src.hydropulse.ingest.cpcb_wq import (
    CPCBWaterQualityItem,
    ingest_cpcb_directory,
    load_and_validate_cpcb_csv,
)
from src.hydropulse.ingest.openmeteo_flood import (
    fetch_discharge_forecast,
    fetch_discharge_history,
    haversine_distance_km,
    ingest_station_discharge,
    snap_to_river,
)
from src.hydropulse.ingest.openmeteo_weather import (
    fetch_forecast_weather,
    fetch_historical_weather,
    ingest_station_weather,
)
from src.hydropulse.ingest.storage import (
    db_cursor,
    init_db,
    is_source_stale,
    record_audit,
    upsert_discharge_records,
    upsert_weather_records,
    upsert_wq_records,
)
from src.hydropulse.ingest.wris_cwc import fetch_cwc_observations
from src.hydropulse.pipeline.refresh import run_refresh_pipeline


@pytest.fixture
def test_db(tmp_path: Path) -> Path:
    """Create isolated SQLite database for testing."""
    db_file = tmp_path / "test_hydropulse.db"
    init_db(db_file)
    return db_file


# -----------------------------------------------------------------------------
# 1. Weather Ingestion Tests
# -----------------------------------------------------------------------------
def test_fetch_historical_weather_mocked():
    """Verify historical weather parser extracts ERA5 daily metrics with model_reanalysis provenance."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "daily": {
            "time": ["2022-06-01", "2022-06-02"],
            "precipitation_sum": [12.5, 0.0],
            "temperature_2m_max": [34.2, 36.1],
            "temperature_2m_min": [24.0, 25.2],
            "relative_humidity_2m_mean": [65.0, 58.0],
        }
    }
    session = MagicMock()
    session.get.return_value = mock_resp

    records = fetch_historical_weather(
        latitude=23.63,
        longitude=85.52,
        start_date="2022-06-01",
        end_date="2022-06-02",
        session=session,
    )
    assert len(records) == 2
    assert records[0]["date"] == "2022-06-01"
    assert records[0]["precipitation_mm"] == 12.5
    assert records[0]["provenance"] == "model_reanalysis"
    assert records[1]["temperature_max_c"] == 36.1


def test_fetch_forecast_weather_mocked():
    """Verify forward weather forecast parser tags records with forecast provenance."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "daily": {
            "time": ["2026-11-01", "2026-11-02"],
            "precipitation_sum": [5.0, 2.0],
            "temperature_2m_max": [30.0, 29.5],
            "temperature_2m_min": [20.0, 19.5],
            "relative_humidity_2m_mean": [70.0, 72.0],
        }
    }
    session = MagicMock()
    session.get.return_value = mock_resp

    records = fetch_forecast_weather(
        latitude=23.63, longitude=85.52, forecast_days=2, session=session
    )
    assert len(records) == 2
    assert records[0]["provenance"] == "forecast"
    assert records[1]["precipitation_mm"] == 2.0


def test_ingest_station_weather_integration():
    """Verify ingest_station_weather combines history and forecast with station_id."""
    station = {"id": "stn_test", "latitude": 23.63, "longitude": 85.52}
    with (
        patch("src.hydropulse.ingest.openmeteo_weather.fetch_historical_weather") as mock_hist,
        patch("src.hydropulse.ingest.openmeteo_weather.fetch_forecast_weather") as mock_fc,
    ):
        mock_hist.return_value = [{"date": "2022-06-01", "provenance": "model_reanalysis"}]
        mock_fc.return_value = [{"date": "2026-11-01", "provenance": "forecast"}]

        res = ingest_station_weather(station, start_date="2022-06-01", end_date="2022-06-01")
        assert len(res) == 2
        assert all(r["station_id"] == "stn_test" for r in res)


# -----------------------------------------------------------------------------
# 2. Flood & River Snapping Tests
# -----------------------------------------------------------------------------
def test_haversine_distance():
    """Verify great-circle distance computation."""
    dist = haversine_distance_km(23.63, 85.52, 23.78, 85.96)
    assert 45.0 < dist < 55.0


def test_snap_to_river_on_fixture_grid():
    """Verify snap_to_river identifies the grid cell with maximum mean discharge."""
    session = MagicMock()

    def mock_get(url: str, params: dict[str, Any], timeout: int | None = None):
        lat = params["latitude"]
        lon = params["longitude"]
        resp = MagicMock()
        resp.status_code = 200
        # Simulate active river channel at (23.655, 85.545) with high flow
        if abs(lat - 23.655) < 0.001 and abs(lon - 85.545) < 0.001:
            resp.json.return_value = {"daily": {"river_discharge": [250.0, 260.0, 240.0]}}
        else:
            resp.json.return_value = {"daily": {"river_discharge": [5.0, 4.0, 6.0]}}
        return resp

    session.get.side_effect = mock_get

    best_lat, best_lon, shift_km = snap_to_river(
        latitude=23.63,
        longitude=85.52,
        grid_step=0.025,
        grid_size=3,
        session=session,
    )
    assert best_lat == 23.655
    assert best_lon == 85.545
    assert shift_km > 0.5


def test_fetch_discharge_history_and_forecast_mocked():
    """Verify discharge history and forecast parser."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "daily": {
            "time": ["2022-06-01"],
            "river_discharge": [145.8],
            "river_discharge_mean": [140.0],
            "river_discharge_p25": [120.0],
            "river_discharge_p75": [160.0],
        }
    }
    session = MagicMock()
    session.get.return_value = mock_resp

    records = fetch_discharge_history(23.63, 85.52, "2022-06-01", "2022-06-01", session=session)
    assert len(records) == 1
    assert records[0]["discharge_m3s"] == 145.8
    assert records[0]["provenance"] == "model_reanalysis"

    fc_records = fetch_discharge_forecast(23.63, 85.52, forecast_days=1, session=session)
    assert len(fc_records) == 1
    assert fc_records[0]["provenance"] == "forecast"


def test_ingest_station_discharge_with_snap():
    """Verify discharge ingestion executes snapping when flagged."""
    station = {"id": "stn_ramgarh", "latitude": 23.63, "longitude": 85.52, "snap_to_river": True}
    with (
        patch(
            "src.hydropulse.ingest.openmeteo_flood.snap_to_river",
            return_value=(23.655, 85.545, 1.2),
        ),
        patch(
            "src.hydropulse.ingest.openmeteo_flood.fetch_discharge_forecast",
            return_value=[{"date": "2026-11-01", "discharge_m3s": 100.0, "provenance": "forecast"}],
        ),
    ):
        res = ingest_station_discharge(station, include_forecast=True)
        assert len(res) == 1
        assert res[0]["is_snapped"] is True
        assert res[0]["snapped_latitude"] == 23.655


# -----------------------------------------------------------------------------
# 3. CPCB Water Quality Validation Tests
# -----------------------------------------------------------------------------
def test_cpcb_schema_valid_record():
    """Verify valid CPCB observation passes validation."""
    data = {
        "station_id": "damodar_ramgarh",
        "date": "2023-05-15",
        "ph": "7.5",
        "dissolved_oxygen_mg_l": "6.8",
        "bod_mg_l": "2.4",
        "cod_mg_l": "18.0",
        "conductivity_us_cm": "450.0",
        "turbidity_ntu": "5.5",
        "fecal_coliform_mpn_100ml": "500",
        "provenance": "observed",
    }
    item = CPCBWaterQualityItem(**data)
    assert item.ph == 7.5
    assert item.dissolved_oxygen_mg_l == 6.8
    assert item.provenance == "observed"


@pytest.mark.parametrize(
    "invalid_kwargs",
    [
        {"ph": 15.0},  # pH > 14
        {"ph": -0.5},  # pH < 0
        {"dissolved_oxygen_mg_l": -1.0},  # Negative DO
        {"bod_mg_l": -5.0},  # Negative BOD
        {"date": "15-05-2023"},  # Non-ISO date
        {"provenance": "unverified"},  # Disallowed provenance
    ],
)
def test_cpcb_schema_invalid_bounds(invalid_kwargs):
    """Verify out-of-bound parameters raise ValidationError."""
    base = {
        "station_id": "damodar_ramgarh",
        "date": "2023-05-15",
        "ph": 7.0,
        "provenance": "observed",
    }
    base.update(invalid_kwargs)
    with pytest.raises(ValidationError):
        CPCBWaterQualityItem(**base)


def test_load_and_validate_synthetic_sample(tmp_path):
    """Verify loading real or synthetic CSV file from data/raw/wq."""
    csv_file = tmp_path / "test_wq.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["station_id", "date", "ph", "dissolved_oxygen_mg_l", "provenance"])
        writer.writerow(["damodar_ramgarh", "2023-01-15", "7.4", "6.8", "synthetic"])

    records = load_and_validate_cpcb_csv(csv_file)
    assert len(records) == 1
    assert records[0]["ph"] == 7.4
    assert records[0]["provenance"] == "synthetic"


def test_ingest_cpcb_directory(tmp_path, test_db):
    """Verify directory scanner parses CSV files and commits to storage."""
    csv_file = tmp_path / "wq_data.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["station_id", "date", "ph", "dissolved_oxygen_mg_l", "provenance"])
        writer.writerow(["damodar_bokaro", "2023-03-15", "7.1", "6.2", "synthetic"])

    count = ingest_cpcb_directory(tmp_path, db_target=test_db)
    assert count == 1
    with db_cursor(test_db) as cursor:
        cursor.execute("SELECT * FROM water_quality_records WHERE station_id='damodar_bokaro'")
        row = cursor.fetchone()
        assert row is not None
        assert row["ph"] == 7.1


# -----------------------------------------------------------------------------
# 4. WRIS / CWC Adapter Tests
# -----------------------------------------------------------------------------
def test_wris_cwc_unverified_station():
    """Verify unverified station code returns empty list gracefully."""
    res = fetch_cwc_observations(station_id="test_stn", cwc_code=None)
    assert res == []


def test_wris_cwc_missing_hydroswift():
    """Verify adapter logs warning and returns empty list when hydroswift is absent."""
    with patch("src.hydropulse.ingest.wris_cwc.is_hydroswift_available", return_value=False):
        res = fetch_cwc_observations(station_id="test_stn", cwc_code="CWC123")
        assert res == []


# -----------------------------------------------------------------------------
# 5. Storage, Upsert, and Audit Staleness Tests
# -----------------------------------------------------------------------------
def test_storage_upsert_and_audit(test_db):
    """Verify database upsert operations and audit logging."""
    w_records = [
        {
            "station_id": "stn_1",
            "date": "2026-10-30",
            "precipitation_mm": 10.0,
            "provenance": "forecast",
        }
    ]
    upsert_count = upsert_weather_records(w_records, db_target=test_db)
    assert upsert_count == 1

    # Update record
    w_records[0]["precipitation_mm"] = 15.0
    upsert_weather_records(w_records, db_target=test_db)

    with db_cursor(test_db) as cursor:
        cursor.execute("SELECT precipitation_mm FROM weather_records WHERE station_id='stn_1'")
        row = cursor.fetchone()
        assert row is not None
        assert row["precipitation_mm"] == 15.0

    # Discharge upsert
    q_records = [
        {
            "station_id": "stn_1",
            "date": "2026-10-30",
            "discharge_m3s": 42.5,
            "provenance": "forecast",
            "is_snapped": True,
        }
    ]
    q_count = upsert_discharge_records(q_records, db_target=test_db)
    assert q_count == 1

    # WQ upsert
    wq_records = [
        {
            "station_id": "stn_1",
            "date": "2026-10-30",
            "ph": 7.2,
            "provenance": "observed",
        }
    ]
    wq_count = upsert_wq_records(wq_records, db_target=test_db)
    assert wq_count == 1


def test_staleness_detection(test_db):
    """Verify is_source_stale flags sources correctly based on last_success_at."""
    # Never refreshed source is stale
    assert is_source_stale("unregistered_source", db_target=test_db) is True

    # Freshly refreshed source
    record_audit("test_source", status="success", db_target=test_db)
    assert is_source_stale("test_source", max_age_hours=24, db_target=test_db) is False

    # Stale source (older than 24h)
    with db_cursor(test_db) as cursor:
        old_time = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
        cursor.execute(
            "UPDATE ingest_audit SET last_success_at = ? WHERE source_name='test_source'",
            (old_time,),
        )

    assert is_source_stale("test_source", max_age_hours=24, db_target=test_db) is True


# -----------------------------------------------------------------------------
# 6. Pipeline Refresh Integration Test
# -----------------------------------------------------------------------------
def test_run_refresh_pipeline_mocked(test_db):
    """Verify complete refresh pipeline populates DB with mocked API dependencies."""
    mock_weather = [{"date": "2026-11-01", "precipitation_mm": 5.0, "provenance": "forecast"}]
    mock_flood = [{"date": "2026-11-01", "discharge_m3s": 50.0, "provenance": "forecast"}]

    with (
        patch("src.hydropulse.pipeline.refresh.ingest_station_weather", return_value=mock_weather),
        patch("src.hydropulse.pipeline.refresh.ingest_station_discharge", return_value=mock_flood),
        patch("src.hydropulse.pipeline.refresh.ingest_cpcb_directory", return_value=6),
    ):
        summary = run_refresh_pipeline(
            limit_stations=5,
            db_target=test_db,
        )

        assert summary["stations_selected"] == 5
        assert summary["weather_records_ingested"] == 5
        assert summary["discharge_records_ingested"] == 5
        assert summary["wq_records_ingested"] == 6
        assert summary["sources"]["openmeteo_weather"]["status"] == "success"
        assert summary["sources"]["openmeteo_flood"]["status"] == "success"
