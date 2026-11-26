"""Deterministic expected-points (xPts) assembler (Plan step 8).

Combines player-level probabilities, team-level match probabilities, and
the official scoring rules to produce a single ``PlayerFixtureProjection``.

For now, this implements the baseline:
    xPts = P(start) * ( Appearance + P(CS)*CS_pts + xG*g_pts + xA*a_pts )
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable
import uuid

import duckdb

from fpl_alpha.allocation import allocate_fixture, attack_weights_from_bootstrap, shrink_rate
from fpl_alpha.config import RAW
from fpl_alpha.identity import player_snapshots_from_bootstrap, teams_from_bootstrap
from fpl_alpha.ingestion import fpl
from fpl_alpha.minutes import availability_factor, start_probability
from fpl_alpha.schemas import (
    Fixture,
    Player,
    PlayerConsistency,
    PlayerFixtureAttack,
    PlayerFixtureProjection,
    PlayerSnapshot,
    ProjectionRun,
    TeamGoalModel,
)
from fpl_alpha.scoring import CURRENT_RULESET, FPLScoringRules
from fpl_alpha.storage import (
    load_player_consistency,
    persist_projection_run,
    select_gameweek_projection_run,
)
from fpl_alpha.team_xg import resolve_fixture_team_goals

POS_DEFCON90_PRIOR = {"GKP": 0.0, "DEF": 7.5, "MID": 8.0, "FWD": 4.0, "UNK": 6.0}
POS_SAVES90_PRIOR = {"GKP": 3.0, "DEF": 0.0, "MID": 0.0, "FWD": 0.0, "UNK": 0.0}
POS_GC90_PRIOR = {"GKP": 1.3, "DEF": 1.3, "MID": 0.0, "FWD": 0.0, "UNK": 0.0}


def project_player_fixture(
    player: Player,
    snapshot: PlayerSnapshot,
    attack: PlayerFixtureAttack,
    p_clean_sheet: float,
    *,
    fixture_fpl_id: int = 0,
    run_id: str = "run_0",
    gameweek: int = 0,
    games_played: float = 38.0,
    consistency: PlayerConsistency | None = None,
    rules: FPLScoringRules = CURRENT_RULESET,
) -> PlayerFixtureProjection:
    """Assemble deterministic baseline xPts for a single player in one fixture."""
    from fpl_alpha.minutes import expected_minutes as calc_expected_minutes
    
    # Zero-history / unplayed players: if they haven't played, no xPts
    if snapshot.minutes <= 0:
        return PlayerFixtureProjection(
            run_id=run_id,
            gameweek=gameweek,
            player_fpl_id=player.fpl_id,
            fixture_fpl_id=fixture_fpl_id,
            expected_points=0.0,
            expected_goals=0.0,
            expected_assists=0.0,
            p_start=0.0,
            p_60_plus=0.0,
            p_clean_sheet=p_clean_sheet,
            appearance_points=0.0,
            goal_points=0.0,
            assist_points=0.0,
            clean_sheet_points=0.0,
            save_points=0.0,
            defensive_contribution_points=0.0,
            goals_conceded_points=0.0,
            bonus_points=0.0,
        )

    # Minutes model
    avail = availability_factor(snapshot.status, snapshot.chance_of_playing_next_round)
    matches_played = consistency.matches_played if consistency is not None else None
    matches_started = consistency.matches_started if consistency is not None else None
    p_start = start_probability(
        snapshot.starts,
        snapshot.minutes,
        avail,
        games_played=games_played,
        matches_started=matches_started,
        matches_played=matches_played,
    )
    exp_mins = calc_expected_minutes(
        snapshot.minutes,
        avail,
        games_played=games_played,
        matches_played=matches_played,
    )
    
    # We roughly approximate P(60') as P(start) for the baseline.
    p_60 = p_start
    
    appearance_pts = (
        p_start * rules.appearance_under_60_points 
        + p_60 * (rules.appearance_60_plus_points - rules.appearance_under_60_points)
    )
    
    goal_pts = attack.exp_goals * rules.goal_points.get(player.position, 0)
    assist_pts = attack.exp_assists * rules.assist_points
    
    # Clean sheet requires 60+ minutes
    cs_pts = p_60 * p_clean_sheet * rules.clean_sheet_points.get(player.position, 0)

    mins = max(0.0, float(snapshot.minutes))
    shrunk_defcon = shrink_rate(
        snapshot.defensive_contribution_per_90,
        mins,
        POS_DEFCON90_PRIOR.get(player.position, 6.0),
    )
    shrunk_saves = shrink_rate(
        snapshot.saves_per_90,
        mins,
        POS_SAVES90_PRIOR.get(player.position, 0.0),
    )
    shrunk_gc = shrink_rate(
        snapshot.goals_conceded_per_90,
        mins,
        POS_GC90_PRIOR.get(player.position, 0.0),
    )

    defcon_pts = expected_defcon_points(
        player.position, shrunk_defcon, exp_mins, rules=rules
    )
    save_pts = expected_save_points(
        player.position, shrunk_saves, exp_mins, rules=rules
    )
    gc_pts = expected_goals_conceded_points(
        player.position, shrunk_gc, exp_mins, rules=rules
    )

    total_xpts = appearance_pts + goal_pts + assist_pts + cs_pts + defcon_pts + save_pts + gc_pts
    
    return PlayerFixtureProjection(
        run_id=run_id,
        gameweek=gameweek,
        player_fpl_id=player.fpl_id,
        fixture_fpl_id=fixture_fpl_id,
        expected_points=total_xpts,
        expected_goals=attack.exp_goals,
        expected_assists=attack.exp_assists,
        p_start=p_start,
        p_60_plus=p_60,
        p_clean_sheet=p_clean_sheet,
        appearance_points=appearance_pts,
        goal_points=goal_pts,
        assist_points=assist_pts,
        clean_sheet_points=cs_pts,
        defensive_contribution_points=defcon_pts,
        save_points=save_pts,
        goals_conceded_points=gc_pts,
    )

import math

def poisson_prob_ge(lam: float, k: int) -> float:
    """Probability of a Poisson random variable with parameter `lam` being >= `k`."""
    if lam <= 0:
        return 0.0
    # P(X >= k) = 1 - sum_{i=0}^{k-1} e^(-lam) * lam^i / i!
    p_less_than_k = 0.0
    for i in range(k):
        p_less_than_k += math.exp(-lam) * (lam ** i) / math.factorial(i)
    return max(0.0, 1.0 - p_less_than_k)

def expected_defcon_points(
    position: str,
    defcon_per_90: float,
    expected_minutes: float,
    *,
    rules: FPLScoringRules = CURRENT_RULESET,
) -> float:
    """Estimate expected defensive contribution points (Step 10)."""
    if position == "GKP":
        return 0.0
    
    if defcon_per_90 <= 0 or expected_minutes <= 0:
        return 0.0
        
    lam = defcon_per_90 * (expected_minutes / 90.0)
    
    threshold = rules.defender_defensive_contribution_threshold
    if position in {"MID", "FWD"}:
        threshold = rules.attacker_defensive_contribution_threshold
        
    p_ge_threshold = poisson_prob_ge(lam, threshold)
    return p_ge_threshold * rules.defensive_contribution_points


def expected_save_points(
    position: str,
    saves_per_90: float,
    expected_minutes: float,
    *,
    rules: FPLScoringRules = CURRENT_RULESET,
) -> float:
    """Estimate expected save points (Step 10).
    
    A GKP gets 1 point per 3 saves. We compute E[floor(saves / 3)] 
    assuming saves follow a Poisson distribution.
    """
    if position != "GKP" or saves_per_90 <= 0 or expected_minutes <= 0:
        return 0.0
        
    lam = saves_per_90 * (expected_minutes / 90.0)
    if lam <= 0:
        return 0.0
        
    # E[floor(X/3)] = sum_{k=0}^inf floor(k/3) * P(X=k)
    # We truncate the infinite sum at 25 saves (prob is ~0)
    expected_points = 0.0
    for k in range(3, 25):
        pts = (k // rules.saves_per_point) * rules.save_points
        if pts > 0:
            prob_k = math.exp(-lam) * (lam ** k) / math.factorial(k)
            expected_points += pts * prob_k
            
    return expected_points

def expected_goals_conceded_points(
    position: str,
    goals_conceded_per_90: float,
    expected_minutes: float,
    *,
    rules: FPLScoringRules = CURRENT_RULESET,
) -> float:
    """Estimate expected goals-conceded penalty points (Step 10).
    
    GKP/DEF get -1 point per 2 goals conceded. 
    Computed as E[floor(goals / 2)] * rules.goals_conceded_points.
    """
    if position not in {"GKP", "DEF"} or goals_conceded_per_90 <= 0 or expected_minutes <= 0:
        return 0.0
        
    lam = goals_conceded_per_90 * (expected_minutes / 90.0)
    if lam <= 0:
        return 0.0
        
    expected_pts = 0.0
    for k in range(2, 15):
        pts = (k // rules.goals_conceded_per_deduction) * rules.goals_conceded_points
        if pts != 0:
            prob_k = math.exp(-lam) * (lam ** k) / math.factorial(k)
            expected_pts += pts * prob_k
            
    return expected_pts


def generate_gameweek_projections(
    connection: duckdb.DuckDBPyConnection,
    gameweek: int,
    *,
    bootstrap: dict[str, Any] | None = None,
    fixtures_payload: list[dict[str, Any]] | None = None,
    as_of: datetime | None = None,
    run_id: str | None = None,
    model_name: str = "fpl_alpha_v1",
    model_version: str = "1.0.0",
    use_historical_state: bool = False,
    persist: bool = False,
    select: bool = False,
    selection_reason: str = "selected gameweek projection run",
    rules: FPLScoringRules = CURRENT_RULESET,
) -> tuple[ProjectionRun, list[PlayerFixtureProjection]]:
    """Assemble projections for all players in a target gameweek.

    Can evaluate against historical state (using only data known before the gameweek)
    or current live state, and optionally persist the resulting immutable run.
    """
    as_of = as_of or datetime.now(timezone.utc)
    effective_run_id = run_id or str(uuid.uuid4())

    if bootstrap is None:
        boot_path = RAW / "fpl" / "bootstrap-static.json"
        if not boot_path.exists():
            raise FileNotFoundError(f"Missing FPL bootstrap data at {boot_path}")
        bootstrap = json.loads(boot_path.read_text())

    if fixtures_payload is None:
        fixtures_path = RAW / "fpl" / "fixtures.json"
        if not fixtures_path.exists():
            raise FileNotFoundError(f"Missing FPL fixtures data at {fixtures_path}")
        fixtures_payload = json.loads(fixtures_path.read_text())

    all_fixtures = fpl.fixtures_from_api(fixtures_payload)
    gameweek_fixtures = [f for f in all_fixtures if f.event == gameweek]
    if not gameweek_fixtures:
        raise ValueError(f"No fixtures found for gameweek {gameweek}")

    teams = teams_from_bootstrap(bootstrap)

    if use_historical_state and gameweek > 1:
        history_rows = connection.execute(
            """
            SELECT 
                player_fpl_id,
                COUNT(*) AS matches,
                SUM(CASE WHEN starts > 0 THEN 1 ELSE 0 END) AS starts,
                SUM(minutes) AS minutes,
                SUM(total_points) AS total_points,
                SUM(goals_scored) AS goals_scored,
                SUM(assists) AS assists,
                SUM(clean_sheets) AS clean_sheets,
                SUM(expected_goals) AS expected_goals,
                SUM(expected_assists) AS expected_assists,
                SUM(saves) AS saves,
                SUM(goals_conceded) AS goals_conceded
            FROM player_gameweek_history
            WHERE gameweek < ?
            GROUP BY player_fpl_id
            """,
            [gameweek],
        ).fetchall()
        h_dict = {r[0]: r for r in history_rows}

        modified_elements = []
        for el_raw in bootstrap["elements"]:
            e = dict(el_raw)
            p_id = e["id"]
            if p_id in h_dict:
                r = h_dict[p_id]
                mins = int(r[3])
                e["minutes"] = mins
                e["starts"] = int(r[2])
                e["total_points"] = int(r[4])
                e["goals_scored"] = int(r[5])
                e["assists"] = int(r[6])
                e["clean_sheets"] = int(r[7])
                e["expected_goals"] = str(r[8] or 0.0)
                e["expected_assists"] = str(r[9] or 0.0)
                e["expected_goals_per_90"] = str(round(float(r[8] or 0.0) * 90.0 / mins, 2)) if mins > 0 else "0.0"
                e["expected_assists_per_90"] = str(round(float(r[9] or 0.0) * 90.0 / mins, 2)) if mins > 0 else "0.0"
                e["clean_sheets_per_90"] = str(round(float(r[7] or 0) * 90.0 / mins, 2)) if mins > 0 else "0.0"
                e["saves_per_90"] = str(round(float(r[10] or 0) * 90.0 / mins, 2)) if mins > 0 else "0.0"
                e["goals_conceded_per_90"] = str(round(float(r[11] or 0) * 90.0 / mins, 2)) if mins > 0 else "0.0"
            else:
                e["minutes"] = 0
                e["starts"] = 0
                e["expected_goals"] = "0.0"
                e["expected_assists"] = "0.0"
                e["expected_goals_per_90"] = "0.0"
                e["expected_assists_per_90"] = "0.0"
                e["clean_sheets_per_90"] = "0.0"
                e["saves_per_90"] = "0.0"
                e["goals_conceded_per_90"] = "0.0"
            modified_elements.append(e)

        effective_bootstrap = dict(bootstrap, elements=modified_elements)
    else:
        effective_bootstrap = bootstrap

    games_played = max(0.0, float(gameweek - 1))
    consistencies = (
        load_player_consistency(
            connection,
            games_played=max(1.0, games_played),
            max_gameweek=gameweek - 1,
        )
        if gameweek > 1
        else {}
    )

    rates = attack_weights_from_bootstrap(
        effective_bootstrap,
        games_played=max(1.0, games_played),
        consistencies=consistencies,
    )
    snapshots = {
        s.player_fpl_id: s
        for s in player_snapshots_from_bootstrap(effective_bootstrap, as_of)
    }
    elements_map = {e["id"]: e for e in effective_bootstrap["elements"]}
    POS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

    projections: list[PlayerFixtureProjection] = []

    for fixture in gameweek_fixtures:
        home_team = next((t for t in teams if t.fpl_id == fixture.team_h_fpl_id), None)
        away_team = next((t for t in teams if t.fpl_id == fixture.team_a_fpl_id), None)
        if home_team is None or away_team is None:
            continue

        home_fpl = next(
            (t for t in effective_bootstrap["teams"] if t["id"] == fixture.team_h_fpl_id),
            {},
        )
        away_fpl = next(
            (t for t in effective_bootstrap["teams"] if t["id"] == fixture.team_a_fpl_id),
            {},
        )
        h_str = home_fpl.get("strength_overall_home", 3)
        a_str = away_fpl.get("strength_overall_away", 3)

        model, cs = resolve_fixture_team_goals(
            connection,
            fixture,
            home_strength=h_str,
            away_strength=a_str,
            home_team_name=home_team.short_name,
            away_team_name=away_team.short_name,
        )

        for r in allocate_fixture(model, rates):
            e = elements_map.get(r.fpl_id)
            if e is None:
                continue
            pos = POS.get(e["element_type"], "UNK")
            snapshot = snapshots.get(r.fpl_id)
            if snapshot is None:
                continue

            player = Player(
                fpl_id=r.fpl_id,
                web_name=e["web_name"],
                full_name=f"{e.get('first_name', '')} {e.get('second_name', '')}".strip(),
                team_fpl_id=r.team_fpl_id,
                position=pos,
                now_cost=e.get("now_cost", 0),
            )
            cons = consistencies.get(r.fpl_id)
            proj = project_player_fixture(
                player,
                snapshot,
                r,
                cs.get(r.team_fpl_id, 0.0),
                fixture_fpl_id=fixture.fpl_id,
                run_id=effective_run_id,
                gameweek=gameweek,
                games_played=games_played,
                consistency=cons,
                rules=rules,
            )
            projections.append(proj)

    fingerprint_dict = {
        "gameweek": gameweek,
        "model_name": model_name,
        "model_version": model_version,
        "scoring_rules_version": rules.version,
        "as_of": as_of.isoformat(),
        "fixture_ids": sorted(f.fpl_id for f in gameweek_fixtures),
        "use_historical_state": use_historical_state,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_dict, sort_keys=True).encode()
    ).hexdigest()

    run = ProjectionRun(
        run_id=effective_run_id,
        gameweek=gameweek,
        model_name=model_name,
        model_version=model_version,
        scoring_rules_version=rules.version,
        input_fingerprint=fingerprint,
        as_of=as_of,
        created_at=as_of,
        is_partial=False,
        notes=f"Generated projection for GW{gameweek}"
        + (" (historical state)" if use_historical_state else ""),
    )

    if persist:
        stored_run_id = persist_projection_run(connection, run, projections)
        effective_run_id = stored_run_id
        if select:
            select_gameweek_projection_run(
                connection,
                gameweek,
                stored_run_id,
                as_of,
                selection_reason=selection_reason,
            )

    return run, projections

