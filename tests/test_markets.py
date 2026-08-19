"""Unit tests for the no-vig math (Plan step 3)."""
import math

import pytest

from fpl_alpha.markets import consensus, devig_proportional, implied_prob


def test_implied_prob():
    assert implied_prob(2.0) == pytest.approx(0.5)
    assert implied_prob(4.0) == pytest.approx(0.25)


def test_implied_prob_rejects_bad_odds():
    with pytest.raises(ValueError):
        implied_prob(1.0)


def test_devig_sums_to_one():
    # A book with an overround; fair probs must normalize to 1.
    fair = devig_proportional([2.1, 3.5, 3.8])
    assert math.isclose(sum(fair), 1.0, abs_tol=1e-9)


def test_devig_preserves_order_and_ranking():
    fair = devig_proportional([1.5, 4.0, 7.0])  # strong favorite first
    assert fair[0] > fair[1] > fair[2]


def test_consensus_averages_books():
    # Two identical books -> consensus equals a single de-vigged book.
    books = [[2.0, 2.0], [2.0, 2.0]]
    probs = consensus("F1", "h2h", ["home", "away"], books)
    assert len(probs) == 2
    assert probs[0].prob == pytest.approx(0.5)
    assert probs[0].n_books == 2
