#!/usr/bin/env python3
"""xPts Explorer

Calculates projected points for all players using the FPL-Strength Fallback,
and allows filtering by team, position, price, and form.
"""
import argparse
import json
from datetime import datetime, timezone

from fpl_alpha.config import RAW
from fpl_alpha.identity import teams_from_bootstrap
from fpl_alpha.ingestion import fpl
from fpl_alpha.allocation import attack_weights_from_bootstrap, allocate_fixture
from fpl_alpha.team_xg import fit_fpl_team_goals
from fpl_alpha.projections import project_player_fixture
from fpl_alpha.schemas import Player, PlayerSnapshot

def _f(v):
    return float(v) if v is not None else 0.0

def main():
    ap = argparse.ArgumentParser(description="Filter and explore projected FPL points")
    ap.add_argument("--team", help="Filter by team short name (e.g., ARS, BHA)")
    ap.add_argument("--pos", help="Filter by position (GKP, DEF, MID, FWD)")
    ap.add_argument("--max-price", type=float, help="Maximum price (e.g., 7.5)")
    ap.add_argument("--min-form", type=float, help="Minimum FPL form (e.g., 4.0)")
    ap.add_argument("--limit", type=int, default=20, help="Number of players to show (default: 20)")
    ap.add_argument("--sort", choices=["xpts", "form", "price"], default="xpts", help="Sort criteria")
    args = ap.parse_args()

    boot = json.loads((RAW / "fpl" / "bootstrap-static.json").read_text())
    teams = teams_from_bootstrap(boot)
    
    next_events = [e["id"] for e in boot.get("events", []) if e.get("is_next")]
    target_gameweek = next_events[0] if next_events else 1
    games_played = max(1.0, float(target_gameweek - 1))
    
    fpl_fixtures_path = RAW / "fpl" / "fixtures.json"
    gameweek_fixtures = [f for f in fpl.fixtures_from_api(json.loads(fpl_fixtures_path.read_text())) if f.event == target_gameweek]
    
    rates = attack_weights_from_bootstrap(boot, games_played=games_played)
    el = {e["id"]: e for e in boot["elements"]}
    POS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
    
    results = []
    
    for fixture in gameweek_fixtures:
        home_team = next(t for t in teams if t.fpl_id == fixture.team_h_fpl_id)
        away_team = next(t for t in teams if t.fpl_id == fixture.team_a_fpl_id)
        
        home_fpl = next(t for t in boot["teams"] if t["id"] == fixture.team_h_fpl_id)
        away_fpl = next(t for t in boot["teams"] if t["id"] == fixture.team_a_fpl_id)
        
        h_str = home_fpl.get("strength_overall_home", 3)
        a_str = away_fpl.get("strength_overall_away", 3)
        
        model = fit_fpl_team_goals(
            f"{home_team.short_name}_v_{away_team.short_name}", 
            home_team.fpl_id, away_team.fpl_id, h_str, a_str
        )
        cs = {home_team.fpl_id: model.p_clean_sheet_home, away_team.fpl_id: model.p_clean_sheet_away}
        
        for r in allocate_fixture(model, rates):
            e = el[r.fpl_id]
            pos = POS.get(e["element_type"], "UNK")
            cost = e["now_cost"] / 10.0
            form = _f(e.get("form"))
            team = home_team if r.team_fpl_id == home_team.fpl_id else away_team
            opp = away_team if r.team_fpl_id == home_team.fpl_id else home_team
            is_home = (r.team_fpl_id == home_team.fpl_id)
            opp_str = f"{opp.short_name} ({'H' if is_home else 'A'})"
            
            # Apply filters
            if args.team and team.short_name.upper() != args.team.upper(): continue
            if args.pos and pos.upper() != args.pos.upper(): continue
            if args.max_price and cost > args.max_price: continue
            if args.min_form and form < args.min_form: continue
            
            dummy_player = Player(
                fpl_id=r.fpl_id, web_name=e["web_name"], full_name="", 
                team_fpl_id=r.team_fpl_id, position=pos, now_cost=e["now_cost"]
            )
            # Correctly map defensive/save stats needed for projections
            dummy_snapshot = PlayerSnapshot(
                player_fpl_id=r.fpl_id, captured_at=datetime.now(timezone.utc), now_cost=e["now_cost"], 
                selected_by_percent=0.0, status=e.get("status", "a"), total_points=0, points_per_game=0.0, 
                form=form, minutes=int(_f(e.get("minutes"))), starts=int(_f(e.get("starts"))), goals_scored=0, assists=0,
                clean_sheets=0, bonus=0, bps=0, expected_goals=0.0, expected_assists=0.0, 
                expected_goal_involvements=0.0, expected_goals_conceded=0.0, 
                clean_sheets_per_90=_f(e.get("clean_sheets_per_90")), 
                defensive_contribution_per_90=_f(e.get("expected_goals_conceded_per_90")), # FPL doesn't have def_contrib natively, usually map to xgc or 0
                expected_goals_per_90=_f(e.get("expected_goals_per_90")), 
                expected_assists_per_90=_f(e.get("expected_assists_per_90")), 
                expected_goal_involvements_per_90=_f(e.get("expected_goal_involvements_per_90")), 
                expected_goals_conceded_per_90=_f(e.get("expected_goals_conceded_per_90")), 
                goals_conceded_per_90=_f(e.get("goals_conceded_per_90")), 
                saves_per_90=_f(e.get("saves_per_90")), 
                starts_per_90=_f(e.get("starts_per_90")), 
                influence=0.0, creativity=0.0, threat=0.0, ict_index=0.0,
                chance_of_playing_next_round=e.get("chance_of_playing_next_round"), chance_of_playing_this_round=None, 
                transfers_in_event=0, transfers_out_event=0, transfers_in=0, transfers_out=0
            )
            
            proj = project_player_fixture(dummy_player, dummy_snapshot, r, cs[r.team_fpl_id], games_played=games_played)
            
            if proj.expected_points > 0:
                results.append({
                    "name": e["web_name"],
                    "team": team.short_name,
                    "pos": pos,
                    "cost": cost,
                    "form": form,
                    "opp": opp_str,
                    "xpts": proj.expected_points,
                    "xg": r.exp_goals,
                    "xa": r.exp_assists,
                    "mins": int(dummy_snapshot.minutes),
                    "saves_90": _f(e.get("saves_per_90"))
                })
                
    if not results:
        print("No players match your filters.")
        return

    if args.sort == "xpts":
        results.sort(key=lambda x: x["xpts"], reverse=True)
    elif args.sort == "form":
        results.sort(key=lambda x: x["form"], reverse=True)
    elif args.sort == "price":
        results.sort(key=lambda x: x["cost"], reverse=True)
        
    results = results[:args.limit]
    
    print(f"{'Player':<15} | {'Team':<4} | {'Pos':<3} | {'Opp':<7} | {'£':<4} | {'Form':<4} | {'xG':<4} | {'xA':<4} | {'xPts':<5}")
    print("-" * 75)
    for r in results:
        print(f"{r['name']:<15} | {r['team']:<4} | {r['pos']:<3} | {r['opp']:<7} | £{r['cost']:<3.1f} | {r['form']:<4.1f} | {r['xg']:<4.2f} | {r['xa']:<4.2f} | {r['xpts']:<5.2f}")

if __name__ == "__main__":
    main()
