"""Tests for health endpoint, OpenAPI documentation, and configuration."""

from datetime import datetime

from config.settings import load_stations_config, load_thresholds_config


def test_health_endpoint(client):
    """Test that /api/v1/health returns 200 with required contract keys."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200

    data = response.get_json()
    assert data["status"] == "healthy"
    assert data["service"] == "hydropulse-ai"
    assert "version" in data
    assert "generated_at" in data
    assert data["data_provenance"] in ["observed", "model_reanalysis", "forecast", "synthetic"]
    assert isinstance(data["is_stale"], bool)

    # Validate ISO datetime format
    parsed_dt = datetime.fromisoformat(data["generated_at"])
    assert parsed_dt is not None


def test_root_index_endpoint(client):
    """Test root endpoint provides service info and doc links."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.get_json()
    assert "HydroPulse AI" in data["service"]
    assert data["docs_url"] == "/docs"
    assert data["health_url"] == "/api/v1/health"
    assert "CWC" in data["advisory"]


def test_docs_and_openapi_spec(client):
    """Test that /docs renders HTML and /api/v1/openapi.json returns valid JSON."""
    docs_resp = client.get("/docs")
    assert docs_resp.status_code == 200
    assert b"HydroPulse AI" in docs_resp.data
    assert b"swagger-ui" in docs_resp.data

    spec_resp = client.get("/api/v1/openapi.json")
    assert spec_resp.status_code == 200
    spec = spec_resp.get_json()
    assert spec["openapi"] == "3.0.3"
    assert "/api/v1/health" in spec["paths"]
    assert "/api/v1/stations" in spec["paths"]


def test_error_envelope_404(client):
    """Test that unknown endpoints return standard JSON error envelope."""
    response = client.get("/api/v1/non_existent_route")
    assert response.status_code == 404
    data = response.get_json()
    assert "error" in data
    assert data["error"]["status_code"] == 404
    assert data["error"]["title"] == "Not Found"
    assert "generated_at" in data


def test_error_envelope_405(client):
    """Test that disallowed methods return standard 405 error envelope."""
    response = client.post("/api/v1/health")
    assert response.status_code == 405
    data = response.get_json()
    assert "error" in data
    assert data["error"]["status_code"] == 405
    assert data["error"]["title"] == "Method Not Allowed"
    assert "generated_at" in data


def test_candidate_stations_config():
    """Test that config/stations.yaml loads correctly with strict integrity rules."""
    stations = load_stations_config()
    assert len(stations) >= 8, f"Expected at least 8 stations, found {len(stations)}"

    for s in stations:
        assert "id" in s
        assert "name" in s
        assert "river" in s
        assert s["basin"] in ["Damodar", "Subarnarekha"]
        assert -90 <= s["latitude"] <= 90
        assert -180 <= s["longitude"] <= 180
        # AGENTS.md integrity rule: candidate stations must be verified: false
        assert s["verified"] is False
        assert s["snap_to_river"] is True


def test_thresholds_config():
    """Test that config/thresholds.yaml defines flood and drought thresholds."""
    thresholds = load_thresholds_config()
    assert "flood" in thresholds
    assert "percentiles" in thresholds["flood"]
    p = thresholds["flood"]["percentiles"]
    assert p["watch"] == 0.90
    assert p["warning"] == 0.95
    assert p["danger"] == 0.99

    assert "drought" in thresholds
    assert "low_flow_percentile" in thresholds["drought"]
    assert thresholds["drought"]["low_flow_percentile"] == 0.10
