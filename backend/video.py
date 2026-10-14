import json
import subprocess
from .config import FFMPEG, FFPROBE


def probe(path):
    process = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if process.returncode:
        raise ValueError("Файл не является читаемым видео")
    info = json.loads(process.stdout)
    stream = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    if not stream:
        raise ValueError("В файле нет видеопотока")
    duration = float(info["format"].get("duration", 0))
    width, height = int(stream["width"]), int(stream["height"])
    if (
        not 0.1 < duration <= 8 * 3600
        or width > 4096
        or height > 4096
        or min(width, height) < 100
    ):
        raise ValueError("Допустимо видео до 8 часов, от 100 px до 4096 px по стороне")
    return duration, width, height


def normalize(source, target, poster):
    _, source_width, source_height = probe(source)
    width = min(1280, source_width) // 2 * 2
    height = max(2, round(source_height * width / source_width / 2) * 2)
    # Explicit even dimensions also work with the older FFmpeg installed on this host.
    process = subprocess.run(
        [
            FFMPEG,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-an",
            "-vf",
            f"scale={width}:{height},fps=25",
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
            str(target),
        ],
        capture_output=True,
        text=True,
        timeout=3600,
    )
    if process.returncode:
        raise ValueError("Не удалось подготовить видео для браузера")
    duration, width, height = probe(target)
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-loglevel",
            "error",
            "-ss",
            "0",
            "-i",
            str(target),
            "-frames:v",
            "1",
            str(poster),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return duration, width, height
