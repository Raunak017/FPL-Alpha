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

### PropLine EPL odds
- PropLine is the sole odds provider. The key is `.env` → `PROPLINE_API_KEY`.
- Fetch only mapped upcoming fixtures and the selected markets; rely on the 24-hour
  raw-cache TTL for repeat runs unless `--force` is explicitly needed.

### Official FPL API (no key, but still be polite)
- Not formally documented; no published rate limit, but the endpoint **can soft-ban an IP**
  that hammers it. Keep it to **≤ ~1 req/sec**, send a real `User-Agent`, and cache.
- `bootstrap-static` already includes xG/xA/xGI, expected goals conceded, defensive
  contributions, prices, ownership, status/news — so **prefer it over scraping Understat/FBref**.

## Developers (2)

- **dev1 — Rushi Pardeshi.** FPL Team ID `432989` (team name "KanteGetAnyWorse", USA).
- **dev2 — TBD.** Add their FPL Team ID to `.env` as `FPL_TEAM_ID_DEV2` when known.

## Data layers & access

| Layer | Source | Auth | Status |
|-------|--------|------|--------|
| FPL players/teams/fixtures | `fantasy.premierleague.com/api/bootstrap-static/`, `/fixtures/` | none (public) | ✅ working |
| Per-player detail | `/api/element-summary/{id}/` | none | ✅ working |
| Manager squad/history | `/api/entry/{id}/`, `/history/`, `/event/{gw}/picks/` | none (public by Team ID) | ✅ (picks public only after a GW locks) |
| Football xG stats | FPL bootstrap (primary); FBref (secondary) | none | ✅ FPL / ⚠️ FBref scrape with care |
| Understat xG | understat.com | none | ⛔ anti-bot gated now |
| Betting odds | PropLine | `PROPLINE_API_KEY` | ✅ cache-first EPL ingestion |

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
├── scripts/                  # refresh_fpl.py · refresh_propline_odds.py
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
python scripts/refresh_upcoming_propline_odds.py  # mapped upcoming EPL odds
pytest                                 # runs the no-vig math tests
```

`refresh_fpl.py` does nothing over the wire if the cache is still fresh; pass
`--force` to bypass the TTL. PropLine refreshes are cache-first; never poll in a loop.

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
