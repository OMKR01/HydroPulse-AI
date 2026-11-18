"""Public exports for the evaluation subpackage."""

from src.hydropulse.evaluation.events import (
    compute_false_alarm_analysis,
    evaluate_single_event,
    generate_event_validation_markdown,
    load_historical_events,
    run_full_event_validation,
)
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
    "nse",
    "kge",
    "rmse",
    "mae",
    "pbias",
    "alert_metrics",
    "peak_timing_error",
    "per_horizon_metrics",
    "compute_quantile_coverage",
    "write_metrics_json",
    "plot_hydrograph",
    "plot_worst_best_years",
    "plot_model_comparison",
    "plot_shap_importance",
    "load_historical_events",
    "evaluate_single_event",
    "compute_false_alarm_analysis",
    "run_full_event_validation",
    "generate_event_validation_markdown",
]
