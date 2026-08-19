# FPL Alpha — Market-Informed Fantasy Premier League Projection Engine

A data-driven FPL decision-support tool. The end goal is a
**market → probabilities → expected-points** engine: de-vig bookmaker odds →
infer team scoring rates (Poisson λ) → simulate/derive per-player expected FPL
points, layered on top of official FPL data. Full roadmap in
[`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md); working conventions and module
ownership in [`AGENTS.md`](AGENTS.md).

## ⚠️ RATE LIMITS — READ BEFORE WRITING ANY API CODE ⚠️

**Free-tier budgets are tiny and easy to blow through. Never poll in a loop.
Always cache responses to `data/` and read from cache during development.**
Treat every live call as if it costs money — because on these tiers it effectively does.

In this repo the rule is enforced structurally: **every external call goes
through `fpl_alpha.cache.fetch`**, which is cache-first and throttled, with
per-provider budgets defined in `fpl_alpha.config` (`ProviderLimits`). Never
call `urllib`/`requests` directly from a stage; never add a call that bypasses
`cache.py`.

### SportsGameOdds — the tightest constraint, handle with most care
- **The free tier does NOT include EPL.** Live test returned:
  `400 "The leagueID EPL is unavailable at your current subscription tier. Upgrade to unlock"`.
  So on the current key we **cannot pull EPL odds at all** without upgrading.
- Documented free-tier limits (when a league IS available): ~**2,500 objects/month**,
  **10 requests/minute**, ~**10-minute** odds refresh. Billing is **per match-object**
  (one fixture with hundreds of markets = one object), so a full slate of ~10 EPL matches
  is ~10 objects per snapshot.
- **Rules for this repo:**
  - Never exceed **10 req/min** (`SPORTSGAMEODDS.min_interval_s = 6.0` in `config.py`).
  - Treat the monthly object budget as scarce: at most a **handful of snapshots per gameweek**
    (e.g. Mon / Wed / Fri / deadline-day), never a live loop.
  - Odds only refresh every ~10 min upstream, so polling faster buys nothing but burns quota.
  - Always write the response to `data/` and develop against the cached file.
- Key lives in `.env` as `SPORTSGAMEODDS_API_KEY` (gitignored). Auth via `X-Api-Key` header
  **or** `?apiKey=` query param. List valid leagues: `GET /v2/leagues/`.

### The Odds API (fallback for EPL odds)
- Free tier ≈ **500 credits/month**. **Credits are consumed per request as
  `#markets × #regions`** — e.g. `markets=h2h,totals` + `regions=uk,eu` = **4 credits/call**.
  This multiplies fast; request only the markets/regions you actually need.
- Soccer player props are currently **US-bookmaker only** on this API.
- Key: `.env` → `ODDS_API_KEY`.

### Official FPL API (no key, but still be polite)
- Not formally documented; no published rate limit, but the endpoint **can soft-ban an IP**
  that hammers it. Keep it to **≤ ~1 req/sec**, send a real `User-Agent`, and cache.
- `bootstrap-static` already includes xG/xA/xGI, expected goals conceded, defensive
  contributions, prices, ownership, status/news — so **prefer it over scraping Understat/FBref**.

## Developers (2)

- **dev1 — Rushi Pardeshi.** FPL Team ID `432989` (team name "KanteGetAnyWorse", USA).
  Owns the current SportsGameOdds key.
- **dev2 — TBD.** Add their FPL Team ID to `.env` as `FPL_TEAM_ID_DEV2` when known.

## Data layers & access

| Layer | Source | Auth | Status |
|-------|--------|------|--------|
| FPL players/teams/fixtures | `fantasy.premierleague.com/api/bootstrap-static/`, `/fixtures/` | none (public) | ✅ working |
| Per-player detail | `/api/element-summary/{id}/` | none | ✅ working |
| Manager squad/history | `/api/entry/{id}/`, `/history/`, `/event/{gw}/picks/` | none (public by Team ID) | ✅ (picks public only after a GW locks) |
| Football xG stats | FPL bootstrap (primary); FBref (secondary) | none | ✅ FPL / ⚠️ FBref scrape with care |
| Understat xG | understat.com | none | ⛔ anti-bot gated now |
| Betting odds | SportsGameOdds / The Odds API | **API key** | 🔑 SGO EPL paywalled; Odds API key not set |

## Layout

```
FPL-Alpha/
├── CLAUDE.md                 # this file
├── README.md  AGENTS.md      # quickstart / working conventions
├── pyproject.toml
├── .env / .env.example       # secrets + team IDs (.env gitignored)
├── .gitignore
│
├── src/fpl_alpha/
│   ├── config.py             # env + paths + per-provider rate-limit budgets
│   ├── cache.py              # cache-first, throttled HTTP gateway (the one choke point)
│   ├── snapshots.py          # timestamped odds/FPL captures + manifest
│   ├── schemas.py            # typed data contracts between pipeline stages
│   ├── ingestion/            # fpl.py · odds.py · stats.py            (steps 1–2)
│   ├── identity.py           # canonical FPL ids + odds-name matching  (identity layer)
│   ├── markets.py            # de-vig + consensus                      (step 3)
│   ├── team_xg.py            # market-implied Poisson team goals       (step 4)
│   └── models/               # player-level models                    (steps 5+, empty)
│
├── scripts/                  # refresh_fpl.py · snapshot_odds.py
├── tests/                    # pytest (no-vig math covered)
├── notebooks/
├── docs/                     # PROJECT_PLAN.md (the 12-step roadmap)
└── data/{raw,processed,snapshots}/   # cached API JSON (gitignored)
```

Downstream stages (`simulation`, `scoring`, `projections`, `optimization`,
`evaluation`) are added when reached — the plan reserves the names, but empty
packages are intentionally omitted for now.

## Running

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # add keys / team ids as available

python scripts/refresh_fpl.py         # cache FPL bootstrap + fixtures (cache-first)
python scripts/snapshot_odds.py --provider the-odds-api \
    --scope epl-gw1 --captured-at 2026-08-21T17:30:00Z   # scheduled odds snapshot
pytest                                 # runs the no-vig math tests
```

`refresh_fpl.py` does nothing over the wire if the cache is still fresh; pass
`--force` to bypass the TTL. Run odds snapshots on a schedule, never in a loop.

## Conventions

- **Cache-first.** Every external call goes through `cache.fetch`; dev work reads
  `data/raw/`. Never bypass it or add a polling loop against any API.
- **No speculative abstractions.** Start each new stage as a single module;
  promote to a package only when it genuinely needs multiple files. Don't
  pre-create empty folders to match the plan's target tree.
- **Data contract first.** Stages exchange the typed records in `schemas.py`, not
  raw dicts — so the two devs can build adjacent stages in parallel.
- Secrets only in `.env`. Never hardcode keys in tracked files or commit `data/`.
- Reproducibility: timestamps are passed in explicitly (see `snapshots.py`),
  never generated inline.
- Python ≥ 3.11, type hints on public functions. Tests for any non-trivial math.
- Times in the design notes are PT/BST; the 2026/27 season starts at the **GW1
  deadline Fri Aug 21 2026** — pre-season, expect `current_event = None`,
  `next_event = 1` from the FPL API.
