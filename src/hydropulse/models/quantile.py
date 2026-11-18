"""Quantile regression wrappers for uncertainty quantification.

Provides P10, P50, P90 discharge forecasts (80% prediction interval) using:
    - LightGBM with quantile objective (preferred, fast)
    - Optional: PyTorch quantile loss wrapper

Calibration: compute_quantile_coverage checks what fraction of test observations
fall inside the P10-P90 band. A well-calibrated 80% interval should achieve
coverage >= 0.75 in practice (allowing for model uncertainty and distribution shift).

AGENTS.md: all provenance tags inherited from inputs; GloFAS = model_reanalysis.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

FORECAST_HORIZONS = 7
QUANTILES = (0.10, 0.50, 0.90)

FEATURE_EXCLUDE = {
    "date",
    "station_id",
    "provenance",
    "is_interpolated",
    "is_outlier_precip",
    "is_outlier_discharge",
    "outlier_reason",
    "discharge_m3s",
    *[f"target_discharge_h{h}" for h in range(1, FORECAST_HORIZONS + 1)],
}

_QUANTILE_LGBM_PARAMS: dict[str, Any] = {
    "n_estimators": 400,
    "learning_rate": 0.05,
    "max_depth": 6,
    "num_leaves": 50,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_samples": 20,
    "random_state": 42,
    "n_jobs": -1,
    "verbose": -1,
}


def _select_features(df: pd.DataFrame) -> list[str]:
    return [
        c for c in df.columns if c not in FEATURE_EXCLUDE and pd.api.types.is_numeric_dtype(df[c])
    ]


class QuantileLGBMForecaster:
    """P10/P50/P90 discharge forecaster using LightGBM quantile objective.

    Trains 3 x 7 = 21 models (one per quantile per horizon).
    Monotone constraints are enforced post-hoc (P10 <= P50 <= P90 clipping).
    """

    name: str = "lgbm_quantile"

    def __init__(self, lgbm_params: dict[str, Any] | None = None) -> None:
        self._params = lgbm_params or _QUANTILE_LGBM_PARAMS.copy()
        # {quantile_label: {horizon: model}}
        self._models: dict[str, dict[int, Any]] = {
            "q10": {},
            "q50": {},
            "q90": {},
        }
        self._feature_cols: list[str] = []

    def fit(self, train_df: pd.DataFrame) -> QuantileLGBMForecaster:
        """Fit quantile models per horizon."""
        try:
            import lightgbm as lgb
        except ImportError as exc:
            raise ImportError("lightgbm is required: pip install lightgbm") from exc

        self._feature_cols = _select_features(train_df)
        if not self._feature_cols:
            logger.error("[%s] No feature columns; cannot fit.", self.name)
            return self

        q_labels = {0.10: "q10", 0.50: "q50", 0.90: "q90"}

        for h in range(1, FORECAST_HORIZONS + 1):
            target_col = f"target_discharge_h{h}"
            if target_col not in train_df.columns:
                continue

            sub = train_df[self._feature_cols + [target_col]].dropna()
            if len(sub) < 20:
                logger.warning("[%s] Too few rows for h=%d; skipping.", self.name, h)
                continue

            X = sub[self._feature_cols].to_numpy(dtype=float)
            y = sub[target_col].to_numpy(dtype=float)

            for q_val, q_key in q_labels.items():
                params = self._params.copy()
                params["objective"] = "quantile"
                params["alpha"] = q_val
                model = lgb.LGBMRegressor(**params)
                model.fit(X, y)
                self._models[q_key][h] = model

            logger.info("[%s] Fitted quantile trio for h=%d on %d samples.", self.name, h, len(sub))

        return self

    def predict(self, df: pd.DataFrame) -> dict[str, np.ndarray]:
        """Return P10, P50, P90 forecasts, each shape (n, 7).

        Returns dict: {"q10": array, "q50": array, "q90": array}
        The arrays are monotonically enforced: q10 <= q50 <= q90.
        """
        n = len(df)
        result: dict[str, np.ndarray] = {
            "q10": np.full((n, FORECAST_HORIZONS), np.nan),
            "q50": np.full((n, FORECAST_HORIZONS), np.nan),
            "q90": np.full((n, FORECAST_HORIZONS), np.nan),
        }

        if not self._feature_cols:
            return result

        X = df.reindex(columns=self._feature_cols).fillna(0.0).to_numpy(dtype=float)

        for h in range(1, FORECAST_HORIZONS + 1):
            col_idx = h - 1
            for q_key in ("q10", "q50", "q90"):
                model = self._models[q_key].get(h)
                if model is not None:
                    result[q_key][:, col_idx] = model.predict(X)

        # Enforce monotone: q10 <= q50 <= q90 (crossing can happen with separate models)
        for i in range(n):
            for h_idx in range(FORECAST_HORIZONS):
                q10 = result["q10"][i, h_idx]
                q50 = result["q50"][i, h_idx]
                q90 = result["q90"][i, h_idx]
                if not (np.isnan(q10) or np.isnan(q50) or np.isnan(q90)):
                    sorted_trio = np.sort([q10, q50, q90])
                    result["q10"][i, h_idx] = max(sorted_trio[0], 0.0)
                    result["q50"][i, h_idx] = max(sorted_trio[1], 0.0)
                    result["q90"][i, h_idx] = max(sorted_trio[2], 0.0)

        return result

    def calibration_report(
        self,
        test_df: pd.DataFrame,
        horizon: int = 1,
    ) -> dict[str, Any]:
        """Compute coverage fraction for the 80% (P10-P90) band on a test set.

        Returns dict with keys: coverage_80pct, target_>=_0.75, horizon, n_samples.
        """
        from src.hydropulse.evaluation.metrics import compute_quantile_coverage

        preds = self.predict(test_df)
        target_col = f"target_discharge_h{horizon}"
        if target_col not in test_df.columns:
            return {"error": f"Target column {target_col} not in test_df"}

        obs = test_df[target_col].to_numpy(dtype=float)
        h_idx = horizon - 1
        q_lo = preds["q10"][:, h_idx]
        q_hi = preds["q90"][:, h_idx]

        cov = compute_quantile_coverage(obs, q_lo, q_hi)

        return {
            "horizon_days": horizon,
            "coverage_80pct": round(cov, 4) if not np.isnan(cov) else None,
            "target_>=_0.75": bool(not np.isnan(cov) and cov >= 0.75),
            "n_samples": int(np.sum(~np.isnan(obs))),
        }

    @property
    def feature_names(self) -> list[str]:
        return list(self._feature_cols)
