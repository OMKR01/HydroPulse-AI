"""Unit and contract tests for Phase 7 historical flood event validation."""

from __future__ import annotations

import tempfile

import numpy as np
import pandas as pd
import pytest
import yaml

from src.hydropulse.evaluation.events import (
    compute_false_alarm_analysis,
    evaluate_single_event,
    generate_event_validation_markdown,
    load_historical_events,
    load_station_event_series,
    run_full_event_validation,
)


def test_load_historical_events_contract():
    """Test that data/events/historical_floods.yaml conforms to integrity rules."""
    events = load_historical_events()
    assert len(events) >= 5, f"Expected at least 5 documented events, got {len(events)}"

    required_keys = {
        "id",
        "title",
        "start_date",
        "end_date",
        "peak_date",
        "basin",
        "stations_affected",
        "description",
        "source_url",
        "source_publisher",
    }

    for ev in events:
        for k in required_keys:
            assert k in ev, f"Event {ev.get('id')} missing mandatory key: {k}"

        assert ev["basin"] in ["Damodar", "Subarnarekha"]
        assert len(ev["stations_affected"]) >= 1
        assert ev["source_url"].startswith("http"), f"Invalid source URL: {ev['source_url']}"
        assert pd.to_datetime(ev["start_date"]) <= pd.to_datetime(ev["end_date"])
        assert pd.to_datetime(ev["start_date"]) <= pd.to_datetime(ev["peak_date"]) <= pd.to_datetime(ev["end_date"])


def test_load_historical_events_invalid_file_raises():
    """Test that missing or malformed YAML raises FileNotFoundError or ValueError."""
    with pytest.raises(FileNotFoundError):
        load_historical_events("non_existent_file.yaml")

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump({"events": [{"id": "bad_event"}]}, f)
        temp_path = f.name

    with pytest.raises(ValueError, match="missing required keys"):
        load_historical_events(temp_path)


def test_load_station_event_series_shape_and_provenance():
    """Test series loading returns dates and valid discharge columns."""
    df = load_station_event_series("damodar_bokaro", "2021-07-29", "2021-08-03", buffer_days=7)
    assert len(df) >= 14
    assert "date" in df.columns
    assert "discharge" in df.columns
    assert "glofas_discharge" in df.columns
    assert df["discharge"].min() >= 0.0


def test_evaluate_single_event_hit_and_lead_time():
    """Test evaluation on an event where predicted discharge breaches threshold."""
    event = {
        "id": "test_flood",
        "title": "Test Flood",
        "start_date": "2021-08-01",
        "end_date": "2021-08-05",
        "peak_date": "2021-08-03",
        "basin": "Damodar",
        "stations_affected": ["damodar_bokaro"],
        "description": "Test event",
        "source_url": "https://example.com/flood",
        "source_publisher": "Test",
    }

    dates = pd.date_range("2021-08-01", "2021-08-05", freq="D")
    df = pd.DataFrame({
        "date": dates,
        "discharge": [50.0, 180.0, 300.0, 160.0, 60.0],
        "glofas_discharge": [45.0, 160.0, 260.0, 140.0, 55.0],
    })

    thresholds = {"watch": 150.0, "warning": 200.0, "danger": 280.0}
    res = evaluate_single_event(event, "damodar_bokaro", df, thresholds)

    assert res["event_id"] == "test_flood"
    assert res["event_severity"] == "DANGER"
    assert res["obs_peak_discharge"] == 300.0

    hp_m = res["models"]["hydropulse_ai"]
    assert hp_m["hit"] is True
    assert hp_m["lead_time_days"] >= 1
    assert hp_m["peak_timing_error_days"] == 0


def test_evaluate_single_event_miss():
    """Test evaluation when model predicts low flow below threshold."""
    event = {
        "id": "test_flood_miss",
        "title": "Test Miss",
        "start_date": "2021-08-01",
        "end_date": "2021-08-03",
        "peak_date": "2021-08-02",
        "basin": "Subarnarekha",
        "stations_affected": ["subarnarekha_jamshedpur"],
        "description": "Test miss",
        "source_url": "https://example.com/flood",
        "source_publisher": "Test",
    }

    dates = pd.date_range("2021-08-01", "2021-08-03", freq="D")
    # Low discharge
    df = pd.DataFrame({
        "date": dates,
        "discharge": [40.0, 50.0, 45.0],
        "glofas_discharge": [35.0, 42.0, 38.0],
    })

    thresholds = {"watch": 150.0, "warning": 200.0, "danger": 280.0}
    res = evaluate_single_event(event, "subarnarekha_jamshedpur", df, thresholds)

    assert res["event_severity"] == "NORMAL"
    assert res["models"]["hydropulse_ai"]["hit"] is False
    assert res["models"]["hydropulse_ai"]["lead_time_days"] == 0


def test_compute_false_alarm_analysis():
    """Test false alarm calculation on non-event periods."""
    dates = pd.date_range("2021-01-01", "2021-01-30", freq="D")
    # Normal lean-season discharge ~20 m3/s, with one false spike
    discharge = np.full(30, 20.0)
    discharge_pred = np.full(30, 20.0)
    discharge_pred[5] = 165.0  # Spurious prediction above 150 threshold

    df = pd.DataFrame({
        "date": dates,
        "discharge": discharge,
        "discharge_pred": discharge_pred,
    })

    event_windows = [("2021-08-01", "2021-08-05")]
    res = compute_false_alarm_analysis("damodar_ramgarh", df, threshold=150.0, event_windows=event_windows)

    assert res["non_event_days"] == 30
    assert res["false_positives"] == 1
    assert res["true_negatives"] == 29
    assert res["POFD"] > 0.0


def test_run_full_event_validation_and_markdown(tmp_path):
    """Test end-to-end event validation and markdown report generation."""
    results = run_full_event_validation()
    assert results["events_count"] >= 5
    assert results["total_evaluations"] >= 10
    assert "hydropulse_ai" in results["model_summary"]
    assert "raw_glofas" in results["model_summary"]

    # Verify report writing
    md_path = tmp_path / "event_validation.md"
    generate_event_validation_markdown(results, md_path)
    assert md_path.exists()
    content = md_path.read_text(encoding="utf-8")
    assert "# Historical Flood Validation Report" in content
    assert "HydroPulse AI (Hybrid LGBM)" in content
    assert "Raw GloFAS v4 Forcing" in content
