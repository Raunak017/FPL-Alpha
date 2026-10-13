from datetime import datetime, timezone
import pytest
import numpy as np

from fpl_alpha.simulation import simulate_fixture
from fpl_alpha.schemas import (
    Player, PlayerSnapshot, PlayerFixtureAttack, TeamGoalModel
)
from fpl_alpha.scoring import CURRENT_RULESET

def test_simulate_fixture():
    # Fix random seed for reproducibility
    np.random.seed(42)

    home_player = Player(
        fpl_id=1, web_name="Home Striker", full_name="",
        team_fpl_id=1, position="FWD", now_cost=100
    )
    home_snap = PlayerSnapshot(
        player_fpl_id=1, captured_at=datetime.now(timezone.utc), now_cost=100,
        selected_by_percent=50.0, status="a", total_points=200, points_per_game=6.0,
        form=8.0, minutes=3000, starts=35, goals_scored=20, assists=5,
        clean_sheets=10, bonus=30, bps=800, expected_goals=20.0, expected_assists=5.0,
        expected_goal_involvements=25.0, expected_goals_conceded=30.0, clean_sheets_per_90=0.3,
        defensive_contribution_per_90=15.0, expected_goals_per_90=0.6, expected_assists_per_90=0.15,
        expected_goal_involvements_per_90=0.75, expected_goals_conceded_per_90=0.9, goals_conceded_per_90=0.9,
        saves_per_90=0.0, starts_per_90=0.9, influence=500.0, creativity=200.0, threat=800.0, ict_index=150.0,
        chance_of_playing_next_round=100, chance_of_playing_this_round=100,
        transfers_in_event=0, transfers_out_event=0, transfers_in=0, transfers_out=0
    )
    home_attack = PlayerFixtureAttack(
        fpl_id=1, fixture_id="F1", team_fpl_id=1,
        exp_goals=0.8, exp_assists=0.2
    )

    away_player = Player(
        fpl_id=2, web_name="Away Keeper", full_name="",
        team_fpl_id=2, position="GKP", now_cost=45
    )
    away_snap = PlayerSnapshot(
        player_fpl_id=2, captured_at=datetime.now(timezone.utc), now_cost=45,
        selected_by_percent=10.0, status="a", total_points=120, points_per_game=3.5,
        form=3.0, minutes=3420, starts=38, goals_scored=0, assists=0,
        clean_sheets=8, bonus=5, bps=500, expected_goals=0.0, expected_assists=0.0,
        expected_goal_involvements=0.0, expected_goals_conceded=50.0, clean_sheets_per_90=0.2,
        defensive_contribution_per_90=0.0, expected_goals_per_90=0.0, expected_assists_per_90=0.0,
        expected_goal_involvements_per_90=0.0, expected_goals_conceded_per_90=1.5, goals_conceded_per_90=1.5,
        saves_per_90=3.5, starts_per_90=1.0, influence=300.0, creativity=0.0, threat=0.0, ict_index=30.0,
        chance_of_playing_next_round=100, chance_of_playing_this_round=100,
        transfers_in_event=0, transfers_out_event=0, transfers_in=0, transfers_out=0
    )
    away_attack = PlayerFixtureAttack(
        fpl_id=2, fixture_id="F1", team_fpl_id=2,
        exp_goals=0.0, exp_assists=0.0
    )

    team_model = TeamGoalModel(
        fixture_id="F1", home_team_fpl_id=1, away_team_fpl_id=2,
        lambda_home=2.0, lambda_away=1.0,
        p_clean_sheet_home=0.36, p_clean_sheet_away=0.13, score_dist={}
    )

    results = simulate_fixture(
        fixture_fpl_id=101,
        team_model=team_model,
        home_players=[(home_player, home_snap, home_attack)],
        away_players=[(away_player, away_snap, away_attack)],
        n_iterations=1000
    )

    assert len(results) == 2
    
    # Extract results
    res_home = next(r for r in results if r.player_fpl_id == 1)
    res_away = next(r for r in results if r.player_fpl_id == 2)
    
    # Basic sanity checks
    # Home striker mean points should be high (xG 0.8 => ~3.2 pts from goals + 2 app + defcon)
    assert res_home.mean_pts > 4.0
    assert res_home.p_10_plus > 0.05
    assert res_home.ceiling_pts >= 8.0
    
    # Away keeper mean points
    # Saves: 3.5 per 90 => lambda 3.5 => ~ 1 save pt. 
    # App: 2 pts. 
    # GC: lambda 2.0 home goals => ~ 1 deduccion (-1) => ~ 3.0 pts total
    assert res_away.mean_pts > 1.0
    assert res_away.p_10_plus >= 0.0  # Keepers sometimes get 10 but rare without penalty saves


def test_correlated_simulation_zero_team_goals():
    # When team lambda is 0, player goals/assists must be strictly 0
    home_player = Player(
        fpl_id=1, web_name="Striker", full_name="", team_fpl_id=1, position="FWD", now_cost=100
    )
    home_snap = PlayerSnapshot(
        player_fpl_id=1, captured_at=datetime.now(timezone.utc), now_cost=100,
        selected_by_percent=50.0, status="a", total_points=50, points_per_game=5.0,
        form=5.0, minutes=3420, starts=38, goals_scored=5, assists=2,
        clean_sheets=3, bonus=5, bps=100, expected_goals=5.0, expected_assists=2.0,
        expected_goal_involvements=7.0, expected_goals_conceded=10.0, clean_sheets_per_90=0.3,
        defensive_contribution_per_90=0.0, expected_goals_per_90=0.5, expected_assists_per_90=0.2,
        expected_goal_involvements_per_90=0.7, expected_goals_conceded_per_90=1.0, goals_conceded_per_90=1.0,
        saves_per_90=0.0, starts_per_90=1.0, influence=100.0, creativity=100.0, threat=100.0, ict_index=30.0,
        chance_of_playing_next_round=100, chance_of_playing_this_round=100,
        transfers_in_event=0, transfers_out_event=0, transfers_in=0, transfers_out=0
    )
    home_attack = PlayerFixtureAttack(
        fpl_id=1, fixture_id="F1", team_fpl_id=1, exp_goals=0.5, exp_assists=0.2, goal_share=0.5, assist_share=0.5
    )
    team_model = TeamGoalModel(
        fixture_id="F1", home_team_fpl_id=1, away_team_fpl_id=2,
        lambda_home=0.0, lambda_away=0.0,
        p_clean_sheet_home=1.0, p_clean_sheet_away=1.0, score_dist={}
    )
    res = simulate_fixture(
        fixture_fpl_id=101,
        team_model=team_model,
        home_players=[(home_player, home_snap, home_attack)],
        away_players=[],
        n_iterations=500,
        random_seed=42,
    )
    # With 0 team goals and 0 defcon, striker only gets appearance points (ceiling 2, zero attacking returns)
    assert res[0].p_10_plus == 0.0
    assert res[0].ceiling_pts <= 2.0
    assert 1.5 < res[0].mean_pts <= 2.0


def test_simulation_dynamic_games_played():
    # Test that games_played impacts start_probability and expected_minutes
    player = Player(fpl_id=1, web_name="Early", full_name="", team_fpl_id=1, position="MID", now_cost=60)
    snap = PlayerSnapshot(
        player_fpl_id=1, captured_at=datetime.now(timezone.utc), now_cost=60,
        selected_by_percent=10.0, status="a", total_points=15, points_per_game=5.0,
        form=5.0, minutes=270, starts=3, goals_scored=1, assists=1,
        clean_sheets=1, bonus=2, bps=40, expected_goals=1.0, expected_assists=1.0,
        expected_goal_involvements=2.0, expected_goals_conceded=3.0, clean_sheets_per_90=0.33,
        defensive_contribution_per_90=0.0, expected_goals_per_90=0.33, expected_assists_per_90=0.33,
        expected_goal_involvements_per_90=0.66, expected_goals_conceded_per_90=1.0, goals_conceded_per_90=1.0,
        saves_per_90=0.0, starts_per_90=1.0, influence=50.0, creativity=50.0, threat=50.0, ict_index=15.0,
        chance_of_playing_next_round=100, chance_of_playing_this_round=100,
        transfers_in_event=0, transfers_out_event=0, transfers_in=0, transfers_out=0
    )
    attack = PlayerFixtureAttack(fpl_id=1, fixture_id="F1", team_fpl_id=1, exp_goals=0.2, exp_assists=0.2)
    team_model = TeamGoalModel("F1", 1, 2, 1.5, 1.0, 0.36, 0.22, {})
    
    # In GW4 (games_played=3), player started all 3 games (starts/3 = 1.0)
    res_early = simulate_fixture(101, team_model, [(player, snap, attack)], [], n_iterations=1000, games_played=3.0, random_seed=42)
    # Default 38 games played would treat 3 starts out of 38 as 0.08 start rate!
    res_default = simulate_fixture(101, team_model, [(player, snap, attack)], [], n_iterations=1000, games_played=38.0, random_seed=42)
    
    assert res_early[0].mean_pts > res_default[0].mean_pts

