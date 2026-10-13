# Data Ingestion

Run these commands from the repository root. Set `PROPLINE_API_KEY` in `.env`.

## Setup once

```bash
conda activate fpl-alpha
uv sync --extra dev --active
export PYTHONPATH=src
```

For later shells, activate the environment and set `PYTHONPATH` again; rerun
`uv sync` only after dependency changes.

## Normal gameweek refresh

```bash
python scripts/refresh_fpl.py
```

Fetches stale official FPL bootstrap and fixture responses, then updates teams,
players, fixtures, player snapshots, and newly finalized player history in
DuckDB. This is cache-first. Use `--force` only when an immediate FPL refresh
is needed.

```bash
python scripts/refresh_upcoming_propline_odds.py
```

Performs the normal cache-first FPL refresh, finds current PropLine EPL events,
strictly maps future events to FPL fixtures, and stores timestamped match and
player-prop odds. It does not fetch completed fixtures. Use `--gameweek <N>` to
limit one gameweek; `--force` bypasses only the PropLine cache.

```bash
python scripts/build_upcoming_team_xg.py
```

Reads the latest stored PropLine odds without calling either API. For every
mapped future fixture with complete h2h, BTTS, and totals markets, it builds
no-vig consensus, persists team xG and clean-sheet probabilities, and prints
both built and skipped fixtures.

## Inspect one fixture

```bash
python scripts/build_market_consensus.py --fixture-id <FPL_FIXTURE_ID>
python scripts/build_team_xg.py --fixture-id <FPL_FIXTURE_ID>
```

The first prints fair match probabilities. The second persists one fixture's
team-xG projection and market-vs-model comparison.

## Recommended order

Run the three normal-refresh commands in order when new odds are wanted. The
FPL and PropLine commands are cache-first (PropLine cache TTL is 1 hour; FPL is
24 hours), so repeat runs reuse raw responses until their cache expires. Do not
poll in a tight loop.

## Ingestion Observability and Status Tracking

Every PropLine odds ingestion attempt is tracked in DuckDB (`odds_ingestion_runs`):
- Run states: `RUNNING` -> `COMPLETED` or `FAILED`. Terminal states are immutable.
- Metrics recorded: `failure_stage`, `error_message`, `records_fetched`, `records_parsed`, `records_inserted`, `records_updated`, `duration_ms`, `input_fingerprint`, and retry tracking (`is_retry`, `retry_of_run_id`).
- Downstream consensus and team-xG queries only read data from `COMPLETED` runs, ensuring failed or partial runs are never consumed.

To inspect recent runs:

```bash
duckdb data/fpl_alpha.duckdb "SELECT run_id, status, failure_stage, duration_ms, started_at, error_message FROM odds_ingestion_runs ORDER BY started_at DESC LIMIT 5;"
```

## Failure Recovery and Troubleshooting

### 1. Ingestion / API Failure Mid-Run
- **Cause**: Network timeout, API 5xx, or validation error.
- **System state**: The transaction is automatically rolled back, leaving zero orphaned snapshot rows in DuckDB. The run is logged as `FAILED` with the exact `failure_stage`. Successfully fetched event payloads remain cached on disk (`data/raw/propline/`).
- **Action**: Fix transient network/API issues and re-run:
  ```bash
  python scripts/refresh_upcoming_propline_odds.py
  ```
  The cache-first gateway reuses already-fetched event files within TTL without consuming extra API quota.

### 2. Unmapped PropLine Events
- **Symptom**: Output displays `Unmapped PropLine events (<count>): <home> v <away> (<id>)`.
- **Cause**: Provider team names do not match FPL team names or kickoff timestamps differ.
- **Action**: Unmapped matches are safely skipped (ingestion still proceeds for all mapped fixtures). To map the fixture, add the provider's team name variant to `_ODDS_TEAM_ALIASES` in `src/fpl_alpha/identity.py`, then rerun ingestion.

### 3. Unmatched Player Props
- **Symptom**: Output displays `Unmatched player props (<count>): <name1>, <name2>`.
- **Cause**: Bookmaker player name differs from FPL web name / full name.
- **System state**: Odds are still successfully saved with `fpl_player_id = NULL`. Ingestion succeeds.
- **Action**: Add an entry to `_PROPLINE_PLAYER_ALIASES` in `src/fpl_alpha/identity.py`:
  ```python
  "normalized_name": (fpl_player_id, required_team_fpl_id),
  ```
  Rerunning ingestion will enrich the existing snapshots with the resolved `fpl_player_id` without duplicating rows.

### 4. Conflicting Odds Prices
- **Symptom**: `IngestionValidationError: Found N conflicting odds records with different prices for existing snapshot keys`.
- **Cause**: Incoming data has the exact same primary key `(event, bookmaker, market, captured_at)` but different prices.
- **Action**: Check `data/raw/propline/` cache files for corrupt or manually altered payloads. Use `--force` to capture a new snapshot with an updated timestamp from the provider if odds lines have moved.
