"""Focused Step 3 tests for DuckDB odds snapshots to fair probabilities."""
from datetime import datetime, timedelta, timezone

import pytest

from fpl_alpha.markets import (
    american_to_decimal,
    consensus_from_latest_odds,
    devig_proportional,
)
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


def _snapshot(
    captured_at: datetime,
    bookmaker_key: str,
    market_key: str,
    market_ordinal: int,
    outcome_name: str,
    american_price: int,
    *,
    point: float | None = None,
    market_description: str | None = None,
    market_team: str | None = None,
) -> OddsOutcomeSnapshot:
    return OddsOutcomeSnapshot(
        provider_key="propline",
        provider_event_id="event-1",
        bookmaker_key=bookmaker_key,
        market_key=market_key,
        market_ordinal=market_ordinal,
        market_description=market_description,
        market_team=market_team,
        outcome_ordinal={"Chelsea": 0, "Draw": 1, "Hull City": 2, "Over": 0, "Under": 1, "Yes": 0, "No": 1}[outcome_name],
        selection_description=None,
        fpl_player_id=None,
        outcome_name=outcome_name,
        american_price=american_price,
        point=point,
        last_update=None,
        last_change_at=None,
        captured_at=captured_at,
    )


def _seed_odds(connection, captured_at: datetime) -> None:
    upsert_teams(connection, [Team(1, "Chelsea", "CHE"), Team(2, "Hull City", "HUL")])
    upsert_fixtures(
        connection,
        [
            Fixture(
                33, 123, 4, "2026-09-12T14:00:00Z", False, False, 0, False, False,
                2, None, 3, 1, None, 2,
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
    upsert_odds_bookmakers(
        connection,
        [
            OddsBookmaker("propline", "book-1", "Book 1"),
            OddsBookmaker("propline", "book-2", "Book 2"),
            OddsBookmaker("propline", "book-3", "Book 3"),
        ],
    )

    stale = captured_at - timedelta(minutes=10)
    rows = [
        _snapshot(stale, "book-1", "h2h", 0, "Chelsea", 150),
        _snapshot(stale, "book-1", "h2h", 0, "Draw", 250),
        _snapshot(stale, "book-1", "h2h", 0, "Hull City", 250),
        _snapshot(captured_at, "book-1", "h2h", 0, "Chelsea", -100),
        _snapshot(captured_at, "book-1", "h2h", 0, "Draw", 300),
        _snapshot(captured_at, "book-1", "h2h", 0, "Hull City", 300),
        _snapshot(captured_at, "book-2", "h2h", 0, "Chelsea", -120),
        _snapshot(captured_at, "book-2", "h2h", 0, "Draw", 330),
        _snapshot(captured_at, "book-2", "h2h", 0, "Hull City", 350),
        # Missing draw: this book must not enter the consensus.
        _snapshot(captured_at, "book-3", "h2h", 0, "Chelsea", -110),
        _snapshot(captured_at, "book-3", "h2h", 0, "Hull City", 325),
        _snapshot(captured_at, "book-1", "totals", 1, "Over", -110, point=2.5, market_description="Total Goals"),
        _snapshot(captured_at, "book-1", "totals", 1, "Under", -110, point=2.5, market_description="Total Goals"),
        # Team total must not be mixed into the match total market.
        _snapshot(captured_at, "book-1", "totals", 2, "Over", 120, point=2.5, market_description="Chelsea Team Total", market_team="Chelsea"),
        _snapshot(captured_at, "book-1", "totals", 2, "Under", -150, point=2.5, market_description="Chelsea Team Total", market_team="Chelsea"),
        _snapshot(captured_at, "book-1", "both_teams_to_score", 3, "Yes", -105),
        _snapshot(captured_at, "book-1", "both_teams_to_score", 3, "No", -115),
    ]
    insert_odds_outcome_snapshots(connection, rows)


def test_american_to_decimal():
    assert american_to_decimal(150) == 2.5
    assert american_to_decimal(-200) == 1.5
    with pytest.raises(ValueError, match="cannot be zero"):
        american_to_decimal(0)


def test_consensus_from_latest_complete_match_odds(tmp_path):
    captured_at = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)
    connection = open_database(tmp_path / "fpl_alpha.duckdb")
    try:
        _seed_odds(connection, captured_at)
        probabilities = consensus_from_latest_odds(connection, 33)
    finally:
        connection.close()

    by_market = {}
    for probability in probabilities:
        by_market.setdefault(probability.market, {})[probability.outcome] = probability

    assert set(by_market) == {"h2h", "btts", "totals_2.5"}
    assert all(probability.n_books == 2 for probability in by_market["h2h"].values())
    assert all(probability.n_books == 1 for probability in by_market["btts"].values())
    assert all(probability.n_books == 1 for probability in by_market["totals_2.5"].values())
    assert sum(probability.prob for probability in by_market["h2h"].values()) == pytest.approx(1)

    expected_home = sum(
        (
            devig_proportional([2.0, 4.0, 4.0])[0],
            devig_proportional([american_to_decimal(-120), 4.3, 4.5])[0],
        )
    ) / 2
    assert by_market["h2h"]["home"].prob == pytest.approx(expected_home)
