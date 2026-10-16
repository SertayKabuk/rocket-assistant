"""SQLite storage for analysed matches and per-player ratings."""
import json
import sqlite3
from contextlib import contextmanager

from .config import DB_PATH
from .ratings import LEADERBOARD_PRIOR_MATCHES

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    id TEXT PRIMARY KEY,
    replay_id TEXT,
    file TEXT,
    uploaded_at TEXT NOT NULL,
    played_at TEXT,
    map TEXT,
    match_type TEXT,
    team_size INTEGER,
    duration REAL,
    score0 INTEGER,
    score1 INTEGER,
    best_key TEXT,
    best_name TEXT,
    analyzer_version INTEGER,
    rating_version INTEGER,
    analysis TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS match_players (
    match_id TEXT NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    player_key TEXT NOT NULL,
    name TEXT,
    platform TEXT,
    team INTEGER,
    bot INTEGER,
    won INTEGER,
    score INTEGER, goals INTEGER, assists INTEGER, saves INTEGER, shots INTEGER, demos INTEGER,
    seconds REAL,
    attack REAL, defence REAL, boost REAL, speed REAL, overall REAL,
    is_best INTEGER,
    PRIMARY KEY (match_id, player_key)
);
CREATE INDEX IF NOT EXISTS idx_match_players_player ON match_players(player_key);
CREATE INDEX IF NOT EXISTS idx_matches_played ON matches(played_at);
"""

RATING_COLUMNS = ("attack", "defence", "boost", "speed", "overall")


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)


def match_exists(match_id):
    with connect() as conn:
        return conn.execute("SELECT 1 FROM matches WHERE id = ?", (match_id,)).fetchone() is not None


def save_match(match_id, analysis, file_name, uploaded_at, analyzer_version):
    """Insert or replace a match and its player rows."""
    score = analysis["score"]
    best = analysis.get("leaders", {}).get("overall") or {}
    with connect() as conn:
        conn.execute("DELETE FROM matches WHERE id = ?", (match_id,))
        conn.execute(
            """INSERT INTO matches (id, replay_id, file, uploaded_at, played_at, map, match_type, team_size,
                   duration, score0, score1, best_key, best_name, analyzer_version, rating_version, analysis)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (match_id, analysis.get("replayId"), file_name, uploaded_at, _iso_date(analysis.get("date")),
             analysis.get("map"), analysis.get("matchType"), analysis.get("teamSize"), analysis.get("liveSeconds"),
             score[0], score[1], best.get("key"), best.get("name"), analyzer_version,
             analysis.get("ratingVersion"), json.dumps(analysis, separators=(",", ":"))))
        for p in analysis["players"]:
            r = p.get("ratings") or {}
            team = p["team"]
            won = None if score[0] == score[1] or team not in (0, 1) else int(score[team] > score[1 - team])
            conn.execute(
                """INSERT OR REPLACE INTO match_players VALUES
                   (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (match_id, p["key"], p["name"], p.get("platform"), p["team"], int(p.get("bot", False)), won,
                 p.get("score", 0), p.get("goals", 0), p.get("assists", 0), p.get("saves", 0), p.get("shots", 0),
                 (p.get("adv") or {}).get("demos", 0), (p.get("adv") or {}).get("time"),
                 *(r.get(c) for c in RATING_COLUMNS), int(best.get("key") == p["key"])))


def _iso_date(date):
    # Replay dates look like "2026-03-23 23-05-13"
    if not date or len(date) < 19:
        return date
    return f"{date[:10]}T{date[11:13]}:{date[14:16]}:{date[17:19]}"


def all_matches_for_refresh():
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id, file, uploaded_at, analyzer_version, rating_version FROM matches")]


def load_analysis(match_id):
    with connect() as conn:
        row = conn.execute("SELECT analysis, uploaded_at FROM matches WHERE id = ?", (match_id,)).fetchone()
    if row is None:
        return None
    return {**json.loads(row["analysis"]), "id": match_id, "uploadedAt": row["uploaded_at"]}


def list_matches(limit=50, offset=0, player_key=None):
    where, params = "", []
    if player_key:
        where = "WHERE id IN (SELECT match_id FROM match_players WHERE player_key = ?)"
        params.append(player_key)
    with connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM matches {where}", params).fetchone()[0]
        rows = conn.execute(
            f"""SELECT id, played_at, uploaded_at, map, match_type, team_size, duration, score0, score1,
                       best_key, best_name
                FROM matches {where} ORDER BY played_at DESC LIMIT ? OFFSET ?""",
            [*params, limit, offset]).fetchall()
        players = {}
        if rows:
            ids = [r["id"] for r in rows]
            marks = ",".join("?" * len(ids))
            for p in conn.execute(
                    f"""SELECT match_id, player_key, name, team, overall FROM match_players
                        WHERE match_id IN ({marks}) ORDER BY team, score DESC""", ids):
                players.setdefault(p["match_id"], []).append(
                    {"key": p["player_key"], "name": p["name"], "team": p["team"], "overall": p["overall"]})
    return {"total": total, "matches": [{**dict(r), "players": players.get(r["id"], [])} for r in rows]}


def leaderboard(min_matches=1, team_size=None, since=None, players=None, together=False):
    """Average ratings per player.

    team_size / since (ISO date) limit which matches count; players limits the output to those keys;
    together counts only matches where a player had another of `players` on their team.
    """
    where, params = _base_filters(team_size, since)
    if players:
        marks = ",".join("?" * len(players))
        where.append(f"mp.player_key IN ({marks})")
        params.extend(players)
        if together:
            where.append(f"""EXISTS (SELECT 1 FROM match_players o WHERE o.match_id = mp.match_id
                             AND o.team = mp.team AND o.player_key <> mp.player_key AND o.player_key IN ({marks}))""")
            params.extend(players)
    with connect() as conn:
        rows = conn.execute(
            """SELECT mp.player_key AS key,
                      (SELECT name FROM match_players x JOIN matches m ON m.id = x.match_id
                       WHERE x.player_key = mp.player_key ORDER BY m.played_at DESC LIMIT 1) AS name,
                      MAX(mp.platform) AS platform,
                      COUNT(*) AS matches, SUM(mp.won) AS wins, SUM(mp.is_best) AS mvps,
                      SUM(mp.goals) AS goals, SUM(mp.assists) AS assists, SUM(mp.saves) AS saves,
                      SUM(mp.shots) AS shots, SUM(mp.demos) AS demos, SUM(mp.seconds) AS seconds,
                      """ + ", ".join(f"AVG(mp.{c}) AS {c}, COUNT(mp.{c}) AS n_{c}" for c in RATING_COLUMNS) + """
               FROM match_players mp JOIN matches m ON m.id = mp.match_id
               WHERE """ + " AND ".join(where) + """
               GROUP BY mp.player_key
               HAVING COUNT(*) >= ?""", (*params, min_matches)).fetchall()
    means = rating_means(team_size, since)
    board = [_shrink(dict(r), means) for r in rows]
    board.sort(key=lambda r: r["overall"] if r["overall"] is not None else -1, reverse=True)
    return board


def _base_filters(team_size=None, since=None):
    where, params = ["mp.bot = 0", "mp.overall IS NOT NULL"], []
    if team_size:
        where.append("m.team_size = ?")
        params.append(team_size)
    if since:
        where.append("m.played_at >= ?")
        params.append(since)
    return where, params


def rating_means(team_size=None, since=None):
    """Average per-match rating of all rated players (within the same mode/period filters)."""
    where, params = _base_filters(team_size, since)
    with connect() as conn:
        row = conn.execute(
            "SELECT " + ", ".join(f"AVG(mp.{c}) AS {c}" for c in RATING_COLUMNS) +
            " FROM match_players mp JOIN matches m ON m.id = mp.match_id WHERE " + " AND ".join(where),
            params).fetchone()
    return {c: row[c] for c in RATING_COLUMNS}


def _shrink(row, means):
    """Pull a player's average toward the population mean: with few matches it says little about them.

    Adds the plain average as `<category>Raw`; `<category>` becomes the adjusted value used for ranking.
    """
    k = LEADERBOARD_PRIOR_MATCHES
    for c in RATING_COLUMNS:
        n, raw, mean = row.pop(f"n_{c}"), row[c], means[c]
        row[f"{c}Raw"] = round(raw, 1) if raw is not None else None
        if raw is not None and mean is not None:
            row[c] = round((n * raw + k * mean) / (n + k), 1)
    return row


def player_rows(player_key):
    with connect() as conn:
        rows = conn.execute(
            """SELECT mp.*, m.played_at, m.map, m.match_type, m.team_size, m.score0, m.score1
               FROM match_players mp JOIN matches m ON m.id = mp.match_id
               WHERE mp.player_key = ? ORDER BY m.played_at""", (player_key,)).fetchall()
    return [dict(r) for r in rows]


def counts():
    with connect() as conn:
        matches = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        players = conn.execute(
            "SELECT COUNT(DISTINCT player_key) FROM match_players WHERE bot = 0").fetchone()[0]
    return {"matches": matches, "players": players}
