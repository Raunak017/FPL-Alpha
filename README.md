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
scripts/           refresh_fpl.py · refresh_upcoming_propline_odds.py · fit_team_xg.py ·
                   build_upcoming_team_xg.py · optimize_team.py · explore_xpts.py
tests/             pytest
data/{raw,processed,snapshots}/   gitignored cache
```

Downstream stages (`simulation`, `scoring`, `projections`, `optimization`,
`evaluation`) are added when reached — the plan reserves the names.

## Scripts

| Script | What it does |
|--------|---------------|
| `refresh_fpl.py` | Refreshes cached FPL core data (bootstrap + fixtures) and upserts teams/players/fixtures/snapshots into DuckDB. Cache-first. |
| `refresh_upcoming_propline_odds.py` | Primary odds ingest: captures all mapped upcoming EPL fixtures into DuckDB in one transaction. |
| `refresh_propline_odds.py --event-id <id>` | Captures a specific PropLine event odds cache-first into DuckDB. |
| `build_team_xg.py --fixture-id <id>` | Fits team xG for a fixture from DuckDB odds consensus and persists `team_goal_model_snapshots`. |
| `build_upcoming_team_xg.py` | Fits and persists team xG for every mapped upcoming fixture with stored odds. |
| `build_market_consensus.py --fixture-id <id> [--fit]` | Primary market consensus: derives fair no-vig probabilities from DuckDB snapshots (`consensus_from_latest_odds`). Pass `--fit` to fit and persist team xG to DuckDB. |
| `fit_team_xg.py [--fixture-id <id>]` | Step 4 pipeline: DuckDB consensus → fit Poisson team goals → persisted in DuckDB (`fixture_team_xg`) with market provenance and fit residuals. |
| `optimize_team.py` | Solves the MILP wildcard optimization maximizing starting XI + captain expected points under budget and formation constraints. |
| `explore_xpts.py` | Interactive terminal explorer to filter and inspect expected points across teams, positions, and prices. |
| `benchmark_odds_ingestion.py` | Benchmarks odds ingestion throughput and peak memory usage across scales. |
| `snapshot_odds.py --scope <name>` | Fallback/secondary odds ingest: captures scheduled odds snapshot from The Odds API into `data/snapshots/`. |
| `demo_epl_market_to_xg.py` | Secondary/fallback demo: runs market-to-xG directly from cached The Odds API JSON payloads. |
| `compare_ep_next.py` | Directional validation: compares model projections against official FPL `ep_next` predictions. |

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # add keys / team ids as available

python scripts/refresh_fpl.py      # cache FPL bootstrap + fixtures
python scripts/refresh_upcoming_propline_odds.py  # mapped upcoming EPL odds
python scripts/build_upcoming_team_xg.py          # fit Poisson team goals
python scripts/optimize_team.py                   # run wildcard MILP optimization
pytest                             # runs the unit tests
```

## Developers

- **dev1 — Rushi Pardeshi.** FPL Team ID `432989`. Owns the The Odds API key.
- **dev2 — TBD.** Add their Team ID to `.env` as `FPL_TEAM_ID_DEV2`.

Working conventions and module ownership live in [`AGENTS.md`](AGENTS.md).
