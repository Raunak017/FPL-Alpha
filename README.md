# FPL Alpha

Market-informed Fantasy Premier League projection & optimization engine.
Turns bookmaker odds into fair probabilities, infers team scoring rates, and
derives per-player expected FPL points on top of official FPL data.

See [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md) for the full 12-step roadmap.
**Current focus: steps 1–4** (FPL data → odds → no-vig probabilities → team xG).

## ⚠️ Rate limits first

Free-tier odds budgets are tiny. **Every external call goes through
`fpl_alpha.cache.fetch`, which is cache-first and throttled** — dev work reads
`data/raw/`, snapshots are captured on a schedule, never in a loop. Never add an
API call that bypasses `cache.py`. Details in [`CLAUDE.md`](CLAUDE.md).

## Layout

```
src/fpl_alpha/
  config.py        env + paths + per-provider rate-limit budgets
  cache.py         cache-first, throttled HTTP gateway  (the one choke point)
  snapshots.py     timestamped odds/FPL captures + manifest
  schemas.py       typed data contracts between pipeline stages
  ingestion/       fpl.py · odds.py · stats.py           (steps 1–2)
  identity.py      canonical FPL ids + odds-name matching (identity layer)
  markets.py       de-vig + consensus                     (step 3)
  team_xg.py       market-implied Poisson team goals      (step 4)
  models/          player-level models                    (steps 5+, empty)
scripts/           refresh_fpl.py · snapshot_odds.py · demo_market_to_xg.py ·
                   demo_epl_market_to_xg.py · compare_ep_next.py
tests/             pytest
data/{raw,processed,snapshots}/   gitignored cache
```

Downstream stages (`simulation`, `scoring`, `projections`, `optimization`,
`evaluation`) are added when reached — the plan reserves the names.

## Scripts

| Script | What it does |
|--------|---------------|
| `refresh_fpl.py` | Refreshes the cached FPL core data (bootstrap + fixtures) and upserts teams/players/fixtures/snapshots/gameweek history into the local DB. Cache-first — does nothing over the wire if the cache is still fresh; pass `--force` to bypass the TTL. |
| `snapshot_odds.py --scope <name> --captured-at <iso8601>` | Captures a timestamped odds snapshot from The Odds API and writes it under `data/raw/snapshots/`. Run on a schedule (Mon/Wed/Fri/deadline-day), never in a loop — prints the credit cost (`#markets x #regions`) and the remaining budget after the call. |
| `demo_market_to_xg.py` | Fully offline demo of steps 3→4 (de-vig + consensus → Poisson team xG) using hardcoded example odds for one fixture — no odds API key needed. |
| `demo_epl_market_to_xg.py [--live]` | Same steps 2→4 chain but on the real EPL slate: parses the cached (or, with `--live`, freshly fetched) The Odds API snapshot, identity-matches team names to FPL ids, and prints team xG / clean-sheet probabilities / top attacking threats per fixture. Offline by default (0 credits); `--live` spends `#markets x #regions` credits. |
| `compare_ep_next.py` | Offline sanity check: runs the full cached pipeline (odds → team λ → availability-gated allocation) to compute a **partial** xPts per player and compares it against FPL's own `ep_next`, printing top-20 tables, a per-position mean breakdown, and Pearson/Spearman correlations. Deliberately missing bonus, defensive contribution, saves, and goals-conceded penalty — read as a directional/rank check, not a precision benchmark. |

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # add keys / team ids as available

python scripts/refresh_fpl.py      # cache FPL bootstrap + fixtures
python scripts/demo_market_to_xg.py # odds -> fair probs -> team xG (offline demo)
python scripts/demo_epl_market_to_xg.py  # same chain on the real EPL slate (offline)
python scripts/compare_ep_next.py  # partial xPts vs FPL's ep_next (offline sanity check)
python scripts/snapshot_odds.py --scope epl-gw1 \
    --captured-at 2026-08-21T17:30:00Z          # scheduled odds snapshot (spends credits)
pytest                             # runs the unit tests
```

## Developers

- **dev1 — Rushi Pardeshi.** FPL Team ID `432989`. Owns the The Odds API key.
- **dev2 — TBD.** Add their Team ID to `.env` as `FPL_TEAM_ID_DEV2`.

Working conventions and module ownership live in [`AGENTS.md`](AGENTS.md).
