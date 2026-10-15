import pytest

from fpl_alpha.scoring import (
    CURRENT_RULESET,
    PlayerMatchEvents,
    defensive_contribution_points,
    rules_for,
    score_player_fixture,
)


@pytest.mark.parametrize(
    ("position", "expected"),
    [("GKP", 10), ("DEF", 6), ("MID", 5), ("FWD", 4)],
)
def test_goal_values_are_versioned_by_position(position, expected):
    result = score_player_fixture(position, PlayerMatchEvents(minutes=60, goals=1))
    assert result.goal_points == expected
    assert result.rules_version == "2026-27"


def test_defender_full_score_breakdown():
    result = score_player_fixture(
        "DEF",
        PlayerMatchEvents(
            minutes=90,
            goals=1,
            assists=1,
            clean_sheet=True,
            goals_conceded=3,
            penalties_missed=1,
            own_goals=1,
            yellow_cards=1,
            clearances_blocks_interceptions=6,
            tackles=4,
            bonus=3,
        ),
    )

    assert result.appearance_points == 2
    assert result.clean_sheet_points == 4
    assert result.defensive_contribution_points == 2
    assert result.goals_conceded_points == -1
    assert result.total_points == 14


def test_goalkeeper_save_penalty_and_conceded_scoring():
    result = score_player_fixture(
        "GKP",
        PlayerMatchEvents(
            minutes=90,
            goals=1,
            clean_sheet=True,
            goals_conceded=4,
            saves=7,
            penalties_saved=1,
        ),
    )

    assert result.save_points == 2
    assert result.penalty_save_points == 5
    assert result.goals_conceded_points == -2
    assert result.total_points == 21


def test_clean_sheet_requires_sixty_minutes_and_player_specific_flag():
    assert score_player_fixture("DEF", PlayerMatchEvents(minutes=59, clean_sheet=True)).clean_sheet_points == 0
    assert score_player_fixture("DEF", PlayerMatchEvents(minutes=90, clean_sheet=False)).clean_sheet_points == 0


def test_defensive_contribution_thresholds_and_cap():
    assert defensive_contribution_points("DEF", 7, 3) == 2
    assert defensive_contribution_points("MID", 7, 3, 1) == 0
    assert defensive_contribution_points("MID", 7, 3, 2) == 2
    assert defensive_contribution_points("GKP", 20, 20, 20) == 0


def test_red_card_replaces_yellow_deduction_for_the_fixture():
    result = score_player_fixture("MID", PlayerMatchEvents(minutes=60, yellow_cards=1, red_cards=1))
    assert result.card_points == -3


def test_invalid_events_and_rules_version_are_rejected():
    with pytest.raises(ValueError, match="minutes"):
        score_player_fixture("MID", PlayerMatchEvents(minutes=-1))
    with pytest.raises(ValueError, match="bonus"):
        score_player_fixture("MID", PlayerMatchEvents(minutes=90, bonus=4))
    with pytest.raises(ValueError, match="unknown FPL scoring rules"):
        rules_for("1900-01")
    assert rules_for("2026-27") is CURRENT_RULESET
