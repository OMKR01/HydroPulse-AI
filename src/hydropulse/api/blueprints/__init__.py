"""API Blueprints."""

from src.hydropulse.api.blueprints.governance import governance_bp
from src.hydropulse.api.blueprints.health import health_bp
from src.hydropulse.api.blueprints.risk import risk_bp
from src.hydropulse.api.blueprints.river_health import river_health_bp
from src.hydropulse.api.blueprints.stations import stations_bp

__all__ = [
    "health_bp",
    "stations_bp",
    "risk_bp",
    "river_health_bp",
    "governance_bp",
]
