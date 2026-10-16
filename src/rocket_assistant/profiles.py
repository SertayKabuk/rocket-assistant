"""Aggregate a player's matches into a profile."""
from . import db
from .ratings import CATEGORIES, LEADERBOARD_PRIOR_MATCHES, describe_model

CATS = ("overall", *CATEGORIES)
ADV_KEYS = ("avgSpeed", "supersonicPct", "boostPerMin", "avgBoost", "emptyBoostPct", "fullBoostPct",
            "boostCollected", "bigPads", "smallPads", "defThirdPct", "midThirdPct", "offThirdPct",
            "behindBallPct", "groundPct", "lowAirPct", "highAirPct", "demos", "demoed")
MAX_DETAIL_MATCHES = 50


def player_profile(key):
    rows = db.player_rows(key)
    if not rows:
        return None
    rated = [r for r in rows if r["overall"] is not None]
    everyone = {c: round(v, 1) if v is not None else None for c, v in db.rating_means().items()}
    # Same adjusted (shrunk) averages and ranking as the leaderboard
    board = db.leaderboard(min_matches=1)
    rank = next((i + 1 for i, r in enumerate(board) if r["key"] == key), None)
    entry = board[rank - 1] if rank else None
    raw = {c: _avg([r[c] for r in rated]) for c in CATS}
    mine = {c: entry[c] for c in CATS} if entry else raw
    comparison = sorted(
        ({"category": c, "rating": mine[c], "average": everyone[c],
          "diff": _diff(mine[c], everyone[c])}
         for c in CATEGORIES),
        key=lambda x: x["diff"] if x["diff"] is not None else 0, reverse=True)

    adv_sums, heat, heat_n, breakdown = {}, None, 0, {}
    for row in rated[-MAX_DETAIL_MATCHES:]:
        analysis = db.load_analysis(row["match_id"])
        if not analysis:
            continue
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
        "matches": len(rows),
        "ratedMatches": len(rated),
        "wins": sum(1 for r in rows if r["won"]),
        "mvps": sum(r["is_best"] or 0 for r in rows),
        "totals": {k: sum(r[k] or 0 for r in rows) for k in ("goals", "assists", "saves", "shots", "demos", "score")},
        "ratings": mine,
        "ratingsRaw": raw,
        "priorMatches": LEADERBOARD_PRIOR_MATCHES,
        "everyone": everyone,
        "comparison": comparison,
        "adv": {k: _avg(v) for k, v in adv_sums.items()},
        "breakdown": {cat: [{"key": k, "label": v["label"], "value": _avg(v["values"], 2),
                             "score": _avg(v["scores"], 0)} for k, v in parts.items()]
                      for cat, parts in breakdown.items()},
        "heatmap": [round(v / heat_n, 5) for v in heat] if heat else None,
        "history": [{"matchId": r["match_id"], "playedAt": r["played_at"], "map": r["map"],
                     "teamSize": r["team_size"], "team": r["team"], "won": r["won"], "isBest": bool(r["is_best"]),
                     "score": [r["score0"], r["score1"]], "goals": r["goals"], "assists": r["assists"],
                     "saves": r["saves"], "shots": r["shots"], **{c: r[c] for c in CATS}} for r in rows],
        "model": describe_model(),
    }


def _avg(values, digits=1):
    """Mean of the non-None values, rounded (digits=0 gives an int), or None if there are none."""
    values = [v for v in values if v is not None]
    if not values:
        return None
    mean = sum(values) / len(values)
    return round(mean, digits) if digits else round(mean)


def _diff(a, b):
    return round(a - b, 1) if a is not None and b is not None else None
