from conftest import make_adv, make_analysis, make_player

from rocket_assistant.ratings import CATEGORIES, MIN_SECONDS, OVERALL_WEIGHTS, _scale, rate_player


def test_scale_clamps_and_supports_lower_is_better():
    assert _scale(1.5, 0, 3) == 50
    assert _scale(-1, 0, 3) == 0
    assert _scale(10, 0, 3) == 100
    # low > high: lower values are better
    assert _scale(4, 20, 4) == 100
    assert _scale(20, 20, 4) == 0
    assert _scale(12, 20, 4) == 50


def test_weights_sum_to_one():
    for parts in CATEGORIES.values():
        assert abs(sum(p[4] for p in parts) - 1) < 1e-9
    assert abs(sum(OVERALL_WEIGHTS.values()) - 1) < 1e-9


def test_rate_player_returns_all_categories_in_range():
    ratings = rate_player(make_player("steam:1", "A", 0, goals=2, saves=2, shots=4))
    for cat in ("attack", "defence", "boost", "speed", "overall"):
        assert 0 <= ratings[cat] <= 100
    assert {"attack", "defence", "boost", "speed", "impact"} <= ratings["breakdown"].keys()


def test_counting_stats_are_normalised_per_five_minutes():
    full = rate_player(make_player("a", "A", 0, goals=2, adv=make_adv(time=300)))
    half = rate_player(make_player("b", "B", 0, goals=1, adv=make_adv(time=150)))
    goals = lambda r: next(p for p in r["breakdown"]["attack"] if p["key"] == "goals5")  # noqa: E731
    assert goals(full)["value"] == goals(half)["value"] == 2


def test_bots_and_short_appearances_are_not_rated():
    assert rate_player(make_player("bot", "Bot", 0, bot=True)) is None
    assert rate_player(make_player("x", "X", 0, adv=make_adv(time=MIN_SECONDS - 1))) is None
    assert rate_player({**make_player("y", "Y", 0), "adv": None}) is None


def test_missing_boost_data_skips_boost_and_reweights_overall():
    no_boost = make_adv(avgBoost=None, emptyBoostPct=None, fullBoostPct=None, boostCollected=None,
                        boostUsed=None, boostPerMin=None, bigPads=None, smallPads=None)
    ratings = rate_player(make_player("a", "A", 0, adv=no_boost))
    assert ratings["boost"] is None
    assert "boost" not in ratings["breakdown"]
    assert 0 <= ratings["overall"] <= 100


def test_rate_match_picks_best_player():
    strong = make_player("steam:1", "Strong", 0, goals=3, saves=3, shots=5, score=700)
    weak = make_player("steam:2", "Weak", 1, goals=0, saves=0, shots=0, score=50)
    analysis = make_analysis([strong, weak])
    assert analysis["leaders"]["overall"]["key"] == "steam:1"
    assert analysis["leaders"]["attack"]["name"] == "Strong"
