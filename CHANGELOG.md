# Changelog

Notable user-visible features, persistence changes, and operational workflow
updates. Add an entry here before committing related work.

## 2026-10-12

### Added

- Vectorized staging architecture for odds ingestion via temporary typed NDJSON staging, dropping ingestion latency to ~2s for 27k rows and under 12s for 250k rows with <2 MB Python staging memory.
- `odds_ingestion_runs` table in DuckDB tracking run status (`RUNNING`, `COMPLETED`, `FAILED`), failure stage, error message, duration, input fingerprint, and inserted/updated record counts.
- `scripts/benchmark_odds_ingestion.py` for evaluating odds ingestion performance and peak memory at 27k, 100k, and 250k row scales.
- Resilience test suite in `tests/test_odds_ingestion_resilience.py` covering atomic rollbacks, recovery, validation checks, and idempotency.

### Changed

- `odds_outcome_snapshots` now links records to `run_id`.
- Downstream market consensus (`markets.consensus_from_latest_odds`) now excludes incomplete or failed ingestion runs.
- `refresh_upcoming_propline_odds.py` and `refresh_propline_odds.py` now invoke `store_odds_snapshot_bundle` with atomic transaction boundaries and audit run logging.

## 2026-10-06 — `2a43a99`

### Added

- Persisted live team-xG projections, clean-sheet probabilities, fit loss, and
  market-vs-model comparisons in DuckDB.
- `build_team_xg.py` for one fixture and `build_upcoming_team_xg.py` for every
  mapped future fixture with stored odds.
- Automatic cache-first PropLine ingestion for all strictly mapped upcoming EPL
  fixtures via `refresh_upcoming_propline_odds.py`.
- Reusable FPL refresh workflow, strict provider-to-FPL fixture matching, and
  explicit team/player identity aliases.
- `docs/DATA_INGESTION.md` with the normal FPL, odds, consensus, and team-xG
  command sequence.
- `uv.lock` for reproducible dependency resolution.

### Changed

- FPL and PropLine raw-response caches now use 24-hour TTLs.
- The project plan now records completed Steps 1–4 and the batch team-xG flow.

### Removed

- Legacy SportsGameOdds and The Odds API clients, configuration, keys, and
  snapshot command. PropLine is the sole odds provider.
