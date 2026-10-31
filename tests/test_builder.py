"""Unit tests for HydroPulse AI feature pipeline builder (builder.py)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.hydropulse.features.builder import (
    build_all_processed_datasets,
    build_station_features,
    load_station_raw_dataframe,
)
from src.hydropulse.ingest.storage import (
    init_db,
    upsert_discharge_records,
    upsert_weather_records,
)


@pytest.fixture
def populated_temp_db(tmp_path: Path) -> Path:
    """Create a temporary SQLite DB populated with sample multi-day records."""
    db_file = tmp_path / "test_hydropulse.db"
    init_db(db_file)

    weather_rows = []
    discharge_rows = []

    dates = pd.date_range("2023-01-01", periods=20, freq="D")
    for i, dt in enumerate(dates):
        d_str = dt.strftime("%Y-%m-%d")
        # Station 1: Ramgarh
        weather_rows.append(
            {
                "station_id": "damodar_ramgarh",
                "date": d_str,
                "precipitation_mm": 10.0 + i,
                "temperature_max_c": 30.0,
                "temperature_min_c": 18.0,
                "relative_humidity_mean": 65.0,
                "provenance": "model_reanalysis",
            }
        )
        discharge_rows.append(
            {
                "station_id": "damodar_ramgarh",
                "date": d_str,
                "discharge_m3s": 25.0 + 2 * i,
                "discharge_mean_m3s": 25.0 + 2 * i,
                "discharge_p25_m3s": 20.0 + 2 * i,
                "discharge_p75_m3s": 30.0 + 2 * i,
                "provenance": "model_reanalysis",
            }
        )
        # Station 2: Bokaro
        weather_rows.append(
            {
                "station_id": "damodar_bokaro",
                "date": d_str,
                "precipitation_mm": 12.0 + i,
                "temperature_max_c": 32.0,
                "temperature_min_c": 20.0,
                "relative_humidity_mean": 70.0,
                "provenance": "model_reanalysis",
            }
        )
        discharge_rows.append(
            {
                "station_id": "damodar_bokaro",
                "date": d_str,
                "discharge_m3s": 50.0 + 3 * i,
                "discharge_mean_m3s": 50.0 + 3 * i,
                "discharge_p25_m3s": 40.0 + 3 * i,
                "discharge_p75_m3s": 60.0 + 3 * i,
                "provenance": "model_reanalysis",
            }
        )

    upsert_weather_records(weather_rows, db_target=db_file)
    upsert_discharge_records(discharge_rows, db_target=db_file)
    return db_file


def test_load_station_raw_dataframe(populated_temp_db: Path):
    """Verify loading raw joined data from SQLite."""
    df = load_station_raw_dataframe("damodar_ramgarh", db_target=populated_temp_db)
    assert not df.empty
    assert len(df) == 20
    assert "precipitation_mm" in df.columns
    assert "discharge_m3s" in df.columns
    assert (df["station_id"] == "damodar_ramgarh").all()


def test_load_station_raw_dataframe_nonexistent(populated_temp_db: Path):
    """Verify loading unknown station returns an empty DataFrame."""
    df = load_station_raw_dataframe("unknown_station_xyz", db_target=populated_temp_db)
    assert df.empty


def test_build_station_features(populated_temp_db: Path):
    """Verify building complete feature set for a station."""
    df_feat = build_station_features("damodar_ramgarh", db_target=populated_temp_db)
    assert not df_feat.empty
    assert len(df_feat) == 20

    # Lags and rollings
    assert "precip_lag_1" in df_feat.columns
    assert "precip_roll_sum_3d" in df_feat.columns
    assert "antecedent_precipitation_index" in df_feat.columns

    # SPI columns
    assert "spi_30d" in df_feat.columns
    assert "spi_30d_category" in df_feat.columns

    # Static attributes
    assert "static_elevation_m" in df_feat.columns
    assert "static_drainage_area_km2" in df_feat.columns

    # Forecast targets (t+1 .. t+7)
    for h in range(1, 8):
        assert f"target_discharge_h{h}" in df_feat.columns


def test_build_station_features_nonexistent(populated_temp_db: Path):
    """Verify build_station_features returns empty DataFrame for unknown station."""
    df_feat = build_station_features("nonexistent_station", db_target=populated_temp_db)
    assert df_feat.empty


def test_build_all_processed_datasets(populated_temp_db: Path, tmp_path: Path):
    """Verify end-to-end dataset builder exports Parquet files."""
    out_dir = tmp_path / "processed_parquet"
    summary = build_all_processed_datasets(output_dir=out_dir, db_target=populated_temp_db)

    assert summary["stations_processed"] >= 2
    assert len(summary["files_saved"]) >= 2
    for file_path in summary["files_saved"]:
        p = Path(file_path)
        assert p.exists()
        assert p.suffix == ".parquet"
        df_read = pd.read_parquet(p)
        assert not df_read.empty
        assert "target_discharge_h1" in df_read.columns
