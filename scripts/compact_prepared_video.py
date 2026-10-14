"""Create and verify a smaller copy without changing video geometry or timing."""

import argparse
import json
from pathlib import Path
import subprocess

from scripts.prepare_parking_video import probe, sha256


def compact(source):
    import imageio_ffmpeg
    import numpy as np

    source = Path(source).resolve()
    report = json.loads(source.with_suffix(".json").read_text(encoding="utf-8"))
    if sha256(source) != report["sha256"]:
        raise ValueError("The source video does not match its verified report")
    target = source.with_name(source.stem + "-compact.mp4")
    candidate = target if target.exists() else target.with_suffix(".part.mp4")
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    if not target.exists():
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-v",
                "error",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "25",
                "-maxrate",
                "1800k",
                "-bufsize",
                "3600k",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(candidate),
            ],
            check=True,
            timeout=600,
        )
    info = probe(candidate, count=True)
    stream = info["streams"][0]
    if (
        int(stream["nb_read_frames"]) != report["frames"]
        or float(info["format"]["duration"]) != report["output_seconds"]
        or stream["width"] != report["width"]
        or stream["height"] != report["height"]
    ):
        raise ValueError("Compression changed frame count, duration or geometry")
    subprocess.run(
        [ffmpeg, "-v", "error", "-xerror", "-i", str(candidate), "-f", "null", "-"],
        check=True,
        timeout=180,
    )

    def pixels(path, index):
        return np.frombuffer(
            subprocess.check_output(
                [
                    ffmpeg,
                    "-v",
                    "error",
                    "-ss",
                    f"{max(0, index / report['fps'] - 0.001):.9f}",
                    "-i",
                    str(path),
                    "-frames:v",
                    "1",
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "rgb24",
                    "-",
                ],
                timeout=60,
            ),
            dtype=np.uint8,
        ).astype(np.int16)

    comparisons = []
    count = report["frames"]
    for index in [0, count // 4, count // 2, 3 * count // 4, count - 1]:
        reference, encoded = pixels(source, index), pixels(candidate, index)
        if reference.size != encoded.size or not reference.size:
            raise ValueError("A compact frame is missing or has the wrong dimensions")
        error = float(np.mean(np.abs(reference - encoded)))
        # This copy intentionally trades fine weather texture for a bounded file size.
        if error > 5:
            raise ValueError(
                f"Compact frame {index} differs excessively: RGB MAE {error:.2f}"
            )
        comparisons.append({"frame": index, "rgb_mae": round(error, 4)})
    if candidate != target:
        candidate.replace(target)
    report["parent_source_frame_comparison"] = report.pop("source_frame_comparison")
    report.update(
        {
            "output": str(target),
            "parent_sha256": report["sha256"],
            "sha256": sha256(target),
            "bytes": target.stat().st_size,
            "source_frame_comparison": comparisons,
            "comparison_reference": "Verified full-quality timelapse",
            "compression": {"crf": 25, "maxrate_kbit_s": 1800, "bufsize_kbit": 3600},
        }
    )
    target.with_suffix(".json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-v",
            "error",
            "-ss",
            "144",
            "-i",
            str(target),
            "-frames:v",
            "1",
            str(target.with_suffix(".jpg")),
        ],
        check=True,
        timeout=30,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video")
    compact(parser.parse_args().video)
