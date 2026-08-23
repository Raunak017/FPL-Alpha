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

### The Odds API — our one EPL odds source, the tightest constraint
This is the **only** odds provider now (SportsGameOdds was dropped — its free
tier paywalls EPL). Handle its budget with the most care.
- Free tier ≈ **500 credits/month**. **Credits are consumed per request as
  `#markets × #regions`** — e.g. `markets=h2h,totals` + `regions=uk,eu` = **4 credits/call**
  (historical requests cost **×10**). This multiplies fast; request only the
  markets/regions a downstream stage actually consumes.
- **The API reports your budget back to you.** Every live response carries
  `x-requests-remaining`, `x-requests-used`, and `x-requests-last` (cost of that
  call). `cache.py` records these to `data/raw/the-odds-api/_usage.json` and logs
  a warning once remaining dips below `THE_ODDS_API.low_budget_threshold` (50).
  Read the running total with `cache.read_usage("the-odds-api")`; treat that
  count as authoritative, not any counter we keep ourselves.
- **Rules for this repo:**
  - Throttle is `THE_ODDS_API.min_interval_s = 2.0` and the cache TTL is 10 min
    in `config.py` — tighten, never loosen.
  - At most a **handful of snapshots per gameweek** (e.g. Mon / Wed / Fri /
    deadline-day), never a live loop. Always develop against the cached file.
- **Player props (feasible, not yet built).** Per-player markets exist for EPL
  but only via the *event-specific* endpoint, one fixture at a time, and only
  from **US bookmakers** (`regions=us`):
  `GET /v4/sports/soccer_epl/events/{eventId}/odds?regions=us&markets=player_goal_scorer_anytime,...`.
  Get the `{eventId}`s from `GET /v4/sports/soccer_epl/events` first — that list
  call is **free** (no credits) — then spend `#markets × #regions` **per event**
  (anytime-goalscorer over a 10-match slate ≈ 10 credits/snapshot). Available
  keys: `player_goal_scorer_anytime`/`_first`/`_last`, `player_assists`,
  `player_shots`, `player_shots_on_target`, `player_to_receive_card`/`_red_card`.
  See the header comment in `ingestion/odds.py`; wire up alongside Plan step 5.
- Key: `.env` → `ODDS_API_KEY`.

### Consolidating many bookmakers into one number
The Odds API returns **raw per-bookmaker prices with no consensus of its own**
(a single EPL fixture can list ~20 books). Our consolidation is
`markets.consensus`: de-vig each book independently, then combine per outcome
with an **outlier-resistant center** (drop the highest and lowest quote, average
the rest — a symmetric trimmed mean that degrades to the median for 3 books and
the plain mean for ≤2), renormalized to a valid distribution. This keeps one
stray/slow book from skewing the fair probability, which matters most for thin
markets like player props quoted by only 2–3 US books.

### Official FPL API (no key, but still be polite)
- Not formally documented; no published rate limit, but the endpoint **can soft-ban an IP**
  that hammers it. Keep it to **≤ ~1 req/sec**, send a real `User-Agent`, and cache.
- `bootstrap-static` already includes xG/xA/xGI, expected goals conceded, defensive
  contributions, prices, ownership, status/news — so **prefer it over scraping Understat/FBref**.

### Official FPL API (no key, but still be polite)
- Not formally documented; no published rate limit, but the endpoint **can soft-ban an IP**
  that hammers it. Keep it to **≤ ~1 req/sec**, send a real `User-Agent`, and cache.
- `bootstrap-static` already includes xG/xA/xGI, expected goals conceded, defensive
  contributions, prices, ownership, status/news — so **prefer it over scraping Understat/FBref**.

## Developers (2)

- **dev1 — Rushi Pardeshi.** FPL Team ID `432989` (team name "KanteGetAnyWorse", USA).
  Owns the current The Odds API key.
- **dev2 — TBD.** Add their FPL Team ID to `.env` as `FPL_TEAM_ID_DEV2` when known.

## Data layers & access

| Layer | Source | Auth | Status |
|-------|--------|------|--------|
| FPL players/teams/fixtures | `fantasy.premierleague.com/api/bootstrap-static/`, `/fixtures/` | none (public) | ✅ working |
| Per-player detail | `/api/element-summary/{id}/` | none | ✅ working |
| Manager squad/history | `/api/entry/{id}/`, `/history/`, `/event/{gw}/picks/` | none (public by Team ID) | ✅ (picks public only after a GW locks) |
| Football xG stats | FPL bootstrap (primary); FBref (secondary) | none | ✅ FPL / ⚠️ FBref scrape with care |
| Understat xG | understat.com | none | ⛔ anti-bot gated now |
| Betting odds (EPL match) | The Odds API (`soccer_epl`, featured `/odds`) | **API key** (`ODDS_API_KEY`) | ✅ working — decimal odds; live EPL source (verified 2026-08-21) |
| Betting odds (EPL player props) | The Odds API (event `/events/{id}/odds`, `regions=us`) | **API key** (`ODDS_API_KEY`) | 🟡 feasible, not built — US books only, per-event credit cost (see odds.py) |

Downstream stages (`simulation`, `scoring`, `projections`, `optimization`,
`evaluation`) are added when reached — the plan reserves the names, but empty
packages are intentionally omitted for now.

## Running

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # add keys / team ids as available

python scripts/refresh_fpl.py         # cache FPL bootstrap + fixtures (cache-first)
python scripts/snapshot_odds.py \
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
