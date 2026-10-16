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
2. **Score each stat 0–100** against benchmarks taken from real matches of the same mode.
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

Goals, shots, assists and goals conceded are converted to **per 5 minutes played**, so short games and overtime
compare fairly.

Two stats are noisy when the numbers are small, so they are pulled toward the mode's average (a Bayesian
average):

- **Shooting %** = (goals + 4 × average conversion) ÷ (shots + 4). One goal from one shot in 3v3 gives
  (1 + 4 × 0.41) ÷ 5 = 53%, not 100%.
- **Save rate** = (saves + 4 × average save rate) ÷ (opponent shots + 4), where opponent shots are all shots taken
  by the other team.

### 2. Scoring each stat 0–100

Stats are very different between modes (a 1v1 player takes far more shots than a 3v3 player), so each mode has
its own benchmarks. For every stat, the **10th percentile** of all rated players in that mode scores 0, the
**90th percentile** scores 100, and values in between are on a straight line:

```
score = (value − p10) / (p90 − p10) × 100, capped at 0 and 100
```

For stats where lower is better, like time at 0 boost, the scale is reversed. A rating of 50 means roughly "a
typical player in this mode". Modes without enough data (like 4v4) use the closest mode. A stat with no spread in
a mode is skipped there (assists in 1v1) and the other weights in its category are scaled up.

The benchmarks ship with the app in `src/rocket_assistant/benchmarks.json`. They are fixed, so ratings don't
change when someone uploads a replay. To recalculate them from your own matches:

```powershell
uv run rocket-assistant calibrate        # writes DATA_DIR/benchmarks.json and re-rates every match
```

A mode needs at least 50 rated player-matches to get its own benchmarks. `DATA_DIR/benchmarks.json` takes
precedence over the shipped file; delete it to go back. Use `--output` to write somewhere else, for example
`--output src/rocket_assistant/benchmarks.json` to update the shipped defaults.

### 3. Category weights

The 0 → 100 columns show the 3v3 benchmarks. The **How ratings work** page in the app lists them for every mode.

**Attack**

| Stat | Weight | 3v3: 0 → 100 |
|---|---|---|
| Goals / 5 min | 35% | 0 → 2.0 |
| Shots / 5 min | 25% | 0 → 3.9 |
| Assists / 5 min | 15% | 0 → 1.5 |
| Time in attacking third | 15% | 12% → 28% |
| Shooting % (adjusted, see above) | 10% | 27% → 58% |

**Defence**

| Stat | Weight | 3v3: 0 → 100 |
|---|---|---|
| Save rate (saves ÷ opponent shots, adjusted) | 40% | 5% → 26% |
| Time behind the ball | 35% | 65% → 80% |
| Team goals conceded / 5 min (lower is better) | 25% | 4.8 → 0 |

Saves are measured per opponent shot rather than per minute, so a player isn't rewarded just because their team
lets the other side shoot a lot. Goals conceded is a team stat, but it is the one Defence stat that is about
results and not positioning.

**Boost**

| Stat | Weight | 3v3: 0 → 100 |
|---|---|---|
| Time at 0 boost (lower is better) | 30% | 24% → 5% |
| Boost collected / min | 30% | 225 → 434 |
| Small pads / min | 25% | 6.1 → 10.7 |
| Time at 100 boost, i.e. boost sitting unused (lower is better) | 15% | 29% → 8% |

**Speed**

| Stat | Weight | 3v3: 0 → 100 |
|---|---|---|
| Average speed | 40% | 1214 → 1486 uu/s |
| Time supersonic | 30% | 3.3% → 11.8% |
| Time at slow speed (lower is better) | 15% | 63% → 42% |
| Time in high air | 15% | 1.1% → 6.7% |

**Overall** = 30% Attack + 30% Defence + 10% Boost + 10% Speed + 20% Impact. Impact is in-game score per minute
(3v3: 20 → 104). Boost and Speed describe how someone plays more than whether their team wins, so they carry
less weight. If a category can't be rated, for example when an older replay has no boost data, the remaining
weights are scaled up. The player with the highest Overall is the match's best player. Players with less than 60
seconds on the field, and bots, aren't rated.

### Leaderboard

One match says little about a player: in the server data, a single match explains only about 13% of the
difference between players. So the leaderboard doesn't show the plain average. Each player's average is blended
with the average of everyone, **as if they had also played 10 average matches**:

```
adjusted = (sum of ratings + 10 × everyone's average) ÷ (matches + 10)
```

A newcomer with one 90 shows around 50, while someone who averaged 56 over 270 matches stays at about 55.
The raw average is shown when you hover a rating. Both are calculated from the matches that pass the filters.

### How well it works

Checked on 310 matches from a real server (1,478 rated player-matches):

| | Old model | Current model |
|---|---|---|
| Average Overall in 1v1 / 2v2 / 3v3 | 62 / 51 / 41 | 51 / 47 / 45 |
| Defence: how strongly it separates winners from losers (Cohen's d) | 0.09 | 0.91 |
| Overall: same | — | 1.04 |
| Match's best player is on the winning team | 83% | 91% |

Known weaknesses:

- **Benchmarks depend on who uploads.** They describe the players in the data, not the whole Rocket League
  population, so 50 means "typical for this group". Recalibrate when the data grows or changes.
- **Some stats reward a style, not just skill.** Time in the attacking third helps Attack and time behind the ball
  helps Defence, so a player's role in the team affects their ratings.
- **Goals conceded is shared by the whole team**, so a good defender on a losing team still loses some Defence.

The app shows the same model on its **How ratings work** page (`#/ratings`), and the "Why this rating" panel on
a match page shows each stat's value and score for one player.

### Changing the model

Edit the `CATEGORIES`, `OVERALL_WEIGHTS`, `IMPACT` and prior constants at the top of
`src/rocket_assistant/ratings.py` and raise `RATING_VERSION`. Every stored match is re-rated the next time the
server starts. New benchmarks (from `calibrate`) are detected automatically by their hash, so they don't need a
version bump.

## Configuration

| Env var | Default |
|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `8765` |
| `ROCKET_DATA_DIR` | `./data` |
| `ROCKET_TOOLS_DIR` | `./tools` |
| `ROCKET_MAX_UPLOAD_MB` | `30` |
| `ROCKET_MAX_FILES_PER_UPLOAD` | `50` |
