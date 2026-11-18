"""HydroPulse AI — Demonstration Client Script.

Demonstrates the full potential of the HydroPulse AI REST API, querying
multi-horizon discharge forecasts, flood alerts, CPCB water quality,
SPI drought indicators, and ML evaluation benchmarks.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Ensure project root is in sys.path for local module imports
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Base URL of the HydroPulse AI backend (defaults to local Flask development server)
BASE_URL = "http://127.0.0.1:5000"

# Demo API Key / Bearer Token (simulating enterprise client authentication)
DEMO_API_KEY = "hp_demo_jharkhand_sdma_2026_eval"
DEMO_BEARER_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.demo_token_hydropulse"

HEADERS = {
    "User-Agent": "HydroPulse-Client/1.0",
    "Accept": "application/json",
    "X-API-Key": DEMO_API_KEY,
    "Authorization": f"Bearer {DEMO_BEARER_TOKEN}",
}


def fetch_endpoint(path: str, local_client=None) -> dict | None:
    """Fetch JSON from a HydroPulse API endpoint (HTTP or local test client fallback)."""
    if local_client:
        resp = local_client.get(path, headers=HEADERS)
        if resp.status_code == 200:
            return resp.get_json()
        print(f" [!] Error querying {path}: HTTP {resp.status_code}")
        return None

    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url, headers=HEADERS, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data
    except Exception:
        # Fallback to local application factory client if server not listening on socket
        try:
            from src.hydropulse.api.factory import create_app

            app = create_app()
            client = app.test_client()
            resp = client.get(path, headers=HEADERS)
            if resp.status_code == 200:
                return resp.get_json()
        except Exception as inner_err:
            print(f" [!] Connection Error querying {path}: {inner_err}")
        return None


def run_full_potential_demo() -> None:
    """Execute end-to-end telemetry queries across all core modules."""
    print("=" * 78)
    print("  HYDROPULSE AI — SYSTEM DEMONSTRATION & TELEMETRY CLIENT")
    print(f"  Target Server: {BASE_URL}")
    print(f"  Demo Client Auth: {DEMO_API_KEY}")
    print("=" * 78)

    # 1. System Health & Heartbeat
    print("\n[1/6] Querying System Health (/api/v1/health)...")
    health = fetch_endpoint("/api/v1/health")
    if health:
        print(f"  -> Status:        {health.get('status')}")
        print(f"  -> Service:       {health.get('service')} (v{health.get('version')})")
        print(f"  -> Provenance:    {health.get('data_provenance')}")
        print(f"  -> Latency/Check: {health.get('checks')}")

    # 2. Active Flood Risk & Alerts
    print("\n[2/6] Querying Active Basin Alerts (/api/v1/alerts)...")
    alerts = fetch_endpoint("/api/v1/alerts")
    if alerts:
        active = alerts.get("active_alerts", [])
        print(f"  -> Total Stations Monitored: {alerts.get('total_stations', 0)}")
        print(f"  -> Active High-Risk Alerts:   {len(active)}")
        for alert in active[:3]:
            print(
                f"     * [{alert.get('alert_level')}] {alert.get('station_name')} "
                f"({alert.get('river')}) - Peak: {alert.get('peak_discharge_m3s')} m3/s"
            )

    # 3. 7-Day Quantile Flood Forecast (Bokaro Station)
    station_id = "damodar_bokaro"
    print(
        f"\n[3/6] Querying 7-Day Discharge Forecast (/api/v1/stations/{station_id}/forecast?days=7)..."
    )
    forecast = fetch_endpoint(f"/api/v1/stations/{station_id}/forecast?days=7")
    if forecast:
        print(f"  -> Station:    {forecast.get('station_name')} ({forecast.get('basin')} Basin)")
        print(f"  -> Provenance: {forecast.get('data_provenance')}")
        print("  -> Horizon Predictions (m3/s with P10/P50/P90 Uncertainty Intervals):")
        print("     Day | Horizon | Date       | P10 (Low) | P50 (Median) | P90 (Surge) | Alert")
        print("     ----+---------+------------+-----------+--------------+-------------+--------")
        for pt in forecast.get("forecast_points", []):
            d = pt.get("date")
            h = pt.get("horizon_days")
            p10 = pt.get("discharge_p10_m3s", 0)
            p50 = pt.get("discharge_p50_m3s", 0)
            p90 = pt.get("discharge_p90_m3s", 0)
            lvl = pt.get("alert_level")
            print(
                f"     +{h}d | t+{h:<5} | {d} | {p10:8.2f}  | {p50:11.2f}  | {p90:10.2f}  | {lvl}"
            )

    # 4. Water Quality Index (CPCB Standards)
    print(f"\n[4/6] Querying Water Quality Index (/api/v1/water-quality/{station_id})...")
    wq = fetch_endpoint(f"/api/v1/water-quality/{station_id}")
    if wq:
        score = wq.get("wqi") or wq.get("wqi_score") or "N/A"
        status = wq.get("wqi_status") or wq.get("wqi_class") or "Indicative"
        cpcb = wq.get("cpcb_class") or "N/A"
        summary = wq.get("hotspot_summary") or "Normal"
        print(f"  -> WQI Score:   {score} / 100 ({status})")
        print(f"  -> CPCB Class:  Class {cpcb}")
        print(f"  -> Effluent:    Hotspot: {wq.get('is_hotspot', False)} ({summary})")

    # 5. SPI Meteorological Drought Outlook
    print(f"\n[5/6] Querying Drought & Low-Flow Stress (/api/v1/drought/{station_id})...")
    drought = fetch_endpoint(f"/api/v1/drought/{station_id}")
    if drought:
        low_flow = drought.get("is_low_flow", False)
        status = drought.get("low_flow_status") or (
            "Low-Flow Stress" if low_flow else "Normal Flow"
        )
        print(f"  -> Low-Flow Alert:   {low_flow} ({status})")
        print(f"  -> SPI-1 (30 Days):  {drought.get('spi_1', 'N/A')}")
        print(f"  -> SPI-3 (90 Days):  {drought.get('spi_3', 'N/A')}")
        print(f"  -> SPI-6 (180 Days): {drought.get('spi_6', 'N/A')}")

    # 6. ML Model Evaluation Governance
    print("\n[6/6] Querying Model Governance Metrics (/api/v1/model/metrics)...")
    metrics = fetch_endpoint("/api/v1/model/metrics")
    if metrics:
        mdata = metrics.get("metrics_data", {})
        best = mdata.get("current_best", {})
        print(f"  -> Provenance:  {metrics.get('data_provenance')}")
        print(f"  -> Generated:   {metrics.get('generated_at')}")
        if best:
            print("  -> Current Best Hydrologic Models (from reports/metrics.json):")
            for k, v in list(best.items())[:3]:
                print(
                    f"     * {k}: Model={v.get('model')} | NSE={v.get('NSE')} | KGE={v.get('KGE')} | RMSE={v.get('RMSE')}"
                )

    print("\n" + "=" * 78)
    print("  DEMONSTRATION COMPLETED SUCCESSFULLY")
    print("=" * 78)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        BASE_URL = sys.argv[1]
    run_full_potential_demo()
