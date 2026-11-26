#!/usr/bin/env python3
"""Evaluate FPL Alpha Projections Against Real Match Performance.

Compares our expected points and underlying stats (xG, xA, clean sheets, minutes)
with official FPL match results.

Usage:
    python scripts/evaluate_projections.py                 # Summary table of all evaluated gameweeks
    python scripts/evaluate_projections.py --gw 6          # Detailed breakdown for Gameweek 6
    python scripts/evaluate_projections.py --backfill      # Backfill projections for past gameweeks and evaluate
    python scripts/evaluate_projections.py --player Saka   # Track player projections vs actuals across gameweeks
"""
from __future__ import annotations

import argparse
import sys

from fpl_alpha.evaluation import (
    backfill_historical_projections,
    evaluate_gameweek,
)
from fpl_alpha.storage import (
    load_gameweek_evaluations,
    open_database,
)


def _fmt(val: float | None, width: int = 6, dec: int = 2, sign: bool = False) -> str:
    if val is None or val != val:  # check for NaN
        return " " * (width - 4) + "N/A "
    fmt_str = f"{{:{'+' if sign else ''}{width}.{dec}f}}"
    return fmt_str.format(val)


def print_summary_table(evaluations: list) -> None:
    if not evaluations:
        print("No gameweek evaluations found in database.")
        print("Tip: Run with '--backfill' to generate baseline forecasts for completed gameweeks.")
        return

    print("=" * 105)
    print("FPL ALPHA PROJECTION EVALUATION — GAMEWEEK SUMMARY")
    print("=" * 105)
    header = (
        f"{'GW':^4} | {'Active N':^8} | {'Rel N':^6} | {'MAE':^6} | {'RMSE':^6} | "
        f"{'Bias':^6} | {'Pearson':^7} | {'Rank ρ':^7} | {'Top 10 (Ours/Opt)':^19} | {'CS Brier':^8}"
    )
    print(header)
    print("-" * 105)

    total_active_n = 0
    sum_mae = 0.0
    sum_rmse = 0.0
    sum_bias = 0.0
    sum_pearson = 0.0
    sum_spearman = 0.0
    total_top10_act = 0.0
    total_top10_opt = 0.0
    sum_cs_brier = 0.0

    for ev in evaluations:
        active = ev.active_players
        top10_str = f"{ev.top_10_actual_points:4.0f} / {ev.top_10_optimal_points:4.0f} ({(ev.top_10_actual_points/ev.top_10_optimal_points*100 if ev.top_10_optimal_points > 0 else 0):.0f}%)"
        print(
            f"GW{ev.gameweek:<2} | "
            f"{active.sample_size:^8} | "
            f"{ev.relevant_players.sample_size:^6} | "
            f"{active.mae:6.2f} | "
            f"{active.rmse:6.2f} | "
            f"{active.mean_bias:+6.2f} | "
            f"{active.pearson:+7.2f} | "
            f"{active.spearman:+7.2f} | "
            f"{top10_str:^19} | "
            f"{ev.clean_sheet_brier:8.3f}"
        )

        total_active_n += active.sample_size
        sum_mae += active.mae
        sum_rmse += active.rmse
        sum_bias += active.mean_bias
        sum_pearson += active.pearson
        sum_spearman += active.spearman
        total_top10_act += ev.top_10_actual_points
        total_top10_opt += ev.top_10_optimal_points
        sum_cs_brier += ev.clean_sheet_brier

    n_gws = len(evaluations)
    print("-" * 105)
    avg_top10_str = f"{total_top10_act:4.0f} / {total_top10_opt:4.0f} ({(total_top10_act/total_top10_opt*100 if total_top10_opt > 0 else 0):.0f}%)"
    print(
        f"{'AVG':^4} | "
        f"{int(total_active_n / n_gws):^8} | "
        f"{'-':^6} | "
        f"{sum_mae / n_gws:6.2f} | "
        f"{sum_rmse / n_gws:6.2f} | "
        f"{sum_bias / n_gws:+6.2f} | "
        f"{sum_pearson / n_gws:+7.2f} | "
        f"{sum_spearman / n_gws:+7.2f} | "
        f"{avg_top10_str:^19} | "
        f"{sum_cs_brier / n_gws:8.3f}"
    )
    print("=" * 105)
    print("* Active N = Players with > 0 minutes. Rel N = Projected xPts >= 3.0.")
    print("* Top 10 = Real points scored by top 10 projected vs optimal top 10.")


def print_gameweek_detail(summary, player_evals: list) -> None:
    print("=" * 80)
    print(f"GAMEWEEK {summary.gameweek} DETAILED EVALUATION REPORT")
    print("=" * 80)
    print(f"Run ID: {summary.run_id}")
    print(f"Evaluated At: {summary.evaluated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print()

    # Overall & Subsets
    print("PERFORMANCE OVERVIEW:")
    print(
        f"  Active Players (mins > 0):  N={summary.active_players.sample_size:<4} "
        f"MAE={summary.active_players.mae:.2f}  RMSE={summary.active_players.rmse:.2f}  "
        f"Bias={summary.active_players.mean_bias:+.2f}  "
        f"Pearson r={summary.active_players.pearson:+.2f}  Rank ρ={summary.active_players.spearman:+.2f}"
    )
    print(
        f"  Starters/Key (xPts >= 3.0): N={summary.relevant_players.sample_size:<4} "
        f"MAE={summary.relevant_players.mae:.2f}  RMSE={summary.relevant_players.rmse:.2f}  "
        f"Bias={summary.relevant_players.mean_bias:+.2f}  "
        f"Pearson r={summary.relevant_players.pearson:+.2f}  Rank ρ={summary.relevant_players.spearman:+.2f}"
    )
    print()

    # Decision Quality
    ratio = (summary.top_10_actual_points / summary.top_10_optimal_points * 100) if summary.top_10_optimal_points > 0 else 0
    print("DECISION QUALITY (TOP PICKS):")
    print(f"  Top 10 Projected Actual Points:  {summary.top_10_actual_points:.0f} pts")
    print(f"  Top 10 Optimal Actual Points:    {summary.top_10_optimal_points:.0f} pts")
    print(f"  Top 10 Capture Efficiency:       {ratio:.1f}%")
    print(f"  Top 10 / Top 20 Overlap:         {summary.top_10_overlap}/10 players in top 10, {summary.top_20_overlap}/20 in top 20")
    print()

    # Positional Breakdown
    print("POSITIONAL BREAKDOWN (Active Players):")
    print(f"  {'Pos':4} | {'Count':5} | {'MAE':6} | {'RMSE':6} | {'Bias':6} | {'Pearson':7} | {'Rank ρ':7}")
    print("  " + "-" * 55)
    for pos in ("GKP", "DEF", "MID", "FWD"):
        m = summary.position_metrics.get(pos)
        if m and m.sample_size > 0:
            print(f"  {pos:4} | {m.sample_size:5} | {m.mae:6.2f} | {m.rmse:6.2f} | {m.mean_bias:+6.2f} | {m.pearson:+7.2f} | {m.spearman:+7.2f}")
    print()

    # Component Stats
    print("UNDERLYING STATS ACCURACY:")
    print(f"  Expected Goals (xG vs Goals):      MAE={summary.goals_mae:.3f}   Pearson r={summary.goals_pearson:+.2f}")
    print(f"  Expected Assists (xA vs Assists):  MAE={summary.assists_mae:.3f}   Pearson r={summary.assists_pearson:+.2f}")
    print(f"  Clean Sheet Probability:           Brier Score={summary.clean_sheet_brier:.3f} (DEF/GKP 60'+)")
    print()

    # Top 10 Projected
    by_proj = sorted(player_evals, key=lambda pe: pe.projected_points, reverse=True)
    print("TOP 10 PROJECTED PLAYERS vs ACTUAL OUTCOME:")
    print(f"  {'Player':18} {'Team':4} {'Pos':3} {'Mins':4} | {'xPts':5} {'Actual':6} {'Delta':6} | {'xG':4} {'G':2} | {'xA':4} {'A':2} | {'p_CS':4} {'CS':2}")
    print("  " + "-" * 74)
    for pe in by_proj[:10]:
        delta = pe.actual_points - pe.projected_points
        print(
            f"  {pe.web_name:18} {pe.team_short_name:4} {pe.position:3} {pe.minutes:4d} | "
            f"{pe.projected_points:5.2f} {pe.actual_points:6d} {delta:+6.2f} | "
            f"{pe.projected_goals:4.2f} {pe.actual_goals:2d} | "
            f"{pe.projected_assists:4.2f} {pe.actual_assists:2d} | "
            f"{pe.projected_clean_sheet:4.2f} {pe.actual_clean_sheet:2d}"
        )
    print()

    # Top 10 Actual Scorers
    by_act = sorted(player_evals, key=lambda pe: pe.actual_points, reverse=True)
    print("TOP 10 ACTUAL SCORERS THAT GAMEWEEK (What did our system project?):")
    print(f"  {'Player':18} {'Team':4} {'Pos':3} {'Mins':4} | {'Actual':6} {'xPts':5} {'Delta':6} | {'G':2} {'xG':4} | {'A':2} {'xA':4} | {'CS':2} {'p_CS':4}")
    print("  " + "-" * 74)
    for pe in by_act[:10]:
        delta = pe.actual_points - pe.projected_points
        print(
            f"  {pe.web_name:18} {pe.team_short_name:4} {pe.position:3} {pe.minutes:4d} | "
            f"{pe.actual_points:6d} {pe.projected_points:5.2f} {delta:+6.2f} | "
            f"{pe.actual_goals:2d} {pe.projected_goals:4.2f} | "
            f"{pe.actual_assists:2d} {pe.projected_assists:4.2f} | "
            f"{pe.actual_clean_sheet:2d} {pe.projected_clean_sheet:4.2f}"
        )
    print()

    # Notable Outliers
    active_evals = [pe for pe in player_evals if pe.minutes > 0]
    by_diff_pos = sorted(active_evals, key=lambda pe: pe.actual_points - pe.projected_points, reverse=True)
    print("BIGGEST SURPRISE HAULS (Actual >> Projected):")
    for pe in by_diff_pos[:5]:
        d = pe.actual_points - pe.projected_points
        print(f"  + {pe.web_name:18} ({pe.team_short_name}) Actual={pe.actual_points:2d} vs xPts={pe.projected_points:.2f} ({d:+.2f} pts) [Goals: {pe.actual_goals}, Assists: {pe.actual_assists}]")
    print()

    by_diff_neg = sorted(active_evals, key=lambda pe: pe.projected_points - pe.actual_points, reverse=True)
    print("BIGGEST BUSTS (Projected >> Actual):")
    for pe in by_diff_neg[:5]:
        d = pe.actual_points - pe.projected_points
        print(f"  - {pe.web_name:18} ({pe.team_short_name}) xPts={pe.projected_points:.2f} vs Actual={pe.actual_points:2d} ({d:+.2f} pts) [Mins: {pe.minutes}]")
    print("=" * 80)


def print_player_history(connection, player_query: str) -> None:
    evaluations = load_gameweek_evaluations(connection)
    if not evaluations:
        print("No gameweek evaluations found.")
        return

    gws = [ev.gameweek for ev in evaluations]
    query = """
        SELECT
            h.gameweek,
            p.web_name,
            p.position,
            t.short_name,
            COALESCE(proj.expected_points, 0.0) AS exp_pts,
            h.total_points,
            h.minutes,
            COALESCE(proj.expected_goals, 0.0) AS exp_g,
            h.goals_scored,
            COALESCE(proj.expected_assists, 0.0) AS exp_a,
            h.assists,
            COALESCE(proj.p_clean_sheet, 0.0) AS p_cs,
            h.clean_sheets
        FROM player_gameweek_history h
        JOIN players p ON h.player_fpl_id = p.fpl_id
        JOIN teams t ON p.team_fpl_id = t.fpl_id
        LEFT JOIN (
            SELECT
                pfp.gameweek,
                pfp.player_fpl_id,
                SUM(pfp.expected_points) AS expected_points,
                SUM(pfp.expected_goals) AS expected_goals,
                SUM(pfp.expected_assists) AS expected_assists,
                MAX(pfp.p_clean_sheet) AS p_clean_sheet
            FROM player_fixture_projections pfp
            JOIN gameweek_projection_selections gps
                ON pfp.run_id = gps.run_id AND pfp.gameweek = gps.gameweek
            GROUP BY pfp.gameweek, pfp.player_fpl_id
        ) proj ON h.player_fpl_id = proj.player_fpl_id AND h.gameweek = proj.gameweek
        WHERE LOWER(p.web_name) LIKE LOWER(?)
        ORDER BY h.gameweek ASC
    """
    rows = connection.execute(query, [f"%{player_query}%"]).fetchall()
    if not rows:
        print(f"No player matching '{player_query}' found in history.")
        return

    print("=" * 85)
    name = rows[0][1]
    team = rows[0][3]
    pos = rows[0][2]
    print(f"PLAYER PROJECTION vs REAL PERFORMANCE: {name} ({team} - {pos})")
    print("=" * 85)
    print(f"{'GW':4} | {'Mins':4} | {'xPts':5} | {'Actual':6} | {'Delta':6} | {'xG':4} | {'G':2} | {'xA':4} | {'A':2} | {'p_CS':4} | {'CS':2}")
    print("-" * 85)
    tot_exp = 0.0
    tot_act = 0
    tot_xg = 0.0
    tot_g = 0
    tot_xa = 0.0
    tot_a = 0
    for r in rows:
        gw, _, _, _, xpts, act, mins, xg, g, xa, a, p_cs, cs = r
        delta = act - xpts
        print(
            f"GW{gw:<2} | {mins:4d} | {xpts:5.2f} | {act:6d} | {delta:+6.2f} | "
            f"{xg:4.2f} | {g:2d} | {xa:4.2f} | {a:2d} | {p_cs:4.2f} | {cs:2d}"
        )
        tot_exp += xpts
        tot_act += act
        tot_xg += xg
        tot_g += g
        tot_xa += xa
        tot_a += a

    print("-" * 85)
    print(
        f"{'TOT':4} | {'-':^4} | {tot_exp:5.2f} | {tot_act:6d} | {tot_act - tot_exp:+6.2f} | "
        f"{tot_xg:4.2f} | {tot_g:2d} | {tot_xa:4.2f} | {tot_a:2d} | {'-':^4} | {'-':^2}"
    )
    print("=" * 85)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gw", type=int, help="Gameweek to inspect in detail")
    parser.add_argument("--backfill", action="store_true", help="Generate and evaluate baseline projections for past gameweeks")
    parser.add_argument("--force", action="store_true", help="Force regenerate historical runs even if already stored")
    parser.add_argument("--player", type=str, help="Search player name and display GW-by-GW projection vs actuals")
    args = parser.parse_args()

    conn = open_database()
    try:
        if args.backfill:
            print("Backfilling historical baseline projections for completed gameweeks...")
            run_ids = backfill_historical_projections(conn, force=args.force)
            print(f"Successfully processed {len(run_ids)} gameweeks.\n")

        if args.player:
            print_player_history(conn, args.player)
            return

        if args.gw:
            summary, player_evals = evaluate_gameweek(conn, args.gw)
            print_gameweek_detail(summary, player_evals)
            return

        # Default: print summary table of all evaluated gameweeks
        evaluations = load_gameweek_evaluations(conn)
        print_summary_table(evaluations)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
