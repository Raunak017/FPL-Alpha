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
    complete_empty_odds_ingestion_run,
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
    run = None
    unresolved = []
    outcome_count = 0
    run_record = start_odds_ingestion_run(connection, provider_key="propline")
    run_id = run_record.run_id
    current_stage = "load_reference_data"
    try:
        current_stage = "load_reference_data"
        teams = load_teams(connection)
        players = load_players(connection)
        fixtures = load_fixtures(connection)

        current_stage = "fetch_epl_events"
        event_payloads = odds.propline_epl_events(force=args.force)

        current_stage = "map_upcoming_events"
        selected, unmapped, skipped = odds.mapped_upcoming_propline_events(
            event_payloads, teams, fixtures, now, args.gameweek
        )

        normalized = []
        for event, _ in selected:
            event_id = event.provider_event_id
            current_stage = f"fetch_event_odds:{event_id}"
            payload = odds.propline_epl_event_odds(event_id, markets, force=args.force)

            current_stage = f"read_event_cache:{event_id}"
            cache_key = odds.propline_epl_event_odds_cache_key(event_id, markets)
            cache_file = RAW / "propline" / f"{cache_key}.json"
            captured_at = datetime.fromtimestamp(cache_file.stat().st_mtime, tz=timezone.utc)

            current_stage = f"normalize_event_odds:{event_id}"
            normalized.append(
                odds.normalize_propline_event_odds(
                    payload, teams, players, fixtures, captured_at
                )
            )

        if normalized:
            current_stage = "store_snapshot_bundle"
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
            current_stage = "complete_empty_run"
            run = complete_empty_odds_ingestion_run(
                connection, run_id, provider_key="propline"
            )
            unresolved = []
            outcome_count = 0
    except Exception as exc:
        fail_odds_ingestion_run(connection, run_id, current_stage, str(exc))
        raise
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
    if run is not None:
        print(
            f"Ingestion run {run.run_id} ({run.status}) in {run.duration_ms:.1f}ms: "
            f"{run.records_inserted} inserted, {run.records_updated} updated."
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
