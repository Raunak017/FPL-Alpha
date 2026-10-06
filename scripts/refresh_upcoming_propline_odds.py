#!/usr/bin/env python3
"""Capture all mapped upcoming PropLine EPL fixtures into DuckDB."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from fpl_alpha.config import RAW
from fpl_alpha.ingestion import odds
from fpl_alpha.ingestion.refresh import refresh_fpl_database
from fpl_alpha.schemas import OddsProviderEvent
from fpl_alpha.storage import (
    insert_odds_outcome_snapshots,
    load_fixtures,
    load_players,
    load_teams,
    open_database,
    upsert_odds_bookmakers,
    upsert_odds_event_fixture_mappings,
    upsert_odds_player_mappings,
    upsert_odds_provider_events,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gameweek", type=int, help="restrict to one FPL gameweek")
    parser.add_argument(
        "--markets",
        default=",".join(odds.PROPLINE_EPL_MARKETS),
        help="comma-separated PropLine market keys",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="ignore the PropLine cache TTL; FPL remains cache-first",
    )
    args = parser.parse_args()

    fpl_result = refresh_fpl_database()
    markets = tuple(market for market in args.markets.split(",") if market)
    now = datetime.now(timezone.utc)

    connection = open_database()
    try:
        teams = load_teams(connection)
        players = load_players(connection)
        fixtures = load_fixtures(connection)
        event_payloads = odds.propline_epl_events(force=args.force)

        selected, unmapped, skipped = odds.mapped_upcoming_propline_events(
            event_payloads, teams, fixtures, now, args.gameweek
        )

        normalized = []
        for event, _ in selected:
            event_id = event.provider_event_id
            payload = odds.propline_epl_event_odds(event_id, markets, force=args.force)
            cache_key = odds.propline_epl_event_odds_cache_key(event_id, markets)
            cache_file = RAW / "propline" / f"{cache_key}.json"
            captured_at = datetime.fromtimestamp(cache_file.stat().st_mtime, tz=timezone.utc)
            normalized.append(
                odds.normalize_propline_event_odds(
                    payload, teams, players, fixtures, captured_at
                )
            )

        if normalized:
            events, mappings, player_mappings, bookmakers, snapshots = zip(*normalized)
            connection.execute("BEGIN TRANSACTION")
            try:
                upsert_odds_provider_events(connection, events)
                upsert_odds_event_fixture_mappings(connection, mappings)
                upsert_odds_player_mappings(
                    connection, (mapping for group in player_mappings for mapping in group)
                )
                upsert_odds_bookmakers(
                    connection, (bookmaker for group in bookmakers for bookmaker in group)
                )
                insert_odds_outcome_snapshots(
                    connection, (snapshot for group in snapshots for snapshot in group)
                )
            except Exception:
                connection.execute("ROLLBACK")
                raise
            else:
                connection.execute("COMMIT")

            unresolved = sorted(
                {
                    mapping.selection_description
                    for group in player_mappings
                    for mapping in group
                    if mapping.fpl_player_id is None
                }
            )
            outcome_count = sum(map(len, snapshots))
        else:
            unresolved = []
            outcome_count = 0
    finally:
        connection.close()

    print(
        f"FPL reference refreshed: {fpl_result.player_count} players, "
        f"{fpl_result.fixture_count} fixtures."
    )
    print(
        f"PropLine odds stored: {len(selected)} mapped upcoming events, "
        f"{outcome_count} outcomes."
    )
    if unmapped:
        print(
            f"Unmapped PropLine events ({len(unmapped)}): "
            + _event_labels(unmapped)
        )
    if skipped:
        print(
            f"Skipped non-upcoming events ({len(skipped)}): "
            + _event_labels(skipped)
        )
    if unresolved:
        print(f"Unmatched player props ({len(unresolved)}): {', '.join(unresolved)}")


def _event_labels(events: list[OddsProviderEvent]) -> str:
    return ", ".join(
        f"{event.home_team} v {event.away_team} ({event.provider_event_id})"
        for event in events
    )


if __name__ == "__main__":
    main()
