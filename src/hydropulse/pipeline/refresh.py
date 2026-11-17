"""Data refresh pipeline and scheduler for HydroPulse AI.

Orchestrates automated updates for weather forecasts, GloFAS river discharge,
and CPCB water quality observations, logging audit provenance and freshness.
"""

from __future__ import annotations

import argparse
import logging
from datetime import UTC, datetime
from typing import Any

import requests

from config.settings import DATA_DIR, load_stations_config
from src.hydropulse.ingest.cpcb_wq import ingest_cpcb_directory
from src.hydropulse.ingest.openmeteo_flood import ingest_station_discharge
from src.hydropulse.ingest.openmeteo_weather import ingest_station_weather
from src.hydropulse.ingest.storage import (
    init_db,
    is_source_stale,
    record_audit,
    upsert_discharge_records,
    upsert_weather_records,
)
from src.hydropulse.ingest.wris_cwc import fetch_cwc_observations

logger = logging.getLogger("hydropulse.pipeline.refresh")


def run_refresh_pipeline(
    station_ids: list[str] | None = None,
    limit_stations: int | None = 5,
    include_history: bool = False,
    history_start_date: str | None = None,
    history_end_date: str | None = None,
    session: requests.Session | None = None,
    db_target: str | Any | None = None,
) -> dict[str, Any]:
    """Execute complete data refresh cycle across monitoring stations.

    Args:
        station_ids: Optional subset of station identifiers to process.
        limit_stations: Maximum number of stations to process (default 5 for quick refresh).
        include_history: Whether to backfill historical ERA5/GloFAS records.
        history_start_date: Historical start date (YYYY-MM-DD).
        history_end_date: Historical end date (YYYY-MM-DD).
        session: Optional HTTP session for mocked testing or custom connection pools.
        db_target: Optional SQLite database target path.

    Returns:
        Summary dict of ingested records and audit status per source.
    """
    start_time = datetime.now(UTC)
    logger.info("Starting HydroPulse AI refresh pipeline at %s...", start_time.isoformat())

    # Ensure database schema is initialized
    init_db(db_target=db_target)

    all_stations = load_stations_config()
    if station_ids:
        stations = [s for s in all_stations if s["id"] in station_ids]
    elif limit_stations:
        stations = all_stations[:limit_stations]
    else:
        stations = all_stations

    summary: dict[str, Any] = {
        "started_at": start_time.isoformat(),
        "stations_selected": len(stations),
        "weather_records_ingested": 0,
        "discharge_records_ingested": 0,
        "wq_records_ingested": 0,
        "cwc_records_ingested": 0,
        "sources": {},
    }

    # 1. Ingest Water Quality records from raw data directory
    try:
        wq_dir = DATA_DIR / "raw" / "wq"
        wq_count = ingest_cpcb_directory(wq_dir, db_target=db_target)
        summary["wq_records_ingested"] = wq_count
        summary["sources"]["cpcb_wq"] = {
            "status": "success",
            "count": wq_count,
            "stale": is_source_stale("cpcb_wq", db_target=db_target),
        }
    except Exception as exc:
        logger.error("Water quality refresh error: %s", exc)
        record_audit("cpcb_wq", status="failed", error_message=str(exc), db_target=db_target)
        summary["sources"]["cpcb_wq"] = {"status": "failed", "error": str(exc)}

    # 2. Iterate stations for Weather & Discharge Ingestion
    weather_total = 0
    discharge_total = 0
    cwc_total = 0
    weather_errors = 0
    discharge_errors = 0

    for stn in stations:
        stn_id = stn["id"]
        logger.info("Processing station %s (%s)...", stn_id, stn.get("name", ""))

        # Weather
        try:
            w_records = ingest_station_weather(
                stn,
                start_date=history_start_date if include_history else None,
                end_date=history_end_date if include_history else None,
                include_forecast=True,
                session=session,
            )
            for r in w_records:
                r.setdefault("station_id", stn_id)
            w_count = upsert_weather_records(w_records, db_target=db_target)
            weather_total += w_count
            record_audit(
                "openmeteo_weather",
                status="success",
                station_id=stn_id,
                records_ingested=w_count,
                db_target=db_target,
            )
        except Exception as exc:
            weather_errors += 1
            logger.warning("Weather ingestion error for %s: %s", stn_id, exc)
            record_audit(
                "openmeteo_weather",
                status="failed",
                station_id=stn_id,
                error_message=str(exc),
                db_target=db_target,
            )

        # River Discharge (GloFAS)
        try:
            q_records = ingest_station_discharge(
                stn,
                start_date=history_start_date if include_history else None,
                end_date=history_end_date if include_history else None,
                include_forecast=True,
                session=session,
            )
            for r in q_records:
                r.setdefault("station_id", stn_id)
            q_count = upsert_discharge_records(q_records, db_target=db_target)
            discharge_total += q_count
            record_audit(
                "openmeteo_flood",
                status="success",
                station_id=stn_id,
                records_ingested=q_count,
                db_target=db_target,
            )
        except Exception as exc:
            discharge_errors += 1
            logger.warning("Discharge ingestion error for %s: %s", stn_id, exc)
            record_audit(
                "openmeteo_flood",
                status="failed",
                station_id=stn_id,
                error_message=str(exc),
                db_target=db_target,
            )

        # CWC / India-WRIS
        try:
            cwc_records = fetch_cwc_observations(
                station_id=stn_id,
                cwc_code=stn.get("cwc_code"),
                start_date=history_start_date,
                end_date=history_end_date,
            )
            cwc_total += len(cwc_records)
        except Exception as exc:
            logger.debug("CWC adapter skipped for %s: %s", stn_id, exc)

    summary["weather_records_ingested"] = weather_total
    summary["discharge_records_ingested"] = discharge_total
    summary["cwc_records_ingested"] = cwc_total

    summary["sources"]["openmeteo_weather"] = {
        "status": "success" if weather_errors == 0 else "partial",
        "count": weather_total,
        "stale": is_source_stale("openmeteo_weather", db_target=db_target),
    }
    summary["sources"]["openmeteo_flood"] = {
        "status": "success" if discharge_errors == 0 else "partial",
        "count": discharge_total,
        "stale": is_source_stale("openmeteo_flood", db_target=db_target),
    }

    completed_at = datetime.now(UTC)
    summary["completed_at"] = completed_at.isoformat()
    summary["duration_seconds"] = round((completed_at - start_time).total_seconds(), 2)
    logger.info(
        "Refresh completed in %.2f s: Weather=%d, Flood=%d, WQ=%d",
        summary["duration_seconds"],
        weather_total,
        discharge_total,
        summary["wq_records_ingested"],
    )
    return summary


def start_background_scheduler(interval_hours: int = 6):
    """Start an APScheduler background job executing run_refresh_pipeline periodically."""
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        run_refresh_pipeline,
        trigger="interval",
        hours=interval_hours,
        id="hydropulse_refresh_job",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("APScheduler background refresh job registered (every %d hours).", interval_hours)
    return scheduler


def start_blocking_scheduler(interval_hours: int = 6, limit_stations: int | None = 5):
    """Start an APScheduler blocking daemon executing run_refresh_pipeline periodically.

    Designed for containerized scheduler workers (Docker Compose, Kubernetes jobs).
    Executes an initial refresh immediately, then blocks on scheduled intervals.
    """
    import signal

    from apscheduler.schedulers.blocking import BlockingScheduler

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        run_refresh_pipeline,
        trigger="interval",
        hours=interval_hours,
        kwargs={"limit_stations": limit_stations},
        id="hydropulse_refresh_job",
        replace_existing=True,
    )

    def _shutdown(signum, frame):
        logger.info("Received termination signal %s. Shutting down scheduler...", signum)
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGINT, _shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _shutdown)

    logger.info(
        "APScheduler blocking daemon starting (every %d hours, %s stations). Initializing first cycle...",
        interval_hours,
        limit_stations if limit_stations is not None else "all",
    )
    # Run immediate first cycle
    try:
        run_refresh_pipeline(limit_stations=limit_stations)
    except Exception as exc:
        logger.error("Initial refresh cycle encountered an error: %s", exc)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler daemon terminated gracefully.")
    return scheduler


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for data refresh pipeline."""
    parser = argparse.ArgumentParser(description="HydroPulse AI Data Refresh Engine")
    parser.add_argument(
        "--stations",
        type=int,
        default=5,
        help="Number of stations to refresh (default: 5, pass 0 for all)",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="Include historical backfill window",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="History start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="History end date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run continuously as a foreground scheduler daemon (for Docker scheduler service)",
    )
    parser.add_argument(
        "--interval-hours",
        type=int,
        default=6,
        help="Refresh interval in hours when running in daemon mode (default: 6)",
    )

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    limit = None if args.stations <= 0 else args.stations

    if args.daemon:
        logger.info(
            "Entering daemon mode with interval=%d hours, stations=%s",
            args.interval_hours,
            limit,
        )
        start_blocking_scheduler(interval_hours=args.interval_hours, limit_stations=limit)
        return 0

    summary = run_refresh_pipeline(
        limit_stations=limit,
        include_history=args.history,
        history_start_date=args.start_date,
        history_end_date=args.end_date,
    )

    print("\n--- Refresh Pipeline Execution Summary ---")
    print(f"Stations Processed: {summary['stations_selected']}")
    print(f"Weather Records:    {summary['weather_records_ingested']}")
    print(f"Discharge Records:  {summary['discharge_records_ingested']}")
    print(f"WQ Records:         {summary['wq_records_ingested']}")
    print(f"Duration:           {summary['duration_seconds']}s")
    for src, info in summary["sources"].items():
        print(f"  [{src}] status={info['status']} stale={info.get('stale', False)}")

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
