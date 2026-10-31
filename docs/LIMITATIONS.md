# Limitations & Assumptions — HydroPulse AI

In strict accordance with the project integrity principles, all assumptions, data discontinuities, and structural limitations are catalogued here.

## 1. GloFAS Discontinuities & Gap Strategy
- **Nature of Data**: GloFAS discharge is numerical simulation output from the ECMWF/Copernicus land surface model (HTESSEL + LISFLOOD), not ground truth gauge measurement.
- **Historical End Date**: GloFAS v4 historical reanalysis terminates in mid-2022. Post-2022 data relies on operational forecast runs or ERA5-forced simulations.
- **Handling Strategy**: The data ingestion layer explicitly detects date boundaries and tags pre-2022 data as `model_reanalysis` and forward runs as `forecast`. Missing mid-2022 to current transition periods are documented and never filled with fabricated readings.

## 2. Spatial Resolution & River Snapping
- **Grid Size**: GloFAS operates on a ~0.05° (~5 km) grid cell. 
- **Point Snapping**: If a user coordinates a gauge at a bridge, the nearest grid cell center may lie on dry land or an adjacent hill. The `snap_to_river()` heuristic searches adjacent cells within $\pm 0.1^\circ$ to locate the channel cell with highest mean flow. The displacement distance is logged.

## 3. Reservoir Gate Operations
- Major dams exist in the monitored basins: Tenughat, Konar, Maithon, Panchet, and Chandil.
- Real-time hourly gate release hydrographs are not publicly exposed via open APIs in India.
- Consequently, downstream discharge spikes caused strictly by dam operations cannot be anticipated solely by precipitation-runoff models until the surge reaches downstream gauges.

## 4. Sparse Water Quality Data
- CPCB/JSPCB water quality stations report at monthly or bi-monthly frequencies. High-frequency daily WQI estimation relies on statistical interpolation and hydrological correlation.
- Extreme industrial discharge spills in mining belts cannot be predicted without continuous online effluent sensors.

## 5. Advisory Status
- HydroPulse AI is an experimental decision-support prototype. It does not supersede statutory flood warnings issued by the Central Water Commission (CWC) or the Jharkhand State Disaster Management Authority (JSDMA).

## 6. Feature Pipeline & Hydrologic Lag Approximations
- Upstream station topology propagation uses empirical discrete daily lags (1-day and 2-day). Hydrodynamic flood wave travel time (Muskingum routing) is approximated through autoregressive lag features rather than full 1D/2D hydraulic channel modeling.
- Standardized Precipitation Index (SPI) requires adequate accumulation history: for sample lengths below 30 days, expanding-window estimators yield NaN values until the minimum threshold of valid observations ($N \ge 10$) is satisfied.

## 7. Outlier Management & Imputation
- Adhering to the non-destructive principle, outlier values are flagged with specific reasons (`negative_rainfall`, `exceeds_physical_max`, `discharge_zscore`) rather than dropped or silently overwritten. Downstream model pipelines must handle flagged records explicitly via robust scalers or loss functions.
