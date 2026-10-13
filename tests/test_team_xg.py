"""Tests for the market-implied team-xG solver (Plan step 4)."""
import math

import pytest

from fpl_alpha.schemas import MarketProb
from fpl_alpha.team_xg import fit_team_goals, model_probs, poisson_pmf, score_matrix


def test_poisson_pmf_known_values():
    assert poisson_pmf(0, 0.9) == pytest.approx(math.exp(-0.9))
    # A Poisson pmf must sum to ~1 over its support.
    assert sum(poisson_pmf(k, 1.7) for k in range(30)) == pytest.approx(1.0, abs=1e-9)


def test_score_matrix_sums_to_one():
    total = sum(score_matrix(1.8, 1.1).values())
    assert total == pytest.approx(1.0, abs=1e-4)


def test_model_probs_1x2_sums_to_one():
    p = model_probs(1.5, 1.2)
    assert p["home"] + p["draw"] + p["away"] == pytest.approx(1.0, abs=1e-4)


def _probs_to_markets(lh: float, la: float, line: float = 2.5) -> list[MarketProb]:
    """Generate the fair market probs a fixture with these lambdas would show."""
    p = model_probs(lh, la, total_line=line)
    return [
        MarketProb("F1", "h2h", "home", p["home"]),
        MarketProb("F1", "h2h", "draw", p["draw"]),
        MarketProb("F1", "h2h", "away", p["away"]),
        MarketProb("F1", f"totals_over_{line}", "over", p["over"]),
        MarketProb("F1", f"totals_under_{line}", "under", p["under"]),
    ]


def test_fit_recovers_lambdas_round_trip():
    # If the market probs came from a Poisson (lh, la), the fitter should recover them.
    true_lh, true_la = 1.8, 0.9
    markets = _probs_to_markets(true_lh, true_la)
    m = fit_team_goals("F1", home_team_fpl_id=10, away_team_fpl_id=20, market_probs=markets)
    assert m.lambda_home == pytest.approx(true_lh, abs=0.05)
    assert m.lambda_away == pytest.approx(true_la, abs=0.05)


def test_clean_sheet_probs_match_opponent_lambda():
    true_lh, true_la = 1.8, 0.9
    m = fit_team_goals("F1", 10, 20, _probs_to_markets(true_lh, true_la))
    # Home keeps a clean sheet iff the AWAY team fails to score.
    assert m.p_clean_sheet_home == pytest.approx(math.exp(-m.lambda_away), abs=1e-9)
    assert m.p_clean_sheet_away == pytest.approx(math.exp(-m.lambda_home), abs=1e-9)


def test_strong_home_favorite_has_higher_home_lambda():
    m = fit_team_goals("F1", 10, 20, _probs_to_markets(2.3, 0.6))
    assert m.lambda_home > m.lambda_away


def test_fit_raises_without_usable_markets():
    with pytest.raises(ValueError):
        fit_team_goals("F1", 10, 20, [MarketProb("F1", "corners", "over", 0.5)])


def test_fit_records_residuals_and_provenance():
    true_lh, true_la = 1.8, 0.9
    markets = _probs_to_markets(true_lh, true_la)
    m = fit_team_goals("F1", 10, 20, markets)
    assert m.fit_loss >= 0.0
    assert "home" in m.residuals
    assert "draw" in m.residuals
    assert "away" in m.residuals
    assert "markets" in m.market_provenance
    assert "h2h" in m.market_provenance["markets"]
    assert m.market_provenance["targets"]["home"] == pytest.approx(markets[0].prob)


def test_duckdb_consensus_fit_and_persistence():
    from datetime import datetime, timezone
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
        load_latest_fixture_team_xg,
        open_database,
        upsert_fixtures,
        upsert_odds_bookmakers,
        upsert_odds_event_fixture_mappings,
        upsert_odds_provider_events,
        upsert_teams,
    )
    from fpl_alpha.team_xg import fit_and_persist_fixture_team_xg

    conn = open_database(":memory:")
    upsert_teams(
        conn,
        [
            Team(1, "Arsenal", "ARS", ("Arsenal",)),
            Team(2, "Chelsea", "CHE", ("Chelsea",)),
        ],
    )
    upsert_fixtures(
        conn,
        [
            Fixture(
                fpl_id=10,
                code=1001,
                event=1,
                kickoff_time="2026-09-12T14:00:00Z",
                finished=False,
                finished_provisional=False,
                minutes=0,
                provisional_start_time=False,
                started=False,
                team_a_fpl_id=2,
                team_a_score=None,
                team_a_difficulty=3,
                team_h_fpl_id=1,
                team_h_score=None,
                team_h_difficulty=3,
            )
        ],
    )
    upsert_odds_provider_events(
        conn,
        [
            OddsProviderEvent(
                "propline", "event-1", "soccer_epl", "Arsenal", "Chelsea",
                "2026-09-12T14:00:00Z",
            )
        ],
    )
    upsert_odds_event_fixture_mappings(
        conn,
        [OddsEventFixtureMapping("propline", "event-1", 10, "exact")],
    )
    upsert_odds_bookmakers(
        conn,
        [OddsBookmaker("propline", "book-1", "Book 1")],
    )

    now = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)
    snapshots = [
        OddsOutcomeSnapshot(
            provider_key="propline",
            provider_event_id="event-1",
            bookmaker_key="book-1",
            market_key="h2h",
            market_ordinal=0,
            market_description=None,
            market_team=None,
            outcome_ordinal=0,
            selection_description=None,
            fpl_player_id=None,
            outcome_name="Arsenal",
            american_price=-120,
            point=None,
            last_update=None,
            last_change_at=None,
            captured_at=now,
        ),
        OddsOutcomeSnapshot(
            provider_key="propline",
            provider_event_id="event-1",
            bookmaker_key="book-1",
            market_key="h2h",
            market_ordinal=0,
            market_description=None,
            market_team=None,
            outcome_ordinal=1,
            selection_description=None,
            fpl_player_id=None,
            outcome_name="Draw",
            american_price=260,
            point=None,
            last_update=None,
            last_change_at=None,
            captured_at=now,
        ),
        OddsOutcomeSnapshot(
            provider_key="propline",
            provider_event_id="event-1",
            bookmaker_key="book-1",
            market_key="h2h",
            market_ordinal=0,
            market_description=None,
            market_team=None,
            outcome_ordinal=2,
            selection_description=None,
            fpl_player_id=None,
            outcome_name="Chelsea",
            american_price=310,
            point=None,
            last_update=None,
            last_change_at=None,
            captured_at=now,
        ),
    ]
    insert_odds_outcome_snapshots(conn, snapshots)

    # Step 4: DuckDB consensus -> fit_team_goals() -> persisted team-xG
    record = fit_and_persist_fixture_team_xg(conn, 10, provider_key="propline")
    assert record.fixture_fpl_id == 10
    assert record.lambda_home > record.lambda_away
    assert record.fit_loss >= 0.0
    assert "h2h" in record.market_provenance["markets"]
    assert "home" in record.residuals

    # Load from DuckDB
    loaded = load_latest_fixture_team_xg(conn, 10, provider_key="propline")
    assert loaded is not None
    assert loaded.fixture_fpl_id == 10
    assert loaded.lambda_home == pytest.approx(record.lambda_home)
    assert loaded.lambda_away == pytest.approx(record.lambda_away)
    assert loaded.fit_loss == pytest.approx(record.fit_loss)
    assert loaded.residuals == record.residuals
    assert loaded.market_provenance == record.market_provenance
