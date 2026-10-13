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


def test_wildcard_maximizes_xi_and_captain_points():
    # Construct a pool where spending extra budget on a bench player would
    # yield higher 15-squad points but lower XI + captain points.
    players = []
    # 2 GKPs: 1 starter (4.5m, 4pts), 1 bench (4.0m, 1pt)
    players.append(PlayerChoice(1, "GKP1", "GKP", 1, 45, 4.0))
    players.append(PlayerChoice(2, "GKP2", "GKP", 2, 40, 1.0))
    
    # 5 DEFs: 3 starters (4.5m, 4pts each), 2 cheap bench (4.0m, 1pt each)
    for i in range(3, 6):
        players.append(PlayerChoice(i, f"DEF{i}", "DEF", i, 45, 4.0))
    for i in range(6, 8):
        players.append(PlayerChoice(i, f"DEF{i}", "DEF", i, 40, 1.0))
        
    # 5 MIDs: 4 starters (5.0m, 5pts each), 1 cheap bench (4.5m, 1.5pts)
    for i in range(8, 12):
        players.append(PlayerChoice(i, f"MID{i}", "MID", i, 50, 5.0))
    players.append(PlayerChoice(12, "MID12", "MID", 12, 45, 1.5))
    
    # 3 FWDs:
    # Option A: Premium captain (14.0m, 12pts), Mid starter (7.0m, 6pts), Cheap bench (4.5m, 1pt) -> cost = 25.5m
    # Option B: Three balanced FWDs (8.5m, 7pts each) -> total FWD pts = 21, but max captain pts = 7 (so XI+cap = 7*2 + 7*2 = 28 vs 12*2 + 6 = 30)
    players.append(PlayerChoice(13, "PremiumCap", "FWD", 13, 140, 12.0))
    players.append(PlayerChoice(14, "MidFWD", "FWD", 14, 70, 6.0))
    players.append(PlayerChoice(15, "CheapBenchFWD", "FWD", 15, 45, 1.0))
    
    # Alternative balanced options
    players.append(PlayerChoice(16, "BalFWD1", "FWD", 16, 85, 7.0))
    players.append(PlayerChoice(17, "BalFWD2", "FWD", 17, 85, 7.0))
    players.append(PlayerChoice(18, "BalFWD3", "FWD", 18, 85, 7.0))
    
    # Set budget just enough for PremiumCap (total cost: 45+40 + 3*45+2*40 + 4*50+45 + 140+70+45 = 855)
    squad, xi_cap_xpts = optimize_wildcard(players, budget=860)
    xi, cap, bench, total_xi_pts = optimize_starting_xi(squad)
    
    # PremiumCap should be chosen and captained to maximize XI + captain points
    assert any(p.fpl_id == 13 for p in squad)
    assert cap.fpl_id == 13
    assert xi_cap_xpts == pytest.approx(total_xi_pts, abs=0.01)
