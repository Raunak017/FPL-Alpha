"""Reusable cache-first FPL refresh workflow."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from ..config import RAW
from ..identity import (
    player_snapshots_from_bootstrap,
    players_from_bootstrap,
    teams_from_bootstrap,
)
from ..storage import (
    gameweek_history_is_ingested,
    mark_gameweek_history_ingested,
    open_database,
    upsert_fixtures,
    upsert_player_gameweek_history,
    upsert_player_snapshots,
    upsert_players,
    upsert_teams,
)
from . import fpl


@dataclass(frozen=True)
class FPLRefreshResult:
    player_count: int
    team_count: int
    fixture_count: int
    ingested_gameweeks: tuple[int, ...]


def refresh_fpl_database(force: bool = False) -> FPLRefreshResult:
    """Refresh normalized FPL data, using raw responses cache-first by default."""
    bootstrap = fpl.bootstrap_static(force=force)
    fixture_payload = fpl.fixtures(force=force)
    teams = teams_from_bootstrap(bootstrap)
    players = players_from_bootstrap(bootstrap)
    fixtures = fpl.fixtures_from_api(fixture_payload)

    cache_file = RAW / "fpl" / "bootstrap-static.json"
    captured_at = datetime.fromtimestamp(cache_file.stat().st_mtime, tz=timezone.utc)

    connection = open_database()
    try:
        pending_gameweeks = [
            gameweek
            for gameweek in fpl.finalized_gameweeks(bootstrap)
            if not gameweek_history_is_ingested(connection, gameweek)
        ]
        history_by_gameweek = {}
        for gameweek in pending_gameweeks:
            live_history, element_summary_player_ids = fpl.player_history_from_gameweek_live(
                gameweek, fpl.event_live(gameweek, force=force), players, fixtures
            )
            element_summary_history = [
                record
                for player_id in element_summary_player_ids
                for record in fpl.player_history_from_element_summary(
                    player_id, fpl.element_summary(player_id, force=force)
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
                connection, player_snapshots_from_bootstrap(bootstrap, captured_at)
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

    return FPLRefreshResult(
        player_count=len(bootstrap["elements"]),
        team_count=len(bootstrap["teams"]),
        fixture_count=len(fixture_payload),
        ingested_gameweeks=tuple(pending_gameweeks),
    )

