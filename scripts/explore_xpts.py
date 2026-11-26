#!/usr/bin/env python3
"""xPts Explorer

Calculates projected points for all players using the FPL-Strength Fallback,
and allows filtering by team, position, price, and form.
"""
import argparse
import json
from datetime import datetime, timezone

from fpl_alpha.config import RAW
from fpl_alpha.identity import teams_from_bootstrap, player_snapshots_from_bootstrap
from fpl_alpha.ingestion import fpl
from fpl_alpha.allocation import attack_weights_from_bootstrap, allocate_fixture
from fpl_alpha.team_xg import fit_fpl_team_goals
from fpl_alpha.projections import project_player_fixture
from fpl_alpha.schemas import Player, PlayerSnapshot

def _f(v):
    return float(v) if v is not None else 0.0

def main():
    ap = argparse.ArgumentParser(description="Filter and explore projected FPL points")
    ap.add_argument("--player", "--name", dest="player", help="Filter by player name (e.g., Haaland, Saka)")
    ap.add_argument("--team", help="Filter by team short name (e.g., ARS, BHA)")
    ap.add_argument("--pos", help="Filter by position (GKP, DEF, MID, FWD)")
    ap.add_argument("--min-price", type=float, help="Minimum price (e.g., 5.0)")
    ap.add_argument("--max-price", type=float, help="Maximum price (e.g., 7.5)")
    ap.add_argument("--min-form", type=float, help="Minimum FPL form (e.g., 4.0)")
    ap.add_argument("--limit", type=int, default=20, help="Number of players to show (default: 20)")
    ap.add_argument("--sort", choices=["xpts", "form", "price", "rank"], default="xpts", help="Sort criteria")
    args = ap.parse_args()

    boot = json.loads((RAW / "fpl" / "bootstrap-static.json").read_text())
    teams = teams_from_bootstrap(boot)
    
    next_events = [e["id"] for e in boot.get("events", []) if e.get("is_next")]
    target_gameweek = next_events[0] if next_events else 1
    games_played = max(1.0, float(target_gameweek - 1))
    
    fpl_fixtures_path = RAW / "fpl" / "fixtures.json"
    gameweek_fixtures = [f for f in fpl.fixtures_from_api(json.loads(fpl_fixtures_path.read_text())) if f.event == target_gameweek]
    
    from fpl_alpha.storage import open_database, load_player_consistency
    from fpl_alpha.team_xg import resolve_fixture_team_goals
    conn = open_database()
    consistencies = load_player_consistency(conn, games_played=games_played, max_gameweek=int(games_played))

    rates = attack_weights_from_bootstrap(boot, games_played=games_played, consistencies=consistencies)
    el = {e["id"]: e for e in boot["elements"]}
    POS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
    
    now_utc = datetime.now(timezone.utc)
    snapshots = {s.player_fpl_id: s for s in player_snapshots_from_bootstrap(boot, now_utc)}
    results = []

    for fixture in gameweek_fixtures:
        home_team = next(t for t in teams if t.fpl_id == fixture.team_h_fpl_id)
        away_team = next(t for t in teams if t.fpl_id == fixture.team_a_fpl_id)
        
        home_fpl = next(t for t in boot["teams"] if t["id"] == fixture.team_h_fpl_id)
        away_fpl = next(t for t in boot["teams"] if t["id"] == fixture.team_a_fpl_id)
        
        h_str = home_fpl.get("strength_overall_home", 3)
        a_str = away_fpl.get("strength_overall_away", 3)
        
        model, cs = resolve_fixture_team_goals(
            conn,
            fixture,
            home_strength=h_str,
            away_strength=a_str,
            home_team_name=home_team.short_name,
            away_team_name=away_team.short_name,
        )
        
        for r in allocate_fixture(model, rates):
            e = el[r.fpl_id]
            pos = POS.get(e["element_type"], "UNK")
            cost = e["now_cost"] / 10.0
            form = _f(e.get("form"))
            team = home_team if r.team_fpl_id == home_team.fpl_id else away_team
            opp = away_team if r.team_fpl_id == home_team.fpl_id else home_team
            is_home = (r.team_fpl_id == home_team.fpl_id)
            opp_str = f"{opp.short_name} ({'H' if is_home else 'A'})"
            
            snapshot = snapshots[r.fpl_id]
            if snapshot.minutes <= 0:
                continue

            dummy_player = Player(
                fpl_id=r.fpl_id, web_name=e["web_name"], full_name="", 
                team_fpl_id=r.team_fpl_id, position=pos, now_cost=e["now_cost"]
            )
            cons = consistencies.get(r.fpl_id)
            proj = project_player_fixture(
                dummy_player,
                snapshot,
                r,
                cs[r.team_fpl_id],
                games_played=games_played,
                consistency=cons,
            )
            
            status = e.get("status", "a")
            chance = e.get("chance_of_playing_next_round")
            status_note = ""
            if status == "i" or chance == 0:
                status_note = "Injured (0%)"
            elif status == "s":
                status_note = "Suspended (0%)"
            elif status == "d" or (chance is not None and chance < 100):
                status_note = f"Doubtful ({chance}%)"

            if proj.expected_points > 0 or (args.player and args.player.lower() in e["web_name"].lower()):
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
                    "apps": cons.matches_played if cons else (1 if snapshot.minutes > 0 else 0),
                    "mins": int(snapshot.minutes),
                    "saves_90": _f(e.get("saves_per_90")),
                    "status_note": status_note,
                })

    if not results:
        print("No player projections available.")
        return

    # Assign overall and positional ranks based on xPts > 0 before filtering
    active_results = [r for r in results if r["xpts"] > 0]
    active_results.sort(key=lambda x: x["xpts"], reverse=True)
    pos_counters = {"GKP": 0, "DEF": 0, "MID": 0, "FWD": 0}
    for idx, r in enumerate(active_results, start=1):
        r["rank"] = idx
        pos_counters[r["pos"]] = pos_counters.get(r["pos"], 0) + 1
        r["pos_rank"] = pos_counters[r["pos"]]

    for r in results:
        if r.get("rank") is None:
            r["rank"] = None
            r["pos_rank"] = None

    filtered = []
    for r in results:
        if args.player and args.player.lower() not in r["name"].lower():
            continue
        if args.team and r["team"].upper() != args.team.upper():
            continue
        if args.pos and r["pos"].upper() != args.pos.upper():
            continue
        if args.min_price and r["cost"] < args.min_price:
            continue
        if args.max_price and r["cost"] > args.max_price:
            continue
        if args.min_form and r["form"] < args.min_form:
            continue
        filtered.append(r)

    if not filtered:
        print("No players match your filters.")
        return

    if args.sort == "xpts":
        filtered.sort(key=lambda x: x["xpts"], reverse=True)
    elif args.sort == "form":
        filtered.sort(key=lambda x: x["form"], reverse=True)
    elif args.sort == "price":
        filtered.sort(key=lambda x: x["cost"], reverse=True)
    elif args.sort == "rank":
        filtered.sort(key=lambda x: x["rank"] if x["rank"] is not None else 9999)
        
    filtered = filtered[:args.limit]
    
    has_status = any(r.get("status_note") for r in filtered)
    if has_status:
        print(f"{'Rank':<6} | {'PosRk':<6} | {'Player':<16} | {'Team':<4} | {'Pos':<3} | {'Opp':<7} | {'£':<5} | {'Apps':<4} | {'Form':<4} | {'xG':<4} | {'xA':<4} | {'xPts':<5} | {'Status'}")
        print("-" * 110)
        for r in filtered:
            rank_str = f"#{r['rank']}" if r["rank"] is not None else "-"
            pos_rank_str = f"#{r['pos_rank']}" if r["pos_rank"] is not None else "-"
            status = r.get("status_note", "")
            print(f"{rank_str:<6} | {pos_rank_str:<6} | {r['name']:<16} | {r['team']:<4} | {r['pos']:<3} | {r['opp']:<7} | £{r['cost']:<4.1f} | {r['apps']:<4} | {r['form']:<4.1f} | {r['xg']:<4.2f} | {r['xa']:<4.2f} | {r['xpts']:<5.2f} | {status}")
    else:
        print(f"{'Rank':<6} | {'PosRk':<6} | {'Player':<16} | {'Team':<4} | {'Pos':<3} | {'Opp':<7} | {'£':<5} | {'Apps':<4} | {'Form':<4} | {'xG':<4} | {'xA':<4} | {'xPts':<5}")
        print("-" * 96)
        for r in filtered:
            rank_str = f"#{r['rank']}" if r["rank"] is not None else "-"
            pos_rank_str = f"#{r['pos_rank']}" if r["pos_rank"] is not None else "-"
            print(f"{rank_str:<6} | {pos_rank_str:<6} | {r['name']:<16} | {r['team']:<4} | {r['pos']:<3} | {r['opp']:<7} | £{r['cost']:<4.1f} | {r['apps']:<4} | {r['form']:<4.1f} | {r['xg']:<4.2f} | {r['xa']:<4.2f} | {r['xpts']:<5.2f}")

if __name__ == "__main__":
    main()
