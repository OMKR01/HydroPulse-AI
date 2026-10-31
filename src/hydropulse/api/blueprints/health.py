"""Health check blueprint for HydroPulse AI."""

from datetime import UTC, datetime

from flask import Blueprint, jsonify

from config.settings import settings
from src.hydropulse import __version__

health_bp = Blueprint("health", __name__, url_prefix="/api/v1")


@health_bp.route("/health", methods=["GET"])
def health_check():
    """Return system health status, service version, and timestamp.

    ---
    tags:
      - Health
    responses:
      200:
        description: Service is healthy and operational
        content:
          application/json:
            schema:
              type: object
              properties:
                status:
                  type: string
                  example: healthy
                service:
                  type: string
                  example: hydropulse-ai
                version:
                  type: string
                  example: 0.1.0
                environment:
                  type: string
                  example: development
                generated_at:
                  type: string
                  format: date-time
                data_provenance:
                  type: string
                  example: observed
                is_stale:
                  type: boolean
                  example: false
    """
    now_iso = datetime.now(UTC).isoformat()
    return jsonify(
        {
            "status": "healthy",
            "service": "hydropulse-ai",
            "version": __version__,
            "environment": settings.environment,
            "generated_at": now_iso,
            "data_provenance": "observed",
            "is_stale": False,
            "checks": {
                "api": "ok",
                "config": "loaded",
            },
        }
    ), 200
