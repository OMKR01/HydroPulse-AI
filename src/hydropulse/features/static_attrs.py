"""Static catchment physiographic and hydrological attributes per station.

Provides elevation, drainage area, channel slope, stream order, and dominant land cover
to enable entity-aware multi-station machine learning models.
"""

from __future__ import annotations

import pandas as pd

# Approximate physiographic attributes derived from SRTM DEM & Chota Nagpur plateau basins
STATION_STATIC_ATTRIBUTES: dict[str, dict[str, float | int | str]] = {
    "damodar_ramgarh": {
        "elevation_m": 330.0,
        "drainage_area_km2": 3200.0,
        "channel_slope_m_per_km": 1.85,
        "stream_order": 4,
        "dominant_land_cover": "forest_agriculture",
    },
    "konar_gomia": {
        "elevation_m": 240.0,
        "drainage_area_km2": 1100.0,
        "channel_slope_m_per_km": 2.10,
        "stream_order": 3,
        "dominant_land_cover": "forest_reservoir",
    },
    "damodar_bokaro": {
        "elevation_m": 210.0,
        "drainage_area_km2": 5800.0,
        "channel_slope_m_per_km": 1.20,
        "stream_order": 5,
        "dominant_land_cover": "industrial_mining",
    },
    "damodar_dhanbad": {
        "elevation_m": 150.0,
        "drainage_area_km2": 8900.0,
        "channel_slope_m_per_km": 0.95,
        "stream_order": 5,
        "dominant_land_cover": "coalfields_urban",
    },
    "barakar_maithon": {
        "elevation_m": 140.0,
        "drainage_area_km2": 6200.0,
        "channel_slope_m_per_km": 1.15,
        "stream_order": 4,
        "dominant_land_cover": "agriculture_reservoir",
    },
    "subarnarekha_ranchi": {
        "elevation_m": 620.0,
        "drainage_area_km2": 850.0,
        "channel_slope_m_per_km": 2.40,
        "stream_order": 3,
        "dominant_land_cover": "urban_plateau",
    },
    "subarnarekha_chandil": {
        "elevation_m": 190.0,
        "drainage_area_km2": 5200.0,
        "channel_slope_m_per_km": 1.35,
        "stream_order": 4,
        "dominant_land_cover": "reservoir_hills",
    },
    "kharkai_adityapur": {
        "elevation_m": 145.0,
        "drainage_area_km2": 4400.0,
        "channel_slope_m_per_km": 1.50,
        "stream_order": 4,
        "dominant_land_cover": "industrial_agriculture",
    },
    "subarnarekha_jamshedpur": {
        "elevation_m": 135.0,
        "drainage_area_km2": 10500.0,
        "channel_slope_m_per_km": 0.85,
        "stream_order": 5,
        "dominant_land_cover": "heavy_industry_urban",
    },
    "subarnarekha_ghatshila": {
        "elevation_m": 105.0,
        "drainage_area_km2": 14200.0,
        "channel_slope_m_per_km": 0.70,
        "stream_order": 6,
        "dominant_land_cover": "mining_plains",
    },
}

DEFAULT_STATIC_ATTRIBUTES: dict[str, float | int | str] = {
    "elevation_m": 250.0,
    "drainage_area_km2": 3000.0,
    "channel_slope_m_per_km": 1.5,
    "stream_order": 4,
    "dominant_land_cover": "mixed",
}


def get_static_attributes(station_id: str) -> dict[str, float | int | str]:
    """Retrieve static physiographic attributes for a given station id."""
    return STATION_STATIC_ATTRIBUTES.get(station_id, DEFAULT_STATIC_ATTRIBUTES.copy())


def add_static_attributes(df: pd.DataFrame, station_id: str) -> pd.DataFrame:
    """Append static catchment attribute columns to an existing time-series dataframe."""
    df_out = df.copy()
    attrs = get_static_attributes(station_id)
    for k, v in attrs.items():
        df_out[f"static_{k}"] = v
    return df_out
