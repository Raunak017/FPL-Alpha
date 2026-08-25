# FPL Alpha — Project Plan

## Goal

Build a market-informed FPL projection and optimization engine that combines official FPL data, football statistics, betting markets, expected minutes, and simulation to estimate player expected points and recommend squad decisions.

## Status (as of 2026-08-25)

Steps **1, 2, and 4** are code-complete; Step 3 has its core methods but still
needs outlier handling and bookmaker weighting. PropLine live capture has been
validated on EPL events. Player-level work (steps 5+) has not started.

**Legend:** ✅ done · 🟡 partial (see `[remaining: …]` in the heading) · ⬜ not started

| Step | Status |
|------|--------|
| 1. FPL Data Ingestion | ✅ done |
| 2. Betting Odds Ingestion | ✅ done |
| 3. No-Vig Market Probabilities | 🟡 partial |
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
2. ✅ Betting data (PropLine live ingestion and DuckDB persistence)
3. 🟡 Fair market probabilities (core done; outlier handling remaining)
4. ✅ Market-implied team xG

The step 3→4 chain runs today via `scripts/demo_market_to_xg.py` (offline example odds). PropLine now supplies live cached and persisted odds; connecting those DuckDB snapshots to the consensus and team-xG stages is separate follow-on work. Then move into player-level projections.

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
