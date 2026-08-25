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
