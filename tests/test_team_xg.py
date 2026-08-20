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
