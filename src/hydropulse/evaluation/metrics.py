"""Hydrological evaluation metrics for HydroPulse AI.

All functions return plain Python dicts or floats — no hard-typed numbers are
written to docs. Callers write to reports/metrics.json via write_metrics_json().

Metrics implemented:
    NSE       : Nash-Sutcliffe Efficiency
    KGE       : Kling-Gupta Efficiency (Gupta et al. 2009)
    RMSE      : Root Mean Squared Error [m3/s]
    MAE       : Mean Absolute Error [m3/s]
    PBIAS     : Percent Bias [%]
    alert_metrics : POD, FAR, CSI, F1, PR-AUC (binary event detection)
    peak_timing_error : signed lag in days between observed and predicted peak
    per_horizon_metrics : aggregates the above for each of h=1..7
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics import average_precision_score

logger = logging.getLogger(__name__)

# ─────────────────────────────── core scalar metrics ──────────────────────────


def nse(obs: np.ndarray, pred: np.ndarray) -> float:
    """Nash-Sutcliffe Efficiency.

    Perfect model -> 1.0.  Predicting the mean -> 0.0.  Worse than mean -> negative.
    Reference: Nash & Sutcliffe (1970).
    """
    obs = np.asarray(obs, dtype=float)
    pred = np.asarray(pred, dtype=float)
    mask = ~(np.isnan(obs) | np.isnan(pred))
    if mask.sum() < 2:
        return float("nan")
    o, p = obs[mask], pred[mask]
    ss_res = float(np.sum((o - p) ** 2))
    ss_tot = float(np.sum((o - np.mean(o)) ** 2))
    if ss_tot < 1e-12:
        return float("nan")
    return 1.0 - ss_res / ss_tot


def kge(obs: np.ndarray, pred: np.ndarray) -> float:
    """Kling-Gupta Efficiency.

    Decomposes into correlation (r), variability ratio (alpha), and bias ratio (beta).
    Perfect model -> 1.0.  Reference: Gupta et al. (2009) J. Hydrology.
    """
    obs = np.asarray(obs, dtype=float)
    pred = np.asarray(pred, dtype=float)
    mask = ~(np.isnan(obs) | np.isnan(pred))
    if mask.sum() < 3:
        return float("nan")
    o, p = obs[mask], pred[mask]
    r = float(np.corrcoef(o, p)[0, 1])
    std_o = float(np.std(o))
    std_p = float(np.std(p))
    mean_o = float(np.mean(o))
    mean_p = float(np.mean(p))
    alpha = std_p / std_o if std_o > 1e-12 else float("nan")
    beta = mean_p / mean_o if mean_o > 1e-12 else float("nan")
    if any(np.isnan(v) for v in [r, alpha, beta]):
        return float("nan")
    return float(1.0 - np.sqrt((r - 1.0) ** 2 + (alpha - 1.0) ** 2 + (beta - 1.0) ** 2))


def rmse(obs: np.ndarray, pred: np.ndarray) -> float:
    """Root Mean Squared Error [m3/s]."""
    obs = np.asarray(obs, dtype=float)
    pred = np.asarray(pred, dtype=float)
    mask = ~(np.isnan(obs) | np.isnan(pred))
    if mask.sum() == 0:
        return float("nan")
    return float(np.sqrt(np.mean((obs[mask] - pred[mask]) ** 2)))


def mae(obs: np.ndarray, pred: np.ndarray) -> float:
    """Mean Absolute Error [m3/s]."""
    obs = np.asarray(obs, dtype=float)
    pred = np.asarray(pred, dtype=float)
    mask = ~(np.isnan(obs) | np.isnan(pred))
    if mask.sum() == 0:
        return float("nan")
    return float(np.mean(np.abs(obs[mask] - pred[mask])))


def pbias(obs: np.ndarray, pred: np.ndarray) -> float:
    """Percent Bias [%]. Positive -> model over-estimates."""
    obs = np.asarray(obs, dtype=float)
    pred = np.asarray(pred, dtype=float)
    mask = ~(np.isnan(obs) | np.isnan(pred))
    if mask.sum() == 0 or np.sum(np.abs(obs[mask])) < 1e-12:
        return float("nan")
    return float(100.0 * np.sum(pred[mask] - obs[mask]) / np.sum(np.abs(obs[mask])))


# ─────────────────────────────── alert / event metrics ────────────────────────


def alert_metrics(
    obs: np.ndarray,
    pred: np.ndarray,
    threshold: float,
) -> dict[str, Any]:
    """Compute binary alert detection metrics.

    An alert is issued when predicted discharge >= threshold.
    An observed event is when observed discharge >= threshold.

    Returns dict with keys: POD, FAR, CSI, F1, PR_AUC, TP, FP, FN, TN.
    """
    obs = np.asarray(obs, dtype=float)
    pred = np.asarray(pred, dtype=float)
    mask = ~(np.isnan(obs) | np.isnan(pred))

    _nan_result: dict[str, Any] = {
        "POD": float("nan"), "FAR": float("nan"), "CSI": float("nan"),
        "F1": float("nan"), "PR_AUC": float("nan"),
        "TP": 0, "FP": 0, "FN": 0, "TN": 0,
    }
    if mask.sum() == 0:
        return _nan_result

    o, p = obs[mask], pred[mask]
    obs_event = o >= threshold
    pred_event = p >= threshold

    tp = int(np.sum(obs_event & pred_event))
    fp = int(np.sum(~obs_event & pred_event))
    fn = int(np.sum(obs_event & ~pred_event))
    tn = int(np.sum(~obs_event & ~pred_event))

    pod = tp / (tp + fn) if (tp + fn) > 0 else float("nan")
    far_val = fp / (tp + fp) if (tp + fp) > 0 else float("nan")
    csi_val = tp / (tp + fp + fn) if (tp + fp + fn) > 0 else float("nan")
    prec = tp / (tp + fp) if (tp + fp) > 0 else float("nan")

    if not (np.isnan(prec) or np.isnan(pod)) and (prec + pod) > 0:
        f1_val = 2.0 * prec * pod / (prec + pod)
    else:
        f1_val = float("nan")

    try:
        pr_auc = float(average_precision_score(obs_event.astype(int), p))
    except ValueError:
        pr_auc = float("nan")

    def _r(v: float) -> float:
        return round(v, 4) if not np.isnan(v) else float("nan")

    return {
        "POD": _r(pod), "FAR": _r(far_val), "CSI": _r(csi_val),
        "F1": _r(f1_val), "PR_AUC": _r(pr_auc),
        "TP": tp, "FP": fp, "FN": fn, "TN": tn,
    }


def peak_timing_error(
    obs: np.ndarray,
    pred: np.ndarray,
    window: int = 7,
) -> float:
    """Signed peak-timing error in days (pred_peak_idx - obs_peak_idx).

    Divides the series into non-overlapping windows of `window` days, finds
    local peaks in each window, and averages the signed day-differences.
    Positive -> model peaks late; negative -> peaks early.
    """
    obs = np.asarray(obs, dtype=float)
    pred = np.asarray(pred, dtype=float)
    n = min(len(obs), len(pred))
    errors: list[float] = []
    for start in range(0, n - window, window):
        end = start + window
        o_seg = obs[start:end]
        p_seg = pred[start:end]
        if np.any(np.isnan(o_seg)) or np.any(np.isnan(p_seg)):
            continue
        errors.append(float(np.argmax(p_seg) - np.argmax(o_seg)))
    return float(np.mean(errors)) if errors else float("nan")


# ─────────────────────────────── per-horizon aggregation ──────────────────────


def per_horizon_metrics(
    obs_matrix: np.ndarray,
    pred_matrix: np.ndarray,
    threshold: float | None = None,
    horizons: int = 7,
) -> list[dict[str, Any]]:
    """Compute NSE, KGE, RMSE, MAE, PBIAS (and optionally alert metrics) per horizon.

    Args:
        obs_matrix:  shape (n_samples, n_horizons) — observed discharge targets
        pred_matrix: shape (n_samples, n_horizons) — predicted discharge
        threshold:   if provided, also compute alert metrics per horizon
        horizons:    number of forecast horizons (default 7 = t+1 ... t+7)

    Returns:
        List of dicts, one per horizon h=1..horizons.
    """
    obs_matrix = np.asarray(obs_matrix, dtype=float)
    pred_matrix = np.asarray(pred_matrix, dtype=float)
    results: list[dict[str, Any]] = []

    for h in range(horizons):
        o = obs_matrix[:, h] if obs_matrix.ndim == 2 else obs_matrix
        p = pred_matrix[:, h] if pred_matrix.ndim == 2 else pred_matrix

        row: dict[str, Any] = {
            "horizon_days": h + 1,
            "NSE": round(nse(o, p), 4),
            "KGE": round(kge(o, p), 4),
            "RMSE": round(rmse(o, p), 4),
            "MAE": round(mae(o, p), 4),
            "PBIAS": round(pbias(o, p), 4),
            "peak_timing_error_days": round(peak_timing_error(o, p), 4),
            "n_samples": int(np.sum(~np.isnan(o))),
        }

        if threshold is not None:
            am = alert_metrics(o, p, threshold)
            row.update({f"alert_{k}": v for k, v in am.items()})

        results.append(row)

    return results


def compute_quantile_coverage(
    obs: np.ndarray,
    q_lo: np.ndarray,
    q_hi: np.ndarray,
) -> float:
    """Fraction of observations falling inside the [q_lo, q_hi] prediction interval.

    For a calibrated 80% (P10-P90) band, target coverage >= 0.75.
    """
    obs = np.asarray(obs, dtype=float)
    q_lo = np.asarray(q_lo, dtype=float)
    q_hi = np.asarray(q_hi, dtype=float)
    mask = ~(np.isnan(obs) | np.isnan(q_lo) | np.isnan(q_hi))
    if mask.sum() == 0:
        return float("nan")
    inside = (obs[mask] >= q_lo[mask]) & (obs[mask] <= q_hi[mask])
    return float(np.mean(inside))


# ─────────────────────────────── metrics.json writer ──────────────────────────


def write_metrics_json(
    run_record: dict[str, Any],
    metrics_path: str | Path | None = None,
) -> None:
    """Append a run record to reports/metrics.json (never hand-typed numbers).

    run_record should include keys:
        run_id, model_name, station_id, generated_at, git_commit,
        data_hash, split_config, per_horizon (list[dict])
    """
    import datetime

    path = Path(metrics_path or "reports/metrics.json")
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        with open(path, encoding="utf-8") as fh:
            existing: dict[str, Any] = json.load(fh)
    else:
        existing = {
            "system": "HydroPulse AI",
            "generated_at": None,
            "git_commit": None,
            "runs": [],
            "current_best": {},
            "baseline_comparison": {},
            "note": (
                "Metrics are generated by evaluation scripts into this file; "
                "docs read from it. Never hand-type a number."
            ),
        }

    existing["runs"].append(run_record)
    existing["generated_at"] = datetime.datetime.utcnow().isoformat() + "Z"

    # Update current_best: track highest test NSE per station per horizon
    model = run_record.get("model_name", "unknown")
    station = run_record.get("station_id", "unknown")
    for hrow in run_record.get("per_horizon", []):
        h = hrow.get("horizon_days", "?")
        key = f"{station}|h{h}"
        current_nse = existing["current_best"].get(key, {}).get("NSE", -9999.0)
        new_nse = hrow.get("NSE")
        if isinstance(new_nse, float) and not np.isnan(new_nse) and new_nse > current_nse:
            existing["current_best"][key] = {
                "model": model,
                "NSE": new_nse,
                "KGE": hrow.get("KGE"),
                "RMSE": hrow.get("RMSE"),
            }

    def _json_default(x: Any) -> Any:
        if isinstance(x, float) and np.isnan(x):
            return None
        return str(x)

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(existing, fh, indent=2, default=_json_default)

    logger.info("Updated %s with run %s", path, run_record.get("run_id", "?"))
