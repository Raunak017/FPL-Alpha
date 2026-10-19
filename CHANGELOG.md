# Changelog

Notable user-visible features, persistence changes, and operational workflow
updates.

## [Unreleased]

### Fixed
- **Small-Sample Cameo Rate Inflation (DefCon, Saves, Goals Conceded)**: Applied empirical-Bayes shrinkage toward positional priors for `defensive_contribution_per_90`, `saves_per_90`, and `goals_conceded_per_90` based on minutes played in `projections.py` and `simulation.py`. Fixes extreme point inflation where players with 1–5 cameo minutes and 1–2 actions (e.g., Nicoll-Jazuli, Latibeaudiere, Tosin) were extrapolated to 60–180 per-90 rates and erroneously awarded maximum defensive contribution points.
- **PlayerSnapshot Field Completeness & Defcon Mapping**: Fixed `scripts/optimize_team.py` and `scripts/explore_xpts.py` where `PlayerSnapshot` was missing required fields (`expected_goal_involvements`, `expected_goals_conceded`) and `defensive_contribution_per_90` was incorrectly mapped to `expected_goals_conceded_per_90`. Replaced dummy instantiation with full snapshots from `player_snapshots_from_bootstrap()`.
- **Wildcard Optimization Objective**: Re-formulated `optimization.optimize_wildcard()` to maximize starting XI + captain expected points under budget and formation constraints rather than total 15-man squad xPts.
- **Monte Carlo Correlation & Dynamic Games Played**: Correlated simulated player goals and assists with simulated team goals in `simulation.py` via multinomial allocation and assist binomial sampling instead of independent Poisson sampling. Wired dynamic `games_played` to avoid defaulting to 38.0.
- **Python Compatibility**: Restored `requires-python = ">=3.11"` in `pyproject.toml`.
- **Minutes Shrinkage Bug**: Fixed a major bug in `src/fpl_alpha/minutes.py` where early-season start probabilities and expected minutes were severely artificially deflated because the empirical-Bayes shrinkage was hardcoded to divide by 38 `GAMES_PER_SEASON`. Made `games_played` dynamic based on the target gameweek.
- **Reporting Bug**: Fixed an `UnboundLocalError` in `scripts/compare_ep_next.py` when running offline.
### Changed
- **Consolidated Team xG Calculation & Storage**: Unified live fitting and persistence pipelines across `team_xg.py` and `storage.py`. Models and market comparisons are stored in `team_goal_model_snapshots` (with `residuals` and `market_provenance`), while `fixture_team_xg` is maintained as a backward-compatible view with automatic migration for legacy base tables.
- **Unified Fixture Resolution**: Added targeted `storage.load_fixture()` to avoid full fixture scans, parameterized `mapped_fixture_ids_with_odds()` and `upcoming_fixture_ids_with_odds()`, and aligned fixture resolution across CLI scripts (`build_team_xg.py`, `fit_team_xg.py`).
- **Consolidated Downstream Model Resolution**: Added `resolve_fixture_team_goals()` in `team_xg.py`, eliminating duplicate market lookup and FPL fallback code in `scripts/optimize_team.py` and `scripts/explore_xpts.py`. Deduplicated `MarketProb` in `schemas.py`.

### Added
- **Match Selection & Appearance Consistency Factor**: Added [`PlayerConsistency`](file:///Users/rushipardeshi/projects/FPL/FPL-Alpha/src/fpl_alpha/schemas.py) schema and [`load_player_consistency`](file:///Users/rushipardeshi/projects/FPL/FPL-Alpha/src/fpl_alpha/storage.py) to aggregate per-player match appearance frequency (`matches_played / games_played`) and start frequency (`matches_started / games_played`) from past gameweek histories in DuckDB. Wired empirical-Bayes consistency scaling ([`appearance_consistency_factor`](file:///Users/rushipardeshi/projects/FPL/FPL-Alpha/src/fpl_alpha/minutes.py), [`start_consistency_factor`](file:///Users/rushipardeshi/projects/FPL/FPL-Alpha/src/fpl_alpha/minutes.py)) into [`expected_minutes()`](file:///Users/rushipardeshi/projects/FPL/FPL-Alpha/src/fpl_alpha/minutes.py), [`start_probability()`](file:///Users/rushipardeshi/projects/FPL/FPL-Alpha/src/fpl_alpha/minutes.py), [`attack_weights_from_bootstrap()`](file:///Users/rushipardeshi/projects/FPL/FPL-Alpha/src/fpl_alpha/allocation.py), and [`project_player_fixture()`](file:///Users/rushipardeshi/projects/FPL/FPL-Alpha/src/fpl_alpha/projections.py). Penalizes fringe cameos (e.g., 1 appearance in 6 gameweeks) while preserving regular starters and rotation assets. Added `Apps` column to `scripts/explore_xpts.py`.
- **GitHub Actions CI Workflow**: Added `.github/workflows/ci.yml` running the test suite with `uv` on Python 3.11 for pushes to `main`, PRs to `main`, and manual dispatch (`workflow_dispatch`), with concurrency cancellation for obsolete runs.
- **Step 4 Persistence & Residuals**: Finished Step 4 architecture (`DuckDB consensus → fit_team_goals() → persisted team-xG with market provenance + fit residuals`). Added `fixture_team_xg` table in DuckDB, `FixtureTeamXG` schema, and `fit_and_persist_fixture_team_xg()` in `src/fpl_alpha/team_xg.py` / `storage.py`.
- **Step 4 CLI Tool**: Added `scripts/fit_team_xg.py` and `--fit` flag to `scripts/build_market_consensus.py` to fit and persist team goals directly from DuckDB odds consensus.
- **Architecture Integrity**: Preserved primary PropLine → DuckDB → `consensus_from_latest_odds()` pipeline in docs and scripts, keeping The Odds API as a secondary/fallback source.
- **FPL Strength Fallback**: Added `fit_fpl_team_goals()` to `team_xg.py` to map FPL's native 1-5 FDR ratings into expected goals multipliers, removing the reliance on dummy flat goals during offline runs.
- **End-to-End Optimization Script**: Created `scripts/optimize_team.py` to calculate projected points and run a Mixed Integer Linear Programming (MILP) model to output the mathematically optimal 15-man Wildcard squad and Starting XI + Captain.
- **xPts Explorer CLI**: Created `scripts/explore_xpts.py` allowing users to dynamically filter and sort expected points against FPL form, positions, and prices.
- **GLPK Solver Support**: Integrated `pulp.GLPK_CMD(msg=False)` fallback into `optimization.py` to support Apple Silicon machines where default CBC binaries crash.
- **Mock Odds Testing**: Added a `--mock-odds` flag to `scripts/compare_ep_next.py` to bypass the external Odds API and allow testing the deterministic xPts engine locally using a flat 1.5 vs 1.2 dummy goal model.
- **Live Market xG in Optimization & Exploration**: Updated `scripts/optimize_team.py` and `scripts/explore_xpts.py` to seamlessly query DuckDB for persisted live PropLine team-xG projections, automatically falling back to FPL strength FDR multipliers only when market odds are missing.
- Wired `games_played` dynamically through `allocation.py` and `projections.py` to ensure accurate early-season scaling.

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
