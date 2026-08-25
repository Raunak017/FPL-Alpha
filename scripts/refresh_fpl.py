#!/usr/bin/env python3
"""Refresh the cached FPL core data (bootstrap + fixtures).

Cache-first: does nothing over the wire if the cache is still fresh
(see FPL_API.cache_ttl_s). Pass --force to bypass.

    python scripts/refresh_fpl.py
    python scripts/refresh_fpl.py --force
"""
import argparse
from datetime import datetime, timezone

from fpl_alpha.config import RAW
from fpl_alpha.identity import (
    player_snapshots_from_bootstrap,
    players_from_bootstrap,
    teams_from_bootstrap,
)
from fpl_alpha.ingestion import fpl
from fpl_alpha.storage import (
    open_database,
    gameweek_history_is_ingested,
    mark_gameweek_history_ingested,
    upsert_fixtures,
    upsert_player_gameweek_history,
    upsert_player_snapshots,
    upsert_players,
    upsert_teams,
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="ignore cache TTL")
    args = ap.parse_args()

    boot = fpl.bootstrap_static(force=args.force)
    fx = fpl.fixtures(force=args.force)
    teams = teams_from_bootstrap(boot)
    players = players_from_bootstrap(boot)
    fixtures = fpl.fixtures_from_api(fx)

    # This is the local raw-cache write time, not an FPL-provided timestamp.
    cache_file = RAW / "fpl" / "bootstrap-static.json"
    captured_at = datetime.fromtimestamp(cache_file.stat().st_mtime, tz=timezone.utc)

    connection = open_database()
    try:
        pending_gameweeks = [
            gameweek
            for gameweek in fpl.finalized_gameweeks(boot)
            if not gameweek_history_is_ingested(connection, gameweek)
        ]
        history_by_gameweek = {}
        for gameweek in pending_gameweeks:
            live_history, element_summary_player_ids = fpl.player_history_from_gameweek_live(
                gameweek, fpl.event_live(gameweek), players, fixtures
            )
            element_summary_history = [
                record
                for player_id in element_summary_player_ids
                for record in fpl.player_history_from_element_summary(
                    player_id, fpl.element_summary(player_id)
                )
                if record.gameweek == gameweek
            ]
            history_by_gameweek[gameweek] = live_history + element_summary_history

        connection.execute("BEGIN TRANSACTION")
        try:
            upsert_teams(connection, teams)
            upsert_players(connection, players)
            upsert_fixtures(connection, fixtures)
            upsert_player_snapshots(
                connection, player_snapshots_from_bootstrap(boot, captured_at)
            )
            for gameweek, history in history_by_gameweek.items():
                upsert_player_gameweek_history(connection, history)
                mark_gameweek_history_ingested(connection, gameweek)
        except Exception:
            connection.execute("ROLLBACK")
            raise
        else:
            connection.execute("COMMIT")
    finally:
        connection.close()

    print(
        f"FPL cache refreshed: {len(boot['elements'])} players, "
        f"{len(boot['teams'])} teams, {len(fx)} fixtures."
    )


if __name__ == "__main__":
    main()
