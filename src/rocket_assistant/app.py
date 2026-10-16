"""FastAPI web app: upload replays, browse matches, leaderboard and player profiles."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .config import MAX_FILES_PER_UPLOAD, MAX_UPLOAD_BYTES
from .ingest import ReplayError, ingest_bytes
from .profiles import player_profile
from .ratings import describe_model

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Rocket Assistant")


@app.post("/api/replays")
def upload_replays(files: list[UploadFile]):
    if len(files) > MAX_FILES_PER_UPLOAD:
        raise HTTPException(400, f"Upload at most {MAX_FILES_PER_UPLOAD} files at a time")
    payloads = []
    for f in files:
        name = Path(f.filename or "upload.replay").name
        data = f.file.read(MAX_UPLOAD_BYTES + 1)
        payloads.append((name, data))

    def process(item):
        name, data = item
        if not name.lower().endswith(".replay"):
            return {"file": name, "status": "error", "error": "Not a .replay file"}
        try:
            return {"file": name, **ingest_bytes(data, name)}
        except ReplayError as e:
            return {"file": name, "status": "error", "error": str(e)}
        except Exception as e:  # noqa: BLE001
            return {"file": name, "status": "error", "error": f"Could not analyse replay ({e.__class__.__name__})"}

    with ThreadPoolExecutor(max_workers=4) as pool:
        return {"results": list(pool.map(process, payloads))}


@app.get("/api/matches")
def matches(limit: int = 50, offset: int = 0, player: str | None = None):
    return db.list_matches(min(max(limit, 1), 200), max(offset, 0), player)


@app.get("/api/matches/{match_id}")
def match(match_id: str):
    analysis = db.load_analysis(match_id)
    if analysis is None:
        raise HTTPException(404, "Match not found")
    return analysis


@app.get("/api/players")
def players(min_matches: int = 1, mode: int | None = None, days: int | None = None,
            player: Annotated[list[str] | None, Query()] = None, together: bool = False):
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds") if days else None
    rows = db.leaderboard(max(min_matches, 1), team_size=mode, since=since, players=player, together=together)
    return {"players": rows, "model": describe_model()}


@app.get("/api/players/{key:path}")
def player(key: str):
    profile = player_profile(key)
    if profile is None:
        raise HTTPException(404, "Player not found")
    return profile


@app.get("/api/stats")
def stats():
    return db.counts()


@app.get("/api/model")
def model():
    return describe_model()


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")
