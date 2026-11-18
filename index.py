"""Vercel Serverless Function & local WSGI entrypoint for HydroPulse AI."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

# Ensure repository root is on sys.path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Default environment configuration for serverless execution
os.environ.setdefault("FLASK_ENV", "production")
os.environ.setdefault("FLASK_DEBUG", "0")

from src.hydropulse.api.factory import create_app  # noqa: E402


class VercelPathCorrectionMiddleware:
    """WSGI middleware to normalize PATH_INFO from Vercel rewrite headers."""

    def __init__(self, wsgi_app: Callable[[dict[str, Any], Callable[..., Any]], Any]) -> None:
        self.wsgi_app = wsgi_app

    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> Any:
        forwarded_path: str | None = (
            environ.get("HTTP_X_VERCEL_FORWARDED_PATH")
            or environ.get("HTTP_X_FORWARDED_PATH")
            or environ.get("HTTP_X_MATCHED_PATH")
        )
        if forwarded_path:
            if "?" in forwarded_path:
                forwarded_path, _ = forwarded_path.split("?", 1)
            environ["PATH_INFO"] = forwarded_path
        return self.wsgi_app(environ, start_response)


# Initialize Flask WSGI application instance
app = create_app()

# Wrap with Vercel path correction middleware
app.wsgi_app = VercelPathCorrectionMiddleware(app.wsgi_app)  # type: ignore[method-assign]

if __name__ == "__main__":
    from config.settings import settings

    app.run(host=settings.host, port=settings.port, debug=settings.debug)
