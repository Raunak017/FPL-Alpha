# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Fixed
- **Minutes Shrinkage Bug**: Fixed a major bug in `src/fpl_alpha/minutes.py` where early-season start probabilities and expected minutes were severely artificially deflated because the empirical-Bayes shrinkage was hardcoded to divide by 38 `GAMES_PER_SEASON`. Made `games_played` dynamic based on the target gameweek.
- **Reporting Bug**: Fixed an `UnboundLocalError` in `scripts/compare_ep_next.py` when running offline.

### Added
- **Mock Odds Testing**: Added a `--mock-odds` flag to `scripts/compare_ep_next.py` to bypass the external Odds API and allow testing the deterministic xPts engine locally using a flat 1.5 vs 1.2 dummy goal model.
- Wired `games_played` dynamically through `allocation.py` and `projections.py` to ensure accurate early-season scaling.

## [2024-03-XX] - Previous Updates
### Added
- **Step 8: Deterministic xPts Assembler** (`src/fpl_alpha/projections.py`)
  - Integrated `P(start)` base appearance points.
  - Attacking returns from expected goals and expected assists.
  - Clean sheet probability application for GKP/DEF/MID.
  - Poisson-based estimations for `E[defcon]`, `E[saves]`, and `E[goals_conceded]`.
- Enforced Changelog rule in `AGENTS.md`.
- **Step 9: Monte Carlo Match Simulator** (`src/fpl_alpha/simulation.py`)
  - Implemented high-performance, vectorized match simulation using `numpy`.
  - Captures full distributions for players (mean, median, ceiling, floor, P(10+), P(15+)).
  - Accounts for correlated events (e.g. clean sheets lost when opponent goals > 0).
- Added `numpy`, `pandas`, and `pulp` to `pyproject.toml` dependencies to unblock Steps 9-12.

### Changed
- Refactored `compare_ep_next.py` to use the centralized projection builder (`project_player_fixture`).

