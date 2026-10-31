# Data Card — HydroPulse AI

## 1. Overview & Provenance Taxonomy
Every record stored, processed, and served by HydroPulse AI carries an explicit `provenance` attribute adhering strictly to the AGENTS.md integrity rules:
- `observed`: Gauge measurements recorded physically on the ground by CWC, India-WRIS, or CPCB/JSPCB NWMP monitoring stations.
- `model_reanalysis`: Gridded historic reanalysis from GloFAS v4 or ERA5 land reanalysis.
- `forecast`: Operational meteorological or hydrological forward models (e.g., Open-Meteo 7-day weather/flood forecasts).
- `synthetic`: Artificially generated fixtures strictly reserved for unit tests and local mock fallbacks (always flagged with visible badges; never substituted into live workflows).

---

## 2. Ingested Data Sources & Specifications

### A. Open-Meteo Weather API & Historical Archive (ERA5)
- **Documentation**: [https://open-meteo.com/en/docs](https://open-meteo.com/en/docs) and [https://open-meteo.com/en/docs/historical-weather-api](https://open-meteo.com/en/docs/historical-weather-api)
- **Archive Endpoint**: `https://archive-api.open-meteo.com/v1/archive`
- **Forecast Endpoint**: `https://api.open-meteo.com/v1/forecast`
- **Parameters Queried**:
  - `precipitation_sum` (mm) — Total daily precipitation
  - `temperature_2m_max` (°C) — Daily maximum air temperature at 2m
  - `temperature_2m_min` (°C) — Daily minimum air temperature at 2m
  - `relative_humidity_2m_mean` (%) — Mean daily relative humidity
- **Model Backend**: ECMWF ERA5 / ERA5-Land reanalysis (0.1° to 0.25° grid) merged seamlessly with IFS operational models.
- **Provenance**: `model_reanalysis` (archive) and `forecast` (operational forward days).

### B. Open-Meteo Flood API (Copernicus GloFAS v4)
- **Documentation**: [https://open-meteo.com/en/docs/flood-api](https://open-meteo.com/en/docs/flood-api)
- **Endpoint**: `https://flood-api.open-meteo.com/v1/flood`
- **Resolution**: ~0.05° (~5 km gridded river network).
- **Parameters Queried**:
  - `river_discharge` (m³/s) — Daily river discharge
  - `river_discharge_mean` (m³/s) — Ensemble mean discharge
  - `river_discharge_p25` (m³/s) — 25th percentile ensemble lower quartile
  - `river_discharge_p75` (m³/s) — 75th percentile ensemble upper quartile
- **River Cell Snapping (`snap_to_river`)**: Because GloFAS maps rivers onto a ~5 km grid, physical gauge coordinates frequently fall into terrestrial or hill cells with zero discharge. The pipeline evaluates candidate coordinates over an adjacent grid and selects the cell with the highest mean discharge, logging the spatial shift distance in km.
- **Reanalysis Truncation & Gap Strategy**: GloFAS v4 reanalysis terminates in mid-2022 (cutoff: `2022-06-30`). The ingestion pipeline detects queries spanning post-2022 and merges operational forecasts with distinct provenance tags, explicitly documenting missing intermediate windows.

### C. India-WRIS / Central Water Commission (CWC)
- **Portal**: [https://indiawris.gov.in/wris/](https://indiawris.gov.in/wris/)
- **Adapter Library**: HydroSwift ([https://github.com/carbform/HydroSwift](https://github.com/carbform/HydroSwift))
- **Role**: Ground-truth gauged water levels and discharge for model calibration and validation.
- **Handling**: Configured as an optional, non-blocking adapter. If unverified or if the portal is unreachable, returns empty collections and logs audit warnings without halting pipeline execution.

### D. Central Pollution Control Board (CPCB) NWMP / JSPCB
- **Portal**: [https://cpcb.nic.in/water-quality-data/](https://cpcb.nic.in/water-quality-data/)
- **Directory**: `data/raw/wq/`
- **Parameters & Physical Boundaries**:
  - `ph`: [0.0, 14.0]
  - `dissolved_oxygen_mg_l`: [0.0, 30.0] mg/L
  - `bod_mg_l`: [0.0, 500.0] mg/L
  - `cod_mg_l`: [0.0, 2000.0] mg/L
  - `conductivity_us_cm`: [0.0, 50000.0] µS/cm
  - `turbidity_ntu`: [0.0, 10000.0] NTU
  - `fecal_coliform_mpn_100ml`: ≥ 0 MPN/100mL
- **Validation**: Enforced via Pydantic model (`CPCBWaterQualityItem`) upon ingestion. Malformed rows trigger audit rejection.

---

## 3. Processed Datasets & Feature Schema (`data/processed/*.parquet`)

Station-level time-series are exported as columnar Parquet datasets following cleaning, lag generation, SPI fitting, and target horizon derivation.

| Feature Group | Column Names | Definition & Rationale |
|---|---|---|
| **Raw & Provenance** | `precipitation_mm`, `temperature_max_c`, `temperature_min_c`, `relative_humidity_mean`, `discharge_m3s`, `provenance` | Ingested hydrometeorological base data with audit provenance. |
| **Cleaning Flags** | `is_interpolated`, `is_outlier_precip`, `is_outlier_discharge`, `outlier_reason` | Non-destructive data quality flags tracking interpolated intervals ($\le 3$ d) and bounds violations. |
| **Precipitation Lags** | `precip_lag_1` … `precip_lag_14` | Shifted past precipitation ($t-1 \dots t-14$ days) avoiding target leakage. |
| **Rolling Moisture** | `precip_roll_sum_3d`, `7d`, `14d`, `30d` | Cumulative precipitation sums over 3, 7, 14, and 30-day antecedent windows. |
| **Antecedent Index** | `antecedent_precipitation_index` | Exponential decay wetness proxy: $\text{API}_t = \sum_{k=1}^{14} (0.88^k \cdot P_{t-k})$. |
| **Calendar Encodings** | `doy_sin`, `doy_cos`, `month_sin`, `month_cos`, `is_monsoon` | Cyclical sine/cosine encodings of day-of-year and month, plus monsoon indicator (June–Oct). |
| **Discharge Lags** | `discharge_lag_1` … `discharge_lag_7`, `discharge_roll_mean_3d`, `7d` | Autoregressive river flow memory and rolling flow averages. |
| **Basin Topology** | `upstream_discharge_lag_1`, `upstream_discharge_lag_2`, `upstream_precip_roll_3d` | Shifted discharge and rainfall signals propagated from designated upstream stations. |
| **Drought Indices** | `spi_30d`, `spi_90d`, `spi_180d`, `spi_*d_category` | WMO Standardized Precipitation Index fitted via 2-parameter Gamma distribution (Thom MLE expanding window or reference period). |
| **Static Attributes** | `static_elevation_m`, `static_drainage_area_km2`, `static_channel_slope_m_per_km`, `static_stream_order`, `static_dominant_land_cover` | Physiographic catchment characteristics enabling entity-aware multi-station modeling. |
| **Forecast Targets** | `target_discharge_h1` … `target_discharge_h7` | Lead river discharge targets for forecasting horizons $t+1 \dots t+7$ days ahead. |

