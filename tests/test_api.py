"""Comprehensive contract, schema, error-handling, and middleware tests for Phase 5 REST API."""

from __future__ import annotations

import pytest

from src.hydropulse.api.middleware import cache, limiter
from src.hydropulse.api.schemas import (
    AlertsResponse,
    DroughtResponse,
    ErrorEnvelope,
    RiskMapResponse,
    StationForecastResponse,
    StationHistoryResponse,
    StationsListResponse,
    WaterQualityResponse,
)


@pytest.fixture(autouse=True)
def reset_cache_and_limiter():
    """Ensure clean cache and rate limiter state before every test."""
    cache.clear()
    limiter.reset()
    limiter.enabled = False  # Keep disabled by default unless explicitly tested
    yield
    cache.clear()
    limiter.reset()
    limiter.enabled = False


# ─────────────────────── 1. Stations Endpoints ───────────────────────────────


def test_get_stations_contract(client):
    """Test /api/v1/stations schema compliance and integrity."""
    resp = client.get("/api/v1/stations")
    assert resp.status_code == 200
    data = resp.get_json()

    # Validate against Pydantic schema
    validated = StationsListResponse(**data)
    assert validated.count >= 8
    assert validated.data_provenance in ("observed", "model_reanalysis", "forecast", "synthetic")
    assert validated.is_stale is False

    # Check station properties
    first = validated.stations[0]
    assert first.id
    assert first.name
    assert first.basin in ("Damodar", "Subarnarekha")
    assert -90.0 <= first.latitude <= 90.0
    assert -180.0 <= first.longitude <= 180.0


def test_get_station_forecast_success(client):
    """Test /api/v1/stations/<id>/forecast returns 7-day quantile projection."""
    resp = client.get("/api/v1/stations/damodar_ramgarh/forecast?days=7")
    assert resp.status_code == 200
    data = resp.get_json()

    validated = StationForecastResponse(**data)
    assert validated.station_id == "damodar_ramgarh"
    assert validated.forecast_days == 7
    assert len(validated.forecast_points) == 7

    for pt in validated.forecast_points:
        assert pt.discharge_p10_m3s <= pt.discharge_p50_m3s <= pt.discharge_p90_m3s
        assert pt.alert_level in ("Normal", "Watch", "Warning", "Danger")
        assert pt.alert_color.startswith("#")


def test_get_station_forecast_custom_days(client):
    """Test query parameter 'days=3' returns exactly 3 horizons."""
    resp = client.get("/api/v1/stations/damodar_bokaro/forecast?days=3")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["forecast_points"]) == 3
    assert data["forecast_days"] == 3


def test_get_station_forecast_invalid_days_param(client):
    """Test that days < 1 or days > 7 returns 400 error envelope."""
    resp = client.get("/api/v1/stations/damodar_ramgarh/forecast?days=14")
    assert resp.status_code == 400
    data = resp.get_json()
    err = ErrorEnvelope(**data)
    assert err.error.status_code == 400
    assert "between 1 and 7" in err.error.detail

    resp_alpha = client.get("/api/v1/stations/damodar_ramgarh/forecast?days=xyz")
    assert resp_alpha.status_code == 400


def test_get_station_forecast_not_found(client):
    """Test that requesting unknown station returns 404 error envelope."""
    resp = client.get("/api/v1/stations/unknown_station_xyz/forecast")
    assert resp.status_code == 404
    data = resp.get_json()
    err = ErrorEnvelope(**data)
    assert err.error.status_code == 404
    assert "not found" in err.error.detail.lower()


def test_get_station_history_success(client):
    """Test /api/v1/stations/<id>/history returns time-series."""
    resp = client.get("/api/v1/stations/damodar_ramgarh/history?days=15")
    assert resp.status_code == 200
    data = resp.get_json()

    validated = StationHistoryResponse(**data)
    assert validated.station_id == "damodar_ramgarh"
    assert validated.days_returned == 15
    assert len(validated.history) == 15
    assert validated.history[0].date


def test_get_station_history_invalid_days(client):
    resp = client.get("/api/v1/stations/damodar_ramgarh/history?days=500")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"]["status_code"] == 400


# ─────────────────────── 2. Risk Map & Alerts Endpoints ───────────────────────


def test_get_risk_map_geojson(client):
    """Test that /api/v1/risk/map produces RFC 7946 compliant GeoJSON."""
    resp = client.get("/api/v1/risk/map")
    assert resp.status_code == 200
    data = resp.get_json()

    validated = RiskMapResponse(**data)
    assert validated.type == "FeatureCollection"
    assert len(validated.features) >= 8

    feat = validated.features[0]
    assert feat.type == "Feature"
    assert feat.geometry.type == "Point"
    assert len(feat.geometry.coordinates) == 2
    # Coordinates: [lon, lat]
    lon, lat = feat.geometry.coordinates
    assert 84.0 <= lon <= 88.0
    assert 22.0 <= lat <= 25.0

    props = feat.properties
    assert props.alert_level in ("Normal", "Watch", "Warning", "Danger")
    assert props.alert_color.startswith("#")
    assert props.alert_message_en
    assert props.alert_message_hi


def test_get_alerts_bilingual_and_explainability(client):
    """Test /api/v1/alerts bilingual advisories and explainability reasons."""
    resp = client.get("/api/v1/alerts")
    assert resp.status_code == 200
    data = resp.get_json()

    validated = AlertsResponse(**data)
    assert validated.data_provenance in ("forecast", "model_reanalysis", "observed")

    for item in validated.alerts:
        assert item.alert_level in ("Watch", "Warning", "Danger")
        assert len(item.message_en) > 10
        assert len(item.message_hi) > 10
        # Check reasons list
        assert isinstance(item.reasons, list)
        assert len(item.reasons) >= 1


# ─────────────────────── 3. River Health Endpoints ────────────────────────────


def test_get_water_quality_success(client):
    """Test /api/v1/water-quality/<station_id> returns WQI and CPCB class."""
    resp = client.get("/api/v1/water-quality/damodar_ramgarh")
    assert resp.status_code == 200
    data = resp.get_json()

    validated = WaterQualityResponse(**data)
    assert validated.station_id == "damodar_ramgarh"
    assert validated.wqi >= 0.0
    assert validated.rating in ("Excellent", "Good", "Poor", "Very Poor", "Unfit")
    assert validated.cpcb_class in ("A", "B", "C", "D", "E", "Below_E")
    assert isinstance(validated.sub_indices, dict)
    assert isinstance(validated.weights_used, dict)
    assert validated.status_label in ("indicative", "verified")


def test_get_water_quality_industrial_hotspot(client):
    """Test hotspot detection response for industrial mining station."""
    resp = client.get("/api/v1/water-quality/damodar_bokaro")
    assert resp.status_code == 200
    data = resp.get_json()
    validated = WaterQualityResponse(**data)
    assert validated.hotspot_severity in ("None", "Moderate", "Critical")
    assert (
        "indicative" in validated.hotspot_summary.lower()
        or "verified" in validated.hotspot_summary.lower()
    )


def test_get_water_quality_not_found(client):
    resp = client.get("/api/v1/water-quality/non_existent_station")
    assert resp.status_code == 404


def test_get_drought_status_success(client):
    """Test /api/v1/drought/<station_id> returns SPI and 30-day outlook."""
    resp = client.get("/api/v1/drought/damodar_ramgarh")
    assert resp.status_code == 200
    data = resp.get_json()

    validated = DroughtResponse(**data)
    assert validated.station_id == "damodar_ramgarh"
    assert validated.severity in ("Normal", "Watch", "Moderate", "Severe", "Extreme")
    assert 0.0 <= validated.composite_score <= 1.0
    assert validated.low_flow_threshold_m3s >= 0.0
    assert isinstance(validated.is_low_flow, bool)
    assert validated.outlook_trend in (
        "Improving",
        "Persistent Low Flow",
        "Deteriorating",
        "Normal",
    )
    assert -100.0 <= validated.projected_deficit_pct <= 100.0
    assert 0 <= validated.forecast_low_flow_days_7d <= 7


def test_get_drought_status_not_found(client):
    resp = client.get("/api/v1/drought/non_existent_station")
    assert resp.status_code == 404


# ─────────────────────── 4. Governance & Metrics ─────────────────────────────


def test_get_model_metrics(client):
    """Test /api/v1/model/metrics returns metrics logged in reports/metrics.json."""
    resp = client.get("/api/v1/model/metrics")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["system"] == "HydroPulse AI"
    assert "metrics_data" in data
    assert "generated_at" in data


# ─────────────────────── 5. Middleware, Cache, & Rate Limit ───────────────────


def test_request_id_and_timing_headers(client):
    """Test that responses include X-Request-ID and X-Response-Time-Ms headers."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert "X-Request-ID" in resp.headers
    assert "X-Response-Time-Ms" in resp.headers


def test_custom_request_id_propagation(client):
    """Test client-supplied X-Request-ID is echoed back."""
    custom_id = "test-trace-id-12345"
    resp = client.get("/api/v1/health", headers={"X-Request-ID": custom_id})
    assert resp.status_code == 200
    assert resp.headers["X-Request-ID"] == custom_id


def test_ttl_response_caching(client):
    """Test that subsequent identical GET requests hit the cache."""
    # First request: MISS
    resp1 = client.get("/api/v1/stations")
    assert resp1.status_code == 200
    assert resp1.headers.get("X-Cache") == "MISS"

    # Second request: HIT
    resp2 = client.get("/api/v1/stations")
    assert resp2.status_code == 200
    assert resp2.headers.get("X-Cache") == "HIT"
    assert resp1.get_json() == resp2.get_json()


def test_rate_limiter_enforcement(client):
    """Test that rate limiter returns 429 when threshold exceeded."""
    limiter.enabled = True
    limiter.max_requests = 3
    limiter.window_seconds = 60

    # 3 allowed requests
    for _ in range(3):
        r = client.get("/api/v1/stations")
        assert r.status_code == 200

    # 4th request must be rate limited
    r_blocked = client.get("/api/v1/stations")
    assert r_blocked.status_code == 429
    data = r_blocked.get_json()
    assert data["error"]["status_code"] == 429
    assert "Retry-After" in r_blocked.headers
