"""LightGBM-based multi-horizon flood discharge forecasting.

Design:
    - Direct multi-output strategy: one LGBMRegressor per horizon (t+1...t+7).
    - Feature set: all Phase 2 outputs from features/builder.py.
    - SHAP feature importances computed per-horizon after fitting.
    - Hybrid mode: trains on GloFAS residual (observed - GloFAS) so the model
      acts as a local bias-correction post-processor over GloFAS forecasts.

AGENTS.md compliance:
    - GloFAS is model output, labelled model_reanalysis everywhere.
    - All models serialised to reports/runs/<run_id>/lgbm_h{h}.pkl.
    - Chronological split only (no shuffling).
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

FORECAST_HORIZONS = 7

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

# Default hyper-params — not tuned in Phase 3; sensible priors for hydro data
_DEFAULT_PARAMS: dict[str, Any] = {
    "n_estimators": 400,
    "learning_rate": 0.05,
    "max_depth": 6,
    "num_leaves": 50,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_samples": 20,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
    "random_state": 42,
    "n_jobs": -1,
    "verbose": -1,
}


def _select_features(df: pd.DataFrame) -> list[str]:
    """Return numeric, leak-free feature column names."""
    return [
        c for c in df.columns if c not in FEATURE_EXCLUDE and pd.api.types.is_numeric_dtype(df[c])
    ]


class LGBMForecaster:
    """Direct multi-horizon LightGBM forecaster (t+1 ... t+7).

    Optionally operates in 'hybrid' mode where the training target is the
    residual (observed - GloFAS) rather than raw observed discharge.  The
    final forecast is then GloFAS + residual_hat.
    """

    name: str = "lgbm"

    def __init__(
        self,
        lgbm_params: dict[str, Any] | None = None,
        hybrid: bool = False,
    ) -> None:
        self._params = lgbm_params or _DEFAULT_PARAMS.copy()
        self._hybrid = hybrid
        self._models: dict[int, Any] = {}  # horizon -> LGBMRegressor
        self._feature_cols: list[str] = []
        self.shap_values_: dict[int, np.ndarray] = {}
        self.mean_abs_shap_: dict[int, np.ndarray] = {}
        if hybrid:
            self.name = "lgbm_hybrid"

    def fit(
        self,
        train_df: pd.DataFrame,
        val_df: pd.DataFrame | None = None,
    ) -> LGBMForecaster:
        """Fit one LGBMRegressor per forecast horizon.

        Args:
            train_df: DataFrame with feature columns and target_discharge_h{n} columns.
            val_df:   Optional validation DataFrame (used for early stopping if provided).
        """
        try:
            import lightgbm as lgb
        except ImportError as exc:
            raise ImportError("lightgbm must be installed: pip install lightgbm") from exc

        self._feature_cols = _select_features(train_df)
        if not self._feature_cols:
            logger.error("[%s] No feature columns found. Cannot fit.", self.name)
            return self

        self._models = {}
        for h in range(1, FORECAST_HORIZONS + 1):
            target_col = f"target_discharge_h{h}"
            if target_col not in train_df.columns:
                logger.warning("[%s] Missing %s; skipping h=%d.", self.name, target_col, h)
                continue

            sub = train_df[self._feature_cols + [target_col]].dropna()
            if len(sub) < 20:
                logger.warning("[%s] Too few rows (%d) for h=%d.", self.name, len(sub), h)
                continue

            X_train = sub[self._feature_cols].to_numpy(dtype=float)
            y_train = sub[target_col].to_numpy(dtype=float)

            if self._hybrid:
                # Target becomes residual (observed - GloFAS) if available
                glofas_col = "discharge_mean_m3s"
                obs_col = "discharge_m3s"
                if glofas_col in sub.columns and obs_col in sub.columns:
                    glofas_ahead = (
                        sub[glofas_col].shift(-h).reindex(sub.index).to_numpy(dtype=float)
                    )
                    obs_ahead = sub[target_col].to_numpy(dtype=float)
                    y_train = obs_ahead - glofas_ahead
                    # Drop rows where residual is NaN
                    valid = ~np.isnan(y_train)
                    X_train, y_train = X_train[valid], y_train[valid]
                    if len(X_train) < 10:
                        logger.warning("[%s] Too few valid residual rows for h=%d.", self.name, h)
                        continue
                else:
                    logger.info(
                        "[%s] GloFAS columns not available; falling back to raw target for h=%d.",
                        self.name,
                        h,
                    )

            model = lgb.LGBMRegressor(**self._params)

            if val_df is not None and target_col in val_df.columns:
                sub_val = val_df[self._feature_cols + [target_col]].dropna()
                X_val = sub_val[self._feature_cols].to_numpy(dtype=float)
                y_val = sub_val[target_col].to_numpy(dtype=float)
                import warnings

                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", category=UserWarning)
                    model.fit(
                        X_train,
                        y_train,
                        eval_set=[(X_val, y_val)],
                        callbacks=[
                            lgb.early_stopping(stopping_rounds=30, verbose=False),
                            lgb.log_evaluation(period=-1),
                        ],
                    )
            else:
                model.fit(X_train, y_train)

            self._models[h] = model
            logger.info("[%s] Fitted h=%d on %d samples.", self.name, h, len(X_train))

        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        """Return predictions, shape (n, 7). NaN where model not fitted."""
        n = len(df)
        preds = np.full((n, FORECAST_HORIZONS), np.nan)

        if not self._models or not self._feature_cols:
            logger.warning("[%s] Not fitted; returning NaN.", self.name)
            return preds

        X = df.reindex(columns=self._feature_cols).fillna(0.0).to_numpy(dtype=float)

        for h in range(1, FORECAST_HORIZONS + 1):
            model = self._models.get(h)
            if model is None:
                continue
            raw_pred = model.predict(X)

            if self._hybrid:
                # Add back GloFAS forecast
                glofas_col = "discharge_mean_m3s"
                if glofas_col in df.columns:
                    glofas_vals = df[glofas_col].to_numpy(dtype=float)
                    raw_pred = raw_pred + glofas_vals
                    # Clip to physically valid (non-negative)
                    raw_pred = np.maximum(raw_pred, 0.0)

            preds[:, h - 1] = raw_pred

        return preds

    def compute_shap(self, df: pd.DataFrame, max_samples: int = 1000) -> None:
        """Compute SHAP values for all fitted horizon models.

        Uses TreeExplainer (fast, exact for tree models).
        Results stored in self.shap_values_ and self.mean_abs_shap_.

        Args:
            df:          DataFrame with feature columns (test or a sample thereof).
            max_samples: cap to keep computation time reasonable.
        """
        try:
            import shap
        except ImportError:
            logger.warning("shap not installed; skipping SHAP computation.")
            return

        if not self._models or not self._feature_cols:
            logger.warning("[%s] Not fitted; cannot compute SHAP.", self.name)
            return

        sample_df = df.reindex(columns=self._feature_cols).fillna(0.0)
        if len(sample_df) > max_samples:
            sample_df = sample_df.sample(n=max_samples, random_state=42)

        X_sample = sample_df.to_numpy(dtype=float)

        for h, model in self._models.items():
            try:
                explainer = shap.TreeExplainer(model)
                sv = explainer.shap_values(X_sample)
                self.shap_values_[h] = sv
                self.mean_abs_shap_[h] = np.mean(np.abs(sv), axis=0)
                logger.info("[%s] SHAP computed for h=%d.", self.name, h)
            except Exception as exc:
                logger.warning("[%s] SHAP failed for h=%d: %s", self.name, h, exc)

    def save(self, run_dir: str | Path) -> None:
        """Persist all fitted horizon models to disk as pickle."""
        p = Path(run_dir)
        p.mkdir(parents=True, exist_ok=True)
        for h, model in self._models.items():
            model_path = p / f"{self.name}_h{h}.pkl"
            with open(model_path, "wb") as fh:
                pickle.dump(model, fh)
        logger.info("[%s] Saved %d models to %s.", self.name, len(self._models), p)

    @classmethod
    def load(cls, run_dir: str | Path, hybrid: bool = False) -> LGBMForecaster:
        """Load serialised horizon models from disk."""
        p = Path(run_dir)
        prefix = "lgbm_hybrid" if hybrid else "lgbm"
        instance = cls(hybrid=hybrid)
        for h in range(1, FORECAST_HORIZONS + 1):
            model_path = p / f"{prefix}_h{h}.pkl"
            if model_path.exists():
                with open(model_path, "rb") as fh:
                    instance._models[h] = pickle.load(fh)
        if not instance._models:
            logger.warning("[%s] No model files found in %s.", prefix, p)
        return instance

    @property
    def feature_names(self) -> list[str]:
        """Return the fitted feature column names."""
        return list(self._feature_cols)
