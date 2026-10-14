import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("PARKING_DATA_DIR", str(ROOT / "data"))).resolve()
MODELS = ROOT / "models"
DB = DATA / "parking.sqlite3"
FFMPEG = os.environ.get("PARKING_FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("PARKING_FFPROBE", "ffprobe")
for folder in (DATA, DATA / "projects", MODELS):
    folder.mkdir(parents=True, exist_ok=True)
