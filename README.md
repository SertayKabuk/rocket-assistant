# Rocket Assistant

Web app for Rocket League replays. Upload `.replay` files and every player in every match is rated 0–100 on
**attack, defence, boost and speed**, with an overall rating that picks each match's best player. Ratings are
combined across matches into a leaderboard and per-player profiles (heatmaps, trends, strengths and weaknesses).

## Run

```sh
uv run rocket-assistant              # web app on http://127.0.0.1:8765 (opens a browser)
uv run rocket-assistant import       # bulk-import your local Demos folder
uv run rocket-assistant import PATH  # ...or any folder of .replay files
```

Rocket League saves replays to `Documents\My Games\Rocket League\TAGame\Demos` when you click *Save Replay*.

Replays are parsed with [rrrocket](https://github.com/nickbabcock/rrrocket), which is downloaded to `tools/` on
first use (or set `RRROCKET=/path/to/rrrocket`).

## Docker

```sh
docker compose up -d --build   # http://localhost:8765, data kept in the "rocket-data" volume
```

Or without compose:

```sh
docker build -t rocket-assistant .
docker run -d -p 8765:8765 -v rocket-data:/data rocket-assistant
```

The image works on **amd64 and arm64** and picks the rrrocket build for the target architecture:

- **amd64:** downloads upstream's prebuilt Linux binary at build time and checks its SHA-256.
- **arm64:** upstream publishes no Linux arm64 binary (and rrrocket isn't on crates.io), so the Dockerfile
  compiles the pinned release commit from source in a Rust stage. This takes a few minutes the first time.

Either way the container needs no internet access when it runs. To move to a new rrrocket release, update
`RRROCKET_VERSION`, `RRROCKET_SHA256` (amd64 tarball) and `RRROCKET_COMMIT` (the release tag's commit) in the
`Dockerfile`, plus `RRROCKET_VERSION` in `ingest.py` for local runs. The app runs as a non-root user and keeps its
SQLite database and uploaded replays in `/data`.

## Development

```sh
uv sync                 # includes dev tools
uv run pytest           # tests
uv run ruff check       # lint
```

## CI/CD

`.github/workflows/ci.yml` runs on pushes to `main`, version tags (`v1.2.3`) and pull requests:

1. **Lint and test:** ruff, pytest and a syntax check of the frontend JavaScript.
2. **Image:** builds the Docker image natively on an amd64 runner and an arm64 runner (`ubuntu-24.04-arm`), then
   smoke-tests each one: starts the container, calls the API and checks rrrocket runs on the right architecture.
3. **Publish** (not on pull requests): pushes a multi-arch image to GitHub Container Registry as
   `ghcr.io/<owner>/<repo>`, tagged with the branch name, the commit SHA and `latest` on `main`, and with the
   version (`1.2.3`, `1.2`) on version tags.

The workflow only needs the built-in `GITHUB_TOKEN`. Free arm64 runners are available for public repositories;
for a private repository, check that your plan includes them, or change the arm64 runner to `ubuntu-24.04` and
add `docker/setup-qemu-action` (much slower, because rrrocket compiles under emulation).

## How it works

| Module | Role |
|---|---|
| `analyze.py` | Walks the replay's network frames: positions, speed, boost, demos, heatmaps |
| `ratings.py` | Turns stats into 0–100 ratings using fixed benchmarks (also shown at `#/ratings`) |
| `ingest.py` | Parses uploads, de-duplicates by match GUID, stores the replay file |
| `db.py` | SQLite (`data/rocket.db`): matches + one row per player per match |
| `app.py` | FastAPI JSON API and the static frontend in `static/` |

Players are identified by platform account id, so the same person is merged across everyone's uploads.
When the analyzer or rating model changes (`ANALYZER_VERSION` / `RATING_VERSION`), stored matches are
re-processed on the next start.

## Ratings

Each player gets a separate rating for every match. Three steps:

1. **Measure stats** from the replay (`analyze.py`).
2. **Score each stat 0–100** against fixed benchmarks.
3. **Combine the scores** into each category, and the categories into Overall, using weights (`ratings.py`).

### 1. Measuring stats from the replay

Replays store each car's position, speed and boost about 30 times a second. Only time when the ball is in
play counts: kickoff countdowns and goal celebrations are skipped.

- **Goals, shots, saves, assists, score:** taken straight from the game's own scoreboard in the replay.
- **Field thirds:** the field is split into defensive, middle and attacking thirds, flipped depending on which
  goal the player defends.
- **Behind the ball:** the share of time a player is between the ball and their own goal.
- **Speed bands:** slow (under 1400 uu/s), boost speed (1400–2200), supersonic (2200+).
- **Height bands:** ground, low air (below the crossbar, which includes driving on walls), high air (above the
  crossbar).
- **Boost:** every rise in a player's boost counts as boost collected. A gain of more than 40 is counted as a
  big pad, anything smaller as a small pad.

Goals, shots, assists and saves are converted to **per 5 minutes played**, so short games and overtime compare
fairly.

### 2. Scoring each stat 0–100

Each stat is placed on a straight line between a "low" and a "high" benchmark and capped at 0 and 100:

```
score = (value − low) / (high − low) × 100
```

For example, saves per 5 minutes uses low 0 and high 3, so 1.5 saves scores 50 and 3 or more scores 100. Some
stats are better when lower, like time at 0 boost; for those, low and high are swapped.

### 3. Category weights and benchmarks

**Attack**

| Stat | Weight | Scores 0 at | Scores 100 at |
|---|---|---|---|
| Goals / 5 min | 35% | 0 | 2 |
| Shots / 5 min | 25% | 0 | 4 |
| Assists / 5 min | 15% | 0 | 1.5 |
| Time in attacking third | 15% | 12% | 30% |
| Shooting % (goals ÷ shots) | 10% | 0% | 50% |

**Defence**

| Stat | Weight | Scores 0 at | Scores 100 at |
|---|---|---|---|
| Saves / 5 min | 50% | 0 | 3 |
| Time behind the ball | 30% | 60% | 85% |
| Time in defensive third | 20% | 35% | 55% |

**Boost**

| Stat | Weight | Scores 0 at | Scores 100 at |
|---|---|---|---|
| Time at 0 boost (lower is better) | 30% | 20% | 4% |
| Boost collected / min | 30% | 200 | 450 |
| Small pads / min | 25% | 4 | 12 |
| Time at 100 boost, i.e. boost sitting unused (lower is better) | 15% | 30% | 5% |

**Speed**

| Stat | Weight | Scores 0 at | Scores 100 at |
|---|---|---|---|
| Average speed | 40% | 1150 uu/s | 1550 uu/s |
| Time supersonic | 30% | 2% | 14% |
| Time at slow speed (lower is better) | 15% | 70% | 40% |
| Time in high air | 15% | 1% | 8% |

**Overall** = 30% Attack + 30% Defence + 15% Boost + 15% Speed + 10% Impact. Impact is in-game score per
minute, scaled from 50 (scores 0) to 150 (scores 100). If a category can't be rated, for example when an older
replay has no boost data, the remaining weights are scaled up to fill the gap. The player with the highest
Overall is the match's best player.

On the **leaderboard**, a player's numbers are the average of their per-match ratings over the matches that pass
the filters. Players with less than 60 seconds on the field, and bots, aren't rated.

### Known weaknesses

- **The benchmarks are estimates**, not taken from real data. With more replays, check where most players land
  and adjust them.
- **Defence rewards positioning, not results.** There's no stat for clearing the ball or for goals conceded, so a
  player who sits back and rarely saves can still score fairly well.
- **Some stats reward a style, not just skill.** Time in the defensive third helps Defence and time in the
  attacking third helps Attack, so a player's position in the team affects their ratings.
- **Small samples:** a single match per player can produce extreme numbers, which is why the leaderboard has a
  minimum-matches filter.

The app shows the same model on its **How ratings work** page (`#/ratings`), and the "Why this rating" panel on
a match page shows each stat's value and score for one player.

### Changing the model

Edit the `CATEGORIES`, `OVERALL_WEIGHTS` and `IMPACT` tables at the top of `src/rocket_assistant/ratings.py` and
raise `RATING_VERSION`. Every stored match is re-rated the next time the server starts.

## Configuration

| Env var | Default |
|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `8765` |
| `ROCKET_DATA_DIR` | `./data` |
| `ROCKET_TOOLS_DIR` | `./tools` |
| `ROCKET_MAX_UPLOAD_MB` | `30` |
| `ROCKET_MAX_FILES_PER_UPLOAD` | `50` |
