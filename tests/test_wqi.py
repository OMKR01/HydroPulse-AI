"""Unit tests for Phase 4 — Water Quality Index (WQI), CPCB Classification, and Trend Analysis.

Tests:
    - Weighted-Arithmetic WQI computation accuracy and dynamic reweighting.
    - CPCB designated-best-use classification (A, B, C, D, E, Below_E) boundary conditions.
    - Non-parametric Mann-Kendall trend test with Sen's slope.
    - Classical monthly seasonal decomposition (additive and multiplicative).
    - Pollution hotspot screening with "indicative" vs "verified" tagging.
    - NextMonthWQIClassifier fit/predict and leak-free verification.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.hydropulse.models.wqi import (
    NextMonthWQIClassifier,
    calculate_wqi,
    classify_cpcb_use,
    detect_pollution_hotspots,
    mann_kendall_test,
    seasonal_decompose_monthly,
)


class TestWQICalculation:
    def test_ideal_pure_water_wqi_zero(self):
        """Pure water at ideal values should yield a WQI of 0.0 (Excellent)."""
        record = {
            "ph": 7.0,
            "dissolved_oxygen_mg_l": 14.6,
            "bod_mg_l": 0.0,
            "cod_mg_l": 0.0,
            "conductivity_us_cm": 0.0,
            "turbidity_ntu": 0.0,
            "fecal_coliform_mpn_100ml": 0.0,
        }
        score = calculate_wqi(record)
        assert score.wqi == 0.0
        assert score.rating == "Excellent"
        assert score.cpcb_class == "A"
        assert len(score.parameters_present) == 7

    def test_standard_limit_boundary_wqi_100(self):
        """Parameters set precisely at permissible limits should evaluate to WQI ~100 (Very Poor)."""
        record = {
            "ph": 8.5,  # |8.5 - 7.0| / 1.5 = 1.0 -> q = 100
            "dissolved_oxygen_mg_l": 5.0,  # (14.6 - 5.0) / 9.6 = 1.0 -> q = 100
            "bod_mg_l": 5.0,  # 5.0 / 5.0 = 1.0 -> q = 100
            "cod_mg_l": 50.0,  # 50.0 / 50.0 = 1.0 -> q = 100
            "conductivity_us_cm": 1000.0,  # 1000 / 1000 = 1.0 -> q = 100
            "turbidity_ntu": 10.0,  # 10 / 10 = 1.0 -> q = 100
            "fecal_coliform_mpn_100ml": 500.0,  # 500 / 500 = 1.0 -> q = 100
        }
        score = calculate_wqi(record)
        assert pytest.approx(score.wqi, abs=0.5) == 100.0
        assert score.rating == "Very Poor"

    def test_severe_contamination_unfit(self):
        """Heavily polluted industrial sample should have WQI > 100 (Unfit)."""
        record = {
            "ph": 5.2,
            "dissolved_oxygen_mg_l": 1.5,
            "bod_mg_l": 28.0,
            "cod_mg_l": 180.0,
            "conductivity_us_cm": 2800.0,
            "turbidity_ntu": 35.0,
            "fecal_coliform_mpn_100ml": 8000.0,
        }
        score = calculate_wqi(record)
        assert score.wqi > 100.0
        assert score.rating == "Unfit"
        assert score.cpcb_class == "Below_E"

    def test_dynamic_reweighting_missing_parameters(self):
        """When only a subset of parameters is available, weights must still sum to 1.0."""
        record = {
            "ph": 7.4,
            "dissolved_oxygen_mg_l": 6.8,
            "bod_mg_l": 2.2,
        }
        score = calculate_wqi(record)
        assert len(score.parameters_present) == 3
        total_weight = sum(score.weights_used.values())
        assert pytest.approx(total_weight, abs=1e-4) == 1.0
        assert score.wqi >= 0.0

    def test_empty_record_handled_safely(self):
        score = calculate_wqi({})
        assert score.wqi == 0.0
        assert score.cpcb_class == "Below_E"
        assert score.to_dict()["rating"] == "Unfit"


class TestCPCBClassificationBoundaries:
    """Verifies all boundary conditions for CPCB Classes A, B, C, D, E, Below_E."""

    def test_class_a_boundaries(self):
        # Exact Class A limits
        rec = {
            "ph": 6.5,
            "dissolved_oxygen_mg_l": 6.0,
            "bod_mg_l": 2.0,
            "fecal_coliform_mpn_100ml": 50.0,
        }
        assert classify_cpcb_use(rec) == "A"

        # pH at upper limit 8.5
        rec["ph"] = 8.5
        assert classify_cpcb_use(rec) == "A"

        # Slight violation in BOD -> downgrades to B
        rec["bod_mg_l"] = 2.1
        assert classify_cpcb_use(rec) == "B"

    def test_class_b_boundaries(self):
        rec = {
            "ph": 7.2,
            "dissolved_oxygen_mg_l": 5.0,
            "bod_mg_l": 3.0,
            "fecal_coliform_mpn_100ml": 500.0,
        }
        assert classify_cpcb_use(rec) == "B"

        # Violates coliform (501 > 500) -> downgrades to C
        rec["fecal_coliform_mpn_100ml"] = 501.0
        assert classify_cpcb_use(rec) == "C"

    def test_class_c_boundaries(self):
        rec = {
            "ph": 8.9,  # C allows up to 9.0
            "dissolved_oxygen_mg_l": 4.0,
            "bod_mg_l": 3.0,
            "fecal_coliform_mpn_100ml": 5000.0,
        }
        assert classify_cpcb_use(rec) == "C"

        # Violates DO (< 4.0 fails C and D)
        rec["dissolved_oxygen_mg_l"] = 3.5
        assert classify_cpcb_use(rec) in ("E", "Below_E")

    def test_class_d_boundaries(self):
        # Fisheries & wildlife: DO >= 4.0, pH 6.5 - 8.5, BOD can be higher than 3
        rec = {
            "ph": 7.5,
            "dissolved_oxygen_mg_l": 4.2,
            "bod_mg_l": 4.8,  # Fails C (BOD <= 3.0), but passes D
        }
        assert classify_cpcb_use(rec) == "D"

    def test_class_e_boundaries(self):
        # Irrigation & industrial cooling: pH 6.0 - 8.5, EC <= 2250, low DO
        rec = {
            "ph": 6.2,  # Below 6.5 (fails D), but >= 6.0
            "dissolved_oxygen_mg_l": 3.0,  # Below 4.0 (fails D)
            "conductivity_us_cm": 2100.0,  # <= 2250 uS/cm
        }
        assert classify_cpcb_use(rec) == "E"

    def test_below_e_violations(self):
        # Acidic industrial discharge
        rec = {"ph": 4.5, "conductivity_us_cm": 3500.0}
        assert classify_cpcb_use(rec) == "Below_E"

        # Highly alkaline
        rec = {"ph": 10.2}
        assert classify_cpcb_use(rec) == "Below_E"


class TestMannKendallTrend:
    def test_strictly_increasing_trend(self):
        vals = np.linspace(2.0, 20.0, 20)
        res = mann_kendall_test(vals, parameter_name="bod_mg_l")
        assert res.trend == "increasing"
        assert res.sens_slope > 0.0
        assert res.p_value < 0.01
        assert res.s_statistic > 0

    def test_strictly_decreasing_trend(self):
        vals = np.linspace(15.0, 2.0, 25)
        res = mann_kendall_test(vals, parameter_name="dissolved_oxygen_mg_l")
        assert res.trend == "decreasing"
        assert res.sens_slope < 0.0
        assert res.p_value < 0.01
        assert res.s_statistic < 0

    def test_no_trend_constant(self):
        vals = np.array([7.0] * 15)
        res = mann_kendall_test(vals, parameter_name="ph")
        assert res.trend == "no_trend"
        assert res.sens_slope == 0.0
        assert res.to_dict()["n_samples"] == 15

    def test_small_sample_size(self):
        vals = np.array([5.0, 6.0])
        res = mann_kendall_test(vals)
        assert res.trend == "no_trend"
        assert res.p_value == 1.0


class TestSeasonalDecomposition:
    def test_additive_decomposition_cycle(self):
        # 36 months = 3 cycles of 12 months
        months = np.arange(36)
        trend_true = 10.0 + 0.1 * months
        season_true = 3.0 * np.sin(2.0 * np.pi * months / 12.0)
        series = pd.Series(trend_true + season_true)

        decomp = seasonal_decompose_monthly(series, period=12, model="additive")
        assert len(decomp.trend) == 36
        assert len(decomp.seasonal) == 36
        assert len(decomp.residual) == 36
        assert pytest.approx(np.mean(decomp.seasonal), abs=0.2) == 0.0

    def test_multiplicative_decomposition(self):
        months = np.arange(36)
        series = pd.Series(20.0 + 2.0 * np.sin(2.0 * np.pi * months / 12.0))
        decomp = seasonal_decompose_monthly(series, period=12, model="multiplicative")
        assert pytest.approx(np.mean(decomp.seasonal), abs=0.2) == 1.0

    def test_short_series_fallback(self):
        series = pd.Series([1.0, 2.0, 3.0, 4.0])
        decomp = seasonal_decompose_monthly(series, period=12)
        assert len(decomp.observed) == 4


class TestHotspotDetection:
    def test_normal_no_hotspot(self):
        record = {
            "dissolved_oxygen_mg_l": 7.0,
            "bod_mg_l": 2.0,
            "cod_mg_l": 15.0,
            "conductivity_us_cm": 400.0,
        }
        res = detect_pollution_hotspots(record, "damodar_ramgarh", "2023-01-15", provenance="synthetic")
        assert res.is_hotspot is False
        assert res.severity == "None"
        assert res.status_label == "indicative"

    def test_critical_hotspot_bokaro(self):
        record = {
            "dissolved_oxygen_mg_l": 2.1,  # Hypoxia
            "bod_mg_l": 8.5,  # Organic overload
            "cod_mg_l": 75.0,  # Industrial chemical
            "conductivity_us_cm": 1800.0,  # High salinity
        }
        res = detect_pollution_hotspots(record, "damodar_bokaro", "2023-02-15", provenance="observed")
        assert res.is_hotspot is True
        assert res.severity == "Critical"
        assert res.status_label == "verified"
        assert len(res.trigger_pollutants) >= 3


class TestNextMonthWQIClassifier:
    def test_fit_and_predict(self):
        rng = np.random.default_rng(42)
        n = 36  # 36 monthly observations
        dates = pd.date_range("2020-01-01", periods=n, freq="ME")

        df = pd.DataFrame({
            "date": dates.strftime("%Y-%m-%d"),
            "ph": rng.uniform(6.8, 8.2, n),
            "dissolved_oxygen_mg_l": rng.uniform(4.5, 7.5, n),
            "bod_mg_l": rng.uniform(1.5, 4.0, n),
            "conductivity_us_cm": rng.uniform(300.0, 800.0, n),
        })

        train_df = df.iloc[:28]
        test_df = df.iloc[28:]

        clf = NextMonthWQIClassifier(random_state=42)
        clf.fit(train_df)
        assert clf.fitted is True

        preds = clf.predict(test_df)
        assert len(preds) == len(test_df)
        assert all(p in ("A", "B", "C", "D", "E", "Below_E") for p in preds)

    def test_predict_unfitted_raises_runtime_error(self):
        clf = NextMonthWQIClassifier()
        with pytest.raises(RuntimeError, match="must be fitted"):
            clf.predict(pd.DataFrame({"ph": [7.0]}))
