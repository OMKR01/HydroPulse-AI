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
- **Official Criteria Documentation**: [https://cpcb.nic.in/water-quality-criteria/](https://cpcb.nic.in/water-quality-criteria/)
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

#### Official CPCB Designated-Best-Use Water Quality Criteria
| Class | Designated Best Use | pH | Dissolved Oxygen (DO) | Biochemical Oxygen Demand (BOD) | Total / Fecal Coliform | Electrical Conductivity (EC) |
|---|---|---|---|---|---|---|
| **Class A** | Drinking water source without conventional treatment but after disinfection | 6.5 – 8.5 | $\ge 6.0\text{ mg/L}$ | $\le 2.0\text{ mg/L}$ | $\le 50\text{ MPN/100mL}$ | — |
| **Class B** | Outdoor bathing (organized swimming) | 6.5 – 8.5 | $\ge 5.0\text{ mg/L}$ | $\le 3.0\text{ mg/L}$ | $\le 500\text{ MPN/100mL}$ | — |
| **Class C** | Drinking water source after conventional treatment and disinfection | 6.5 – 9.0 | $\ge 4.0\text{ mg/L}$ | $\le 3.0\text{ mg/L}$ | $\le 5000\text{ MPN/100mL}$ | — |
| **Class D** | Propagation of wildlife and fisheries | 6.5 – 8.5 | $\ge 4.0\text{ mg/L}$ | — | — | — |
| **Class E** | Irrigation, industrial cooling, controlled waste disposal | 6.0 – 8.5 | — | — | — | $\le 2250\text{ }\mu\text{S/cm}$ |
| **Below E** | Not fit for designated uses (heavy pollution / toxic load) | $< 6.0$ or $> 8.5$ | $< 4.0\text{ mg/L}$ | $> 3.0\text{ mg/L}$ | $> 5000\text{ MPN/100mL}$ | $> 2250\text{ }\mu\text{S/cm}$ |

#### Weighted-Arithmetic Water Quality Index (WA-WQI; Brown et al., 1972)
The aggregate WQI maps multiple physico-chemical contaminants into an integrated unit index:
$$\text{WQI} = \frac{\sum_{i=1}^n W_i q_i}{\sum_{i=1}^n W_i}$$
where quality sub-indices $q_i = 100 \times \left|\frac{V_i - V_{\text{ideal}}}{S_i - V_{\text{ideal}}}\right|$ and unit weights $W_i = \frac{K}{S_i}$ with $K = \frac{1}{\sum (1/S_i)}$.
- **Standard Limits ($S_i$) & Ideals ($V_{\text{ideal}}$)**:
  - $\text{pH}$: $S_i = 8.5$, $V_{\text{ideal}} = 7.0$
  - $\text{DO}$: $S_i = 5.0\text{ mg/L}$, $V_{\text{ideal}} = 14.6\text{ mg/L}$
  - $\text{BOD}$: $S_i = 5.0\text{ mg/L}$, $V_{\text{ideal}} = 0.0$
  - $\text{COD}$: $S_i = 50.0\text{ mg/L}$, $V_{\text{ideal}} = 0.0$
  - $\text{Conductivity}$: $S_i = 1000.0\text{ }\mu\text{S/cm}$, $V_{\text{ideal}} = 0.0$
  - $\text{Turbidity}$: $S_i = 10.0\text{ NTU}$, $V_{\text{ideal}} = 0.0$
  - $\text{Fecal Coliform}$: $S_i = 500.0\text{ MPN/100mL}$, $V_{\text{ideal}} = 0.0$
- **WQI Rating Bands**:
  - $0\text{--}25$: Excellent (Grade A)
  - $26\text{--}50$: Good (Grade B)
  - $51\text{--}75$: Poor (Grade C)
  - $76\text{--}100$: Very Poor (Grade D)
  - $> 100$: Unfit for Drinking (Grade E / Below E)

#### Mining & Industrial Hotspot Screening (Bokaro–Dhanbad Stretch)
Screening triggers on industrial effluent indicators:
- Hypoxia: $\text{DO} < 4.0\text{ mg/L}$
- Excessive Organic Pollution: $\text{BOD} > 5.0\text{ mg/L}$
- Industrial Chemical Effluent: $\text{COD} > 50.0\text{ mg/L}$
- Salinity / Heavy Mineral Runoff: $\text{Conductivity} > 1500.0\text{ }\mu\text{S/cm}$
- Severe Fecal Contamination: $\text{Fecal Coliform} > 2500.0\text{ MPN/100mL}$
*Provenance Notice:* Marked strictly as `indicative` unless real ground observations from CPCB/JSPCB are confirmed.

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

---

## 4. Documented Historical Flood Events (`data/events/historical_floods.yaml`)
In accordance with AGENTS.md integrity rules, every event used for validation represents a verified, documented historical flood event in Jharkhand backed by news publications, CWC, or peer-reviewed literature.

| Event ID | Event Title & Basin | Dates | Sourced URL | Publisher / Authority |
|---|---|---|---|---|
| `flood_2022_subarnarekha_aug` | August 2022 Subarnarekha and Kharkai Flash Inundation (Subarnarekha) | 2022-08-20 to 2022-08-23 | [Times of India Article](https://timesofindia.indiatimes.com/city/ranchi/500-houses-submerged-in-jamshedpur-as-kharkai-subarnarekha-cross-danger-mark/articleshow/93693910.cms) | The Times of India |
| `flood_2021_damodar_jul_aug` | Late July - Early August 2021 Upper Damodar Basin Surge (Damodar) | 2021-07-29 to 2021-08-03 | [The Hindu Article](https://www.thehindu.com/news/national/other-states/record-inflow-in-dvc-dams-as-monsoon-spells-trouble/article35661139.ece) | The Hindu / DVC |
| `flood_2021_yaas_may` | May 2021 Cyclone Yaas Remnant Inundation (Damodar & Subarnarekha) | 2021-05-26 to 2021-05-29 | [Times of India Article](https://timesofindia.indiatimes.com/city/ranchi/cyclone-yaas-leaves-trail-of-destruction-in-jharkhand/articleshow/83021960.cms) | The Times of India / IMD |
| `flood_2016_subarnarekha_aug` | August 2016 Subarnarekha Catchment Flash Surge (Subarnarekha) | 2016-08-16 to 2016-08-20 | [SANDRP Report](https://sandrp.in/2016/08/24/subarnarekha-basin-floods-august-2016/) | SANDRP / CWC |
| `flood_2016_damodar_sep` | September 2016 Upper Damodar Valley Inundation (Damodar) | 2016-09-04 to 2016-09-08 | [Times of India Article](https://timesofindia.indiatimes.com/city/kolkata/cwc-alert-as-dams-fill-up-fast/articleshow/54044158.cms) | The Times of India / CWC |


