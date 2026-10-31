"""Pytest fixtures for HydroPulse AI."""

import pytest
from flask import Flask
from flask.testing import FlaskClient

from src.hydropulse.api.factory import create_app


@pytest.fixture
def app() -> Flask:
    """Create and configure a testing Flask app instance."""
    test_app = create_app(
        {
            "TESTING": True,
            "DEBUG": False,
            "ENV": "testing",
        }
    )
    return test_app


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """Return a Flask test client."""
    return app.test_client()
