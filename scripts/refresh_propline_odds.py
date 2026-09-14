#!/usr/bin/env python3
"""Capture selected PropLine EPL event odds into DuckDB.

Repeat --event-id for each event. Responses are fetched cache-first and saved
unchanged under data/raw/propline/ by fpl_alpha.cache.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from fpl_alpha.config import RAW
from fpl_alpha.ingestion import odds
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
    parser.add_argument("--event-id", action="append", required=True)
    parser.add_argument(
        "--markets",
        default=",".join(odds.PROPLINE_EPL_MARKETS),
        help="comma-separated PropLine market keys",
    )
    parser.add_argument("--force", action="store_true", help="ignore cache TTL")
    args = parser.parse_args()

    markets = tuple(market for market in args.markets.split(",") if market)
    connection = open_database()
    try:
        teams = load_teams(connection)
        players = load_players(connection)
        fixtures = load_fixtures(connection)
        if not teams or not players or not fixtures:
            raise RuntimeError("Populate FPL teams, players, and fixtures before capturing PropLine odds.")

        normalized = []
        for event_id in args.event_id:
            payload = odds.propline_epl_event_odds(event_id, markets, force=args.force)
            cache_key = odds.propline_epl_event_odds_cache_key(event_id, markets)
            cache_file = RAW / "propline" / f"{cache_key}.json"
            # This is the local raw-cache write time, not a provider timestamp.
            captured_at = datetime.fromtimestamp(cache_file.stat().st_mtime, tz=timezone.utc)
            normalized.append(
                odds.normalize_propline_event_odds(payload, teams, players, fixtures, captured_at)
            )
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
    finally:
        connection.close()

    unresolved = [
        mapping.selection_description
        for group in player_mappings
        for mapping in group
        if mapping.fpl_player_id is None
    ]
    print(f"PropLine odds stored: {len(events)} events, {sum(map(len, snapshots))} outcomes.")
    if unresolved:
        print(f"Unmatched player props ({len(unresolved)}): {', '.join(sorted(unresolved))}")


if __name__ == "__main__":
    main()
