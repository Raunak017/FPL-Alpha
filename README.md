# FPL Alpha

Market-informed Fantasy Premier League projection & optimization engine.
Turns bookmaker odds into fair probabilities, infers team scoring rates, and
derives per-player expected FPL points on top of official FPL data.

See [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md) for the full 12-step roadmap.
**Current focus: steps 1–4** (FPL data → odds → no-vig probabilities → team xG).

## ⚠️ Rate limits first

Free-tier odds budgets are tiny. **Every external call goes through
`fpl_alpha.cache.fetch`, which is cache-first and throttled** — dev work reads
`data/raw/`, snapshots are captured on a schedule, never in a loop. Never add an
API call that bypasses `cache.py`. Details in [`CLAUDE.md`](CLAUDE.md).

## Layout

```
src/fpl_alpha/
  config.py        env + paths + per-provider rate-limit budgets
  cache.py         cache-first, throttled HTTP gateway  (the one choke point)
  snapshots.py     timestamped odds/FPL captures + manifest
  schemas.py       typed data contracts between pipeline stages
  ingestion/       fpl.py · odds.py · stats.py           (steps 1–2)
  identity.py      canonical FPL ids + odds-name matching (identity layer)
  markets.py       de-vig + consensus                     (step 3)
  team_xg.py       market-implied Poisson team goals      (step 4)
  models/          player-level models                    (steps 5+, empty)
scripts/           refresh_fpl.py · snapshot_odds.py
tests/             pytest
data/{raw,processed,snapshots}/   gitignored cache
```

Downstream stages (`simulation`, `scoring`, `projections`, `optimization`,
`evaluation`) are added when reached — the plan reserves the names.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # add keys / team ids as available

python scripts/refresh_fpl.py      # cache FPL bootstrap + fixtures
python scripts/demo_market_to_xg.py # odds -> fair probs -> team xG (offline demo)
pytest                             # runs the unit tests
```

## Developers

- **dev1 — Rushi Pardeshi.** FPL Team ID `432989`. Owns the SportsGameOdds key.
- **dev2 — TBD.** Add their Team ID to `.env` as `FPL_TEAM_ID_DEV2`.

Working conventions and module ownership live in [`AGENTS.md`](AGENTS.md).
