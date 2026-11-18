"""Web blueprint serving the HydroPulse AI interactive monitoring dashboard."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Blueprint, render_template

from config.settings import settings
from src.hydropulse import __version__

# Indian Standard Time (UTC+05:30) for Jharkhand river telemetry
IST = timezone(timedelta(hours=5, minutes=30))
_WEB_DIR = Path(__file__).resolve().parent

web_bp = Blueprint(
    "web",
    __name__,
    template_folder=str(_WEB_DIR / "templates"),
    static_folder=str(_WEB_DIR / "static"),
    static_url_path="/static",
)


@web_bp.route("/dashboard", methods=["GET"])
def dashboard():
    """Render the main interactive dashboard interface."""
    now_ist = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    return render_template(
        "dashboard.html",
        version=__version__,
        environment=settings.environment,
        last_updated=now_ist,
        default_lang="en",
        mapbox_token=getattr(settings, "mapbox_access_token", ""),
    )
