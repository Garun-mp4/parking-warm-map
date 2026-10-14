from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3
from uuid import uuid4
from .config import DB


@contextmanager
def connection():
    db = sqlite3.connect(DB, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def initialize():
    with connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, created TEXT NOT NULL,
            metadata TEXT NOT NULL, slots TEXT NOT NULL DEFAULT '[]', revision INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, created TEXT NOT NULL,
            status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0, stage TEXT NOT NULL DEFAULT '',
            settings TEXT NOT NULL, slots TEXT NOT NULL, revision INTEGER NOT NULL,
            error TEXT, result_path TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0, pid INTEGER);
        """)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(runs)")}
        if "pid" not in columns:
            db.execute("ALTER TABLE runs ADD COLUMN pid INTEGER")


def now():
    return datetime.now(timezone.utc).isoformat()


def create_project(title, metadata, slots=None, project_id=None):
    project_id = project_id or uuid4().hex
    with connection() as db:
        db.execute(
            "INSERT INTO projects(id,title,created,metadata,slots) VALUES(?,?,?,?,?)",
            (project_id, title, now(), json.dumps(metadata), json.dumps(slots or [])),
        )
    return project_id


def decode_project(row):
    project = dict(row)
    project["metadata"] = json.loads(project["metadata"])
    project["slots"] = json.loads(project["slots"])
    with connection() as db:
        run = db.execute(
            "SELECT * FROM runs WHERE project_id=? ORDER BY created DESC LIMIT 1",
            (project["id"],),
        ).fetchone()
        completed = db.execute(
            "SELECT id FROM runs WHERE project_id=? AND status='completed' ORDER BY created DESC LIMIT 1",
            (project["id"],),
        ).fetchone()
    project["latest_run"] = decode_run(run) if run else None
    project["completed_run_id"] = completed["id"] if completed else None
    return project


def project(project_id):
    with connection() as db:
        row = db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    return decode_project(row) if row else None


def projects():
    with connection() as db:
        rows = db.execute("SELECT * FROM projects ORDER BY created DESC").fetchall()
    return [decode_project(row) for row in rows]


def save_slots(project_id, slots):
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute(
            "SELECT slots FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        if current and json.dumps(
            json.loads(current["slots"]), sort_keys=True
        ) == json.dumps(slots, sort_keys=True):
            return
        db.execute(
            "UPDATE projects SET slots=?,revision=revision+1 WHERE id=?",
            (json.dumps(slots), project_id),
        )


def decode_run(row):
    if not row:
        return None
    result = dict(row)
    result["settings"] = json.loads(result["settings"])
    result["slots"] = json.loads(result["slots"])
    result.pop("result_path", None)
    return result


def run(run_id):
    with connection() as db:
        row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    return dict(row) if row else None


def create_run(project_data, settings):
    run_id = uuid4().hex
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        active = db.execute(
            "SELECT id FROM runs WHERE status IN ('queued','running')"
        ).fetchone()
        if active:
            raise ValueError(
                "Уже выполняется анализ. Дождитесь завершения или отмените его."
            )
        db.execute(
            "INSERT INTO runs(id,project_id,created,status,settings,slots,revision) VALUES(?,?,?,?,?,?,?)",
            (
                run_id,
                project_data["id"],
                now(),
                "queued",
                json.dumps(settings),
                json.dumps(project_data["slots"]),
                project_data["revision"],
            ),
        )
    return run_id


def update_run(run_id, **values):
    permitted = {
        "status",
        "progress",
        "stage",
        "error",
        "result_path",
        "cancel_requested",
        "pid",
    }
    if not values or not set(values) <= permitted:
        raise ValueError("Invalid update")
    with connection() as db:
        db.execute(
            f"UPDATE runs SET {','.join(k + '=?' for k in values)} WHERE id=?",
            [*values.values(), run_id],
        )
