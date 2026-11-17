"""Tests for pipeline stub entry points."""

from unittest.mock import MagicMock, patch

from src.hydropulse.pipeline.refresh import (
    main as refresh_main,
)
from src.hydropulse.pipeline.refresh import (
    start_background_scheduler,
    start_blocking_scheduler,
)
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


def test_refresh_daemon_flag():
    """Verify refresh main CLI parses daemon flag and triggers blocking scheduler."""
    with patch("src.hydropulse.pipeline.refresh.start_blocking_scheduler") as mock_sched:
        exit_code = refresh_main(["--daemon", "--interval-hours", "12", "--stations", "3"])
        assert exit_code == 0
        mock_sched.assert_called_once_with(interval_hours=12, limit_stations=3)


def test_start_background_scheduler():
    """Verify start_background_scheduler configures and starts a background job."""
    with (
        patch("apscheduler.schedulers.background.BackgroundScheduler.start") as mock_start,
        patch("apscheduler.schedulers.background.BackgroundScheduler.add_job") as mock_add_job,
    ):
        scheduler = start_background_scheduler(interval_hours=4)
        assert scheduler is not None
        mock_add_job.assert_called_once()
        mock_start.assert_called_once()


def test_start_blocking_scheduler():
    """Verify start_blocking_scheduler initializes first run and blocks."""
    mock_blocking_inst = MagicMock()
    with (
        patch("apscheduler.schedulers.blocking.BlockingScheduler", return_value=mock_blocking_inst),
        patch("src.hydropulse.pipeline.refresh.run_refresh_pipeline") as mock_run,
    ):
        scheduler = start_blocking_scheduler(interval_hours=8, limit_stations=2)
        assert scheduler is not None
        mock_run.assert_called_once_with(limit_stations=2)
        mock_blocking_inst.add_job.assert_called_once()
        mock_blocking_inst.start.assert_called_once()


def test_train_stub():
    """Verify train main entry point returns 0."""
    with patch(
        "src.hydropulse.pipeline.train.run_training",
        return_value={"status": "mocked"},
    ):
        exit_code = train_main([])
        assert exit_code == 0
