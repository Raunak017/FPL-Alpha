"""Tests for the expected-minutes / start-probability model (step 7)."""
from __future__ import annotations

import pytest

from fpl_alpha.minutes import (
    PRIOR_MINUTES,
    PRIOR_START,
    availability_factor,
    expected_minutes,
    start_probability,
)


# --- availability_factor (lives in minutes now, re-exported from allocation) --
def test_availability_factor_prefers_chance():
    assert availability_factor("d", 75) == pytest.approx(0.75)
    assert availability_factor("i", 0) == 0.0
    assert availability_factor("a", 100) == 1.0


def test_availability_factor_status_fallback():
    assert availability_factor("a", None) == 1.0
    assert availability_factor("i", None) == 0.0
    assert availability_factor("s", None) == 0.0
    assert availability_factor(None, None) == 1.0


def test_allocation_reexports_availability_factor():
    from fpl_alpha.allocation import availability_factor as af
    assert af is availability_factor


# --- expected_minutes -------------------------------------------------------
def test_expected_minutes_nailed_starter_is_high():
    # ~full season of minutes -> close to a full match, gated by fitness.
    assert expected_minutes(3200, 1.0) > 70.0


def test_expected_minutes_bench_player_is_low():
    nailed = expected_minutes(3200, 1.0)
    bench = expected_minutes(400, 1.0)
    assert bench < nailed
    assert bench < PRIOR_MINUTES  # own low history pulls below the neutral prior


def test_expected_minutes_zero_history_falls_back_to_prior():
    assert expected_minutes(0, 1.0) == pytest.approx(PRIOR_MINUTES)


def test_expected_minutes_injured_is_zero():
    assert expected_minutes(3200, 0.0) == 0.0


def test_expected_minutes_capped_at_90():
    assert expected_minutes(10_000, 1.0) <= 90.0


def test_expected_minutes_scales_with_availability():
    full = expected_minutes(3200, 1.0)
    doubt = expected_minutes(3200, 0.5)
    assert doubt == pytest.approx(full * 0.5)


# --- start_probability ------------------------------------------------------
def test_start_probability_nailed_starter_high():
    assert start_probability(35, 3200, 1.0) > 0.75


def test_start_probability_supersub_low():
    # Lots of minutes but zero starts -> a known non-starter, not the prior.
    p = start_probability(0, 1800, 1.0)
    assert p < PRIOR_START


def test_start_probability_new_player_uses_prior():
    assert start_probability(0, 0, 1.0) == pytest.approx(PRIOR_START)


def test_start_probability_injured_zero():
    assert start_probability(35, 3200, 0.0) == 0.0


# --- consistency factors ---------------------------------------------------
def test_appearance_consistency_factor_starter_vs_cameo():
    from fpl_alpha.minutes import appearance_consistency_factor
    # Nailed starter played 6 of 6 matches
    assert appearance_consistency_factor(6, 6) > 0.9
    # Cameo played 1 of 6 matches
    assert appearance_consistency_factor(1, 6) < 0.25
    # Unused reserve played 0 of 6 matches
    assert appearance_consistency_factor(0, 6) < 0.1


def test_start_consistency_factor_starter_vs_bench():
    from fpl_alpha.minutes import start_consistency_factor
    # Nailed starter started 6 of 6 matches
    assert start_consistency_factor(6, 6) > 0.9
    # Bench player started 0 of 6 matches
    assert start_consistency_factor(0, 6) < 0.1


def test_expected_minutes_and_start_prob_with_cameo_consistency():
    # Nicoll-Jazuli scenario: 3 mins, 0 starts, 1 appearance in 6 games
    exp_mins = expected_minutes(3, 1.0, games_played=6.0, matches_played=1)
    p_start = start_probability(0, 3, 1.0, games_played=6.0, matches_started=0, matches_played=1)

    # Both must be heavily deflated by the 1/6 selection consistency
    assert exp_mins < 10.0
    assert p_start < 0.10


def test_expected_minutes_and_start_prob_injured_starter_not_crushed():
    # Returning starter scenario: started all 3 matches played (90 mpg) out of 6 team games
    exp_mins = expected_minutes(270, 1.0, games_played=6.0, matches_played=3)
    p_start = start_probability(3, 270, 1.0, games_played=6.0, matches_started=3, matches_played=3)

    # Must preserve starter status (not crushed to ~22 mins / ~49% start prob)
    assert exp_mins > 55.0
    assert p_start > 0.60


