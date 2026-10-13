#!/usr/bin/env python3
"""Run the complete end-to-end pipeline (Offline).

Generates expected points using the FPL Strength Fallback (no Odds API),
then feeds the results into the MILP Optimizer to pick the mathematically
optimal 15-man wildcard squad and starting XI.
"""
import json
from datetime import datetime, timezone

from fpl_alpha.config import RAW
from fpl_alpha.identity import teams_from_bootstrap, player_snapshots_from_bootstrap
from fpl_alpha.ingestion import fpl
from fpl_alpha.allocation import attack_weights_from_bootstrap, allocate_fixture
from fpl_alpha.team_xg import fit_fpl_team_goals
from fpl_alpha.projections import project_player_fixture
from fpl_alpha.schemas import Player, PlayerSnapshot
from fpl_alpha.scoring import CURRENT_RULESET
from fpl_alpha.optimization import PlayerChoice, optimize_wildcard, optimize_starting_xi


def _f(v):
    return float(v) if v is not None else 0.0

def main():
    print("Loading FPL Data...")
    boot = json.loads((RAW / "fpl" / "bootstrap-static.json").read_text())
    teams = teams_from_bootstrap(boot)
    
    # Identify target gameweek
    next_events = [e["id"] for e in boot.get("events", []) if e.get("is_next")]
    target_gameweek = next_events[0] if next_events else 1
    games_played = max(1.0, float(target_gameweek - 1))
    
    print(f"Targeting Gameweek {target_gameweek} (games played so far: {games_played}).")
    
    fpl_fixtures_path = RAW / "fpl" / "fixtures.json"
    gameweek_fixtures = [f for f in fpl.fixtures_from_api(json.loads(fpl_fixtures_path.read_text())) if f.event == target_gameweek]
    
    rates = attack_weights_from_bootstrap(boot, games_played=games_played)
    el = {e["id"]: e for e in boot["elements"]}
    POS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
    now_utc = datetime.now(timezone.utc)
    snapshots = {s.player_fpl_id: s for s in player_snapshots_from_bootstrap(boot, now_utc)}
    
    print("Running Projections (FPL Strength Fallback)...")
    projections = []
    opp_display = {}
    
    for fixture in gameweek_fixtures:
        home_team = next(t for t in teams if t.fpl_id == fixture.team_h_fpl_id)
        away_team = next(t for t in teams if t.fpl_id == fixture.team_a_fpl_id)
        
        home_fpl = next(t for t in boot["teams"] if t["id"] == fixture.team_h_fpl_id)
        away_fpl = next(t for t in boot["teams"] if t["id"] == fixture.team_a_fpl_id)
        
        h_str = home_fpl.get("strength_overall_home", 3)
        a_str = away_fpl.get("strength_overall_away", 3)
        
        model = fit_fpl_team_goals(
            f"{home_team.short_name}_v_{away_team.short_name}", 
            home_team.fpl_id, away_team.fpl_id, 
            h_str, a_str
        )
        cs = {home_team.fpl_id: model.p_clean_sheet_home, away_team.fpl_id: model.p_clean_sheet_away}
        
        for r in allocate_fixture(model, rates):
            e = el[r.fpl_id]
            pos = POS.get(e["element_type"], "UNK")
            
            is_home = (r.team_fpl_id == home_team.fpl_id)
            if is_home:
                opp_display[r.fpl_id] = f"{away_team.short_name} (H)"
            else:
                opp_display[r.fpl_id] = f"{home_team.short_name} (A)"
                
            player = Player(
                fpl_id=r.fpl_id, web_name=e["web_name"], full_name="", 
                team_fpl_id=r.team_fpl_id, position=pos, now_cost=e["now_cost"]
            )
            snapshot = snapshots[r.fpl_id]
            
            proj = project_player_fixture(
                player, snapshot, r, cs[r.team_fpl_id], 
                games_played=games_played
            )
            
            projections.append(PlayerChoice(
                fpl_id=r.fpl_id,
                name=e["web_name"],
                position=pos,
                team_id=r.team_fpl_id,
                cost=e["now_cost"],
                expected_points=proj.expected_points
            ))

    print("\nOptimizing 15-Man Wildcard Squad...")
    # Clean out injured/unavailable players to avoid picking 0.0 pointers just for budget
    available_players = [p for p in projections if p.expected_points > 0]
    
    squad, squad_xpts = optimize_wildcard(available_players, budget=1000)
    
    print("\nOptimizing Starting XI & Captain...")
    starters, captain, bench, xi_xpts = optimize_starting_xi(squad)
    
    print(f"\n==============================================")
    print(f" OPTIMAL GW{target_gameweek} WILDCARD TEAM (xPts: {xi_xpts:.2f})")
    print(f"==============================================")
    
    print("\n[ STARTING XI ]")
    for pos in ["GKP", "DEF", "MID", "FWD"]:
        pos_players = [p for p in starters if p.position == pos]
        for p in pos_players:
            cap_str = " (C)" if p.fpl_id == captain.fpl_id else ""
            pts = p.expected_points * (2 if p.fpl_id == captain.fpl_id else 1)
            opp = opp_display.get(p.fpl_id, "UNK")
            print(f"  {p.position} | {p.name:15} | {opp:7} | £{p.cost/10:.1f}m | {pts:5.2f} pts{cap_str}")
            
    print("\n[ BENCH ]")
    for p in bench:
        opp = opp_display.get(p.fpl_id, "UNK")
        print(f"  {p.position} | {p.name:15} | {opp:7} | £{p.cost/10:.1f}m | {p.expected_points:5.2f} pts")
        
    print(f"\nTotal Cost: £{sum(p.cost for p in squad)/10:.1f}m")

if __name__ == "__main__":
    main()
