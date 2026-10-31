"""Data ingestion modules for Open-Meteo weather, GloFAS discharge, WRIS CWC, and CPCB WQ."""

from src.hydropulse.ingest.cpcb_wq import (
    CPCBWaterQualityItem,
    ingest_cpcb_directory,
    load_and_validate_cpcb_csv,
)
from src.hydropulse.ingest.openmeteo_flood import (
    fetch_discharge_forecast,
    fetch_discharge_history,
    ingest_station_discharge,
    snap_to_river,
)
from src.hydropulse.ingest.openmeteo_weather import (
    fetch_forecast_weather,
    fetch_historical_weather,
    ingest_station_weather,
)
from src.hydropulse.ingest.storage import (
    DischargeRecord,
    IngestAudit,
    WaterQualityRecord,
    WeatherRecord,
    db_cursor,
    get_connection,
    init_db,
    is_source_stale,
    record_audit,
    resolve_db_path,
    upsert_discharge_records,
    upsert_weather_records,
    upsert_wq_records,
)
from src.hydropulse.ingest.wris_cwc import fetch_cwc_observations

__all__ = [
    "CPCBWaterQualityItem",
    "DischargeRecord",
    "IngestAudit",
    "WaterQualityRecord",
    "WeatherRecord",
    "fetch_cwc_observations",
    "fetch_discharge_forecast",
    "fetch_discharge_history",
    "fetch_forecast_weather",
    "fetch_historical_weather",
    "db_cursor",
    "get_connection",
    "ingest_cpcb_directory",
    "ingest_station_discharge",
    "ingest_station_weather",
    "init_db",
    "is_source_stale",
    "load_and_validate_cpcb_csv",
    "record_audit",
    "resolve_db_path",
    "snap_to_river",
    "upsert_discharge_records",
    "upsert_weather_records",
    "upsert_wq_records",
]
