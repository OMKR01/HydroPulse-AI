"""Public exports for the models subpackage."""

from src.hydropulse.models.baselines import (
    ClimatologyBaseline,
    PersistenceBaseline,
    RidgeBaseline,
    get_all_baselines,
    raw_glofas_baseline,
)
from src.hydropulse.models.drought import (
    DroughtAssessment,
    DroughtOutlook,
    StationDroughtEvaluator,
    compute_30d_drought_outlook,
    compute_low_flow_threshold,
    evaluate_drought_status,
    is_low_flow_stress,
)
from src.hydropulse.models.lgbm import LGBMForecaster
from src.hydropulse.models.quantile import QuantileLGBMForecaster
from src.hydropulse.models.wqi import (
    HotspotAssessment,
    MannKendallResult,
    NextMonthWQIClassifier,
    SeasonalDecompositionResult,
    WQIScore,
    calculate_wqi,
    classify_cpcb_use,
    detect_pollution_hotspots,
    mann_kendall_test,
    seasonal_decompose_monthly,
)

try:
    from src.hydropulse.models.lstm import MultiStationLSTM, PerStationLSTM
except Exception:
    MultiStationLSTM = None  # type: ignore
    PerStationLSTM = None  # type: ignore

__all__ = [
    "PersistenceBaseline",
    "ClimatologyBaseline",
    "RidgeBaseline",
    "get_all_baselines",
    "raw_glofas_baseline",
    "LGBMForecaster",
    "QuantileLGBMForecaster",
    "PerStationLSTM",
    "MultiStationLSTM",
    # Phase 4 drought exports
    "compute_low_flow_threshold",
    "is_low_flow_stress",
    "evaluate_drought_status",
    "compute_30d_drought_outlook",
    "StationDroughtEvaluator",
    "DroughtAssessment",
    "DroughtOutlook",
    # Phase 4 water quality exports
    "calculate_wqi",
    "classify_cpcb_use",
    "mann_kendall_test",
    "seasonal_decompose_monthly",
    "detect_pollution_hotspots",
    "NextMonthWQIClassifier",
    "WQIScore",
    "MannKendallResult",
    "SeasonalDecompositionResult",
    "HotspotAssessment",
]
