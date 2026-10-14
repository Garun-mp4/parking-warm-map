from bisect import bisect_right
import csv
import io
import subprocess
import cv2
import numpy as np
from .analytics import heat_color, summary
from .config import ROOT, FFMPEG


def paint(frame, slots, values, heatmap=True):
    h, w = frame.shape[:2]
    layer = frame.copy()
    for slot, value in zip(slots, values):
        points = np.round(np.asarray(slot["points"]) * [w, h]).astype(np.int32)
        color = (
            heat_color(value)
            if heatmap
            else (205, 230, 200)
            if value == 0
            else (182, 201, 243)
            if value == 1
            else (230, 230, 230)
        )
        cv2.fillPoly(layer, [points], color)
    frame = cv2.addWeighted(layer, 0.55, frame, 0.45, 0)
    for slot, value in zip(slots, values):
        points = np.round(np.asarray(slot["points"]) * [w, h]).astype(np.int32)
        cv2.polylines(frame, [points], True, (25, 25, 25), 1, cv2.LINE_AA)
        x, y = points.mean(axis=0).astype(int)
        label = slot["id"]
        cv2.rectangle(frame, (x - 13, y - 9), (x + 18, y + 5), (255, 255, 255), -1)
        cv2.putText(
            frame,
            label,
            (x - 12, y + 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.30,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )
    return frame


def png(result, metadata, start, end):
    data = summary(result, start, end)
    frame = cv2.imread(str(ROOT / metadata["poster_path"]))
    frame = paint(frame, data["slots"], [s["occupancy"] for s in data["slots"]])
    # Include scale and interval in the image so the standalone export is interpretable.
    canvas = np.full((frame.shape[0] + 90, frame.shape[1], 3), 255, np.uint8)
    canvas[: frame.shape[0]] = frame
    y = frame.shape[0] + 30
    cv2.putText(
        canvas,
        f"Occupancy: {start / 3600:.2f} - {end / 3600:.2f} h | Coverage: {data['coverage']:.1f}%",
        (15, y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (0, 0, 0),
        1,
        cv2.LINE_AA,
    )
    for x in range(200):
        cv2.line(canvas, (15 + x, y + 15), (15 + x, y + 30), heat_color(x / 199 * 100))
    cv2.putText(
        canvas,
        "0%                                      100%",
        (15, y + 48),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.35,
        (0, 0, 0),
        1,
        cv2.LINE_AA,
    )
    return cv2.imencode(".png", canvas)[1].tobytes()


def csv_export(result, start, end):
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(
        [
            "Место",
            "Занятость %",
            "Достоверное наблюдение %",
            "Занято секунд",
            "Свободно секунд",
            "Не определено секунд",
            "Подтверждённые смены состояния",
        ]
    )
    for row in summary(result, start, end)["slots"]:
        writer.writerow(
            [
                row["name"],
                row["occupancy"],
                row["coverage"],
                row["occupied_seconds"],
                row["free_seconds"],
                row["unknown_seconds"],
                row["changes"],
            ]
        )
    return output.getvalue().encode("utf-8-sig")


def video_export(result, metadata, folder):
    target = folder / (result["run_id"] + "-annotated.mp4")
    if target.exists():
        return target
    cap = cv2.VideoCapture(str(ROOT / metadata["video_path"]))
    width, height = int(cap.get(3)), int(cap.get(4))
    fps = cap.get(5)
    raw = target.with_suffix(".avi")
    writer = cv2.VideoWriter(
        str(raw), cv2.VideoWriter_fourcc(*"MJPG"), fps, (width, height)
    )
    if not cap.isOpened() or not writer.isOpened():
        cap.release()
        writer.release()
        raise ValueError("Не удалось открыть видео для экспорта")
    times = [s["video_seconds"] for s in result["samples"]]
    try:
        index = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            sample = result["samples"][max(0, bisect_right(times, index / fps) - 1)]
            frame = paint(frame, result["slots"], sample["states"], False)
            cv2.rectangle(frame, (0, 0), (width, 35), (255, 255, 255), -1)
            cv2.putText(
                frame,
                f"Source elapsed: {sample['source_seconds'] / 3600:.2f} h | occupied: {sample['states'].count(1)} | unknown: {sample['states'].count(-1)}",
                (12, 23),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.50,
                (0, 0, 0),
                1,
                cv2.LINE_AA,
            )
            writer.write(frame)
            index += 1
    finally:
        cap.release()
        writer.release()
    temporary = target.with_name(target.stem + ".partial.mp4")
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(raw),
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
            str(temporary),
        ],
        check=True,
        capture_output=True,
        timeout=3600,
    )
    temporary.replace(target)
    raw.unlink()
    return target
