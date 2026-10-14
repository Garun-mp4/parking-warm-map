from fastapi.testclient import TestClient
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
