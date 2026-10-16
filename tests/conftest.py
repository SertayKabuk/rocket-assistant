import pytest
from fastapi.testclient import TestClient

from rocket_assistant import db
from rocket_assistant.analyze import GRID_NX, GRID_NY
from rocket_assistant.ratings import rate_match


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init()
    return tmp_path


@pytest.fixture
def client(temp_db):
    from rocket_assistant.app import app

    return TestClient(app)


def make_adv(**overrides):
    adv = {
        "time": 300.0, "avgSpeed": 1350, "supersonicPct": 8.0, "boostSpeedPct": 37.0, "slowPct": 55.0,
        "groundPct": 70.0, "lowAirPct": 26.0, "highAirPct": 4.0,
        "defThirdPct": 45.0, "midThirdPct": 35.0, "offThirdPct": 20.0, "behindBallPct": 72.0,
        "avgBoost": 50.0, "emptyBoostPct": 10.0, "fullBoostPct": 15.0, "boostCollected": 1500, "boostUsed": 1450,
        "boostPerMin": 290, "bigPads": 12, "smallPads": 40, "demos": 1, "demoed": 0,
    }
    return {**adv, **overrides}


def make_player(key, name, team, goals=1, saves=1, shots=2, assists=0, score=300, bot=False, adv=None):
    return {
        "key": key, "name": name, "team": team, "platform": "Steam", "bot": bot,
        "score": score, "goals": goals, "assists": assists, "saves": saves, "shots": shots,
        "adv": adv if adv is not None else make_adv(),
        "heatmap": [1 / (GRID_NX * GRID_NY)] * (GRID_NX * GRID_NY),
    }


def make_analysis(players, score=(1, 0), team_size=2, date="2026-03-23 23-05-13"):
    return rate_match({
        "replayId": "R", "matchGuid": "G", "name": "", "date": date, "map": "DFH Stadium",
        "matchType": "Online", "teamSize": team_size, "duration": 300.0, "liveSeconds": 300.0,
        "score": list(score), "recorder": players[0]["name"], "players": players, "goals": [],
        "ball": {"heatmap": [0] * (GRID_NX * GRID_NY), "blueHalfPct": 50.0},
        "grid": {"nx": GRID_NX, "ny": GRID_NY, "fieldX": 4096, "fieldY": 5120},
    })
