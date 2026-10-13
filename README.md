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
scripts/           refresh_fpl.py · snapshot_odds.py · demo_market_to_xg.py ·
                   demo_epl_market_to_xg.py · compare_ep_next.py
tests/             pytest
data/{raw,processed,snapshots}/   gitignored cache
```

Downstream stages (`simulation`, `scoring`, `projections`, `optimization`,
`evaluation`) are added when reached — the plan reserves the names.

## Scripts

| Script | What it does |
|--------|---------------|
| `refresh_fpl.py` | Refreshes cached FPL core data (bootstrap + fixtures) and upserts teams/players/fixtures/snapshots into DuckDB. Cache-first. |
| `refresh_propline_odds.py --event-id <id>` | Primary odds ingest: captures PropLine event odds cache-first into DuckDB (`odds_outcome_snapshots`, `odds_event_fixture_mappings`). |
| `build_market_consensus.py --fixture-id <id> [--fit]` | Primary market consensus: derives fair no-vig probabilities from DuckDB snapshots (`consensus_from_latest_odds`). Pass `--fit` to fit and persist team xG to DuckDB. |
| `fit_team_xg.py [--fixture-id <id>]` | Step 4 pipeline: DuckDB consensus → fit Poisson team goals → persisted in DuckDB (`fixture_team_xg`) with market provenance and fit residuals. |
| `optimize_team.py` | Solves the MILP wildcard optimization maximizing starting XI + captain expected points under budget and formation constraints. |
| `explore_xpts.py` | Interactive terminal explorer to filter and inspect expected points across teams, positions, and prices. |
| `snapshot_odds.py --scope <name>` | Fallback/secondary odds ingest: captures scheduled odds snapshot from The Odds API into `data/snapshots/`. |
| `demo_epl_market_to_xg.py` | Secondary/fallback demo: runs market-to-xG directly from cached The Odds API JSON payloads. |
| `compare_ep_next.py` | Directional validation: compares model projections against official FPL `ep_next` predictions. |

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # add keys / team ids as available

python scripts/refresh_fpl.py      # cache FPL bootstrap + fixtures
python scripts/demo_market_to_xg.py # odds -> fair probs -> team xG (offline demo)
python scripts/demo_epl_market_to_xg.py  # same chain on the real EPL slate (offline)
python scripts/compare_ep_next.py  # partial xPts vs FPL's ep_next (offline sanity check)
python scripts/snapshot_odds.py --scope epl-gw1 \
    --captured-at 2026-08-21T17:30:00Z          # scheduled odds snapshot (spends credits)
pytest                             # runs the unit tests
```

## Developers

- **dev1 — Rushi Pardeshi.** FPL Team ID `432989`. Owns the The Odds API key.
- **dev2 — TBD.** Add their Team ID to `.env` as `FPL_TEAM_ID_DEV2`.

Working conventions and module ownership live in [`AGENTS.md`](AGENTS.md).
