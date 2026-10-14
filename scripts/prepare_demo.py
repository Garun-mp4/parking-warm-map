"""Build a real, timestamped full-day timelapse and independent reference labels."""

from pathlib import Path
from datetime import datetime
import csv
import hashlib
import json
import shutil
import subprocess
import tarfile
import zipfile

from backend import store
from scripts.download_sources import CACHE, small, archive

ROOT = Path(__file__).resolve().parents[1]

DATE, CAMERA = "2015-11-16", "8"


def prepare():
    CACHE.mkdir(parents=True, exist_ok=True)
    output = ROOT / "data" / "demo"
    frames = output / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    model_zip = small("CNRPark+EXT_Trained_Models_mAlexNet.zip")
    with zipfile.ZipFile(model_zip) as bundle:
        for name in bundle.namelist():
            if name.startswith(
                "mAlexNet-on-CNRParkAB_all-val-CNRPark-EXT_val/"
            ) and not name.endswith("/"):
                (ROOT / "models" / Path(name).name).write_bytes(bundle.read(name))
    bundled = ROOT / "examples" / "cnrpark-day"
    if bundled.exists() and not (output / "manifest.json").exists():
        shutil.copytree(bundled, output, dirs_exist_ok=True)
    if (output / "manifest.json").exists():
        data = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        video = ROOT / data["metadata"]["video_path"]
        if video.exists() and all(
            (ROOT / s["frame"]).exists() for s in data["metadata"]["samples"]
        ):
            if (
                hashlib.sha256(video.read_bytes()).hexdigest()
                != data["metadata"]["sha256"]
            ):
                raise ValueError("Example video checksum mismatch")
            store.initialize()
            if not store.project("cnrpark-day"):
                store.create_project(
                    "Рабочий день в Пизе",
                    data["metadata"],
                    data["slots"],
                    "cnrpark-day",
                )
            print("Verified bundled example: 10 h 12 min, 2.3 MB", flush=True)
            return
    csv_path = small("CNRPark+EXT.csv")
    source = archive()
    with tarfile.open(source) as bundle:
        geometry = bundle.extractfile(f"camera{CAMERA}.csv").read().decode()
        for member in bundle:
            if f"/{DATE}/camera{CAMERA}/" in member.name and member.name.endswith(
                ".jpg"
            ):
                (frames / Path(member.name).name).write_bytes(
                    bundle.extractfile(member).read()
                )
    paths = sorted(frames.glob(DATE + "*.jpg"))
    captures = [datetime.strptime(p.stem, "%Y-%m-%d_%H%M") for p in paths]
    if len(captures) < 2 or (captures[-1] - captures[0]).total_seconds() < 7200:
        raise ValueError("The example must cover at least two actual hours")
    label_rows = list(csv.DictReader(csv_path.open()))
    selected_labels = [
        r
        for r in label_rows
        if r["camera"] == CAMERA.zfill(2) and r["datetime"].startswith(DATE)
    ]
    available_ids = {r["slot_id"] for r in selected_labels}
    slots = []
    for row in csv.DictReader(geometry.splitlines()):
        if row["SlotId"] not in available_ids:
            continue
        x, y, w, h = [int(row[k]) for k in ("X", "Y", "W", "H")]
        points = [
            [x / 2592, y / 1944],
            [(x + w) / 2592, y / 1944],
            [(x + w) / 2592, (y + h) / 1944],
            [x / 2592, (y + h) / 1944],
        ]
        slots.append(
            {"id": row["SlotId"], "name": f"Место {row['SlotId']}", "points": points}
        )
    samples = []
    truth = []
    for i, (path, captured) in enumerate(zip(paths, captures)):
        source_seconds = (captured - captures[0]).total_seconds()
        samples.append(
            {
                "video_seconds": i * 2.0,
                "source_seconds": source_seconds,
                "captured_at": captured.isoformat(),
                "frame": str(path.relative_to(ROOT)).replace("\\", "/"),
            }
        )
        key = captured.strftime("%Y-%m-%d_%H.%M")
        states = {
            r["slot_id"]: int(r["occupancy"])
            for r in selected_labels
            if r["datetime"] == key
        }
        truth.append({"source_seconds": source_seconds, "labels": states})
    concat = output / "frames.txt"
    concat.write_text(
        "".join(f"file '{p.resolve().as_posix()}'\nduration 2\n" for p in paths)
        + f"file '{paths[-1].resolve().as_posix()}'\n",
        encoding="utf-8",
    )
    video = output / "parking-day.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat),
            "-t",
            str(len(paths) * 2),
            "-vf",
            "fps=25",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "24",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(video),
        ],
        check=True,
    )
    shutil.copyfile(paths[len(paths) // 2], output / "poster.jpg")
    duration = (captures[-1] - captures[0]).total_seconds()
    metadata = {
        "kind": "sampled_timelapse",
        "filename": video.name,
        "video_path": str(video.relative_to(ROOT)),
        "poster_path": "data/demo/poster.jpg",
        "width": 1000,
        "height": 750,
        "video_duration_seconds": len(paths) * 2,
        "source_duration_seconds": duration,
        "capture_start": captures[0].isoformat(),
        "capture_end": captures[-1].isoformat(),
        "samples": samples,
        "sample_count": len(paths),
        "capture_interval_seconds": 1800,
        "source_url": "http://cnrpark.it/",
        "source_name": f"CNRPark-EXT · камера {CAMERA} · {DATE}",
        "license": "ODbL 1.0",
        "sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
        "notice": "Таймлапс из реальных снимков примерно каждые 30 минут. Занятость между снимками оценивается по последнему наблюдению; точные моменты приезда неизвестны.",
    }
    (output / "manifest.json").write_text(
        json.dumps(
            {"metadata": metadata, "slots": slots}, ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )
    (output / "truth.json").write_text(
        json.dumps(truth, ensure_ascii=False), encoding="utf-8"
    )
    store.initialize()
    if not store.project("cnrpark-day"):
        store.create_project("Рабочий день в Пизе", metadata, slots, "cnrpark-day")
    print(
        json.dumps(
            {
                "hours": duration / 3600,
                "frames": len(paths),
                "slots": len(slots),
                "video_megabytes": video.stat().st_size / 1e6,
                "start": metadata["capture_start"],
                "end": metadata["capture_end"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    prepare()
