from rocket_assistant.analyze import _player_key, map_display_name, summarize


def test_map_display_name():
    assert map_display_name("TrainStation_Night_P") == "Urban Central (Night)"
    assert map_display_name("Stadium_P") == "DFH Stadium"
    assert map_display_name("SomeNewMap_P") == "Some New Map"
    assert map_display_name(None) == "Unknown"


def test_player_key_prefers_platform_id_then_epic_then_name():
    steam = {"Name": "A", "OnlineID": "765", "Platform": {"value": "OnlinePlatform_Steam"}}
    epic = {"Name": "B", "OnlineID": "0", "Platform": {"value": "OnlinePlatform_Epic"},
            "PlayerID": {"fields": {"EpicAccountId": "abc"}}}
    unknown = {"Name": "C", "OnlineID": "0"}
    assert _player_key(steam) == "steam:765"
    assert _player_key(epic) == "epic:abc"
    assert _player_key(unknown) == "name:C"


def test_summarize_reads_header():
    header = {"properties": {
        "Id": "RID", "MatchGUID": "GUID", "Date": "2026-03-23 23-05-13", "MapName": "Stadium_P",
        "MatchType": "Online", "TeamSize": 2, "Team0Score": 3, "PlayerName": "A",
        "PlayerStats": [
            {"Name": "A", "OnlineID": "1", "Platform": {"value": "OnlinePlatform_Steam"}, "Team": 0,
             "Score": 500, "Goals": 3, "Assists": 0, "Saves": 1, "Shots": 4, "bBot": False},
        ],
        "Goals": [{"frame": 10, "PlayerName": "A", "PlayerTeam": 0}],
    }}
    s = summarize(header)
    assert s["matchGuid"] == "GUID"
    assert s["score"] == [3, 0]  # missing Team1Score defaults to 0
    assert s["players"][0]["key"] == "steam:1"
    assert s["players"][0]["platform"] == "Steam"
    assert s["goals"] == [{"player": "A", "team": 0, "frame": 10}]
