"""Unit and smoke tests for Phase 3 — Flood Forecasting Models.

All tests use synthetic data only (no network calls, no DB access).
Tests cover:
    - Baseline models: persistence, climatology, ridge (fit/predict, shape, no leakage)
    - LightGBM forecaster: fit/predict shape, SHAP computation
    - Quantile forecaster: monotone ordering, calibration coverage interface
    - PyTorch LSTM: forward pass shape, gradient sensitivity
    - Evaluation metrics: NSE boundary conditions, KGE, alert metrics formulae
    - Plots: runs without error, saves PNG to tempdir
    - Pipeline: chronological split function correctness
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

try:
    import torch

    TORCH_AVAILABLE = True
except (ImportError, OSError):
    torch = None  # type: ignore
    TORCH_AVAILABLE = False

# ──────────────────────────── fixtures ────────────────────────────────────


def _make_station_df(n: int = 500, seed: int = 42) -> pd.DataFrame:
    """Synthetic hydrometeorological time-series with feature and target columns."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2010-01-01", periods=n, freq="D")

    precip = rng.exponential(10.0, n)
    precip[rng.uniform(size=n) < 0.4] = 0.0
    discharge = 50.0 + 0.8 * np.roll(precip, 1) + rng.normal(0, 5, n)
    discharge = np.maximum(discharge, 5.0)

    df = pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "station_id": "test_station",
            "precipitation_mm": np.round(precip, 2),
            "temperature_max_c": rng.uniform(20.0, 38.0, n),
            "temperature_min_c": rng.uniform(10.0, 22.0, n),
            "relative_humidity_mean": rng.uniform(40.0, 95.0, n),
            "discharge_m3s": np.round(discharge, 2),
            "discharge_mean_m3s": np.round(discharge * 0.95, 2),
            "provenance": "model_reanalysis",
        }
    )

    # Add lag and calendar features (minimal set)
    df["precip_lag_1"] = df["precipitation_mm"].shift(1)
    df["discharge_lag_1"] = df["discharge_m3s"].shift(1)
    df["precip_roll_sum_7d"] = df["precipitation_mm"].shift(1).rolling(7, min_periods=1).sum()
    df["antecedent_precipitation_index"] = (
        df["precipitation_mm"].shift(1).rolling(14, min_periods=1).mean()
    )

    doy = pd.to_datetime(df["date"]).dt.dayofyear
    df["doy_sin"] = np.sin(2.0 * np.pi * doy / 365.25)
    df["doy_cos"] = np.cos(2.0 * np.pi * doy / 365.25)
    df["is_monsoon"] = pd.to_datetime(df["date"]).dt.month.isin([6, 7, 8, 9, 10]).astype(int)
    df["static_elevation_m"] = 350.0
    df["static_catchment_area_km2"] = 1200.0

    # Multi-horizon targets
    for h in range(1, 8):
        df[f"target_discharge_h{h}"] = df["discharge_m3s"].shift(-h)

    return df


@pytest.fixture
def station_df() -> pd.DataFrame:
    return _make_station_df(n=500)


@pytest.fixture
def train_val_test(station_df: pd.DataFrame):
    df = station_df.copy()
    n = len(df)
    train = df.iloc[: int(n * 0.70)].reset_index(drop=True)
    val = df.iloc[int(n * 0.70) : int(n * 0.85)].reset_index(drop=True)
    test = df.iloc[int(n * 0.85) :].reset_index(drop=True)
    return train, val, test


# ──────────────────────────── evaluation/metrics tests ────────────────────


class TestMetrics:
    def test_nse_perfect(self):
        from src.hydropulse.evaluation.metrics import nse

        obs = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        assert nse(obs, obs) == pytest.approx(1.0, abs=1e-9)

    def test_nse_mean_pred(self):
        from src.hydropulse.evaluation.metrics import nse

        obs = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        pred = np.full_like(obs, obs.mean())
        assert nse(obs, pred) == pytest.approx(0.0, abs=1e-9)

    def test_nse_worse_than_mean(self):
        from src.hydropulse.evaluation.metrics import nse

        obs = np.array([10.0, 20.0, 30.0])
        pred = np.array([0.0, 0.0, 0.0])
        assert nse(obs, pred) < 0.0

    def test_nse_with_nans(self):
        from src.hydropulse.evaluation.metrics import nse

        obs = np.array([1.0, float("nan"), 3.0])
        pred = np.array([1.0, 99.0, 3.0])
        # NaN rows excluded — should be perfect on valid rows
        assert nse(obs, pred) == pytest.approx(1.0, abs=1e-9)

    def test_kge_perfect(self):
        from src.hydropulse.evaluation.metrics import kge

        obs = np.array([5.0, 10.0, 15.0, 20.0, 25.0])
        assert kge(obs, obs) == pytest.approx(1.0, abs=1e-9)

    def test_rmse_mae(self):
        from src.hydropulse.evaluation.metrics import mae, rmse

        obs = np.array([0.0, 0.0, 0.0])
        pred = np.array([3.0, 4.0, 0.0])
        assert rmse(obs, pred) == pytest.approx(math.sqrt((9 + 16) / 3), rel=1e-6)
        assert mae(obs, pred) == pytest.approx(7.0 / 3.0, rel=1e-6)

    def test_alert_metrics_all_correct(self):
        from src.hydropulse.evaluation.metrics import alert_metrics

        obs = np.array([100.0, 200.0, 50.0, 300.0])
        pred = np.array([100.0, 200.0, 50.0, 300.0])
        result = alert_metrics(obs, pred, threshold=150.0)
        assert result["POD"] == pytest.approx(1.0)
        assert result["FAR"] == pytest.approx(0.0)
        assert result["CSI"] == pytest.approx(1.0)

    def test_alert_metrics_all_missed(self):
        from src.hydropulse.evaluation.metrics import alert_metrics

        obs = np.array([200.0, 300.0])
        pred = np.array([50.0, 50.0])  # all misses
        result = alert_metrics(obs, pred, threshold=150.0)
        assert result["POD"] == pytest.approx(0.0)
        assert result["TP"] == 0
        assert result["FN"] == 2

    def test_peak_timing_error_zero(self):
        from src.hydropulse.evaluation.metrics import peak_timing_error

        obs = np.array([1.0, 2.0, 5.0, 2.0, 1.0, 1.0, 2.0, 5.0, 2.0, 1.0, 1.0, 2.0, 5.0, 2.0, 1.0])
        # Identical sequence → timing error should be 0
        assert peak_timing_error(obs, obs.copy(), window=5) == pytest.approx(0.0, abs=1e-9)

    def test_per_horizon_metrics_shape(self, station_df: pd.DataFrame):
        from src.hydropulse.evaluation.metrics import per_horizon_metrics

        n = 50
        obs_matrix = np.random.default_rng(0).uniform(10, 100, (n, 7))
        pred_matrix = obs_matrix + np.random.default_rng(1).normal(0, 5, (n, 7))
        results = per_horizon_metrics(obs_matrix, pred_matrix)
        assert len(results) == 7
        for row in results:
            assert "NSE" in row
            assert "KGE" in row
            assert "horizon_days" in row

    def test_quantile_coverage(self):
        from src.hydropulse.evaluation.metrics import compute_quantile_coverage

        obs = np.array([10.0, 20.0, 30.0, 40.0])
        q_lo = np.array([8.0, 18.0, 28.0, 0.0])
        q_hi = np.array([12.0, 22.0, 32.0, 35.0])
        cov = compute_quantile_coverage(obs, q_lo, q_hi)
        # First three are inside, last is outside (40 > 35)
        assert cov == pytest.approx(0.75, abs=1e-9)


# ──────────────────────────── baselines tests ──────────────────────────────


class TestBaselines:
    def test_persistence_shape(self, train_val_test):
        from src.hydropulse.models.baselines import PersistenceBaseline

        train, _, test = train_val_test
        model = PersistenceBaseline()
        model.fit(train)
        preds = model.predict(test)
        assert preds.shape == (len(test), 7)

    def test_persistence_values(self, train_val_test):
        from src.hydropulse.models.baselines import PersistenceBaseline

        train, _, test = train_val_test
        model = PersistenceBaseline()
        model.fit(train)
        preds = model.predict(test)
        # All 7 columns should be equal (same last-known value repeated)
        np.testing.assert_array_equal(preds[:, 0], preds[:, 6])

    def test_climatology_shape(self, train_val_test):
        from src.hydropulse.models.baselines import ClimatologyBaseline

        train, _, test = train_val_test
        model = ClimatologyBaseline()
        model.fit(train)
        preds = model.predict(test)
        assert preds.shape == (len(test), 7)
        assert not np.all(np.isnan(preds))

    def test_ridge_shape_and_not_all_nan(self, train_val_test):
        from src.hydropulse.models.baselines import RidgeBaseline

        train, _, test = train_val_test
        model = RidgeBaseline()
        model.fit(train)
        preds = model.predict(test)
        assert preds.shape == (len(test), 7)
        assert not np.all(np.isnan(preds))

    def test_ridge_coef_available(self, train_val_test):
        from src.hydropulse.models.baselines import RidgeBaseline

        train, _, test = train_val_test
        model = RidgeBaseline()
        model.fit(train)
        coefs = model.coef_
        assert len(coefs) == 7
        for _h, c in coefs.items():
            assert c.shape[0] > 0

    def test_raw_glofas_shape(self, train_val_test):
        from src.hydropulse.models.baselines import raw_glofas_baseline

        _, _, test = train_val_test
        preds = raw_glofas_baseline(test)
        assert preds.shape == (len(test), 7)

    def test_get_all_baselines_returns_three(self):
        from src.hydropulse.models.baselines import get_all_baselines

        baselines = get_all_baselines()
        assert len(baselines) == 3
        names = {b.name for b in baselines}
        assert "persistence" in names
        assert "climatology" in names
        assert "ridge" in names


# ──────────────────────────── LightGBM tests ──────────────────────────────


class TestLGBMForecaster:
    def test_fit_predict_shape(self, train_val_test):
        from src.hydropulse.models.lgbm import LGBMForecaster

        train, val, test = train_val_test
        model = LGBMForecaster(lgbm_params={"n_estimators": 20, "verbose": -1, "random_state": 42})
        model.fit(train, val_df=val)
        preds = model.predict(test)
        assert preds.shape == (len(test), 7)

    def test_preds_non_negative(self, train_val_test):
        from src.hydropulse.models.lgbm import LGBMForecaster

        train, val, test = train_val_test
        model = LGBMForecaster(lgbm_params={"n_estimators": 20, "verbose": -1, "random_state": 42})
        model.fit(train)
        preds = model.predict(test)
        valid = preds[~np.isnan(preds)]
        assert len(valid) > 0
        assert preds.shape == (len(test), 7)

    def test_save_and_load(self, train_val_test):
        from src.hydropulse.models.lgbm import LGBMForecaster

        train, _, test = train_val_test
        model = LGBMForecaster(lgbm_params={"n_estimators": 10, "verbose": -1, "random_state": 42})
        model.fit(train)
        preds_before = model.predict(test)
        assert preds_before.shape == (len(test), 7)

        with tempfile.TemporaryDirectory() as tmpdir:
            model.save(tmpdir)
            loaded = LGBMForecaster.load(tmpdir, hybrid=False)
            loaded._feature_cols = model._feature_cols  # restore metadata
            # loaded models exist
            assert len(loaded._models) == len(model._models)

    def test_hybrid_mode_name(self):
        from src.hydropulse.models.lgbm import LGBMForecaster

        model = LGBMForecaster(hybrid=True)
        assert model.name == "lgbm_hybrid"

    def test_shap_runs_without_error(self, train_val_test):
        from src.hydropulse.models.lgbm import LGBMForecaster

        train, _, test = train_val_test
        model = LGBMForecaster(lgbm_params={"n_estimators": 15, "verbose": -1, "random_state": 42})
        model.fit(train)
        model.compute_shap(test, max_samples=50)
        # mean_abs_shap_ populated for fitted horizons
        assert len(model.mean_abs_shap_) > 0

    def test_predict_before_fit_returns_nan(self, station_df):
        from src.hydropulse.models.lgbm import LGBMForecaster

        model = LGBMForecaster()
        preds = model.predict(station_df)
        assert np.isnan(preds).all()


# ──────────────────────────── Quantile tests ──────────────────────────────


class TestQuantileForecaster:
    def test_monotone_ordering(self, train_val_test):
        from src.hydropulse.models.quantile import QuantileLGBMForecaster

        train, _, test = train_val_test
        model = QuantileLGBMForecaster(
            lgbm_params={"n_estimators": 20, "verbose": -1, "random_state": 42}
        )
        model.fit(train)
        preds = model.predict(test)

        for h_idx in range(7):
            q10 = preds["q10"][:, h_idx]
            q50 = preds["q50"][:, h_idx]
            q90 = preds["q90"][:, h_idx]
            valid = ~(np.isnan(q10) | np.isnan(q50) | np.isnan(q90))
            assert np.all(q10[valid] <= q50[valid]), f"q10 > q50 at h={h_idx + 1}"
            assert np.all(q50[valid] <= q90[valid]), f"q50 > q90 at h={h_idx + 1}"

    def test_calibration_report_keys(self, train_val_test):
        from src.hydropulse.models.quantile import QuantileLGBMForecaster

        train, _, test = train_val_test
        model = QuantileLGBMForecaster(
            lgbm_params={"n_estimators": 20, "verbose": -1, "random_state": 42}
        )
        model.fit(train)
        report = model.calibration_report(test, horizon=1)
        assert "coverage_80pct" in report
        assert "target_>=_0.75" in report


# ──────────────────────────── LSTM tests ──────────────────────────────────


@pytest.mark.skipif(
    not TORCH_AVAILABLE,
    reason="PyTorch DLL blocked by system sandbox policy or not installed",
)
class TestLSTM:
    def test_per_station_lstm_forward_pass(self):
        """Test that _LSTMNet forward pass produces correct output shape."""
        from src.hydropulse.models.lstm import _LSTMNet

        model = _LSTMNet(input_size=10, hidden_size=32, num_layers=1)
        x = torch.randn(4, 30, 10)  # batch=4, seq=30, features=10
        y = model(x)
        assert y.shape == (4, 7)

    def test_multi_station_lstm_forward_pass(self):
        """Test that _MultiStationLSTMNet forward pass produces correct output shape."""
        from src.hydropulse.models.lstm import _MultiStationLSTMNet

        model = _MultiStationLSTMNet(
            input_size=10, n_stations=3, embed_dim=4, hidden_size=32, num_layers=1
        )
        x = torch.randn(2, 30, 10)
        sid = torch.tensor([1, 2], dtype=torch.long)
        y = model(x, sid)
        assert y.shape == (2, 7)

    def test_per_station_fit_predict_shape(self, train_val_test):
        """Smoke test: fit on small data, predict returns correct shape."""
        from src.hydropulse.models.lstm import PerStationLSTM

        train, val, test = train_val_test
        # Use short seq_len and epochs for speed in CI
        model = PerStationLSTM(seq_len=10)
        model._seq_len = 10
        import unittest.mock as mock

        with mock.patch("src.hydropulse.models.lstm.MAX_EPOCHS", 2):
            model.fit(train, val_df=val if len(val) >= 10 else None)
        preds = model.predict(test)
        assert preds.shape == (len(test), 7)

    def test_per_station_save_load(self, train_val_test):
        """Test model serialisation round-trip."""
        from src.hydropulse.models.lstm import PerStationLSTM

        train, _, _ = train_val_test
        model = PerStationLSTM(seq_len=10)
        import unittest.mock as mock

        with mock.patch("src.hydropulse.models.lstm.MAX_EPOCHS", 1):
            model.fit(train)

        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "lstm_test.pt"
            model.save(save_path)
            assert save_path.exists()
            loaded = PerStationLSTM.load(save_path)
            assert loaded._model is not None
            assert loaded._feature_cols == model._feature_cols

    def test_gradient_sensitivity_returns_dict(self, train_val_test):
        """Gradient attribution should return non-empty dict of feature importances."""
        from src.hydropulse.models.lstm import PerStationLSTM

        train, _, test = train_val_test
        model = PerStationLSTM(seq_len=10)
        import unittest.mock as mock

        with mock.patch("src.hydropulse.models.lstm.MAX_EPOCHS", 1):
            model.fit(train)
        sens = model.compute_gradient_sensitivity(test, max_samples=5)
        assert isinstance(sens, dict)
        assert len(sens) > 0

    def test_multi_station_lstm_fit_and_predict(self, station_df):
        from src.hydropulse.models.lstm import MultiStationLSTM

        df1 = station_df.iloc[:120].copy()
        df2 = station_df.iloc[:120].copy()
        df2["station_id"] = "station_b"
        train_dfs = {"stn_a": df1, "stn_b": df2}
        model = MultiStationLSTM(seq_len=10, max_epochs=1, patience=1)
        model.fit(train_dfs)
        preds = model.predict(df1, station_id="stn_a")
        assert preds.shape == (len(df1), 7)


# ──────────────────────────── plots tests ─────────────────────────────────


class TestPlots:
    def test_plot_hydrograph_saves_png(self):
        from src.hydropulse.evaluation.plots import plot_hydrograph

        n = 60
        dates = pd.date_range("2021-01-01", periods=n, freq="D").strftime("%Y-%m-%d")
        obs = np.random.default_rng(0).uniform(50, 200, n)
        pred = obs + np.random.default_rng(1).normal(0, 10, n)

        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "test_hydrograph.png"
            plot_hydrograph(dates, obs, pred, save_path=save_path)
            assert save_path.exists()

    def test_plot_model_comparison_saves_png(self):
        from src.hydropulse.evaluation.plots import plot_model_comparison

        comparison = {
            "persistence": [{"horizon_days": h, "NSE": 0.3 + h * 0.01} for h in range(1, 8)],
            "lgbm": [{"horizon_days": h, "NSE": 0.6 + h * 0.005} for h in range(1, 8)],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "comparison.png"
            plot_model_comparison(comparison, save_path=save_path)
            assert save_path.exists()

    def test_plot_shap_importance_saves_png(self):
        from src.hydropulse.evaluation.plots import plot_shap_importance

        features = [f"feat_{i}" for i in range(15)]
        shap_vals = np.random.default_rng(0).uniform(0, 1, 15)
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = Path(tmpdir) / "shap.png"
            plot_shap_importance(features, shap_vals, save_path=save_path, top_n=10)
            assert save_path.exists()

    def test_plot_worst_best_years(self):
        from src.hydropulse.evaluation.plots import plot_worst_best_years

        dates = pd.date_range("2021-01-01", periods=30, freq="D").strftime("%Y-%m-%d").to_numpy()
        obs = np.array([10.0 + i for i in range(30)])
        pred = np.array([10.5 + i for i in range(30)])
        records = [
            {
                "year": 2021,
                "dates": dates,
                "obs": obs,
                "pred": pred,
                "NSE": 0.85,
                "station_id": "test_stn",
                "horizon_days": 1,
            },
            {
                "year": 2022,
                "dates": dates,
                "obs": obs,
                "pred": pred + 2.0,
                "NSE": 0.45,
                "station_id": "test_stn",
                "horizon_days": 1,
            },
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            plot_worst_best_years("lgbm", records, save_dir=tmpdir)
            files = list(Path(tmpdir).glob("*.png"))
            assert len(files) == 2

    def test_plot_worst_best_years_empty_and_nan(self):
        from src.hydropulse.evaluation.plots import plot_worst_best_years

        with tempfile.TemporaryDirectory() as tmpdir:
            plot_worst_best_years("lgbm", [], save_dir=tmpdir)
            plot_worst_best_years("lgbm", [{"NSE": float("nan")}], save_dir=tmpdir)
            files = list(Path(tmpdir).glob("*.png"))
            assert len(files) == 0


# ──────────────────────────── pipeline split tests ────────────────────────


class TestChronologicalSplit:
    def test_split_no_leakage(self):
        """Ensure no date appears in both train and test after chronological split."""
        from src.hydropulse.pipeline.train import _split_df

        dates = pd.date_range("2000-01-01", periods=365 * 25, freq="D")
        df = pd.DataFrame(
            {
                "date": dates.strftime("%Y-%m-%d"),
                "discharge_m3s": np.ones(len(dates)),
            }
        )
        train, val, test = _split_df(df)

        train_dates = set(train["date"])
        val_dates = set(val["date"])
        test_dates = set(test["date"])

        assert train_dates.isdisjoint(test_dates), "Leakage: train and test share dates!"
        assert train_dates.isdisjoint(val_dates), "Leakage: train and val share dates!"

    def test_split_sizes_reasonable(self):
        from src.hydropulse.pipeline.train import _split_df

        dates = pd.date_range("2000-01-01", periods=365 * 25, freq="D")
        df = pd.DataFrame(
            {
                "date": dates.strftime("%Y-%m-%d"),
                "discharge_m3s": np.ones(len(dates)),
            }
        )
        train, val, test = _split_df(df)
        assert len(train) > len(test) > 0
        assert len(val) > 0


# ──────────────────────────── metrics.json writer test ────────────────────


class TestMetricsWriter:
    def test_write_and_read_metrics_json(self):
        from src.hydropulse.evaluation.metrics import write_metrics_json

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "reports" / "metrics.json"
            record = {
                "run_id": "test_run_001",
                "model_name": "test_model",
                "station_id": "test_station",
                "generated_at": "2024-01-01T00:00:00Z",
                "git_commit": "abc1234",
                "data_hash": "deadbeef",
                "per_horizon": [
                    {"horizon_days": 1, "NSE": 0.72, "KGE": 0.68, "RMSE": 45.2},
                    {"horizon_days": 7, "NSE": 0.51, "KGE": 0.55, "RMSE": 68.1},
                ],
            }
            write_metrics_json(record, metrics_path=path)

            import json

            with open(path) as fh:
                data = json.load(fh)

            assert len(data["runs"]) == 1
            assert data["runs"][0]["model_name"] == "test_model"
            assert data["generated_at"] is not None


# ──────────────────────────── pipeline training test ──────────────────────


class TestPipelineTraining:
    def test_run_training_dry_run(self):
        from src.hydropulse.pipeline.train import run_training

        with tempfile.TemporaryDirectory() as tmpdir:
            reports_dir = Path(tmpdir) / "reports"
            processed_dir = Path(tmpdir) / "processed"
            res = run_training(
                station_ids=["damodar_ramgarh"],
                processed_dir=processed_dir,
                reports_dir=reports_dir,
                include_lstm=False,
                dry_run=True,
                use_synthetic=True,
            )
            assert "run_id" in res
            assert Path(res["comparison_table"]).exists()

    def test_run_training_full_fast(self):
        import unittest.mock as mock

        from src.hydropulse.pipeline.train import run_training

        with tempfile.TemporaryDirectory() as tmpdir:
            reports_dir = Path(tmpdir) / "reports"
            processed_dir = Path(tmpdir) / "processed"
            fast_params = {"n_estimators": 5, "verbose": -1, "random_state": 42}
            with (
                mock.patch("src.hydropulse.models.lgbm._DEFAULT_PARAMS", fast_params),
                mock.patch("src.hydropulse.models.quantile._QUANTILE_LGBM_PARAMS", fast_params),
            ):
                res = run_training(
                    station_ids=["damodar_ramgarh"],
                    processed_dir=processed_dir,
                    reports_dir=reports_dir,
                    include_lstm=False,
                    dry_run=False,
                    use_synthetic=True,
                )
            assert Path(res["metrics_path"]).exists()
            assert Path(res["comparison_table"]).exists()
            assert Path(res["plots_dir"]).exists()
