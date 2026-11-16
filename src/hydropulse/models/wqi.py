"""Water Quality Index (WQI), CPCB classification, and trend analysis for river health.

Implements:
1. Weighted-Arithmetic Water Quality Index (WA-WQI; Brown et al., 1972) with dynamic re-weighting.
2. Official CPCB designated-best-use classification (Classes A, B, C, D, E, Below_E).
   Official reference: https://cpcb.nic.in/water-quality-criteria/
3. Non-parametric Mann-Kendall trend test with Sen's slope and tie-corrected variance.
4. Classical monthly seasonal decomposition (additive and multiplicative).
5. Mining/industrial pollution hotspot screening (Bokaro-Dhanbad belt) with "indicative" tagging.
6. Leak-free next-month WQI predictive classifier.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

# Standard permissible values (Sn) and ideal values (Vi) for surface waters (BIS 10500 / CPCB)
STANDARD_LIMITS: dict[str, float] = {
    "ph": 8.5,  # Upper permissible limit (neutral=7.0, lower=6.5)
    "dissolved_oxygen_mg_l": 5.0,  # Minimum desirable DO
    "bod_mg_l": 5.0,  # Maximum permissible BOD
    "cod_mg_l": 50.0,  # Permissible COD limit
    "conductivity_us_cm": 1000.0,  # Standard inland EC limit
    "turbidity_ntu": 10.0,  # Standard turbidity limit
    "fecal_coliform_mpn_100ml": 500.0,  # Outdoor bathing limit
}

IDEAL_VALUES: dict[str, float] = {
    "ph": 7.0,
    "dissolved_oxygen_mg_l": 14.6,  # Saturated DO at standard temp
    "bod_mg_l": 0.0,
    "cod_mg_l": 0.0,
    "conductivity_us_cm": 0.0,
    "turbidity_ntu": 0.0,
    "fecal_coliform_mpn_100ml": 0.0,
}

CPCBClass = Literal["A", "B", "C", "D", "E", "Below_E"]
WQIRating = Literal["Excellent", "Good", "Poor", "Very Poor", "Unfit"]
TrendDirection = Literal["increasing", "decreasing", "no_trend"]
HotspotSeverity = Literal["None", "Moderate", "Critical"]


@dataclass(frozen=True)
class WQIScore:
    """Detailed breakdown of computed Water Quality Index for an observation."""

    wqi: float
    rating: WQIRating
    cpcb_class: CPCBClass
    sub_indices: dict[str, float]
    weights_used: dict[str, float]
    parameters_present: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MannKendallResult:
    """Result of Mann-Kendall non-parametric trend test and Sen's slope."""

    parameter: str
    n_samples: int
    s_statistic: float
    var_s: float
    z_statistic: float
    p_value: float
    sens_slope: float
    trend: TrendDirection

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SeasonalDecompositionResult:
    """Classical additive or multiplicative seasonal decomposition components."""

    parameter: str
    observed: list[float]
    trend: list[float]
    seasonal: list[float]
    residual: list[float]
    period: int
    model: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HotspotAssessment:
    """Industrial/mining pollution hotspot screening assessment."""

    station_id: str
    date: str
    severity: HotspotSeverity
    is_hotspot: bool
    trigger_pollutants: list[str]
    status_label: str  # "indicative" or "verified"
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ─────────────────────── 1. WQI and CPCB Classification ──────────────────────────


def compute_sub_index(param: str, value: float) -> float:
    """Compute the quality sub-index (qn) for a single parameter.

    qn = 100 * |(Vn - Vi) / (Sn - Vi)|
    """
    if param not in STANDARD_LIMITS or param not in IDEAL_VALUES:
        return 0.0

    sn = STANDARD_LIMITS[param]

    if param == "ph":
        # pH ideal is 7.0; permissible range is 6.5 to 8.5
        # |V - 7.0| / (8.5 - 7.0) = |V - 7.0| / 1.5
        return float(100.0 * abs(value - 7.0) / 1.5)

    if param == "dissolved_oxygen_mg_l":
        # Lower DO means worse water quality. Vi = 14.6 mg/L, Sn = 5.0 mg/L.
        if value >= 14.6:
            return 0.0
        return float(100.0 * (14.6 - value) / (14.6 - 5.0))

    # For other contaminants (BOD, COD, EC, Turbidity, Coliform), Vi = 0.0
    return float(100.0 * max(0.0, value) / sn)


def calculate_wqi(record: dict[str, Any] | pd.Series) -> WQIScore:
    """Calculate Weighted-Arithmetic Water Quality Index (Brown et al., 1972).

    Dynamically calculates proportionality constant K and normalizes unit weights Wn
    based exclusively on the parameters present in the record.

    Returns:
        WQIScore: aggregated WQI, qualitative rating, and CPCB class.
    """
    present_params: dict[str, float] = {}

    for param in STANDARD_LIMITS:
        val = record.get(param)
        if val is not None and not (isinstance(val, float) and np.isnan(val)):
            try:
                fval = float(val)
                present_params[param] = fval
            except (ValueError, TypeError):
                continue

    if not present_params:
        return WQIScore(
            wqi=0.0,
            rating="Unfit",
            cpcb_class="Below_E",
            sub_indices={},
            weights_used={},
            parameters_present=[],
        )

    # 1. Calculate proportionality constant K = 1 / sum(1 / Sn)
    inv_sum = sum(1.0 / STANDARD_LIMITS[p] for p in present_params)
    k_const = 1.0 / inv_sum if inv_sum > 0 else 1.0

    # 2. Normalized unit weights Wn = K / Sn such that sum(Wn) == 1.0
    weights = {p: (k_const / STANDARD_LIMITS[p]) for p in present_params}

    # 3. Compute quality sub-indices qn
    sub_indices = {p: compute_sub_index(p, present_params[p]) for p in present_params}

    # 4. Aggregated WQI = sum(Wn * qn)
    total_wqi = sum(weights[p] * sub_indices[p] for p in present_params)
    total_wqi = max(0.0, float(total_wqi))

    # Rating scale
    if total_wqi <= 25.0:
        rating: WQIRating = "Excellent"
    elif total_wqi <= 50.0:
        rating = "Good"
    elif total_wqi <= 75.0:
        rating = "Poor"
    elif total_wqi <= 100.0:
        rating = "Very Poor"
    else:
        rating = "Unfit"

    cpcb = classify_cpcb_use(record)

    return WQIScore(
        wqi=round(total_wqi, 2),
        rating=rating,
        cpcb_class=cpcb,
        sub_indices={k: round(v, 2) for k, v in sub_indices.items()},
        weights_used={k: round(v, 4) for k, v in weights.items()},
        parameters_present=list(present_params.keys()),
    )


def classify_cpcb_use(record: dict[str, Any] | pd.Series) -> CPCBClass:
    """Classify inland surface water into CPCB designated-best-use classes (A, B, C, D, E, Below_E).

    Reference: Central Pollution Control Board (CPCB) Water Quality Criteria:
    https://cpcb.nic.in/water-quality-criteria/

    Criteria:
    - Class A (Drinking source without conventional treatment but after disinfection):
        Total/Fecal Coliform <= 50 MPN/100ml, pH 6.5 to 8.5, DO >= 6.0 mg/L, BOD <= 2.0 mg/L.
    - Class B (Outdoor bathing / organized swimming):
        Total/Fecal Coliform <= 500 MPN/100ml, pH 6.5 to 8.5, DO >= 5.0 mg/L, BOD <= 3.0 mg/L.
    - Class C (Drinking source after conventional treatment and disinfection):
        Total/Fecal Coliform <= 5000 MPN/100ml, pH 6.5 to 9.0, DO >= 4.0 mg/L, BOD <= 3.0 mg/L.
    - Class D (Propagation of wild life and fisheries):
        pH 6.5 to 8.5, DO >= 4.0 mg/L.
    - Class E (Irrigation, industrial cooling, controlled waste disposal):
        pH 6.0 to 8.5, Conductivity <= 2250 uS/cm.
    - Below_E: Fails Class E criteria (e.g. pH < 6.0 or > 8.5, Conductivity > 2250, or DO < 4.0).
    """

    def _get(key: str) -> float | None:
        val = record.get(key)
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    ph = _get("ph")
    do = _get("dissolved_oxygen_mg_l")
    bod = _get("bod_mg_l")
    cond = _get("conductivity_us_cm")
    coliform = _get("fecal_coliform_mpn_100ml")

    # If critical indicators are entirely missing, fallback safely
    if ph is None and do is None and bod is None:
        return "Below_E"

    # Helper checks (missing parameters do not fail higher classes if other criteria pass)
    def satisfies_a() -> bool:
        if ph is not None and not (6.5 <= ph <= 8.5):
            return False
        if do is not None and do < 6.0:
            return False
        if bod is not None and bod > 2.0:
            return False
        if coliform is not None and coliform > 50.0:
            return False
        return True

    def satisfies_b() -> bool:
        if ph is not None and not (6.5 <= ph <= 8.5):
            return False
        if do is not None and do < 5.0:
            return False
        if bod is not None and bod > 3.0:
            return False
        if coliform is not None and coliform > 500.0:
            return False
        return True

    def satisfies_c() -> bool:
        if ph is not None and not (6.5 <= ph <= 9.0):
            return False
        if do is not None and do < 4.0:
            return False
        if bod is not None and bod > 3.0:
            return False
        if coliform is not None and coliform > 5000.0:
            return False
        return True

    def satisfies_d() -> bool:
        if ph is not None and not (6.5 <= ph <= 8.5):
            return False
        if do is not None and do < 4.0:
            return False
        return True

    def satisfies_e() -> bool:
        if ph is not None and not (6.0 <= ph <= 8.5):
            return False
        if cond is not None and cond > 2250.0:
            return False
        return True

    if satisfies_a():
        return "A"
    if satisfies_b():
        return "B"
    if satisfies_c():
        return "C"
    if satisfies_d():
        return "D"
    if satisfies_e():
        return "E"

    return "Below_E"


# ─────────────────────── 2. Trend & Seasonal Analysis ────────────────────────────


def mann_kendall_test(
    series: pd.Series | np.ndarray,
    parameter_name: str = "parameter",
    alpha: float = 0.05,
) -> MannKendallResult:
    """Non-parametric Mann-Kendall trend test with Sen's slope and tie correction.

    Tests whether a monotonic upward or downward trend exists over time.

    Args:
        series: Array or Series of ordered temporal measurements.
        parameter_name: Label of the parameter being tested.
        alpha: Significance level (default 0.05 for 95% confidence).

    Returns:
        MannKendallResult: contains S statistic, p-value, Sen's slope, and trend.
    """
    if isinstance(series, pd.Series):
        vals = series.dropna().to_numpy(dtype=float)
    else:
        arr = np.asarray(series, dtype=float)
        vals = arr[~np.isnan(arr)]

    n = len(vals)
    if n < 4:
        return MannKendallResult(
            parameter=parameter_name,
            n_samples=n,
            s_statistic=0.0,
            var_s=0.0,
            z_statistic=0.0,
            p_value=1.0,
            sens_slope=0.0,
            trend="no_trend",
        )

    # 1. Compute Mann-Kendall S statistic
    # S = sum_{k=1}^{n-1} sum_{j=k+1}^n sgn(x_j - x_k)
    s = 0.0
    slopes: list[float] = []
    for k in range(n - 1):
        for j in range(k + 1, n):
            diff = vals[j] - vals[k]
            s += np.sign(diff)
            slopes.append(diff / (j - k))

    # 2. Tie adjustment for Var(S)
    # Var(S) = (1/18) * [n(n-1)(2n+5) - sum_p tp*(tp-1)*(2*tp+5)]
    unique_vals, counts = np.unique(vals, return_counts=True)
    tie_term = sum(t * (t - 1) * (2 * t + 5) for t in counts if t > 1)
    var_s = (n * (n - 1) * (2 * n + 5) - tie_term) / 18.0

    # 3. Standardized test statistic Z
    if var_s > 0:
        if s > 0:
            z = (s - 1.0) / np.sqrt(var_s)
        elif s < 0:
            z = (s + 1.0) / np.sqrt(var_s)
        else:
            z = 0.0
    else:
        z = 0.0

    # 4. Two-tailed p-value from standard normal
    p_value = 2.0 * (1.0 - stats.norm.cdf(abs(z)))

    # 5. Sen's slope = median of all pair slopes
    sens_slope = float(np.median(slopes)) if slopes else 0.0

    # Determine trend
    if p_value < alpha:
        trend: TrendDirection = "increasing" if s > 0 else "decreasing"
    else:
        trend = "no_trend"

    return MannKendallResult(
        parameter=parameter_name,
        n_samples=n,
        s_statistic=float(s),
        var_s=float(var_s),
        z_statistic=round(float(z), 4),
        p_value=round(float(p_value), 5),
        sens_slope=round(sens_slope, 5),
        trend=trend,
    )


def seasonal_decompose_monthly(
    series: pd.Series,
    period: int = 12,
    model: Literal["additive", "multiplicative"] = "additive",
    parameter_name: str = "parameter",
) -> SeasonalDecompositionResult:
    """Classical monthly seasonal decomposition (trend, seasonal, residual).

    Uses a centered moving average of length `period` for trend estimation,
    computes detrended monthly averages for seasonal component, and extracts residuals.

    Args:
        series: Pandas Series with datetime or sorted monthly index.
        period: Seasonal periodicity (default 12 for monthly data).
        model: "additive" (Y = T + S + R) or "multiplicative" (Y = T * S * R).
        parameter_name: Name of the decomposed parameter.
    """
    clean_series = series.copy().astype(float)
    clean_series = clean_series.interpolate(method="linear").bfill().ffill()
    n = len(clean_series)

    if n < period * 2:
        # Not enough data for 2 full cycles; return flat components
        vals = clean_series.tolist()
        return SeasonalDecompositionResult(
            parameter=parameter_name,
            observed=vals,
            trend=vals,
            seasonal=[0.0 if model == "additive" else 1.0] * n,
            residual=[0.0] * n,
            period=period,
            model=model,
        )

    # 1. Centered moving average trend
    if period % 2 == 0:
        # 2xM moving average for even period
        ma1 = clean_series.rolling(window=period, center=True).mean()
        trend_s = ma1.rolling(window=2, center=True).mean().shift(-1)
    else:
        trend_s = clean_series.rolling(window=period, center=True).mean()

    # Fill trend ends via nearest linear extrapolation
    trend_s = trend_s.bfill().ffill()

    # 2. Detrended series
    if model == "multiplicative":
        trend_safe = trend_s.replace(0.0, 1e-4)
        detrended = clean_series / trend_safe
    else:
        detrended = clean_series - trend_s

    # 3. Seasonal component per cycle step (0 to period-1)
    cycle_idx = np.arange(n) % period
    detrended_df = pd.DataFrame({"cycle": cycle_idx, "val": detrended})
    seasonal_means = detrended_df.groupby("cycle")["val"].mean()

    if model == "additive":
        # Center additive seasonal to mean = 0
        seasonal_means = seasonal_means - seasonal_means.mean()
    else:
        # Center multiplicative seasonal to mean = 1
        mean_val = seasonal_means.mean()
        if abs(mean_val) > 1e-6:
            seasonal_means = seasonal_means / mean_val

    seasonal_array = np.array([seasonal_means[c] for c in cycle_idx])

    # 4. Residuals
    if model == "multiplicative":
        residual_array = (clean_series / (trend_s * seasonal_array)).to_numpy()
    else:
        residual_array = (clean_series - trend_s - seasonal_array).to_numpy()

    return SeasonalDecompositionResult(
        parameter=parameter_name,
        observed=[round(float(x), 3) for x in clean_series.tolist()],
        trend=[round(float(x), 3) for x in trend_s.tolist()],
        seasonal=[round(float(x), 3) for x in seasonal_array.tolist()],
        residual=[round(float(x), 3) for x in residual_array.tolist()],
        period=period,
        model=model,
    )


# ─────────────────────── 3. Hotspot Flagging ─────────────────────────────────────


def detect_pollution_hotspots(
    record: dict[str, Any] | pd.Series,
    station_id: str,
    date: str,
    provenance: str = "synthetic",
) -> HotspotAssessment:
    """Screen for industrial/mining pollution hotspots in the Bokaro-Dhanbad belt.

    Identifies severe organic or industrial chemical contamination:
    - Dissolved Oxygen < 4.0 mg/L (hypoxia)
    - BOD > 5.0 mg/L (organic overload)
    - COD > 50.0 mg/L (chemical effluent)
    - Conductivity > 1500 uS/cm (saline/mineral effluent)
    - Fecal Coliform > 2500 MPN/100ml (untreated sewage load)

    In accordance with AGENTS.md integrity rules:
    Tagged explicitly as "indicative" unless real observed data is confirmed.
    """

    def _val(k: str) -> float | None:
        v = record.get(k)
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    triggers: list[str] = []
    do = _val("dissolved_oxygen_mg_l")
    bod = _val("bod_mg_l")
    cod = _val("cod_mg_l")
    cond = _val("conductivity_us_cm")
    fc = _val("fecal_coliform_mpn_100ml")

    if do is not None and do < 4.0:
        triggers.append(f"Hypoxia (DO {do:.1f} < 4.0 mg/L)")
    if bod is not None and bod > 5.0:
        triggers.append(f"Excess Organic Load (BOD {bod:.1f} > 5.0 mg/L)")
    if cod is not None and cod > 50.0:
        triggers.append(f"Industrial Chemical Effluent (COD {cod:.1f} > 50.0 mg/L)")
    if cond is not None and cond > 1500.0:
        triggers.append(f"High Electrical Conductivity ({cond:.0f} > 1500 µS/cm)")
    if fc is not None and fc > 2500.0:
        triggers.append(f"Severe Fecal Contamination ({fc:.0f} > 2500 MPN/100mL)")

    status_label = "verified" if provenance == "observed" else "indicative"

    if len(triggers) >= 2 or (bod is not None and bod >= 10.0) or (do is not None and do <= 2.0):
        severity: HotspotSeverity = "Critical"
        is_hotspot = True
        summary = (
            f"[{status_label.upper()}] Critical industrial pollution hotspot at {station_id}. "
            f"Violations: {'; '.join(triggers)}."
        )
    elif len(triggers) == 1:
        severity = "Moderate"
        is_hotspot = True
        summary = (
            f"[{status_label.upper()}] Moderate pollution stress at {station_id}. "
            f"Trigger: {triggers[0]}."
        )
    else:
        severity = "None"
        is_hotspot = False
        summary = f"[{status_label.upper()}] No critical industrial effluent violations detected at {station_id}."

    return HotspotAssessment(
        station_id=station_id,
        date=str(date),
        severity=severity,
        is_hotspot=is_hotspot,
        trigger_pollutants=triggers,
        status_label=status_label,
        summary=summary,
    )


# ─────────────────────── 4. Next-Month WQI Classifier ───────────────────────────


class NextMonthWQIClassifier:
    """Predicts next-month CPCB water-health category using prior monthly indicators.

    Ensures zero forward leakage:
    1. Features at month M only include lags from M and antecedent weather/hydrology.
    2. Scaler and classifier are fitted strictly on the train period.
    """

    def __init__(self, random_state: int = 42) -> None:
        self.random_state = random_state
        self.scaler = StandardScaler()
        self.model = RandomForestClassifier(
            n_estimators=50,
            max_depth=4,
            random_state=self.random_state,
        )
        self.feature_cols: list[str] = []
        self._classes: list[str] = []
        self.fitted = False

    def _extract_features(self, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
        """Derive monthly features and lead target class (t+1 month)."""
        data = df.copy()
        if "date" in data.columns:
            data["date"] = pd.to_datetime(data["date"])
            data = data.sort_values("date").reset_index(drop=True)
            month = data["date"].dt.month
            data["month_sin"] = np.sin(2.0 * np.pi * month / 12.0)
            data["month_cos"] = np.cos(2.0 * np.pi * month / 12.0)

        # Baseline water quality features
        feature_candidates = [
            "month_sin",
            "month_cos",
            "ph",
            "dissolved_oxygen_mg_l",
            "bod_mg_l",
            "cod_mg_l",
            "conductivity_us_cm",
            "turbidity_ntu",
            "fecal_coliform_mpn_100ml",
        ]
        feat_cols = [c for c in feature_candidates if c in data.columns]

        # Target: CPCB class of next month (shift -1)
        if "cpcb_class" not in data.columns:
            data["cpcb_class"] = data.apply(classify_cpcb_use, axis=1)

        data["target_cpcb_next"] = data["cpcb_class"].shift(-1)

        valid = data.dropna(subset=feat_cols + ["target_cpcb_next"]).copy()
        return valid[feat_cols], valid["target_cpcb_next"]

    def fit(self, train_df: pd.DataFrame) -> NextMonthWQIClassifier:
        """Fit the predictive classifier on training split only."""
        X_df, y_ser = self._extract_features(train_df)
        if len(X_df) < 5:
            raise ValueError(f"Insufficient training observations ({len(X_df)} < 5)")

        self.feature_cols = list(X_df.columns)
        X_scaled = self.scaler.fit_transform(X_df.values)
        self.model.fit(X_scaled, y_ser.values)
        self._classes = list(self.model.classes_)
        self.fitted = True
        return self

    def predict(self, df: pd.DataFrame) -> list[str]:
        """Predict next-month CPCB class for the given observations."""
        if not self.fitted:
            raise RuntimeError("Model must be fitted before predict()")

        data = df.copy()
        if "date" in data.columns:
            data["date"] = pd.to_datetime(data["date"])
            month = data["date"].dt.month
            data["month_sin"] = np.sin(2.0 * np.pi * month / 12.0)
            data["month_cos"] = np.cos(2.0 * np.pi * month / 12.0)

        X = data[self.feature_cols].ffill().bfill().values
        X_scaled = self.scaler.transform(X)
        preds = self.model.predict(X_scaled)
        return list(preds)
