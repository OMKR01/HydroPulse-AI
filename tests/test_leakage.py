"""Formal time-series leakage verification test suite.

Proves that for any cutoff time T, features computed at row t <= T are strictly invariant
to arbitrary perturbations or extreme values introduced into future rows (t > T).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.hydropulse.features.cleaning import (
    TrainOnlyScaler,
    detect_gaps,
    detect_outliers,
    fill_small_gaps,
)
from src.hydropulse.features.lags import (
    compute_upstream_features,
    extract_all_features,
)
from src.hydropulse.features.spi import (
    classify_spi,
    compute_spi,
    fit_spi_gamma,
    transform_accumulated_to_spi,
)
from src.hydropulse.features.static_attrs import add_static_attributes, get_static_attributes


@pytest.fixture
def synthetic_timeseries() -> pd.DataFrame:
    """Generate a 100-day realistic hydro-meteorological series."""
    rng = np.random.default_rng(seed=42)
    dates = pd.date_range("2023-01-01", periods=100, freq="D")

    # Precipitation with intermittent dry days
    precip = rng.exponential(scale=15.0, size=100)
    precip[rng.uniform(size=100) < 0.4] = 0.0

    # Base discharge responding to lagged rain
    discharge = 20.0 + 0.5 * np.roll(precip, 1) + rng.normal(0, 2, size=100)
    discharge = np.maximum(discharge, 5.0)

    df = pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "station_id": "test_station",
            "precipitation_mm": np.round(precip, 2),
            "discharge_m3s": np.round(discharge, 2),
            "temperature_max_c": rng.uniform(25.0, 38.0, size=100),
            "temperature_min_c": rng.uniform(15.0, 24.0, size=100),
            "provenance": "model_reanalysis",
        }
    )
    return df


def test_no_future_leakage_in_feature_extraction(synthetic_timeseries: pd.DataFrame):
    """Perturb all observations after cutoff T=50 and assert features at t <= 50 are unchanged."""
    df_original = synthetic_timeseries.copy()
    cutoff_idx = 50

    # 1. Compute baseline features on untouched series
    feats_orig = extract_all_features(df_original)

    # 2. Perturb future rows with massive extreme values
    df_perturbed = df_original.copy()
    df_perturbed.loc[df_perturbed.index > cutoff_idx, "precipitation_mm"] += 2500.0
    df_perturbed.loc[df_perturbed.index > cutoff_idx, "discharge_m3s"] += 50000.0

    # 3. Compute features on future-perturbed series
    feats_pert = extract_all_features(df_perturbed)

    # Select all engineered feature columns
    engineered_cols = [
        c
        for c in feats_orig.columns
        if c
        not in (
            "date",
            "station_id",
            "provenance",
            "precipitation_mm",
            "discharge_m3s",
            "temperature_max_c",
            "temperature_min_c",
        )
    ]

    assert len(engineered_cols) > 0, "No engineered feature columns found!"

    # 4. Assert exact equality for all rows up to and including cutoff
    for col in engineered_cols:
        orig_slice = feats_orig.loc[:cutoff_idx, col].to_numpy()
        pert_slice = feats_pert.loc[:cutoff_idx, col].to_numpy()

        # Both slices must have identical NaN patterns and identical numerical values
        np.testing.assert_allclose(
            orig_slice,
            pert_slice,
            equal_nan=True,
            err_msg=f"Data leakage detected in feature column: {col}",
        )


def test_no_future_leakage_in_spi(synthetic_timeseries: pd.DataFrame):
    """Verify that SPI computed on shifted precipitation is invariant to future rainfall."""
    df_original = synthetic_timeseries.copy()
    cutoff_idx = 60

    spi_orig = compute_spi(df_original, windows=(30, 90))

    df_perturbed = df_original.copy()
    df_perturbed.loc[df_perturbed.index > cutoff_idx, "precipitation_mm"] += 9999.0

    spi_pert = compute_spi(df_perturbed, windows=(30, 90))

    for w in (30, 90):
        col = f"spi_{w}d"
        orig_vals = spi_orig.loc[:cutoff_idx, col].to_numpy()
        pert_vals = spi_pert.loc[:cutoff_idx, col].to_numpy()

        np.testing.assert_allclose(
            orig_vals,
            pert_vals,
            equal_nan=True,
            err_msg=f"Future leakage detected in {col}",
        )


def test_train_only_scaler_isolation(synthetic_timeseries: pd.DataFrame):
    """Verify TrainOnlyScaler parameters fit strictly on train split without test contamination."""
    df = synthetic_timeseries.copy()
    train_df = df.iloc[:50]
    test_df = df.iloc[50:]

    scaler = TrainOnlyScaler(method="standard")
    scaler.fit(train_df, feature_cols=["precipitation_mm", "discharge_m3s"])

    # Center must equal training mean
    assert np.isclose(scaler.center_["discharge_m3s"], train_df["discharge_m3s"].mean())
    assert not np.isclose(scaler.center_["discharge_m3s"], df["discharge_m3s"].mean())

    # Transform test set using train statistics
    scaled_test = scaler.transform(test_df)
    assert "discharge_m3s_scaled" in scaled_test.columns

    # Inverse transform recovers original test values
    inverted_test = scaler.inverse_transform(scaled_test)
    np.testing.assert_allclose(
        inverted_test["discharge_m3s"], test_df["discharge_m3s"], rtol=1e-5
    )


def test_upstream_feature_leakage(synthetic_timeseries: pd.DataFrame):
    """Verify upstream station propagation does not look ahead."""
    target_df = synthetic_timeseries.copy()
    upstream_df = synthetic_timeseries.copy()
    cutoff_idx = 45

    res_orig = compute_upstream_features(target_df, upstream_df)

    upstream_perturbed = upstream_df.copy()
    upstream_perturbed.loc[upstream_perturbed.index > cutoff_idx, "discharge_m3s"] += 8000.0

    res_pert = compute_upstream_features(target_df, upstream_perturbed)

    np.testing.assert_allclose(
        res_orig.loc[:cutoff_idx, "upstream_discharge_lag_1"].to_numpy(),
        res_pert.loc[:cutoff_idx, "upstream_discharge_lag_1"].to_numpy(),
        equal_nan=True,
    )


def test_outlier_detection_non_destructive(synthetic_timeseries: pd.DataFrame):
    """Verify outliers are flagged rather than dropped."""
    df = synthetic_timeseries.copy()
    df.loc[10, "precipitation_mm"] = -10.0  # Negative
    df.loc[20, "precipitation_mm"] = 950.0  # Physical max
    df.loc[30, "discharge_m3s"] = -5.0  # Negative flow

    cleaned = detect_outliers(df)
    assert len(cleaned) == len(df), "Records were improperly dropped!"
    assert cleaned.loc[10, "is_outlier_precip"]
    assert cleaned.loc[20, "is_outlier_precip"]
    assert cleaned.loc[30, "is_outlier_discharge"]
    assert "negative_rainfall" in cleaned.loc[10, "outlier_reason"]


def test_gap_detection_and_interpolation():
    """Verify gap detection and short-gap filling flags is_interpolated."""
    dates = ["2023-01-01", "2023-01-02", "2023-01-05", "2023-01-06"]  # 2-day gap (Jan 3, Jan 4)
    df = pd.DataFrame(
        {
            "date": dates,
            "station_id": "test",
            "precipitation_mm": [5.0, 10.0, 20.0, 25.0],
            "provenance": "observed",
        }
    )

    gaps = detect_gaps(df)
    assert len(gaps) == 1
    assert gaps[0]["gap_days"] == 2

    filled = fill_small_gaps(df, max_gap_days=3)
    assert len(filled) == 6
    interpolated_rows = filled[filled["is_interpolated"]]
    assert len(interpolated_rows) == 2
    assert all(interpolated_rows["provenance"] == "interpolated")


def test_spi_classification_categories():
    """Verify boundary conditions for SPI drought categories."""
    assert classify_spi(2.5) == "Extremely Wet"
    assert classify_spi(1.6) == "Very Wet"
    assert classify_spi(1.2) == "Moderately Wet"
    assert classify_spi(0.1) == "Near Normal"
    assert classify_spi(-1.2) == "Moderately Dry"
    assert classify_spi(-1.8) == "Severely Dry"
    assert classify_spi(-2.4) == "Extremely Dry"
    assert classify_spi(None) is None


def test_static_attributes_lookup():
    """Verify static catchment attributes are retrieved correctly."""
    attrs = get_static_attributes("damodar_ramgarh")
    assert attrs["elevation_m"] == 330.0
    assert attrs["stream_order"] == 4

    df = pd.DataFrame({"date": ["2023-01-01"], "precipitation_mm": [10.0]})
    df_with_static = add_static_attributes(df, "damodar_ramgarh")
    assert df_with_static["static_elevation_m"].iloc[0] == 330.0


def test_spi_with_reference_df(synthetic_timeseries: pd.DataFrame):
    """Verify compute_spi with explicit reference_df fits fixed gamma parameters."""
    train_df = synthetic_timeseries.iloc[:50].copy()
    test_df = synthetic_timeseries.iloc[50:].copy()

    res = compute_spi(test_df, reference_df=train_df, windows=(30,))
    assert "spi_30d" in res.columns
    assert "spi_30d_category" in res.columns
    assert len(res) == len(test_df)


def test_fit_spi_gamma_direct():
    """Verify direct fit_spi_gamma and transform_accumulated_to_spi."""
    data = np.array([0.0, 0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 45.0, 50.0])
    alpha, beta, q = fit_spi_gamma(data)
    assert alpha > 0
    assert beta > 0
    assert 0.0 < q < 1.0

    spi_vals = transform_accumulated_to_spi(data, alpha, beta, q)
    assert len(spi_vals) == len(data)
    assert not np.isnan(spi_vals[2])

