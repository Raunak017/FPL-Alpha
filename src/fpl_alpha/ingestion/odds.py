"""Betting-odds client (Plan step 2). The Odds API — the live EPL source.

⚠️ Rate limits are the tightest constraint in this repo (see CLAUDE.md):
  - The Odds API bills credits = #markets x #regions per call (x10 for
    historical). The ~500-credit/mo free tier is easy to blow through.
All calls go through cache.fetch (throttled + credit-tracked via the
``x-requests-*`` response headers). For scheduled captures, wrap the return
value with snapshots.write_snapshot so line movement is recoverable.

Status (verified 2026-08-21):
  - `soccer_epl` works and returns decimal odds. `the_odds_api_epl` +
    `parse_the_odds_api_events` feed the market -> team_xg chain (see
    scripts/demo_epl_market_to_xg.py).
  - (SportsGameOdds was dropped: EPL is paywalled on its free tier.)

--- Player props: FEASIBLE, not yet built (research 2026-08-21) --------------
Per-player markets exist for EPL but come with real constraints, so they are
documented here rather than wired up (build alongside Plan step 5):

  - Endpoint: the featured /odds endpoint above does NOT carry player props.
    They live on the *event-specific* endpoint, one fixture at a time:
        GET /v4/sports/soccer_epl/events/{eventId}/odds?regions=us&markets=...
    Get {eventId}s first from GET /v4/sports/soccer_epl/events (that list call
    is FREE — no credits), then spend per event.
  - Region: soccer player props are US-bookmakers-only right now (regions=us).
  - Market keys: player_goal_scorer_anytime / _first / _last, player_assists,
    player_shots, player_shots_on_target, player_to_receive_card / _red_card.
  - Cost: credits = #markets x #regions, charged *per event*. Anytime
    goalscorer across a 10-match slate = ~10 credits/snapshot from the ~500/mo
    budget — a couple of snapshots per GW at most.
  - Consolidation reuses markets.consensus: anytime-goalscorer is a per-player
    yes/no pair, de-vigged then combined across the (few) US books exactly like
    a 2-outcome h2h. Names resolve to FPL ids via identity.match_odds_name.
"""
from __future__ import annotations

import urllib.parse
from collections import Counter
from typing import Any

from ..cache import fetch
from ..config import ODDS_API_KEY, THE_ODDS_API
from ..schemas import FixtureOdds


def the_odds_api_epl(
    markets: str = "h2h,totals",
    regions: str = "uk,eu",
    force: bool = False,
) -> list[dict[str, Any]]:
    """EPL odds from The Odds API. Cost = len(markets) x len(regions) credits —
    request only what a downstream stage actually consumes."""
    if not ODDS_API_KEY:
        raise RuntimeError("ODDS_API_KEY not set")
    q = urllib.parse.urlencode(
        {"apiKey": ODDS_API_KEY, "regions": regions, "markets": markets, "oddsFormat": "decimal"}
    )
    path = f"/sports/soccer_epl/odds/?{q}"
    key = f"theoddsapi-epl-{markets.replace(',', '+')}-{regions.replace(',', '+')}"
    return fetch(THE_ODDS_API, path, key=key, force=force)


# --- Parsers: provider JSON -> normalized FixtureOdds -----------------------
def _modal_total_line(bookmakers: list[dict[str, Any]]) -> float | None:
    """The most-quoted totals line across books (the 'main' line, e.g. 2.5).

    Books post totals at different lines; consensus must combine a single,
    coherent line. Tie-break toward the lower line so we don't drift to a
    high-scoring alternate quoted by only a couple of books.
    """
    counts: Counter[float] = Counter()
    for bk in bookmakers:
        for m in bk.get("markets", []):
            if m.get("key") == "totals":
                for o in m.get("outcomes", []):
                    pt = o.get("point")
                    if pt is not None:
                        counts[float(pt)] += 1
    if not counts:
        return None
    top = max(counts.values())
    return min(line for line, c in counts.items() if c == top)


def parse_the_odds_api_events(events: list[dict[str, Any]]) -> list[FixtureOdds]:
    """Turn The Odds API ``/odds`` payload into normalized :class:`FixtureOdds`.

    Aligns each book's decimal prices into fixed outcome order — h2h as
    [home, draw, away], totals as [over, under] at the modal line — skipping
    any book that doesn't quote the full set for a market (so consensus never
    sees a half-populated row). A book quoting only some markets contributes to
    the ones it does quote.
    """
    out: list[FixtureOdds] = []
    for ev in events:
        home, away = ev.get("home_team"), ev.get("away_team")
        books = ev.get("bookmakers", [])
        line = _modal_total_line(books)

        h2h_rows: list[list[float]] = []
        totals_rows: list[list[float]] = []
        for bk in books:
            markets = {m.get("key"): m for m in bk.get("markets", [])}

            h2h = markets.get("h2h")
            if h2h:
                prices = {o.get("name"): o.get("price") for o in h2h.get("outcomes", [])}
                row = [prices.get(home), prices.get("Draw"), prices.get(away)]
                if all(isinstance(p, (int, float)) for p in row):
                    h2h_rows.append([float(p) for p in row])

            tot = markets.get("totals")
            if tot and line is not None:
                over = under = None
                for o in tot.get("outcomes", []):
                    if o.get("point") is not None and float(o["point"]) == line:
                        if o.get("name") == "Over":
                            over = o.get("price")
                        elif o.get("name") == "Under":
                            under = o.get("price")
                if isinstance(over, (int, float)) and isinstance(under, (int, float)):
                    totals_rows.append([float(over), float(under)])

        out.append(
            FixtureOdds(
                source="the-odds-api",
                event_id=str(ev.get("id", "")),
                commence_time=str(ev.get("commence_time", "")),
                home_team=str(home),
                away_team=str(away),
                h2h=h2h_rows,
                totals=totals_rows,
                totals_line=line if totals_rows else None,
            )
        )
    return out
