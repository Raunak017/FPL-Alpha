"""Focused mocked-payload tests for finalized gameweek history ingestion."""
from fpl_alpha.ingestion.fpl import (
    finalized_gameweeks,
    player_history_from_element_summary,
    player_history_from_gameweek_live,
)
from fpl_alpha.schemas import Fixture, Player
from fpl_alpha.storage import (
    gameweek_history_is_ingested,
    mark_gameweek_history_ingested,
    open_database,
    upsert_player_gameweek_history,
)


def _fixture(fpl_id: int, home: int, away: int) -> Fixture:
    return Fixture(
        fpl_id=fpl_id,
        code=fpl_id * 100,
        event=7,
        kickoff_time="2026-10-03T14:00:00Z",
        finished=True,
        finished_provisional=False,
        minutes=90,
        provisional_start_time=False,
        started=True,
        team_a_fpl_id=away,
        team_a_score=1,
        team_a_difficulty=3,
        team_h_fpl_id=home,
        team_h_score=2,
        team_h_difficulty=2,
    )


def _live_stats(*, minutes: int = 90, total_points: int = 6) -> dict[str, int | float]:
    return {
        "minutes": minutes,
        "total_points": total_points,
        "goals_scored": 0,
        "assists": 0,
        "clean_sheets": 0,
        "goals_conceded": 0,
        "own_goals": 0,
        "penalties_saved": 0,
        "penalties_missed": 0,
        "yellow_cards": 0,
        "red_cards": 0,
        "saves": 0,
        "bonus": 0,
        "bps": 10,
        "influence": 2.5,
        "creativity": 3.5,
        "threat": 4.5,
        "ict_index": 1.1,
        "starts": 1 if minutes else 0,
        "expected_goals": 0.1,
        "expected_assists": 0.2,
        "expected_goal_involvements": 0.3,
        "expected_goals_conceded": 0.4,
    }


def _history_row(fixture: int) -> dict[str, int | str | bool]:
    return {
        "fixture": fixture,
        "round": 7,
        "kickoff_time": "2026-10-03T14:00:00Z",
        "opponent_team": 5,
        "was_home": True,
        "team_h_score": 2,
        "team_a_score": 1,
        "minutes": 90,
        "total_points": 8,
        "goals_scored": 1,
        "assists": 0,
        "clean_sheets": 0,
        "goals_conceded": 1,
        "own_goals": 0,
        "penalties_saved": 0,
        "penalties_missed": 0,
        "yellow_cards": 0,
        "red_cards": 0,
        "saves": 0,
        "bonus": 2,
        "bps": 25,
        "influence": "30.0",
        "creativity": "20.0",
        "threat": "40.0",
        "ict_index": "9.0",
        "starts": 1,
        "expected_goals": "0.70",
        "expected_assists": "0.10",
        "expected_goal_involvements": "0.80",
        "expected_goals_conceded": "1.00",
        "value": 75,
        "transfers_balance": 10,
        "selected": 100000,
        "transfers_in": 50,
        "transfers_out": 40,
    }


def test_gameweek_live_uses_team_schedule_for_blank_single_and_dgw_routing():
    players = [
        Player(10, "Home", "Home Player", 1, "MID", 75),
        Player(11, "Away", "Away Player", 2, "MID", 75),
        Player(12, "Double", "Double Player", 3, "MID", 75),
        Player(13, "Blank", "Blank Player", 4, "MID", 75),
    ]
    fixtures = [_fixture(100, 1, 2), _fixture(101, 3, 5), _fixture(102, 6, 3)]
    live = {
        "elements": [
            {"id": 10, "stats": _live_stats(minutes=0, total_points=0), "explain": []},
            {"id": 11, "stats": _live_stats(), "explain": []},
            # One explain fixture must not prevent DGW routing.
            {"id": 12, "stats": _live_stats(), "explain": [{"fixture": 101, "stats": []}]},
        ]
    }

    history, element_summary_ids = player_history_from_gameweek_live(
        7, live, players, fixtures
    )

    assert [record.player_fpl_id for record in history] == [10, 11]
    assert history[0].fixture_fpl_id == 100
    assert history[0].minutes == 0
    assert history[0].total_points == 0
    assert history[0].value is None
    assert element_summary_ids == [12]


def test_finalization_and_marker_skip_completed_gameweeks(tmp_path):
    bootstrap = {
        "events": [
            {"id": 6, "finished": True, "data_checked": False},
            {"id": 7, "finished": True, "data_checked": True},
            {"id": 8, "finished": False, "data_checked": True},
        ]
    }
    connection = open_database(tmp_path / "fpl_alpha.duckdb")
    try:
        assert finalized_gameweeks(bootstrap) == [7]
        assert not gameweek_history_is_ingested(connection, 7)
        connection.execute("BEGIN TRANSACTION")
        mark_gameweek_history_ingested(connection, 7)
        connection.execute("COMMIT")
        assert gameweek_history_is_ingested(connection, 7)
    finally:
        connection.close()


def test_dgw_element_summary_history_upserts_each_fixture(tmp_path):
    history = player_history_from_element_summary(
        12,
        {"history": [_history_row(101), _history_row(102)]},
    )
    connection = open_database(tmp_path / "fpl_alpha.duckdb")
    try:
        upsert_player_gameweek_history(connection, history)
        rows = connection.execute(
            "SELECT fixture_fpl_id, value FROM player_gameweek_history ORDER BY fixture_fpl_id"
        ).fetchall()
    finally:
        connection.close()

    assert rows == [(101, 75), (102, 75)]
