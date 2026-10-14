"""DuckDB persistence for normalized official FPL data.

Raw API responses remain cache-owned by :mod:`fpl_alpha.cache`. This module
stores normalized records only; callers supply observation timestamps so stored
snapshots are reproducible.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb

from .config import DATA
from .schemas import (
    Fixture,
    OddsBookmaker,
    OddsEventFixtureMapping,
    OddsIngestionRun,
    OddsOutcomeSnapshot,
    OddsPlayerMapping,
    OddsProviderEvent,
    Player,
    PlayerGameweekHistory,
    PlayerSnapshot,
    Team,
    TeamGoalProjection,
)


class IngestionValidationError(ValueError):
    """Raised when odds snapshot staging validation fails."""

DATABASE_PATH = DATA / "fpl_alpha.duckdb"


def open_database(database_path: str | Path = DATABASE_PATH) -> duckdb.DuckDBPyConnection:
    """Open a database and ensure the FPL schema exists."""
    if str(database_path) != ":memory:":
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(database_path))
    initialize_schema(connection)
    return connection


def initialize_schema(connection: duckdb.DuckDBPyConnection) -> None:
    """Create the initial normalized FPL tables if they do not exist."""
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS teams (
            fpl_id BIGINT PRIMARY KEY,
            name VARCHAR NOT NULL,
            short_name VARCHAR NOT NULL,
            aliases VARCHAR[] NOT NULL DEFAULT []
        );

        CREATE TABLE IF NOT EXISTS players (
            fpl_id BIGINT PRIMARY KEY,
            web_name VARCHAR NOT NULL,
            full_name VARCHAR NOT NULL,
            team_fpl_id BIGINT NOT NULL,
            position VARCHAR NOT NULL,
            aliases VARCHAR[] NOT NULL DEFAULT []
        );

        CREATE TABLE IF NOT EXISTS fixtures (
            fpl_id BIGINT PRIMARY KEY,
            code BIGINT NOT NULL,
            event BIGINT,
            kickoff_time TIMESTAMPTZ,
            finished BOOLEAN NOT NULL,
            finished_provisional BOOLEAN NOT NULL,
            minutes INTEGER NOT NULL,
            provisional_start_time BOOLEAN NOT NULL,
            started BOOLEAN NOT NULL,
            team_a_fpl_id BIGINT NOT NULL,
            team_a_score INTEGER,
            team_a_difficulty INTEGER NOT NULL,
            team_h_fpl_id BIGINT NOT NULL,
            team_h_score INTEGER,
            team_h_difficulty INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS player_snapshots (
            player_fpl_id BIGINT NOT NULL,
            captured_at TIMESTAMPTZ NOT NULL,
            now_cost INTEGER NOT NULL,
            selected_by_percent DOUBLE NOT NULL,
            status VARCHAR NOT NULL,
            total_points INTEGER,
            points_per_game DOUBLE,
            form DOUBLE,
            minutes INTEGER,
            starts INTEGER,
            goals_scored INTEGER,
            assists INTEGER,
            clean_sheets INTEGER,
            bonus INTEGER,
            bps INTEGER,
            expected_goals DOUBLE,
            expected_assists DOUBLE,
            expected_goal_involvements DOUBLE,
            expected_goals_conceded DOUBLE,
            clean_sheets_per_90 DOUBLE,
            defensive_contribution_per_90 DOUBLE,
            expected_goals_per_90 DOUBLE,
            expected_assists_per_90 DOUBLE,
            expected_goal_involvements_per_90 DOUBLE,
            expected_goals_conceded_per_90 DOUBLE,
            goals_conceded_per_90 DOUBLE,
            saves_per_90 DOUBLE,
            starts_per_90 DOUBLE,
            influence DOUBLE,
            creativity DOUBLE,
            threat DOUBLE,
            ict_index DOUBLE,
            chance_of_playing_next_round INTEGER,
            chance_of_playing_this_round INTEGER,
            transfers_in_event BIGINT NOT NULL,
            transfers_out_event BIGINT NOT NULL,
            transfers_in BIGINT NOT NULL,
            transfers_out BIGINT NOT NULL,
            PRIMARY KEY (player_fpl_id, captured_at)
        );

        CREATE TABLE IF NOT EXISTS player_gameweek_history (
            player_fpl_id BIGINT NOT NULL,
            fixture_fpl_id BIGINT NOT NULL,
            gameweek INTEGER NOT NULL,
            kickoff_time TIMESTAMPTZ,
            opponent_team_fpl_id BIGINT NOT NULL,
            was_home BOOLEAN NOT NULL,
            team_h_score INTEGER,
            team_a_score INTEGER,
            minutes INTEGER NOT NULL,
            total_points INTEGER NOT NULL,
            goals_scored INTEGER NOT NULL,
            assists INTEGER NOT NULL,
            clean_sheets INTEGER NOT NULL,
            goals_conceded INTEGER NOT NULL,
            own_goals INTEGER NOT NULL,
            penalties_saved INTEGER NOT NULL,
            penalties_missed INTEGER NOT NULL,
            yellow_cards INTEGER NOT NULL,
            red_cards INTEGER NOT NULL,
            saves INTEGER NOT NULL,
            bonus INTEGER NOT NULL,
            bps INTEGER NOT NULL,
            influence DOUBLE NOT NULL,
            creativity DOUBLE NOT NULL,
            threat DOUBLE NOT NULL,
            ict_index DOUBLE NOT NULL,
            starts INTEGER,
            expected_goals DOUBLE,
            expected_assists DOUBLE,
            expected_goal_involvements DOUBLE,
            expected_goals_conceded DOUBLE,
            value INTEGER,
            transfers_balance BIGINT,
            selected BIGINT,
            transfers_in BIGINT,
            transfers_out BIGINT,
            PRIMARY KEY (player_fpl_id, fixture_fpl_id)
        );

        CREATE TABLE IF NOT EXISTS gameweek_history_ingestions (
            gameweek INTEGER PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS odds_provider_events (
            provider_key VARCHAR NOT NULL,
            provider_event_id VARCHAR NOT NULL,
            sport_key VARCHAR NOT NULL,
            home_team VARCHAR NOT NULL,
            away_team VARCHAR NOT NULL,
            commence_time TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (provider_key, provider_event_id)
        );

        CREATE TABLE IF NOT EXISTS odds_event_fixture_mappings (
            provider_key VARCHAR NOT NULL,
            provider_event_id VARCHAR NOT NULL,
            fpl_fixture_id BIGINT,
            match_method VARCHAR NOT NULL,
            PRIMARY KEY (provider_key, provider_event_id)
        );

        CREATE TABLE IF NOT EXISTS odds_bookmakers (
            provider_key VARCHAR NOT NULL,
            bookmaker_key VARCHAR NOT NULL,
            title VARCHAR NOT NULL,
            PRIMARY KEY (provider_key, bookmaker_key)
        );

        CREATE TABLE IF NOT EXISTS odds_player_mappings (
            provider_key VARCHAR NOT NULL,
            provider_event_id VARCHAR NOT NULL,
            selection_description VARCHAR NOT NULL,
            fpl_player_id BIGINT,
            match_method VARCHAR NOT NULL,
            PRIMARY KEY (provider_key, provider_event_id, selection_description)
        );

        CREATE TABLE IF NOT EXISTS odds_ingestion_runs (
            run_id VARCHAR PRIMARY KEY,
            provider_key VARCHAR NOT NULL,
            provider_event_ids VARCHAR[] NOT NULL,
            input_fingerprint VARCHAR,
            status VARCHAR NOT NULL,
            failure_stage VARCHAR,
            error_message VARCHAR,
            records_fetched INTEGER NOT NULL DEFAULT 0,
            records_parsed INTEGER NOT NULL DEFAULT 0,
            records_inserted INTEGER NOT NULL DEFAULT 0,
            records_updated INTEGER NOT NULL DEFAULT 0,
            records_rejected INTEGER NOT NULL DEFAULT 0,
            started_at TIMESTAMPTZ NOT NULL,
            finished_at TIMESTAMPTZ,
            duration_ms DOUBLE,
            retry_of_run_id VARCHAR,
            is_retry BOOLEAN DEFAULT FALSE
        );

        CREATE TABLE IF NOT EXISTS odds_outcome_snapshots (
            provider_key VARCHAR NOT NULL,
            provider_event_id VARCHAR NOT NULL,
            bookmaker_key VARCHAR NOT NULL,
            market_key VARCHAR NOT NULL,
            market_ordinal INTEGER NOT NULL,
            market_description VARCHAR,
            market_team VARCHAR,
            outcome_ordinal INTEGER NOT NULL,
            selection_description VARCHAR,
            fpl_player_id BIGINT,
            outcome_name VARCHAR NOT NULL,
            american_price INTEGER NOT NULL,
            point DOUBLE,
            last_update TIMESTAMPTZ,
            last_change_at TIMESTAMPTZ,
            captured_at TIMESTAMPTZ NOT NULL,
            run_id VARCHAR,
            PRIMARY KEY (
                provider_key, provider_event_id, bookmaker_key, market_key,
                market_ordinal, outcome_ordinal, captured_at
            )
        );

        CREATE TABLE IF NOT EXISTS team_goal_model_snapshots (
            fixture_fpl_id BIGINT NOT NULL,
            generated_at TIMESTAMPTZ NOT NULL,
            provider_key VARCHAR NOT NULL,
            provider_event_ids VARCHAR[] NOT NULL,
            source_captured_at_min TIMESTAMPTZ NOT NULL,
            source_captured_at_max TIMESTAMPTZ NOT NULL,
            source_market_snapshot_count INTEGER NOT NULL,
            lambda_home DOUBLE NOT NULL,
            lambda_away DOUBLE NOT NULL,
            p_clean_sheet_home DOUBLE NOT NULL,
            p_clean_sheet_away DOUBLE NOT NULL,
            fit_loss DOUBLE NOT NULL,
            PRIMARY KEY (fixture_fpl_id, generated_at)
        );

        CREATE TABLE IF NOT EXISTS team_goal_model_market_comparisons (
            fixture_fpl_id BIGINT NOT NULL,
            generated_at TIMESTAMPTZ NOT NULL,
            market VARCHAR NOT NULL,
            outcome VARCHAR NOT NULL,
            market_prob DOUBLE NOT NULL,
            model_prob DOUBLE NOT NULL,
            n_books INTEGER NOT NULL,
            PRIMARY KEY (fixture_fpl_id, generated_at, market, outcome)
        );

        ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS total_points INTEGER;
        ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS points_per_game DOUBLE;
        ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS form DOUBLE;
        ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS minutes INTEGER;
        ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS starts INTEGER;
        ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS goals_scored INTEGER;
        ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS assists INTEGER;
        ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS clean_sheets INTEGER;
        ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS bonus INTEGER;
        ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS bps INTEGER;
        ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS expected_goals DOUBLE;
        ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS expected_assists DOUBLE;
        ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS expected_goal_involvements DOUBLE;
        ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS expected_goals_conceded DOUBLE;
        ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS clean_sheets_per_90 DOUBLE;
        ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS defensive_contribution_per_90 DOUBLE;
        ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS expected_goals_per_90 DOUBLE;
        ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS expected_assists_per_90 DOUBLE;
        ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS expected_goal_involvements_per_90 DOUBLE;
        ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS expected_goals_conceded_per_90 DOUBLE;
        ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS goals_conceded_per_90 DOUBLE;
        ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS saves_per_90 DOUBLE;
        ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS starts_per_90 DOUBLE;
        ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS influence DOUBLE;
        ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS creativity DOUBLE;
        ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS threat DOUBLE;
        ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS ict_index DOUBLE;
        ALTER TABLE player_snapshots ADD COLUMN IF NOT EXISTS chance_of_playing_this_round INTEGER;
        ALTER TABLE player_gameweek_history ADD COLUMN IF NOT EXISTS team_h_score INTEGER;
        ALTER TABLE player_gameweek_history ADD COLUMN IF NOT EXISTS team_a_score INTEGER;
        ALTER TABLE player_gameweek_history ALTER COLUMN value DROP NOT NULL;
        ALTER TABLE player_gameweek_history ALTER COLUMN transfers_balance DROP NOT NULL;
        ALTER TABLE player_gameweek_history ALTER COLUMN selected DROP NOT NULL;
        ALTER TABLE player_gameweek_history ALTER COLUMN transfers_in DROP NOT NULL;
        ALTER TABLE player_gameweek_history ALTER COLUMN transfers_out DROP NOT NULL;
        ALTER TABLE odds_outcome_snapshots ADD COLUMN IF NOT EXISTS run_id VARCHAR;
        ALTER TABLE odds_ingestion_runs ADD COLUMN IF NOT EXISTS retry_of_run_id VARCHAR;
        ALTER TABLE odds_ingestion_runs ADD COLUMN IF NOT EXISTS is_retry BOOLEAN DEFAULT FALSE;
        ALTER TABLE odds_ingestion_runs ALTER COLUMN input_fingerprint DROP NOT NULL;

        CREATE OR REPLACE VIEW player_snapshot_values AS
        SELECT
            *,
            now_cost / 10.0 AS price_millions,
            CASE WHEN now_cost > 0 THEN total_points / (now_cost / 10.0) END AS points_per_million,
            CASE WHEN minutes > 0 THEN total_points * 90.0 / minutes END AS points_per_90
        FROM player_snapshots;
        """
    )


def upsert_teams(connection: duckdb.DuckDBPyConnection, teams: Iterable[Team]) -> None:
    """Insert or update canonical FPL teams."""
    rows = [(team.fpl_id, team.name, team.short_name, list(team.aliases)) for team in teams]
    if rows:
        connection.executemany(
            """
            INSERT INTO teams (fpl_id, name, short_name, aliases)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (fpl_id) DO UPDATE SET
                name = excluded.name,
                short_name = excluded.short_name,
                aliases = excluded.aliases
            """,
            rows,
        )


def upsert_players(connection: duckdb.DuckDBPyConnection, players: Iterable[Player]) -> None:
    """Insert or update static player identity, excluding snapshot state."""
    rows = [
        (
            player.fpl_id,
            player.web_name,
            player.full_name,
            player.team_fpl_id,
            player.position,
            list(player.aliases),
        )
        for player in players
    ]
    if rows:
        connection.executemany(
            """
            INSERT INTO players (fpl_id, web_name, full_name, team_fpl_id, position, aliases)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (fpl_id) DO UPDATE SET
                web_name = excluded.web_name,
                full_name = excluded.full_name,
                team_fpl_id = excluded.team_fpl_id,
                position = excluded.position,
                aliases = excluded.aliases
            """,
            rows,
        )


def upsert_fixtures(
    connection: duckdb.DuckDBPyConnection, fixtures: Iterable[Fixture]
) -> None:
    """Insert or update FPL fixtures and their current match state."""
    rows = [
        (
            fixture.fpl_id,
            fixture.code,
            fixture.event,
            fixture.kickoff_time,
            fixture.finished,
            fixture.finished_provisional,
            fixture.minutes,
            fixture.provisional_start_time,
            fixture.started,
            fixture.team_a_fpl_id,
            fixture.team_a_score,
            fixture.team_a_difficulty,
            fixture.team_h_fpl_id,
            fixture.team_h_score,
            fixture.team_h_difficulty,
        )
        for fixture in fixtures
    ]
    if rows:
        connection.executemany(
            """
            INSERT INTO fixtures (
                fpl_id, code, event, kickoff_time, finished, finished_provisional,
                minutes, provisional_start_time, started, team_a_fpl_id, team_a_score,
                team_a_difficulty, team_h_fpl_id, team_h_score, team_h_difficulty
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (fpl_id) DO UPDATE SET
                code = excluded.code,
                event = excluded.event,
                kickoff_time = excluded.kickoff_time,
                finished = excluded.finished,
                finished_provisional = excluded.finished_provisional,
                minutes = excluded.minutes,
                provisional_start_time = excluded.provisional_start_time,
                started = excluded.started,
                team_a_fpl_id = excluded.team_a_fpl_id,
                team_a_score = excluded.team_a_score,
                team_a_difficulty = excluded.team_a_difficulty,
                team_h_fpl_id = excluded.team_h_fpl_id,
                team_h_score = excluded.team_h_score,
                team_h_difficulty = excluded.team_h_difficulty
            """,
            rows,
        )


def upsert_player_snapshots(
    connection: duckdb.DuckDBPyConnection, snapshots: Iterable[PlayerSnapshot]
) -> None:
    """Insert or update time-varying player state for a supplied observation time."""
    rows = [
        (
            snapshot.player_fpl_id,
            snapshot.captured_at,
            snapshot.now_cost,
            snapshot.selected_by_percent,
            snapshot.status,
            snapshot.total_points,
            snapshot.points_per_game,
            snapshot.form,
            snapshot.minutes,
            snapshot.starts,
            snapshot.goals_scored,
            snapshot.assists,
            snapshot.clean_sheets,
            snapshot.bonus,
            snapshot.bps,
            snapshot.expected_goals,
            snapshot.expected_assists,
            snapshot.expected_goal_involvements,
            snapshot.expected_goals_conceded,
            snapshot.clean_sheets_per_90,
            snapshot.defensive_contribution_per_90,
            snapshot.expected_goals_per_90,
            snapshot.expected_assists_per_90,
            snapshot.expected_goal_involvements_per_90,
            snapshot.expected_goals_conceded_per_90,
            snapshot.goals_conceded_per_90,
            snapshot.saves_per_90,
            snapshot.starts_per_90,
            snapshot.influence,
            snapshot.creativity,
            snapshot.threat,
            snapshot.ict_index,
            snapshot.chance_of_playing_next_round,
            snapshot.chance_of_playing_this_round,
            snapshot.transfers_in_event,
            snapshot.transfers_out_event,
            snapshot.transfers_in,
            snapshot.transfers_out,
        )
        for snapshot in snapshots
    ]
    if rows:
        connection.executemany(
            """
            INSERT INTO player_snapshots (
                player_fpl_id, captured_at, now_cost, selected_by_percent, status,
                total_points, points_per_game, form, minutes, starts, goals_scored,
                assists, clean_sheets, bonus, bps, expected_goals, expected_assists,
                expected_goal_involvements, expected_goals_conceded, clean_sheets_per_90,
                defensive_contribution_per_90, expected_goals_per_90, expected_assists_per_90,
                expected_goal_involvements_per_90, expected_goals_conceded_per_90,
                goals_conceded_per_90, saves_per_90, starts_per_90, influence, creativity,
                threat, ict_index, chance_of_playing_next_round,
                chance_of_playing_this_round, transfers_in_event, transfers_out_event,
                transfers_in, transfers_out
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (player_fpl_id, captured_at) DO UPDATE SET
                now_cost = excluded.now_cost,
                selected_by_percent = excluded.selected_by_percent,
                status = excluded.status,
                total_points = excluded.total_points,
                points_per_game = excluded.points_per_game,
                form = excluded.form,
                minutes = excluded.minutes,
                starts = excluded.starts,
                goals_scored = excluded.goals_scored,
                assists = excluded.assists,
                clean_sheets = excluded.clean_sheets,
                bonus = excluded.bonus,
                bps = excluded.bps,
                expected_goals = excluded.expected_goals,
                expected_assists = excluded.expected_assists,
                expected_goal_involvements = excluded.expected_goal_involvements,
                expected_goals_conceded = excluded.expected_goals_conceded,
                clean_sheets_per_90 = excluded.clean_sheets_per_90,
                defensive_contribution_per_90 = excluded.defensive_contribution_per_90,
                expected_goals_per_90 = excluded.expected_goals_per_90,
                expected_assists_per_90 = excluded.expected_assists_per_90,
                expected_goal_involvements_per_90 = excluded.expected_goal_involvements_per_90,
                expected_goals_conceded_per_90 = excluded.expected_goals_conceded_per_90,
                goals_conceded_per_90 = excluded.goals_conceded_per_90,
                saves_per_90 = excluded.saves_per_90,
                starts_per_90 = excluded.starts_per_90,
                influence = excluded.influence,
                creativity = excluded.creativity,
                threat = excluded.threat,
                ict_index = excluded.ict_index,
                chance_of_playing_next_round = excluded.chance_of_playing_next_round,
                chance_of_playing_this_round = excluded.chance_of_playing_this_round,
                transfers_in_event = excluded.transfers_in_event,
                transfers_out_event = excluded.transfers_out_event,
                transfers_in = excluded.transfers_in,
                transfers_out = excluded.transfers_out
            """,
            rows,
        )


def upsert_player_gameweek_history(
    connection: duckdb.DuckDBPyConnection, history: Iterable[PlayerGameweekHistory]
) -> None:
    """Insert or update completed player fixture records."""
    rows = [
        (
            record.player_fpl_id,
            record.fixture_fpl_id,
            record.gameweek,
            record.kickoff_time,
            record.opponent_team_fpl_id,
            record.was_home,
            record.team_h_score,
            record.team_a_score,
            record.minutes,
            record.total_points,
            record.goals_scored,
            record.assists,
            record.clean_sheets,
            record.goals_conceded,
            record.own_goals,
            record.penalties_saved,
            record.penalties_missed,
            record.yellow_cards,
            record.red_cards,
            record.saves,
            record.bonus,
            record.bps,
            record.influence,
            record.creativity,
            record.threat,
            record.ict_index,
            record.starts,
            record.expected_goals,
            record.expected_assists,
            record.expected_goal_involvements,
            record.expected_goals_conceded,
            record.value,
            record.transfers_balance,
            record.selected,
            record.transfers_in,
            record.transfers_out,
        )
        for record in history
    ]
    if rows:
        connection.executemany(
            """
            INSERT INTO player_gameweek_history (
                player_fpl_id, fixture_fpl_id, gameweek, kickoff_time, opponent_team_fpl_id,
                was_home, team_h_score, team_a_score, minutes, total_points, goals_scored,
                assists, clean_sheets, goals_conceded, own_goals, penalties_saved,
                penalties_missed, yellow_cards, red_cards, saves, bonus, bps, influence,
                creativity, threat, ict_index, starts, expected_goals, expected_assists,
                expected_goal_involvements, expected_goals_conceded, value, transfers_balance,
                selected, transfers_in, transfers_out
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (player_fpl_id, fixture_fpl_id) DO UPDATE SET
                gameweek = excluded.gameweek,
                kickoff_time = excluded.kickoff_time,
                opponent_team_fpl_id = excluded.opponent_team_fpl_id,
                was_home = excluded.was_home,
                team_h_score = excluded.team_h_score,
                team_a_score = excluded.team_a_score,
                minutes = excluded.minutes,
                total_points = excluded.total_points,
                goals_scored = excluded.goals_scored,
                assists = excluded.assists,
                clean_sheets = excluded.clean_sheets,
                goals_conceded = excluded.goals_conceded,
                own_goals = excluded.own_goals,
                penalties_saved = excluded.penalties_saved,
                penalties_missed = excluded.penalties_missed,
                yellow_cards = excluded.yellow_cards,
                red_cards = excluded.red_cards,
                saves = excluded.saves,
                bonus = excluded.bonus,
                bps = excluded.bps,
                influence = excluded.influence,
                creativity = excluded.creativity,
                threat = excluded.threat,
                ict_index = excluded.ict_index,
                starts = excluded.starts,
                expected_goals = excluded.expected_goals,
                expected_assists = excluded.expected_assists,
                expected_goal_involvements = excluded.expected_goal_involvements,
                expected_goals_conceded = excluded.expected_goals_conceded,
                value = excluded.value,
                transfers_balance = excluded.transfers_balance,
                selected = excluded.selected,
                transfers_in = excluded.transfers_in,
                transfers_out = excluded.transfers_out
            """,
            rows,
        )


def gameweek_history_is_ingested(
    connection: duckdb.DuckDBPyConnection, gameweek: int
) -> bool:
    """Return whether a final gameweek was fully persisted."""
    return connection.execute(
        "SELECT EXISTS (SELECT 1 FROM gameweek_history_ingestions WHERE gameweek = ?)",
        [gameweek],
    ).fetchone()[0]


def mark_gameweek_history_ingested(
    connection: duckdb.DuckDBPyConnection, gameweek: int
) -> None:
    """Record a completed gameweek ingestion inside the caller's transaction."""
    connection.execute(
        "INSERT INTO gameweek_history_ingestions (gameweek) VALUES (?) "
        "ON CONFLICT (gameweek) DO NOTHING",
        [gameweek],
    )


def load_teams(connection: duckdb.DuckDBPyConnection) -> list[Team]:
    """Load canonical teams for provider-event fixture matching."""
    return [
        Team(fpl_id, name, short_name, tuple(aliases))
        for fpl_id, name, short_name, aliases in connection.execute(
            "SELECT fpl_id, name, short_name, aliases FROM teams ORDER BY fpl_id"
        ).fetchall()
    ]


def load_fixtures(connection: duckdb.DuckDBPyConnection) -> list[Fixture]:
    """Load FPL fixtures for provider-event fixture matching."""
    rows = connection.execute(
        """
        SELECT fpl_id, code, event, CAST(kickoff_time AS VARCHAR), finished, finished_provisional,
               minutes, provisional_start_time, started, team_a_fpl_id, team_a_score,
               team_a_difficulty, team_h_fpl_id, team_h_score, team_h_difficulty
        FROM fixtures
        ORDER BY fpl_id
        """
    ).fetchall()
    return [
        Fixture(
            fpl_id=fpl_id,
            code=code,
            event=event,
            kickoff_time=_timestamp_as_iso(kickoff_time),
            finished=finished,
            finished_provisional=finished_provisional,
            minutes=minutes,
            provisional_start_time=provisional_start_time,
            started=started,
            team_a_fpl_id=team_a_fpl_id,
            team_a_score=team_a_score,
            team_a_difficulty=team_a_difficulty,
            team_h_fpl_id=team_h_fpl_id,
            team_h_score=team_h_score,
            team_h_difficulty=team_h_difficulty,
        )
        for (
            fpl_id,
            code,
            event,
            kickoff_time,
            finished,
            finished_provisional,
            minutes,
            provisional_start_time,
            started,
            team_a_fpl_id,
            team_a_score,
            team_a_difficulty,
            team_h_fpl_id,
            team_h_score,
            team_h_difficulty,
        ) in rows
    ]


def load_players(connection: duckdb.DuckDBPyConnection) -> list[Player]:
    """Load FPL player identity for constrained provider-prop matching."""
    return [
        Player(fpl_id, web_name, full_name, team_fpl_id, position, 0, tuple(aliases))
        for fpl_id, web_name, full_name, team_fpl_id, position, aliases in connection.execute(
            """
            SELECT fpl_id, web_name, full_name, team_fpl_id, position, aliases
            FROM players
            ORDER BY fpl_id
            """
        ).fetchall()
    ]


def upsert_odds_provider_events(
    connection: duckdb.DuckDBPyConnection, events: Iterable[OddsProviderEvent]
) -> None:
    """Upsert provider event identity independently of its FPL mapping."""
    rows = [
        (
            event.provider_key,
            event.provider_event_id,
            event.sport_key,
            event.home_team,
            event.away_team,
            event.commence_time,
        )
        for event in events
    ]
    if rows:
        connection.executemany(
            """
            INSERT INTO odds_provider_events (
                provider_key, provider_event_id, sport_key, home_team, away_team, commence_time
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (provider_key, provider_event_id) DO UPDATE SET
                sport_key = excluded.sport_key,
                home_team = excluded.home_team,
                away_team = excluded.away_team,
                commence_time = excluded.commence_time
            """,
            rows,
        )


def upsert_odds_event_fixture_mappings(
    connection: duckdb.DuckDBPyConnection, mappings: Iterable[OddsEventFixtureMapping]
) -> None:
    """Upsert the current provider-event to FPL-fixture mapping."""
    rows = [
        (
            mapping.provider_key,
            mapping.provider_event_id,
            mapping.fpl_fixture_id,
            mapping.match_method,
        )
        for mapping in mappings
    ]
    if rows:
        connection.executemany(
            """
            INSERT INTO odds_event_fixture_mappings (
                provider_key, provider_event_id, fpl_fixture_id, match_method
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT (provider_key, provider_event_id) DO UPDATE SET
                fpl_fixture_id = excluded.fpl_fixture_id,
                match_method = excluded.match_method
            """,
            rows,
        )


def upsert_odds_bookmakers(
    connection: duckdb.DuckDBPyConnection, bookmakers: Iterable[OddsBookmaker]
) -> None:
    """Upsert bookmaker identity for an odds provider."""
    rows = [
        (bookmaker.provider_key, bookmaker.bookmaker_key, bookmaker.title)
        for bookmaker in bookmakers
    ]
    if rows:
        connection.executemany(
            """
            INSERT INTO odds_bookmakers (provider_key, bookmaker_key, title)
            VALUES (?, ?, ?)
            ON CONFLICT (provider_key, bookmaker_key) DO UPDATE SET
                title = excluded.title
            """,
            rows,
        )


def upsert_odds_player_mappings(
    connection: duckdb.DuckDBPyConnection, mappings: Iterable[OddsPlayerMapping]
) -> None:
    """Persist auditable player-prop mappings, including unresolved names."""
    rows = [
        (
            mapping.provider_key,
            mapping.provider_event_id,
            mapping.selection_description,
            mapping.fpl_player_id,
            mapping.match_method,
        )
        for mapping in mappings
    ]
    if rows:
        connection.executemany(
            """
            INSERT INTO odds_player_mappings (
                provider_key, provider_event_id, selection_description,
                fpl_player_id, match_method
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (provider_key, provider_event_id, selection_description) DO UPDATE SET
                fpl_player_id = excluded.fpl_player_id,
                match_method = excluded.match_method
            """,
            rows,
        )


def _snapshot_to_dict(s: OddsOutcomeSnapshot, run_id: str | None = None) -> dict[str, Any]:
    return {
        "provider_key": s.provider_key,
        "provider_event_id": s.provider_event_id,
        "bookmaker_key": s.bookmaker_key,
        "market_key": s.market_key,
        "market_ordinal": s.market_ordinal,
        "market_description": s.market_description,
        "market_team": s.market_team,
        "outcome_ordinal": s.outcome_ordinal,
        "selection_description": s.selection_description,
        "fpl_player_id": s.fpl_player_id,
        "outcome_name": s.outcome_name,
        "american_price": s.american_price,
        "point": s.point,
        "last_update": (
            s.last_update.isoformat()
            if isinstance(s.last_update, datetime)
            else s.last_update
        ),
        "last_change_at": (
            s.last_change_at.isoformat()
            if isinstance(s.last_change_at, datetime)
            else s.last_change_at
        ),
        "captured_at": (
            s.captured_at.isoformat()
            if isinstance(s.captured_at, datetime)
            else str(s.captured_at)
        ),
        "run_id": run_id or s.run_id,
    }


def compute_odds_snapshots_fingerprint(
    provider_key: str, snapshots: Iterable[OddsOutcomeSnapshot]
) -> str:
    """Generate deterministic SHA-256 fingerprint from actual normalized snapshot content."""
    snapshots_list = list(snapshots)
    if not snapshots_list:
        return hashlib.sha256(f"{provider_key}:empty".encode("utf-8")).hexdigest()

    sorted_snapshots = sorted(
        snapshots_list,
        key=lambda s: (
            s.provider_event_id,
            s.bookmaker_key,
            s.market_key,
            s.market_ordinal,
            s.outcome_ordinal,
            s.captured_at.isoformat() if isinstance(s.captured_at, datetime) else str(s.captured_at),
        ),
    )

    h = hashlib.sha256()
    h.update(provider_key.encode("utf-8"))
    for s in sorted_snapshots:
        cap_str = (
            s.captured_at.isoformat()
            if isinstance(s.captured_at, datetime)
            else str(s.captured_at)
        )
        line = (
            f"{s.provider_event_id}|{s.bookmaker_key}|{s.market_key}|{s.market_ordinal}|"
            f"{s.market_description}|{s.market_team or ''}|{s.outcome_ordinal}|"
            f"{s.selection_description or ''}|{s.fpl_player_id or ''}|{s.outcome_name}|"
            f"{s.american_price}|{s.point if s.point is not None else ''}|{cap_str}\n"
        )
        h.update(line.encode("utf-8"))
    return h.hexdigest()


def start_odds_ingestion_run(
    connection: duckdb.DuckDBPyConnection,
    provider_key: str,
    provider_event_ids: Iterable[str] = (),
    *,
    run_id: str | None = None,
    started_at: datetime | None = None,
) -> OddsIngestionRun:
    """Pre-create or register a RUNNING odds ingestion run record in DuckDB."""
    now = datetime.now(timezone.utc)
    started_at = started_at or now
    run_id = run_id or f"run_{started_at.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
    event_ids = tuple(sorted(str(eid) for eid in provider_event_ids))

    row = connection.execute(
        "SELECT status, CAST(started_at AS VARCHAR), provider_event_ids FROM odds_ingestion_runs WHERE run_id = ?",
        [run_id],
    ).fetchone()

    if row is not None:
        existing_status, existing_started_str, existing_events = row[0], row[1], row[2]
        if existing_status in ("COMPLETED", "FAILED"):
            raise RuntimeError(
                f"Cannot restart terminal odds ingestion run {run_id} with status {existing_status}"
            )
        # Preserve original started_at for existing RUNNING run
        if existing_started_str:
            started_at = datetime.fromisoformat(existing_started_str.replace(" ", "T"))
        merged_events = tuple(sorted(set(existing_events or ()).union(event_ids))) if event_ids else tuple(existing_events or ())
        connection.execute(
            """
            UPDATE odds_ingestion_runs SET
                provider_key = ?,
                provider_event_ids = ?
            WHERE run_id = ?
            """,
            [provider_key, list(merged_events), run_id],
        )
        event_ids = merged_events
    else:
        connection.execute(
            """
            INSERT INTO odds_ingestion_runs (
                run_id, provider_key, provider_event_ids, input_fingerprint,
                status, failure_stage, error_message, records_fetched,
                records_parsed, records_inserted, records_updated, records_rejected,
                started_at, finished_at, duration_ms, retry_of_run_id, is_retry
            ) VALUES (?, ?, ?, NULL, 'RUNNING', NULL, NULL, 0, 0, 0, 0, 0, ?, NULL, NULL, NULL, FALSE)
            """,
            [run_id, provider_key, list(event_ids), started_at],
        )

    return OddsIngestionRun(
        run_id=run_id,
        provider_key=provider_key,
        provider_event_ids=event_ids,
        input_fingerprint=None,
        status="RUNNING",
        failure_stage=None,
        error_message=None,
        records_fetched=0,
        records_parsed=0,
        records_inserted=0,
        records_updated=0,
        records_rejected=0,
        started_at=started_at,
        finished_at=None,
        duration_ms=None,
        retry_of_run_id=None,
        is_retry=False,
    )


def fail_odds_ingestion_run(
    connection: duckdb.DuckDBPyConnection,
    run_id: str,
    failure_stage: str,
    error_message: str,
    *,
    finished_at: datetime | None = None,
    rollback: bool = False,
) -> None:
    """Record an odds ingestion run failure with stage and error details."""
    finished_at = finished_at or datetime.now(timezone.utc)
    if rollback:
        try:
            connection.execute("ROLLBACK")
        except Exception:
            pass

    row = connection.execute(
        "SELECT status, CAST(started_at AS VARCHAR) FROM odds_ingestion_runs WHERE run_id = ?",
        [run_id],
    ).fetchone()
    if not row:
        return
    status, started_str = row[0], row[1]
    if status in ("COMPLETED", "FAILED"):
        return

    duration_ms = None
    if started_str:
        started = datetime.fromisoformat(started_str.replace(" ", "T"))
        duration_ms = (finished_at - started).total_seconds() * 1000.0

    connection.execute(
        """
        UPDATE odds_ingestion_runs SET
            status = 'FAILED',
            failure_stage = ?,
            error_message = ?,
            finished_at = ?,
            duration_ms = ?
        WHERE run_id = ?
        """,
        [failure_stage, str(error_message), finished_at, duration_ms, run_id],
    )


def complete_empty_odds_ingestion_run(
    connection: duckdb.DuckDBPyConnection,
    run_id: str,
    provider_key: str,
    provider_event_ids: Iterable[str] = (),
    *,
    finished_at: datetime | None = None,
) -> OddsIngestionRun:
    """Mark an odds ingestion run with 0 records as COMPLETED."""
    finished_at = finished_at or datetime.now(timezone.utc)
    row = connection.execute(
        "SELECT status, CAST(started_at AS VARCHAR) FROM odds_ingestion_runs WHERE run_id = ?",
        [run_id],
    ).fetchone()
    if not row:
        raise RuntimeError(f"Odds ingestion run {run_id} does not exist")
    status, started_str = row[0], row[1]
    if status in ("COMPLETED", "FAILED"):
        raise RuntimeError(
            f"Cannot complete terminal odds ingestion run {run_id} with status {status}"
        )

    started_at = datetime.fromisoformat(started_str.replace(" ", "T")) if started_str else finished_at
    duration_ms = (finished_at - started_at).total_seconds() * 1000.0
    fingerprint = compute_odds_snapshots_fingerprint(provider_key, [])
    event_ids = tuple(sorted(str(eid) for eid in provider_event_ids))
    connection.execute(
        """
        UPDATE odds_ingestion_runs SET
            status = 'COMPLETED',
            provider_event_ids = ?,
            input_fingerprint = ?,
            records_fetched = 0,
            records_parsed = 0,
            records_inserted = 0,
            records_updated = 0,
            records_rejected = 0,
            finished_at = ?,
            duration_ms = ?,
            retry_of_run_id = NULL,
            is_retry = FALSE
        WHERE run_id = ?
        """,
        [list(event_ids), fingerprint, finished_at, duration_ms, run_id],
    )
    return OddsIngestionRun(
        run_id=run_id,
        provider_key=provider_key,
        provider_event_ids=event_ids,
        input_fingerprint=fingerprint,
        status="COMPLETED",
        failure_stage=None,
        error_message=None,
        records_fetched=0,
        records_parsed=0,
        records_inserted=0,
        records_updated=0,
        records_rejected=0,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        retry_of_run_id=None,
        is_retry=False,
    )


def insert_odds_outcome_snapshots(
    connection: duckdb.DuckDBPyConnection,
    snapshots: Iterable[OddsOutcomeSnapshot],
    run_id: str | None = None,
) -> None:
    """Append timestamped bookmaker outcomes using vectorized staging."""
    snapshots_list = list(snapshots)
    if not snapshots_list:
        return

    with tempfile.NamedTemporaryFile("w+", suffix=".ndjson", delete=True) as tmp:
        for snapshot in snapshots_list:
            tmp.write(json.dumps(_snapshot_to_dict(snapshot, run_id=run_id)) + "\n")
        tmp.flush()

        stage_table = f"stage_odds_{uuid.uuid4().hex[:8]}"
        connection.execute(
            f"""
            CREATE TEMPORARY TABLE {stage_table} AS
            SELECT * FROM read_json(?, columns={{
                'provider_key': 'VARCHAR',
                'provider_event_id': 'VARCHAR',
                'bookmaker_key': 'VARCHAR',
                'market_key': 'VARCHAR',
                'market_ordinal': 'INTEGER',
                'market_description': 'VARCHAR',
                'market_team': 'VARCHAR',
                'outcome_ordinal': 'INTEGER',
                'selection_description': 'VARCHAR',
                'fpl_player_id': 'BIGINT',
                'outcome_name': 'VARCHAR',
                'american_price': 'INTEGER',
                'point': 'DOUBLE',
                'last_update': 'TIMESTAMPTZ',
                'last_change_at': 'TIMESTAMPTZ',
                'captured_at': 'TIMESTAMPTZ',
                'run_id': 'VARCHAR'
            }});
            """,
            [tmp.name],
        )
        try:
            conflict_count = connection.execute(
                f"""
                SELECT count(*)
                FROM {stage_table} AS s
                JOIN odds_outcome_snapshots AS t
                  ON s.provider_key = t.provider_key
                 AND s.provider_event_id = t.provider_event_id
                 AND s.bookmaker_key = t.bookmaker_key
                 AND s.market_key = t.market_key
                 AND s.market_ordinal = t.market_ordinal
                 AND s.outcome_ordinal = t.outcome_ordinal
                 AND s.captured_at = t.captured_at
                WHERE s.american_price != t.american_price
                   OR s.point IS DISTINCT FROM t.point
                   OR s.outcome_name IS DISTINCT FROM t.outcome_name
                """
            ).fetchone()[0]
            if conflict_count > 0:
                raise IngestionValidationError(
                    f"Found {conflict_count} conflicting odds records with different prices for existing snapshot keys"
                )

            connection.execute(
                f"""
                INSERT INTO odds_outcome_snapshots (
                    provider_key, provider_event_id, bookmaker_key, market_key, market_ordinal,
                    market_description, market_team, outcome_ordinal, selection_description,
                    fpl_player_id, outcome_name, american_price, point, last_update,
                    last_change_at, captured_at, run_id
                )
                SELECT
                    provider_key, provider_event_id, bookmaker_key, market_key, market_ordinal,
                    market_description, market_team, outcome_ordinal, selection_description,
                    fpl_player_id, outcome_name, american_price, point, last_update,
                    last_change_at, captured_at, run_id
                FROM {stage_table}
                ON CONFLICT (
                    provider_key, provider_event_id, bookmaker_key, market_key,
                    market_ordinal, outcome_ordinal, captured_at
                ) DO UPDATE SET
                    fpl_player_id = COALESCE(
                        excluded.fpl_player_id, odds_outcome_snapshots.fpl_player_id
                    ),
                    run_id = COALESCE(odds_outcome_snapshots.run_id, excluded.run_id);
                """
            )
        finally:
            connection.execute(f"DROP TABLE IF EXISTS {stage_table}")


def store_odds_snapshot_bundle(
    connection: duckdb.DuckDBPyConnection,
    provider_key: str,
    events: Iterable[OddsProviderEvent],
    event_fixture_mappings: Iterable[OddsEventFixtureMapping],
    player_mappings: Iterable[OddsPlayerMapping],
    bookmakers: Iterable[OddsBookmaker],
    snapshots: Iterable[OddsOutcomeSnapshot],
    *,
    records_fetched: int | None = None,
    run_id: str | None = None,
) -> OddsIngestionRun:
    """Atomically ingest an odds snapshot bundle with vectorized staging, validation, and run tracking."""
    started_at = datetime.now(timezone.utc)
    run_id = run_id or f"run_{started_at.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"

    # Step 1: Pre-create or ensure RUNNING record in DuckDB immediately
    run_record = start_odds_ingestion_run(
        connection, provider_key=provider_key, run_id=run_id, started_at=started_at
    )
    started_at = run_record.started_at

    stage_table: str | None = None
    failure_stage = "prepare_inputs"
    in_transaction = False
    try:
        failure_stage = "prepare_inputs"
        events_list = list(events)
        event_fixture_mappings_list = list(event_fixture_mappings)
        player_mappings_list = list(player_mappings)
        bookmakers_list = list(bookmakers)
        snapshots_list = list(snapshots)

        provider_event_ids = tuple(sorted({e.provider_event_id for e in events_list}))
        records_parsed = len(snapshots_list)
        records_fetched = records_fetched if records_fetched is not None else records_parsed

        failure_stage = "compute_fingerprint"
        input_fingerprint = compute_odds_snapshots_fingerprint(provider_key, snapshots_list)

        connection.execute(
            """
            UPDATE odds_ingestion_runs SET
                provider_event_ids = ?,
                input_fingerprint = ?,
                records_fetched = ?,
                records_parsed = ?
            WHERE run_id = ?
            """,
            [list(provider_event_ids), input_fingerprint, records_fetched, records_parsed, run_id],
        )

        stage_table = f"stage_odds_{uuid.uuid4().hex[:8]}"
        failure_stage = "staging"
        connection.execute("BEGIN TRANSACTION")
        in_transaction = True

        if snapshots_list:
            with tempfile.NamedTemporaryFile("w+", suffix=".ndjson", delete=True) as tmp:
                for snapshot in snapshots_list:
                    tmp.write(json.dumps(_snapshot_to_dict(snapshot, run_id=run_id)) + "\n")
                tmp.flush()

                connection.execute(
                    f"""
                    CREATE TEMPORARY TABLE {stage_table} AS
                    SELECT * FROM read_json(?, columns={{
                        'provider_key': 'VARCHAR',
                        'provider_event_id': 'VARCHAR',
                        'bookmaker_key': 'VARCHAR',
                        'market_key': 'VARCHAR',
                        'market_ordinal': 'INTEGER',
                        'market_description': 'VARCHAR',
                        'market_team': 'VARCHAR',
                        'outcome_ordinal': 'INTEGER',
                        'selection_description': 'VARCHAR',
                        'fpl_player_id': 'BIGINT',
                        'outcome_name': 'VARCHAR',
                        'american_price': 'INTEGER',
                        'point': 'DOUBLE',
                        'last_update': 'TIMESTAMPTZ',
                        'last_change_at': 'TIMESTAMPTZ',
                        'captured_at': 'TIMESTAMPTZ',
                        'run_id': 'VARCHAR'
                    }});
                    """,
                    [tmp.name],
                )

            # Validation 1: Record count matches input
            failure_stage = "validation_counts"
            staged_count = connection.execute(f"SELECT count(*) FROM {stage_table}").fetchone()[0]
            if staged_count != len(snapshots_list):
                raise IngestionValidationError(
                    f"Staged record count ({staged_count}) does not match parsed count ({len(snapshots_list)})"
                )

            # Validation 2: Required non-null fields
            failure_stage = "validation_required_fields"
            null_count = connection.execute(
                f"""
                SELECT count(*) FROM {stage_table}
                WHERE provider_key IS NULL
                   OR provider_event_id IS NULL
                   OR bookmaker_key IS NULL
                   OR market_key IS NULL
                   OR market_ordinal IS NULL
                   OR outcome_ordinal IS NULL
                   OR outcome_name IS NULL
                   OR american_price IS NULL
                   OR captured_at IS NULL
                """
            ).fetchone()[0]
            if null_count > 0:
                raise IngestionValidationError(
                    f"Found {null_count} records with NULL in required primary key or price fields"
                )

            # Validation 3: Duplicate primary keys in staging batch
            failure_stage = "validation_duplicate_keys"
            duplicate_key_count = connection.execute(
                f"""
                SELECT count(*) FROM (
                    SELECT provider_key, provider_event_id, bookmaker_key, market_key,
                            market_ordinal, outcome_ordinal, captured_at
                    FROM {stage_table}
                    GROUP BY 1, 2, 3, 4, 5, 6, 7
                    HAVING count(*) > 1
                )
                """
            ).fetchone()[0]
            if duplicate_key_count > 0:
                raise IngestionValidationError(
                    f"Found {duplicate_key_count} duplicate primary key combinations in staging batch"
                )

            # Validation 4: Conflicting odds prices against existing snapshots
            failure_stage = "validation_conflicting_prices"
            conflict_row = connection.execute(
                f"""
                SELECT count(*),
                       min(s.provider_event_id),
                       min(s.bookmaker_key),
                       min(s.market_key)
                FROM {stage_table} AS s
                JOIN odds_outcome_snapshots AS t
                  ON s.provider_key = t.provider_key
                 AND s.provider_event_id = t.provider_event_id
                 AND s.bookmaker_key = t.bookmaker_key
                 AND s.market_key = t.market_key
                 AND s.market_ordinal = t.market_ordinal
                 AND s.outcome_ordinal = t.outcome_ordinal
                 AND s.captured_at = t.captured_at
                WHERE s.american_price != t.american_price
                   OR s.point IS DISTINCT FROM t.point
                   OR s.outcome_name IS DISTINCT FROM t.outcome_name
                """
            ).fetchone()
            conflict_count = conflict_row[0] if conflict_row else 0
            if conflict_count > 0:
                raise IngestionValidationError(
                    f"Found {conflict_count} conflicting odds records with different prices for existing snapshot keys "
                    f"(event={conflict_row[1]}, bookmaker={conflict_row[2]}, market={conflict_row[3]})"
                )

            # Upsert metadata inside the transaction
            failure_stage = "upsert_metadata"
            upsert_odds_provider_events(connection, events_list)
            upsert_odds_event_fixture_mappings(connection, event_fixture_mappings_list)
            upsert_odds_player_mappings(connection, player_mappings_list)
            upsert_odds_bookmakers(connection, bookmakers_list)

            # Insert outcome snapshots
            failure_stage = "insert_snapshots"
            records_updated = connection.execute(
                f"""
                SELECT count(*) FROM {stage_table} AS s
                JOIN odds_outcome_snapshots AS t
                  ON s.provider_key = t.provider_key
                 AND s.provider_event_id = t.provider_event_id
                 AND s.bookmaker_key = t.bookmaker_key
                 AND s.market_key = t.market_key
                 AND s.market_ordinal = t.market_ordinal
                 AND s.outcome_ordinal = t.outcome_ordinal
                 AND s.captured_at = t.captured_at
                """
            ).fetchone()[0]
            records_inserted = staged_count - records_updated

            connection.execute(
                f"""
                INSERT INTO odds_outcome_snapshots (
                    provider_key, provider_event_id, bookmaker_key, market_key, market_ordinal,
                    market_description, market_team, outcome_ordinal, selection_description,
                    fpl_player_id, outcome_name, american_price, point, last_update,
                    last_change_at, captured_at, run_id
                )
                SELECT
                    provider_key, provider_event_id, bookmaker_key, market_key, market_ordinal,
                    market_description, market_team, outcome_ordinal, selection_description,
                    fpl_player_id, outcome_name, american_price, point, last_update,
                    last_change_at, captured_at, run_id
                FROM {stage_table}
                ON CONFLICT (
                    provider_key, provider_event_id, bookmaker_key, market_key,
                    market_ordinal, outcome_ordinal, captured_at
                ) DO UPDATE SET
                    fpl_player_id = COALESCE(
                        excluded.fpl_player_id, odds_outcome_snapshots.fpl_player_id
                    ),
                    run_id = COALESCE(odds_outcome_snapshots.run_id, excluded.run_id);
                """
            )
            connection.execute(f"DROP TABLE {stage_table}")
            stage_table = None
        else:
            failure_stage = "upsert_metadata"
            upsert_odds_provider_events(connection, events_list)
            upsert_odds_event_fixture_mappings(connection, event_fixture_mappings_list)
            upsert_odds_player_mappings(connection, player_mappings_list)
            upsert_odds_bookmakers(connection, bookmakers_list)
            records_inserted = 0
            records_updated = 0

        # Check for retry of prior run
        retry_of_run_id: str | None = None
        is_retry: bool = False
        earlier_run = connection.execute(
            """
            SELECT run_id FROM odds_ingestion_runs
            WHERE input_fingerprint = ? AND status = 'COMPLETED' AND run_id != ?
            ORDER BY started_at ASC LIMIT 1
            """,
            [input_fingerprint, run_id],
        ).fetchone()
        if earlier_run:
            retry_of_run_id = earlier_run[0]
            is_retry = True
        elif snapshots_list and records_inserted == 0 and records_updated == len(snapshots_list):
            owner_row = connection.execute(
                """
                SELECT run_id FROM odds_outcome_snapshots
                WHERE provider_key = ?
                  AND provider_event_id = ?
                  AND bookmaker_key = ?
                  AND market_key = ?
                  AND market_ordinal = ?
                  AND outcome_ordinal = ?
                  AND captured_at = ?
                  AND run_id IS NOT NULL
                  AND run_id != ?
                LIMIT 1
                """,
                [
                    snapshots_list[0].provider_key,
                    snapshots_list[0].provider_event_id,
                    snapshots_list[0].bookmaker_key,
                    snapshots_list[0].market_key,
                    snapshots_list[0].market_ordinal,
                    snapshots_list[0].outcome_ordinal,
                    snapshots_list[0].captured_at,
                    run_id,
                ],
            ).fetchone()
            if owner_row:
                retry_of_run_id = owner_row[0]
                is_retry = True

        # Mark COMPLETED inside transaction
        failure_stage = "commit"
        finished_at = datetime.now(timezone.utc)
        duration_ms = (finished_at - started_at).total_seconds() * 1000.0

        connection.execute(
            """
            UPDATE odds_ingestion_runs SET
                status = 'COMPLETED',
                records_inserted = ?,
                records_updated = ?,
                records_rejected = 0,
                finished_at = ?,
                duration_ms = ?,
                retry_of_run_id = ?,
                is_retry = ?
            WHERE run_id = ?
            """,
            [records_inserted, records_updated, finished_at, duration_ms, retry_of_run_id, is_retry, run_id],
        )
        connection.execute("COMMIT")
        in_transaction = False

        return OddsIngestionRun(
            run_id=run_id,
            provider_key=provider_key,
            provider_event_ids=provider_event_ids,
            input_fingerprint=input_fingerprint,
            status="COMPLETED",
            failure_stage=None,
            error_message=None,
            records_fetched=records_fetched,
            records_parsed=records_parsed,
            records_inserted=records_inserted,
            records_updated=records_updated,
            records_rejected=0,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            retry_of_run_id=retry_of_run_id,
            is_retry=is_retry,
        )
    except Exception as exc:
        if in_transaction:
            try:
                connection.execute("ROLLBACK")
            except Exception:
                pass
        if stage_table:
            try:
                connection.execute(f"DROP TABLE IF EXISTS {stage_table}")
            except Exception:
                pass
        fail_odds_ingestion_run(connection, run_id, failure_stage, str(exc))
        raise


def load_odds_ingestion_run(
    connection: duckdb.DuckDBPyConnection, run_id: str
) -> OddsIngestionRun | None:
    """Retrieve an odds ingestion run record by ID."""
    row = connection.execute(
        """
        SELECT
            run_id, provider_key, provider_event_ids, input_fingerprint,
            status, failure_stage, error_message, records_fetched,
            records_parsed, records_inserted, records_updated, records_rejected,
            CAST(started_at AS VARCHAR), CAST(finished_at AS VARCHAR), duration_ms,
            retry_of_run_id, is_retry
        FROM odds_ingestion_runs
        WHERE run_id = ?
        """,
        [run_id],
    ).fetchone()
    if row is None:
        return None
    return OddsIngestionRun(
        run_id=row[0],
        provider_key=row[1],
        provider_event_ids=tuple(row[2]) if row[2] is not None else (),
        input_fingerprint=row[3],
        status=row[4],
        failure_stage=row[5],
        error_message=row[6],
        records_fetched=row[7],
        records_parsed=row[8],
        records_inserted=row[9],
        records_updated=row[10],
        records_rejected=row[11],
        started_at=datetime.fromisoformat(row[12].replace(" ", "T")) if row[12] else None,
        finished_at=datetime.fromisoformat(row[13].replace(" ", "T")) if row[13] else None,
        duration_ms=row[14],
        retry_of_run_id=row[15],
        is_retry=bool(row[16]) if row[16] is not None else False,
    )


from .markets import latest_odds_snapshot_provenance


def insert_team_goal_projection(
    connection: duckdb.DuckDBPyConnection, projection: TeamGoalProjection
) -> None:
    """Persist one live team-goal model snapshot and its market comparisons."""
    model = projection.model
    connection.execute(
        """
        INSERT INTO team_goal_model_snapshots (
            fixture_fpl_id, generated_at, provider_key, provider_event_ids,
            source_captured_at_min, source_captured_at_max, source_market_snapshot_count,
            lambda_home, lambda_away, p_clean_sheet_home, p_clean_sheet_away, fit_loss
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (fixture_fpl_id, generated_at) DO UPDATE SET
            provider_key = excluded.provider_key,
            provider_event_ids = excluded.provider_event_ids,
            source_captured_at_min = excluded.source_captured_at_min,
            source_captured_at_max = excluded.source_captured_at_max,
            source_market_snapshot_count = excluded.source_market_snapshot_count,
            lambda_home = excluded.lambda_home,
            lambda_away = excluded.lambda_away,
            p_clean_sheet_home = excluded.p_clean_sheet_home,
            p_clean_sheet_away = excluded.p_clean_sheet_away,
            fit_loss = excluded.fit_loss
        """,
        [
            projection.fixture_fpl_id,
            projection.generated_at,
            projection.provider_key,
            list(projection.provider_event_ids),
            projection.source_captured_at_min,
            projection.source_captured_at_max,
            projection.source_market_snapshot_count,
            model.lambda_home,
            model.lambda_away,
            model.p_clean_sheet_home,
            model.p_clean_sheet_away,
            projection.fit_loss,
        ],
    )
    comparisons = [
        (
            projection.fixture_fpl_id,
            projection.generated_at,
            comparison.market,
            comparison.outcome,
            comparison.market_prob,
            comparison.model_prob,
            comparison.n_books,
        )
        for comparison in projection.comparisons
    ]
    if comparisons:
        connection.executemany(
            """
            INSERT INTO team_goal_model_market_comparisons (
                fixture_fpl_id, generated_at, market, outcome, market_prob, model_prob, n_books
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (fixture_fpl_id, generated_at, market, outcome) DO UPDATE SET
                market_prob = excluded.market_prob,
                model_prob = excluded.model_prob,
                n_books = excluded.n_books
            """,
            comparisons,
        )


def _timestamp_as_iso(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        if value.endswith("+00:00"):
            return value.removesuffix("+00:00") + "Z"
        if value.endswith("+00"):
            return value.removesuffix("+00") + "Z"
        return value
    return value.isoformat().replace("+00:00", "Z")
