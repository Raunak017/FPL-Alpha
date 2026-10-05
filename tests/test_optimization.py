import pytest
from fpl_alpha.optimization import PlayerChoice, optimize_wildcard, optimize_starting_xi

def test_optimize_wildcard():
    # Create 30 dummy players with varying costs and xPts
    players = []
    for i in range(1, 31):
        pos = "GKP" if i <= 4 else "DEF" if i <= 12 else "MID" if i <= 22 else "FWD"
        players.append(PlayerChoice(
            fpl_id=i, name=f"Player_{i}", position=pos, team_id=(i%10)+1,
            cost=40 + (i%3)*10, expected_points=2.0 + (i%5)
        ))
        
    chosen, xpts = optimize_wildcard(players, budget=1000)
    
    assert len(chosen) == 15
    assert sum(p.cost for p in chosen) <= 1000
    pos_counts = {"GKP": 0, "DEF": 0, "MID": 0, "FWD": 0}
    for p in chosen:
        pos_counts[p.position] += 1
    assert pos_counts["GKP"] == 2
    assert pos_counts["DEF"] == 5
    assert pos_counts["MID"] == 5
    assert pos_counts["FWD"] == 3

def test_optimize_starting_xi():
    # Create 15-man squad
    squad = []
    for i in range(1, 16):
        pos = "GKP" if i <= 2 else "DEF" if i <= 7 else "MID" if i <= 12 else "FWD"
        squad.append(PlayerChoice(
            fpl_id=i, name=f"Player_{i}", position=pos, team_id=1,
            cost=50, expected_points=i * 1.0  # Higher ID = higher points
        ))
        
    xi, cap, bench, xpts = optimize_starting_xi(squad)
    
    assert len(xi) == 11
    assert len(bench) == 4
    # Highest point player should be captain (Player 15, FWD, 15.0 pts)
    assert cap.fpl_id == 15
    
    # 1 GKP should be in XI, 1 on bench
    assert sum(1 for p in xi if p.position == "GKP") == 1
    assert sum(1 for p in bench if p.position == "GKP") == 1
