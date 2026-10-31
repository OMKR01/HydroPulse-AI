"""Tests for pipeline stub entry points."""

from unittest.mock import patch

from src.hydropulse.pipeline.refresh import main as refresh_main
from src.hydropulse.pipeline.train import main as train_main


def test_refresh_stub():
    """Verify refresh main entry point returns 0."""
    with patch(
        "src.hydropulse.pipeline.refresh.run_refresh_pipeline",
        return_value={
            "stations_selected": 5,
            "weather_records_ingested": 10,
            "discharge_records_ingested": 10,
            "wq_records_ingested": 6,
            "duration_seconds": 0.5,
            "sources": {
                "openmeteo_weather": {"status": "success", "stale": False},
                "openmeteo_flood": {"status": "success", "stale": False},
            },
        },
    ):
        exit_code = refresh_main([])
        assert exit_code == 0


def test_train_stub():
    """Verify train main entry point returns 0."""
    exit_code = train_main()
    assert exit_code == 0
