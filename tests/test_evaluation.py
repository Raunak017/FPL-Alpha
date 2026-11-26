from datetime import datetime, timezone
import math
import uuid
import pytest

from fpl_alpha.evaluation import (
    _brier_score,
    _pearson,
    _ranks,
    _spearman,
    compute_metric_summary,
    evaluate_and_persist_gameweek,
    evaluate_gameweek,
)
from fpl_alpha.schemas import (
    GameweekEvaluationSummary,
    MetricSummary,
    Player,
    PlayerFixtureProjection,
    PlayerGameweekHistory,
    ProjectionRun,
    Team,
)
from fpl_alpha.storage import (
    load_gameweek_evaluations,
    open_database,
    persist_projection_run,
    select_gameweek_projection_run,
    upsert_gameweek_evaluation,
    upsert_player_gameweek_history,
    upsert_players,
    upsert_teams,
)


def test_pearson_math():
    # Perfect positive
    assert _pearson([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]) == pytest.approx(1.0)
    # Perfect negative
    assert _pearson([1.0, 2.0, 3.0], [6.0, 4.0, 2.0]) == pytest.approx(-1.0)
    # Constant inputs (zero variance) should not divide by zero
    assert _pearson([2.0, 2.0, 2.0], [1.0, 2.0, 3.0]) == 0.0
    # Length < 2
    assert _pearson([1.0], [2.0]) == 0.0


def test_ranks_and_spearman():
    # Ranks with ties: [10, 20, 20, 40] -> ranks [1.0, 2.5, 2.5, 4.0]
    ranks = _ranks([10.0, 20.0, 20.0, 40.0])
    assert ranks == [1.0, 2.5, 2.5, 4.0]

    # Spearman rank correlation
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert _spearman(xs, ys) == pytest.approx(1.0)

    # Inverted
    assert _spearman(xs, [50.0, 40.0, 30.0, 20.0, 10.0]) == pytest.approx(-1.0)


def test_brier_score():
    # Perfect predictions
    assert _brier_score([1.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)
    # Complete miss
    assert _brier_score([1.0, 0.0], [0.0, 1.0]) == pytest.approx(1.0)
    # Mid probability: (0.5 - 1)^2 + (0.5 - 0)^2 = 0.25 + 0.25 = 0.5 / 2 = 0.25
    assert _brier_score([0.5, 0.5], [1.0, 0.0]) == pytest.approx(0.25)


def test_compute_metric_summary():
    preds = [3.0, 4.0, 5.0]
    acts = [2.0, 4.0, 6.0]
    # errors: +1, 0, -1 -> abs errors: 1, 0, 1 -> MAE = 2/3
    # squared errors: 1, 0, 1 -> RMSE = sqrt(2/3)
    # mean bias = 0
    m = compute_metric_summary(preds, acts)
    assert m.sample_size == 3
    assert m.mae == pytest.approx(2.0 / 3.0, abs=1e-3)
    assert m.rmse == pytest.approx(math.sqrt(2.0 / 3.0), abs=1e-3)
    assert m.mean_bias == pytest.approx(0.0)
    assert m.pearson == pytest.approx(1.0)


def test_evaluate_gameweek_end_to_end(tmp_path):
    conn = open_database(tmp_path / "test.duckdb")

    # Seed teams
    team = Team(fpl_id=1, name="Arsenal", short_name="ARS", aliases=())
    upsert_teams(conn, [team])

    # Seed player
    player = Player(
        fpl_id=10,
        web_name="Saka",
        full_name="Bukayo Saka",
        team_fpl_id=1,
        position="MID",
        now_cost=100,
    )
    upsert_players(conn, [player])

    # Seed projection run and projection
    as_of = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    run_id = str(uuid.uuid4())
    run = ProjectionRun(
        run_id=run_id,
        gameweek=1,
        model_name="test_model",
        model_version="1.0",
        scoring_rules_version="2026_default",
        input_fingerprint="fp123",
        as_of=as_of,
        created_at=as_of,
    )
    proj = PlayerFixtureProjection(
        run_id=run_id,
        gameweek=1,
        player_fpl_id=10,
        fixture_fpl_id=101,
        expected_points=6.5,
        expected_goals=0.6,
        expected_assists=0.3,
        p_clean_sheet=0.4,
    )
    persist_projection_run(conn, run, [proj])
    select_gameweek_projection_run(conn, 1, run_id, as_of, selection_reason="test")

    # Seed actual match history
    history = PlayerGameweekHistory(
        player_fpl_id=10,
        fixture_fpl_id=101,
        gameweek=1,
        kickoff_time="2026-09-01T15:00:00Z",
        opponent_team_fpl_id=2,
        was_home=True,
        team_h_score=2,
        team_a_score=1,
        minutes=90,
        total_points=8,
        goals_scored=1,
        assists=0,
        clean_sheets=0,
        goals_conceded=1,
        own_goals=0,
        penalties_saved=0,
        penalties_missed=0,
        yellow_cards=0,
        red_cards=0,
        saves=0,
        bonus=1,
        bps=25,
        influence=30.0,
        creativity=20.0,
        threat=40.0,
        ict_index=9.0,
        starts=1,
        expected_goals=0.6,
        expected_assists=0.3,
        expected_goal_involvements=0.9,
        expected_goals_conceded=1.0,
        value=100,
        transfers_balance=0,
        selected=100000,
        transfers_in=0,
        transfers_out=0,
    )
    upsert_player_gameweek_history(conn, [history])

    # Evaluate
    summary, player_evals = evaluate_gameweek(conn, 1)

    assert summary.gameweek == 1
    assert summary.all_players.sample_size == 1
    assert summary.active_players.sample_size == 1
    # expected 6.5 vs actual 8 -> abs error 1.5, bias -1.5
    assert summary.all_players.mae == pytest.approx(1.5)
    assert summary.all_players.mean_bias == pytest.approx(-1.5)
    assert summary.top_10_actual_points == 8.0
    assert summary.goals_mae == pytest.approx(0.4)  # exp 0.6 vs 1 goal

    assert len(player_evals) == 1
    assert player_evals[0].web_name == "Saka"
    assert player_evals[0].projected_points == 6.5
    assert player_evals[0].actual_points == 8

    # Persist and reload
    evaluate_and_persist_gameweek(conn, 1)
    stored = load_gameweek_evaluations(conn)
    assert len(stored) == 1
    assert stored[0].gameweek == 1
    assert stored[0].all_players.mae == pytest.approx(1.5)
