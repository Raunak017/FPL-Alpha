"""Projection evaluation and accuracy tracking against real FPL performance.

Compares deterministic expected points (xPts), expected goals (xG), expected
assists (xA), clean sheets, and expected minutes against realized match stats
from FPL official API data (stored in `player_gameweek_history`).

Provides:
- Statistical metrics: MAE, RMSE, Pearson correlation, Spearman rank correlation, bias.
- Top-N decision metrics: Actual points scored by top-10 predicted vs optimal top-10.
- Positional & component breakdowns (goals, assists, clean sheets, minutes).
- Automatic evaluation hook for when passed gameweeks are updated.
- Backfill capabilities for historical gameweeks.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import math
from typing import Any, Iterable

import duckdb

from .projections import generate_gameweek_projections
from .schemas import (
    GameweekEvaluationSummary,
    MetricSummary,
    PlayerEvaluation,
)
from .storage import (
    load_gameweek_evaluations,
    upsert_gameweek_evaluation,
)


def _pearson(xs: list[float], ys: list[float]) -> float:
    """Calculate Pearson correlation coefficient between two lists."""
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx <= 1e-9 or sy <= 1e-9:
        return 0.0
    corr = cov / (sx * sy)
    return max(-1.0, min(1.0, corr))


def _ranks(xs: list[float]) -> list[float]:
    """Assign average ranks to ties (1-based)."""
    n = len(xs)
    order = sorted(range(n), key=lambda i: xs[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _spearman(xs: list[float], ys: list[float]) -> float:
    """Calculate Spearman rank correlation coefficient between two lists."""
    if len(xs) < 2:
        return 0.0
    return _pearson(_ranks(xs), _ranks(ys))


def _brier_score(probs: list[float], actuals: list[float]) -> float:
    """Mean squared error for probability forecasts."""
    if not probs:
        return 0.0
    return sum((p - a) ** 2 for p, a in zip(probs, actuals)) / len(probs)


def compute_metric_summary(predicted: list[float], actual: list[float]) -> MetricSummary:
    """Compute comprehensive error and correlation metrics."""
    n = len(predicted)
    if n == 0 or len(actual) != n:
        return MetricSummary(
            sample_size=0,
            mae=0.0,
            rmse=0.0,
            mean_bias=0.0,
            pearson=0.0,
            spearman=0.0,
        )

    mae = sum(abs(p - a) for p, a in zip(predicted, actual)) / n
    rmse = math.sqrt(sum((p - a) ** 2 for p, a in zip(predicted, actual)) / n)
    mean_bias = sum(p - a for p, a in zip(predicted, actual)) / n
    pearson = _pearson(predicted, actual)
    spearman = _spearman(predicted, actual)

    return MetricSummary(
        sample_size=n,
        mae=round(mae, 4),
        rmse=round(rmse, 4),
        mean_bias=round(mean_bias, 4),
        pearson=round(pearson, 4),
        spearman=round(spearman, 4),
    )


def evaluate_gameweek(
    connection: duckdb.DuckDBPyConnection,
    gameweek: int,
    run_id: str | None = None,
) -> tuple[GameweekEvaluationSummary, list[PlayerEvaluation]]:
    """Evaluate projections against realized stats for a single gameweek.

    Returns an aggregate `GameweekEvaluationSummary` and a list of detailed
    `PlayerEvaluation` records.
    """
    effective_run_id = run_id
    if effective_run_id is None:
        sel_row = connection.execute(
            "SELECT run_id FROM gameweek_projection_selections WHERE gameweek = ?",
            [gameweek],
        ).fetchone()
        if sel_row is not None:
            effective_run_id = str(sel_row[0])
        else:
            latest_run = connection.execute(
                "SELECT run_id FROM projection_runs WHERE gameweek = ? ORDER BY as_of DESC LIMIT 1",
                [gameweek],
            ).fetchone()
            if latest_run is not None:
                effective_run_id = str(latest_run[0])

    if effective_run_id is None:
        raise ValueError(f"No projection run found for gameweek {gameweek}")

    # Verify actual history exists
    has_history = connection.execute(
        "SELECT EXISTS (SELECT 1 FROM player_gameweek_history WHERE gameweek = ?)",
        [gameweek],
    ).fetchone()[0]
    if not has_history:
        raise ValueError(f"No realized match history ingested for gameweek {gameweek}")

    # Load projections aggregated per player
    proj_rows = connection.execute(
        """
        SELECT
            player_fpl_id,
            SUM(expected_points) AS exp_points,
            SUM(COALESCE(expected_goals, 0.0)) AS exp_goals,
            SUM(COALESCE(expected_assists, 0.0)) AS exp_assists,
            MAX(COALESCE(p_clean_sheet, 0.0)) AS p_clean_sheet,
            MAX(COALESCE(p_start, 0.0)) AS p_start
        FROM player_fixture_projections
        WHERE run_id = ? AND gameweek = ?
        GROUP BY player_fpl_id
        """,
        [effective_run_id, gameweek],
    ).fetchall()
    projections = {
        r[0]: {
            "exp_points": float(r[1]),
            "exp_goals": float(r[2]),
            "exp_assists": float(r[3]),
            "p_clean_sheet": float(r[4]),
            "p_start": float(r[5]),
        }
        for r in proj_rows
    }

    # Load realized stats aggregated per player
    hist_rows = connection.execute(
        """
        SELECT
            h.player_fpl_id,
            p.web_name,
            p.position,
            t.short_name AS team_name,
            SUM(h.minutes) AS minutes,
            SUM(COALESCE(h.starts, 0)) AS starts,
            SUM(h.total_points) AS total_points,
            SUM(h.goals_scored) AS goals_scored,
            SUM(h.assists) AS assists,
            MAX(h.clean_sheets) AS clean_sheets
        FROM player_gameweek_history h
        JOIN players p ON h.player_fpl_id = p.fpl_id
        JOIN teams t ON p.team_fpl_id = t.fpl_id
        WHERE h.gameweek = ?
        GROUP BY h.player_fpl_id, p.web_name, p.position, t.short_name
        """,
        [gameweek],
    ).fetchall()

    player_evaluations: list[PlayerEvaluation] = []
    for r in hist_rows:
        p_id = r[0]
        web_name = r[1]
        pos = r[2]
        team_name = r[3]
        mins = int(r[4])
        starts = int(r[5])
        actual_pts = int(r[6])
        actual_g = int(r[7])
        actual_a = int(r[8])
        actual_cs = int(r[9])

        pr = projections.get(p_id)
        if pr is not None:
            exp_pts = pr["exp_points"]
            exp_g = pr["exp_goals"]
            exp_a = pr["exp_assists"]
            p_cs = pr["p_clean_sheet"]
        else:
            exp_pts = 0.0
            exp_g = 0.0
            exp_a = 0.0
            p_cs = 0.0

        pts_err = exp_pts - actual_pts
        abs_err = abs(pts_err)

        player_evaluations.append(
            PlayerEvaluation(
                player_fpl_id=p_id,
                web_name=web_name,
                position=pos,
                team_short_name=team_name,
                gameweek=gameweek,
                minutes=mins,
                starts=starts,
                projected_points=round(exp_pts, 2),
                actual_points=actual_pts,
                points_error=round(pts_err, 2),
                abs_points_error=round(abs_err, 2),
                projected_goals=round(exp_g, 2),
                actual_goals=actual_g,
                projected_assists=round(exp_a, 2),
                actual_assists=actual_a,
                projected_clean_sheet=round(p_cs, 2),
                actual_clean_sheet=actual_cs,
            )
        )

    # 1. Overall metrics (all players)
    all_preds = [pe.projected_points for pe in player_evaluations]
    all_acts = [float(pe.actual_points) for pe in player_evaluations]
    all_summary = compute_metric_summary(all_preds, all_acts)

    # 2. Active players metrics (minutes > 0)
    active_evals = [pe for pe in player_evaluations if pe.minutes > 0]
    act_preds = [pe.projected_points for pe in active_evals]
    act_acts = [float(pe.actual_points) for pe in active_evals]
    active_summary = compute_metric_summary(act_preds, act_acts)

    # 3. Relevant players metrics (xPts >= 3.0)
    rel_evals = [pe for pe in player_evaluations if pe.projected_points >= 3.0]
    rel_preds = [pe.projected_points for pe in rel_evals]
    rel_acts = [float(pe.actual_points) for pe in rel_evals]
    relevant_summary = compute_metric_summary(rel_preds, rel_acts)

    # 4. Positional breakdown (active players)
    position_metrics: dict[str, MetricSummary] = {}
    for pos in ("GKP", "DEF", "MID", "FWD"):
        pos_evals = [pe for pe in active_evals if pe.position == pos]
        position_metrics[pos] = compute_metric_summary(
            [pe.projected_points for pe in pos_evals],
            [float(pe.actual_points) for pe in pos_evals],
        )

    # 5. Top-10 and Top-20 ranking performance
    by_predicted = sorted(player_evaluations, key=lambda pe: pe.projected_points, reverse=True)
    by_actual = sorted(player_evaluations, key=lambda pe: pe.actual_points, reverse=True)

    top_10_pred = by_predicted[:10]
    top_10_act = by_actual[:10]
    top_20_pred = by_predicted[:20]
    top_20_act = by_actual[:20]

    top_10_act_pts = sum(pe.actual_points for pe in top_10_pred)
    top_10_opt_pts = sum(pe.actual_points for pe in top_10_act)

    top_10_pred_ids = {pe.player_fpl_id for pe in top_10_pred}
    top_10_act_ids = {pe.player_fpl_id for pe in top_10_act}
    top_10_overlap = len(top_10_pred_ids & top_10_act_ids)

    top_20_pred_ids = {pe.player_fpl_id for pe in top_20_pred}
    top_20_act_ids = {pe.player_fpl_id for pe in top_20_act}
    top_20_overlap = len(top_20_pred_ids & top_20_act_ids)

    # 6. Component statistics
    g_preds = [pe.projected_goals for pe in active_evals]
    g_acts = [float(pe.actual_goals) for pe in active_evals]
    g_mae = sum(abs(p - a) for p, a in zip(g_preds, g_acts)) / len(g_preds) if g_preds else 0.0
    g_pearson = _pearson(g_preds, g_acts)

    a_preds = [pe.projected_assists for pe in active_evals]
    a_acts = [float(pe.actual_assists) for pe in active_evals]
    a_mae = sum(abs(p - a) for p, a in zip(a_preds, a_acts)) / len(a_preds) if a_preds else 0.0
    a_pearson = _pearson(a_preds, a_acts)

    # Clean sheet Brier score for defensive assets who played at least 60 minutes
    cs_evals = [pe for pe in active_evals if pe.position in ("GKP", "DEF") and pe.minutes >= 60]
    cs_brier = _brier_score(
        [pe.projected_clean_sheet for pe in cs_evals],
        [float(pe.actual_clean_sheet) for pe in cs_evals],
    )

    summary = GameweekEvaluationSummary(
        gameweek=gameweek,
        run_id=effective_run_id,
        evaluated_at=datetime.now(timezone.utc),
        all_players=all_summary,
        active_players=active_summary,
        relevant_players=relevant_summary,
        position_metrics=position_metrics,
        top_10_actual_points=float(top_10_act_pts),
        top_10_optimal_points=float(top_10_opt_pts),
        top_10_overlap=top_10_overlap,
        top_20_overlap=top_20_overlap,
        goals_mae=round(g_mae, 4),
        goals_pearson=round(g_pearson, 4),
        assists_mae=round(a_mae, 4),
        assists_pearson=round(a_pearson, 4),
        clean_sheet_brier=round(cs_brier, 4),
    )

    return summary, player_evaluations


def evaluate_and_persist_gameweek(
    connection: duckdb.DuckDBPyConnection,
    gameweek: int,
    run_id: str | None = None,
) -> GameweekEvaluationSummary:
    """Evaluate a gameweek run and persist the summary metrics to DuckDB."""
    summary, _ = evaluate_gameweek(connection, gameweek, run_id=run_id)
    upsert_gameweek_evaluation(connection, summary)
    return summary


def evaluate_all_passed_gameweeks(
    connection: duckdb.DuckDBPyConnection,
) -> dict[int, GameweekEvaluationSummary]:
    """Evaluate all finalized gameweeks that have stored projection runs."""
    rows = connection.execute(
        """
        SELECT DISTINCT s.gameweek
        FROM gameweek_projection_selections s
        JOIN gameweek_history_ingestions h ON s.gameweek = h.gameweek
        ORDER BY s.gameweek ASC
        """
    ).fetchall()

    summaries: dict[int, GameweekEvaluationSummary] = {}
    for (gw,) in rows:
        summary = evaluate_and_persist_gameweek(connection, gw)
        summaries[gw] = summary
    return summaries


def backfill_historical_projections(
    connection: duckdb.DuckDBPyConnection,
    gameweeks: Iterable[int] | None = None,
    *,
    force: bool = False,
) -> list[str]:
    """Generate baseline projections for historical gameweeks, select, and evaluate.

    Uses strictly historical state for past gameweeks (no lookahead bias).
    """
    if gameweeks is None:
        rows = connection.execute(
            "SELECT gameweek FROM gameweek_history_ingestions ORDER BY gameweek ASC"
        ).fetchall()
        target_gws = [r[0] for r in rows]
    else:
        target_gws = list(gameweeks)

    run_ids: list[str] = []
    for gw in target_gws:
        if not force:
            existing = connection.execute(
                "SELECT run_id FROM gameweek_projection_selections WHERE gameweek = ?",
                [gw],
            ).fetchone()
            if existing is not None:
                evaluate_and_persist_gameweek(connection, gw, run_id=str(existing[0]))
                run_ids.append(str(existing[0]))
                continue

        run, _ = generate_gameweek_projections(
            connection,
            gw,
            use_historical_state=True,
            persist=True,
            select=True,
            selection_reason="baseline historical backfill",
        )
        evaluate_and_persist_gameweek(connection, gw, run_id=run.run_id)
        run_ids.append(run.run_id)

    return run_ids
