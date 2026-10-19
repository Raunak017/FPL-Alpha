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


def test_project_player_fixture_shrinks_cameo_defcon():
    """Ensure small-sample cameos (e.g. 3 mins with 2 tackles = 60.0 defcon/90) do not inflate."""
    cameo_player = Player(
        fpl_id=662, web_name="Cameo Mid", full_name="",
        team_fpl_id=6, position="MID", now_cost=45
    )
    # 3 minutes played, 0 starts, but 60.0 raw defcon per 90 from 2 tackles in 3 mins
    cameo_snapshot = PlayerSnapshot(
        player_fpl_id=662, captured_at=datetime.now(timezone.utc),
        now_cost=45, selected_by_percent=0.1, status="a",
        total_points=1, points_per_game=1.0, form=0.5,
        minutes=3, starts=0, goals_scored=0, assists=0,
        clean_sheets=0, bonus=0, bps=5,
        expected_goals=0.0, expected_assists=0.0, expected_goal_involvements=0.0,
        expected_goals_conceded=0.0, clean_sheets_per_90=0.0,
        defensive_contribution_per_90=60.0, expected_goals_per_90=0.0,
        expected_assists_per_90=0.0, expected_goal_involvements_per_90=0.0,
        expected_goals_conceded_per_90=0.0, goals_conceded_per_90=0.0,
        saves_per_90=0.0, starts_per_90=0.0, influence=5.0,
        creativity=2.0, threat=0.0, ict_index=0.7,
        chance_of_playing_next_round=None, chance_of_playing_this_round=None,
        transfers_in_event=0, transfers_out_event=0,
        transfers_in=0, transfers_out=0
    )
    attack = PlayerFixtureAttack(
        fpl_id=662, fixture_id="F2", team_fpl_id=6,
        exp_goals=0.02, exp_assists=0.02
    )

    proj = project_player_fixture(
        player=cameo_player,
        snapshot=cameo_snapshot,
        attack=attack,
        p_clean_sheet=0.3,
        games_played=6.0,
    )

    # Shrunk defcon should NOT give 2.0 points (which raw 60.0 per 90 would give)
    assert proj.defensive_contribution_points < 0.1
    assert proj.expected_points < 2.0


def test_project_player_fixture_zero_minutes_returns_zero():
    """Players who have not played (0 minutes) should receive 0.0 xPts and 0 expected minutes."""
    player = Player(
        fpl_id=999, web_name="Reserve", full_name="Reserve Player",
        team_fpl_id=1, position="MID", now_cost=45
    )
    snapshot = PlayerSnapshot(
        player_fpl_id=999, captured_at=datetime.now(timezone.utc),
        now_cost=45, selected_by_percent=0.1, status="a",
        total_points=0, points_per_game=0.0, form=0.0,
        minutes=0, starts=0, goals_scored=0, assists=0,
        clean_sheets=0, bonus=0, bps=0,
        expected_goals=0.0, expected_assists=0.0, expected_goal_involvements=0.0,
        expected_goals_conceded=0.0, clean_sheets_per_90=0.0,
        defensive_contribution_per_90=0.0, expected_goals_per_90=0.0,
        expected_assists_per_90=0.0, expected_goal_involvements_per_90=0.0,
        expected_goals_conceded_per_90=0.0, goals_conceded_per_90=0.0,
        saves_per_90=0.0, starts_per_90=0.0, influence=0.0,
        creativity=0.0, threat=0.0, ict_index=0.0,
        chance_of_playing_next_round=None, chance_of_playing_this_round=None,
        transfers_in_event=0, transfers_out_event=0,
        transfers_in=0, transfers_out=0
    )
    attack = PlayerFixtureAttack(
        fpl_id=999, fixture_id="F1", team_fpl_id=1,
        exp_goals=0.0, exp_assists=0.0
    )

    proj = project_player_fixture(
        player=player,
        snapshot=snapshot,
        attack=attack,
        p_clean_sheet=0.3,
        games_played=6.0,
    )

    assert proj.expected_points == 0.0
    assert proj.p_start == 0.0
    assert proj.appearance_points == 0.0
    assert proj.p_60_plus == 0.0


