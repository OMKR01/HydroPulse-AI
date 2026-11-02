"""Public exports for the evaluation subpackage."""

from src.hydropulse.evaluation.metrics import (
    alert_metrics,
    compute_quantile_coverage,
    kge,
    mae,
    nse,
    pbias,
    peak_timing_error,
    per_horizon_metrics,
    rmse,
    write_metrics_json,
)
from src.hydropulse.evaluation.plots import (
    plot_hydrograph,
    plot_model_comparison,
    plot_shap_importance,
    plot_worst_best_years,
)

__all__ = [
    "nse", "kge", "rmse", "mae", "pbias",
    "alert_metrics", "peak_timing_error", "per_horizon_metrics",
    "compute_quantile_coverage", "write_metrics_json",
    "plot_hydrograph", "plot_worst_best_years",
    "plot_model_comparison", "plot_shap_importance",
]
