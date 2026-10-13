"""Cache-first PropLine EPL odds ingestion (Plan step 2)."""
from __future__ import annotations

import urllib.parse
from datetime import datetime
from typing import Any, Iterable

from ..cache import fetch
from ..config import PROPLINE, PROPLINE_API_KEY
from ..identity import match_odds_name_strict, normalize_odds_name
from ..schemas import (
    Fixture,
    OddsBookmaker,
    OddsEventFixtureMapping,
    OddsOutcomeSnapshot,
    OddsPlayerMapping,
    OddsProviderEvent,
    Player,
    Team,
)

PROPLINE_EPL_MARKETS = (
    "h2h",
    "totals",
    "both_teams_to_score",
    "anytime_goal_scorer",
    "player_assists",
)
PROPLINE_PLAYER_PROP_MARKETS = {"anytime_goal_scorer", "player_assists"}
# Provider spelling -> (FPL player ID, required FPL team ID). Keep aliases
# narrow and fixture-scoped; unmatched labels are safer than guessed matches.
_PROPLINE_PLAYER_ALIASES = {
    "ben white": (10, 1),
    "ephron mason clarke": (186, 7),
    "ferdi kadioglu": (113, 5),
    "jair": (474, 18),
    "kaine kessler": (177, 7),
    "savinho": (403, 19),
    "yegor yarmolyuk": (102, 4),
    "yehor yarmolyuk": (102, 4),
    "calvin ramsey": (365, 14),
}


def propline_epl_events(force: bool = False) -> list[dict[str, Any]]:
    """List upcoming EPL events from PropLine, cache-first."""
    _require_propline_key()
    path = "/sports/soccer_epl/events?" + urllib.parse.urlencode(
        {"apiKey": PROPLINE_API_KEY}
    )
    return fetch(
        PROPLINE,
        path,
        key="propline-epl-events",
        force=force,
    )


def propline_epl_event_markets(event_id: str, force: bool = False) -> dict[str, Any]:
    """List markets available for one EPL event, cache-first."""
    _require_propline_key()
    path = f"/sports/soccer_epl/events/{event_id}/markets?" + urllib.parse.urlencode(
        {"apiKey": PROPLINE_API_KEY}
    )
    return fetch(
        PROPLINE,
        path,
        key=f"propline-epl-event-{event_id}-markets",
        force=force,
    )


def propline_epl_event_odds(
    event_id: str,
    markets: tuple[str, ...] = PROPLINE_EPL_MARKETS,
    force: bool = False,
) -> dict[str, Any]:
    """Fetch selected match markets and player props for one EPL event."""
    _require_propline_key()
    market_csv = ",".join(markets)
    path = (
        f"/sports/soccer_epl/events/{event_id}/odds?"
        + urllib.parse.urlencode({"apiKey": PROPLINE_API_KEY, "markets": market_csv})
    )
    return fetch(
        PROPLINE,
        path,
        key=propline_epl_event_odds_cache_key(event_id, markets),
        force=force,
    )


def propline_epl_event_odds_cache_key(event_id: str, markets: tuple[str, ...]) -> str:
    """Return the raw-cache key for a selected PropLine event response."""
    return f"propline-epl-event-{event_id}-{'-'.join(markets)}"


def propline_event_from_payload(payload: dict[str, Any]) -> OddsProviderEvent:
    """Normalize one PropLine event-list or odds-response identity."""
    return OddsProviderEvent(
        provider_key="propline",
        provider_event_id=str(payload["id"]),
        sport_key=payload["sport_key"],
        home_team=payload["home_team"],
        away_team=payload["away_team"],
        commence_time=payload["commence_time"],
    )


def normalize_propline_event_odds(
    payload: dict[str, Any],
    teams: list[Team],
    players: list[Player],
    fixtures: list[Fixture],
    captured_at: datetime,
) -> tuple[
    OddsProviderEvent,
    OddsEventFixtureMapping,
    list[OddsPlayerMapping],
    list[OddsBookmaker],
    list[OddsOutcomeSnapshot],
]:
    """Normalize one PropLine event response and map it to an FPL fixture."""
    event = propline_event_from_payload(payload)
    fixture = map_propline_event_to_fixture(event, teams, fixtures)
    mapping = OddsEventFixtureMapping(
        provider_key=event.provider_key,
        provider_event_id=event.provider_event_id,
        fpl_fixture_id=fixture.fpl_id if fixture is not None else None,
        match_method="home_away_kickoff_exact" if fixture is not None else "unmapped",
    )

    player_mappings: dict[str, OddsPlayerMapping] = {}
    bookmakers: list[OddsBookmaker] = []
    snapshots: list[OddsOutcomeSnapshot] = []
    for bookmaker in payload.get("bookmakers", []):
        bookmakers.append(
            OddsBookmaker(
                provider_key=event.provider_key,
                bookmaker_key=bookmaker["key"],
                title=bookmaker["title"],
            )
        )
        for market_ordinal, market in enumerate(bookmaker.get("markets", [])):
            for outcome_ordinal, outcome in enumerate(market.get("outcomes", [])):
                selection_description = outcome.get("description")
                player_mapping = _map_player_prop(
                    event, fixture, players, market, outcome
                )
                if player_mapping is not None:
                    player_mappings.setdefault(
                        player_mapping.selection_description, player_mapping
                    )
                snapshots.append(
                    OddsOutcomeSnapshot(
                        provider_key=event.provider_key,
                        provider_event_id=event.provider_event_id,
                        bookmaker_key=bookmaker["key"],
                        market_key=market["key"],
                        market_ordinal=market_ordinal,
                        market_description=market.get("description"),
                        market_team=market.get("team"),
                        outcome_ordinal=outcome_ordinal,
                        selection_description=selection_description,
                        fpl_player_id=(
                            player_mapping.fpl_player_id if player_mapping is not None else None
                        ),
                        outcome_name=outcome["name"],
                        american_price=outcome["price"],
                        point=outcome.get("point"),
                        last_update=market.get("last_update"),
                        last_change_at=outcome.get("last_change_at"),
                        captured_at=captured_at,
                    )
                )
    return event, mapping, list(player_mappings.values()), bookmakers, snapshots


def map_propline_event_to_fixture(
    event: OddsProviderEvent, teams: list[Team], fixtures: list[Fixture]
) -> Fixture | None:
    home_match = match_odds_name_strict(event.home_team, teams)
    away_match = match_odds_name_strict(event.away_team, teams)
    if home_match is None or away_match is None:
        return None
    home, _ = home_match
    away, _ = away_match
    if not isinstance(home, Team) or not isinstance(away, Team):
        return None

    matches = [
        fixture
        for fixture in fixtures
        if fixture.team_h_fpl_id == home.fpl_id
        and fixture.team_a_fpl_id == away.fpl_id
        and _same_time(fixture.kickoff_time, event.commence_time)
    ]
    return matches[0] if len(matches) == 1 else None


def mapped_upcoming_propline_events(
    payloads: Iterable[dict[str, Any]],
    teams: list[Team],
    fixtures: list[Fixture],
    now: datetime,
    gameweek: int | None = None,
) -> tuple[list[tuple[OddsProviderEvent, Fixture]], list[OddsProviderEvent], list[OddsProviderEvent]]:
    """Strictly classify current provider events against upcoming FPL fixtures."""
    selected: list[tuple[OddsProviderEvent, Fixture]] = []
    unmapped: list[OddsProviderEvent] = []
    skipped: list[OddsProviderEvent] = []
    for payload in payloads:
        event = propline_event_from_payload(payload)
        fixture = map_propline_event_to_fixture(event, teams, fixtures)
        if fixture is None:
            unmapped.append(event)
        elif gameweek is not None and fixture.event != gameweek:
            continue
        elif (
            fixture.finished
            or fixture.kickoff_time is None
            or _parse_time(fixture.kickoff_time) <= now
        ):
            skipped.append(event)
        else:
            selected.append((event, fixture))
    return selected, unmapped, skipped


def _map_player_prop(
    event: OddsProviderEvent,
    fixture: Fixture | None,
    players: list[Player],
    market: dict[str, Any],
    outcome: dict[str, Any],
) -> OddsPlayerMapping | None:
    if market.get("key") not in PROPLINE_PLAYER_PROP_MARKETS:
        return None

    selection = _player_selection(market, outcome)
    if selection is None:
        return None
    if fixture is None:
        return OddsPlayerMapping(
            event.provider_key, event.provider_event_id, selection, None, "event_unmapped"
        )

    fixture_players = [
        player
        for player in players
        if player.team_fpl_id in {fixture.team_h_fpl_id, fixture.team_a_fpl_id}
    ]
    resolved = _match_propline_player_alias(selection, fixture, fixture_players)
    if resolved is None:
        resolved = match_odds_name_strict(selection, fixture_players)
    fpl_player_id = (
        resolved[0].fpl_id
        if resolved is not None and isinstance(resolved[0], Player)
        else None
    )
    return OddsPlayerMapping(
        provider_key=event.provider_key,
        provider_event_id=event.provider_event_id,
        selection_description=selection,
        fpl_player_id=fpl_player_id,
        match_method=resolved[1] if resolved is not None else "unmatched",
    )


def _match_propline_player_alias(
    selection: str, fixture: Fixture, fixture_players: list[Player]
) -> tuple[Player, str] | None:
    alias = _PROPLINE_PLAYER_ALIASES.get(normalize_odds_name(selection))
    if alias is None:
        return None
    player_fpl_id, required_team_fpl_id = alias
    if required_team_fpl_id not in {fixture.team_h_fpl_id, fixture.team_a_fpl_id}:
        return None
    matches = [
        player
        for player in fixture_players
        if player.fpl_id == player_fpl_id and player.team_fpl_id == required_team_fpl_id
    ]
    return (matches[0], "explicit_alias") if len(matches) == 1 else None


def _player_selection(market: dict[str, Any], outcome: dict[str, Any]) -> str | None:
    description = outcome.get("description")
    if isinstance(description, str) and description.strip():
        selection = description.strip()
        return None if selection.casefold() in {"no goalscorer", "no goal scorer"} else selection
    name = outcome.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    if name.casefold().strip() in {"yes", "no", "over", "under"}:
        return None
    return name.strip()


def _same_time(left: str | None, right: str) -> bool:
    if left is None:
        return False
    return _parse_time(left) == _parse_time(right)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _require_propline_key() -> None:
    if not PROPLINE_API_KEY:
        raise RuntimeError("PROPLINE_API_KEY not set")
