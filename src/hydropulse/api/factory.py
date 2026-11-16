import logging
from datetime import UTC, datetime
from typing import Any

from flask import Flask, g, jsonify
from flask_cors import CORS

from config.settings import settings
from src.hydropulse import __version__
from src.hydropulse.api.blueprints.governance import governance_bp
from src.hydropulse.api.blueprints.health import health_bp
from src.hydropulse.api.blueprints.risk import risk_bp
from src.hydropulse.api.blueprints.river_health import river_health_bp
from src.hydropulse.api.blueprints.stations import stations_bp
from src.hydropulse.api.docs import docs_bp
from src.hydropulse.api.middleware import setup_middleware


def configure_logging(app: Flask) -> None:
    """Set up structured console logging."""
    log_level = logging.DEBUG if app.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def register_error_handlers(app: Flask) -> None:
    """Register standard JSON error envelopes for API exceptions."""

    def json_error(status_code: int, title: str, detail: str):
        now_iso = datetime.now(UTC).isoformat()
        req_id = getattr(g, "request_id", None)
        return (
            jsonify({
                "error": {
                    "status_code": status_code,
                    "title": title,
                    "detail": detail,
                },
                "generated_at": now_iso,
                "service": "hydropulse-ai",
                "version": __version__,
                "request_id": req_id,
            }),
            status_code,
        )

    @app.errorhandler(400)
    def bad_request(err):
        return json_error(400, "Bad Request", str(getattr(err, "description", err)))

    @app.errorhandler(404)
    def not_found(err):
        return json_error(404, "Not Found", str(getattr(err, "description", err)))

    @app.errorhandler(405)
    def method_not_allowed(err):
        return json_error(405, "Method Not Allowed", str(getattr(err, "description", err)))

    @app.errorhandler(429)
    def too_many_requests(err):
        return json_error(429, "Too Many Requests", str(getattr(err, "description", err)))

    @app.errorhandler(500)
    def internal_server_error(err):
        return json_error(
            500, "Internal Server Error", "An unexpected internal server error occurred."
        )


def create_app(config_override: dict[str, Any] | None = None) -> Flask:
    """Create and configure an instance of the Flask application."""
    app = Flask(
        __name__,
        static_folder="../web/static",
        template_folder="../web/templates",
    )

    # Core configuration
    app.config["SECRET_KEY"] = settings.secret_key
    app.config["ENV"] = settings.environment
    app.config["DEBUG"] = settings.debug
    app.config["JSON_SORT_KEYS"] = False

    if config_override:
        app.config.update(config_override)

    # Explicit CORS configuration per AGENTS.md rule 7
    CORS(
        app,
        resources={r"/api/*": {"origins": "*"}},
        methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
    )

    configure_logging(app)
    register_error_handlers(app)
    setup_middleware(app)

    # Register blueprints
    app.register_blueprint(health_bp)
    app.register_blueprint(stations_bp)
    app.register_blueprint(risk_bp)
    app.register_blueprint(river_health_bp)
    app.register_blueprint(governance_bp)
    app.register_blueprint(docs_bp)

    @app.route("/")
    def index():
        """Root landing route redirecting to /docs or API information."""
        return jsonify({
            "service": "HydroPulse AI",
            "description": "Jharkhand River Health Monitoring & Early Warning System",
            "version": __version__,
            "docs_url": "/docs",
            "health_url": "/api/v1/health",
            "advisory": (
                "Official warnings are issued by the Central Water Commission (CWC) "
                "and Jharkhand State Disaster Management Authority (JSDMA)."
            ),
        })

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host=settings.host, port=settings.port, debug=settings.debug)
