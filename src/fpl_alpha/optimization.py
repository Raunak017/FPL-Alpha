"""Squad & Transfer Optimizer (Plan step 12).

Uses Mixed Integer Linear Programming (MILP) via PuLP to select optimal
squads and starting XIs based on expected points.
"""
from __future__ import annotations

from dataclasses import dataclass
import pulp
import pandas as pd

@dataclass
class PlayerChoice:
    fpl_id: int
    name: str
    position: str
    team_id: int
    cost: int  # tenths of a million
    expected_points: float

def optimize_wildcard(
    players: list[PlayerChoice],
    budget: int = 1000,
    max_per_team: int = 3,
    bench_weight: float = 0.001,
) -> tuple[list[PlayerChoice], float]:
    """Select the optimal 15-man squad from scratch maximizing starting XI + captain expected points.

    Returns the chosen 15-man squad and the optimal starting XI + captain expected points.
    """
    prob = pulp.LpProblem("FPL_Wildcard_Optimization", pulp.LpMaximize)

    # Decision variables
    squad_vars = {
        p.fpl_id: pulp.LpVariable(f"squad_{p.fpl_id}", cat="Binary")
        for p in players
    }
    start_vars = {
        p.fpl_id: pulp.LpVariable(f"start_{p.fpl_id}", cat="Binary")
        for p in players
    }
    cap_vars = {
        p.fpl_id: pulp.LpVariable(f"cap_{p.fpl_id}", cat="Binary")
        for p in players
    }

    # Objective function: Maximize XI + Captain expected points (with small tie-breaker for bench)
    prob += pulp.lpSum(
        p.expected_points * start_vars[p.fpl_id]
        + p.expected_points * cap_vars[p.fpl_id]
        + bench_weight * p.expected_points * (squad_vars[p.fpl_id] - start_vars[p.fpl_id])
        for p in players
    )

    # Constraints
    # 1. Total squad players = 15
    prob += pulp.lpSum(squad_vars[p.fpl_id] for p in players) == 15

    # 2. Squad budget constraint
    prob += pulp.lpSum(p.cost * squad_vars[p.fpl_id] for p in players) <= budget

    # 3. Squad position limits (15-man squad: 2 GKP, 5 DEF, 5 MID, 3 FWD)
    positions = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
    for pos, limit in positions.items():
        prob += pulp.lpSum(
            squad_vars[p.fpl_id] for p in players if p.position == pos
        ) == limit

    # 4. Max players per team in squad
    team_ids = {p.team_id for p in players}
    for t_id in team_ids:
        prob += pulp.lpSum(
            squad_vars[p.fpl_id] for p in players if p.team_id == t_id
        ) <= max_per_team

    # 5. Starting XI must be subset of squad
    for p in players:
        prob += start_vars[p.fpl_id] <= squad_vars[p.fpl_id]

    # 6. Total starting players = 11
    prob += pulp.lpSum(start_vars[p.fpl_id] for p in players) == 11

    # 7. Valid starting formations
    prob += pulp.lpSum(start_vars[p.fpl_id] for p in players if p.position == "GKP") == 1
    prob += pulp.lpSum(start_vars[p.fpl_id] for p in players if p.position == "DEF") >= 3
    prob += pulp.lpSum(start_vars[p.fpl_id] for p in players if p.position == "DEF") <= 5
    prob += pulp.lpSum(start_vars[p.fpl_id] for p in players if p.position == "MID") >= 2
    prob += pulp.lpSum(start_vars[p.fpl_id] for p in players if p.position == "MID") <= 5
    prob += pulp.lpSum(start_vars[p.fpl_id] for p in players if p.position == "FWD") >= 1
    prob += pulp.lpSum(start_vars[p.fpl_id] for p in players if p.position == "FWD") <= 3

    # 8. Captain must be a starter
    for p in players:
        prob += cap_vars[p.fpl_id] <= start_vars[p.fpl_id]

    # 9. Exactly 1 captain
    prob += pulp.lpSum(cap_vars[p.fpl_id] for p in players) == 1

    # Solve
    try:
        prob.solve(pulp.GLPK_CMD(msg=False))
    except pulp.PulpSolverError:
        prob.solve(pulp.PULP_CBC_CMD(msg=False))

    if pulp.LpStatus[prob.status] != 'Optimal':
        raise ValueError(f"No optimal solution found. Status: {pulp.LpStatus[prob.status]}")

    chosen = [p for p in players if squad_vars[p.fpl_id].varValue == 1.0]
    starters = [p for p in players if start_vars[p.fpl_id].varValue == 1.0]
    captain = next(p for p in players if cap_vars[p.fpl_id].varValue == 1.0)
    xi_plus_captain_xpts = sum(p.expected_points for p in starters) + captain.expected_points

    return chosen, xi_plus_captain_xpts

def optimize_starting_xi(
    squad_15: list[PlayerChoice]
) -> tuple[list[PlayerChoice], PlayerChoice, list[PlayerChoice], float]:
    """Select the optimal starting XI and captain from a 15-man squad.
    
    Returns (Starting XI, Captain, Bench, Total expected points).
    """
    if len(squad_15) != 15:
        raise ValueError("Must provide exactly 15 players.")
        
    prob = pulp.LpProblem("FPL_Starting_XI", pulp.LpMaximize)
    
    # Variables
    start_vars = {p.fpl_id: pulp.LpVariable(f"start_{p.fpl_id}", cat="Binary") for p in squad_15}
    cap_vars = {p.fpl_id: pulp.LpVariable(f"cap_{p.fpl_id}", cat="Binary") for p in squad_15}
    
    # Objective: xi points + captain bonus
    prob += pulp.lpSum(
        p.expected_points * start_vars[p.fpl_id] + p.expected_points * cap_vars[p.fpl_id]
        for p in squad_15
    )
    
    # Constraints
    # 1. Total starting = 11
    prob += pulp.lpSum(start_vars[p.fpl_id] for p in squad_15) == 11
    
    # 2. Exactly 1 captain
    prob += pulp.lpSum(cap_vars[p.fpl_id] for p in squad_15) == 1
    
    # 3. Captain must be a starter
    for p in squad_15:
        prob += cap_vars[p.fpl_id] <= start_vars[p.fpl_id]
        
    # 4. Valid formations
    # GKP: 1
    # DEF: 3 to 5
    # MID: 2 to 5
    # FWD: 1 to 3
    prob += pulp.lpSum(start_vars[p.fpl_id] for p in squad_15 if p.position == "GKP") == 1
    prob += pulp.lpSum(start_vars[p.fpl_id] for p in squad_15 if p.position == "DEF") >= 3
    prob += pulp.lpSum(start_vars[p.fpl_id] for p in squad_15 if p.position == "DEF") <= 5
    prob += pulp.lpSum(start_vars[p.fpl_id] for p in squad_15 if p.position == "MID") >= 2
    prob += pulp.lpSum(start_vars[p.fpl_id] for p in squad_15 if p.position == "MID") <= 5
    prob += pulp.lpSum(start_vars[p.fpl_id] for p in squad_15 if p.position == "FWD") >= 1
    prob += pulp.lpSum(start_vars[p.fpl_id] for p in squad_15 if p.position == "FWD") <= 3

    # Solve
    try:
        prob.solve(pulp.GLPK_CMD(msg=False))
    except pulp.PulpSolverError:
        prob.solve()
    
    starting_xi = [p for p in squad_15 if start_vars[p.fpl_id].varValue == 1.0]
    bench = [p for p in squad_15 if start_vars[p.fpl_id].varValue == 0.0]
    captain = [p for p in squad_15 if cap_vars[p.fpl_id].varValue == 1.0][0]
    
    total_xpts = sum(p.expected_points for p in starting_xi) + captain.expected_points
    
    # Sort bench (e.g. by highest xpts first for sub priority)
    # Exclude bench GKP from outfield sub order
    bench_gkp = [p for p in bench if p.position == "GKP"]
    bench_outfield = sorted([p for p in bench if p.position != "GKP"], key=lambda x: x.expected_points, reverse=True)
    ordered_bench = bench_gkp + bench_outfield

    return starting_xi, captain, ordered_bench, total_xpts
