# FPL Alpha — Project Plan

## Goal

Build a market-informed FPL projection and optimization engine that combines official FPL data, football statistics, betting markets, expected minutes, and simulation to estimate player expected points and recommend squad decisions.

## Status (as of 2026-08-20)

Steps **1–4** (the initial focus) are code-complete and unit-tested end-to-end
**offline**; the one external gap is a live, EPL-capable odds key. Player-level
work (steps 5+) has not started.

**Legend:** ✅ done · 🟡 partial (see `[remaining: …]` in the heading) · ⬜ not started

| Step | Status |
|------|--------|
| 1. FPL Data Ingestion | 🟡 partial |
| 2. Betting Odds Ingestion | 🟡 partial |
| 3. No-Vig Market Probabilities | 🟡 partial |
| 4. Market-Implied Team xG | ✅ done |
| 5–12 (player projections → optimizer) | ⬜ not started |

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

### 2. Betting Odds Ingestion — 🟡 partial [remaining: EPL-capable API key; BTTS + player props / shots / saves / cards markets]
Integrate an odds provider and collect:

- ✅ Match odds (h2h) — client wired
- ✅ Goal totals — client wired
- ⬜ BTTS
- ⬜ Player goal props
- ⬜ Assist props
- ⬜ Shots
- ⬜ Saves
- ⬜ Cards

✅ Store raw timestamped odds snapshots — `snapshots.py` (deterministic naming + `manifest.jsonl`).

*Clients in `src/fpl_alpha/ingestion/odds.py` (SportsGameOdds + The Odds API), throttled via `cache.py`; captured on a schedule by `scripts/snapshot_odds.py`. **Blocked live:** SGO EPL is paywalled on the free tier and `ODDS_API_KEY` is unset, so only cached/example data flows today.*

### 3. No-Vig Market Probabilities — 🟡 partial [remaining: outlier handling + book weighting]
Convert bookmaker odds into fair probabilities by:

- ✅ Removing bookmaker margin — `markets.devig_proportional` (proportional method)
- ✅ Combining multiple bookmakers — `markets.consensus` (equal-weighted average)
- 🟡 Handling outliers and missing markets — consensus averages equally for now; no outlier rejection / sharpness weighting yet

*Implemented in `src/fpl_alpha/markets.py`; tested in `tests/test_markets.py`.*

### 4. Market-Implied Team xG — ✅ done
Use match markets to estimate:

- ✅ Home expected goals
- ✅ Away expected goals
- ✅ Clean-sheet probabilities
- ✅ Score distributions

✅ Poisson-based baseline model (independent Poisson; fit by coordinate descent + golden-section, pure stdlib).

*Implemented in `src/fpl_alpha/team_xg.py`; tested in `tests/test_team_xg.py`; end-to-end demo `scripts/demo_market_to_xg.py`. Planned refinement (not blocking): Dixon–Coles low-score correction.*

### 5. Player Goal Probabilities — ⬜ not started
Use anytime goalscorer markets and team xG to estimate:

- Goal probability
- Player expected goals
- Share of team scoring

*Depends on step 2 player-prop markets (needs the odds key).*

### 6. Player Assist Probabilities — ⬜ not started
Estimate assists using:

- Assist markets
- xA / chance creation
- Player role
- Team expected goals

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
2. 🟡 Betting data (infrastructure done; blocked on an EPL-capable odds key)
3. 🟡 Fair market probabilities (core done; outlier handling remaining)
4. ✅ Market-implied team xG

The step 3→4 chain runs today via `scripts/demo_market_to_xg.py` (offline example odds). Once a live odds feed is wired, `snapshot_odds.py → markets.consensus → team_xg.fit_team_goals` runs on real fixtures with no code changes. Then move into player-level projections.

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
                      │ Goal probability ⬜ │
                      │ Assist probability⬜│
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

Built so far: Official FPL API ingestion, the Identity + Data Layer, and the
Team xG / clean-sheet portion of the Probability Engine.

## Repository Structure

The structure below was the *proposed* target. **As-built it is intentionally leaner** —
each stage starts as a single module and is promoted to a package only when it
needs more than one file, per the guidance at the bottom of this section. See
`README.md` / `CLAUDE.md` for the current tree. Notably, the deep `models/*` and
`markets/*` sub-packages are **not** created yet (steps 5+), and stages exist as
single modules: `markets.py`, `team_xg.py`, `identity.py`.

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
