"""Betting-odds clients (Plan step 2). SportsGameOdds + The Odds API.

⚠️ Rate limits are the tightest constraint in this repo (see CLAUDE.md):
  - SportsGameOdds free tier does NOT include EPL and bills per match-object.
  - The Odds API bills credits = #markets x #regions per call.
Both go through cache.fetch (throttled). For scheduled captures, wrap the return
value with snapshots.write_snapshot so line movement is recoverable.

Status: signatures scaffolded; wire up once an EPL-capable key is available.
"""
from __future__ import annotations

import urllib.parse
from typing import Any

from ..cache import fetch
from ..config import ODDS_API_KEY, SPORTSGAMEODDS, SPORTSGAMEODDS_API_KEY, THE_ODDS_API


def sportsgameodds_events(
    league_id: str = "EPL", limit: int = 10, force: bool = False
) -> dict[str, Any]:
    """Fetch events+odds for a league. Raises on the free-tier EPL paywall
    (HTTP 400 'unavailable at your current subscription tier')."""
    if not SPORTSGAMEODDS_API_KEY:
        raise RuntimeError("SPORTSGAMEODDS_API_KEY not set")
    path = f"/events/?leagueID={league_id}&oddsAvailable=true&limit={limit}"
    return fetch(
        SPORTSGAMEODDS,
        path,
        key=f"sgo-events-{league_id}-{limit}",
        headers={"X-Api-Key": SPORTSGAMEODDS_API_KEY},
        force=force,
    )


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
