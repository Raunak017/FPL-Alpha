# AGENTS.md — working conventions

Guidance for both developers and any AI coding agents on this repo. See
[`CLAUDE.md`](CLAUDE.md) for the authoritative data-access + rate-limit rules.

## Non-negotiables

1. **Cache-first, always.** Every external request goes through
   `fpl_alpha.cache.fetch`. Never call `urllib`/`requests` directly from a
   stage. Never add a polling loop against any API.
2. **Respect the budgets.** Rate limits live in `config.py` (`ProviderLimits`).
   Tighten them, never loosen. SportsGameOdds EPL is paywalled on the free tier;
   The Odds API bills `#markets × #regions` per call — request only what you use.
3. **Secrets only in `.env`** (gitignored). Never hardcode keys; never commit
   `data/`.
4. **No speculative abstractions.** Start each new stage as a single module;
   promote to a package only when it genuinely needs multiple files. Do not
   pre-create empty folders to match the plan's target tree.

## Pipeline & the data contract

The engine is a linear DAG. Each stage consumes the previous stage's output as
defined in `schemas.py` — build against those records, not raw dicts, so the two
stages can be developed in parallel.

```
ingestion → identity → markets → team_xg → models → simulation
          → scoring → projections → optimization → evaluation
```

## Rough ownership (steps 1–4)

| Area | Modules | Notes |
|------|---------|-------|
| Ingestion | `ingestion/fpl.py`, `ingestion/odds.py` | cache-first clients |
| Identity | `identity.py` | odds-name ↔ FPL-id matching is the hard part |
| Markets | `markets.py` | de-vig + consensus (math is unit-tested) |
| Team xG | `team_xg.py` | Poisson solver from match markets |

## Conventions

- Python ≥ 3.11, `from __future__ import annotations`, type hints on public fns.
- Keep ingestion stdlib-only; add deps per stage (see `pyproject.toml` comments).
- Tests for any non-trivial math (`tests/`). Run `pytest` before pushing.
- Timestamps are passed in explicitly (see `snapshots.py`) — never generated
  inline — so runs stay reproducible.
- Unresolved name matches must be logged, never silently dropped.
