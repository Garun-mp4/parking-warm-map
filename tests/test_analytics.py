import pytest
from pydantic import ValidationError
from backend.analytics import summary, Stabilizer, metrics
from backend.schemas import Layout, Settings


def result(states, times=None, duration=60):
    times = times or [0, 30, 60]
    return {
        "source_duration_seconds": duration,
        "slots": [
            {"id": "1", "name": "One", "points": [[0, 0], [1, 0], [1, 1], [0, 1]]}
        ],
        "samples": [
            {"source_seconds": t, "video_seconds": i * 2, "states": [s]}
            for i, (t, s) in enumerate(zip(times, states))
        ],
    }


def test_time_weighted_occupancy_and_censored_last_sample():
    data = summary(result([1, 0, 1]))
    assert data["occupancy"] == 50
    assert data["slots"][0]["occupied_seconds"] == 30
    assert data["slots"][0]["changes"] == 1


def test_unknown_is_not_free_and_empty_denominator_is_not_zero():
    data = summary(result([1, -1, 0]))
    assert data["occupancy"] == 100
    assert data["coverage"] == 50
    assert data["slots"][0]["unknown_seconds"] == 30
    assert summary(result([-1, -1, -1]))["occupancy"] is None


def test_irregular_real_timestamps_not_video_fps():
    data = summary(result([1, 0, 0], [0, 10, 60]))
    assert data["occupancy"] == pytest.approx(16.67)
    clipped = summary(result([1, 0, 0]), 15, 45)
    assert clipped["occupancy"] == 50
    with pytest.raises(ValueError):
        summary(result([1, 0, 0]), 20, 10)
    between = summary(result([1, 0, 0]), 5, 10)
    assert between["peak_occupied"] == 1
    assert [r["time"] for r in between["timeline"]] == [5, 10]


def test_transient_missed_detection_does_not_release_immediately():
    smoothing = Stabilizer(1, 2)
    assert smoothing.step([1], 0) == [1]
    assert smoothing.step([0], 1) == [1]
    assert smoothing.step([1], 2) == [1]
    assert smoothing.step([0], 3) == [1]
    assert smoothing.step([0], 5) == [0]
    assert smoothing.step([-1], 6) == [-1]
    assert smoothing.step([1], 7) == [0]
    assert smoothing.step([1], 9) == [1]


def test_polygon_validation_rejects_crossing_outside_duplicate_ids():
    slot = {"id": "a", "name": "A", "points": [[0, 0], [1, 0], [1, 1], [0, 1]]}
    assert len(Layout(slots=[slot]).slots) == 1
    with pytest.raises(ValidationError):
        Layout(slots=[slot, slot])
    with pytest.raises(ValidationError):
        Layout(slots=[{**slot, "points": [[0, 0], [1, 1], [1, 0], [0, 1]]}])
    with pytest.raises(ValidationError):
        Layout(slots=[{**slot, "points": [[0, 0], [2, 0], [1, 1]]}])
    with pytest.raises(ValidationError):
        Settings(model="malexnet", confidence=0.2)


def test_abstentions_penalize_recall_in_quality_report():
    report = metrics([1, 1, 0], [1, -1, 0])
    assert report["recall"] == 0.5
    assert report["coverage"] == pytest.approx(2 / 3)
