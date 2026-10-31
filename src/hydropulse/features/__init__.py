"""Feature engineering, cleaning, lag extraction, and SPI computation for HydroPulse AI."""

from src.hydropulse.features.builder import (
    build_all_processed_datasets,
    build_station_features,
    load_station_raw_dataframe,
)
from src.hydropulse.features.cleaning import (
    TrainOnlyScaler,
    detect_gaps,
    detect_outliers,
    fill_small_gaps,
)
from src.hydropulse.features.lags import (
    compute_api,
    compute_cyclical_calendar,
    compute_discharge_lags,
    compute_rainfall_lags,
    compute_rolling_rainfall,
    compute_upstream_features,
    extract_all_features,
)
from src.hydropulse.features.spi import (
    classify_spi,
    compute_spi,
    fit_spi_gamma,
    transform_accumulated_to_spi,
)
from src.hydropulse.features.static_attrs import (
    add_static_attributes,
    get_static_attributes,
)

__all__ = [
    "TrainOnlyScaler",
    "add_static_attributes",
    "build_all_processed_datasets",
    "build_station_features",
    "classify_spi",
    "compute_api",
    "compute_cyclical_calendar",
    "compute_discharge_lags",
    "compute_rainfall_lags",
    "compute_rolling_rainfall",
    "compute_spi",
    "compute_upstream_features",
    "detect_gaps",
    "detect_outliers",
    "extract_all_features",
    "fill_small_gaps",
    "fit_spi_gamma",
    "get_static_attributes",
    "load_station_raw_dataframe",
    "transform_accumulated_to_spi",
]
