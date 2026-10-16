"""Paths and settings, overridable with environment variables for deployment."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("ROCKET_DATA_DIR", PROJECT_ROOT / "data"))
DB_PATH = DATA_DIR / "rocket.db"
REPLAY_DIR = DATA_DIR / "replays"
TOOLS_DIR = Path(os.environ.get("ROCKET_TOOLS_DIR", PROJECT_ROOT / "tools"))
MAX_UPLOAD_BYTES = int(os.environ.get("ROCKET_MAX_UPLOAD_MB", "30")) * 1024 * 1024
MAX_FILES_PER_UPLOAD = int(os.environ.get("ROCKET_MAX_FILES_PER_UPLOAD", "50"))
