"""Unit tests for Vercel serverless integration and path correction middleware."""

from __future__ import annotations

import sys

import pytest
from flask import Flask

from api.index import VercelPathCorrectionMiddleware, app


class TestVercelIntegration:
    """Test suite verifying Vercel serverless configuration and routing middleware."""

    @pytest.fixture
    def client(self):
        """Create a test client from the Vercel-wrapped Flask application."""
        app.config["TESTING"] = True
        return app.test_client()

    def test_app_is_flask_instance(self):
        """Verify that the exported app is a valid Flask instance with middleware applied."""
        assert isinstance(app, Flask)
        assert isinstance(app.wsgi_app, VercelPathCorrectionMiddleware)

    def test_direct_request_without_forwarded_headers(self, client):
        """Direct requests without proxy headers should route to normal endpoints."""
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "healthy"
        assert data["service"] == "hydropulse-ai"

    def test_root_fallback_when_path_is_api_index(self, client):
        """When rewritten to /api/index with no forwarded path, it should route to /."""
        response = client.get("/api/index")
        assert response.status_code == 200
        data = response.get_json()
        assert data["service"] == "HydroPulse AI"

    def test_vercel_rewrite_path_parameter_dashboard(self, client):
        """Verify Vercel rewrite destination /api/index?__path=dashboard renders dashboard."""
        response = client.get("/api/index?__path=dashboard")
        assert response.status_code == 200
        content = response.data.decode("utf-8")
        assert "HydroPulse" in content
        assert "dashboard" in content.lower()

    def test_vercel_rewrite_path_parameter_static_css(self, client):
        """Verify Vercel rewrite /api/index?__path=static/css/dashboard.css serves CSS."""
        response = client.get("/api/index?__path=static/css/dashboard.css")
        assert response.status_code == 200
        assert "text/css" in response.headers.get("Content-Type", "")
        content = response.data.decode("utf-8")
        assert "INVERSA" in content or "dashboard" in content or len(content) > 1000

    def test_vercel_rewrite_path_parameter_with_query(self, client):
        """Verify Vercel rewrite with additional query parameters strips __path cleanly."""
        response = client.get("/api/index?days=3&__path=api/v1/stations/damodar_ramgarh/forecast")
        assert response.status_code == 200
        data = response.get_json()
        assert data["station_id"] == "damodar_ramgarh"
        assert data["forecast_days"] == 3

    def test_vercel_forwarded_path_header(self, client):
        """Simulate Vercel rewriting /(.*) to /api/index with X-Vercel-Forwarded-Path."""
        response = client.get(
            "/api/index",
            headers={"X-Vercel-Forwarded-Path": "/api/v1/health"},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "healthy"

    def test_vercel_forwarded_path_dashboard_html(self, client):
        """Verify /dashboard HTML page renders cleanly through Vercel rewrite."""
        response = client.get(
            "/api/index",
            headers={"X-Vercel-Forwarded-Path": "/dashboard"},
        )
        assert response.status_code == 200
        content = response.data.decode("utf-8")
        assert "HydroPulse" in content
        assert "dashboard" in content.lower()

    def test_vercel_forwarded_path_stations(self, client):
        """Verify /api/v1/stations endpoint responds with registry via Vercel rewrite."""
        response = client.get(
            "/api/index",
            headers={"X-Vercel-Forwarded-Path": "/api/v1/stations"},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert "stations" in data
        assert len(data["stations"]) > 0

    def test_vercel_forwarded_path_with_query_string(self, client):
        """Ensure forwarded path with embedded query string gets normalized cleanly."""
        response = client.get(
            "/api/index?days=3",
            headers={"X-Vercel-Forwarded-Path": "/api/v1/stations/damodar_ramgarh/forecast?days=3"},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["station_id"] == "damodar_ramgarh"
        assert data["forecast_days"] == 3

    def test_vercel_static_file_serving(self, client):
        """Verify static CSS stylesheet can be served through Vercel rewrite."""
        response = client.get(
            "/api/index",
            headers={"X-Vercel-Forwarded-Path": "/static/css/dashboard.css"},
        )
        assert response.status_code == 200
        assert "text/css" in response.headers.get("Content-Type", "")
        assert len(response.data) > 0

    def test_vercel_404_routing(self, client):
        """Non-existent paths through Vercel rewrite should return standard 404 JSON."""
        response = client.get(
            "/api/index",
            headers={"X-Vercel-Forwarded-Path": "/api/v1/non_existent_route"},
        )
        assert response.status_code == 404
        data = response.get_json()
        assert "error" in data
        assert data["error"]["status_code"] == 404

    def test_models_import_gracefully_when_torch_is_missing(self, monkeypatch):
        """Ensure models package imports cleanly without torch installed (Vercel runtime)."""

        class BlockTorch:
            def find_spec(self, fullname, path, target=None):
                if fullname.startswith("torch"):
                    raise ModuleNotFoundError(f"No module named {fullname}")
                return None

        # Temporarily prepend import hook
        sys.meta_path.insert(0, BlockTorch())
        try:
            from src.hydropulse.models.lstm import PerStationLSTM

            assert isinstance(PerStationLSTM.name, str)
        finally:
            sys.meta_path.pop(0)
