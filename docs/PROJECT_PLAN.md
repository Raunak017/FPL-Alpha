# FPL Alpha — Project Plan

## Goal

Build a market-informed FPL projection and optimization engine that combines official FPL data, football statistics, betting markets, expected minutes, and simulation to estimate player expected points and recommend squad decisions.

> **See also:** [`XPTS_FORMULA_STATUS.md`](XPTS_FORMULA_STATUS.md) — the player
> expected-points formula mapped term-by-term to current code, the team→player
> allocation blocker, and why odds and FPL data are complementary (backward rates
> vs. forward fixture-specific expectations).

## Status (as of 2026-08-23)

Steps **1–4** (the initial focus) are code-complete and unit-tested end-to-end,
running on **real cached EPL odds** from The Odds API (`soccer_epl`, verified
2026-08-21). SportsGameOdds was dropped (its free tier paywalls EPL). Player-level
work has begun: steps **5–6** now have a baseline **historical-shares allocator**
(`allocation.py`) that splits market team xG into per-player xG/xA from cached FPL
data — no new API spend. Steps 7+ (minutes, deterministic xPts, simulation) not
started; the player-prop endpoint is researched but not wired (see step 2).

**Legend:** ✅ done · 🟡 partial (see `[remaining: …]` in the heading) · ⬜ not started

| Step | Status |
|------|--------|
| 1. FPL Data Ingestion | 🟡 partial |
| 2. Betting Odds Ingestion | 🟡 partial |
| 3. No-Vig Market Probabilities | 🟡 partial |
| 4. Market-Implied Team xG | ✅ done |
| 5. Player Goal Probabilities | 🟡 partial |
| 6. Player Assist Probabilities | 🟡 partial |
| 7–12 (minutes → optimizer) | ⬜ not started |

## Roadmap

### 1. FPL Data Ingestion — 🟡 partial [remaining: normalize player-history & detailed FPL stats into schemas]
Pull and normalize:

- ✅ Players — `identity.players_from_bootstrap`
- ✅ Teams — `identity.teams_from_bootstrap`
- ✅ Fixtures — `ingestion.fpl.fixtures`
- ✅ Prices — `Player.now_cost`
- ✅ Positions — `element_type` → GKP/DEF/MID/FWD
- 🟡 FPL statistics — pulled & cached in bootstrap-static; not yet extracted into typed records
- 🟡 Player history — fetchable via `ingestion.fpl.element_summary`; not yet normalized

✅ Canonical player and team IDs established (FPL is the source of truth).

*Implemented in `src/fpl_alpha/ingestion/fpl.py`, `identity.py`; run via `scripts/refresh_fpl.py`; all calls cache-first through `cache.py`.*

### 2. Betting Odds Ingestion — 🟡 partial [remaining: BTTS; wire up player props / shots / cards (endpoint researched, see below)]
Integrate an odds provider and collect:

- ✅ Match odds (h2h) — client wired
- ✅ Goal totals — client wired
- ⬜ BTTS
- 🟡 Player goal props — feasible & documented, not wired (see note)
- 🟡 Assist props — feasible & documented, not wired
- 🟡 Shots — feasible & documented, not wired
- ⬜ Saves — no market on The Odds API for soccer
- 🟡 Cards — feasible & documented, not wired

✅ Store raw timestamped odds snapshots — `snapshots.py` (deterministic naming + `manifest.jsonl`).

*Client in `src/fpl_alpha/ingestion/odds.py` (The Odds API — sole provider; SportsGameOdds was dropped as its free tier paywalls EPL), throttled + credit-tracked via `cache.py` (`x-requests-*` headers → `data/raw/the-odds-api/_usage.json`); captured on a schedule by `scripts/snapshot_odds.py`.*

**Player props (researched 2026-08-21, not yet built — per decision to defer to step 5).** EPL per-player markets exist but only via the *event-specific* endpoint (`/v4/sports/soccer_epl/events/{eventId}/odds`), one fixture at a time, **US bookmakers only** (`regions=us`). The `/events` list call (for event IDs) is free; each event then costs `#markets × #regions` credits (anytime goalscorer over a 10-match slate ≈ 10 credits/snapshot). Keys: `player_goal_scorer_anytime`/`_first`/`_last`, `player_assists`, `player_shots`, `player_shots_on_target`, `player_to_receive_card`/`_red_card`. Full details in the `ingestion/odds.py` header comment.

### 3. No-Vig Market Probabilities — 🟡 partial [remaining: book weighting by sharpness]
Convert bookmaker odds into fair probabilities by:

- ✅ Removing bookmaker margin — `markets.devig_proportional` (proportional method)
- ✅ Combining multiple bookmakers — `markets.consensus`
- ✅ Handling outliers — per-outcome robust center (drop high+low quote → trimmed mean, median at n=3), then renormalize; one stray book no longer skews the fair prob
- 🟡 Book weighting — surviving books are still combined equally; sharpness weighting is the next upgrade

*Implemented in `src/fpl_alpha/markets.py`; tested in `tests/test_markets.py`.*

### 4. Market-Implied Team xG — ✅ done
Use match markets to estimate:

- ✅ Home expected goals
- ✅ Away expected goals
- ✅ Clean-sheet probabilities
- ✅ Score distributions

✅ Poisson-based baseline model (independent Poisson; fit by coordinate descent + golden-section, pure stdlib).

*Implemented in `src/fpl_alpha/team_xg.py`; tested in `tests/test_team_xg.py`; end-to-end demo `scripts/demo_market_to_xg.py`. Planned refinement (not blocking): Dixon–Coles low-score correction.*

### 5. Player Goal Probabilities — 🟡 partial [remaining: minutes weighting (step 7); player-prop source]
Use team xG and per-player shares to estimate:

- ✅ Player expected goals — `allocation.allocate_fixture` splits team λ by each player's season `expected_goals` share
- ✅ Share of team scoring — `PlayerFixtureAttack.goal_share`
- 🟡 Goal probability — derivable from `exp_goals` via Poisson (`1 − e^(−xG)`); not yet emitted as a field
- 🟡 Accuracy — shares are last-season totals (no minutes/rotation adjustment yet; new signings get ~0 share)

*Baseline built from **already-cached** bootstrap data (zero API spend), in `src/fpl_alpha/allocation.py`; tested in `tests/test_allocation.py`; runs end-to-end in `scripts/demo_epl_market_to_xg.py`. Player-prop markets (researched, see step 2) are an optional higher-accuracy source to layer in later.*

### 6. Player Assist Probabilities — 🟡 partial [remaining: minutes weighting; per-team assist ratio]
Estimate assists using:

- ✅ xA / chance creation — `allocation.allocate_fixture` splits a team assist budget by each player's season `expected_assists` share
- ✅ Team expected goals — assist budget = `team λ × ASSISTED_GOAL_FRACTION` (~0.75 of goals are assisted)
- 🟡 Player role — implicit via xA share only; no explicit role model
- ⬜ Assist markets — not wired (see step 2 player props)

*Shares the `allocation.py` implementation with step 5.*

### 7. Expected Minutes Model — ⬜ not started
Estimate:

- Start probability
- Expected minutes
- Early substitution risk
- Rotation risk

Allow manual overrides for injuries, press conferences, and tactical changes.

### 8. Deterministic Expected Points — ⬜ not started
Build an interpretable FPL xPts calculator using:

- Appearance
- Goals
- Assists
- Clean sheets
- Saves
- Defensive contributions
- Cards
- Bonus

This becomes the baseline model.

### 9. Monte Carlo Match Simulator — ⬜ not started
Simulate each match thousands of times and apply actual FPL scoring rules.

Output:

- Mean xPts
- Median
- Ceiling
- P(10+ points)
- P(15+ points)

### 10. Advanced Scoring Models — ⬜ not started
Improve:

- Defensive contributions
- Goalkeeper saves
- Cards
- Bonus points / BPS

### 11. Multi-Gameweek Projections — ⬜ not started
Generate player projections across:

- 1 GW
- 3 GWs
- 5 GWs
- Longer planning horizons

Account for fixture difficulty and uncertainty.

### 12. Squad & Transfer Optimizer — ⬜ not started
Use projected points to recommend:

- Starting XI
- Bench order
- Captain
- Transfers
- Points hits
- Multi-GW transfer plans

Later extend this to:

- Wildcard
- Free Hit
- Bench Boost
- Triple Captain

## Initial Focus

Start with Steps **1–4**:

1. ✅ FPL data
2. 🟡 Betting data (match odds live via The Odds API; player props researched, not wired)
3. 🟡 Fair market probabilities (core + outlier handling done; sharpness weighting remaining)
4. ✅ Market-implied team xG

The step 2→4 chain runs today on real cached EPL odds via `scripts/demo_epl_market_to_xg.py` (`the_odds_api_epl → parse_the_odds_api_events → markets.consensus → team_xg.fit_team_goals`); `scripts/demo_market_to_xg.py` still exercises the same chain on hardcoded example odds. A scheduled `snapshot_odds.py` refresh spends credits (tracked via `cache.read_usage`). Then move into player-level projections.

## High-Level Architecture

                        ┌─────────────────┐
                        │ Official FPL API│   ✅ ingested
                        └────────┬────────┘
                                 │
                                 │
┌─────────────────┐      ┌──────▼──────┐      ┌──────────────────┐
│ Football Stats  │─────▶│ Identity +  │◀─────│ Betting Markets  │
│                 │      │ Data Layer   │      │ 🟡 clients ready │
└─────────────────┘      └──────┬──────┘      └──────────────────┘
                          ✅ built
                                 │
                                 ▼
                      ┌─────────────────────┐
                      │ Probability Engine  │
                      │                     │
                      │ Team xG          ✅ │
                      │ Clean-sheet prob.✅ │
                      │ Goal probability 🟡 │
                      │ Assist probability🟡│
                      │ Expected minutes ⬜ │
                      │ Saves / cards    ⬜ │
                      │ DefCon           ⬜ │
                      └─────────┬───────────┘
                                │
                                ▼
                       ┌─────────────────┐
                       │ Match Simulator │   ⬜ not started
                       └────────┬────────┘
                                │
                                ▼
                       ┌─────────────────┐
                       │ FPL Scoring     │   ⬜ not started
                       │ Engine          │
                       └────────┬────────┘
                                │
                                ▼
                       ┌─────────────────┐
                       │ Player xPts     │   ⬜ not started
                       │ Distributions   │
                       └────────┬────────┘
                                │
                                ▼
                       ┌─────────────────┐
                       │ Squad / Transfer│   ⬜ not started
                       │ Optimizer       │
                       └─────────────────┘

Built so far: Official FPL API ingestion, the Identity + Data Layer, the
Team xG / clean-sheet portion of the Probability Engine, and the historical-shares
player allocator (team xG → per-player goal/assist probability).

## Repository Structure

The structure below was the *proposed* target. **As-built it is intentionally leaner** —
each stage starts as a single module and is promoted to a package only when it
needs more than one file, per the guidance at the bottom of this section. See
`README.md` / `CLAUDE.md` for the current tree. Notably, the deep `models/*` and
`markets/*` sub-packages are **not** created yet (steps 5+), and stages exist as
single modules: `markets.py`, `team_xg.py`, `allocation.py`, `identity.py`.

Proposed target:

fpl-alpha/
├── README.md
├── PROJECT_PLAN.md
├── AGENTS.md
├── pyproject.toml
├── .env.example
├── .gitignore
│
├── src/
│   └── fpl_alpha/
│       ├── ingestion/
│       │   ├── fpl/
│       │   ├── odds/
│       │   └── stats/
│       │
│       ├── identity/
│       │
│       ├── markets/
│       │   ├── normalization/
│       │   ├── no_vig/
│       │   └── consensus/
│       │
│       ├── models/
│       │   ├── team_goals/
│       │   ├── player_goals/
│       │   ├── assists/
│       │   ├── minutes/
│       │   ├── clean_sheets/
│       │   ├── saves/
│       │   ├── defcon/
│       │   └── bonus/
│       │
│       ├── simulation/
│       │
│       ├── scoring/
│       │
│       ├── projections/
│       │
│       ├── optimization/
│       │
│       └── evaluation/
│
├── tests/
│
├── notebooks/
│
├── scripts/
│
├── data/
│   ├── raw/
│   ├── processed/
│   └── snapshots/
│
└── docs/

This structure should evolve as the architecture becomes clearer.

Avoid creating abstractions purely to match this proposed structure.
