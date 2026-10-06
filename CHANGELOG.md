# Changelog

Notable user-visible features, persistence changes, and operational workflow
updates. Add an entry here before committing related work.

## 2026-10-06 — `2a43a99`

### Added

- Persisted live team-xG projections, clean-sheet probabilities, fit loss, and
  market-vs-model comparisons in DuckDB.
- `build_team_xg.py` for one fixture and `build_upcoming_team_xg.py` for every
  mapped future fixture with stored odds.
- Automatic cache-first PropLine ingestion for all strictly mapped upcoming EPL
  fixtures via `refresh_upcoming_propline_odds.py`.
- Reusable FPL refresh workflow, strict provider-to-FPL fixture matching, and
  explicit team/player identity aliases.
- `docs/DATA_INGESTION.md` with the normal FPL, odds, consensus, and team-xG
  command sequence.
- `uv.lock` for reproducible dependency resolution.

### Changed

- FPL and PropLine raw-response caches now use 24-hour TTLs.
- The project plan now records completed Steps 1–4 and the batch team-xG flow.

### Removed

- Legacy SportsGameOdds and The Odds API clients, configuration, keys, and
  snapshot command. PropLine is the sole odds provider.
