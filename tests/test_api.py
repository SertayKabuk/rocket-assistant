from conftest import make_analysis, make_player

from rocket_assistant import db

ME, FRIEND, OTHER = "steam:1", "steam:2", "steam:3"


def seed():
    # Match 1 (2v2): me + friend vs other
    db.save_match("m1", make_analysis([
        make_player(ME, "Me", 0, goals=2), make_player(FRIEND, "Friend", 0), make_player(OTHER, "Other", 1),
    ], score=(2, 0), team_size=2, date="2026-03-01 20-00-00"), "a.replay", "2026-03-01T20:00:00", 3)
    # Match 2 (3v3): me vs friend
    db.save_match("m2", make_analysis([
        make_player(ME, "Me", 0), make_player(FRIEND, "Friend", 1),
    ], score=(0, 1), team_size=3, date="2020-01-01 20-00-00"), "b.replay", "2020-01-01T20:00:00", 3)


def keys(resp):
    return {p["key"]: p for p in resp.json()["players"]}


def test_leaderboard_filters(client):
    seed()
    all_players = keys(client.get("/api/players"))
    assert set(all_players) == {ME, FRIEND, OTHER}
    assert all_players[ME]["matches"] == 2

    picked = keys(client.get("/api/players", params={"player": [ME, FRIEND]}))
    assert set(picked) == {ME, FRIEND}

    together = keys(client.get("/api/players", params={"player": [ME, FRIEND], "together": "true"}))
    assert together[ME]["matches"] == 1  # only m1, where they were teammates

    assert set(keys(client.get("/api/players", params={"mode": 3}))) == {ME, FRIEND}
    assert keys(client.get("/api/players", params={"days": 365 * 3}))[ME]["matches"] == 1
    assert set(keys(client.get("/api/players", params={"min_matches": 2}))) == {ME, FRIEND}


def test_match_and_profile_endpoints(client):
    seed()
    matches = client.get("/api/matches").json()
    assert matches["total"] == 2
    assert client.get("/api/matches/m1").json()["map"] == "DFH Stadium"
    assert client.get("/api/matches/missing").status_code == 404

    profile = client.get(f"/api/players/{ME}").json()
    assert profile["name"] == "Me"
    assert profile["matches"] == 2
    assert profile["wins"] == 1
    assert len(profile["heatmap"]) == 24 * 30
    assert client.get("/api/players/steam:404").status_code == 404


def test_upload_rejects_non_replays(client):
    resp = client.post("/api/replays", files=[("files", ("notes.txt", b"hello", "text/plain"))])
    assert resp.json()["results"][0]["status"] == "error"


def test_frontend_is_served(client):
    assert "Rocket Assistant" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
