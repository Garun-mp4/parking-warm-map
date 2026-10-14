import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
from typing import Literal
import psutil
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from . import store
from .analytics import summary
from .config import DATA, ROOT, MODELS
from .schemas import Layout, Settings
from .video import normalize


@asynccontextmanager
async def lifespan(app):
    store.initialize()
    with store.connection() as db:
        active = db.execute(
            "SELECT id,pid FROM runs WHERE status IN ('running','queued')"
        ).fetchall()
    for row in active:
        if not row["pid"] or not psutil.pid_exists(row["pid"]):
            store.update_run(
                row["id"],
                status="interrupted",
                stage="Обработка прервана",
                error="Процесс остановился. Запустите анализ повторно.",
            )
    yield


app = FastAPI(title="Парковка: карта занятости", lifespan=lifespan)


def require_project(project_id):
    project = store.project(project_id)
    if not project:
        raise HTTPException(404, "Проект не найден")
    return project


def require_result(run_id):
    run = store.run(run_id)
    if not run:
        raise HTTPException(404, "Анализ не найден")
    if run["status"] != "completed" or not run["result_path"]:
        raise HTTPException(409, "Анализ ещё не завершён")
    path = Path(run["result_path"])
    if not path.is_file():
        raise HTTPException(404, "Файл результата не найден. Повторите анализ.")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "app_id": "parking-warm-map",
        "classifier_ready": (MODELS / "snapshot_iter_870.caffemodel").exists(),
    }


@app.get("/api/projects")
def list_projects():
    return store.projects()


@app.post("/api/examples/day")
def import_day():
    manifest = DATA / "demo" / "manifest.json"
    if not manifest.exists():
        raise HTTPException(
            409, "Пример ещё не скачан. Выполните scripts/prepare_demo.py."
        )
    if not store.project("cnrpark-day"):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        store.create_project(
            "Рабочий день в Пизе", data["metadata"], data["slots"], "cnrpark-day"
        )
    return require_project("cnrpark-day")


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    return require_project(project_id)


@app.get("/api/projects/{project_id}/video")
def get_video(project_id: str):
    project = require_project(project_id)
    return FileResponse(
        ROOT / project["metadata"]["video_path"], media_type="video/mp4"
    )


@app.get("/api/projects/{project_id}/poster")
def get_poster(project_id: str, first: bool = False):
    project = require_project(project_id)
    if first and project["metadata"].get("samples"):
        return FileResponse(
            ROOT / project["metadata"]["samples"][0]["frame"], media_type="image/jpeg"
        )
    return FileResponse(
        ROOT / project["metadata"]["poster_path"], media_type="image/jpeg"
    )


@app.put("/api/projects/{project_id}/layout")
def put_layout(project_id: str, layout: Layout):
    require_project(project_id)
    store.save_slots(project_id, [slot.model_dump() for slot in layout.slots])
    return require_project(project_id)


@app.post("/api/projects/upload", status_code=201)
async def upload(file: UploadFile = File(...), title: str = Form("Новая парковка")):
    if not 1 <= len(title.strip()) <= 100:
        raise HTTPException(422, "Название должно содержать от 1 до 100 символов")
    project_id = uuid4().hex
    folder = DATA / "projects" / project_id
    folder.mkdir()
    source = folder / "original.upload"
    size = 0
    digest = hashlib.sha256()
    try:
        with source.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > 500 * 1024 * 1024:
                    raise HTTPException(
                        413,
                        "Файл превышает 500 МБ. Сначала подготовьте компактную версию.",
                    )
                digest.update(chunk)
                output.write(chunk)
        duration, width, height = await asyncio.to_thread(
            normalize, source, folder / "video.mp4", folder / "poster.jpg"
        )
        metadata = {
            "kind": "video",
            "filename": file.filename,
            "video_path": str(folder / "video.mp4"),
            "poster_path": str(folder / "poster.jpg"),
            "video_duration_seconds": duration,
            "source_duration_seconds": duration,
            "width": width,
            "height": height,
            "source_name": "Ваше видео",
            "sha256": digest.hexdigest(),
            "notice": "Для ускоренного видео укажите известный коэффициент ускорения перед анализом. Неизвестное ускорение не позволяет восстановить реальные длительности.",
        }
        store.create_project(title.strip(), metadata, project_id=project_id)
        return require_project(project_id)
    except HTTPException:
        raise
    except (ValueError, subprocess.SubprocessError, OSError) as error:
        raise HTTPException(422, str(error)) from error
    finally:
        await file.close()
        if not store.project(project_id):
            # Only files created for this generated project ID, never a caller-provided path.
            for path in folder.iterdir():
                if path.is_file():
                    path.unlink()
            folder.rmdir()


@app.post("/api/projects/{project_id}/analyses", status_code=202)
def start_analysis(project_id: str, settings: Settings):
    project = require_project(project_id)
    if not project["slots"]:
        raise HTTPException(422, "Сначала разметьте хотя бы одно парковочное место")
    try:
        run_id = store.create_run(project, settings.model_dump())
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    log = (DATA / "worker.log").open("ab")
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "backend.worker", run_id],
            cwd=str(ROOT),
            stdout=log,
            stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        store.update_run(run_id, pid=process.pid)
    except OSError as error:
        store.update_run(
            run_id,
            status="failed",
            stage="Не удалось запустить процесс",
            error=str(error),
        )
        raise HTTPException(500, "Не удалось запустить обработку") from error
    finally:
        log.close()
    return store.decode_run(store.run(run_id))


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    row = store.run(run_id)
    if not row:
        raise HTTPException(404, "Анализ не найден")
    return store.decode_run(row)


@app.post("/api/runs/{run_id}/cancel")
def cancel(run_id: str):
    row = store.run(run_id)
    if not row:
        raise HTTPException(404, "Анализ не найден")
    if row["status"] not in ("running", "queued"):
        raise HTTPException(409, "Задача уже завершена")
    store.update_run(run_id, cancel_requested=1, stage="Останавливаем анализ")
    return {"status": "cancel_requested"}


@app.get("/api/runs/{run_id}/result")
def get_result(run_id: str):
    return require_result(run_id)


@app.get("/api/runs/{run_id}/summary")
def get_summary(
    run_id: str,
    start: float = Query(0, ge=0, allow_inf_nan=False),
    end: float | None = Query(None, ge=0, allow_inf_nan=False),
):
    try:
        return {"run_id": run_id, **summary(require_result(run_id), start, end)}
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.get("/api/runs/{run_id}/heatmap.png")
def get_heatmap(
    run_id: str,
    start: float = Query(0, ge=0, allow_inf_nan=False),
    end: float | None = Query(None, ge=0, allow_inf_nan=False),
    palette: Literal["thermal", "warm"] = "thermal",
):
    from .heatmap import png_layer

    result = require_result(run_id)
    metadata = require_project(result["project_id"])["metadata"]
    try:
        data = summary(result, start, end)
        return Response(
            png_layer(data["slots"], metadata["width"], metadata["height"], palette),
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=86400"},
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@app.get("/api/runs/{run_id}/export/{format}")
def export(
    run_id: str,
    format: str,
    start: float = Query(0, ge=0, allow_inf_nan=False),
    end: float | None = Query(None, ge=0, allow_inf_nan=False),
    palette: Literal["thermal", "warm"] = "thermal",
    opacity: float = Query(0.6, ge=0, le=1, allow_inf_nan=False),
    video_seconds: float = Query(0, ge=0, allow_inf_nan=False),
    mode: Literal["heatmap", "states"] = "heatmap",
):
    from .exports import png, csv_export, video_export

    result = require_result(run_id)
    project = require_project(result["project_id"])
    end = result["source_duration_seconds"] if end is None else end
    try:
        summary(result, start, end)
        if format == "png":
            return Response(
                png(
                    result,
                    project["metadata"],
                    start,
                    end,
                    palette,
                    opacity,
                    video_seconds,
                ),
                media_type="image/png",
                headers={
                    "Content-Disposition": 'attachment; filename="parking-heatmap.png"'
                },
            )
        if format == "csv":
            return Response(
                csv_export(result, start, end),
                media_type="text/csv",
                headers={
                    "Content-Disposition": 'attachment; filename="parking-statistics.csv"'
                },
            )
        if format == "json":
            return Response(
                json.dumps(result, ensure_ascii=False),
                media_type="application/json",
                headers={
                    "Content-Disposition": 'attachment; filename="parking-analysis.json"'
                },
            )
        if format == "mp4":
            path = video_export(
                result,
                project["metadata"],
                DATA / "projects" / project["id"],
                start,
                end,
                palette,
                opacity,
                mode,
            )
            return FileResponse(
                path,
                media_type="video/mp4",
                filename="parking-heatmap.mp4"
                if mode == "heatmap"
                else "parking-annotated.mp4",
            )
    except (ValueError, subprocess.SubprocessError) as error:
        raise HTTPException(422, str(error)) from error
    raise HTTPException(404, "Неизвестный формат экспорта")


@app.get("/api/projects/{project_id}/layout/export")
def export_layout(project_id: str):
    project = require_project(project_id)
    return Response(
        json.dumps({"slots": project["slots"]}, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="parking-layout.json"'},
    )


@app.get("/api/validation")
def validation():
    path = ROOT / "docs" / "validation.json"
    if not path.exists():
        raise HTTPException(404, "Отчёт о проверке ещё не создан")
    return json.loads(path.read_text(encoding="utf-8"))


DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
