from bisect import bisect_right
import csv
from datetime import datetime, timedelta
import hashlib
import io
import json
import subprocess
from threading import Lock
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from .analytics import summary
from .heatmap import SPEC, RENDER, color, composite, layer
from .config import ROOT, FFMPEG

VIDEO_LOCK = Lock()
FONT = ROOT / "frontend/public/fonts/Inter.ttf"


def paint_states(frame, slots, values):
    h, w = frame.shape[:2]
    overlay = frame.copy()
    for slot, value in zip(slots, values):
        points = np.round(np.asarray(slot["points"]) * [w, h]).astype(np.int32)
        fill = (
            (205, 230, 200)
            if value == 0
            else (182, 201, 243)
            if value == 1
            else (230, 230, 230)
        )
        cv2.fillPoly(overlay, [points], fill)
    frame = cv2.addWeighted(overlay, 0.55, frame, 0.45, 0)
    for slot in slots:
        points = np.round(np.asarray(slot["points"]) * [w, h]).astype(np.int32)
        cv2.polylines(frame, [points], True, (25, 25, 25), 1, cv2.LINE_AA)
        x, y = points.mean(axis=0).astype(int)
        cv2.rectangle(frame, (x - 13, y - 9), (x + 18, y + 5), (255, 255, 255), -1)
        cv2.putText(
            frame,
            slot["id"],
            (x - 12, y + 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.30,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )
    return frame


def clock(seconds, metadata):
    if metadata.get("capture_start"):
        return (
            datetime.fromisoformat(metadata["capture_start"])
            + timedelta(seconds=seconds)
        ).strftime("%H:%M")
    return f"{int(seconds) // 3600:02d}:{int(seconds) % 3600 // 60:02d}"


def panel(width, height):
    image = Image.new("RGB", (width, height), "white")
    return (
        image,
        ImageDraw.Draw(image),
        ImageFont.truetype(str(FONT), max(12, min(18, width // 48))),
    )


def header(width, title, subtitle):
    image, draw, font = panel(width, 66)
    draw.text((16, 10), title, font=font, fill="black")
    draw.text((16, 36), subtitle, font=font, fill="#444444")
    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


def legend(width, palette, coverage, sparse, heatmap=True):
    image, draw, font = panel(width, 106)
    if heatmap:
        bar_width = min(width - 36, 450)
        for x in range(bar_width):
            draw.line(
                (18 + x, 12, 18 + x, 27),
                fill=color(x / max(1, bar_width - 1) * 100, palette),
            )
        for value in (0, 25, 50, 75, 100):
            x = 18 + value / 100 * bar_width
            draw.text((min(x, width - 48), 33), f"{value}%", font=font, fill="black")
        draw.text(
            (18, 59), "Редко занято → почти всегда занято", font=font, fill="black"
        )
        if width >= 700:
            draw.rectangle((width - 216, 15, width - 188, 35), fill="#e6e6e6")
            for x in range(width - 216, width - 188, 6):
                draw.line(
                    (x, 35, min(x + 16, width - 188), 15), fill="#999999", width=2
                )
            draw.text((width - 180, 16), "Нет данных", font=font, fill="black")
    else:
        draw.text(
            (18, 18),
            "Свободно: зелёный · Занято: коралловый · Неизвестно: серый",
            font=font,
            fill="black",
        )
    note = (
        "Оценка по редким снимкам · шаг ≈ 30 мин"
        if sparse
        else "Состояния определены по выбранному шагу анализа"
    )
    draw.text(
        (18, 82),
        f"Покрытие {coverage:.1f}% · {note}",
        font=ImageFont.truetype(str(FONT), max(11, min(14, width // 65))),
        fill="#444444",
    )
    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


def capture(metadata, video_seconds):
    cap = cv2.VideoCapture(str(ROOT / metadata["video_path"]))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 10
        seconds = min(
            video_seconds, max(0, metadata["video_duration_seconds"] - 1 / fps)
        )
        cap.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000)
        ok, frame = cap.read()
        if not ok:
            raise ValueError("Не удалось прочитать кадр для экспорта")
        return frame
    finally:
        cap.release()


def png(
    result,
    metadata,
    start,
    end,
    palette="thermal",
    opacity=RENDER["defaultOpacity"],
    video_seconds=0,
):
    data = summary(result, start, end)
    frame = capture(metadata, video_seconds)
    frame = composite(
        frame, layer(data["slots"], frame.shape[1], frame.shape[0], palette), opacity
    )
    times = [s["video_seconds"] for s in result["samples"]]
    source = result["samples"][max(0, bisect_right(times, video_seconds) - 1)][
        "source_seconds"
    ]
    top = header(
        frame.shape[1],
        "Тепловая карта · занятость среди известных интервалов",
        f"Период {clock(start, metadata)} — {clock(end, metadata)} · Кадр {clock(source, metadata)}",
    )
    canvas = np.vstack(
        (
            top,
            frame,
            legend(frame.shape[1], palette, data["coverage"], result["sampled"]),
        )
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


def video_export(
    result,
    metadata,
    folder,
    start=0,
    end=None,
    palette="thermal",
    opacity=RENDER["defaultOpacity"],
    mode="heatmap",
):
    end = result["source_duration_seconds"] if end is None else end
    data = summary(result, start, end)
    identity = json.dumps(
        [SPEC["version"], result["run_id"], start, end, palette, opacity, mode]
    )
    key = hashlib.sha256(identity.encode()).hexdigest()[:16]
    target = folder / f"{result['run_id']}-{key}.mp4"
    # Serialize encodes and publish complete files atomically.
    with VIDEO_LOCK:
        if target.exists():
            return target
        cap = cv2.VideoCapture(str(ROOT / metadata["video_path"]))
        width, height = int(cap.get(3)), int(cap.get(4))
        fps = cap.get(5)
        if not cap.isOpened() or not fps or not width or not height:
            cap.release()
            raise ValueError("Не удалось открыть видео для экспорта")
        heatmap = mode == "heatmap"
        rgba = layer(data["slots"], width, height, palette) if heatmap else None
        bottom = legend(width, palette, data["coverage"], result["sampled"], heatmap)
        raw = target.with_suffix(".avi")
        temporary = target.with_suffix(".partial.mp4")
        writer = cv2.VideoWriter(
            str(raw), cv2.VideoWriter_fourcc(*"MJPG"), fps, (width, height + 172)
        )
        if not writer.isOpened():
            cap.release()
            raise ValueError("Не удалось подготовить видео для экспорта")
        times = [s["video_seconds"] for s in result["samples"]]
        try:
            index, previous_sample, top = 0, -1, None
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                sample_index = max(0, bisect_right(times, index / fps) - 1)
                sample = result["samples"][sample_index]
                if sample_index != previous_sample:
                    title = (
                        "Тепловая карта · занятость среди известных интервалов"
                        if heatmap
                        else "Состояние мест в момент наблюдения"
                    )
                    top = header(
                        width,
                        title,
                        f"Кадр {clock(sample['source_seconds'], metadata)} · Период карты {clock(start, metadata)} — {clock(end, metadata)}",
                    )
                    previous_sample = sample_index
                frame = (
                    composite(frame, rgba, opacity)
                    if heatmap
                    else paint_states(frame, result["slots"], sample["states"])
                )
                writer.write(np.vstack((top, frame, bottom)))
                index += 1
            writer.release()
            cap.release()
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
        finally:
            cap.release()
            writer.release()
            raw.unlink(missing_ok=True)
            temporary.unlink(missing_ok=True)
        return target
