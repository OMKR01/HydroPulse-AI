"""Database storage, schemas, and audit ledger for HydroPulse AI using SQLite.

Maintains tables for weather_records, discharge_records, water_quality_records,
and ingest_audit with strict provenance tagging on every record.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from config.settings import DATA_DIR, settings


@dataclass
class WeatherRecord:
    """Daily meteorological observations and forecasts."""

    station_id: str
    date: str
    precipitation_mm: float | None = None
    temperature_max_c: float | None = None
    temperature_min_c: float | None = None
    relative_humidity_mean: float | None = None
    provenance: str = "model_reanalysis"
    ingested_at: str = ""
    id: int | None = None


@dataclass
class DischargeRecord:
    """Daily river discharge observations, GloFAS reanalysis, and forecasts."""

    station_id: str
    date: str
    discharge_m3s: float = 0.0
    discharge_mean_m3s: float | None = None
    discharge_p25_m3s: float | None = None
    discharge_p75_m3s: float | None = None
    provenance: str = "model_reanalysis"
    is_snapped: bool = False
    snapped_latitude: float | None = None
    snapped_longitude: float | None = None
    ingested_at: str = ""
    id: int | None = None


@dataclass
class WaterQualityRecord:
    """Monthly river water quality measurements (CPCB/JSPCB NWMP standard)."""

    station_id: str
    date: str
    ph: float | None = None
    dissolved_oxygen_mg_l: float | None = None
    bod_mg_l: float | None = None
    cod_mg_l: float | None = None
    conductivity_us_cm: float | None = None
    turbidity_ntu: float | None = None
    fecal_coliform_mpn_100ml: float | None = None
    wqi: float | None = None
    cpcb_class: str | None = None
    provenance: str = "observed"
    ingested_at: str = ""
    id: int | None = None


@dataclass
class IngestAudit:
    """Audit ledger tracking pipeline refresh execution and source health."""

    source_name: str
    status: str
    station_id: str | None = None
    records_ingested: int = 0
    error_message: str | None = None
    last_success_at: str | None = None
    created_at: str = ""
    id: int | None = None


def resolve_db_path(target: str | Path | None = None) -> str:
    """Resolve database URL or path to an active SQLite connection string."""
    if target is None:
        raw = settings.database_url
    elif isinstance(target, Path):
        raw = str(target)
    else:
        raw = str(target)

    if raw == ":memory:" or raw.startswith("sqlite:///:memory:"):
        return ":memory:"

    if raw.startswith("sqlite:///"):
        clean_path = raw.replace("sqlite:///", "")
    else:
        clean_path = raw

    path_obj = Path(clean_path)
    if not path_obj.is_absolute():
        path_obj = DATA_DIR / "interim" / path_obj.name

    path_obj.parent.mkdir(parents=True, exist_ok=True)
    return str(path_obj)


def get_connection(db_target: str | Path | None = None) -> sqlite3.Connection:
    """Return a configured sqlite3 connection with Row factory."""
    resolved = resolve_db_path(db_target)
    conn = sqlite3.connect(resolved)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_cursor(db_target: str | Path | None = None) -> Generator[sqlite3.Cursor, None, None]:
    """Yield a sqlite3 cursor with automated commit and safe connection closing."""
    conn = get_connection(db_target)
    try:
        with conn:
            yield conn.cursor()
    finally:
        conn.close()


def init_db(db_target: str | Path | None = None) -> None:
    """Create all required schema tables and indexes."""
    with db_cursor(db_target) as cursor:
        # 1. Weather Records
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS weather_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                station_id TEXT NOT NULL,
                date TEXT NOT NULL,
                precipitation_mm REAL,
                temperature_max_c REAL,
                temperature_min_c REAL,
                relative_humidity_mean REAL,
                provenance TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                UNIQUE(station_id, date)
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_weather_station_date ON weather_records(station_id, date)"
        )

        # 2. Discharge Records
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS discharge_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                station_id TEXT NOT NULL,
                date TEXT NOT NULL,
                discharge_m3s REAL NOT NULL,
                discharge_mean_m3s REAL,
                discharge_p25_m3s REAL,
                discharge_p75_m3s REAL,
                provenance TEXT NOT NULL,
                is_snapped INTEGER DEFAULT 0,
                snapped_latitude REAL,
                snapped_longitude REAL,
                ingested_at TEXT NOT NULL,
                UNIQUE(station_id, date)
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_discharge_station_date ON discharge_records(station_id, date)"
        )

        # 3. Water Quality Records
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS water_quality_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                station_id TEXT NOT NULL,
                date TEXT NOT NULL,
                ph REAL,
                dissolved_oxygen_mg_l REAL,
                bod_mg_l REAL,
                cod_mg_l REAL,
                conductivity_us_cm REAL,
                turbidity_ntu REAL,
                fecal_coliform_mpn_100ml REAL,
                wqi REAL,
                cpcb_class TEXT,
                provenance TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                UNIQUE(station_id, date)
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_wq_station_date ON water_quality_records(station_id, date)"
        )

        # 4. Ingest Audit
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ingest_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_name TEXT NOT NULL,
                station_id TEXT,
                records_ingested INTEGER DEFAULT 0,
                status TEXT NOT NULL,
                error_message TEXT,
                last_success_at TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_source ON ingest_audit(source_name)")


def record_audit(
    source_name: str,
    status: str,
    station_id: str | None = None,
    records_ingested: int = 0,
    error_message: str | None = None,
    db_target: str | Path | None = None,
) -> IngestAudit:
    """Log an audit entry and track last_success_at for data freshness."""
    init_db(db_target)
    now_iso = datetime.now(UTC).isoformat()
    last_success_iso: str | None = now_iso if status == "success" else None

    with db_cursor(db_target) as cursor:
        if status != "success":
            cursor.execute(
                """
                SELECT last_success_at FROM ingest_audit
                WHERE source_name = ? AND last_success_at IS NOT NULL
                ORDER BY id DESC LIMIT 1
                """,
                (source_name,),
            )
            row = cursor.fetchone()
            if row:
                last_success_iso = row["last_success_at"]

        cursor.execute(
            """
            INSERT INTO ingest_audit
                (source_name, station_id, records_ingested, status, error_message, last_success_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_name,
                station_id,
                records_ingested,
                status,
                error_message,
                last_success_iso,
                now_iso,
            ),
        )
        audit_id = cursor.lastrowid

        return IngestAudit(
            id=audit_id,
            source_name=source_name,
            status=status,
            station_id=station_id,
            records_ingested=records_ingested,
            error_message=error_message,
            last_success_at=last_success_iso,
            created_at=now_iso,
        )


def is_source_stale(
    source_name: str,
    max_age_hours: int = 24,
    db_target: str | Path | None = None,
) -> bool:
    """Check if a data source has not refreshed successfully within max_age_hours."""
    init_db(db_target)
    with db_cursor(db_target) as cursor:
        cursor.execute(
            """
            SELECT last_success_at FROM ingest_audit
            WHERE source_name = ? AND last_success_at IS NOT NULL
            ORDER BY id DESC LIMIT 1
            """,
            (source_name,),
        )
        row = cursor.fetchone()
        if not row or not row["last_success_at"]:
            return True

        last_str = row["last_success_at"]
        try:
            if last_str.endswith("Z"):
                last_str = last_str.replace("Z", "+00:00")
            last_success = datetime.fromisoformat(last_str)
            if last_success.tzinfo is None:
                last_success = last_success.replace(tzinfo=UTC)
        except Exception:
            return True

        cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
        return last_success < cutoff


def upsert_weather_records(
    records: list[dict[str, Any]], db_target: str | Path | None = None
) -> int:
    """Insert or update weather records into database."""
    if not records:
        return 0

    init_db(db_target)
    now_iso = datetime.now(UTC).isoformat()
    with db_cursor(db_target) as cursor:
        count = 0
        for item in records:
            cursor.execute(
                """
                INSERT INTO weather_records (
                    station_id, date, precipitation_mm, temperature_max_c,
                    temperature_min_c, relative_humidity_mean, provenance, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(station_id, date) DO UPDATE SET
                    precipitation_mm=excluded.precipitation_mm,
                    temperature_max_c=excluded.temperature_max_c,
                    temperature_min_c=excluded.temperature_min_c,
                    relative_humidity_mean=excluded.relative_humidity_mean,
                    provenance=excluded.provenance,
                    ingested_at=excluded.ingested_at
                """,
                (
                    item["station_id"],
                    item["date"],
                    item.get("precipitation_mm"),
                    item.get("temperature_max_c"),
                    item.get("temperature_min_c"),
                    item.get("relative_humidity_mean"),
                    item.get("provenance", "model_reanalysis"),
                    now_iso,
                ),
            )
            count += 1
        return count


def upsert_discharge_records(
    records: list[dict[str, Any]], db_target: str | Path | None = None
) -> int:
    """Insert or update river discharge records into database."""
    if not records:
        return 0

    init_db(db_target)
    now_iso = datetime.now(UTC).isoformat()
    with db_cursor(db_target) as cursor:
        count = 0
        for item in records:
            cursor.execute(
                """
                INSERT INTO discharge_records (
                    station_id, date, discharge_m3s, discharge_mean_m3s,
                    discharge_p25_m3s, discharge_p75_m3s, provenance,
                    is_snapped, snapped_latitude, snapped_longitude, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(station_id, date) DO UPDATE SET
                    discharge_m3s=excluded.discharge_m3s,
                    discharge_mean_m3s=excluded.discharge_mean_m3s,
                    discharge_p25_m3s=excluded.discharge_p25_m3s,
                    discharge_p75_m3s=excluded.discharge_p75_m3s,
                    provenance=excluded.provenance,
                    is_snapped=excluded.is_snapped,
                    snapped_latitude=excluded.snapped_latitude,
                    snapped_longitude=excluded.snapped_longitude,
                    ingested_at=excluded.ingested_at
                """,
                (
                    item["station_id"],
                    item["date"],
                    float(item["discharge_m3s"]),
                    item.get("discharge_mean_m3s"),
                    item.get("discharge_p25_m3s"),
                    item.get("discharge_p75_m3s"),
                    item.get("provenance", "model_reanalysis"),
                    1 if item.get("is_snapped") else 0,
                    item.get("snapped_latitude"),
                    item.get("snapped_longitude"),
                    now_iso,
                ),
            )
            count += 1
        return count


def upsert_wq_records(records: list[dict[str, Any]], db_target: str | Path | None = None) -> int:
    """Insert or update water quality records into database."""
    if not records:
        return 0

    init_db(db_target)
    now_iso = datetime.now(UTC).isoformat()
    with db_cursor(db_target) as cursor:
        count = 0
        for item in records:
            cursor.execute(
                """
                INSERT INTO water_quality_records (
                    station_id, date, ph, dissolved_oxygen_mg_l, bod_mg_l, cod_mg_l,
                    conductivity_us_cm, turbidity_ntu, fecal_coliform_mpn_100ml,
                    wqi, cpcb_class, provenance, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(station_id, date) DO UPDATE SET
                    ph=excluded.ph,
                    dissolved_oxygen_mg_l=excluded.dissolved_oxygen_mg_l,
                    bod_mg_l=excluded.bod_mg_l,
                    cod_mg_l=excluded.cod_mg_l,
                    conductivity_us_cm=excluded.conductivity_us_cm,
                    turbidity_ntu=excluded.turbidity_ntu,
                    fecal_coliform_mpn_100ml=excluded.fecal_coliform_mpn_100ml,
                    wqi=excluded.wqi,
                    cpcb_class=excluded.cpcb_class,
                    provenance=excluded.provenance,
                    ingested_at=excluded.ingested_at
                """,
                (
                    item["station_id"],
                    item["date"],
                    item.get("ph"),
                    item.get("dissolved_oxygen_mg_l"),
                    item.get("bod_mg_l"),
                    item.get("cod_mg_l"),
                    item.get("conductivity_us_cm"),
                    item.get("turbidity_ntu"),
                    item.get("fecal_coliform_mpn_100ml"),
                    item.get("wqi"),
                    item.get("cpcb_class"),
                    item.get("provenance", "observed"),
                    now_iso,
                ),
            )
            count += 1
        return count
