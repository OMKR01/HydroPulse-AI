"""Baseline flood discharge forecasting models for HydroPulse AI.

Three honest baselines that every ML model must beat to be considered useful:

1. PersistenceBaseline   — last-known discharge carried forward for all horizons
2. ClimatologyBaseline   — historical median discharge by calendar week/month
3. RidgeBaseline         — Ridge regression with full Phase 2 feature set, one model per horizon

All three implement the same interface:
    .name        : str — model identifier
    .fit(df)     : fit on training DataFrame
    .predict(df) : return np.ndarray of shape (n, 7)

AGENTS.md: GloFAS is model output, not a gauge reading. Provenance is inherited
           from the input DataFrame's 'provenance' column.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

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
    # Exclude current-day target and all future targets to prevent leakage
    "discharge_m3s",
    *[f"target_discharge_h{h}" for h in range(1, FORECAST_HORIZONS + 1)],
}


def _select_features(df: pd.DataFrame) -> list[str]:
    """Return numeric feature columns that are safe to use as model inputs."""
    return [
        c for c in df.columns if c not in FEATURE_EXCLUDE and pd.api.types.is_numeric_dtype(df[c])
    ]


class PersistenceBaseline:
    """Persistence baseline: discharge_hat[t+h] = discharge_obs[t] for all h.

    The simplest possible benchmark — carries the last known discharge value
    unchanged across all 7 forecast horizons.
    """

    name: str = "persistence"

    def fit(self, train_df: pd.DataFrame) -> PersistenceBaseline:
        """No fitting needed; persistence uses the observation directly."""
        logger.info("[%s] fit() — no parameters to learn.", self.name)
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        """Return persistence forecasts: shape (n, 7).

        Uses 'discharge_m3s' as the last-known observed value.
        Falls back to discharge_lag_1 if discharge_m3s is absent.
        """
        if "discharge_m3s" in df.columns:
            last_q = df["discharge_m3s"].to_numpy(dtype=float)
        elif "discharge_lag_1" in df.columns:
            last_q = df["discharge_lag_1"].to_numpy(dtype=float)
        else:
            logger.warning("[%s] No discharge column found; returning NaN.", self.name)
            return np.full((len(df), FORECAST_HORIZONS), np.nan)

        # Repeat same value for each of h=1..7
        return np.column_stack([last_q] * FORECAST_HORIZONS)


class ClimatologyBaseline:
    """Climatology baseline: median discharge by calendar week, one value per horizon.

    For each forecast horizon h, the prediction is the training-set median
    discharge observed h days later, conditioned on the calendar week.
    This captures the monsoon seasonality dominant in Jharkhand basins.
    """

    name: str = "climatology"
    _climatology: dict[int, dict[int, float]] = {}  # horizon -> week -> median

    def fit(self, train_df: pd.DataFrame) -> ClimatologyBaseline:
        """Compute weekly climatology from training data for each horizon."""
        self._climatology = {}
        if "date" not in train_df.columns or "discharge_m3s" not in train_df.columns:
            logger.warning("[%s] Missing date or discharge column; climatology empty.", self.name)
            return self

        df = train_df.copy()
        df["_date"] = pd.to_datetime(df["date"])
        df["_week"] = df["_date"].dt.isocalendar().week.astype(int)

        for h in range(1, FORECAST_HORIZONS + 1):
            target_col = f"target_discharge_h{h}"
            if target_col not in df.columns:
                # Construct from discharge_m3s if targets not pre-built
                df[target_col] = df["discharge_m3s"].shift(-h)

            week_medians: dict[int, float] = {}
            for week, grp in df.groupby("_week"):
                vals = grp[target_col].dropna().to_numpy()
                if len(vals) > 0:
                    week_medians[int(week)] = float(np.median(vals))

            # Fill any missing weeks with global median
            global_med = (
                float(np.nanmedian(df[target_col].dropna().to_numpy()))
                if not df[target_col].dropna().empty
                else 0.0
            )
            self._climatology[h] = {w: week_medians.get(w, global_med) for w in range(1, 54)}
            # Fill remaining
            for w in range(1, 54):
                if w not in self._climatology[h]:
                    self._climatology[h][w] = global_med

        logger.info("[%s] Fitted climatology for %d horizons.", self.name, len(self._climatology))
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        """Return climatology median for each row's calendar week, shape (n, 7)."""
        if not self._climatology:
            logger.warning("[%s] Not fitted; returning NaN.", self.name)
            return np.full((len(df), FORECAST_HORIZONS), np.nan)

        df_ = df.copy()
        if "date" in df_.columns:
            df_["_date"] = pd.to_datetime(df_["date"])
            df_["_week"] = df_["_date"].dt.isocalendar().week.astype(int)
        else:
            df_["_week"] = 1

        preds: list[np.ndarray] = []
        for h in range(1, FORECAST_HORIZONS + 1):
            clim_h = self._climatology.get(h, {})
            col = np.array([clim_h.get(int(w), float("nan")) for w in df_["_week"]], dtype=float)
            preds.append(col)

        return np.column_stack(preds)


class RidgeBaseline:
    """Ridge regression baseline — direct multi-output strategy (one model per horizon).

    Uses all Phase 2-engineered features. Scaler fitted on train only (no leakage).
    """

    name: str = "ridge"

    def __init__(self, alpha: float = 1.0) -> None:
        self._alpha = alpha
        self._pipelines: dict[int, Pipeline] = {}
        self._feature_cols: list[str] = []

    def fit(self, train_df: pd.DataFrame) -> RidgeBaseline:
        """Fit one Ridge pipeline per horizon on training data."""
        self._feature_cols = _select_features(train_df)
        if not self._feature_cols:
            logger.warning("[%s] No feature columns found; nothing to fit.", self.name)
            return self

        self._pipelines = {}
        for h in range(1, FORECAST_HORIZONS + 1):
            target_col = f"target_discharge_h{h}"
            if target_col not in train_df.columns:
                logger.warning(
                    "[%s] Target column %s not found; skipping h=%d.", self.name, target_col, h
                )
                continue

            sub = train_df[self._feature_cols + [target_col]].dropna()
            if len(sub) < 10:
                logger.warning("[%s] Too few rows (%d) for h=%d; skipping.", self.name, len(sub), h)
                continue

            X_train = sub[self._feature_cols].to_numpy(dtype=float)
            y_train = sub[target_col].to_numpy(dtype=float)

            pipe = Pipeline(
                [
                    ("scaler", StandardScaler()),
                    ("ridge", Ridge(alpha=self._alpha)),
                ]
            )
            pipe.fit(X_train, y_train)
            self._pipelines[h] = pipe

        logger.info(
            "[%s] Fitted %d horizon models with %d features.",
            self.name,
            len(self._pipelines),
            len(self._feature_cols),
        )
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        """Return Ridge predictions, shape (n, 7). NaN where model not fitted."""
        n = len(df)
        preds = np.full((n, FORECAST_HORIZONS), np.nan)

        if not self._pipelines or not self._feature_cols:
            logger.warning("[%s] Not fitted; returning NaN.", self.name)
            return preds

        # Use available feature columns; fill missing with 0
        X_sub = df.reindex(columns=self._feature_cols).fillna(0.0).to_numpy(dtype=float)

        for h in range(1, FORECAST_HORIZONS + 1):
            pipe = self._pipelines.get(h)
            if pipe is None:
                continue
            preds[:, h - 1] = pipe.predict(X_sub)

        return preds

    @property
    def coef_(self) -> dict[int, np.ndarray]:
        """Return coefficient arrays per horizon for interpretability."""
        return {h: pipe.named_steps["ridge"].coef_ for h, pipe in self._pipelines.items()}


def raw_glofas_baseline(df: pd.DataFrame) -> np.ndarray:
    """Return raw GloFAS discharge as a naive baseline (shape n x 7).

    Copies the GloFAS model output columns (discharge_mean_m3s / discharge_m3s)
    for each horizon — effectively treating the GloFAS reanalysis as a forecast.
    This is the baseline that the hybrid ML correction is supposed to improve upon.

    PROVENANCE NOTE: GloFAS is model output, not a gauge reading.
    """
    n = len(df)
    preds = np.full((n, FORECAST_HORIZONS), np.nan)

    glofas_col = None
    for candidate in ["discharge_mean_m3s", "discharge_m3s"]:
        if candidate in df.columns:
            glofas_col = candidate
            break

    if glofas_col is None:
        logger.warning("[raw_glofas] No GloFAS discharge column found; returning NaN.")
        return preds

    vals = df[glofas_col].to_numpy(dtype=float)
    for h in range(FORECAST_HORIZONS):
        preds[:, h] = vals  # same value repeated — GloFAS single-step re-used as proxy

    return preds


def get_all_baselines(alpha: float = 1.0) -> list[Any]:
    """Return instantiated baseline model objects ready for fit/predict."""
    return [
        PersistenceBaseline(),
        ClimatologyBaseline(),
        RidgeBaseline(alpha=alpha),
    ]
