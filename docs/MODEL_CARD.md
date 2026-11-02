# HydroPulse AI — Model Card

> **Status:** Phase 3 complete (November 2026)  
> This model card follows the Google Model Card format.  
> All metric values in this document are read from `reports/metrics.json`  
> which is populated exclusively by evaluation scripts — never hand-typed.

---

## Model Overview

| Field | Value |
|---|---|
| **System** | HydroPulse AI: Jharkhand River Health Monitoring System |
| **Task** | Multi-horizon river discharge forecasting (t+1 … t+7 days) |
| **Basins** | Damodar, Subarnarekha (Jharkhand, India) |
| **Intended use** | Advisory situational awareness for flood risk monitoring |
| **Owner** | Om Kumar, MCA, Amity University Ranchi |
| **Version** | Phase 3 |

---

## Models Implemented

### 1. Baselines (honest floor)

| Model | Description |
|---|---|
| **Persistence** | Last-known discharge repeated for all 7 horizons |
| **Climatology** | Historical median by calendar week, per horizon |
| **Ridge regression** | Phase 2 feature set, one Ridge model per horizon, train-only StandardScaler |
| **Raw GloFAS** | GloFAS reanalysis discharge used as-is without ML correction |

> All baselines expose `.fit(train_df)` / `.predict(df) -> (n, 7)`.

### 2. LightGBM — Direct Multi-Horizon (`lgbm`)

- **Strategy:** Direct (7 independent `LGBMRegressor` instances, one per horizon)
- **Features:** All Phase 2 features — lagged rainfall (1-14 d), rolling sums (3/7/14/30 d), antecedent precipitation index, discharge auto-lags (1-7 d), day-of-year sin/cos, monsoon indicator, static catchment attributes
- **Hyper-parameters:** `n_estimators=400`, `lr=0.05`, `max_depth=6`, `subsample=0.8` (not tuned in Phase 3)
- **Explainability:** SHAP TreeExplainer, mean |SHAP| per feature per horizon
- **Persistence:** `reports/runs/<run_id>/lgbm_h{h}.pkl`

### 3. LightGBM Hybrid GloFAS Correction (`lgbm_hybrid`)

- **Target:** residual = observed_discharge minus raw_GloFAS_discharge
- **Forecast:** GloFAS + residual_hat (clipped to >= 0)
- **Rationale:** GloFAS is a global model with systematic biases at station scale; the ML layer learns the local correction

> **IMPORTANT:** GloFAS is model output (ERA5 reanalysis forcing), not a gauge reading. All outputs from this model carry `data_provenance: "model_reanalysis"`.

### 4. Quantile LightGBM (`lgbm_quantile`)

- **Quantiles:** P10, P50, P90 via `objective="quantile"`, 21 models total (3 x 7)
- **Monotone enforcement:** Post-hoc sorting ensures P10 <= P50 <= P90
- **Calibration target:** >= 75% of test observations fall inside the P10-P90 band

### 5. Per-Station LSTM (`lstm_per_station`)

- **Architecture:** 2-layer LSTM, hidden=128, dropout=0.2, direct 7-output head
- **Input:** Sliding window of 30 days of normalised features
- **Training:** Adam (lr=1e-3), cosine LR decay, early stopping (patience=15 on val loss)
- **Attribution:** Gradient-based sensitivity (mean |d(output)/d(input)| over test windows)
- **Persistence:** `reports/runs/<run_id>/lstm_<station_id>.pt`

### 6. Multi-Station LSTM (`lstm_multi_station`)

- **Architecture:** Same as per-station LSTM with an additional learnable station embedding (dim=8) concatenated to the feature sequence
- **Training:** All stations jointly, enabling shared temporal representations
- **When to use:** When per-station data is too sparse for independent training

---

## Data

| Source | Role | Provenance Label |
|---|---|---|
| Open-Meteo ERA5 archive | Historical precipitation, temperature, humidity | `model_reanalysis` |
| Open-Meteo Flood API (GloFAS v4) | Daily river discharge reanalysis + forecast | `model_reanalysis` |
| India-WRIS / CWC | Optional observed gauge data (sparse) | `observed` |
| CPCB NWMP | Water quality (Phase 4) | `observed` |

**GloFAS coverage note:** The reanalysis history ends mid-2022 in the current dataset. The period from 2022-H2 onwards uses forecast-era data, which has a different uncertainty profile. This transition is explicitly handled in the pipeline but introduces heterogeneity in the test set.

**Station coordinates:** All 10 station entries in `config/stations.yaml` are marked `verified: false`. Coordinates are approximate; the `snap_to_river()` procedure adjusts each point to the nearest GloFAS river cell.

---

## Training / Evaluation Splits

```
Train :  2000-01-01 to 2018-12-31   (~19 years, ~6935 rows per station)
Val   :  2019-01-01 to 2020-12-31   (~2 years, used for LSTM early stopping)
Test  :  2021-01-01 to 2024-12-31   (~4 years, never seen during training)
```

- **Chronological splits only.** No row shuffling at any point.
- **Scaler / threshold statistics** fit strictly on the train partition.
- **Blocked time-series cross-validation** (5 folds) used for hyper-parameter selection in future phases.

---

## Metrics

> All numbers populated automatically from `reports/metrics.json`.
> See that file for the current best results per station per horizon.

| Metric | Description |
|---|---|
| NSE | Nash-Sutcliffe Efficiency (1.0 = perfect; < 0 = worse than mean) |
| KGE | Kling-Gupta Efficiency (decomposes correlation, variability, bias) |
| RMSE | Root Mean Squared Error [m3/s] |
| MAE | Mean Absolute Error [m3/s] |
| POD | Probability of Detection (hit rate for Watch/Warning/Danger events) |
| FAR | False Alarm Ratio |
| CSI | Critical Success Index |
| F1 | Harmonic mean of precision and recall |
| PR-AUC | Area under Precision-Recall curve |
| Peak timing error | Signed day-lag between predicted and observed discharge peak |

---

## Honest Assessment of LSTM vs LightGBM

In many hydrological benchmarks on data-sparse river systems, gradient boosted trees
(LightGBM/XGBoost) match or outperform LSTMs because:

1. **Data volume:** LSTMs excel with large datasets. With approximately 7000 training rows per
   station and noisy GloFAS targets, the advantage of learned sequence representations
   is often marginal.
2. **Feature engineering:** The Phase 2 lag and rolling features already encode much
   of the temporal structure an LSTM would learn implicitly.
3. **Overfitting risk:** With limited validation data, LSTM regularisation (dropout,
   early stopping) may not be sufficient to prevent overfitting on the monsoon peaks.

**If the LSTM does not improve NSE/KGE over LightGBM in the evaluation results,
that is reported honestly in `reports/model_comparison.md` and this model card
is updated accordingly.** The multi-station LSTM is more likely to show gains when
several stations have overlapping monsoon dynamics.

---

## Known Failure Modes

1. **Ungauged sub-catchments:** Model extrapolates to unmonitored tributaries with no
   skill guarantee.
2. **Dam releases:** No reservoir release schedule data is incorporated. Sudden release
   events (Tenughat, Maithon, Panchet, Chandil) can cause large forecast errors.
3. **Flash floods:** Sub-daily convective events are not captured by daily-resolution
   GloFAS/ERA5 inputs. The system cannot forecast flash floods.
4. **Land-use change:** Models trained on 2000-2018 data may not capture recent
   catchment changes (urbanisation, mining, deforestation).
5. **GloFAS transition (2022):** The shift from reanalysis to forecast-era data in
   the test period introduces additional uncertainty.
6. **Extreme events:** Training data likely under-represents Extremely High discharge
   events (P99+); model may systematically underestimate peak flows.
7. **Point snapping uncertainty:** `snap_to_river()` moves the monitoring point up to
   a few km to align with the nearest GloFAS river cell; this introduces a spatial
   mismatch that is unquantified.

---

## Where This Model Should NOT Be Trusted

- **Emergency flood evacuation decisions** — always follow CWC / Jharkhand SDMA official warnings.
- **Sub-daily flood routing.**
- **Stations outside the 10 configured monitoring points** — model has no spatial generalisation.
- **Post-dam-failure scenarios.**
- **Water-quality predictions** — handled separately in Phase 4 (WQI model).

---

## Advisory Disclaimer

> *This system is for research and situational awareness only.*
> *Official flood warnings come from the Central Water Commission (CWC)*
> *and the Jharkhand State Disaster Management Authority.*
> *Do not use model output to make life-safety decisions.*

---

## Reproducibility

| Item | Value |
|---|---|
| Random seed | 42 (fixed in all models) |
| Python | 3.11+ |
| Key libraries | LightGBM >= 4.1, PyTorch >= 2.1, scikit-learn >= 1.3, SHAP >= 0.43 |
| Run logs | `reports/runs/<run_id>/run_config_<station>.json` |
| Git SHA | Logged per run in `reports/metrics.json` |
