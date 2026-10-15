"""Deterministic expected-points (xPts) assembler (Plan step 8).

Combines player-level probabilities, team-level match probabilities, and
the official scoring rules to produce a single ``PlayerFixtureProjection``.

For now, this implements the baseline:
    xPts = P(start) * ( Appearance + P(CS)*CS_pts + xG*g_pts + xA*a_pts )
"""
from __future__ import annotations

from typing import Iterable

from fpl_alpha.minutes import availability_factor, start_probability
from fpl_alpha.schemas import (
    Player,
    PlayerFixtureAttack,
    PlayerFixtureProjection,
    PlayerSnapshot,
    TeamGoalModel,
)
from fpl_alpha.scoring import CURRENT_RULESET, FPLScoringRules


def project_player_fixture(
    player: Player,
    snapshot: PlayerSnapshot,
    attack: PlayerFixtureAttack,
    p_clean_sheet: float,
    *,
    fixture_fpl_id: int = 0,
    run_id: str = "run_0",
    gameweek: int = 0,
    games_played: float = 38.0,
    rules: FPLScoringRules = CURRENT_RULESET,
) -> PlayerFixtureProjection:
    """Assemble deterministic baseline xPts for a single player in one fixture."""
    from fpl_alpha.minutes import expected_minutes as calc_expected_minutes
    
    # Minutes model
    avail = availability_factor(snapshot.status, snapshot.chance_of_playing_next_round)
    p_start = start_probability(snapshot.starts, snapshot.minutes, avail, games_played=games_played)
    exp_mins = calc_expected_minutes(snapshot.minutes, avail, games_played=games_played)
    
    # We roughly approximate P(60') as P(start) for the baseline.
    p_60 = p_start
    
    appearance_pts = (
        p_start * rules.appearance_under_60_points 
        + p_60 * (rules.appearance_60_plus_points - rules.appearance_under_60_points)
    )
    
    goal_pts = attack.exp_goals * rules.goal_points.get(player.position, 0)
    assist_pts = attack.exp_assists * rules.assist_points
    
    # Clean sheet requires 60+ minutes
    cs_pts = p_60 * p_clean_sheet * rules.clean_sheet_points.get(player.position, 0)

    defcon_pts = expected_defcon_points(
        player.position, snapshot.defensive_contribution_per_90, exp_mins, rules=rules
    )
    save_pts = expected_save_points(
        player.position, snapshot.saves_per_90, exp_mins, rules=rules
    )
    gc_pts = expected_goals_conceded_points(
        player.position, snapshot.goals_conceded_per_90, exp_mins, rules=rules
    )

    total_xpts = appearance_pts + goal_pts + assist_pts + cs_pts + defcon_pts + save_pts + gc_pts
    
    return PlayerFixtureProjection(
        run_id=run_id,
        gameweek=gameweek,
        player_fpl_id=player.fpl_id,
        fixture_fpl_id=fixture_fpl_id,
        expected_points=total_xpts,
        expected_goals=attack.exp_goals,
        expected_assists=attack.exp_assists,
        p_start=p_start,
        p_60_plus=p_60,
        p_clean_sheet=p_clean_sheet,
        appearance_points=appearance_pts,
        goal_points=goal_pts,
        assist_points=assist_pts,
        clean_sheet_points=cs_pts,
        defensive_contribution_points=defcon_pts,
        save_points=save_pts,
        goals_conceded_points=gc_pts,
    )

import math

def poisson_prob_ge(lam: float, k: int) -> float:
    """Probability of a Poisson random variable with parameter `lam` being >= `k`."""
    if lam <= 0:
        return 0.0
    # P(X >= k) = 1 - sum_{i=0}^{k-1} e^(-lam) * lam^i / i!
    p_less_than_k = 0.0
    for i in range(k):
        p_less_than_k += math.exp(-lam) * (lam ** i) / math.factorial(i)
    return max(0.0, 1.0 - p_less_than_k)

def expected_defcon_points(
    position: str,
    defcon_per_90: float,
    expected_minutes: float,
    *,
    rules: FPLScoringRules = CURRENT_RULESET,
) -> float:
    """Estimate expected defensive contribution points (Step 10)."""
    if position == "GKP":
        return 0.0
    
    if defcon_per_90 <= 0 or expected_minutes <= 0:
        return 0.0
        
    lam = defcon_per_90 * (expected_minutes / 90.0)
    
    threshold = rules.defender_defensive_contribution_threshold
    if position in {"MID", "FWD"}:
        threshold = rules.attacker_defensive_contribution_threshold
        
    p_ge_threshold = poisson_prob_ge(lam, threshold)
    return p_ge_threshold * rules.defensive_contribution_points


def expected_save_points(
    position: str,
    saves_per_90: float,
    expected_minutes: float,
    *,
    rules: FPLScoringRules = CURRENT_RULESET,
) -> float:
    """Estimate expected save points (Step 10).
    
    A GKP gets 1 point per 3 saves. We compute E[floor(saves / 3)] 
    assuming saves follow a Poisson distribution.
    """
    if position != "GKP" or saves_per_90 <= 0 or expected_minutes <= 0:
        return 0.0
        
    lam = saves_per_90 * (expected_minutes / 90.0)
    if lam <= 0:
        return 0.0
        
    # E[floor(X/3)] = sum_{k=0}^inf floor(k/3) * P(X=k)
    # We truncate the infinite sum at 25 saves (prob is ~0)
    expected_points = 0.0
    for k in range(3, 25):
        pts = (k // rules.saves_per_point) * rules.save_points
        if pts > 0:
            prob_k = math.exp(-lam) * (lam ** k) / math.factorial(k)
            expected_points += pts * prob_k
            
    return expected_points

def expected_goals_conceded_points(
    position: str,
    goals_conceded_per_90: float,
    expected_minutes: float,
    *,
    rules: FPLScoringRules = CURRENT_RULESET,
) -> float:
    """Estimate expected goals-conceded penalty points (Step 10).
    
    GKP/DEF get -1 point per 2 goals conceded. 
    Computed as E[floor(goals / 2)] * rules.goals_conceded_points.
    """
    if position not in {"GKP", "DEF"} or goals_conceded_per_90 <= 0 or expected_minutes <= 0:
        return 0.0
        
    lam = goals_conceded_per_90 * (expected_minutes / 90.0)
    if lam <= 0:
        return 0.0
        
    expected_pts = 0.0
    for k in range(2, 15):
        pts = (k // rules.goals_conceded_per_deduction) * rules.goals_conceded_points
        if pts != 0:
            prob_k = math.exp(-lam) * (lam ** k) / math.factorial(k)
            expected_pts += pts * prob_k
            
    return expected_pts
