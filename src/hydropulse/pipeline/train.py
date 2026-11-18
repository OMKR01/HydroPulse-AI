"""Full training pipeline orchestrator for HydroPulse AI — Phase 3.

Replaces the Phase 0 scaffold stub with a complete end-to-end pipeline:

    1. Load processed features from Parquet (data/processed/<station_id>.parquet)
       or fall back to building from the SQLite DB via features/builder.py.
    2. Chronological split per station:
           Train  2000-01-01 -> 2018-12-31 (~19 years)
           Val    2019-01-01 -> 2020-12-31 (~2 years, for early stopping)
           Test   2021-01-01 -> 2024-12-31 (~4 years)
    3. Fit all models: persistence -> climatology -> ridge -> LightGBM ->
       LightGBM quantile -> LightGBM hybrid -> per-station LSTM -> multi-station LSTM.
    4. Evaluate on test set: per-horizon NSE/KGE/RMSE/MAE + alert metrics.
    5. Persist models and write reports/runs/<run_id>/run_config.json.
    6. Update reports/metrics.json via evaluation/metrics.write_metrics_json().
    7. Generate hydrograph plots (best + worst test year per model).
    8. Print comparison table to console and save reports/model_comparison.md.

Run:
    python -m hydropulse.pipeline.train [--station STATION_ID] [--no-lstm] [--dry-run]

AGENTS.md compliance:
    - All seeds fixed (RANDOM_SEED=42).
    - Chronological split only; no shuffling.
    - GloFAS provenance labelled throughout.
    - Data hash and git SHA logged to run_config.json.
    - Metrics written by evaluation scripts; never hand-typed.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logger = logging.getLogger(__name__)

RANDOM_SEED = 42
TRAIN_END = "2018-12-31"
VAL_END = "2020-12-31"
TEST_END = "2024-12-31"

# Watch threshold for alert metrics (P90 approximation; updated from thresholds.yaml if available)
DEFAULT_ALERT_THRESHOLD_QUANTILE = 0.90


# ──────────────────────────── utility helpers ──────────────────────────────


def _git_sha() -> str | None:
    """Return the current HEAD git commit SHA or None if not in a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


def _data_hash(df: pd.DataFrame) -> str:
    """MD5 hash of the DataFrame's shape and first/last values for provenance logging."""
    summary = f"{df.shape}|{df.iloc[0].to_dict() if len(df) > 0 else ''}|{df.iloc[-1].to_dict() if len(df) > 0 else ''}"
    return hashlib.md5(summary.encode()).hexdigest()[:12]


def _make_run_id() -> str:
    """Generate a unique run ID using UTC timestamp."""
    ts = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"run_{ts}"


def _split_df(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Chronological split into train/val/test partitions.

    Uses 'date' column (string YYYY-MM-DD or datetime).
    """
    df = df.copy()
    if "date" not in df.columns:
        raise ValueError("DataFrame must have a 'date' column.")

    df["_dt"] = pd.to_datetime(df["date"])
    df = df.sort_values("_dt").reset_index(drop=True)

    train = df[df["_dt"] <= TRAIN_END].drop(columns=["_dt"])
    val = df[(df["_dt"] > TRAIN_END) & (df["_dt"] <= VAL_END)].drop(columns=["_dt"])
    test = df[(df["_dt"] > VAL_END) & (df["_dt"] <= TEST_END)].drop(columns=["_dt"])

    return train, val, test


def _generate_synthetic_station_features(
    station_id: str,
    seed: int = RANDOM_SEED,
    start_date: str = "2010-01-01",
    end_date: str = "2024-12-31",
) -> pd.DataFrame:
    """Generate realistic synthetic features adhering to repo provenance rules.

    Every row explicitly carries provenance='synthetic'.
    """
    rng = np.random.default_rng(seed + abs(hash(station_id)) % 1000)
    dates = pd.date_range(start_date, end_date, freq="D")
    n = len(dates)

    doy = getattr(dates, "day_of_year", dates.dayofyear).to_numpy()
    months = dates.month.to_numpy()
    is_monsoon = np.isin(months, [6, 7, 8, 9, 10]).astype(int)
    monsoon_factor = np.where(is_monsoon, 2.5, 0.2)

    precip = rng.exponential(scale=6.0 * monsoon_factor)
    precip[rng.uniform(size=n) < np.where(is_monsoon, 0.2, 0.75)] = 0.0

    temp_max = 28.0 + 8.0 * np.sin(2.0 * np.pi * (doy - 100) / 365.25) + rng.normal(0, 2.5, n)
    temp_min = temp_max - rng.uniform(8.0, 14.0, n)
    rel_hum = np.clip(np.where(is_monsoon, 75.0, 45.0) + rng.normal(0, 10.0, n), 20.0, 98.0)

    base_q = 20.0 + (abs(hash(station_id)) % 30)
    discharge = np.zeros(n)
    q = base_q
    for i in range(n):
        q = 0.85 * q + 0.15 * base_q + 1.2 * precip[i] + rng.normal(0, 0.8)
        discharge[i] = max(q, 2.0)

    discharge_mean_m3s = np.maximum(discharge * 0.92 + rng.normal(0, 1.5, n), 1.5)

    df = pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "station_id": station_id,
            "precipitation_mm": np.round(precip, 2),
            "temperature_max_c": np.round(temp_max, 2),
            "temperature_min_c": np.round(temp_min, 2),
            "relative_humidity_mean": np.round(rel_hum, 2),
            "discharge_m3s": np.round(discharge, 2),
            "discharge_mean_m3s": np.round(discharge_mean_m3s, 2),
            "discharge_p25_m3s": np.round(discharge_mean_m3s * 0.85, 2),
            "discharge_p75_m3s": np.round(discharge_mean_m3s * 1.15, 2),
            "provenance": "synthetic",
            "is_interpolated": False,
            "is_outlier_precip": False,
            "is_outlier_discharge": False,
            "outlier_reason": "",
        }
    )

    for lag in range(1, 15):
        df[f"precip_lag_{lag}"] = df["precipitation_mm"].shift(lag).fillna(0.0)

    for r in [3, 7, 14, 30]:
        df[f"precip_roll_sum_{r}d"] = (
            df["precipitation_mm"].shift(1).rolling(r, min_periods=1).sum().fillna(0.0)
        )
    df["antecedent_precipitation_index"] = (
        df["precipitation_mm"].shift(1).rolling(14, min_periods=1).mean().fillna(0.0)
    )

    df["doy_sin"] = np.sin(2.0 * np.pi * doy / 365.25)
    df["doy_cos"] = np.cos(2.0 * np.pi * doy / 365.25)
    df["month_sin"] = np.sin(2.0 * np.pi * months / 12.0)
    df["month_cos"] = np.cos(2.0 * np.pi * months / 12.0)
    df["is_monsoon"] = is_monsoon

    for lag in range(1, 8):
        df[f"discharge_lag_{lag}"] = df["discharge_m3s"].shift(lag).bfill().ffill()
    df["discharge_roll_mean_3d"] = (
        df["discharge_m3s"].shift(1).rolling(3, min_periods=1).mean().bfill().ffill()
    )
    df["discharge_roll_mean_7d"] = (
        df["discharge_m3s"].shift(1).rolling(7, min_periods=1).mean().bfill().ffill()
    )

    df["upstream_discharge_lag_1"] = df["discharge_lag_1"] * 0.8
    df["upstream_discharge_lag_2"] = df["discharge_lag_2"] * 0.8
    df["upstream_precip_roll_3d"] = df["precip_roll_sum_3d"] * 0.9

    df["precip_acc_30d"] = df["precip_roll_sum_30d"]
    df["spi_30d"] = np.clip(
        (df["precip_acc_30d"] - df["precip_acc_30d"].mean()) / (df["precip_acc_30d"].std() + 1e-6),
        -3.0,
        3.0,
    )
    df["spi_30d_category"] = "Near Normal"
    df["precip_acc_90d"] = (
        df["precipitation_mm"].shift(1).rolling(90, min_periods=1).sum().fillna(0.0)
    )
    df["spi_90d"] = np.clip(
        (df["precip_acc_90d"] - df["precip_acc_90d"].mean()) / (df["precip_acc_90d"].std() + 1e-6),
        -3.0,
        3.0,
    )
    df["spi_90d_category"] = "Near Normal"
    df["precip_acc_180d"] = (
        df["precipitation_mm"].shift(1).rolling(180, min_periods=1).sum().fillna(0.0)
    )
    df["spi_180d"] = np.clip(
        (df["precip_acc_180d"] - df["precip_acc_180d"].mean())
        / (df["precip_acc_180d"].std() + 1e-6),
        -3.0,
        3.0,
    )
    df["spi_180d_category"] = "Near Normal"

    df["static_elevation_m"] = 320.0
    df["static_drainage_area_km2"] = 1500.0
    df["static_channel_slope_m_per_km"] = 3.5
    df["static_stream_order"] = 4
    df["static_dominant_land_cover"] = 2

    for h in range(1, 8):
        df[f"target_discharge_h{h}"] = df["discharge_m3s"].shift(-h)

    return df


def _load_station_df(
    station_id: str,
    processed_dir: Path,
    force_synthetic: bool = False,
) -> pd.DataFrame:
    """Load station features from Parquet, or generate synthetic fallback if sparse."""
    if force_synthetic:
        logger.info("Using synthetic dataset for %s (provenance=synthetic).", station_id)
        return _generate_synthetic_station_features(station_id)

    pq_path = processed_dir / f"{station_id}.parquet"
    if pq_path.exists():
        df = pd.read_parquet(pq_path)
        if len(df) >= 100:
            logger.info("Loaded %s from %s (%d rows).", station_id, pq_path, len(df))
            return df
        logger.warning(
            "Parquet for %s has only %d rows (<100); generating synthetic historical features.",
            station_id,
            len(df),
        )
        return _generate_synthetic_station_features(station_id)

    logger.warning("Parquet not found for %s; attempting builder from DB.", station_id)
    try:
        from src.hydropulse.features.builder import build_station_features

        df = build_station_features(station_id)
        if not df.empty and len(df) >= 100:
            pq_path.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(pq_path, index=False)
            return df
    except Exception as exc:
        logger.error("Builder failed for %s: %s", station_id, exc)

    logger.info("Generating synthetic fallback features for %s (provenance=synthetic).", station_id)
    return _generate_synthetic_station_features(station_id)


def _compute_watch_threshold(train_df: pd.DataFrame) -> float | None:
    """Compute P90 discharge from training data for alert metrics."""
    if "discharge_m3s" in train_df.columns:
        vals = train_df["discharge_m3s"].dropna().to_numpy()
        if len(vals) > 10:
            return float(np.nanpercentile(vals, 90))
    return None


def _build_eval_records(
    model_name: str,
    station_id: str,
    test_df: pd.DataFrame,
    preds: np.ndarray,
    horizon: int = 1,
) -> list[dict[str, Any]]:
    """Build per-year evaluation records for worst/best plot selection."""
    if "date" not in test_df.columns:
        return []

    from src.hydropulse.evaluation.metrics import nse as _nse

    test_c = test_df.reset_index(drop=True)
    test_c["_year"] = pd.to_datetime(test_c["date"]).dt.year
    target_col = f"target_discharge_h{horizon}"
    if target_col not in test_c.columns:
        return []

    records: list[dict[str, Any]] = []
    h_idx = horizon - 1

    for year, grp in test_c.groupby("_year"):
        idx = grp.index
        obs_yr = grp[target_col].to_numpy(dtype=float)
        pred_yr = preds[idx, h_idx] if preds.ndim == 2 else preds[idx]
        nse_val = _nse(obs_yr, pred_yr)
        records.append(
            {
                "model_name": model_name,
                "station_id": station_id,
                "year": int(year),
                "horizon_days": horizon,
                "NSE": nse_val,
                "dates": grp["date"].to_numpy(),
                "obs": obs_yr,
                "pred": pred_yr,
            }
        )

    return records


def _print_comparison_table(comparison: dict[str, dict[str, Any]]) -> str:
    """Format a markdown comparison table for console output and file save."""
    header = "| Model | h=1 NSE | h=3 NSE | h=7 NSE | h=1 KGE | h=7 RMSE |"
    sep = "|-------|---------|---------|---------|---------|----------|"
    rows = [header, sep]

    for model_name, data in comparison.items():
        per_h = data.get("per_horizon", [])

        def _get(h: int, key: str, _per_h: list = per_h) -> str:  # noqa: B023
            for row in _per_h:
                if row.get("horizon_days") == h:
                    v = row.get(key)
                    return f"{v:.4f}" if isinstance(v, float) and not np.isnan(v) else "N/A"
            return "N/A"

        rows.append(
            f"| {model_name} | {_get(1, 'NSE')} | {_get(3, 'NSE')} | {_get(7, 'NSE')} "
            f"| {_get(1, 'KGE')} | {_get(7, 'RMSE')} |"
        )

    return "\n".join(rows)


# ──────────────────────────── main training pipeline ──────────────────────


def run_training(
    station_ids: list[str] | None = None,
    processed_dir: str | Path = "data/processed",
    reports_dir: str | Path = "reports",
    include_lstm: bool = True,
    dry_run: bool = False,
    use_synthetic: bool = False,
) -> dict[str, Any]:
    """Execute the full Phase 3 training pipeline.

    Args:
        station_ids:   list of station IDs to train on; None -> all from stations.yaml
        processed_dir: directory containing per-station Parquet files
        reports_dir:   root for metrics.json and run artefacts
        include_lstm:  whether to train LSTM models (slow on CPU, can be skipped)
        dry_run:       if True, only load data and print split stats without training

    Returns:
        summary dict with run_id, models trained, metrics path
    """
    import yaml

    from config.settings import BASE_DIR
    from src.hydropulse.evaluation.metrics import per_horizon_metrics, write_metrics_json
    from src.hydropulse.evaluation.plots import (
        plot_model_comparison,
        plot_shap_importance,
        plot_worst_best_years,
    )
    from src.hydropulse.models.baselines import (
        ClimatologyBaseline,
        PersistenceBaseline,
        RidgeBaseline,
        raw_glofas_baseline,
    )
    from src.hydropulse.models.lgbm import LGBMForecaster
    from src.hydropulse.models.quantile import QuantileLGBMForecaster

    np.random.seed(RANDOM_SEED)

    run_id = _make_run_id()
    run_dir = Path(reports_dir) / "runs" / run_id
    plots_dir = Path(reports_dir) / "plots"
    metrics_path = Path(reports_dir) / "metrics.json"
    run_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)
    processed_dir = Path(processed_dir)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    logger.info("=== HydroPulse AI — Phase 3 Training Run: %s ===", run_id)
    logger.info("  Train: <= %s | Val: %s--%s | Test: > %s", TRAIN_END, TRAIN_END, VAL_END, VAL_END)
    logger.info("  LSTM: %s | dry_run: %s", include_lstm, dry_run)

    # Load station list
    if station_ids is None:
        stations_yaml = Path(BASE_DIR) / "config" / "stations.yaml"
        with open(stations_yaml, encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh)
        station_ids = [s["id"] for s in cfg.get("stations", [])]
    logger.info("Stations: %s", station_ids)

    # ── Per-station training loop ──────────────────────────────────────────
    comparison: dict[str, dict[str, Any]] = {}
    all_eval_records: dict[str, list[dict[str, Any]]] = {}

    for station_id in station_ids:
        logger.info("--- Station: %s ---", station_id)
        df = _load_station_df(station_id, processed_dir, force_synthetic=use_synthetic)

        if df.empty:
            logger.warning("No data for station %s; skipping.", station_id)
            continue

        train_df, val_df, test_df = _split_df(df)
        logger.info(
            "Split sizes: train=%d val=%d test=%d",
            len(train_df),
            len(val_df),
            len(test_df),
        )

        if dry_run:
            logger.info("[dry-run] Skipping model training for %s.", station_id)
            continue

        if len(train_df) < 100 or len(test_df) < 30:
            logger.warning("Insufficient data for %s; skipping.", station_id)
            continue

        watch_thresh = _compute_watch_threshold(train_df)
        d_hash = _data_hash(df)
        git_sha = _git_sha()

        # ── Baselines ─────────────────────────────────────────────────────
        models_to_eval: list[tuple[str, Any, np.ndarray]] = []

        for baseline in [PersistenceBaseline(), ClimatologyBaseline(), RidgeBaseline()]:
            baseline.fit(train_df)
            preds = baseline.predict(test_df)
            models_to_eval.append((baseline.name, baseline, preds))
            logger.info("[%s] Baseline fitted and predicted.", baseline.name)

        # Raw GloFAS baseline
        glofas_preds = raw_glofas_baseline(test_df)
        models_to_eval.append(("raw_glofas", None, glofas_preds))

        # ── LightGBM point forecast ────────────────────────────────────────
        lgbm = LGBMForecaster()
        lgbm.fit(train_df, val_df=val_df)
        lgbm_preds = lgbm.predict(test_df)
        lgbm.compute_shap(test_df)
        models_to_eval.append(("lgbm", lgbm, lgbm_preds))
        lgbm.save(run_dir)

        # SHAP plot for h=1
        if lgbm.mean_abs_shap_.get(1) is not None:
            plot_shap_importance(
                lgbm.feature_names,
                lgbm.mean_abs_shap_[1],
                model_name="LightGBM",
                horizon_days=1,
                save_path=plots_dir / f"shap_{station_id}_lgbm_h1.png",
            )

        # ── LightGBM hybrid correction ────────────────────────────────────
        lgbm_hyb = LGBMForecaster(hybrid=True)
        lgbm_hyb.fit(train_df, val_df=val_df)
        lgbm_hyb_preds = lgbm_hyb.predict(test_df)
        models_to_eval.append(("lgbm_hybrid", lgbm_hyb, lgbm_hyb_preds))
        lgbm_hyb.save(run_dir)

        # ── Quantile LightGBM ─────────────────────────────────────────────
        q_model = QuantileLGBMForecaster()
        q_model.fit(train_df)
        q_preds = q_model.predict(test_df)
        cal_report = q_model.calibration_report(test_df, horizon=1)
        logger.info("[lgbm_quantile] Calibration h=1: %s", cal_report)
        models_to_eval.append(("lgbm_q50", None, q_preds["q50"]))

        # ── LSTM (optional) ───────────────────────────────────────────────
        if include_lstm and len(train_df) >= 500:
            from src.hydropulse.models.lstm import PerStationLSTM

            lstm = PerStationLSTM(max_epochs=15, patience=5)
            lstm.fit(train_df, val_df=val_df if len(val_df) >= 30 else None)
            lstm_preds = lstm.predict(test_df)
            models_to_eval.append(("lstm_per_station", lstm, lstm_preds))
            lstm.save(run_dir / f"lstm_{station_id}.pt")
            logger.info("[lstm_per_station] Fitted and saved for %s.", station_id)
        else:
            logger.info(
                "Skipping LSTM for %s (include_lstm=%s, train_rows=%d).",
                station_id,
                include_lstm,
                len(train_df),
            )

        # ── Evaluate all models ───────────────────────────────────────────
        target_cols = [f"target_discharge_h{h}" for h in range(1, 8)]
        available_targets = [c for c in target_cols if c in test_df.columns]

        if available_targets:
            obs_matrix = test_df[available_targets].to_numpy(dtype=float)
        else:
            logger.warning("No target columns in test_df for %s.", station_id)
            obs_matrix = None

        for model_name, _model_obj, preds in models_to_eval:
            if obs_matrix is None:
                continue

            per_h = per_horizon_metrics(
                obs_matrix,
                preds,
                threshold=watch_thresh,
                horizons=7,
            )

            is_synth = (
                (df["provenance"] == "synthetic").any() if "provenance" in df.columns else False
            )
            prov_label = "synthetic" if is_synth else "model_reanalysis (GloFAS + Open-Meteo ERA5)"

            run_record: dict[str, Any] = {
                "run_id": run_id,
                "model_name": model_name,
                "station_id": station_id,
                "generated_at": datetime.datetime.now(datetime.UTC).isoformat(),
                "git_commit": git_sha,
                "data_hash": d_hash,
                "data_provenance": prov_label,
                "split_config": {
                    "train_end": TRAIN_END,
                    "val_end": VAL_END,
                    "test_end": TEST_END,
                    "train_rows": len(train_df),
                    "val_rows": len(val_df),
                    "test_rows": len(test_df),
                },
                "quantile_calibration": cal_report if model_name.startswith("lgbm") else None,
                "per_horizon": per_h,
            }
            write_metrics_json(run_record, metrics_path=metrics_path)

            if model_name not in comparison:
                comparison[model_name] = {"per_horizon": per_h}

            # Build per-year records for worst/best plots
            eval_recs = _build_eval_records(model_name, station_id, test_df, preds, horizon=1)
            all_eval_records.setdefault(model_name, []).extend(eval_recs)

        # Hydrograph plots: worst and best test year for LightGBM and LSTM
        for model_name in ["lgbm", "lstm_per_station"]:
            if model_name in all_eval_records:
                plot_worst_best_years(
                    model_name,
                    all_eval_records[model_name],
                    save_dir=plots_dir,
                )

        # Write run config
        run_config = {
            "run_id": run_id,
            "station_id": station_id,
            "git_commit": git_sha,
            "data_hash": d_hash,
            "train_end": TRAIN_END,
            "val_end": VAL_END,
            "test_end": TEST_END,
            "random_seed": RANDOM_SEED,
            "include_lstm": include_lstm,
            "models_trained": [m for m, _, _ in models_to_eval],
        }
        with open(run_dir / f"run_config_{station_id}.json", "w", encoding="utf-8") as fh:
            json.dump(run_config, fh, indent=2)

    # ── Multi-station LSTM ────────────────────────────────────────────────
    if include_lstm and not dry_run and len(station_ids) > 1:
        logger.info("=== Training multi-station LSTM on all stations ===")
        try:
            from src.hydropulse.models.lstm import MultiStationLSTM

            train_dfs: dict[str, pd.DataFrame] = {}
            val_dfs: dict[str, pd.DataFrame] = {}

            for sid in station_ids:
                df = _load_station_df(sid, processed_dir, force_synthetic=use_synthetic)
                if df.empty:
                    continue
                tr, va, _ = _split_df(df)
                if len(tr) >= 200:
                    train_dfs[sid] = tr
                if len(va) >= 30:
                    val_dfs[sid] = va

            if len(train_dfs) >= 2:
                ms_lstm = MultiStationLSTM(max_epochs=15, patience=5)
                ms_lstm.fit(train_dfs, val_dfs=val_dfs if val_dfs else None)
                ms_lstm.save(run_dir / "lstm_multi_station.pt")
                logger.info("Multi-station LSTM saved to %s.", run_dir)
        except Exception as exc:
            logger.warning("Multi-station LSTM failed: %s", exc)

    # ── Comparison table ──────────────────────────────────────────────────
    table_md = _print_comparison_table(comparison)
    print("\n=== Model Comparison Table ===")
    print(table_md)

    comp_path = Path(reports_dir) / "model_comparison.md"
    header_md = (
        f"# HydroPulse AI — Model Comparison\n\n"
        f"Generated: {datetime.datetime.now(datetime.UTC).isoformat()}  \n"
        f"Run ID: `{run_id}`  \n"
        f"Metrics source: `reports/metrics.json`\n\n"
        f"> Numbers generated by evaluation scripts; not hand-typed.\n\n"
    )
    with open(comp_path, "w", encoding="utf-8") as fh:
        fh.write(header_md + table_md + "\n")
    logger.info("Comparison table saved to %s.", comp_path)

    # ── Model comparison plot ─────────────────────────────────────────────
    if comparison:
        plot_model_comparison(
            comparison,
            metric="NSE",
            save_path=plots_dir / "model_comparison_nse.png",
        )

    logger.info("=== Phase 3 training run %s complete ===", run_id)
    return {
        "run_id": run_id,
        "metrics_path": str(metrics_path),
        "comparison_table": str(comp_path),
        "plots_dir": str(plots_dir),
    }


# ──────────────────────────── CLI entry point ─────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="HydroPulse AI — Phase 3 Training Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--station",
        nargs="+",
        default=None,
        metavar="STATION_ID",
        help="Station ID(s) to train on. Default: all stations from config/stations.yaml.",
    )
    parser.add_argument(
        "--no-lstm",
        action="store_true",
        help="Skip LSTM training (fast mode, CPU-friendly).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load data and print split stats only; no model training.",
    )
    parser.add_argument(
        "--processed-dir",
        default="data/processed",
        help="Directory with per-station Parquet files.",
    )
    parser.add_argument(
        "--reports-dir",
        default="reports",
        help="Root for metrics.json and run artefacts.",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Use synthetic dataset for training/testing (provenance=synthetic).",
    )
    args = parser.parse_args(argv)

    summary = run_training(
        station_ids=args.station,
        processed_dir=args.processed_dir,
        reports_dir=args.reports_dir,
        include_lstm=not args.no_lstm,
        dry_run=args.dry_run,
        use_synthetic=args.synthetic,
    )
    print(f"\nRun complete: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
