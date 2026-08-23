"""Unit tests for the no-vig math (Plan step 3)."""
import math

import pytest

from fpl_alpha.markets import (
    _robust_center,
    consensus,
    devig_proportional,
    implied_prob,
)


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


def test_consensus_sums_to_one():
    # Robust center is applied per outcome then renormalized: still a valid dist.
    books = [[1.8, 3.6, 4.5], [1.9, 3.4, 4.2], [1.7, 3.8, 5.0], [2.0, 3.3, 4.0]]
    probs = consensus("F1", "h2h", ["home", "draw", "away"], books)
    assert math.isclose(sum(p.prob for p in probs), 1.0, abs_tol=1e-9)
    assert probs[0].n_books == 4


def test_consensus_ignores_a_stray_book():
    # Three books agree; a fourth is wildly mispriced. The robust center should
    # track the agreeing books, unlike a plain mean which the outlier would pull.
    agree = [2.0, 2.0]          # de-vigs to 0.5 / 0.5
    outlier = [1.05, 21.0]      # de-vigs to ~0.95 / ~0.05
    probs = consensus("F1", "h2h", ["home", "away"], [agree, agree, agree, outlier])
    # Trimming drops the outlier's extreme on each side -> stays near 0.5.
    assert probs[0].prob == pytest.approx(0.5, abs=0.02)


def test_robust_center_is_median_for_three():
    assert _robust_center([0.1, 0.5, 0.9]) == pytest.approx(0.5)
    # Outlier at either end is discarded, leaving the middle value.
    assert _robust_center([0.48, 0.50, 0.95]) == pytest.approx(0.50)


def test_robust_center_small_n_falls_back_to_mean():
    assert _robust_center([0.4]) == pytest.approx(0.4)
    assert _robust_center([0.4, 0.6]) == pytest.approx(0.5)
