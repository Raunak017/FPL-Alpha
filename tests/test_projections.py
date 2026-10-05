from datetime import datetime, timezone
import pytest

from fpl_alpha.projections import project_player_fixture
from fpl_alpha.schemas import (
    Player,
    PlayerFixtureAttack,
    PlayerSnapshot,
)
from fpl_alpha.scoring import CURRENT_RULESET

def test_project_player_fixture():
    player = Player(
        fpl_id=1, web_name="Defender A", full_name="Def A",
        team_fpl_id=1, position="DEF", now_cost=50
    )
    snapshot = PlayerSnapshot(
        player_fpl_id=1, captured_at=datetime.now(timezone.utc),
        now_cost=50, selected_by_percent=10.0, status="a",
        total_points=100, points_per_game=5.0, form=5.0,
        minutes=3420, starts=38, goals_scored=2, assists=5,
        clean_sheets=15, bonus=10, bps=500,
        expected_goals=2.0, expected_assists=5.0, expected_goal_involvements=7.0,
        expected_goals_conceded=30.0, clean_sheets_per_90=0.4,
        defensive_contribution_per_90=10.0, expected_goals_per_90=0.05,
        expected_assists_per_90=0.13, expected_goal_involvements_per_90=0.18,
        expected_goals_conceded_per_90=0.8, goals_conceded_per_90=0.8,
        saves_per_90=0.0, starts_per_90=1.0, influence=200.0,
        creativity=100.0, threat=50.0, ict_index=35.0,
        chance_of_playing_next_round=100, chance_of_playing_this_round=100,
        transfers_in_event=0, transfers_out_event=0,
        transfers_in=0, transfers_out=0
    )
    attack = PlayerFixtureAttack(
        fpl_id=1, fixture_id="F1", team_fpl_id=1,
        exp_goals=0.1, exp_assists=0.2
    )

    proj = project_player_fixture(
        player=player,
        snapshot=snapshot,
        attack=attack,
        p_clean_sheet=0.5,
        fixture_fpl_id=101,
        run_id="run_test",
        gameweek=1
    )

    assert proj.player_fpl_id == 1
    assert proj.fixture_fpl_id == 101
    
    # Check start prob (approx 1.0 since 38 starts, 3420 mins)
    assert proj.p_start > 0.9

    # Appearance = 2 (since p_60 ~ 1.0)
    assert proj.appearance_points > 1.8
    
    # Goal pts = 0.1 * 6 (DEF) = 0.6
    assert proj.goal_points == pytest.approx(0.6)
    
    # Assist pts = 0.2 * 3 = 0.6
    assert proj.assist_points == pytest.approx(0.6)
    
    # CS pts = p_60 * 0.5 * 4 (DEF) ~ 2.0
    assert proj.clean_sheet_points == pytest.approx(2.0, rel=0.1)

    # Expected points sum
    assert proj.expected_points == pytest.approx(
        proj.appearance_points + proj.goal_points + proj.assist_points + 
        proj.clean_sheet_points + proj.defensive_contribution_points + 
        proj.save_points + proj.goals_conceded_points
    )
