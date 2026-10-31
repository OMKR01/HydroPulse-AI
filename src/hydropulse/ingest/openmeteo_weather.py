"""Open-Meteo Weather API ingestion adapter for HydroPulse AI.

Provides historical reanalysis (ERA5 archive) and operational forecasts for precipitation,
temperature, and relative humidity.
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from config.settings import settings

logger = logging.getLogger(__name__)

OPENMETEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
OPENMETEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def get_http_session(retries: int = 3, backoff_factor: float = 0.5) -> requests.Session:
    """Create a configured requests Session with automated exponential backoff retries."""
    session = requests.Session()
    retry_strategy = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def fetch_historical_weather(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
    session: requests.Session | None = None,
    timeout: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch historical daily weather from Open-Meteo ERA5 archive.

    Returned records carry provenance = 'model_reanalysis'.
    """
    http = session or get_http_session()
    req_timeout = timeout or settings.openmeteo_timeout_seconds

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "daily": "precipitation_sum,temperature_2m_max,temperature_2m_min,relative_humidity_2m_mean",
        "timezone": "UTC",
    }

    logger.info(
        "Querying Open-Meteo ERA5 Archive for (%.4f, %.4f) from %s to %s",
        latitude,
        longitude,
        start_date,
        end_date,
    )
    resp = http.get(OPENMETEO_ARCHIVE_URL, params=params, timeout=req_timeout)
    resp.raise_for_status()
    data = resp.json()

    daily = data.get("daily", {})
    times = daily.get("time", [])
    precip = daily.get("precipitation_sum", [])
    temp_max = daily.get("temperature_2m_max", [])
    temp_min = daily.get("temperature_2m_min", [])
    humidity = daily.get("relative_humidity_2m_mean", [])

    records: list[dict[str, Any]] = []
    for i, date_str in enumerate(times):
        records.append(
            {
                "date": date_str,
                "precipitation_mm": precip[i] if i < len(precip) else None,
                "temperature_max_c": temp_max[i] if i < len(temp_max) else None,
                "temperature_min_c": temp_min[i] if i < len(temp_min) else None,
                "relative_humidity_mean": humidity[i] if i < len(humidity) else None,
                "provenance": "model_reanalysis",
            }
        )
    return records


def fetch_forecast_weather(
    latitude: float,
    longitude: float,
    forecast_days: int = 7,
    session: requests.Session | None = None,
    timeout: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch forward weather forecast from Open-Meteo Forecast API.

    Returned records carry provenance = 'forecast'.
    """
    http = session or get_http_session()
    req_timeout = timeout or settings.openmeteo_timeout_seconds

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "forecast_days": forecast_days,
        "daily": "precipitation_sum,temperature_2m_max,temperature_2m_min,relative_humidity_2m_mean",
        "timezone": "UTC",
    }

    logger.info(
        "Querying Open-Meteo Forecast for (%.4f, %.4f), days=%d",
        latitude,
        longitude,
        forecast_days,
    )
    resp = http.get(OPENMETEO_FORECAST_URL, params=params, timeout=req_timeout)
    resp.raise_for_status()
    data = resp.json()

    daily = data.get("daily", {})
    times = daily.get("time", [])
    precip = daily.get("precipitation_sum", [])
    temp_max = daily.get("temperature_2m_max", [])
    temp_min = daily.get("temperature_2m_min", [])
    humidity = daily.get("relative_humidity_2m_mean", [])

    records: list[dict[str, Any]] = []
    for i, date_str in enumerate(times):
        records.append(
            {
                "date": date_str,
                "precipitation_mm": precip[i] if i < len(precip) else None,
                "temperature_max_c": temp_max[i] if i < len(temp_max) else None,
                "temperature_min_c": temp_min[i] if i < len(temp_min) else None,
                "relative_humidity_mean": humidity[i] if i < len(humidity) else None,
                "provenance": "forecast",
            }
        )
    return records


def ingest_station_weather(
    station: dict[str, Any],
    start_date: str | None = None,
    end_date: str | None = None,
    include_forecast: bool = True,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    """Ingest complete weather profile (history + forecast) for a given station dict."""
    station_id = station["id"]
    lat = float(station["latitude"])
    lon = float(station["longitude"])
    results: list[dict[str, Any]] = []

    if start_date and end_date:
        hist_records = fetch_historical_weather(
            latitude=lat,
            longitude=lon,
            start_date=start_date,
            end_date=end_date,
            session=session,
        )
        for r in hist_records:
            r["station_id"] = station_id
        results.extend(hist_records)

    if include_forecast:
        fc_records = fetch_forecast_weather(
            latitude=lat,
            longitude=lon,
            forecast_days=7,
            session=session,
        )
        for r in fc_records:
            r["station_id"] = station_id
        results.extend(fc_records)

    return results
