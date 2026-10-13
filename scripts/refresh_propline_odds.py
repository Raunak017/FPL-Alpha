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
    fail_odds_ingestion_run,
    load_fixtures,
    load_players,
    load_teams,
    open_database,
    start_odds_ingestion_run,
    store_odds_snapshot_bundle,
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
    run_record = start_odds_ingestion_run(
        connection, provider_key="propline", provider_event_ids=args.event_id
    )
    run_id = run_record.run_id
    try:
        teams = load_teams(connection)
        players = load_players(connection)
        fixtures = load_fixtures(connection)
        if not teams or not players or not fixtures:
            msg = "Populate FPL teams, players, and fixtures before capturing PropLine odds."
            fail_odds_ingestion_run(connection, run_id, "validate_reference_data", msg)
            raise RuntimeError(msg)

        normalized = []
        for event_id in args.event_id:
            try:
                payload = odds.propline_epl_event_odds(event_id, markets, force=args.force)
            except Exception as exc:
                fail_odds_ingestion_run(connection, run_id, f"fetch_event_odds:{event_id}", str(exc))
                raise

            cache_key = odds.propline_epl_event_odds_cache_key(event_id, markets)
            cache_file = RAW / "propline" / f"{cache_key}.json"
            # This is the local raw-cache write time, not a provider timestamp.
            captured_at = datetime.fromtimestamp(cache_file.stat().st_mtime, tz=timezone.utc)
            try:
                normalized.append(
                    odds.normalize_propline_event_odds(payload, teams, players, fixtures, captured_at)
                )
            except Exception as exc:
                fail_odds_ingestion_run(connection, run_id, f"normalize_event_odds:{event_id}", str(exc))
                raise

        events, mappings, player_mappings, bookmakers, snapshots = zip(*normalized)
        run = store_odds_snapshot_bundle(
            connection,
            provider_key="propline",
            events=events,
            event_fixture_mappings=mappings,
            player_mappings=(m for group in player_mappings for m in group),
            bookmakers=(b for group in bookmakers for b in group),
            snapshots=(s for group in snapshots for s in group),
            records_fetched=sum(map(len, snapshots)),
            run_id=run_id,
        )
    finally:
        connection.close()

    unresolved = [
        mapping.selection_description
        for group in player_mappings
        for mapping in group
        if mapping.fpl_player_id is None
    ]
    print(f"PropLine odds stored: {len(events)} events, {sum(map(len, snapshots))} outcomes.")
    print(
        f"Ingestion run {run.run_id} ({run.status}) in {run.duration_ms:.1f}ms: "
        f"{run.records_inserted} inserted, {run.records_updated} updated."
    )
    if unresolved:
        print(f"Unmatched player props ({len(unresolved)}): {', '.join(sorted(unresolved))}")


if __name__ == "__main__":
    main()
