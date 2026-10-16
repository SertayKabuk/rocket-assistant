"""Turn rrrocket JSON output into match stats.

`summarize(header_json)` works on header-only output (fast, scoreboard only).
`analyze(full_json)` walks the network frames for positioning, speed, boost and demos.
"""
import math
import re
from collections import defaultdict

ANALYZER_VERSION = 3

# Field geometry in Unreal units. Blue (team 0) defends -y, orange (team 1) defends +y.
FIELD_X = 4096
FIELD_Y = 5120
THIRD_Y = FIELD_Y / 3  # boundary of the middle third
GRID_NX, GRID_NY = 24, 30
GROUND_Z = 40  # resting car is ~17
HIGH_AIR_Z = 642  # crossbar height
SUPERSONIC = 2200
BOOST_SPEED = 1400
BOOST_MAX_RAW = 255
BIG_PAD_GAIN = 0.4  # gains above 40% can only come from a 100-boost pad

MAP_NAMES = {
    "stadium": "DFH Stadium", "trainstation": "Urban Central", "park": "Beckwith Park",
    "eurostadium": "Mannfield", "utopiastadium": "Utopia Coliseum", "wasteland": "Wasteland",
    "neotokyo": "Neo Tokyo", "cs": "Champions Field", "cs_day": "Champions Field (Day)",
    "beach": "Salty Shores", "farm": "Farmstead", "underwater": "AquaDome",
    "chn_stadium": "Forbidden Temple", "arc": "ARCtagon", "music": "Neon Fields",
    "throwbackstadium": "Throwback Stadium", "woods": "Deadeye Canyon", "street": "Sovereign Heights",
    "outlaw": "Deadeye Canyon", "ff_dusk": "Estadio Vida", "swoosh": "Champions Field (Nike FC)",
    "fni_stadium": "Futura Garden", "eurostadium_snownight": "Mannfield (Snowy)",
    "hoopsstadium": "Dunk House", "shattershot": "Core 707", "labs": "Rocket Labs",
    "haunted_trainstation": "Urban Central (Haunted)", "bb": "Champions Field (NFL)",
}


def map_display_name(map_name):
    if not map_name:
        return "Unknown"
    base = re.sub(r"_P$", "", map_name, flags=re.IGNORECASE)
    parts = base.split("_")
    for n in range(len(parts), 0, -1):
        key = "_".join(parts[:n]).lower()
        if key in MAP_NAMES:
            variant = " ".join(parts[n:])
            return MAP_NAMES[key] + (f" ({variant})" if variant else "")
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", base).replace("_", " ")


def _platform(stat):
    platform = stat.get("Platform", {})
    value = platform.get("value", "") if isinstance(platform, dict) else str(platform)
    return value.replace("OnlinePlatform_", "") or "Unknown"


def _player_key(stat):
    """Stable id for a player across replays: platform + account id, falling back to name."""
    fields = (stat.get("PlayerID") or {}).get("fields", {})
    epic = fields.get("EpicAccountId")
    online = str(stat.get("OnlineID") or "0")
    if online != "0":
        return f"{_platform(stat).lower()}:{online}"
    if epic:
        return f"epic:{epic}"
    return f"name:{stat.get('Name', '')}"


def summarize(replay):
    """Scoreboard-level summary from header properties."""
    props = replay.get("properties", {})
    players = []
    for s in props.get("PlayerStats", []):
        players.append({
            "name": s.get("Name", "?"),
            "key": _player_key(s),
            "team": s.get("Team", 0),
            "platform": _platform(s),
            "bot": bool(s.get("bBot")),
            "score": s.get("Score", 0),
            "goals": s.get("Goals", 0),
            "assists": s.get("Assists", 0),
            "saves": s.get("Saves", 0),
            "shots": s.get("Shots", 0),
        })
    score = [props.get("Team0Score", 0) or 0, props.get("Team1Score", 0) or 0]
    return {
        "replayId": props.get("Id", ""),
        "matchGuid": props.get("MatchGUID", ""),
        "name": props.get("ReplayName") or "",
        "date": props.get("Date", ""),
        "map": map_display_name(props.get("MapName")),
        "matchType": props.get("MatchType", ""),
        "teamSize": props.get("TeamSize", 0),
        "duration": props.get("TotalSecondsPlayed"),
        "score": score,
        "recorder": props.get("PlayerName"),
        "players": players,
        "goals": [{"player": g.get("PlayerName"), "team": g.get("PlayerTeam"), "frame": g.get("frame")}
                  for g in props.get("Goals", [])],
    }


class _PlayerAcc:
    def __init__(self):
        self.team = None
        self.time = 0.0
        self.speed_sum = 0.0
        self.speed_bands = [0.0, 0.0, 0.0]  # slow, boost speed, supersonic
        self.height = [0.0, 0.0, 0.0]  # ground, low air, high air
        self.thirds = [0.0, 0.0, 0.0]  # defensive, neutral, offensive (own perspective)
        self.behind_ball = 0.0
        self.boost_time = 0.0
        self.boost_sum = 0.0
        self.boost_empty = 0.0
        self.boost_full = 0.0
        self.collected = 0.0
        self.used = 0.0
        self.big_pads = 0
        self.small_pads = 0
        self.demos = 0
        self.demoed = 0
        self.heat = [0.0] * (GRID_NX * GRID_NY)
        self.boost_series = {}  # second -> boost %


def _grid_index(x, y):
    gx = min(GRID_NX - 1, max(0, int((x + FIELD_X) / (2 * FIELD_X) * GRID_NX)))
    gy = min(GRID_NY - 1, max(0, int((y + FIELD_Y) / (2 * FIELD_Y) * GRID_NY)))
    return gy * GRID_NX + gx


def _actor_ref(value):
    if isinstance(value, dict):
        return value.get("actor") if value.get("active", True) else None
    return value


def analyze(replay, summary):
    """Full analysis using network frames. `summary` is the output of summarize()."""
    frames = replay["network_frames"]["frames"]
    objects = replay["objects"]
    names = replay.get("names", [])

    actor_type = {}  # actor id -> archetype/class name
    car_pri = {}  # car actor -> PRI actor
    comp_car = {}  # car component actor -> car actor
    car_boost = {}  # car actor -> boost component actor
    ball_id = None
    car_team = {}  # car actor -> team from paint
    pri_name, pri_team_actor = {}, {}
    team_actor_num = {}  # team actor -> 0/1
    rb = {}  # actor -> (location, velocity)
    boost_amount = {}  # boost component actor -> raw 0..255
    seen_demos = set()
    acc = defaultdict(_PlayerAcc)  # keyed by PRI actor
    ball_heat = [0.0] * (GRID_NX * GRID_NY)
    ball_blue_half = 0.0
    ball_time = 0.0
    live = False
    seconds_remaining = None
    overtime = False
    live_clock = 0.0  # seconds of active play so far
    frame_clock = []  # per frame: (live_clock, seconds_remaining, overtime)

    def pri_of_car(car):
        return car_pri.get(car)

    def team_of_pri(pri):
        t = team_actor_num.get(pri_team_actor.get(pri))
        return t

    for frame in frames:
        for actor in frame["deleted_actors"]:
            for d in (actor_type, car_pri, comp_car, car_boost, rb, boost_amount, car_team):
                d.pop(actor, None)
            seen_demos = {k for k in seen_demos if k[1] != actor}
        for new in frame["new_actors"]:
            name = objects[new["object_id"]]
            actor_type[new["actor_id"]] = name
            if name == "Archetypes.Ball.Ball_Default":
                ball_id = new["actor_id"]
            if name.endswith("Teams.Team0"):
                team_actor_num[new["actor_id"]] = 0
            elif name.endswith("Teams.Team1"):
                team_actor_num[new["actor_id"]] = 1

        for upd in frame["updated_actors"]:
            aid = upd["actor_id"]
            prop = objects[upd["object_id"]]
            attr = upd["attribute"]
            if prop == "TAGame.RBActor_TA:ReplicatedRBState":
                body = attr["RigidBody"]
                vel = body.get("linear_velocity")
                if vel is None and not body.get("sleeping"):
                    vel = rb.get(aid, (None, None))[1]
                rb[aid] = (body["location"], vel)
            elif prop == "Engine.Pawn:PlayerReplicationInfo":
                car_pri[aid] = _actor_ref(attr.get("ActiveActor"))
            elif prop == "TAGame.CarComponent_TA:Vehicle":
                comp_car[aid] = _actor_ref(attr.get("ActiveActor"))
                if "Boost" in actor_type.get(aid, ""):
                    car_boost[comp_car[aid]] = aid
            elif prop == "TAGame.Car_TA:TeamPaint":
                car_team[aid] = attr["TeamPaint"]["team"]
            elif prop == "Engine.PlayerReplicationInfo:PlayerName":
                pri_name[aid] = attr.get("String")
            elif prop == "Engine.PlayerReplicationInfo:Team":
                pri_team_actor[aid] = _actor_ref(attr.get("ActiveActor"))
            elif prop in ("TAGame.CarComponent_Boost_TA:ReplicatedBoost",
                          "TAGame.CarComponent_Boost_TA:ReplicatedBoostAmount"):  # older replays use the latter
                amount = attr["ReplicatedBoost"]["boost_amount"] if "ReplicatedBoost" in attr else attr.get("Byte", 0)
                prev = boost_amount.get(aid)
                boost_amount[aid] = amount
                pri = pri_of_car(comp_car.get(aid))
                if prev is None or pri is None:
                    continue
                delta = (amount - prev) / BOOST_MAX_RAW
                if delta > 0:
                    acc[pri].collected += delta * 100
                    if delta > BIG_PAD_GAIN or (amount == BOOST_MAX_RAW and delta > 0.15):
                        acc[pri].big_pads += 1
                    else:
                        acc[pri].small_pads += 1
                elif delta < 0:
                    acc[pri].used += -delta * 100
            elif prop == "TAGame.GameEvent_TA:ReplicatedStateName":
                idx = attr.get("Int")
                live = 0 <= idx < len(names) and names[idx] == "Active"
            elif prop == "TAGame.GameEvent_Soccar_TA:SecondsRemaining":
                seconds_remaining = attr.get("Int")
            elif prop == "TAGame.GameEvent_Soccar_TA:bOverTime":
                overtime = bool(attr.get("Boolean"))
            elif prop.startswith("TAGame.Car_TA:ReplicatedDemolish"):
                demo = next(iter(attr.values()))
                if not isinstance(demo, dict):
                    continue
                attacker_car = _actor_ref(demo.get("attacker"))
                victim_car = _actor_ref(demo.get("victim"))
                key = (attacker_car, victim_car)
                if victim_car is None or key in seen_demos:
                    continue
                seen_demos.add(key)
                attacker = pri_of_car(attacker_car) or _actor_ref(demo.get("attacker_pri"))
                victim = pri_of_car(victim_car)
                if attacker is not None:
                    acc[attacker].demos += 1
                if victim is not None:
                    acc[victim].demoed += 1

        dt = frame["delta"]
        if live and dt > 0:
            live_clock += dt
            ball = rb.get(ball_id)
            if ball:
                bloc = ball[0]
                ball_heat[_grid_index(bloc["x"], bloc["y"])] += dt
                ball_time += dt
                if bloc["y"] < 0:
                    ball_blue_half += dt
            second = int(live_clock)
            for car, pri in car_pri.items():
                if car not in rb or pri is None:
                    continue
                loc, vel = rb[car]
                team = team_of_pri(pri)
                if team is None:
                    team = car_team.get(car, 0)
                a = acc[pri]
                a.team = team
                a.time += dt
                speed = math.sqrt(vel["x"] ** 2 + vel["y"] ** 2 + vel["z"] ** 2) if vel else 0.0
                a.speed_sum += speed * dt
                a.speed_bands[2 if speed >= SUPERSONIC else 1 if speed >= BOOST_SPEED else 0] += dt
                a.height[0 if loc["z"] < GROUND_Z else 2 if loc["z"] > HIGH_AIR_Z else 1] += dt
                own_y = loc["y"] if team == 0 else -loc["y"]  # negative = own half
                a.thirds[0 if own_y < -THIRD_Y else 2 if own_y > THIRD_Y else 1] += dt
                if ball:
                    ball_own_y = ball[0]["y"] if team == 0 else -ball[0]["y"]
                    if own_y < ball_own_y:
                        a.behind_ball += dt
                a.heat[_grid_index(loc["x"], loc["y"])] += dt
                comp = car_boost.get(car)
                if comp in boost_amount:
                    pct = boost_amount[comp] / BOOST_MAX_RAW * 100
                    a.boost_time += dt
                    a.boost_sum += pct * dt
                    if pct < 1:
                        a.boost_empty += dt
                    elif pct > 99:
                        a.boost_full += dt
                    a.boost_series.setdefault(second, round(pct))
        frame_clock.append((round(live_clock, 2), seconds_remaining, overtime))

    # Merge accumulators by player name (a player can get a new PRI after reconnecting)
    by_name = {}
    for pri, a in acc.items():
        name = pri_name.get(pri)
        if name is None:
            continue
        if name in by_name:
            _merge(by_name[name], a)
        else:
            by_name[name] = a

    players = []
    header_players = {p["name"]: p for p in summary["players"]}
    all_names = list(header_players) + [n for n in by_name if n not in header_players]
    for name in all_names:
        base = dict(header_players.get(name) or {
            "name": name, "key": f"name:{name}", "team": by_name[name].team or 0,
            "platform": "", "bot": False, "score": 0, "goals": 0, "assists": 0, "saves": 0, "shots": 0,
        })
        a = by_name.get(name)
        if a and a.time > 0:
            t = a.time
            bt = a.boost_time or 1
            has_boost = a.boost_time > 0
            minutes = t / 60
            base["adv"] = {
                "time": round(t, 1),
                "avgSpeed": round(a.speed_sum / t),
                "supersonicPct": _pct(a.speed_bands[2], t),
                "boostSpeedPct": _pct(a.speed_bands[1], t),
                "slowPct": _pct(a.speed_bands[0], t),
                "groundPct": _pct(a.height[0], t),
                "lowAirPct": _pct(a.height[1], t),
                "highAirPct": _pct(a.height[2], t),
                "defThirdPct": _pct(a.thirds[0], t),
                "midThirdPct": _pct(a.thirds[1], t),
                "offThirdPct": _pct(a.thirds[2], t),
                "behindBallPct": _pct(a.behind_ball, t),
                # None when the replay has no boost data for this player
                "avgBoost": round(a.boost_sum / bt, 1) if has_boost else None,
                "emptyBoostPct": _pct(a.boost_empty, bt) if has_boost else None,
                "fullBoostPct": _pct(a.boost_full, bt) if has_boost else None,
                "boostCollected": round(a.collected) if has_boost else None,
                "boostUsed": round(a.used) if has_boost else None,
                "boostPerMin": round(a.used / minutes) if has_boost and minutes else None,
                "bigPads": a.big_pads if has_boost else None,
                "smallPads": a.small_pads if has_boost else None,
                "demos": a.demos,
                "demoed": a.demoed,
            }
            base["heatmap"] = _shares(a.heat)
            if a.boost_series:
                last = max(a.boost_series)
                base["boostSeries"] = [a.boost_series.get(s) for s in range(last + 1)]
        players.append(base)

    goals = []
    for g in summary["goals"]:
        f = g.get("frame")
        clock = frame_clock[f] if f is not None and f < len(frame_clock) else (None, None, False)
        goals.append({**g, "time": clock[0], "secondsRemaining": clock[1], "overtime": clock[2]})

    return {
        **summary,
        "analyzerVersion": ANALYZER_VERSION,
        "liveSeconds": round(live_clock, 1),
        "players": players,
        "goals": goals,
        "ball": {
            "heatmap": _shares(ball_heat),
            "blueHalfPct": _pct(ball_blue_half, ball_time),
        },
        "grid": {"nx": GRID_NX, "ny": GRID_NY, "fieldX": FIELD_X, "fieldY": FIELD_Y},
    }


def _merge(into, other):
    for field in ("time", "speed_sum", "behind_ball", "boost_time", "boost_sum", "boost_empty", "boost_full",
                  "collected", "used", "big_pads", "small_pads", "demos", "demoed"):
        setattr(into, field, getattr(into, field) + getattr(other, field))
    for field in ("speed_bands", "height", "thirds", "heat"):
        setattr(into, field, [x + y for x, y in zip(getattr(into, field), getattr(other, field), strict=True)])
    for s, v in other.boost_series.items():
        into.boost_series.setdefault(s, v)


def _shares(cells):
    """Fraction of total time spent in each grid cell."""
    total = sum(cells) or 1
    return [round(v / total, 5) for v in cells]


def _pct(part, whole):
    return round(part / whole * 100, 1) if whole else 0.0
