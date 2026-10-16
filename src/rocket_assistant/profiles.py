"""Aggregate a player's matches into a profile."""
from . import db
from .ratings import CATEGORIES, describe_model

CATS = ("overall", *CATEGORIES)
ADV_KEYS = ("avgSpeed", "supersonicPct", "boostPerMin", "avgBoost", "emptyBoostPct", "fullBoostPct",
            "boostCollected", "bigPads", "smallPads", "defThirdPct", "midThirdPct", "offThirdPct",
            "behindBallPct", "groundPct", "lowAirPct", "highAirPct", "demos", "demoed")
MAX_DETAIL_MATCHES = 50
RANK_MIN_MATCHES = 3


def player_profile(key):
    rows = db.player_rows(key)
    if not rows:
        return None
    rated = [r for r in rows if r["overall"] is not None]
    everyone_board = db.leaderboard(min_matches=1)
    everyone = {c: _avg([r[c] for r in everyone_board]) for c in CATS}
    # Rank against players with a comparable number of matches, so one lucky game doesn't outrank a regular
    rank_min = max(1, min(RANK_MIN_MATCHES, len(rated)))
    board = db.leaderboard(min_matches=rank_min)
    rank = next((i + 1 for i, r in enumerate(board) if r["key"] == key), None)
    mine = {c: _avg([r[c] for r in rated]) for c in CATS}
    comparison = sorted(
        ({"category": c, "rating": mine[c], "average": everyone[c],
          "diff": round(mine[c] - everyone[c], 1) if mine[c] is not None and everyone[c] is not None else None}
         for c in CATEGORIES),
        key=lambda x: x["diff"] if x["diff"] is not None else 0, reverse=True)

    adv_sums, heat, heat_n, breakdown = {}, None, 0, {}
    for row in rated[-MAX_DETAIL_MATCHES:]:
        analysis = db.load_analysis(row["match_id"])
        player = next((p for p in analysis["players"] if p["key"] == key), None)
        if not player or not player.get("adv"):
            continue
        for k in ADV_KEYS:
            adv_sums.setdefault(k, []).append(player["adv"].get(k, 0))
        if player.get("heatmap"):
            # Mirror orange-team maps so the player's own goal is always on the left
            cells = player["heatmap"] if player["team"] == 0 else player["heatmap"][::-1]
            heat = cells if heat is None else [a + b for a, b in zip(heat, cells, strict=True)]
            heat_n += 1
        for cat, parts in (player.get("ratings") or {}).get("breakdown", {}).items():
            for part in parts:
                entry = {"label": part["label"], "values": [], "scores": []}
                breakdown.setdefault(cat, {}).setdefault(part["key"], entry)
                breakdown[cat][part["key"]]["values"].append(part["value"])
                breakdown[cat][part["key"]]["scores"].append(part["score"])

    latest = rows[-1]
    return {
        "key": key,
        "name": latest["name"],
        "aliases": sorted({r["name"] for r in rows} - {latest["name"]}),
        "platform": latest["platform"],
        "rank": rank,
        "rankedPlayers": len(board),
        "rankMinMatches": rank_min,
        "matches": len(rows),
        "ratedMatches": len(rated),
        "wins": sum(1 for r in rows if r["won"]),
        "mvps": sum(r["is_best"] or 0 for r in rows),
        "totals": {k: sum(r[k] or 0 for r in rows) for k in ("goals", "assists", "saves", "shots", "demos", "score")},
        "ratings": mine,
        "everyone": everyone,
        "comparison": comparison,
        "adv": {k: round(_avg(v), 1) for k, v in adv_sums.items()},
        "breakdown": {cat: [{"key": k, "label": v["label"], "value": round(_avg(v["values"]), 2),
                             "score": round(_avg(v["scores"]))} for k, v in parts.items()]
                      for cat, parts in breakdown.items()},
        "heatmap": [round(v / heat_n, 5) for v in heat] if heat else None,
        "history": [{"matchId": r["match_id"], "playedAt": r["played_at"], "map": r["map"],
                     "teamSize": r["team_size"], "team": r["team"], "won": r["won"], "isBest": bool(r["is_best"]),
                     "score": [r["score0"], r["score1"]], "goals": r["goals"], "assists": r["assists"],
                     "saves": r["saves"], "shots": r["shots"], **{c: r[c] for c in CATS}} for r in rows],
        "model": describe_model(),
    }


def _avg(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 1) if values else None
