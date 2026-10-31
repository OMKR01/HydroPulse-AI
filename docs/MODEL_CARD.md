# Model Card — HydroPulse AI

## 1. Intended Use & Scope
- **Primary Task**: Multi-horizon river discharge forecasting ($t+1 \dots t+7$ days) and low-flow/flood alert derivation for river basins in Jharkhand.
- **Secondary Task**: River health scoring using weighted-arithmetic Water Quality Index (WQI) and Standardized Precipitation Index (SPI) drought categorization.
- **Target Users**: Hydrologic researchers, disaster preparedness teams, academic examiners, and public interest observers.
- **Out of Scope**: Direct operational dam gate actuation, urban street flood drainage modeling, or replacement of statutory CWC warnings.

## 2. Model Architecture Summary
1. **Baselines**:
   - Persistence ($Q_{t+h} = Q_t$)
   - Climatology (day-of-year historical mean/median)
   - L2 Ridge Regression on antecedent rainfall & discharge lags
2. **LightGBM Multi-Horizon**:
   - Gradient boosted trees trained on chronological features with quantile regression objective (P10, P50, P90).
3. **PyTorch LSTM**:
   - Sequence-to-sequence recurring neural network capturing long-range antecedent soil saturation.
4. **Hybrid Residual Post-Processor**:
   - Model learns the residual correction $\Delta Q = Q_{\text{target}} - Q_{\text{GloFAS}}$ over raw GloFAS forecast output.

## 3. Evaluation Metrics
Evaluated strictly per horizon $h \in [1, 7]$:
- Hydrologic: Nash-Sutcliffe Efficiency (NSE), Kling-Gupta Efficiency (KGE), RMSE, MAE.
- Alert & Threshold: Probability of Detection (POD), False Alarm Ratio (FAR), Critical Success Index (CSI), F1 score, Peak-Timing Error.
- Integrity: All final metrics read directly from `reports/metrics.json`.

## 4. Failure Modes & Cautionary Guidance
- Flash floods driven by highly localized convective cloudbursts outside 5-km grid resolution.
- Unscheduled dam gate releases (e.g., sudden discharge from Tenughat or Maithon dam) not reflected in meteorological forcing alone.
- Prolonged dry season zero-flow riverbed behavior in smaller tributaries.
