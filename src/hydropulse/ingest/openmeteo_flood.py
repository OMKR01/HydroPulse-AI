"""Open-Meteo Flood API ingestion adapter and river cell snapping for HydroPulse AI.

Interfaces with the Copernicus GloFAS v4 hydrological model providing gridded river discharge
reanalysis (1984 to mid-2022) and forward forecasts. Includes snap_to_river() grid optimization.
"""

from __future__ import annotations

import logging
import math
from typing import Any

import requests

from config.settings import settings
from src.hydropulse.ingest.openmeteo_weather import get_http_session

logger = logging.getLogger(__name__)

OPENMETEO_FLOOD_URL = "https://flood-api.open-meteo.com/v1/flood"
GLOFAS_REANALYSIS_CUTOFF_DATE = "2022-06-30"


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance between two coordinates in kilometers."""
    radius_earth_km = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return radius_earth_km * c


def snap_to_river(
    latitude: float,
    longitude: float,
    grid_step: float = 0.025,
    grid_size: int = 3,
    session: requests.Session | None = None,
    timeout: int | None = None,
) -> tuple[float, float, float]:
    """Scan a local lat/lon grid around a candidate station and select the cell with highest mean discharge.

    GloFAS cells represent ~5 km resolution. Candidate station coordinates placed on river banks
    or terrestrial cells are snapped to the active river channel.

    Returns:
        tuple[float, float, float]: (snapped_lat, snapped_lon, shift_distance_km)
    """
    http = session or get_http_session()
    req_timeout = timeout or settings.openmeteo_timeout_seconds

    half = grid_size // 2
    offsets = [i * grid_step for i in range(-half, half + 1)]

    candidates: list[tuple[float, float]] = []
    for d_lat in offsets:
        for d_lon in offsets:
            candidates.append((round(latitude + d_lat, 4), round(longitude + d_lon, 4)))

    best_coord = (latitude, longitude)
    max_discharge = -1.0

    logger.info(
        "Snapping station at (%.4f, %.4f) across %d grid cells (step=%.4f°)",
        latitude,
        longitude,
        len(candidates),
        grid_step,
    )

    for c_lat, c_lon in candidates:
        try:
            params = {
                "latitude": c_lat,
                "longitude": c_lon,
                "daily": "river_discharge",
                "forecast_days": 3,
            }
            resp = http.get(OPENMETEO_FLOOD_URL, params=params, timeout=req_timeout)
            if resp.status_code == 200:
                data = resp.json()
                discharges = [
                    d for d in data.get("daily", {}).get("river_discharge", []) if d is not None
                ]
                mean_q = (sum(discharges) / len(discharges)) if discharges else 0.0
                if mean_q > max_discharge:
                    max_discharge = mean_q
                    best_coord = (c_lat, c_lon)
        except Exception as exc:
            logger.warning("Snap check failed at (%.4f, %.4f): %s", c_lat, c_lon, exc)

    shift_km = haversine_distance_km(latitude, longitude, best_coord[0], best_coord[1])
    logger.info(
        "Snapped (%.4f, %.4f) -> (%.4f, %.4f). Shift distance: %.2f km (Max mean discharge: %.2f m³/s)",
        latitude,
        longitude,
        best_coord[0],
        best_coord[1],
        shift_km,
        max_discharge,
    )
    return best_coord[0], best_coord[1], shift_km


def fetch_discharge_history(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    session: requests.Session | None = None,
    timeout: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch daily GloFAS river discharge reanalysis from Open-Meteo Flood API.

    GloFAS reanalysis ends mid-2022 (GLOFAS_REANALYSIS_CUTOFF_DATE). If the requested
    interval extends beyond the cutoff, queries are handled with explicit provenance noting.
    """
    http = session or get_http_session()
    req_timeout = timeout or settings.openmeteo_timeout_seconds

    # Handle GloFAS reanalysis historical cutoff
    if end_date > GLOFAS_REANALYSIS_CUTOFF_DATE:
        logger.warning(
            "Historical GloFAS reanalysis ends around %s. Query end_date %s will be capped or merged with operational runs.",
            GLOFAS_REANALYSIS_CUTOFF_DATE,
            end_date,
        )

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "daily": "river_discharge,river_discharge_mean,river_discharge_p25,river_discharge_p75",
    }

    resp = http.get(OPENMETEO_FLOOD_URL, params=params, timeout=req_timeout)
    resp.raise_for_status()
    data = resp.json()

    daily = data.get("daily", {})
    times = daily.get("time", [])
    q_vals = daily.get("river_discharge", [])
    q_mean = daily.get("river_discharge_mean", [])
    q_p25 = daily.get("river_discharge_p25", [])
    q_p75 = daily.get("river_discharge_p75", [])

    records: list[dict[str, Any]] = []
    for i, date_str in enumerate(times):
        val = q_vals[i] if i < len(q_vals) else None
        if val is not None:
            records.append(
                {
                    "date": date_str,
                    "discharge_m3s": float(val),
                    "discharge_mean_m3s": float(q_mean[i])
                    if i < len(q_mean) and q_mean[i] is not None
                    else None,
                    "discharge_p25_m3s": float(q_p25[i])
                    if i < len(q_p25) and q_p25[i] is not None
                    else None,
                    "discharge_p75_m3s": float(q_p75[i])
                    if i < len(q_p75) and q_p75[i] is not None
                    else None,
                    "provenance": "model_reanalysis",
                }
            )
    return records


def fetch_discharge_forecast(
    latitude: float,
    longitude: float,
    forecast_days: int = 7,
    session: requests.Session | None = None,
    timeout: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch daily GloFAS forward discharge forecasts from Open-Meteo Flood API.

    Returned records carry provenance = 'forecast'.
    """
    http = session or get_http_session()
    req_timeout = timeout or settings.openmeteo_timeout_seconds

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "forecast_days": forecast_days,
        "daily": "river_discharge,river_discharge_mean,river_discharge_p25,river_discharge_p75",
    }

    resp = http.get(OPENMETEO_FLOOD_URL, params=params, timeout=req_timeout)
    resp.raise_for_status()
    data = resp.json()

    daily = data.get("daily", {})
    times = daily.get("time", [])
    q_vals = daily.get("river_discharge", [])
    q_mean = daily.get("river_discharge_mean", [])
    q_p25 = daily.get("river_discharge_p25", [])
    q_p75 = daily.get("river_discharge_p75", [])

    records: list[dict[str, Any]] = []
    for i, date_str in enumerate(times):
        val = q_vals[i] if i < len(q_vals) else None
        if val is not None:
            records.append(
                {
                    "date": date_str,
                    "discharge_m3s": float(val),
                    "discharge_mean_m3s": float(q_mean[i])
                    if i < len(q_mean) and q_mean[i] is not None
                    else None,
                    "discharge_p25_m3s": float(q_p25[i])
                    if i < len(q_p25) and q_p25[i] is not None
                    else None,
                    "discharge_p75_m3s": float(q_p75[i])
                    if i < len(q_p75) and q_p75[i] is not None
                    else None,
                    "provenance": "forecast",
                }
            )
    return records


def ingest_station_discharge(
    station: dict[str, Any],
    start_date: str | None = None,
    end_date: str | None = None,
    include_forecast: bool = True,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    """Ingest GloFAS discharge profile for a station, executing snap_to_river if flagged."""
    station_id = station["id"]
    lat = float(station["latitude"])
    lon = float(station["longitude"])
    is_snapped = False

    if station.get("snap_to_river", False):
        lat, lon, shift_km = snap_to_river(lat, lon, session=session)
        is_snapped = shift_km > 0.001

    results: list[dict[str, Any]] = []

    if start_date and end_date:
        hist = fetch_discharge_history(
            latitude=lat,
            longitude=lon,
            start_date=start_date,
            end_date=end_date,
            session=session,
        )
        for r in hist:
            r["station_id"] = station_id
            r["is_snapped"] = is_snapped
            r["snapped_latitude"] = lat
            r["snapped_longitude"] = lon
        results.extend(hist)

    if include_forecast:
        fc = fetch_discharge_forecast(
            latitude=lat,
            longitude=lon,
            forecast_days=7,
            session=session,
        )
        for r in fc:
            r["station_id"] = station_id
            r["is_snapped"] = is_snapped
            r["snapped_latitude"] = lat
            r["snapped_longitude"] = lon
        results.extend(fc)

    return results
