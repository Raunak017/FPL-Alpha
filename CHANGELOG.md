# Changelog

Notable user-visible features, persistence changes, and operational workflow
updates.

## [Unreleased]

### Fixed
- **PlayerSnapshot Field Completeness & Defcon Mapping**: Fixed `scripts/optimize_team.py` and `scripts/explore_xpts.py` where `PlayerSnapshot` was missing required fields (`expected_goal_involvements`, `expected_goals_conceded`) and `defensive_contribution_per_90` was incorrectly mapped to `expected_goals_conceded_per_90`. Replaced dummy instantiation with full snapshots from `player_snapshots_from_bootstrap()`.
- **Wildcard Optimization Objective**: Re-formulated `optimization.optimize_wildcard()` to maximize starting XI + captain expected points under budget and formation constraints rather than total 15-man squad xPts.
- **Monte Carlo Correlation & Dynamic Games Played**: Correlated simulated player goals and assists with simulated team goals in `simulation.py` via multinomial allocation and assist binomial sampling instead of independent Poisson sampling. Wired dynamic `games_played` to avoid defaulting to 38.0.
- **Python Compatibility**: Restored `requires-python = ">=3.11"` in `pyproject.toml`.
- **Minutes Shrinkage Bug**: Fixed a major bug in `src/fpl_alpha/minutes.py` where early-season start probabilities and expected minutes were severely artificially deflated because the empirical-Bayes shrinkage was hardcoded to divide by 38 `GAMES_PER_SEASON`. Made `games_played` dynamic based on the target gameweek.
- **Reporting Bug**: Fixed an `UnboundLocalError` in `scripts/compare_ep_next.py` when running offline.

### Added
- **Step 4 Persistence & Residuals**: Finished Step 4 architecture (`DuckDB consensus → fit_team_goals() → persisted team-xG with market provenance + fit residuals`). Added `fixture_team_xg` table in DuckDB, `FixtureTeamXG` schema, and `fit_and_persist_fixture_team_xg()` in `src/fpl_alpha/team_xg.py` / `storage.py`.
- **Step 4 CLI Tool**: Added `scripts/fit_team_xg.py` and `--fit` flag to `scripts/build_market_consensus.py` to fit and persist team goals directly from DuckDB odds consensus.
- **Architecture Integrity**: Preserved primary PropLine → DuckDB → `consensus_from_latest_odds()` pipeline in docs and scripts, keeping The Odds API as a secondary/fallback source.
- **FPL Strength Fallback**: Added `fit_fpl_team_goals()` to `team_xg.py` to map FPL's native 1-5 FDR ratings into expected goals multipliers, removing the reliance on dummy flat goals during offline runs.
- **End-to-End Optimization Script**: Created `scripts/optimize_team.py` to calculate projected points and run a Mixed Integer Linear Programming (MILP) model to output the mathematically optimal 15-man Wildcard squad and Starting XI + Captain.
- **xPts Explorer CLI**: Created `scripts/explore_xpts.py` allowing users to dynamically filter and sort expected points against FPL form, positions, and prices.
- **GLPK Solver Support**: Integrated `pulp.GLPK_CMD(msg=False)` fallback into `optimization.py` to support Apple Silicon machines where default CBC binaries crash.
- **Mock Odds Testing**: Added a `--mock-odds` flag to `scripts/compare_ep_next.py` to bypass the external Odds API and allow testing the deterministic xPts engine locally using a flat 1.5 vs 1.2 dummy goal model.
- Wired `games_played` dynamically through `allocation.py` and `projections.py` to ensure accurate early-season scaling.

## 2026-10-13

### Added
- Content-derived canonical SHA-256 fingerprinting for normalized odds snapshot bundles.
- Explicit retry tracking in `odds_ingestion_runs` (`is_retry`, `retry_of_run_id`) preserving original snapshot ingestion ownership (`run_id`) on idempotent re-runs.
- Pre-ingestion run lifecycle observability tracking early-stage failures across API fetching (`fetch_epl_events`, `fetch_event_odds`) and normalization (`normalize_event_odds`).
- Isolated child-process RSS benchmarking in `scripts/benchmark_odds_ingestion.py` using spawned workers for unpolluted peak memory measurement.

### Changed
- `latest_odds_snapshot_provenance` unified with `consensus_from_latest_odds` to use identical eligible market criteria (completed runs, full books, primary 2.5 totals).

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
- Persisted live team-xG projections, clean-sheet probabilities, fit loss, and market-vs-model comparisons in DuckDB (`team_goal_model_snapshots`).
- `build_team_xg.py` for one fixture and `build_upcoming_team_xg.py` for every mapped future fixture with stored odds.
- Automatic cache-first PropLine ingestion for all strictly mapped upcoming EPL fixtures via `refresh_upcoming_propline_odds.py`.
- Reusable FPL refresh workflow, strict provider-to-FPL fixture matching, and explicit team/player identity aliases.
- `docs/DATA_INGESTION.md` with the normal FPL, odds, consensus, and team-xG command sequence.
- `uv.lock` for reproducible dependency resolution.

### Changed
- FPL and PropLine raw-response caches now use 24-hour TTLs.
- The project plan now records completed Steps 1–4 and the batch team-xG flow.

## Steps 8–9 Historical Updates

### Added
- **Step 8: Deterministic xPts Assembler** (`src/fpl_alpha/projections.py`)
  - Integrated `P(start)` base appearance points.
  - Attacking returns from expected goals and expected assists.
  - Clean sheet probability application for GKP/DEF/MID.
  - Poisson-based estimations for `E[defcon]`, `E[saves]`, and `E[goals_conceded]`.
- **Step 9: Monte Carlo Match Simulator** (`src/fpl_alpha/simulation.py`)
  - Implemented high-performance, vectorized match simulation using `numpy`.
  - Captures full distributions for players (mean, median, ceiling, floor, P(10+), P(15+)).
  - Accounts for correlated events (e.g. clean sheets lost when opponent goals > 0).
- Added `numpy`, `pandas`, and `pulp` to `pyproject.toml` dependencies to unblock Steps 9-12.

### Changed
- Refactored `compare_ep_next.py` to use the centralized projection builder (`project_player_fixture`).
