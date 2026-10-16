"""Per-match player ratings (0-100) for attack, defence, boost, speed and overall.

Each stat is placed on a 0-100 scale between benchmarks taken from real matches of the same
mode (1v1, 2v2, 3v3): the 10th percentile scores 0 and the 90th scores 100 (reversed for
"lower is better" stats). Stats in a category are then combined with fixed weights.
Counting stats are normalised to "per 5 minutes" so short games and overtime compare fairly.

Benchmarks live in benchmarks.json (shipped with the app) and can be recalibrated from the
database with `rocket-assistant calibrate`, which writes DATA_DIR/benchmarks.json.
"""
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from .config import DATA_DIR

RATING_VERSION = 3  # bump when the formulas change; benchmark changes are tracked by their hash
MIN_SECONDS = 60  # players with less time on the field aren't rated
SHOT_PRIOR = 4  # shooting % is blended with the mode's average conversion, worth this many shots
SAVE_PRIOR = 4  # save rate likewise, worth this many opponent shots
LEADERBOARD_PRIOR_MATCHES = 10  # leaderboard averages are pulled toward the population mean by this many matches
MIN_CALIBRATION_ROWS = 50  # a mode needs this many rated player-matches to get its own benchmarks
LOW_PCT, HIGH_PCT = 0.10, 0.90

# (key, label, weight, higher_is_better)
CATEGORIES = {
    "attack": [
        ("goals5", "Goals / 5 min", 0.35, True),
        ("shots5", "Shots / 5 min", 0.25, True),
        ("assists5", "Assists / 5 min", 0.15, True),
        ("offThirdPct", "Time in attacking third %", 0.15, True),
        ("shootingPct", "Shooting % (adjusted)", 0.10, True),
    ],
    "defence": [
        ("saveRate", "Saves per opponent shot %", 0.40, True),
        ("behindBallPct", "Time behind ball %", 0.35, True),
        ("conceded5", "Team goals conceded / 5 min", 0.25, False),
    ],
    "boost": [
        ("emptyBoostPct", "Time at 0 boost %", 0.30, False),
        ("collectedPerMin", "Boost collected / min", 0.30, True),
        ("smallPadsPerMin", "Small pads / min", 0.25, True),
        ("fullBoostPct", "Time at 100 boost %", 0.15, False),
    ],
    "speed": [
        ("avgSpeed", "Average speed (uu/s)", 0.40, True),
        ("supersonicPct", "Time supersonic %", 0.30, True),
        ("slowPct", "Time at slow speed %", 0.15, False),
        ("highAirPct", "Time high in the air %", 0.15, True),
    ],
}
IMPACT = ("scorePerMin", "In-game score / min", 1.0, True)
OVERALL_WEIGHTS = {"attack": 0.3, "defence": 0.3, "boost": 0.1, "speed": 0.1, "impact": 0.2}
CATEGORY_LABELS = {"attack": "Attack", "defence": "Defence", "boost": "Boost", "speed": "Speed", "overall": "Overall"}
METRIC_KEYS = [key for parts in CATEGORIES.values() for key, *_ in parts] + [IMPACT[0]]

PACKAGED_BENCHMARKS = Path(__file__).with_name("benchmarks.json")
CUSTOM_BENCHMARKS = DATA_DIR / "benchmarks.json"


def load_benchmarks():
    """Benchmarks from DATA_DIR (written by `calibrate`), else the ones shipped with the app."""
    for path in (CUSTOM_BENCHMARKS, PACKAGED_BENCHMARKS):
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return {"modes": {}}  # only while bootstrapping: rating needs benchmarks, calibrating doesn't


BENCHMARKS = load_benchmarks()


def model_version(benchmarks=None):
    """Formula version plus a hash of the benchmarks, so recalibrating re-rates stored matches."""
    b = benchmarks or BENCHMARKS
    digest = hashlib.sha256(json.dumps(b["modes"], sort_keys=True).encode()).hexdigest()[:8]
    return f"{RATING_VERSION}-{digest}"  # never numeric, so SQLite keeps it as text


def _mode_benchmarks(team_size, benchmarks=None):
    modes = (benchmarks or BENCHMARKS)["modes"]
    if not modes:
        raise RuntimeError("No rating benchmarks found; run `rocket-assistant calibrate`")
    if str(team_size) in modes:
        return modes[str(team_size)]
    nearest = min(modes, key=lambda m: abs(int(m) - (team_size or 3)))  # e.g. 4v4 uses 3v3
    return modes[nearest]


def _scale(value, low, high):
    if high == low:
        return 50.0
    return max(0.0, min(100.0, (value - low) / (high - low) * 100))


def match_context(analysis):
    """Per-team numbers that player metrics depend on (opponent shots, goals conceded)."""
    players, score = analysis["players"], analysis["score"]
    shots = {t: sum(p.get("shots", 0) for p in players if p.get("team") == t) for t in (0, 1)}
    return {t: {"teamSize": analysis.get("teamSize"), "oppShots": shots[1 - t], "conceded": score[1 - t]}
            for t in (0, 1)}


def player_metrics(player, context, priors):
    """Raw stats used for rating, or None if the player can't be rated."""
    adv = player.get("adv")
    if player.get("bot") or player.get("team") not in (0, 1) or not adv or adv["time"] < MIN_SECONDS:
        return None
    ctx = context[player["team"]]
    minutes = adv["time"] / 60
    per5 = 5 / minutes
    return {
        **adv,
        "goals5": player["goals"] * per5,
        "shots5": player["shots"] * per5,
        "assists5": player["assists"] * per5,
        "saves5": player["saves"] * per5,
        "shootingPct": (player["goals"] + SHOT_PRIOR * priors["shooting"]) / (player["shots"] + SHOT_PRIOR) * 100,
        "saveRate": (player["saves"] + SAVE_PRIOR * priors["saveRate"]) / (ctx["oppShots"] + SAVE_PRIOR) * 100,
        "conceded5": ctx["conceded"] * per5,
        "collectedPerMin": adv["boostCollected"] / minutes if adv["boostCollected"] is not None else None,
        "smallPadsPerMin": adv["smallPads"] / minutes if adv["smallPads"] is not None else None,
        "scorePerMin": player["score"] / minutes,
    }


def _score(key, value, higher_is_better, mode_bench):
    """0-100 score, or None when the stat doesn't apply in this mode (e.g. assists in 1v1)."""
    bench = mode_bench["metrics"].get(key)
    if bench is None:
        return None
    p_low, p_high = bench
    return _scale(value, p_low, p_high) if higher_is_better else _scale(value, p_high, p_low)


def rate_player(player, context, benchmarks=None):
    """Return {"attack": .., "defence": .., "boost": .., "speed": .., "overall": .., "breakdown": {...}} or None."""
    mode_bench = _mode_benchmarks(context[0]["teamSize"], benchmarks)
    metrics = player_metrics(player, context, mode_bench["priors"])
    if metrics is None:
        return None
    ratings, breakdown = {}, {}
    for cat, parts in CATEGORIES.items():
        if any(metrics.get(key) is None for key, *_ in parts):
            ratings[cat] = None  # missing data (e.g. no boost info in the replay)
            continue
        total = used = 0.0
        breakdown[cat] = []
        for key, label, weight, higher in parts:
            score = _score(key, metrics[key], higher, mode_bench)
            if score is None:
                continue  # weights of the remaining stats are scaled up
            total += score * weight
            used += weight
            breakdown[cat].append({"key": key, "label": label, "value": round(metrics[key], 2), "score": round(score)})
        ratings[cat] = round(total / used, 1) if used else None
    key, label, _, higher = IMPACT
    impact = _score(key, metrics[key], higher, mode_bench)
    if impact is not None:
        breakdown["impact"] = [{"key": key, "label": label, "value": round(metrics[key], 1), "score": round(impact)}]
    # Weighted average over the categories that could be rated
    available = [(s, w) for c, w in OVERALL_WEIGHTS.items()
                 if (s := impact if c == "impact" else ratings[c]) is not None]
    ratings["overall"] = round(sum(s * w for s, w in available) / sum(w for _, w in available), 1)
    ratings["breakdown"] = breakdown
    return ratings


def rate_match(analysis, benchmarks=None):
    """Add `ratings` to every player and pick the best player per category."""
    context = match_context(analysis)
    for p in analysis["players"]:
        p["ratings"] = rate_player(p, context, benchmarks)
    rated = [p for p in analysis["players"] if p["ratings"]]
    leaders = {}
    for cat in ("overall", *CATEGORIES):
        candidates = [p for p in rated if p["ratings"][cat] is not None]
        if candidates:
            best = max(candidates, key=lambda p: p["ratings"][cat])
            leaders[cat] = {"key": best["key"], "name": best["name"], "team": best["team"],
                            "rating": best["ratings"][cat]}
    analysis["leaders"] = leaders
    analysis["ratingVersion"] = model_version(benchmarks)
    return analysis


def _quantile(values, q):
    values = sorted(values)
    pos = (len(values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def calibrate(analyses):
    """Build benchmarks (10th/90th percentiles per mode) from stored match analyses."""
    by_mode = {}
    for a in analyses:
        context = match_context(a)
        for p in a["players"]:
            if player_metrics(p, context, {"shooting": 0, "saveRate": 0}) is not None:  # eligibility check
                by_mode.setdefault(a.get("teamSize") or 0, []).append((p, context))
    modes = {}
    for mode, rows in sorted(by_mode.items()):
        if len(rows) < MIN_CALIBRATION_ROWS or not mode:
            continue
        goals = sum(p["goals"] for p, _ in rows)
        shots = sum(p["shots"] for p, _ in rows)
        saves = sum(p["saves"] for p, _ in rows)
        opp_shots = sum(ctx[p["team"]]["oppShots"] for p, ctx in rows)
        priors = {"shooting": round(goals / shots, 4) if shots else 0.4,
                  "saveRate": round(saves / opp_shots, 4) if opp_shots else 0.2}
        metrics = [m for p, ctx in rows if (m := player_metrics(p, ctx, priors)) is not None]
        bench = {}
        for key in METRIC_KEYS:
            values = [m[key] for m in metrics if m.get(key) is not None]
            low, high = _quantile(values, LOW_PCT), _quantile(values, HIGH_PCT)
            if high == low:
                high = max(values)  # e.g. assists: most players have none
            # No spread at all means the stat doesn't apply in this mode (assists in 1v1)
            bench[key] = [round(low, 3), round(high, 3)] if high > low else None
        modes[str(mode)] = {"rows": len(rows), "priors": priors, "metrics": bench}
    if not modes:
        raise ValueError(f"Not enough data to calibrate (need {MIN_CALIBRATION_ROWS} rated player-matches per mode)")
    return {"generatedAt": datetime.now(UTC).isoformat(timespec="seconds"), "matches": len(analyses),
            "percentiles": [LOW_PCT, HIGH_PCT], "modes": modes}


def describe_model():
    """The model as data, so the UI can explain how ratings are calculated."""
    modes = BENCHMARKS["modes"]

    def stat(key, label, weight, higher):
        return {"key": key, "label": label, "weight": weight, "higherIsBetter": higher,
                "benchmarks": {m: modes[m]["metrics"][key] for m in modes}}

    return {
        "version": model_version(),
        "minSeconds": MIN_SECONDS,
        "overallWeights": OVERALL_WEIGHTS,
        "labels": CATEGORY_LABELS,
        "categories": {cat: [stat(*part) for part in parts] for cat, parts in CATEGORIES.items()},
        "impact": stat(*IMPACT),
        "modes": {m: {"rows": modes[m]["rows"], "priors": modes[m]["priors"]} for m in modes},
        "calibratedAt": BENCHMARKS.get("generatedAt"),
        "calibrationMatches": BENCHMARKS.get("matches"),
        "shotPrior": SHOT_PRIOR,
        "savePrior": SAVE_PRIOR,
        "leaderboardPriorMatches": LEADERBOARD_PRIOR_MATCHES,
    }
