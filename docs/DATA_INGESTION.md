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
FPL and PropLine commands are cache-first with 24-hour cache TTLs, so repeat
runs reuse raw responses until their cache expires. Do not poll in a tight loop.
