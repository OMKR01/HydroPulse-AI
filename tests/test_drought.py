"""Unit tests for Phase 4 — Drought and Low-Flow Monitoring.

Tests:
    - Low-flow threshold computation (Q90 / 10th percentile).
    - Low-flow stress boolean detector.
    - Combined meteorological and hydrological drought status evaluation.
    - 30-day forward drought outlook.
    - StationDroughtEvaluator lifecycle and leakage isolation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.hydropulse.models.drought import (
    StationDroughtEvaluator,
    compute_30d_drought_outlook,
    compute_low_flow_threshold,
    evaluate_drought_status,
    is_low_flow_stress,
)


class TestLowFlowThreshold:
    def test_compute_low_flow_exact_percentile(self):
        """Test that Q90 low flow corresponds to 10th percentile of uniform series."""
        # 100 values from 1 to 100
        vals = np.linspace(1.0, 100.0, 100)
        thresh = compute_low_flow_threshold(vals, quantile=0.10)
        # 10th percentile of [1, 100] is 10.9
        assert 10.0 <= thresh <= 11.5

    def test_compute_low_flow_series_with_nans(self):
        """Test computation with NaNs present in series."""
        vals = pd.Series([np.nan, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0] * 5)
        thresh = compute_low_flow_threshold(vals, quantile=0.10, min_samples=10)
        assert thresh > 0.0
        assert thresh <= 10.0

    def test_compute_low_flow_insufficient_samples(self):
        """Test fallback when sample size is below min_samples."""
        vals = pd.Series([10.0, 20.0, 30.0])
        thresh = compute_low_flow_threshold(vals, min_samples=10)
        assert thresh >= 0.0

    def test_compute_low_flow_empty(self):
        """Test zero return on empty input."""
        thresh = compute_low_flow_threshold(np.array([]))
        assert thresh == 0.0


class TestLowFlowStress:
    def test_is_low_flow_stress(self):
        assert is_low_flow_stress(5.0, 10.0) is True
        assert is_low_flow_stress(10.0, 10.0) is False
        assert is_low_flow_stress(15.0, 10.0) is False
        assert is_low_flow_stress(None, 10.0) is False
        assert is_low_flow_stress(np.nan, 10.0) is False


class TestDroughtStatusEvaluation:
    def test_extreme_drought_from_spi(self):
        res = evaluate_drought_status(
            station_id="test_station",
            date="2023-05-01",
            discharge=25.0,
            low_flow_threshold=10.0,
            spi_30d=-2.2,
        )
        assert res.severity == "Extreme"
        assert res.composite_score >= 0.8
        assert res.is_low_flow is False
        assert "Extreme" in res.advisory_message

    def test_extreme_compound_drought(self):
        res = evaluate_drought_status(
            station_id="test_station",
            date="2023-05-01",
            discharge=5.0,
            low_flow_threshold=10.0,
            spi_30d=-1.6,
        )
        assert res.severity == "Extreme"
        assert res.is_low_flow is True
        assert "Compound" in res.primary_stressor

    def test_severe_drought(self):
        res = evaluate_drought_status(
            station_id="test_station",
            date="2023-05-01",
            discharge=20.0,
            low_flow_threshold=10.0,
            spi_90d=-1.65,
        )
        assert res.severity == "Severe"

    def test_moderate_drought_hydrological_only(self):
        # SPI is normal, but river is in severe low flow
        res = evaluate_drought_status(
            station_id="test_station",
            date="2023-05-01",
            discharge=4.0,
            low_flow_threshold=10.0,
            spi_30d=0.2,
        )
        assert res.severity == "Moderate"
        assert res.is_low_flow is True

    def test_watch_approaching_low_flow(self):
        res = evaluate_drought_status(
            station_id="test_station",
            date="2023-05-01",
            discharge=12.0,  # 10 < 12 < 1.5 * 10
            low_flow_threshold=10.0,
            spi_30d=0.0,
        )
        assert res.severity == "Watch"

    def test_normal_conditions(self):
        res = evaluate_drought_status(
            station_id="test_station",
            date="2023-07-15",
            discharge=50.0,
            low_flow_threshold=10.0,
            spi_30d=0.5,
            spi_90d=0.8,
        )
        assert res.severity == "Normal"
        assert res.composite_score <= 0.20
        assert res.to_dict()["station_id"] == "test_station"


class TestDroughtOutlook:
    def test_improving_outlook_on_heavy_rain(self):
        current = evaluate_drought_status(
            station_id="test_station",
            date="2023-06-01",
            discharge=5.0,
            low_flow_threshold=10.0,
            spi_30d=-1.8,
        )
        # Normal monthly 120mm -> expected 7d is 28mm. Forecast is 60mm
        outlook = compute_30d_drought_outlook(
            station_id="test_station",
            as_of_date="2023-06-01",
            current_assessment=current,
            forecast_precip_7d=60.0,
            normal_monthly_precip=120.0,
            forecast_discharge_7d=[8.0, 12.0, 15.0, 18.0, 20.0, 25.0, 25.0],
        )
        assert outlook.outlook_trend == "Improving"
        assert outlook.projected_deficit_pct < 0.0  # Surplus
        assert "alleviate" in outlook.summary

    def test_persistent_low_flow_outlook(self):
        current = evaluate_drought_status(
            station_id="test_station",
            date="2023-04-01",
            discharge=4.0,
            low_flow_threshold=10.0,
            spi_30d=-1.5,
        )
        outlook = compute_30d_drought_outlook(
            station_id="test_station",
            as_of_date="2023-04-01",
            current_assessment=current,
            forecast_precip_7d=2.0,
            normal_monthly_precip=30.0,
            forecast_discharge_7d=[3.0, 3.5, 4.0, 4.0, 4.2, 4.5, 4.0],
        )
        assert outlook.outlook_trend == "Persistent Low Flow"
        assert outlook.forecast_low_flow_days_7d == 7
        assert outlook.to_dict()["current_severity"] == "Extreme"


class TestStationDroughtEvaluator:
    def test_fit_and_transform_pipeline(self):
        rng = np.random.default_rng(42)
        n = 200
        dates = pd.date_range("2020-01-01", periods=n, freq="D")
        discharge = rng.uniform(5.0, 100.0, n)
        # Inject artificial low flow
        discharge[:20] = 3.0

        df = pd.DataFrame({
            "date": dates.strftime("%Y-%m-%d"),
            "discharge_m3s": discharge,
            "spi_30d": rng.normal(0, 1, n),
        })

        evaluator = StationDroughtEvaluator(station_id="damodar_ramgarh", low_flow_quantile=0.10)
        evaluator.fit(df)
        assert evaluator.threshold is not None
        assert evaluator.threshold > 0.0

        transformed = evaluator.transform(df)
        assert "is_low_flow" in transformed.columns
        assert "low_flow_threshold" in transformed.columns
        assert "drought_severity" in transformed.columns
        assert "drought_composite_score" in transformed.columns
        assert transformed["is_low_flow"].dtype == bool

    def test_transform_unfitted_raises_runtime_error(self):
        evaluator = StationDroughtEvaluator(station_id="test")
        df = pd.DataFrame({"discharge_m3s": [10.0, 20.0]})
        with pytest.raises(RuntimeError, match="must be fit"):
            evaluator.transform(df)

    def test_fit_missing_column_raises_value_error(self):
        evaluator = StationDroughtEvaluator(station_id="test")
        df = pd.DataFrame({"flow": [10.0, 20.0]})
        with pytest.raises(ValueError, match="not found in dataframe"):
            evaluator.fit(df, discharge_col="discharge_m3s")
