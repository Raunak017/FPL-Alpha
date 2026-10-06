# FPL Alpha — Project Plan

## Goal

Build a market-informed FPL projection and optimization engine that combines official FPL data, football statistics, betting markets, expected minutes, and simulation to estimate player expected points and recommend squad decisions.

## Status (as of 2026-10-06)

Steps **1–4** are code-complete. The live DuckDB consensus-to-team-xG bridge
persists timestamped model snapshots and market comparisons, including an
automated batch builder for mapped upcoming fixtures. Player-level work (steps
5+) has not started.

**Legend:** ✅ done · 🟡 partial (see `[remaining: …]` in the heading) · ⬜ not started

| Step | Status |
|------|--------|
| 1. FPL Data Ingestion | ✅ done |
| 2. Betting Odds Ingestion | ✅ done |
| 3. No-Vig Market Probabilities | ✅ done |
| 4. Market-Implied Team xG | ✅ done |
| 5–12 (player projections → optimizer) | ⬜ not started |

## Roadmap

### 1. FPL Data Ingestion — ✅ done
Pull and normalize:

- ✅ Players — `identity.players_from_bootstrap`
- ✅ Teams — `identity.teams_from_bootstrap`
- ✅ Fixtures — `ingestion.fpl.fixtures`
- ✅ Prices, ownership, status, transfers, season stats, xG/xA/xGI/xGC, per-90, and ICT — timestamped `PlayerSnapshot` records
- ✅ Positions — `element_type` → GKP/DEF/MID/FWD
- ✅ Current-season player fixture history — `PlayerGameweekHistory`, keyed by `(player_fpl_id, fixture_fpl_id)`
- ✅ DuckDB persistence — `data/fpl_alpha.duckdb`, with atomic refresh transactions for `teams`, `players`, `fixtures`, `player_snapshots`, and `player_gameweek_history`

✅ Canonical player and team IDs established (FPL is the source of truth).

*Implemented in `src/fpl_alpha/ingestion/fpl.py`, `identity.py`, and `storage.py`; run via `scripts/refresh_fpl.py`; all API calls are cache-first through `cache.py`.*

#### Populate the local FPL database

Run the normal refresh after installing the project dependencies:

```bash
python scripts/refresh_fpl.py
```

This creates or updates `data/fpl_alpha.duckdb`. It fetches stale/missing
`bootstrap-static` and fixture data, then stores canonical teams/players,
fixtures, and a timestamped player snapshot. The snapshot timestamp is the
local bootstrap cache write time, not an FPL-provided timestamp.

For player fixture history, the refresh processes only gameweeks whose bootstrap
event has both `finished=true` and `data_checked=true`. Each such gameweek is
read once from `/event/{gw}/live/` and marked ingested transactionally, so later
refreshes do not repeat that request. Team fixture schedules identify blanks,
single-fixture gameweeks, and double gameweeks; only double-gameweek players use
the cache-first `/element-summary/{player}/` fallback for per-fixture stats.

Before the first finalized gameweek, expect `player_gameweek_history` to be
empty. The official API does not provide a bulk prior-season fixture-history
endpoint; pre-season bootstrap data can still contain prior-season aggregate
stats in `player_snapshots`.

Inspect stored table sizes with:

```bash
python - <<'PY'
import duckdb

connection = duckdb.connect("data/fpl_alpha.duckdb", read_only=True)
for table in (
    "teams", "players", "fixtures", "player_snapshots",
    "player_gameweek_history",
):
    print(table, connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
connection.close()
PY
```

### 2. Betting Odds Ingestion — ✅ done
Integrate an odds provider and collect:

- ✅ Match odds (h2h)
- ✅ Goal totals
- ✅ Both teams to score
- ✅ Anytime goalscorer props
- ✅ Player assist props

✅ Raw PropLine event responses remain cache-first under `data/raw/propline/`.

✅ Normalized DuckDB persistence for provider events, FPL fixture mappings,
bookmakers, append-only outcome snapshots, and auditable player mappings.

*PropLine is implemented in `src/fpl_alpha/ingestion/odds.py` and captured
cache-first with `scripts/refresh_propline_odds.py`. Events map to FPL fixtures
by home team, away team, and kickoff; player props are fixture-team-scoped and
use explicit aliases or strict normalization, leaving unresolved labels `NULL`.*

Legacy SportsGameOdds and The Odds API clients have been removed; PropLine is
the sole odds source and uses `PROPLINE_API_KEY`.

#### Refresh all mapped upcoming PropLine fixtures

```bash
PYTHONPATH=src python scripts/refresh_upcoming_propline_odds.py
```

The command first performs the normal cache-first FPL refresh, discovers current
PropLine EPL events, strictly maps them to future FPL fixtures, then captures all
supported markets in one DuckDB transaction. Use `--gameweek <N>` to narrow the
scope or `--force` to bypass only the PropLine cache TTL.

### 3. No-Vig Market Probabilities — ✅ done
Convert bookmaker odds into fair probabilities by:

- ✅ Removing bookmaker margin — `markets.devig_proportional` (proportional method)
- ✅ Combining multiple bookmakers — `markets.consensus` (equal-weighted average)
- ✅ Reading latest complete DuckDB bookmaker snapshots — `markets.consensus_from_latest_odds`
- ✅ Rejecting material cross-book outliers — per-market robust MAD rule on de-vigged logit probabilities; fewer than three complete books are retained
- ✅ Equal bookmaker weighting — the V1 policy; evidence-based sharpness weighting is deferred until settled-price calibration data exists

*The current bridge supports h2h, BTTS, and the match-total line nearest 2.5;
incomplete books and team totals are excluded. Run it with
`python scripts/build_market_consensus.py --fixture-id <fpl_fixture_id>`.*

### 4. Market-Implied Team xG — ✅ done
Use match markets to estimate:

- ✅ Home expected goals
- ✅ Away expected goals
- ✅ Clean-sheet probabilities
- ✅ Score distributions

✅ Poisson-based baseline model (independent Poisson; fit by coordinate descent + golden-section, pure stdlib).

*Implemented in `src/fpl_alpha/team_xg.py`. `scripts/build_team_xg.py --fixture-id <fpl_fixture_id>` reads the latest DuckDB market consensus, fits team xG, and persists `team_goal_model_snapshots` plus market-vs-model comparisons. Planned refinement (not blocking): Dixon–Coles low-score correction.*

Build every mapped upcoming fixture with stored PropLine odds using:

```bash
PYTHONPATH=src python scripts/build_upcoming_team_xg.py
```

It prints each fixture with a complete consensus and persisted team-xG projection,
plus fixtures skipped because their latest bookmaker odds are incomplete.

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
2. ✅ Betting data (PropLine live ingestion and DuckDB persistence)
3. ✅ Fair market probabilities
4. ✅ Market-implied team xG

The live Step 3→4 chain runs via `scripts/build_team_xg.py --fixture-id <fpl_fixture_id>`; the offline demo remains available for illustration. Then move into player-level projections.

## High-Level Architecture

                        ┌─────────────────┐
                        │ Official FPL API│   ✅ ingested
                        └────────┬────────┘
                                 │
                                 │
┌─────────────────┐      ┌──────▼──────┐      ┌──────────────────┐
│ Football Stats  │─────▶│ Identity +  │◀─────│ Betting Markets  │
│                 │      │ Data Layer   │      │ ✅ PropLine ingested │
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
