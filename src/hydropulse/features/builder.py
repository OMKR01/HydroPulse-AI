"""Dataset builder for HydroPulse AI feature pipeline.

Extracts observations from SQLite, executes cleaning, lag derivation, SPI computation,
static attribute joining, and exports per-station Parquet datasets to data/processed/.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from config.settings import DATA_DIR, load_stations_config
from src.hydropulse.features.cleaning import detect_outliers, fill_small_gaps
from src.hydropulse.features.lags import extract_all_features
from src.hydropulse.features.spi import compute_spi
from src.hydropulse.features.static_attrs import add_static_attributes
from src.hydropulse.ingest.storage import db_cursor

logger = logging.getLogger(__name__)


def load_station_raw_dataframe(
    station_id: str,
    db_target: str | Path | None = None,
) -> pd.DataFrame:
    """Load merged weather and discharge records for a station from SQLite database."""
    with db_cursor(db_target) as cursor:
        cursor.execute(
            """
            SELECT
                COALESCE(w.date, q.date) AS date,
                w.station_id,
                w.precipitation_mm,
                w.temperature_max_c,
                w.temperature_min_c,
                w.relative_humidity_mean,
                q.discharge_m3s,
                q.discharge_mean_m3s,
                q.discharge_p25_m3s,
                q.discharge_p75_m3s,
                COALESCE(q.provenance, w.provenance, 'model_reanalysis') AS provenance
            FROM weather_records w
            LEFT JOIN discharge_records q
                ON w.station_id = q.station_id AND w.date = q.date
            WHERE w.station_id = ?
            UNION
            SELECT
                q.date,
                q.station_id,
                w.precipitation_mm,
                w.temperature_max_c,
                w.temperature_min_c,
                w.relative_humidity_mean,
                q.discharge_m3s,
                q.discharge_mean_m3s,
                q.discharge_p25_m3s,
                q.discharge_p75_m3s,
                q.provenance
            FROM discharge_records q
            LEFT JOIN weather_records w
                ON q.station_id = w.station_id AND q.date = w.date
            WHERE q.station_id = ? AND w.date IS NULL
            ORDER BY date ASC
            """,
            (station_id, station_id),
        )
        rows = cursor.fetchall()
        if not rows:
            return pd.DataFrame()

        records = [dict(r) for r in rows]
        df = pd.DataFrame(records)
        df["station_id"] = station_id
        return df


def build_station_features(
    station_id: str,
    db_target: str | Path | None = None,
    upstream_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build full leak-free feature dataframe for a single station."""
    raw_df = load_station_raw_dataframe(station_id, db_target=db_target)
    if raw_df.empty:
        logger.warning("No records found for station %s", station_id)
        return pd.DataFrame()

    # 1. Cleaning & small gap filling
    df_clean = fill_small_gaps(raw_df, max_gap_days=3)
    df_clean = detect_outliers(df_clean)

    # 2. Past lag features and calendar features
    df_feats = extract_all_features(df_clean, df_upstream=upstream_df)

    # 3. SPI drought indices (SPI-30d, SPI-90d, SPI-180d)
    df_spi = compute_spi(df_feats, windows=(30, 90, 180))

    # 4. Static catchment attributes
    df_static = add_static_attributes(df_spi, station_id=station_id)

    # 5. Multi-horizon targets (t+1 ... t+7 days ahead)
    if "discharge_m3s" in df_static.columns:
        for h in range(1, 8):
            df_static[f"target_discharge_h{h}"] = df_static["discharge_m3s"].shift(-h)

    return df_static


def build_all_processed_datasets(
    output_dir: str | Path | None = None,
    db_target: str | Path | None = None,
) -> dict[str, Any]:
    """Process all configured stations and save Parquet files in data/processed/."""
    out_path = Path(output_dir or (DATA_DIR / "processed"))
    out_path.mkdir(parents=True, exist_ok=True)

    stations = load_stations_config()
    summary: dict[str, Any] = {
        "output_dir": str(out_path),
        "stations_processed": 0,
        "files_saved": [],
    }

    # Station map for upstream lookups
    cached_dfs: dict[str, pd.DataFrame] = {}

    for stn in stations:
        stn_id = stn["id"]
        up_id = stn.get("upstream_station_id")
        up_df = cached_dfs.get(up_id) if up_id else None

        df_proc = build_station_features(stn_id, db_target=db_target, upstream_df=up_df)
        if not df_proc.empty:
            cached_dfs[stn_id] = df_proc
            file_name = f"{stn_id}.parquet"
            target_file = out_path / file_name
            df_proc.to_parquet(target_file, index=False)
            summary["files_saved"].append(str(target_file))
            summary["stations_processed"] += 1
            logger.info("Saved %d rows for %s -> %s", len(df_proc), stn_id, file_name)

    return summary
