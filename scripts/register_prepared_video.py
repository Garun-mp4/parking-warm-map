"""Add a verified prepared video as a new local project, preserving existing work."""

import argparse
import json
from pathlib import Path
import re
import subprocess
from uuid import uuid4

from backend import store
from backend.config import DATA, FFMPEG
from backend.video import probe
from scripts.prepare_parking_video import sha256


def register(path, title):
    path = Path(path).resolve()
    report = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    camera = re.sub(
        r" \d{4}-\d{2}-\d{2} \d{2}:\d{2}$",
        "",
        report.get("source_title") or report["video_id"],
    )
    hours = report["source_duration_seconds"] / 3600
    scale = report["time_scale"]
    if sha256(path) != report["sha256"]:
        raise ValueError("Prepared video checksum does not match the report")
    duration, width, height = probe(path)
    if abs(duration * report["time_scale"] - report["source_duration_seconds"]) > 1:
        raise ValueError("Video duration does not match the source time scale")
    store.initialize()
    existing = next(
        (
            p
            for p in store.projects()
            if p["metadata"].get("sha256") == report["sha256"]
        ),
        None,
    )
    if existing:
        print(f"Already registered: {existing['id']}")
        return existing["id"]
    project_id = uuid4().hex
    folder = DATA / "projects" / project_id
    folder.mkdir()
    poster = folder / "poster.jpg"
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-frames:v",
            "1",
            str(poster),
        ],
        check=True,
        timeout=30,
    )
    metadata = {
        "kind": "video",
        "filename": path.name,
        "video_path": str(path),
        "poster_path": str(poster),
        "width": width,
        "height": height,
        "video_duration_seconds": duration,
        "source_duration_seconds": report["source_duration_seconds"],
        "capture_start": report["first_frame_utc"],
        "source_name": f"{camera} · {report['first_frame_utc'][:10]} · UTC",
        "source_url": report["source_url"],
        "license": "Public YouTube broadcast; no open redistribution license stated",
        "sha256": report["sha256"],
        "notice": (
            f"{hours:g} часов исходного потока, равномерное ускорение {scale:g}×. "
            "Шаг исходных моментов — 5 секунд, без нарезки событий и обрезки кадра. "
            "Шкала UTC основана на времени потока YouTube; возможны задержки передачи. "
            "Утром и в тумане видимость ограничена. На новом ракурсе разметьте места "
            "и проверьте распознавание; качество модели для этой камеры ещё не оценивалось."
        ),
    }
    store.create_project(
        title or f"{camera} · {hours:g} ч · {scale:g}×", metadata, project_id=project_id
    )
    print(f"Registered new project: {project_id}")
    return project_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video")
    parser.add_argument("--title")
    args = parser.parse_args()
    register(args.video, args.title)
