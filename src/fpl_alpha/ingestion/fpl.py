"""Official FPL API client (Plan step 1). Public, no key.

Refactored from the original ``fpl_data_probe.py``: every call now goes through
the cache-first gateway, so repeated dev runs read ``data/raw/fpl/`` instead of
hitting the endpoint. Returns raw dicts; normalization into schemas.Player /
schemas.Team lives in :mod:`fpl_alpha.identity`.
"""
from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..cache import fetch
from ..config import FPL_API, RAW
from ..schemas import Fixture, Player, PlayerGameweekHistory


def bootstrap_static(force: bool = False) -> dict[str, Any]:
    """Players, teams, gameweeks, prices, ownership, xG/xA — the core dump."""
    return fetch(FPL_API, "/bootstrap-static/", key="bootstrap-static", force=force)


def fixtures(force: bool = False) -> list[dict[str, Any]]:
    """All fixtures incl. FDR difficulty and kickoff times."""
    return fetch(FPL_API, "/fixtures/", key="fixtures", force=force)


def fixtures_from_api(payload: list[dict[str, Any]]) -> list[Fixture]:
    """Normalize raw FPL fixture data into canonical records."""
    return [
        Fixture(
            fpl_id=fixture["id"],
            code=fixture["code"],
            event=fixture["event"],
            kickoff_time=fixture["kickoff_time"],
            finished=fixture["finished"],
            finished_provisional=fixture["finished_provisional"],
            minutes=fixture["minutes"],
            provisional_start_time=fixture["provisional_start_time"],
            started=fixture["started"],
            team_a_fpl_id=fixture["team_a"],
            team_a_score=fixture["team_a_score"],
            team_a_difficulty=fixture["team_a_difficulty"],
            team_h_fpl_id=fixture["team_h"],
            team_h_score=fixture["team_h_score"],
            team_h_difficulty=fixture["team_h_difficulty"],
        )
        for fixture in payload
    ]


def event_live(gameweek: int, force: bool = False) -> dict[str, Any]:
    """All player stats for one FPL gameweek, cache-first."""
    return fetch(
        FPL_API,
        f"/event/{gameweek}/live/",
        key=f"event-{gameweek}-live",
        force=force,
    )


def finalized_gameweeks(bootstrap: dict[str, Any]) -> list[int]:
    """Gameweeks whose FPL results have been checked and are final."""
    return [
        event["id"]
        for event in bootstrap["events"]
        if event["finished"] and event["data_checked"]
    ]


def player_history_from_gameweek_live(
    gameweek: int,
    live: dict[str, Any],
    players: Iterable[Player],
    fixtures: Iterable[Fixture],
) -> tuple[list[PlayerGameweekHistory], list[int]]:
    """Normalize single-fixture player history from gameweek-live data.

    A player's fixture count comes from the team fixture schedule, not the
    ``explain`` payload. Double-gameweek players are returned separately for
    per-fixture element-summary normalization.
    """
    fixtures_by_team: dict[int, list[Fixture]] = defaultdict(list)
    for fixture in fixtures:
        if fixture.event == gameweek:
            fixtures_by_team[fixture.team_h_fpl_id].append(fixture)
            fixtures_by_team[fixture.team_a_fpl_id].append(fixture)

    live_elements = {element["id"]: element for element in live["elements"]}
    history: list[PlayerGameweekHistory] = []
    element_summary_player_ids: list[int] = []
    for player in players:
        team_fixtures = fixtures_by_team.get(player.team_fpl_id, [])
        if not team_fixtures:
            continue
        if len(team_fixtures) > 1:
            element_summary_player_ids.append(player.fpl_id)
            continue

        live_element = live_elements.get(player.fpl_id)
        if live_element is None:
            raise ValueError(
                f"Gameweek {gameweek} live payload is missing player {player.fpl_id}"
            )
        history.append(
            _player_history_from_live_stats(
                player, team_fixtures[0], gameweek, live_element["stats"]
            )
        )

    return history, element_summary_player_ids


def element_summary(player_id: int, force: bool = False) -> dict[str, Any]:
    """Per-player history + upcoming fixtures for one element id."""
    return fetch(
        FPL_API,
        f"/element-summary/{player_id}/",
        key=f"element-summary-{player_id}",
        force=force,
    )


def cached_element_summary(player_id: int) -> dict[str, Any] | None:
    """Return an already-cached player summary without making an API request."""
    path = _element_summary_cache_path(player_id)
    return json.loads(path.read_text()) if path.exists() else None


def player_history_from_element_summary(
    player_fpl_id: int, summary: dict[str, Any]
) -> list[PlayerGameweekHistory]:
    """Normalize completed per-fixture history; pre-GW1 payloads yield ``[]``."""
    return [
        PlayerGameweekHistory(
            player_fpl_id=player_fpl_id,
            fixture_fpl_id=row["fixture"],
            gameweek=row["round"],
            kickoff_time=row["kickoff_time"],
            opponent_team_fpl_id=row["opponent_team"],
            was_home=row["was_home"],
            team_h_score=row["team_h_score"],
            team_a_score=row["team_a_score"],
            minutes=row["minutes"],
            total_points=row["total_points"],
            goals_scored=row["goals_scored"],
            assists=row["assists"],
            clean_sheets=row["clean_sheets"],
            goals_conceded=row["goals_conceded"],
            own_goals=row["own_goals"],
            penalties_saved=row["penalties_saved"],
            penalties_missed=row["penalties_missed"],
            yellow_cards=row["yellow_cards"],
            red_cards=row["red_cards"],
            saves=row["saves"],
            bonus=row["bonus"],
            bps=row["bps"],
            influence=float(row["influence"]),
            creativity=float(row["creativity"]),
            threat=float(row["threat"]),
            ict_index=float(row["ict_index"]),
            starts=row.get("starts"),
            expected_goals=_float_or_none(row.get("expected_goals")),
            expected_assists=_float_or_none(row.get("expected_assists")),
            expected_goal_involvements=_float_or_none(row.get("expected_goal_involvements")),
            expected_goals_conceded=_float_or_none(row.get("expected_goals_conceded")),
            value=row["value"],
            transfers_balance=row["transfers_balance"],
            selected=row["selected"],
            transfers_in=row["transfers_in"],
            transfers_out=row["transfers_out"],
        )
        for row in summary.get("history", [])
    ]


def _player_history_from_live_stats(
    player: Player, fixture: Fixture, gameweek: int, stats: dict[str, Any]
) -> PlayerGameweekHistory:
    if player.team_fpl_id == fixture.team_h_fpl_id:
        opponent_team_fpl_id = fixture.team_a_fpl_id
        was_home = True
    elif player.team_fpl_id == fixture.team_a_fpl_id:
        opponent_team_fpl_id = fixture.team_h_fpl_id
        was_home = False
    else:
        raise ValueError(
            f"Player {player.fpl_id} team is not part of fixture {fixture.fpl_id}"
        )

    return PlayerGameweekHistory(
        player_fpl_id=player.fpl_id,
        fixture_fpl_id=fixture.fpl_id,
        gameweek=gameweek,
        kickoff_time=fixture.kickoff_time,
        opponent_team_fpl_id=opponent_team_fpl_id,
        was_home=was_home,
        team_h_score=fixture.team_h_score,
        team_a_score=fixture.team_a_score,
        minutes=stats["minutes"],
        total_points=stats["total_points"],
        goals_scored=stats["goals_scored"],
        assists=stats["assists"],
        clean_sheets=stats["clean_sheets"],
        goals_conceded=stats["goals_conceded"],
        own_goals=stats["own_goals"],
        penalties_saved=stats["penalties_saved"],
        penalties_missed=stats["penalties_missed"],
        yellow_cards=stats["yellow_cards"],
        red_cards=stats["red_cards"],
        saves=stats["saves"],
        bonus=stats["bonus"],
        bps=stats["bps"],
        influence=float(stats["influence"]),
        creativity=float(stats["creativity"]),
        threat=float(stats["threat"]),
        ict_index=float(stats["ict_index"]),
        starts=stats.get("starts"),
        expected_goals=_float_or_none(stats.get("expected_goals")),
        expected_assists=_float_or_none(stats.get("expected_assists")),
        expected_goal_involvements=_float_or_none(stats.get("expected_goal_involvements")),
        expected_goals_conceded=_float_or_none(stats.get("expected_goals_conceded")),
        value=None,
        transfers_balance=None,
        selected=None,
        transfers_in=None,
        transfers_out=None,
    )


def _element_summary_cache_path(player_id: int) -> Path:
    return RAW / FPL_API.name / f"element-summary-{player_id}.json"


def _float_or_none(value: Any) -> float | None:
    return None if value is None else float(value)


def entry(team_id: int | str, force: bool = False) -> dict[str, Any]:
    """A manager's entry (name, rank, value). Public by Team ID."""
    return fetch(FPL_API, f"/entry/{team_id}/", key=f"entry-{team_id}", force=force)


def entry_history(team_id: int | str, force: bool = False) -> dict[str, Any]:
    return fetch(
        FPL_API, f"/entry/{team_id}/history/", key=f"entry-{team_id}-history", force=force
    )


def entry_picks(team_id: int | str, gw: int, force: bool = False) -> dict[str, Any]:
    """A manager's squad for a gameweek. NOTE: only public once the GW locks."""
    return fetch(
        FPL_API,
        f"/entry/{team_id}/event/{gw}/picks/",
        key=f"entry-{team_id}-picks-gw{gw}",
        force=force,
    )
