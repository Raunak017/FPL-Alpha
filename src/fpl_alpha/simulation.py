"""Monte Carlo Match Simulator (Plan step 9).

Simulates thousands of match iterations to compute full expected points
distributions (mean, median, ceiling, P(10+), P(15+)).

Uses vectorized numpy operations for speed.
"""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass

from fpl_alpha.schemas import (
    Player,
    PlayerSnapshot,
    PlayerFixtureAttack,
    TeamGoalModel,
)
from fpl_alpha.allocation import ASSISTED_GOAL_FRACTION
from fpl_alpha.minutes import availability_factor, start_probability, expected_minutes
from fpl_alpha.schemas import (
    Player,
    PlayerSnapshot,
    PlayerFixtureAttack,
    TeamGoalModel,
)
from fpl_alpha.scoring import CURRENT_RULESET, FPLScoringRules

@dataclass(frozen=True)
class SimulationResult:
    player_fpl_id: int
    fixture_fpl_id: int
    mean_pts: float
    median_pts: float
    ceiling_pts: float  # 95th percentile
    floor_pts: float    # 5th percentile
    p_10_plus: float
    p_15_plus: float

def simulate_fixture(
    fixture_fpl_id: int,
    team_model: TeamGoalModel,
    home_players: list[tuple[Player, PlayerSnapshot, PlayerFixtureAttack]],
    away_players: list[tuple[Player, PlayerSnapshot, PlayerFixtureAttack]],
    n_iterations: int = 10000,
    games_played: float = 38.0,
    rules: FPLScoringRules = CURRENT_RULESET,
    random_seed: int | None = None,
) -> list[SimulationResult]:
    """Run Monte Carlo simulation for a single fixture and return player distributions."""
    rng = np.random.default_rng(random_seed)

    # 1. Simulate match-level goals (for Clean Sheets, Conceded Goals, and Player Returns)
    home_team_goals = rng.poisson(team_model.lambda_home, size=n_iterations)
    away_team_goals = rng.poisson(team_model.lambda_away, size=n_iterations)

    results = []

    # Process Home Team
    results.extend(
        _simulate_team_players(
            fixture_fpl_id,
            home_players,
            own_team_goals=home_team_goals,
            opp_team_goals=away_team_goals,
            team_lambda=team_model.lambda_home,
            n_iterations=n_iterations,
            games_played=games_played,
            rules=rules,
            rng=rng,
        )
    )

    # Process Away Team
    results.extend(
        _simulate_team_players(
            fixture_fpl_id,
            away_players,
            own_team_goals=away_team_goals,
            opp_team_goals=home_team_goals,
            team_lambda=team_model.lambda_away,
            n_iterations=n_iterations,
            games_played=games_played,
            rules=rules,
            rng=rng,
        )
    )

    return results

def _simulate_team_players(
    fixture_fpl_id: int,
    players_data: list[tuple[Player, PlayerSnapshot, PlayerFixtureAttack]],
    own_team_goals: np.ndarray,
    opp_team_goals: np.ndarray,
    team_lambda: float,
    n_iterations: int,
    games_played: float,
    rules: FPLScoringRules,
    rng: np.random.Generator,
) -> list[SimulationResult]:
    """Vectorized simulation for a single team's players correlated with team goals."""
    if not players_data:
        return []

    n_players = len(players_data)

    p_start_list = []
    p_60_list = []
    exp_mins_list = []

    for _, snap, _ in players_data:
        avail = availability_factor(snap.status, snap.chance_of_playing_next_round)
        p_s = start_probability(snap.starts, snap.minutes, avail, games_played=games_played)
        # Approximate p_60 as p_start for now.
        p_60 = p_s
        e_m = expected_minutes(snap.minutes, avail, games_played=games_played)
        p_start_list.append(p_s)
        p_60_list.append(p_60)
        exp_mins_list.append(e_m)

    p_start = np.array(p_start_list)
    p_60 = np.array(p_60_list)
    exp_mins = np.array(exp_mins_list)

    # Defcon / Saves
    defcon_per_90 = np.array([snap.defensive_contribution_per_90 for _, snap, _ in players_data])
    saves_per_90 = np.array([snap.saves_per_90 for _, snap, _ in players_data])

    defcon_lam = defcon_per_90 * (exp_mins / 90.0)
    saves_lam = saves_per_90 * (exp_mins / 90.0)

    # Rules arrays
    pos = [p.position for p, _, _ in players_data]
    goal_pts = np.array([rules.goal_points.get(p, 0) for p in pos])
    cs_pts = np.array([rules.clean_sheet_points.get(p, 0) for p in pos])

    defcon_thresholds = np.array([
        0 if p == "GKP" else (
            rules.defender_defensive_contribution_threshold if p == "DEF" 
            else rules.attacker_defensive_contribution_threshold
        )
        for p in pos
    ])

    gc_applies = np.array([1 if p in {"GKP", "DEF"} else 0 for p in pos])
    is_gkp = np.array([1 if p == "GKP" else 0 for p in pos])

    # ---------------------------------------------------------
    # Simulations
    # ---------------------------------------------------------

    # 1. Appearance (Shape: [n_players, n_iterations])
    rand_app = rng.random(size=(n_players, n_iterations))
    plays_60 = rand_app < p_60[:, None]
    plays_under_60 = (rand_app >= p_60[:, None]) & (rand_app < p_start[:, None])
    plays = plays_60 | plays_under_60

    app_pts = plays_60 * rules.appearance_60_plus_points + plays_under_60 * rules.appearance_under_60_points

    # 2. Attacking returns correlated with simulated team goals
    g_shares = []
    a_shares = []
    for _, _, attack in players_data:
        if attack.goal_share > 0:
            gs = attack.goal_share
        elif team_lambda > 0 and attack.exp_goals > 0:
            gs = min(1.0, attack.exp_goals / team_lambda)
        else:
            gs = 0.0

        if attack.assist_share > 0:
            as_ = attack.assist_share
        elif team_lambda > 0 and attack.exp_assists > 0:
            as_ = min(1.0, attack.exp_assists / (team_lambda * ASSISTED_GOAL_FRACTION))
        else:
            as_ = 0.0

        g_shares.append(gs)
        a_shares.append(as_)

    g_shares_arr = np.array(g_shares, dtype=float)
    a_shares_arr = np.array(a_shares, dtype=float)

    g_sum = float(np.sum(g_shares_arr))
    if g_sum > 0:
        if g_sum < 1.0:
            pvals_g = np.append(g_shares_arr, 1.0 - g_sum)
            pvals_g = pvals_g / np.sum(pvals_g)
            goals = rng.multinomial(own_team_goals, pvals_g)[:, :n_players].T
        else:
            pvals_g = g_shares_arr / g_sum
            goals = rng.multinomial(own_team_goals, pvals_g).T
    else:
        goals = np.zeros((n_players, n_iterations), dtype=int)

    team_assists = rng.binomial(own_team_goals, ASSISTED_GOAL_FRACTION)
    a_sum = float(np.sum(a_shares_arr))
    if a_sum > 0:
        if a_sum < 1.0:
            pvals_a = np.append(a_shares_arr, 1.0 - a_sum)
            pvals_a = pvals_a / np.sum(pvals_a)
            assists = rng.multinomial(team_assists, pvals_a)[:, :n_players].T
        else:
            pvals_a = a_shares_arr / a_sum
            assists = rng.multinomial(team_assists, pvals_a).T
    else:
        assists = np.zeros((n_players, n_iterations), dtype=int)

    # Attacking points earned on pitch
    goals = goals * plays
    assists = assists * plays
    attack_pts = goals * goal_pts[:, None] + assists * rules.assist_points

    # 3. Clean sheets
    # A player gets CS if they play 60+ mins AND opponent scores 0 goals
    cs = plays_60 & (opp_team_goals[None, :] == 0)
    cs_points = cs * cs_pts[:, None]

    # 4. Goals Conceded
    gc_count = opp_team_goals[None, :] * plays
    gc_deductions = (gc_count // rules.goals_conceded_per_deduction) * rules.goals_conceded_points
    gc_points = gc_deductions * gc_applies[:, None]

    # 5. Defcon
    actions = rng.poisson(defcon_lam[:, None], size=(n_players, n_iterations))
    defcon_mask = actions >= defcon_thresholds[:, None]
    defcon_points = defcon_mask * rules.defensive_contribution_points * (1 - is_gkp[:, None])

    # 6. Saves
    saves = rng.poisson(saves_lam[:, None], size=(n_players, n_iterations))
    save_points = (saves // rules.saves_per_point) * rules.save_points * is_gkp[:, None]
    
    # Sum it all up
    total_points = app_pts + attack_pts + cs_points + gc_points + defcon_points + save_points
    
    # Calculate distributions
    results = []
    for i, (player, _, _) in enumerate(players_data):
        pts_arr = total_points[i]
        
        res = SimulationResult(
            player_fpl_id=player.fpl_id,
            fixture_fpl_id=fixture_fpl_id,
            mean_pts=float(np.mean(pts_arr)),
            median_pts=float(np.median(pts_arr)),
            ceiling_pts=float(np.percentile(pts_arr, 95)),
            floor_pts=float(np.percentile(pts_arr, 5)),
            p_10_plus=float(np.mean(pts_arr >= 10)),
            p_15_plus=float(np.mean(pts_arr >= 15)),
        )
        results.append(res)
        
    return results
