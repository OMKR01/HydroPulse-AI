"""Hydrograph and evaluation plot generation for HydroPulse AI.

Uses matplotlib only (non-interactive, Agg backend) so plots are CI-safe.
All functions save PNG files; they never call plt.show().

Functions:
    plot_hydrograph     — observed vs predicted with uncertainty band
    plot_worst_best_years — two hydrograph panels for worst/best NSE year
    plot_model_comparison — bar chart of NSE/KGE per model per horizon
    plot_shap_importance  — horizontal bar chart of mean |SHAP| values
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")  # non-interactive, safe for CI
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

logger = logging.getLogger(__name__)

# Colour-blind–safe palette (Okabe & Ito 2008)
_PALETTE = {
    "observed": "#000000",     # Black
    "predicted": "#0072B2",    # Blue
    "q10_q90": "#56B4E9",      # Sky blue (shaded band)
    "q50": "#E69F00",          # Orange
    "watch": "#F0E442",        # Yellow
    "warning": "#E69F00",      # Orange
    "danger": "#CC79A7",       # Pink/Magenta
    "baseline": "#999999",     # Grey
}


def _save_fig(fig: plt.Figure, save_path: str | Path, dpi: int = 150) -> None:
    """Save figure to path and close it."""
    p = Path(save_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(p, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved plot -> %s", p)


def plot_hydrograph(
    dates: np.ndarray | pd.Series,
    obs: np.ndarray,
    pred: np.ndarray,
    q_lo: np.ndarray | None = None,
    q_hi: np.ndarray | None = None,
    threshold_watch: float | None = None,
    threshold_danger: float | None = None,
    title: str = "River Discharge Hydrograph",
    station_id: str = "",
    horizon_days: int = 1,
    save_path: str | Path = "reports/plots/hydrograph.png",
) -> None:
    """Plot observed vs predicted hydrograph with optional uncertainty band.

    Args:
        dates:           date axis (string or datetime)
        obs:             observed discharge [m3/s]
        pred:            predicted median discharge [m3/s]
        q_lo:            P10 lower bound (optional)
        q_hi:            P90 upper bound (optional)
        threshold_watch: watch alert level [m3/s]
        threshold_danger: danger alert level [m3/s]
        title:           plot title
        station_id:      station identifier for subtitle
        horizon_days:    forecast horizon shown
        save_path:       output PNG path
    """
    fig, ax = plt.subplots(figsize=(14, 5))

    dt_index = pd.to_datetime(dates)

    # Uncertainty band
    if q_lo is not None and q_hi is not None:
        ax.fill_between(
            dt_index, q_lo, q_hi,
            alpha=0.25, color=_PALETTE["q10_q90"], label="P10–P90 band",
        )

    # Observed
    ax.plot(dt_index, obs, color=_PALETTE["observed"], linewidth=1.2,
            label="Observed", zorder=3)

    # Predicted
    ax.plot(dt_index, pred, color=_PALETTE["predicted"], linewidth=1.2,
            linestyle="--", label=f"Predicted (t+{horizon_days}d)", zorder=4)

    # Alert thresholds
    if threshold_watch is not None:
        ax.axhline(threshold_watch, color=_PALETTE["watch"], linestyle=":",
                   linewidth=1.0, label=f"Watch ({threshold_watch:.0f} m³/s)")
    if threshold_danger is not None:
        ax.axhline(threshold_danger, color=_PALETTE["danger"], linestyle=":",
                   linewidth=1.0, label=f"Danger ({threshold_danger:.0f} m³/s)")

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")

    ax.set_xlabel("Date")
    ax.set_ylabel("Discharge [m³/s]")
    ax.set_title(f"{title}\n{station_id}", fontsize=12)
    ax.legend(loc="upper right", fontsize=8)
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", alpha=0.3)

    _save_fig(fig, save_path)


def plot_worst_best_years(
    model_name: str,
    eval_records: list[dict[str, Any]],
    save_dir: str | Path = "reports/plots",
) -> None:
    """Generate two hydrograph plots — worst and best test year by NSE.

    eval_records: each dict must have keys:
        year (int), dates, obs, pred, NSE, station_id, horizon_days
        optionally: q_lo, q_hi
    """
    if not eval_records:
        logger.warning("No evaluation records provided for worst/best year plots.")
        return

    valid = [r for r in eval_records if isinstance(r.get("NSE"), float)
             and not np.isnan(r["NSE"])]
    if not valid:
        logger.warning("All NSE values are NaN — cannot determine worst/best year.")
        return

    worst = min(valid, key=lambda r: r["NSE"])
    best = max(valid, key=lambda r: r["NSE"])

    save_dir = Path(save_dir)
    for label, record in [("best", best), ("worst", worst)]:
        station = record.get("station_id", "unknown")
        year = record.get("year", "?")
        h = record.get("horizon_days", 1)
        nse_val = record.get("NSE", float("nan"))
        save_path = save_dir / f"{model_name}_{station}_h{h}_{label}_year_{year}.png"

        plot_hydrograph(
            dates=record["dates"],
            obs=np.asarray(record["obs"]),
            pred=np.asarray(record["pred"]),
            q_lo=np.asarray(record["q_lo"]) if "q_lo" in record else None,
            q_hi=np.asarray(record["q_hi"]) if "q_hi" in record else None,
            title=f"{model_name.upper()} — {label.capitalize()} Test Year (NSE={nse_val:.3f})",
            station_id=station,
            horizon_days=h,
            save_path=save_path,
        )


def plot_model_comparison(
    comparison: dict[str, list[dict[str, Any]]],
    metric: str = "NSE",
    save_path: str | Path = "reports/plots/model_comparison.png",
) -> None:
    """Bar chart comparing models by a chosen metric at each forecast horizon.

    Args:
        comparison: {model_name: [per_horizon_dict, ...]}
        metric:     which metric to plot (NSE, KGE, RMSE, MAE)
        save_path:  output PNG path
    """
    models = list(comparison.keys())
    if not models:
        logger.warning("Empty comparison dict passed to plot_model_comparison.")
        return

    def _extract_rows(v: Any) -> list[dict[str, Any]]:
        if isinstance(v, dict):
            return v.get("per_horizon", [])
        return v if isinstance(v, list) else []

    n_horizons = max((len(_extract_rows(v)) for v in comparison.values()), default=7)
    n_horizons = max(n_horizons, 1)
    horizons = list(range(1, n_horizons + 1))

    x = np.arange(len(horizons))
    width = 0.8 / max(len(models), 1)

    fig, ax = plt.subplots(figsize=(12, 5))

    colors = ["#0072B2", "#E69F00", "#CC79A7", "#009E73", "#F0E442", "#56B4E9"]
    for i, model in enumerate(models):
        rows = _extract_rows(comparison[model])
        vals = [
            row.get(metric, float("nan"))
            for row in rows
            if isinstance(row, dict)
        ]
        vals_clean = [v if isinstance(v, float) and not np.isnan(v) else 0.0 for v in vals]
        # Pad with 0.0 if fewer horizons than max
        while len(vals_clean) < len(horizons):
            vals_clean.append(0.0)
        offset = (i - len(models) / 2 + 0.5) * width
        ax.bar(x + offset, vals_clean[:len(horizons)], width=width,
               label=model, color=colors[i % len(colors)], alpha=0.85)

    ax.set_xlabel("Forecast Horizon (days ahead)")
    ax.set_ylabel(metric)
    ax.set_title(f"Model Comparison — {metric} by Forecast Horizon")
    ax.set_xticks(x)
    ax.set_xticklabels([f"t+{h}" for h in horizons])
    ax.legend(fontsize=9)
    ax.grid(axis="y", alpha=0.3)

    _save_fig(fig, save_path)


def plot_shap_importance(
    feature_names: list[str],
    mean_abs_shap: np.ndarray,
    model_name: str = "LightGBM",
    horizon_days: int = 1,
    top_n: int = 20,
    save_path: str | Path = "reports/plots/shap_importance.png",
) -> None:
    """Horizontal bar chart of mean |SHAP| feature importances.

    Args:
        feature_names:  list of feature column names
        mean_abs_shap:  mean absolute SHAP values per feature
        model_name:     label for the plot title
        horizon_days:   forecast horizon
        top_n:          how many top features to show
        save_path:      output PNG path
    """
    arr = np.asarray(mean_abs_shap, dtype=float)
    idx = np.argsort(arr)[::-1][:top_n]
    names = [feature_names[i] for i in idx]
    vals = arr[idx]

    fig, ax = plt.subplots(figsize=(8, max(4, top_n * 0.35)))
    bars = ax.barh(range(len(names)), vals[::-1], color=_PALETTE["predicted"], alpha=0.85)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names[::-1], fontsize=9)
    ax.set_xlabel("Mean |SHAP value|")
    ax.set_title(f"{model_name} Feature Importance — t+{horizon_days}d")
    ax.bar_label(bars, fmt="%.2f", padding=2, fontsize=8)
    ax.grid(axis="x", alpha=0.3)

    _save_fig(fig, save_path)
