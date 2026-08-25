"""Tests for the historical-shares player allocator (steps 5-6)."""
from __future__ import annotations

import pytest

from fpl_alpha.allocation import (
    ASSISTED_GOAL_FRACTION,
    allocate,
    allocate_fixture,
    attack_rates_from_bootstrap,
    attack_weights_from_bootstrap,
    availability_factor,
    shrink_rate,
)
from fpl_alpha.schemas import PlayerRates, TeamGoalModel


# --- allocate(): the pure share math ----------------------------------------
def test_allocate_splits_proportionally_and_sums_to_total():
    out = allocate(3.0, {1: 3.0, 2: 1.0})
    assert out[1] == pytest.approx(2.25)  # 3/4 of 3.0
    assert out[2] == pytest.approx(0.75)  # 1/4 of 3.0
    assert sum(out.values()) == pytest.approx(3.0)


def test_allocate_single_player_gets_everything():
    assert allocate(2.4, {7: 0.5})[7] == pytest.approx(2.4)


def test_allocate_zero_weights_returns_zeros_not_nan():
    # No basis to split -> zeros (unallocated), never a divide-by-zero.
    assert allocate(2.0, {1: 0.0, 2: 0.0}) == {1: 0.0, 2: 0.0}


def test_allocate_empty_weights_returns_empty():
    assert allocate(2.0, {}) == {}


def test_allocate_rejects_negative_weights():
    with pytest.raises(ValueError):
        allocate(1.0, {1: -0.1})


# --- allocate_fixture(): team lambda -> per-player xG/xA ---------------------
def _model() -> TeamGoalModel:
    return TeamGoalModel(
        fixture_id="A_v_B",
        home_team_fpl_id=1,
        away_team_fpl_id=2,
        lambda_home=2.0,
        lambda_away=1.0,
        p_clean_sheet_home=0.4,
        p_clean_sheet_away=0.2,
    )


def _rates() -> dict[int, PlayerRates]:
    return {
        10: PlayerRates(10, 1, xg=8.0, xa=2.0),  # home striker (80% of home xG)
        11: PlayerRates(11, 1, xg=2.0, xa=6.0),  # home creator (75% of home xA)
        12: PlayerRates(12, 1, xg=0.0, xa=0.0),  # home keeper
        20: PlayerRates(20, 2, xg=3.0, xa=3.0),  # lone away attacker
    }


def test_fixture_goals_sum_to_each_team_lambda():
    recs = allocate_fixture(_model(), _rates())
    home = sum(r.exp_goals for r in recs if r.team_fpl_id == 1)
    away = sum(r.exp_goals for r in recs if r.team_fpl_id == 2)
    assert home == pytest.approx(2.0)  # lambda_home
    assert away == pytest.approx(1.0)  # lambda_away


def test_fixture_assists_use_assisted_fraction():
    recs = allocate_fixture(_model(), _rates())
    home_assists = sum(r.exp_assists for r in recs if r.team_fpl_id == 1)
    assert home_assists == pytest.approx(2.0 * ASSISTED_GOAL_FRACTION)


def test_fixture_shares_track_weights():
    recs = {r.fpl_id: r for r in allocate_fixture(_model(), _rates())}
    assert recs[10].goal_share == pytest.approx(0.8)
    assert recs[10].exp_goals == pytest.approx(2.0 * 0.8)
    assert recs[11].assist_share == pytest.approx(0.75)
    assert recs[11].exp_assists == pytest.approx(2.0 * ASSISTED_GOAL_FRACTION * 0.75)


def test_fixture_keeper_gets_no_attacking_return():
    recs = {r.fpl_id: r for r in allocate_fixture(_model(), _rates())}
    assert recs[12].exp_goals == 0.0
    assert recs[12].exp_assists == 0.0


def test_fixture_lone_attacker_absorbs_full_team_total():
    recs = {r.fpl_id: r for r in allocate_fixture(_model(), _rates())}
    assert recs[20].exp_goals == pytest.approx(1.0)  # only away player with xG


# --- attack_rates_from_bootstrap(): parsing ---------------------------------
def test_rates_from_bootstrap_parses_string_floats_and_missing():
    boot = {
        "elements": [
            {"id": 10, "team": 1, "expected_goals": "8.00", "expected_assists": "2.00"},
            {"id": 12, "team": 1, "expected_goals": "0.00", "expected_assists": "0.00"},
            {"id": 99, "team": 3, "expected_goals": None},  # assist key absent
        ]
    }
    rates = attack_rates_from_bootstrap(boot)
    assert rates[10].xg == 8.0 and rates[10].xa == 2.0
    assert rates[10].team_fpl_id == 1
    assert rates[99].xg == 0.0 and rates[99].xa == 0.0  # None / missing -> 0.0


# --- availability gate ------------------------------------------------------
def test_availability_factor_uses_chance_when_present():
    assert availability_factor("d", 75) == pytest.approx(0.75)
    assert availability_factor("i", 0) == 0.0
    assert availability_factor("a", 100) == pytest.approx(1.0)


def test_availability_factor_falls_back_to_status_when_chance_none():
    assert availability_factor("a", None) == 1.0   # fit, no news
    assert availability_factor("i", None) == 0.0   # injured, no % given
    assert availability_factor("s", None) == 0.0   # suspended
    assert availability_factor(None, None) == 1.0  # unknown -> assume fit


def test_injured_player_gets_zero_and_share_redistributes():
    # Striker with the biggest xG but injured (available=0) — an "Ekitiké".
    rates = {
        10: PlayerRates(10, 1, xg=10.0, xa=1.0, available=0.0),  # injured
        11: PlayerRates(11, 1, xg=2.0, xa=1.0, available=1.0),   # fit
        12: PlayerRates(12, 1, xg=2.0, xa=1.0, available=1.0),   # fit
        20: PlayerRates(20, 2, xg=1.0, xa=1.0, available=1.0),
    }
    recs = {r.fpl_id: r for r in allocate_fixture(_model(), rates)}
    assert recs[10].exp_goals == 0.0                       # injured -> no share
    # His 2.0 team lambda now splits between the two fit players (2.0 xg each).
    assert recs[11].exp_goals == pytest.approx(1.0)
    assert recs[12].exp_goals == pytest.approx(1.0)
    assert recs[11].exp_goals + recs[12].exp_goals == pytest.approx(2.0)  # lambda_home


def test_doubtful_player_gets_reduced_but_nonzero_share():
    rates = {
        10: PlayerRates(10, 1, xg=5.0, xa=1.0, available=0.5),  # 50% doubt
        11: PlayerRates(11, 1, xg=5.0, xa=1.0, available=1.0),
        20: PlayerRates(20, 2, xg=1.0, xa=1.0, available=1.0),
    }
    recs = {r.fpl_id: r for r in allocate_fixture(_model(), rates)}
    # weights 2.5 vs 5.0 -> shares 1/3 vs 2/3 of lambda_home=2.0
    assert recs[10].exp_goals == pytest.approx(2.0 / 3)
    assert recs[11].exp_goals == pytest.approx(4.0 / 3)


def test_rates_from_bootstrap_records_availability():
    boot = {
        "elements": [
            {"id": 1, "team": 1, "expected_goals": "5", "expected_assists": "1",
             "status": "a", "chance_of_playing_next_round": None},
            {"id": 2, "team": 1, "expected_goals": "5", "expected_assists": "1",
             "status": "i", "chance_of_playing_next_round": 0},
            {"id": 3, "team": 1, "expected_goals": "5", "expected_assists": "1",
             "status": "d", "chance_of_playing_next_round": 75},
        ]
    }
    rates = attack_rates_from_bootstrap(boot)
    assert rates[1].available == 1.0
    assert rates[2].available == 0.0
    assert rates[3].available == pytest.approx(0.75)
    # gate off -> everyone fully available regardless of status
    ungated = attack_rates_from_bootstrap(boot, gate_availability=False)
    assert all(r.available == 1.0 for r in ungated.values())


def test_rates_from_bootstrap_honors_alternate_keys():
    boot = {"elements": [{"id": 5, "team": 2, "expected_goals_per_90": 0.9,
                          "expected_assists_per_90": 0.3}]}
    rates = attack_rates_from_bootstrap(
        boot, goal_key="expected_goals_per_90", assist_key="expected_assists_per_90"
    )
    assert rates[5].xg == pytest.approx(0.9)
    assert rates[5].xa == pytest.approx(0.3)


# --- shrinkage + minutes weighting (step 7) ---------------------------------
def test_shrink_rate_zero_minutes_returns_prior():
    assert shrink_rate(5.0, 0.0, 0.08) == pytest.approx(0.08)  # no evidence -> prior


def test_shrink_rate_heavy_minutes_returns_own_rate():
    # 100k minutes of evidence overwhelms the k~500 prior weight.
    assert shrink_rate(0.30, 100_000, 0.08) == pytest.approx(0.30, abs=2e-3)


def test_shrink_rate_blends_between():
    val = shrink_rate(0.30, 500, 0.08, k=500)  # equal evidence and prior weight
    assert val == pytest.approx((0.30 + 0.08) / 2)


def _thin_squad_bootstrap() -> dict:
    """One historied midfielder + three zero-history teammates (a 'Lukić' squad)."""
    def el(i, xg90, mins, etype=3):
        return {"id": i, "team": 1, "element_type": etype, "status": "a",
                "chance_of_playing_next_round": None, "minutes": mins,
                "expected_goals_per_90": xg90, "expected_assists_per_90": 0.0,
                "expected_goals": str(xg90 * mins / 90), "expected_assists": "0"}
    return {"elements": [
        el(1, 0.30, 2500),  # the historied MID
        el(2, 0.0, 0),      # zero-history teammates
        el(3, 0.0, 0),
        el(4, 0.0, 0, etype=4),  # a forward with no history
        {"id": 9, "team": 2, "element_type": 4, "status": "a",  # opponent, ignored here
         "chance_of_playing_next_round": None, "minutes": 2000,
         "expected_goals_per_90": 0.4, "expected_assists_per_90": 0.1,
         "expected_goals": "8", "expected_assists": "2"},
    ]}


def test_weights_builder_zero_history_player_gets_nonzero_weight():
    w = attack_weights_from_bootstrap(_thin_squad_bootstrap())
    assert w[2].xg > 0.0  # pulled to the positional prior, not left at 0
    assert w[1].available == 1.0  # availability folded into expected minutes


def test_weights_builder_injured_player_zeroed():
    boot = _thin_squad_bootstrap()
    boot["elements"][0]["status"] = "i"
    boot["elements"][0]["chance_of_playing_next_round"] = 0
    w = attack_weights_from_bootstrap(boot)
    assert w[1].xg == 0.0  # expected minutes -> 0


def test_shrinkage_deconcentrates_thin_squad():
    boot = _thin_squad_bootstrap()
    model = TeamGoalModel("A_v_B", 1, 2, 2.0, 1.0, 0.4, 0.2)

    raw = {r.fpl_id: r for r in allocate_fixture(model, attack_rates_from_bootstrap(boot))}
    shrunk = {r.fpl_id: r for r in allocate_fixture(model, attack_weights_from_bootstrap(boot))}

    # Raw season-totals hand the lone historied MID almost the entire team λ...
    assert raw[1].goal_share > 0.95
    # ...shrinkage spreads it to fit teammates, cutting his share sharply.
    assert shrunk[1].goal_share < raw[1].goal_share - 0.3
    # Every team still sums to its λ (allocation is share-preserving).
    assert sum(r.exp_goals for r in shrunk.values() if r.team_fpl_id == 1) == pytest.approx(2.0)
