"""Web blueprint serving the HydroPulse AI interactive monitoring dashboard."""

from __future__ import annotations

from datetime import UTC, datetime

from flask import Blueprint, render_template

from config.settings import settings
from src.hydropulse import __version__

web_bp = Blueprint(
    "web",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/static",
)


@web_bp.route("/dashboard", methods=["GET"])
def dashboard():
    """Render the main interactive dashboard interface."""
    now_iso = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    return render_template(
        "dashboard.html",
        version=__version__,
        environment=settings.environment,
        last_updated=now_iso,
        default_lang="en",
    )
