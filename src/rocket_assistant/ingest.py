"""Parse replay files with rrrocket, analyse, rate and store them."""
import io
import json
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

from . import db
from .analyze import ANALYZER_VERSION, analyze, summarize
from .config import MAX_UPLOAD_BYTES, REPLAY_DIR, TOOLS_DIR
from .ratings import RATING_VERSION, rate_match

RRROCKET_VERSION = "0.11.7"
RRROCKET_TARGETS = {
    ("Windows", "AMD64"): "x86_64-pc-windows-msvc.zip",
    ("Linux", "x86_64"): "x86_64-unknown-linux-musl.tar.gz",
    ("Darwin", "x86_64"): "x86_64-apple-darwin.tar.gz",
    ("Darwin", "arm64"): "aarch64-apple-darwin.tar.gz",
}


class ReplayError(Exception):
    pass


@cache
def rrrocket_path():
    if env := os.environ.get("RRROCKET"):
        return env
    if found := shutil.which("rrrocket"):
        return found
    exe = "rrrocket.exe" if platform.system() == "Windows" else "rrrocket"
    local = next(TOOLS_DIR.rglob(exe), None) if TOOLS_DIR.exists() else None
    if local:
        return str(local)
    target = RRROCKET_TARGETS.get((platform.system(), platform.machine()))
    if not target:
        raise RuntimeError(
            "No prebuilt rrrocket for this platform. Build it with "
            "`cargo install --git https://github.com/nickbabcock/rrrocket rrrocket` and set RRROCKET=/path/to/rrrocket"
        )
    url = (f"https://github.com/nickbabcock/rrrocket/releases/download/v{RRROCKET_VERSION}/"
           f"rrrocket-{RRROCKET_VERSION}-{target}")
    print(f"Downloading rrrocket {RRROCKET_VERSION} ...")
    with urllib.request.urlopen(url) as resp:
        payload = io.BytesIO(resp.read())
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    if target.endswith(".zip"):
        zipfile.ZipFile(payload).extractall(TOOLS_DIR)
    else:
        with tarfile.open(fileobj=payload) as tar:
            tar.extractall(TOOLS_DIR, filter="data")
    local = next(TOOLS_DIR.rglob(exe))
    local.chmod(0o755)
    return str(local)


def _parse(path, network):
    args = [rrrocket_path()] + (["-n"] if network else []) + [str(path)]
    proc = subprocess.run(args, capture_output=True, check=False)
    if proc.returncode != 0:
        raise ReplayError("Could not read this file. Is it a Rocket League .replay file?")
    return json.loads(proc.stdout)


def _build_analysis(path):
    summary = summarize(_parse(path, network=False))
    return rate_match(analyze(_parse(path, network=True), summary))


def ingest_file(path, original_name=None):
    """Analyse one replay file. Returns {"status": "added"|"duplicate", "match": {...}}."""
    path = Path(path)
    original_name = original_name or path.name
    header = summarize(_parse(path, network=False))
    if not header["players"]:
        raise ReplayError("Replay has no player stats")
    match_id = header["matchGuid"] or header["replayId"]
    if not match_id:
        raise ReplayError("Replay has no id")
    if db.match_exists(match_id):
        return {"status": "duplicate", "match": _brief(match_id, header)}

    analysis = rate_match(analyze(_parse(path, network=True), header))
    REPLAY_DIR.mkdir(parents=True, exist_ok=True)
    stored = REPLAY_DIR / f"{match_id}.replay"
    if path.resolve() != stored.resolve():
        shutil.copyfile(path, stored)
    db.save_match(match_id, analysis, original_name, _now(), ANALYZER_VERSION)
    return {"status": "added", "match": _brief(match_id, analysis)}


def ingest_bytes(data, original_name):
    if len(data) > MAX_UPLOAD_BYTES:
        raise ReplayError("File is too large")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "upload.replay"
        path.write_bytes(data)
        return ingest_file(path, original_name)


def _brief(match_id, summary):
    return {"id": match_id, "map": summary["map"], "date": summary["date"], "score": summary["score"],
            "teamSize": summary["teamSize"], "best": (summary.get("leaders") or {}).get("overall")}


def _now():
    return datetime.now(UTC).isoformat(timespec="seconds")


def refresh_outdated():
    """Re-analyse or re-rate stored matches after the analyzer or rating model changed."""
    updated = 0
    for row in db.all_matches_for_refresh():
        stored = REPLAY_DIR / f"{row['id']}.replay"
        reanalyze = row["analyzer_version"] != ANALYZER_VERSION and stored.exists()
        if not reanalyze and row["rating_version"] == RATING_VERSION:
            continue
        analysis = _build_analysis(stored) if reanalyze else rate_match(db.load_analysis(row["id"]))
        version = ANALYZER_VERSION if reanalyze else row["analyzer_version"]
        db.save_match(row["id"], analysis, row["file"], row["uploaded_at"], version)
        updated += 1
    return updated


def import_folder(folder):
    results = {"added": 0, "duplicate": 0, "failed": 0}
    for path in sorted(Path(folder).glob("*.replay")):
        try:
            results[ingest_file(path)["status"]] += 1
        except Exception as e:  # noqa: BLE001 - keep importing the rest
            results["failed"] += 1
            print(f"  {path.name}: {e}")
    return results


def default_demos_folder():
    home = Path.home()
    for candidate in (home / "Documents" / "My Games" / "Rocket League" / "TAGame" / "Demos",
                      home / "OneDrive" / "Documents" / "My Games" / "Rocket League" / "TAGame" / "Demos"):
        if candidate.is_dir():
            return candidate
    return None
