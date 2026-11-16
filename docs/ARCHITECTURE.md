# HydroPulse AI — System Architecture

## Overview
HydroPulse AI is engineered as a modular, reproducible hydrologic and water-quality intelligence platform tailored to the complex river basins of Jharkhand (Damodar, Subarnarekha, and tributaries).

## High-Level Architecture Diagram

```mermaid
graph TD
    subgraph DataIngestion["1. Ingestion Layer (src/hydropulse/ingest)"]
        W[Open-Meteo Weather API<br/>ERA5 Historical + 7-Day Forecast]
        F[Open-Meteo Flood API<br/>GloFAS v4 Gridded Reanalysis & Forecast]
        G[India-WRIS / CWC Gauges<br/>Observed Discharge via hydroswift]
        WQ[CPCB / JSPCB NWMP<br/>Water Quality Monthly Records]
    end

    subgraph Snapping["2. Snapping & Quality Control"]
        S[snap_to_river()<br/>Locates local cell with maximum mean discharge]
        QC[Cleaning & Validation<br/>Outlier detection, unit standardisation, gap logging]
    end

    subgraph Storage["3. Persistence Layer"]
        DB[(SQLite / PostgreSQL via SQLAlchemy<br/>Every row tagged with provenance)]
    end

    subgraph Features["4. Feature Engineering (src/hydropulse/features)"]
        Lags[Rainfall & Discharge Lags 1-14d<br/>Rolling sums 3, 7, 14, 30d]
        SPI_Calc[Gamma-fitted SPI-1, 3, 6]
        Topo[Upstream Topology & Static Catchment Attrs]
    end

    subgraph Modeling["5. Forecasting & Scoring Models (src/hydropulse/models)"]
        Base[Baselines: Persistence, Climatology, Ridge]
        LGBM[LightGBM Direct Multi-Horizon t+1..t+7]
        LSTM[PyTorch Seq2Seq / Multi-Station LSTM]
        Residual[Hybrid GloFAS Residual Correction]
        Quantile[Quantile Loss P10, P50, P90]
        WQI_Model[Weighted-Arithmetic WQI: CPCB A-E]
        Drought_Model[Combined SPI + Q90 Low-Flow Stress]
        SHAP_Expl[SHAP / TreeExplainer for Alert Causality]
    end

    subgraph Serving["6. API & Dashboard (src/hydropulse/api & web)"]
        API[Flask 3 Factory & Blueprints<br/>/api/v1/health, /forecast, /alerts, /docs]
        UI[Leaflet Map + Chart.js Dashboard<br/>Responsive, accessible, bilingual EN/HI]
    end

    W --> QC
    F --> S --> QC
    G --> QC
    WQ --> QC
    QC --> DB
    DB --> Lags & SPI_Calc & Topo
    Lags & SPI_Calc & Topo --> Base & LGBM & LSTM & Residual & Quantile & WQI_Model & Drought_Model
    LGBM --> SHAP_Expl
    Base & LGBM & LSTM & Residual & Quantile & WQI_Model & Drought_Model & SHAP_Expl --> API
    API --> UI
```

## Component Roles
1. **Ingestion Layer**: Fetches public data with caching, strict provenance labeling (`observed`, `model_reanalysis`, `forecast`, `synthetic`), and graceful fallbacks.
2. **Snapping & QC**: Resolves spatial coordinate mismatch between real gauge/town coordinates and GloFAS 0.05-degree river cells via `snap_to_river()`.
3. **Feature Pipeline (`src/hydropulse/features`)**:
   - `cleaning.py`: Performs non-destructive anomaly tagging (`is_outlier_*`), interpolation of short gaps ($\le 3$ d) tagged with `is_interpolated=True`, and train-only scaling (`TrainOnlyScaler`).
   - `lags.py`: Implements strictly leak-free temporal features (rainfall lags 1–14 d, rolling sums 3/7/14/30 d, API antecedent wetness proxy, cyclical calendar encodings, discharge memory, and upstream topology propagation).
   - `spi.py`: Computes Standardized Precipitation Indices (SPI-1/3/6) via 2-parameter Gamma distribution (Thom MLE closed-form expanding window or reference period fitting).
   - `static_attrs.py`: Injects physiographic catchment attributes (elevation, drainage area, slope, stream order, land cover) for entity-aware multi-station learning.
   - `builder.py`: Integrates SQLite raw records, executes feature derivation, and exports per-station Parquet datasets into `data/processed/`.
4. **Model Tier (`src/hydropulse/models`)**:
   - `baselines.py`: Persistence, daily climatology, and regularised Ridge forecasters.
   - `lgbm.py`: Direct multi-horizon LightGBM with hybrid residual GloFAS learning and SHAP TreeExplainer attributions.
   - `quantile.py`: Pinball loss quantile forecaster producing calibrated P10, P50, and P90 uncertainty bands.
   - `lstm.py`: Per-station seq2seq LSTM and entity-aware multi-station LSTM with learnable station embeddings.
   - `drought.py`: Computes historical $Q_{90}$ low-flow thresholds, flags hydrological deficits, synthesizes multi-scalar SPI into compound drought tiers, and forecasts 30-day outlook trajectories.
   - `wqi.py`: Computes Weighted-Arithmetic WQI (WA-WQI) with dynamic weight re-allocation, evaluates statutory CPCB Designated-Best-Use classes A–E, performs non-parametric Mann-Kendall trend tests and classical seasonal decomposition, flags industrial effluent hotspots, and predicts next-month CPCB classes.
5. **API Service Layer (`src/hydropulse/api`)**:
   - `factory.py`: Application factory (`create_app`) configuring environment-specific settings, registering blueprints, middleware hooks, and standard error envelopes.
   - `middleware.py`:
     - `InMemoryTTLCache` & `@cached`: Thread-safe in-memory cache with query-aware keying and `X-Cache: HIT | MISS` transparency.
     - `RateLimiter`: Token bucket / sliding-window rate limiter (default 120 req/min) returning RFC-standard `X-RateLimit-*` headers and HTTP 429 when exhausted.
     - Request Tracking: Injects UUID4 `X-Request-ID` (or propagates upstream client ID) and high-resolution execution timing via `X-Response-Time-Ms`.
     - Consistent Error Envelopes: Formatted JSON `{status, error: {code, message, details, request_id}, timestamp}` for 400, 404, 405, 429, and 500.
   - **Blueprints**:
     - `blueprints/health.py`: Dynamic health check probe and configuration readiness at `/api/v1/health`.
     - `blueprints/stations.py`: Station metadata catalogue (`/api/v1/stations`), 1–7 day multi-horizon forecast hydrographs (`/api/v1/stations/<id>/forecast`), and historical observations (`/api/v1/stations/<id>/history`).
     - `blueprints/risk.py`: Basin-wide GeoJSON FeatureCollection risk map (`/api/v1/risk/map`) and active bilingual flood alerts with SHAP attribution reasons (`/api/v1/alerts`).
     - `blueprints/river_health.py`: Weighted-Arithmetic WQI, CPCB class, and pollutant profiles (`/api/v1/water-quality/<id>`), and compound SPI + $Q_{90}$ drought stress outlooks (`/api/v1/drought/<id>`).
     - `blueprints/governance.py`: Machine-readable single source of truth model metrics from `reports/metrics.json` at `/api/v1/model/metrics`.
   - `docs.py`: Embedded Swagger UI at `/docs` backed by dynamic OpenAPI 3.0 specification at `/api/v1/openapi.json`.
6. **Presentation Tier (`src/hydropulse/web`)**:
   - `routes.py`: Flask blueprint serving `/dashboard` (and `/` for browser agents).
   - `templates/`:
     - `base.html`: Semantic HTML5 document shell, accessibility skip links, Leaflet 1.9.4 & Chart.js 4.4.1 dependencies, permanent CWC/JSDMA statutory disclaimer banner, live provenance pills, and bilingual toggle.
     - `dashboard.html`: Responsive two-column layout mounting geospatial basin map, active alerts ticker strip, station risk cards, hydrograph canvas, WQI panel, and drought outlook widgets.
   - `static/css/dashboard.css`: WCAG AAA accessible high-contrast design system, dark river canvas theme, keyboard focus indicators, and double-encoded color-blind safe palettes (shape + color + text).
   - `static/js/`:
     - `api_client.js`: Asynchronous fetch wrapper handling latency tracking and error envelopes.
     - `state.js`: Central state store for active station, language (`en`/`hi`), and basin filters.
     - `map_view.js`: Leaflet map controller managing custom SVG station markers (● Circle, ■ Square, ▲ Triangle, ◆ Octagon) and pulsing warning indicators.
     - `hydrograph.js`: Chart.js time-series hydrograph plotting 14-day history, P50 forecast, shaded P10–P90 uncertainty confidence intervals, and CWC warning/danger thresholds.
     - `health_view.js`: Weighted-Arithmetic WQI gauge, statutory CPCB Designated-Best-Use classes A–E, and industrial effluent hotspot indicators.
     - `drought_view.js`: Multi-scalar SPI-1/3/6 progress bars, $Q_{90}$ low-flow status, and 30-day forward outlook trajectory.
     - `app.js`: Master application coordinator handling bilingual dictionaries, event wiring, and 60-second live polling.
