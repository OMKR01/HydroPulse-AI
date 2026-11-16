"""Unit and contract tests for HydroPulse AI Web Dashboard presentation tier."""

from __future__ import annotations


def test_dashboard_route_success(client):
    """Test that /dashboard returns 200 OK with HTML content."""
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "text/html" in resp.content_type
    html = resp.get_data(as_text=True)

    # Core branding and accessibility elements
    assert "HydroPulse" in html
    assert "Jharkhand River Health" in html
    assert 'role="banner"' in html
    assert 'role="main"' in html
    assert 'role="contentinfo"' in html


def test_dashboard_disclaimer_and_provenance(client):
    """Test that statutory advisory disclaimer and provenance badge are present."""
    resp = client.get("/dashboard")
    html = resp.get_data(as_text=True)

    # Statutory disclaimer per AGENTS.md integrity rule
    assert "Central Water Commission (CWC)" in html
    assert "Jharkhand State Disaster Management Authority (JSDMA)" in html
    assert "STATUTORY ADVISORY" in html

    # Provenance pill
    assert "provenance-pill" in html
    assert "provenance-label" in html


def test_dashboard_bilingual_and_map_elements(client):
    """Test that bilingual toggle and Leaflet map mounts are present."""
    resp = client.get("/dashboard")
    html = resp.get_data(as_text=True)

    # Bilingual controls
    assert "lang-toggle-btn" in html
    assert "EN" in html
    assert "हिन्दी" in html

    # Map viewport and legend
    assert 'id="map-viewport"' in html
    assert "map-legend" in html
    assert "Normal (Q &lt; P90)" in html
    assert "Watch (P90 &le; Q &lt; P95)" in html
    assert "Warning (P95 &le; Q &lt; P99)" in html
    assert "Danger (Q &ge; P99)" in html


def test_dashboard_tabs_and_canvases(client):
    """Test that hydrograph canvas, WQI panels, and drought cards exist in DOM."""
    resp = client.get("/dashboard")
    html = resp.get_data(as_text=True)

    # Hydrograph canvas
    assert 'id="hydrograph-canvas"' in html
    assert "Discharge Hydrograph &amp; 7-Day Forecast Band" in html
    assert "Uncertainty Band (P10–P90)" in html

    # WQI and CPCB elements
    assert "Weighted-Arithmetic WQI" in html
    assert "CPCB Designated-Best-Use" in html
    assert "hotspot-alert-banner" in html

    # Drought and SPI elements
    assert "Compound Drought Severity" in html
    assert "Standardized Precipitation Index (SPI)" in html
    assert "Hydrological Baseflow Deficit (Q90)" in html
    assert "30-Day Forward Trajectory" in html


def test_root_content_negotiation(client):
    """Test that / delivers HTML for browser requests and JSON for API clients."""
    # Browser-style request
    browser_resp = client.get("/", headers={"Accept": "text/html,application/xhtml+xml"})
    assert browser_resp.status_code == 200
    assert "text/html" in browser_resp.content_type
    assert "HydroPulse" in browser_resp.get_data(as_text=True)

    # API client-style request
    api_resp = client.get("/", headers={"Accept": "application/json"})
    assert api_resp.status_code == 200
    assert "application/json" in api_resp.content_type
    json_data = api_resp.get_json()
    assert "HydroPulse AI" in json_data["service"]
    assert json_data["dashboard_url"] == "/dashboard"


def test_static_assets_served(client):
    """Test that static CSS and JS assets are served properly."""
    css_resp = client.get("/static/css/dashboard.css")
    assert css_resp.status_code == 200
    assert "text/css" in css_resp.content_type
    assert "--risk-normal" in css_resp.get_data(as_text=True)

    js_resp = client.get("/static/js/app.js")
    assert js_resp.status_code == 200
    assert "javascript" in js_resp.content_type or "text/plain" in js_resp.content_type
    assert "DashboardApp" in js_resp.get_data(as_text=True)
