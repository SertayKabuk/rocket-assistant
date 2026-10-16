"""Per-match player ratings (0-100) for attack, defence, boost, speed and overall.

Every metric is mapped linearly onto 0-100 between a "low" and "high" benchmark
(clamped), then weighted within its category. Counting stats are normalised to
"per 5 minutes" of play so short games and overtime don't skew the comparison.
Benchmarks are fixed (not relative to other uploads) so a rating means the same
thing no matter how many replays are in the database.
"""

RATING_VERSION = 2
MIN_SECONDS = 60  # players with less time on the field aren't rated

# (key, label, low, high, weight); low > high means "lower is better"
CATEGORIES = {
    "attack": [
        ("goals5", "Goals / 5 min", 0, 2, 0.35),
        ("shots5", "Shots / 5 min", 0, 4, 0.25),
        ("assists5", "Assists / 5 min", 0, 1.5, 0.15),
        ("offThirdPct", "Time in attacking third %", 12, 30, 0.15),
        ("shootingPct", "Shooting %", 0, 50, 0.10),
    ],
    "defence": [
        ("saves5", "Saves / 5 min", 0, 3, 0.5),
        ("behindBallPct", "Time behind ball %", 60, 85, 0.3),
        ("defThirdPct", "Time in defensive third %", 35, 55, 0.2),
    ],
    "boost": [
        ("emptyBoostPct", "Time at 0 boost %", 20, 4, 0.3),
        ("collectedPerMin", "Boost collected / min", 200, 450, 0.3),
        ("smallPadsPerMin", "Small pads / min", 4, 12, 0.25),
        ("fullBoostPct", "Time at 100 boost %", 30, 5, 0.15),
    ],
    "speed": [
        ("avgSpeed", "Average speed (uu/s)", 1150, 1550, 0.4),
        ("supersonicPct", "Time supersonic %", 2, 14, 0.3),
        ("slowPct", "Time at slow speed %", 70, 40, 0.15),
        ("highAirPct", "Time high in the air %", 1, 8, 0.15),
    ],
}
OVERALL_WEIGHTS = {"attack": 0.3, "defence": 0.3, "boost": 0.15, "speed": 0.15, "impact": 0.1}
IMPACT = ("scorePerMin", "In-game score / min", 50, 150)
CATEGORY_LABELS = {"attack": "Attack", "defence": "Defence", "boost": "Boost", "speed": "Speed", "overall": "Overall"}


def _scale(value, low, high):
    if high == low:
        return 0.0
    return max(0.0, min(100.0, (value - low) / (high - low) * 100))


def player_metrics(player):
    adv = player.get("adv")
    if not adv or adv["time"] < MIN_SECONDS:
        return None
    minutes = adv["time"] / 60
    per5 = 5 / minutes
    return {
        **adv,
        "goals5": player["goals"] * per5,
        "shots5": player["shots"] * per5,
        "assists5": player["assists"] * per5,
        "saves5": player["saves"] * per5,
        "shootingPct": player["goals"] / player["shots"] * 100 if player["shots"] else 0,
        "collectedPerMin": adv["boostCollected"] / minutes if adv["boostCollected"] is not None else None,
        "smallPadsPerMin": adv["smallPads"] / minutes if adv["smallPads"] is not None else None,
        "scorePerMin": player["score"] / minutes,
    }


def rate_player(player):
    """Return {"attack": .., "defence": .., "boost": .., "speed": .., "overall": .., "breakdown": {...}} or None."""
    if player.get("bot"):
        return None
    metrics = player_metrics(player)
    if metrics is None:
        return None
    ratings, breakdown = {}, {}
    for cat, parts in CATEGORIES.items():
        if any(metrics.get(key) is None for key, *_ in parts):
            ratings[cat] = None  # missing data (e.g. no boost info in the replay)
            continue
        total = 0.0
        breakdown[cat] = []
        for key, label, low, high, weight in parts:
            score = _scale(metrics[key], low, high)
            total += score * weight
            breakdown[cat].append({"key": key, "label": label, "value": round(metrics[key], 2), "score": round(score)})
        ratings[cat] = round(total, 1)
    key, label, low, high = IMPACT
    impact = _scale(metrics[key], low, high)
    breakdown["impact"] = [{"key": key, "label": label, "value": round(metrics[key], 1), "score": round(impact)}]
    # Weighted average over the categories that could be rated
    scores = {c: impact if c == "impact" else ratings[c] for c in OVERALL_WEIGHTS}
    available = {c: w for c, w in OVERALL_WEIGHTS.items() if scores[c] is not None}
    ratings["overall"] = round(sum(scores[c] * w for c, w in available.items()) / sum(available.values()), 1)
    ratings["breakdown"] = breakdown
    return ratings


def rate_match(analysis):
    """Add `ratings` to every player and pick the best player per category."""
    leaders = {}
    for p in analysis["players"]:
        p["ratings"] = rate_player(p)
    rated = [p for p in analysis["players"] if p["ratings"]]
    for cat in ("overall", *CATEGORIES):
        candidates = [p for p in rated if p["ratings"][cat] is not None]
        if candidates:
            best = max(candidates, key=lambda p: p["ratings"][cat])
            leaders[cat] = {"key": best["key"], "name": best["name"], "team": best["team"],
                            "rating": best["ratings"][cat]}
    analysis["leaders"] = leaders
    analysis["ratingVersion"] = RATING_VERSION
    return analysis


def describe_model():
    """The model as data, so the UI can explain how ratings are calculated."""
    return {
        "version": RATING_VERSION,
        "minSeconds": MIN_SECONDS,
        "overallWeights": OVERALL_WEIGHTS,
        "labels": CATEGORY_LABELS,
        "categories": {cat: [{"key": k, "label": label, "low": lo, "high": hi, "weight": w}
                             for k, label, lo, hi, w in parts]
                       for cat, parts in CATEGORIES.items()},
        "impact": {"key": IMPACT[0], "label": IMPACT[1], "low": IMPACT[2], "high": IMPACT[3]},
    }
