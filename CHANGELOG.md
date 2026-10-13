# Changelog

Notable user-visible features, persistence changes, and operational workflow
updates. Add an entry here before committing related work.

## 2026-10-13

### Added

- Content-derived canonical SHA-256 fingerprinting for normalized odds snapshot bundles.
- Explicit retry tracking in `odds_ingestion_runs` (`is_retry`, `retry_of_run_id`) preserving original snapshot ingestion ownership (`run_id`) on idempotent re-runs.
- Pre-ingestion run lifecycle observability tracking early-stage failures across API fetching (`fetch_epl_events`, `fetch_event_odds`) and normalization (`normalize_event_odds`).
- Isolated child-process RSS benchmarking in `scripts/benchmark_odds_ingestion.py` using spawned workers for unpolluted peak memory measurement.
- Conflict validation in bulk staging rejecting mismatched odds prices on existing snapshot primary keys while safely permitting identical retries and player-mapping enrichment.

### Changed

- `latest_odds_snapshot_provenance` unified with `consensus_from_latest_odds` to use identical eligible market criteria (completed runs, full books, primary 2.5 totals) and filter out consensus outlier bookmaker observations.
- Ingestion run lifecycle handling guarantees durable `FAILED` records with specific failure-stage details whenever an exception occurs after run initialization, preventing orphaned `RUNNING` records.
- Enforced terminal ingestion run statuses (`COMPLETED` and `FAILED`), prohibiting later lifecycle operations from resetting or overwriting finished runs.
- Prevented unconditional transaction rollbacks in `fail_odds_ingestion_run`, isolating failure reporting from unrelated caller transactions.
- Preserved original `started_at` when `store_odds_snapshot_bundle()` receives an existing `RUNNING` `run_id`, ensuring recorded run duration covers fetching, normalization, and persistence.

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
