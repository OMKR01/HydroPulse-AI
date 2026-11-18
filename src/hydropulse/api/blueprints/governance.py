"""Model governance and performance metrics endpoint."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from flask import Blueprint, jsonify

from config.settings import BASE_DIR
from src.hydropulse.api.middleware import cached
from src.hydropulse.api.schemas import ModelMetricsResponse

logger = logging.getLogger(__name__)

governance_bp = Blueprint("governance", __name__, url_prefix="/api/v1")


@governance_bp.route("/model/metrics", methods=["GET"])
@cached(ttl_seconds=300)
def get_model_metrics():
    """Retrieve comprehensive evaluation metrics for all flood and river health models."""
    metrics_path = BASE_DIR / "reports" / "metrics.json"

    if not metrics_path.exists():
        return jsonify(
            {
                "error": {
                    "status_code": 404,
                    "title": "Not Found",
                    "detail": "Model metrics file reports/metrics.json does not exist.",
                },
                "generated_at": datetime.now(UTC).isoformat(),
            }
        ), 404

    with open(metrics_path, encoding="utf-8") as f:
        metrics_json = json.load(f)

    resp = ModelMetricsResponse(
        generated_at=datetime.now(UTC).isoformat(),
        data_provenance="synthetic",
        is_stale=False,
        system=metrics_json.get("system", "HydroPulse AI"),
        metrics_generated_at=metrics_json.get("generated_at", ""),
        git_commit=metrics_json.get("git_commit"),
        metrics_data=metrics_json,
    )
    return jsonify(resp.model_dump())
