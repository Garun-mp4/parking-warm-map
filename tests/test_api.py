from fastapi.testclient import TestClient
import json
import cv2
import numpy as np
import pytest
from backend import store
from backend import app as module


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB", tmp_path / "test.sqlite3")
    monkeypatch.setattr(module, "DATA", tmp_path)
    (tmp_path / "projects").mkdir()
    with TestClient(module.app) as client:
        yield client


def test_project_layout_invalid_polygon_and_missing_project(client):
    pid = store.create_project("Test", {"kind": "video"})
    assert client.get("/api/projects/missing").status_code == 404
    bad = {
        "slots": [{"id": "a", "name": "A", "points": [[0, 0], [1, 1], [1, 0], [0, 1]]}]
    }
    assert client.put(f"/api/projects/{pid}/layout", json=bad).status_code == 422
    good = {
        "slots": [{"id": "a", "name": "A", "points": [[0, 0], [1, 0], [1, 1], [0, 1]]}]
    }
    assert client.put(f"/api/projects/{pid}/layout", json=good).json()["revision"] == 2
    assert client.put(f"/api/projects/{pid}/layout", json=good).json()["revision"] == 2
    assert (
        client.post(
            f"/api/projects/{pid}/analyses", json={"model": "invalid"}
        ).status_code
        == 422
    )


def test_global_one_analysis_and_cancellation_are_persisted(client):
    slot = {"id": "a", "name": "A", "points": [[0, 0], [1, 0], [1, 1], [0, 1]]}
    pid = store.create_project("Test", {"kind": "video"}, [slot])
    run_id = store.create_run(store.project(pid), {})
    with pytest.raises(ValueError):
        store.create_run(store.project(pid), {})
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 200
    assert store.run(run_id)["cancel_requested"] == 1
    assert client.get(f"/api/runs/{run_id}/result").status_code == 409
    store.update_run(run_id, status="completed")
    assert client.post(f"/api/runs/{run_id}/cancel").status_code == 409


def test_real_upload_decode_browser_video_and_corrupt_file(client, tmp_path):
    source = tmp_path / "fixture.avi"
    writer = cv2.VideoWriter(
        str(source), cv2.VideoWriter_fourcc(*"MJPG"), 10, (200, 150)
    )
    for i in range(20):
        writer.write(np.full((150, 200, 3), i * 10, np.uint8))
    writer.release()
    with source.open("rb") as f:
        response = client.post(
            "/api/projects/upload",
            data={"title": "Uploaded"},
            files={"file": ("fixture.avi", f, "video/avi")},
        )
    assert response.status_code == 201, response.text
    project = response.json()
    assert project["slots"] == []
    assert project["metadata"]["video_duration_seconds"] == pytest.approx(2, abs=0.1)
    assert (
        client.get(
            f"/api/projects/{project['id']}/video", headers={"Range": "bytes=0-99"}
        ).status_code
        == 206
    )
    assert (
        client.post(f"/api/projects/{project['id']}/analyses", json={}).status_code
        == 422
    )
    corrupt = client.post(
        "/api/projects/upload", files={"file": ("bad.mp4", b"not a video", "video/mp4")}
    )
    assert corrupt.status_code == 422


def test_video_first_poster_matches_initial_timestamp_not_editor_midday(
    client, tmp_path
):
    first = tmp_path / "first.jpg"
    middle = tmp_path / "middle.jpg"
    first.write_bytes(b"first actual capture")
    middle.write_bytes(b"midday capture")
    pid = store.create_project(
        "Poster", {"poster_path": str(middle), "samples": [{"frame": str(first)}]}
    )
    assert (
        client.get(f"/api/projects/{pid}/poster?first=true").content
        == first.read_bytes()
    )
    assert client.get(f"/api/projects/{pid}/poster").content == middle.read_bytes()


def test_heat_layer_and_exports_use_real_interval_frame_and_validated_options(
    client, tmp_path
):
    source = tmp_path / "fixture.avi"
    writer = cv2.VideoWriter(
        str(source), cv2.VideoWriter_fourcc(*"MJPG"), 10, (200, 150)
    )
    for i in range(20):
        writer.write(np.full((150, 200, 3), 30 if i < 10 else 220, np.uint8))
    writer.release()
    slots = [
        {
            "id": "a",
            "name": "A",
            "points": [[0.1, 0.2], [0.4, 0.2], [0.4, 0.8], [0.1, 0.8]],
        }
    ]
    metadata = {
        "video_path": str(source),
        "width": 200,
        "height": 150,
        "video_duration_seconds": 2,
    }
    pid = store.create_project("Heat test", metadata, slots)
    run_id = store.create_run(store.project(pid), {})
    result = {
        "run_id": run_id,
        "project_id": pid,
        "slots": slots,
        "source_duration_seconds": 2,
        "sampled": False,
        "samples": [
            {"source_seconds": 0, "video_seconds": 0, "states": [0]},
            {"source_seconds": 1, "video_seconds": 1, "states": [1]},
        ],
    }
    path = tmp_path / "result.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    store.update_run(run_id, status="completed", result_path=str(path))
    base = f"/api/runs/{run_id}"
    assert client.get(base + "/summary").json()["run_id"] == run_id
    cold = client.get(base + "/heatmap.png?start=0&end=1")
    hot = client.get(base + "/heatmap.png?start=1&end=2")
    a = cv2.imdecode(np.frombuffer(cold.content, np.uint8), cv2.IMREAD_UNCHANGED)
    b = cv2.imdecode(np.frombuffer(hot.content, np.uint8), cv2.IMREAD_UNCHANGED)
    assert a.shape == (150, 200, 4)
    assert a[75, 50, 0] > a[75, 50, 2] and b[75, 50, 2] > b[75, 50, 0]
    assert client.get(base + "/heatmap.png?palette=purple").status_code == 422
    assert client.get(base + "/heatmap.png?start=nan").status_code == 422
    assert client.get(base + "/export/png?opacity=2").status_code == 422
    frames = []
    for seconds in [0, 1]:
        response = client.get(base + f"/export/png?video_seconds={seconds}&opacity=0")
        assert response.status_code == 200, response.text
        frames.append(
            cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
        )
    assert frames[0].shape == (322, 200, 3)
    assert frames[1][66 + 75, 180].mean() - frames[0][66 + 75, 180].mean() > 150
