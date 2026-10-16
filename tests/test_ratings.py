import pytest
from conftest import make_adv, make_analysis, make_player

from rocket_assistant import db, ratings
from rocket_assistant.ratings import (
    CATEGORIES,
    MIN_CALIBRATION_ROWS,
    MIN_SECONDS,
    OVERALL_WEIGHTS,
    _scale,
    calibrate,
    match_context,
    model_version,
    rate_player,
)


def rate(player, opponent=None, score=(1, 0), team_size=2, benchmarks=None):
    """Rate `player` (team 0) in a match against `opponent` (team 1)."""
    opponent = opponent or make_player("opp", "Opp", 1)
    context = match_context({"players": [player, opponent], "score": list(score), "teamSize": team_size})
    return rate_player(player, context, benchmarks)


def test_scale_clamps_and_supports_lower_is_better():
    assert _scale(1.5, 0, 3) == 50
    assert _scale(-1, 0, 3) == 0
    assert _scale(10, 0, 3) == 100
    # low > high: lower values are better
    assert _scale(4, 20, 4) == 100
    assert _scale(20, 20, 4) == 0
    assert _scale(12, 20, 4) == 50
    assert _scale(5, 5, 5) == 50  # no spread: everyone is average


def test_weights_sum_to_one():
    for parts in CATEGORIES.values():
        assert abs(sum(p[2] for p in parts) - 1) < 1e-9
    assert abs(sum(OVERALL_WEIGHTS.values()) - 1) < 1e-9


def test_packaged_benchmarks_cover_every_stat():
    for bench in ratings.load_benchmarks()["modes"].values():
        assert set(bench["metrics"]) == set(ratings.METRIC_KEYS)
        assert 0 < bench["priors"]["shooting"] < 1


def test_rate_player_returns_all_categories_in_range():
    result = rate(make_player("steam:1", "A", 0, goals=2, saves=2, shots=4))
    for cat in ("attack", "defence", "boost", "speed", "overall"):
        assert 0 <= result[cat] <= 100
    assert {"attack", "defence", "boost", "speed", "impact"} <= result["breakdown"].keys()


def test_counting_stats_are_normalised_per_five_minutes():
    full = rate(make_player("a", "A", 0, goals=2, adv=make_adv(time=300)))
    half = rate(make_player("b", "B", 0, goals=1, adv=make_adv(time=150)))
    goals = lambda r: next(p for p in r["breakdown"]["attack"] if p["key"] == "goals5")  # noqa: E731
    assert goals(full)["value"] == goals(half)["value"] == 2


def test_shooting_and_save_rate_are_shrunk_toward_the_mode_average():
    context = match_context({"players": [], "score": [0, 0], "teamSize": 2})
    context[0]["oppShots"] = 1
    priors = {"shooting": 0.5, "saveRate": 0.2}
    lucky = ratings.player_metrics(make_player("a", "A", 0, goals=1, shots=1, saves=0), context, priors)
    assert lucky["shootingPct"] == pytest.approx((1 + 4 * 0.5) / (1 + 4) * 100)  # 60%, not 100%
    assert lucky["saveRate"] == pytest.approx((0 + 4 * 0.2) / (1 + 4) * 100)  # 16%, not 0%


def test_conceding_more_lowers_defence():
    player = make_player("a", "A", 0)
    assert rate(player, score=(0, 1))["defence"] > rate(player, score=(0, 6))["defence"]


def test_stats_without_benchmark_are_skipped():
    # 1v1 benchmarks have no assists, so assists don't change the attack rating there
    no_assists = rate(make_player("a", "A", 0, assists=0), team_size=1)
    assists = rate(make_player("a", "A", 0, assists=3), team_size=1)
    assert no_assists["attack"] == assists["attack"]
    assert "assists5" not in {p["key"] for p in assists["breakdown"]["attack"]}


def test_bots_and_short_appearances_are_not_rated():
    assert rate(make_player("bot", "Bot", 0, bot=True)) is None
    assert rate(make_player("x", "X", 0, adv=make_adv(time=MIN_SECONDS - 1))) is None
    assert rate({**make_player("y", "Y", 0), "adv": None}) is None
    assert rate(make_player("z", "Z", -1)) is None


def test_missing_boost_data_skips_boost_and_reweights_overall():
    no_boost = make_adv(avgBoost=None, emptyBoostPct=None, fullBoostPct=None, boostCollected=None,
                        boostUsed=None, boostPerMin=None, bigPads=None, smallPads=None)
    result = rate(make_player("a", "A", 0, adv=no_boost))
    assert result["boost"] is None
    assert "boost" not in result["breakdown"]
    assert 0 <= result["overall"] <= 100


def test_rate_match_picks_best_player_and_stamps_version():
    strong = make_player("steam:1", "Strong", 0, goals=3, saves=3, shots=5, score=700)
    weak = make_player("steam:2", "Weak", 1, goals=0, saves=0, shots=0, score=50)
    analysis = make_analysis([strong, weak], score=(3, 0))
    assert analysis["leaders"]["overall"]["key"] == "steam:1"
    assert analysis["leaders"]["attack"]["name"] == "Strong"
    assert analysis["ratingVersion"] == model_version()


def test_calibrate_builds_percentile_benchmarks_per_mode():
    analyses = []
    for i in range(MIN_CALIBRATION_ROWS // 2 + 1):
        players = [make_player(f"a{i}", "A", 0, goals=i % 5, shots=i % 5 + 2, assists=i % 3, score=100 + 10 * i,
                               adv=make_adv(avgSpeed=1200 + i)),
                   make_player(f"b{i}", "B", 1, goals=0, shots=1, saves=i % 4, score=200)]
        analyses.append({"players": players, "score": [i % 5, 0], "teamSize": 2})
    bench = calibrate(analyses)
    assert set(bench["modes"]) == {"2"}
    mode = bench["modes"]["2"]
    assert mode["rows"] == 2 * len(analyses)
    low, high = mode["metrics"]["avgSpeed"]
    assert 1200 <= low < high <= 1350  # team 1 always drives at 1350
    # Rating with the new benchmarks works, and changes the model version
    result = rate(analyses[0]["players"][0], analyses[0]["players"][1], benchmarks=bench)
    assert 0 <= result["overall"] <= 100
    assert model_version(bench) != model_version()


def test_calibrate_needs_enough_data():
    with pytest.raises(ValueError):
        calibrate([{"players": [make_player("a", "A", 0), make_player("b", "B", 1)], "score": [1, 0], "teamSize": 2}])


def test_leaderboard_average_is_shrunk_toward_everyone(temp_db):
    # One player with a single great match, one with many average matches
    for i in range(12):
        steady = make_player("steam:steady", "Steady", 0, goals=1, shots=3, score=350)
        other = make_player(f"steam:o{i}", f"O{i}", 1, goals=1, shots=3, score=300)
        db.save_match(f"m{i}", make_analysis([steady, other]), "x.replay", "2026-01-01", 1)
    star = make_player("steam:star", "Star", 0, goals=5, shots=6, saves=3, score=900)
    loser = make_player("steam:x", "X", 1, goals=0, shots=0, score=50)
    db.save_match("star", make_analysis([star, loser], score=(5, 0)), "x.replay", "2026-01-01", 1)
    board = {p["key"]: p for p in db.leaderboard(min_matches=1)}
    star_row = board["steam:star"]
    assert star_row["overall"] < star_row["overallRaw"]  # pulled down toward the mean
    steady_row = board["steam:steady"]
    assert abs(steady_row["overall"] - steady_row["overallRaw"]) < abs(star_row["overall"] - star_row["overallRaw"])
