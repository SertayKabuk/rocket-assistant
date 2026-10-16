import argparse
import json
import os
import threading
import webbrowser
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="rocket-assistant", description="Rocket League replay analyzer")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="run the web app (default)")
    serve.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8765")))
    serve.add_argument("--no-browser", action="store_true")
    imp = sub.add_parser("import", help="import every .replay file in a folder")
    imp.add_argument("folder", nargs="?", type=Path, help="defaults to your Rocket League Demos folder")
    cal = sub.add_parser("calibrate", help="recompute rating benchmarks from the stored matches and re-rate them")
    cal.add_argument("--output", type=Path, help="where to write benchmarks (default: DATA_DIR/benchmarks.json)")
    args = parser.parse_args()

    from . import db
    from .ingest import default_demos_folder, import_folder, import_orphans, refresh_outdated

    db.init()
    if args.command == "calibrate":
        return _calibrate(args.output)
    if args.command == "import":
        folder = args.folder or default_demos_folder()
        if not folder or not folder.is_dir():
            parser.error("Replay folder not found; pass it explicitly")
        print(f"Importing replays from {folder} ...")
        print(import_folder(folder))
        return

    import uvicorn

    if updated := refresh_outdated():
        print(f"Re-analysed {updated} stored matches")
    if orphans := import_orphans():
        print(f"Imported {orphans} stored replays that were missing from the database")
    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 8765)
    url = f"http://{'127.0.0.1' if host == '0.0.0.0' else host}:{port}"
    if not getattr(args, "no_browser", False):
        threading.Timer(1.0, webbrowser.open, [url]).start()
    print(f"Rocket Assistant running at {url}")
    uvicorn.run("rocket_assistant.app:app", host=host, port=port, log_level="warning")


def _calibrate(output):
    from . import db, ratings
    from .ingest import refresh_outdated

    analyses = [db.load_analysis(row["id"]) for row in db.all_matches_for_refresh()]
    bench = ratings.calibrate(analyses)
    output = output or ratings.CUSTOM_BENCHMARKS
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(bench, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote benchmarks from {bench['matches']} matches to {output}")
    for mode, b in bench["modes"].items():
        print(f"  {mode}v{mode}: {b['rows']} rated player-matches, priors {b['priors']}")
    if output.resolve() != ratings.CUSTOM_BENCHMARKS.resolve() and ratings.CUSTOM_BENCHMARKS.exists():
        print(f"Note: {ratings.CUSTOM_BENCHMARKS} exists and takes precedence over this file")
    ratings.BENCHMARKS = ratings.load_benchmarks()
    print(f"Re-rated {refresh_outdated()} stored matches")
