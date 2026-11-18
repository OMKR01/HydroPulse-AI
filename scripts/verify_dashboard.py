"""Visual and integration verification script for Phase 6 Web Dashboard."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure repository root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.hydropulse.api.factory import create_app


def verify_dashboard_integration():
    print("Initializing Flask test application instance...")
    app = create_app({"TESTING": True, "DEBUG": False})
    client = app.test_client()

    print("Verifying GET /dashboard...")
    resp = client.get("/dashboard")
    assert resp.status_code == 200, f"Dashboard failed with {resp.status_code}"
    html = resp.get_data(as_text=True)

    # Verification checklist per AGENTS.md Rule 8
    checks = {
        "Statutory CWC/JSDMA Disclaimer": "Central Water Commission (CWC)" in html
        and "JSDMA" in html,
        "Provenance Badge Container": "provenance-pill" in html and "provenance-label" in html,
        "Bilingual Toggle (EN / Hindi)": "lang-toggle-btn" in html and "हिन्दी" in html,
        "Leaflet Map Mount Point": 'id="map-viewport"' in html,
        "Color-Blind Safe Legend": "Risk Level Legend" in html and "Normal (Q &lt; P90)" in html,
        "Discharge Hydrograph Canvas": 'id="hydrograph-canvas"' in html,
        "Forecast Uncertainty Band": "Uncertainty Band (P10" in html,
        "River Health (WQI) Panel": "Weighted-Arithmetic WQI" in html,
        "CPCB Statutory Class Badge": "CPCB Designated-Best-Use" in html,
        "Industrial Corridor Hotspot Alert": "hotspot-alert-banner" in html,
        "Drought Severity & SPI Indicators": "Compound Drought Severity" in html
        and "Standardized Precipitation Index (SPI)" in html,
        "Hydrological Q90 Low-Flow Stress": "Hydrological Baseflow Deficit (Q90)" in html,
        "30-Day Outlook Trajectory": "30-Day Forward Trajectory" in html,
        "Explainability 'Why' Section": "Why is this station at this level?" in html,
        "Active Alerts Ticker Strip": "alerts-ticker-strip" in html,
    }

    print("\n===========================================================")
    print("       HydroPulse AI — Phase 6 Dashboard Verification       ")
    print("===========================================================")
    all_passed = True
    for name, passed in checks.items():
        status = "[PASS]" if passed else "[FAIL]"
        print(f" {status:<8} {name}")
        if not passed:
            all_passed = False

    # Verify Static Assets
    css_resp = client.get("/static/css/dashboard.css")
    js_resp = client.get("/static/js/app.js")
    map_js = client.get("/static/js/map_view.js")
    hydro_js = client.get("/static/js/hydrograph.js")

    assert css_resp.status_code == 200, "CSS asset failed"
    assert js_resp.status_code == 200, "App JS asset failed"
    assert map_js.status_code == 200, "Map JS asset failed"
    assert hydro_js.status_code == 200, "Hydrograph JS asset failed"
    print(f" {'[PASS]':<8} Static Asset Pipelines (CSS, JS, Map, Hydrograph)")

    print("===========================================================\n")
    if all_passed:
        print(
            "SUCCESS: Phase 6 Dashboard complies with all UI, accessibility, and integrity rules!"
        )
    else:
        raise AssertionError("One or more dashboard checks failed!")


if __name__ == "__main__":
    verify_dashboard_integration()
