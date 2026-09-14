"""DuckDB persistence for normalized official FPL data.

Raw API responses remain cache-owned by :mod:`fpl_alpha.cache`. This module
stores normalized records only; callers supply observation timestamps so stored
snapshots are reproducible.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import duckdb

from .config import DATA
from .schemas import (
    Fixture,
    OddsBookmaker,
    OddsEventFixtureMapping,
    OddsOutcomeSnapshot,
    OddsPlayerMapping,
    OddsProviderEvent,
    Player,
    PlayerGameweekHistory,
    PlayerSnapshot,
    Team,
)

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
            PRIMARY KEY (
                provider_key, provider_event_id, bookmaker_key, market_key,
                market_ordinal, outcome_ordinal, captured_at
            )
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


def insert_odds_outcome_snapshots(
    connection: duckdb.DuckDBPyConnection, snapshots: Iterable[OddsOutcomeSnapshot]
) -> None:
    """Append timestamped bookmaker outcomes without replacing past prices."""
    rows = [
        (
            snapshot.provider_key,
            snapshot.provider_event_id,
            snapshot.bookmaker_key,
            snapshot.market_key,
            snapshot.market_ordinal,
            snapshot.market_description,
            snapshot.market_team,
            snapshot.outcome_ordinal,
            snapshot.selection_description,
            snapshot.fpl_player_id,
            snapshot.outcome_name,
            snapshot.american_price,
            snapshot.point,
            snapshot.last_update,
            snapshot.last_change_at,
            snapshot.captured_at,
        )
        for snapshot in snapshots
    ]
    if rows:
        connection.executemany(
            """
            INSERT INTO odds_outcome_snapshots (
                provider_key, provider_event_id, bookmaker_key, market_key, market_ordinal,
                market_description, market_team, outcome_ordinal, selection_description,
                fpl_player_id, outcome_name, american_price, point, last_update,
                last_change_at, captured_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT DO UPDATE SET
                fpl_player_id = COALESCE(
                    excluded.fpl_player_id, odds_outcome_snapshots.fpl_player_id
                )
            """,
            rows,
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
