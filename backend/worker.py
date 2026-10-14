"""Each analysis runs in its own process; SQLite enforces one active local analysis."""

import argparse
import json
import time
import traceback
import cv2
from . import store
from .analytics import Stabilizer
from .config import ROOT, DATA
from .detectors import detector


def analyze(run_id):
    run = store.run(run_id)
    if not run:
        raise ValueError("Unknown analysis")
    settings, slots = json.loads(run["settings"]), json.loads(run["slots"])
    project = store.project(run["project_id"])
    meta = project["metadata"]
    started = time.monotonic()
    store.update_run(run_id, status="running", stage="Загрузка модели", progress=0)
    model = detector(settings["model"])
    sparse = meta["kind"] == "sampled_timelapse"
    cap = None
    if sparse:
        observations = meta["samples"]
        duration = meta["source_duration_seconds"]
    else:
        cap = cv2.VideoCapture(str(ROOT / meta["video_path"]))
        if not cap.isOpened():
            raise ValueError("Видео не удалось открыть")
        video_duration = meta["video_duration_seconds"]
        count = int(video_duration / settings["sample_seconds"]) + 1
        if count > 30000:
            raise ValueError("Слишком много кадров. Увеличьте интервал анализа.")
        observations = [
            {
                "video_seconds": i * settings["sample_seconds"],
                "source_seconds": i
                * settings["sample_seconds"]
                * settings["time_scale"],
            }
            for i in range(count)
            if i * settings["sample_seconds"] < video_duration
        ]
        duration = video_duration * settings["time_scale"]
    stabilizer = Stabilizer(
        len(slots), settings["confirm_seconds"] * settings["time_scale"]
    )
    samples = []
    try:
        for i, point in enumerate(observations):
            if store.run(run_id)["cancel_requested"]:
                store.update_run(run_id, status="cancelled", stage="Анализ отменён")
                return
            if sparse:
                frame = cv2.imread(str(ROOT / point["frame"]))
            else:
                cap.set(cv2.CAP_PROP_POS_MSEC, point["video_seconds"] * 1000)
                ok, frame = cap.read()
                if not ok:
                    raise ValueError(
                        f"Не удалось прочитать кадр {point['video_seconds']:.2f} с"
                    )
            if frame is None:
                raise ValueError("Повреждён исходный кадр")
            states, probabilities, boxes = model.predict(
                frame, slots, settings["confidence"]
            )
            if not sparse:
                states = stabilizer.step(states, point["source_seconds"])
            samples.append(
                {
                    "video_seconds": point["video_seconds"],
                    "source_seconds": point["source_seconds"],
                    "captured_at": point.get("captured_at"),
                    "states": states,
                    "probabilities": [round(float(p), 5) for p in probabilities],
                    "boxes": boxes,
                }
            )
            store.update_run(
                run_id,
                progress=round((i + 1) / len(observations) * 100, 1),
                stage=f"Обработано {i + 1} из {len(observations)} кадров",
            )
        if not samples:
            raise ValueError("Нет пригодных кадров")
        result = {
            "run_id": run_id,
            "project_id": project["id"],
            "revision": run["revision"],
            "slots": slots,
            "samples": samples,
            "source_duration_seconds": duration,
            "video_duration_seconds": meta["video_duration_seconds"],
            "model": model.name,
            "model_sha256": model.sha256,
            "settings": settings,
            "processing_seconds": round(time.monotonic() - started, 3),
            "sampled": sparse,
            "notice": meta.get(
                "notice",
                "Результат автоматического распознавания. Возможны пропуски автомобилей и ошибки при перекрытии.",
            ),
        }
        folder = DATA / "projects" / project["id"]
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (run_id + ".json")
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
        store.update_run(
            run_id,
            status="completed",
            progress=100,
            stage="Анализ завершён",
            result_path=str(path),
        )
    finally:
        if cap is not None:
            cap.release()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    args = parser.parse_args()
    try:
        analyze(args.run_id)
    except Exception as error:
        traceback.print_exc()
        store.update_run(
            args.run_id, status="failed", stage="Ошибка обработки", error=str(error)
        )
