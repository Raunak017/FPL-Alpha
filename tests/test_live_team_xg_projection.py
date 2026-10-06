"""Focused live DuckDB consensus -> team-xG projection tests."""
from datetime import datetime, timezone

import pytest

from fpl_alpha.schemas import (
    Fixture,
    OddsBookmaker,
    OddsEventFixtureMapping,
    OddsOutcomeSnapshot,
    OddsProviderEvent,
    Team,
)
from fpl_alpha.storage import (
    insert_odds_outcome_snapshots,
    open_database,
    upsert_fixtures,
    upsert_odds_bookmakers,
    upsert_odds_event_fixture_mappings,
    upsert_odds_provider_events,
    upsert_teams,
)
from fpl_alpha.team_xg import (
    build_and_persist_team_goal_projection,
    upcoming_fixture_ids_with_odds,
)


def _snapshot(
    captured_at: datetime,
    market_key: str,
    market_ordinal: int,
    outcome_ordinal: int,
    outcome_name: str,
    american_price: int,
    *,
    point: float | None = None,
) -> OddsOutcomeSnapshot:
    return OddsOutcomeSnapshot(
        provider_key="propline",
        provider_event_id="event-1",
        bookmaker_key="book-1",
        market_key=market_key,
        market_ordinal=market_ordinal,
        market_description="Total Goals" if market_key == "totals" else None,
        market_team=None,
        outcome_ordinal=outcome_ordinal,
        selection_description=None,
        fpl_player_id=None,
        outcome_name=outcome_name,
        american_price=american_price,
        point=point,
        last_update=None,
        last_change_at=None,
        captured_at=captured_at,
    )


def test_live_consensus_team_goal_projection_is_persisted(tmp_path):
    captured_at = datetime(2026, 9, 13, 12, tzinfo=timezone.utc)
    generated_at = datetime(2026, 9, 13, 12, 5, tzinfo=timezone.utc)
    connection = open_database(tmp_path / "fpl_alpha.duckdb")
    try:
        upsert_teams(connection, [Team(1, "Chelsea", "CHE"), Team(2, "Hull City", "HUL")])
        upsert_fixtures(
            connection,
            [
                Fixture(
                    33, 123, 4, "2026-09-12T14:00:00Z", False, False, 0, False,
                    False, 2, None, 3, 1, None, 2,
                )
            ],
        )
        upsert_odds_provider_events(
            connection,
            [
                OddsProviderEvent(
                    "propline", "event-1", "soccer_epl", "Chelsea FC", "Hull City",
                    "2026-09-12T14:00:00Z",
                )
            ],
        )
        upsert_odds_event_fixture_mappings(
            connection,
            [OddsEventFixtureMapping("propline", "event-1", 33, "home_away_kickoff_exact")],
        )
        upsert_odds_bookmakers(connection, [OddsBookmaker("propline", "book-1", "Book 1")])
        insert_odds_outcome_snapshots(
            connection,
            [
                _snapshot(captured_at, "h2h", 0, 0, "Chelsea", -100),
                _snapshot(captured_at, "h2h", 0, 1, "Draw", 300),
                _snapshot(captured_at, "h2h", 0, 2, "Hull City", 300),
                _snapshot(captured_at, "totals", 1, 0, "Over", -110, point=2.5),
                _snapshot(captured_at, "totals", 1, 1, "Under", -110, point=2.5),
                _snapshot(captured_at, "both_teams_to_score", 2, 0, "Yes", -105),
                _snapshot(captured_at, "both_teams_to_score", 2, 1, "No", -115),
            ],
        )

        assert upcoming_fixture_ids_with_odds(
            connection, now=datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
        ) == [33]

        projection = build_and_persist_team_goal_projection(
            connection, 33, generated_at=generated_at
        )
        snapshot = connection.execute(
            """
            SELECT lambda_home, lambda_away, p_clean_sheet_home, p_clean_sheet_away,
                   fit_loss, provider_event_ids, source_market_snapshot_count
            FROM team_goal_model_snapshots
            WHERE fixture_fpl_id = 33 AND generated_at = ?
            """,
            [generated_at],
        ).fetchone()
        comparisons = connection.execute(
            """
            SELECT market, outcome
            FROM team_goal_model_market_comparisons
            WHERE fixture_fpl_id = 33 AND generated_at = ?
            ORDER BY market, outcome
            """,
            [generated_at],
        ).fetchall()
    finally:
        connection.close()

    assert projection.model.home_team_fpl_id == 1
    assert projection.model.away_team_fpl_id == 2
    assert projection.provider_event_ids == ("event-1",)
    assert projection.source_captured_at_min == captured_at
    assert projection.source_captured_at_max == captured_at
    assert projection.source_market_snapshot_count == 3
    assert projection.fit_loss >= 0
    assert len(projection.comparisons) == 7
    assert snapshot[0] > 0 and snapshot[1] > 0
    assert snapshot[2] == pytest.approx(projection.model.p_clean_sheet_home)
    assert snapshot[3] == pytest.approx(projection.model.p_clean_sheet_away)
    assert snapshot[4] == pytest.approx(projection.fit_loss)
    assert snapshot[5] == ["event-1"]
    assert snapshot[6] == 3
    assert comparisons == [
        ("btts", "no"),
        ("btts", "yes"),
        ("h2h", "away"),
        ("h2h", "draw"),
        ("h2h", "home"),
        ("totals_2.5", "over"),
        ("totals_2.5", "under"),
    ]
