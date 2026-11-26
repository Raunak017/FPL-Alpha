# FPL Alpha

Market-informed Fantasy Premier League projection & optimization engine.
Turns bookmaker odds into fair probabilities, infers team scoring rates, and
derives per-player expected FPL points on top of official FPL data.

See [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md) for the full 12-step roadmap.
**Current status:** Steps **1–10** (data → odds → consensus → team xG → player allocation, minutes, deterministic xPts, Monte Carlo simulation), **Wildcard / Starting XI optimization (Step 12)**, and **projection evaluation** are built. Remaining: `E[bonus]` modeling, multi-GW projections (Step 11), and multi-GW transfer/chip optimization (Step 12).

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
  storage.py       DuckDB persistence, history, projections, and evaluations
  schemas.py       typed data contracts between pipeline stages
  ingestion/       fpl.py · odds.py · stats.py           (steps 1–2)
  identity.py      canonical FPL ids + odds-name matching (identity layer)
  markets.py       de-vig + consensus                     (step 3)
  team_xg.py       market-implied Poisson team goals      (step 4)
  allocation.py    team-to-player xG/xA allocation        (steps 5–6)
  minutes.py       expected minutes + start consistency   (step 7)
  scoring.py       versioned FPL scoring ruleset
  projections.py   deterministic xPts assembler           (step 8)
  simulation.py    Monte Carlo match simulator            (step 9)
  optimization.py  MILP Wildcard & Starting XI optimizer  (step 12)
  evaluation.py    backtesting & realized-stats metrics
  models/          reserved for sub-models                (empty)
scripts/           refresh_fpl.py · refresh_upcoming_propline_odds.py · fit_team_xg.py ·
                   build_upcoming_team_xg.py · optimize_team.py · explore_xpts.py ·
                   evaluate_projections.py
tests/             pytest
data/{raw,processed,snapshots}/   gitignored cache
```

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
| `explore_xpts.py` | Interactive terminal explorer to filter, search (`--player`/`--name`), and inspect expected points, ranks, and availability across teams, positions, and prices. |
| `evaluate_projections.py` | Evaluates stored projections against realized FPL match stats (MAE, RMSE, Spearman ρ, bias, top-10/20 capture, CS Brier); supports `--gw`, `--backfill`, and `--player`. |
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
