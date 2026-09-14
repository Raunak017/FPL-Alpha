"""Focused tests for DuckDB schema creation and representative upserts."""
from dataclasses import replace
from datetime import datetime, timezone

from fpl_alpha.ingestion.fpl import player_history_from_element_summary
from fpl_alpha.schemas import Fixture, Player, PlayerSnapshot, Team
from fpl_alpha.storage import (
    open_database,
    upsert_fixtures,
    upsert_player_gameweek_history,
    upsert_player_snapshots,
    upsert_players,
    upsert_teams,
)


def _snapshot(
    captured_at: datetime, *, now_cost: int = 100, total_points: int = 200
) -> PlayerSnapshot:
    return PlayerSnapshot(
        player_fpl_id=10,
        captured_at=captured_at,
        now_cost=now_cost,
        selected_by_percent=15.0,
        status="a",
        total_points=total_points,
        points_per_game=5.0,
        form=4.5,
        minutes=500,
        starts=5,
        goals_scored=2,
        assists=3,
        clean_sheets=2,
        bonus=4,
        bps=100,
        expected_goals=1.5,
        expected_assists=2.5,
        expected_goal_involvements=4.0,
        expected_goals_conceded=3.0,
        clean_sheets_per_90=0.36,
        defensive_contribution_per_90=4.5,
        expected_goals_per_90=0.27,
        expected_assists_per_90=0.45,
        expected_goal_involvements_per_90=0.72,
        expected_goals_conceded_per_90=0.54,
        goals_conceded_per_90=0.9,
        saves_per_90=2.0,
        starts_per_90=0.9,
        influence=80.0,
        creativity=90.0,
        threat=100.0,
        ict_index=27.0,
        chance_of_playing_next_round=None,
        chance_of_playing_this_round=None,
        transfers_in_event=1,
        transfers_out_event=2,
        transfers_in=10,
        transfers_out=20,
    )


def test_open_database_initializes_fpl_and_odds_tables(tmp_path):
    connection = open_database(tmp_path / "fpl_alpha.duckdb")
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main'"
            ).fetchall()
        }
    finally:
        connection.close()

    assert {
        "teams",
        "players",
        "fixtures",
        "player_snapshots",
        "player_gameweek_history",
        "gameweek_history_ingestions",
        "odds_provider_events",
        "odds_event_fixture_mappings",
        "odds_bookmakers",
        "odds_player_mappings",
        "odds_outcome_snapshots",
    } <= tables


def test_upserts_keep_identity_and_snapshot_state_separate(tmp_path):
    connection = open_database(tmp_path / "fpl_alpha.duckdb")
    captured_at = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
    try:
        upsert_teams(
            connection,
            [
                Team(1, "Arsenal", "ARS"),
                Team(2, "Chelsea", "CHE"),
            ],
        )
        upsert_players(
            connection,
            [Player(10, "Saka", "Bukayo Saka", 1, "MID", 100)],
        )
        upsert_fixtures(
            connection,
            [
                Fixture(
                    99,
                    123456,
                    1,
                    "2026-08-21T19:00:00Z",
                    False,
                    False,
                    0,
                    False,
                    False,
                    2,
                    None,
                    3,
                    1,
                    None,
                    2,
                )
            ],
        )
        upsert_player_snapshots(
            connection,
            [_snapshot(captured_at)],
        )

        upsert_players(
            connection,
            [Player(10, "Saka", "Bukayo Saka", 1, "MID", 101)],
        )
        upsert_player_snapshots(
            connection,
            [
                replace(
                    _snapshot(captured_at, now_cost=101),
                    selected_by_percent=15.5,
                    status="d",
                    chance_of_playing_next_round=75,
                    transfers_in_event=3,
                    transfers_out_event=4,
                    transfers_in=30,
                    transfers_out=40,
                )
            ],
        )

        player_count = connection.execute("SELECT count(*) FROM players").fetchone()[0]
        snapshot = connection.execute(
            "SELECT now_cost, selected_by_percent, status, transfers_in "
            "FROM player_snapshots"
        ).fetchone()
        fixture_count = connection.execute("SELECT count(*) FROM fixtures").fetchone()[0]
    finally:
        connection.close()

    assert player_count == 1
    assert fixture_count == 1
    assert snapshot == (101, 15.5, "d", 30)


def test_snapshot_value_metrics_are_derived_in_python_and_duckdb(tmp_path):
    captured_at = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
    snapshot = _snapshot(captured_at)
    connection = open_database(tmp_path / "fpl_alpha.duckdb")
    try:
        upsert_player_snapshots(connection, [snapshot])
        values = connection.execute(
            "SELECT price_millions, points_per_million, points_per_90 "
            "FROM player_snapshot_values"
        ).fetchone()
    finally:
        connection.close()

    assert snapshot.price_millions == 10.0
    assert snapshot.points_per_million == 20.0
    assert snapshot.points_per_90 == 36.0
    assert values == (10.0, 20.0, 36.0)


def test_history_normalizes_empty_payload_and_upserts_fixture_record(tmp_path):
    assert player_history_from_element_summary(10, {"history": []}) == []
    history = player_history_from_element_summary(
        10,
        {
            "history": [
                {
                    "fixture": 99,
                    "round": 1,
                    "kickoff_time": "2026-08-21T19:00:00Z",
                    "opponent_team": 2,
                    "was_home": True,
                    "team_h_score": 2,
                    "team_a_score": 1,
                    "minutes": 90,
                    "total_points": 12,
                    "goals_scored": 1,
                    "assists": 1,
                    "clean_sheets": 0,
                    "goals_conceded": 1,
                    "own_goals": 0,
                    "penalties_saved": 0,
                    "penalties_missed": 0,
                    "yellow_cards": 0,
                    "red_cards": 0,
                    "saves": 0,
                    "bonus": 3,
                    "bps": 35,
                    "influence": "40.0",
                    "creativity": "30.0",
                    "threat": "50.0",
                    "ict_index": "12.0",
                    "starts": 1,
                    "expected_goals": "0.80",
                    "expected_assists": "0.25",
                    "expected_goal_involvements": "1.05",
                    "expected_goals_conceded": "1.10",
                    "value": 100,
                    "transfers_balance": 10,
                    "selected": 100000,
                    "transfers_in": 50,
                    "transfers_out": 40,
                }
            ]
        },
    )
    connection = open_database(tmp_path / "fpl_alpha.duckdb")
    try:
        upsert_player_gameweek_history(connection, history)
        upsert_player_gameweek_history(connection, [replace(history[0], total_points=13)])
        stored = connection.execute(
            "SELECT count(*), total_points, expected_goals "
            "FROM player_gameweek_history GROUP BY total_points, expected_goals"
        ).fetchone()
    finally:
        connection.close()

    assert stored == (1, 13, 0.8)
