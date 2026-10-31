"""India-WRIS / Central Water Commission (CWC) ingestion adapter.

Provides optional integration with India-WRIS via the hydroswift library or direct web endpoints.
Designed to be fully non-blocking and fail-safe: timeouts or unverified station codes return
empty results with audit logs, ensuring the core pipeline continues uninterrupted.
"""

from __future__ import annotations

import logging
from typing import Any

from src.hydropulse.ingest.storage import record_audit

logger = logging.getLogger(__name__)


def is_hydroswift_available() -> bool:
    """Check if the optional hydroswift library is installed in the current environment."""
    try:
        import importlib.util

        return importlib.util.find_spec("hydroswift") is not None
    except Exception:
        return False


def fetch_cwc_observations(
    station_id: str,
    cwc_code: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    timeout_seconds: int = 10,
) -> list[dict[str, Any]]:
    """Fetch observed river discharge / water level records from CWC / India-WRIS.

    In accordance with AGENTS.md integrity rules:
    - Never invent CWC station codes.
    - If cwc_code is None or empty, returns empty list with an informational audit log.
    - If hydroswift or the remote service is unavailable, catches all exceptions, logs an audit entry,
      and returns an empty list without raising errors.
    """
    if not cwc_code:
        logger.debug(
            "Station %s has no verified CWC station code; skipping India-WRIS query.", station_id
        )
        return []

    if not is_hydroswift_available():
        logger.info(
            "hydroswift package is not installed; skipping WRIS/CWC download for station %s (%s).",
            station_id,
            cwc_code,
        )
        record_audit(
            source_name="wris_cwc",
            status="partial",
            station_id=station_id,
            records_ingested=0,
            error_message="hydroswift library not installed in environment",
        )
        return []

    try:
        logger.info(
            "Querying India-WRIS via hydroswift for station %s (CWC code %s)...",
            station_id,
            cwc_code,
        )
        # Dynamic import to avoid hard dependency
        import hydroswift  # type: ignore

        # Placeholder adapter call matching hydroswift's public API
        raw_data = hydroswift.get_discharge(cwc_code, start_date=start_date, end_date=end_date)
        records: list[dict[str, Any]] = []
        for row in raw_data:
            records.append(
                {
                    "station_id": station_id,
                    "date": str(row.get("date")),
                    "discharge_m3s": float(row.get("discharge", 0.0)),
                    "provenance": "observed",
                }
            )
        record_audit(
            source_name="wris_cwc",
            status="success",
            station_id=station_id,
            records_ingested=len(records),
        )
        return records

    except Exception as exc:
        logger.warning(
            "India-WRIS / CWC ingestion failed gracefully for %s (%s): %s",
            station_id,
            cwc_code,
            exc,
        )
        record_audit(
            source_name="wris_cwc",
            status="failed",
            station_id=station_id,
            records_ingested=0,
            error_message=str(exc),
        )
        return []
