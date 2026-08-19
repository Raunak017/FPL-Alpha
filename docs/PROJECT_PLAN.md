# FPL Alpha — Project Plan

## Goal

Build a market-informed FPL projection and optimization engine that combines official FPL data, football statistics, betting markets, expected minutes, and simulation to estimate player expected points and recommend squad decisions.

## Roadmap

### 1. FPL Data Ingestion
Pull and normalize:

- Players
- Teams
- Fixtures
- Prices
- Positions
- FPL statistics
- Player history

Establish canonical player and team IDs.

### 2. Betting Odds Ingestion
Integrate an odds provider and collect:

- Match odds
- Goal totals
- BTTS
- Player goal props
- Assist props
- Shots
- Saves
- Cards

Store raw timestamped odds snapshots.

### 3. No-Vig Market Probabilities
Convert bookmaker odds into fair probabilities by:

- Removing bookmaker margin
- Combining multiple bookmakers
- Handling outliers and missing markets

### 4. Market-Implied Team xG
Use match markets to estimate:

- Home expected goals
- Away expected goals
- Clean-sheet probabilities
- Score distributions

Start with a Poisson-based model.

### 5. Player Goal Probabilities
Use anytime goalscorer markets and team xG to estimate:

- Goal probability
- Player expected goals
- Share of team scoring

### 6. Player Assist Probabilities
Estimate assists using:

- Assist markets
- xA / chance creation
- Player role
- Team expected goals

### 7. Expected Minutes Model
Estimate:

- Start probability
- Expected minutes
- Early substitution risk
- Rotation risk

Allow manual overrides for injuries, press conferences, and tactical changes.

### 8. Deterministic Expected Points
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

### 9. Monte Carlo Match Simulator
Simulate each match thousands of times and apply actual FPL scoring rules.

Output:

- Mean xPts
- Median
- Ceiling
- P(10+ points)
- P(15+ points)

### 10. Advanced Scoring Models
Improve:

- Defensive contributions
- Goalkeeper saves
- Cards
- Bonus points / BPS

### 11. Multi-Gameweek Projections
Generate player projections across:

- 1 GW
- 3 GWs
- 5 GWs
- Longer planning horizons

Account for fixture difficulty and uncertainty.

### 12. Squad & Transfer Optimizer
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

1. FPL data
2. Betting data
3. Fair market probabilities
4. Market-implied team xG

Once those are reliable, move into player-level projections.

## High-Level Architecture

                        ┌─────────────────┐
                        │ Official FPL API│
                        └────────┬────────┘
                                 │
                                 │
┌─────────────────┐      ┌──────▼──────┐      ┌──────────────────┐
│ Football Stats  │─────▶│ Identity +  │◀─────│ Betting Markets  │
│                 │      │ Data Layer   │      │                  │
└─────────────────┘      └──────┬──────┘      └──────────────────┘
                                 │
                                 ▼
                      ┌─────────────────────┐
                      │ Probability Engine  │
                      │                     │
                      │ Team xG             │
                      │ Clean-sheet prob.   │
                      │ Goal probability    │
                      │ Assist probability  │
                      │ Expected minutes    │
                      │ Saves / cards       │
                      │ DefCon              │
                      └─────────┬───────────┘
                                │
                                ▼
                       ┌─────────────────┐
                       │ Match Simulator │
                       └────────┬────────┘
                                │
                                ▼
                       ┌─────────────────┐
                       │ FPL Scoring     │
                       │ Engine          │
                       └────────┬────────┘
                                │
                                ▼
                       ┌─────────────────┐
                       │ Player xPts     │
                       │ Distributions   │
                       └────────┬────────┘
                                │
                                ▼
                       ┌─────────────────┐
                       │ Squad / Transfer│
                       │ Optimizer       │
                       └─────────────────┘

## Proposed Repository Structure

Initial structure:

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