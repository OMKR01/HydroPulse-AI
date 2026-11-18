"""Vercel Serverless Function entrypoint for HydroPulse AI Flask Application.

This file serves as the WSGI application handler for Vercel serverless deployments.
It initializes the core Flask application, registers blueprints, and attaches a
path-correction WSGI middleware to normalize forwarded routes and query parameters.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode

# Ensure repository root directory is on sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Default environment configuration for serverless execution
os.environ.setdefault("FLASK_ENV", "production")
os.environ.setdefault("FLASK_DEBUG", "0")

logger = logging.getLogger("hydropulse.vercel")


class VercelPathCorrectionMiddleware:
    """WSGI middleware to normalize PATH_INFO from Vercel rewrite parameters and headers.

    When Vercel rewrites incoming traffic from /(.*) to /api/index?__path=$1,
    this middleware extracts the original destination route, strips internal
    routing parameters from QUERY_STRING, and accurately sets PATH_INFO so Flask's
    internal URL router matches the intended route (e.g., /, /dashboard, /docs,
    /api/v1/health, /static/css/dashboard.css).
    """

    def __init__(self, wsgi_app: Callable[[dict[str, Any], Callable[..., Any]], Any]) -> None:
        self.wsgi_app = wsgi_app

    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> Any:
        try:
            # 1. Primary path resolution: captured from Vercel rewrite /(.*) -> /api/index?__path=$1
            query_string = environ.get("QUERY_STRING", "")
            if "__path" in query_string:
                params = parse_qs(query_string, keep_blank_values=True)
                path_list = params.pop("__path", [""])
                raw_path = path_list[0] if path_list else ""
                environ["QUERY_STRING"] = urlencode(params, doseq=True)
                environ["PATH_INFO"] = "/" + unquote(raw_path).lstrip("/")
            else:
                # 2. Secondary fallback: proxy forwarded path headers
                forwarded_path: str | None = environ.get(
                    "HTTP_X_VERCEL_FORWARDED_PATH"
                ) or environ.get("HTTP_X_FORWARDED_PATH")
                if forwarded_path:
                    if "?" in forwarded_path:
                        forwarded_path, _ = forwarded_path.split("?", 1)
                    environ["PATH_INFO"] = "/" + unquote(forwarded_path).lstrip("/")
                elif environ.get("PATH_INFO") in ("/api/index", "/api/index.py"):
                    environ["PATH_INFO"] = "/"

            return self.wsgi_app(environ, start_response)
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            logger.error("Unhandled serverless exception: %s", exc, exc_info=True)
            status = "500 Internal Server Error"
            headers = [("Content-Type", "application/json")]
            start_response(status, headers)
            error_payload = json.dumps(
                {
                    "error": {
                        "status_code": 500,
                        "title": "Serverless Function Error",
                        "detail": str(exc),
                    }
                }
            )
            return [error_payload.encode("utf-8")]


from src.hydropulse.api.factory import create_app  # noqa: E402

# Initialize the Flask WSGI application instance
app = create_app()

# Wrap with Vercel path correction middleware
app.wsgi_app = VercelPathCorrectionMiddleware(app.wsgi_app)  # type: ignore[method-assign]
