"""Download a bounded public YouTube DVR interval and make a full-span timelapse.

The camera's original segments are cached intact. Audio is omitted. At 75x/15 fps,
one original keyframe every five seconds becomes one output frame: no event-based
cuts, repeated days, frame interpolation, or cropped parking area.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests

from backend.config import FFPROBE, ROOT


def fragment_url(base, sequence):
    parsed = urlparse(base)
    query = parse_qs(parsed.query)
    query["sq"] = [str(sequence)]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def walltime(content):
    match = re.search(rb"First-Frame-Time-Us: ([0-9]+)", content)
    if not match or b"ftyp" not in content[:32]:
        raise ValueError("The response is not a timestamped YouTube video segment")
    return int(match.group(1)) / 1_000_000


def probe(path, count=False):
    command = [FFPROBE, "-v", "error", "-select_streams", "v:0"]
    if count:
        command += ["-count_frames"]
    command += ["-show_format", "-show_streams", "-of", "json", str(path)]
    return json.loads(subprocess.check_output(command, timeout=180))


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def encode(folder, output, manifest):
    import imageio_ffmpeg

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    encoder_version = subprocess.check_output(
        [ffmpeg, "-version"], text=True
    ).splitlines()[0]
    step = manifest["segment_seconds"]
    duration = manifest["source_duration_seconds"]
    count = manifest["segment_count"]
    rows = [
        (entry["sequence"], entry["first_frame_utc"], entry["bytes"])
        for entry in manifest["segments"]
    ]
    expected = list(
        range(manifest["first_sequence"], manifest["first_sequence"] + count)
    )
    if [row[0] for row in rows] != expected:
        raise ValueError("The cached source interval is incomplete")
    for sequence, _, size in rows:
        part = folder / "segments" / f"{sequence:010d}.mp4"
        if not part.is_file() or part.stat().st_size != size:
            raise ValueError(f"Missing or damaged cached segment {sequence}")
        with part.open("rb") as stream:
            prefix = stream.read(8192)
        tag = re.search(rb"Sequence-Number: ([0-9]+)", prefix)
        if not tag or int(tag.group(1)) != sequence:
            raise ValueError(f"The cached file is not the requested segment {sequence}")
    concat = folder / "source.ffconcat"
    concat.write_text(
        "ffconcat version 1.0\n"
        + "".join(
            f"file 'segments/{sequence:010d}.mp4'\nduration {step}\n"
            for sequence, _, _ in rows
        ),
        encoding="utf-8",
    )
    temporary_output = output.with_suffix(".part.mp4")
    print("Encoding full-span 75x timelapse at 15 fps…", flush=True)
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-skip_frame",
            "nokey",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat.name,
            "-an",
            "-vf",
            "setpts=N/(15*TB)",
            "-r",
            "15",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "21",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(temporary_output),
        ],
        check=True,
        timeout=1800,
        cwd=folder,
    )
    encoded = probe(temporary_output, count=True)
    stream = encoded["streams"][0]
    measured = float(encoded["format"]["duration"])
    if abs(measured - duration / 75) > 0.15 or int(stream["nb_read_frames"]) != count:
        raise ValueError(
            f"Unexpected output duration/frame count: {measured}, {stream['nb_read_frames']}"
        )
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-xerror",
            "-i",
            str(temporary_output),
            "-f",
            "null",
            "-",
        ],
        check=True,
        timeout=180,
    )
    import numpy as np

    def pixels(path, seconds=None):
        command = [ffmpeg, "-v", "error"]
        if seconds is not None:
            command += ["-ss", f"{seconds:.9f}"]
        command += [
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ]
        return np.frombuffer(
            subprocess.check_output(command, timeout=60), dtype=np.uint8
        ).astype(np.int16)

    comparisons = []
    for index in [0, count // 4, count // 2, 3 * count // 4, count - 1]:
        source = pixels(folder / "segments" / f"{rows[index][0]:010d}.mp4")
        result = pixels(temporary_output, max(0, index / 15 - 0.001))
        if source.size != result.size or not source.size:
            raise ValueError("An output frame has different dimensions from its source")
        error = float(np.mean(np.abs(source - result)))
        if error > 5:
            raise ValueError(
                f"Output frame {index} does not match its source: MAE={error:.2f}"
            )
        comparisons.append({"frame": index, "rgb_mae": round(error, 4)})
    temporary_output.replace(output)
    report = {k: v for k, v in manifest.items() if k != "segments"}
    report.update(
        {
            "output": str(output),
            "output_seconds": measured,
            "time_scale": 75,
            "fps": 15,
            "width": stream["width"],
            "height": stream["height"],
            "frames": int(stream["nb_read_frames"]),
            "bytes": output.stat().st_size,
            "sha256": sha256(output),
            "temporal_sampling_seconds": step,
            "encoder": encoder_version,
            "source_frame_comparison": comparisons,
            "method": "One original keyframe per five-second segment; uniform 75x acceleration, no temporal event cuts or spatial crop",
        }
    )
    output.with_suffix(".json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-ss",
            "144",
            "-i",
            str(output),
            "-frames:v",
            "1",
            str(output.with_suffix(".jpg")),
        ],
        check=True,
        timeout=30,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


def prepare(args):
    import yt_dlp

    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", args.video_id):
        raise ValueError("Invalid YouTube video ID")
    start = datetime.fromisoformat(args.start)
    if start.tzinfo is None:
        raise ValueError("--start must include a timezone, for example +00:00")
    if not 10 < args.hours <= 48 or not 1 <= args.workers <= 24:
        raise ValueError("Use 10 < hours <= 48 and 1 <= workers <= 24")
    duration = args.hours * 3600
    output = Path(args.output).resolve()
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    folder = ROOT / "data" / "source-cache" / f"{args.video_id}-{start:%Y%m%dT%H%M%S}"
    folder.mkdir(parents=True, exist_ok=True)
    segments = folder / "segments"
    segments.mkdir(exist_ok=True)
    if args.encode_cache:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        if (
            manifest["requested_start"] != start.isoformat()
            or manifest["source_duration_seconds"] != duration
        ):
            raise ValueError("The cache belongs to a different requested interval")
        return encode(folder, output, manifest)
    source_url = f"https://www.youtube.com/watch?v={args.video_id}"
    with yt_dlp.YoutubeDL(
        {
            "quiet": True,
            "live_from_start": True,
            "noplaylist": True,
            "socket_timeout": 25,
            "js_runtimes": {"node": {}},
            "cachedir": False,
        }
    ) as downloader:
        info = downloader.extract_info(source_url, download=False)
    formats = [
        f
        for f in info["formats"]
        if f.get("height") == 720
        and f.get("vcodec", "").startswith("avc1")
        and f.get("is_from_start")
    ]
    if not formats:
        raise ValueError("No public 720p H.264 DVR format available")
    selected = formats[0]
    base = selected["url"]
    step = float(selected["target_duration"])
    if step != 5:
        raise ValueError(
            "This preparation preset requires five-second original segments"
        )
    anchor_response = requests.get(base, timeout=30)
    anchor_response.raise_for_status()
    sequence_tag = re.search(rb"Sequence-Number: ([0-9]+)", anchor_response.content)
    if not sequence_tag:
        raise ValueError("No sequence number in the public DVR response")
    last_available = int(sequence_tag.group(1))
    anchor_time = walltime(anchor_response.content)
    first = last_available + round((start.timestamp() - anchor_time) / step)
    count = round(duration / step)
    if first < 0 or first + count > last_available:
        raise ValueError(
            "The entire requested historical interval is not yet available"
        )

    # Pin the sequence interval on first use so a resumed download keeps the same source.
    selection_file = folder / "selection.json"
    selection = {
        "video_id": args.video_id,
        "requested_start": start.isoformat(),
        "source_duration_seconds": duration,
        "segment_seconds": step,
        "first_sequence": first,
        "segment_count": count,
    }
    if selection_file.exists():
        previous = json.loads(selection_file.read_text(encoding="utf-8"))
        if any(
            previous[k] != selection[k]
            for k in [
                "video_id",
                "requested_start",
                "source_duration_seconds",
                "segment_seconds",
            ]
        ):
            raise ValueError("The cache belongs to a different source interval")
        selection = previous
        first, count = previous["first_sequence"], previous["segment_count"]
    else:
        selection_file.write_text(json.dumps(selection, indent=2), encoding="utf-8")

    connections = threading.local()

    def fetch(sequence):
        target = segments / f"{sequence:010d}.mp4"
        if target.exists():
            content = target.read_bytes()
            return sequence, walltime(content), len(content)
        for attempt in range(4):
            try:
                if shutil.disk_usage(folder).free < 512 * 1024**2:
                    raise OSError("Less than 512 MB free disk space")
                if not hasattr(connections, "session"):
                    connections.session = requests.Session()
                response = connections.session.get(
                    fragment_url(base, sequence), timeout=(15, 45)
                )
                response.raise_for_status()
                content = response.content
                timestamp = walltime(content)
                if response.headers.get("Content-Length") and len(content) != int(
                    response.headers["Content-Length"]
                ):
                    raise ValueError("Incomplete video segment")
                temporary = target.with_suffix(".part")
                temporary.write_bytes(content)
                temporary.replace(target)
                return sequence, timestamp, len(content)
            except (requests.RequestException, ValueError) as error:
                if (
                    isinstance(error, requests.HTTPError)
                    and error.response is not None
                    and 400 <= error.response.status_code < 500
                    and error.response.status_code != 429
                ):
                    raise
                if attempt == 3:
                    raise
                time.sleep(attempt + 1)
        raise RuntimeError("Unreachable")

    # Check the oldest required segment before beginning the bulk download.
    fetch(first)
    fetch(first + count - 1)
    rows = []
    print(
        f"Source: {duration / 3600:g} h, {count} original segments; output {duration / 75:g} s",
        flush=True,
    )
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [
            executor.submit(fetch, sequence) for sequence in range(first, first + count)
        ]
        try:
            for done, future in enumerate(as_completed(futures), 1):
                rows.append(future.result())
                if done % 200 == 0 or done == count:
                    print(
                        f"Downloaded {done}/{count}, {sum(row[2] for row in rows) / 1024**2:.1f} MB",
                        flush=True,
                    )
        except Exception:
            for future in futures:
                future.cancel()
            raise
    rows.sort()
    if any(b[1] <= a[1] for a, b in zip(rows, rows[1:])):
        raise ValueError("Source timestamps do not increase monotonically")
    manifest = {
        **selection,
        "source_url": source_url,
        "source_title": info.get("title"),
        "publisher": info.get("uploader"),
        "source_bytes": sum(row[2] for row in rows),
        "first_frame_utc": datetime.fromtimestamp(rows[0][1], timezone.utc).isoformat(),
        "last_segment_first_frame_utc": datetime.fromtimestamp(
            rows[-1][1], timezone.utc
        ).isoformat(),
        "max_walltime_step_seconds": max(b[1] - a[1] for a, b in zip(rows, rows[1:])),
        "segments": [
            {"sequence": seq, "first_frame_utc": stamp, "bytes": size}
            for seq, stamp, size in rows
        ],
    }
    (folder / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    encode(folder, output, manifest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video-id", default="ta-4QZbfMXc")
    parser.add_argument("--start", required=True, help="ISO timestamp with timezone")
    parser.add_argument("--hours", type=float, default=12)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--encode-cache",
        action="store_true",
        help="Encode an already complete local archive without network requests",
    )
    parser.add_argument("--output", required=True)
    prepare(parser.parse_args())
