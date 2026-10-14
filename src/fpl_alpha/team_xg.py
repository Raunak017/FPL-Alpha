"""Market-implied team xG (Plan step 4).

Turn match markets (1X2, over/under totals, BTTS) into per-team Poisson goal
rates, then derive clean-sheet probabilities and a score distribution. This is
the bridge from raw market probabilities to player-level modelling.

Baseline model: independent Poisson. We fit (lambda_home, lambda_away) so the
model-implied probabilities best match the fair (de-vigged) market probabilities,
then read clean-sheet probs and the score-line grid off the fitted lambdas.

Pure stdlib — no numpy/scipy needed for the baseline. A Dixon–Coles low-score
correction is the natural next upgrade (see TODO).
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from collections.abc import Iterable
from typing import Any

from .markets import consensus_from_latest_odds, latest_odds_snapshot_provenance
from .schemas import (
    Fixture,
    FixtureTeamXG,
    MarketModelComparison,
    MarketProb,
    TeamGoalModel,
    TeamGoalProjection,
)
from .storage import (
    insert_team_goal_projection,
    load_fixture,
    load_latest_fixture_team_xg,
)

# Goal ceiling for integrating the Poisson grid. P(goals > 10) is negligible
# for any realistic team lambda (<0.1% at lambda=3), so truncation is safe.
_MAX_GOALS = 10
_LAMBDA_LO, _LAMBDA_HI = 0.05, 5.0


def poisson_pmf(k: int, lam: float) -> float:
    """P(X = k) for X ~ Poisson(lam)."""
    if lam < 0:
        raise ValueError(f"lambda must be >= 0, got {lam}")
    return math.exp(-lam) * lam**k / math.factorial(k)


def model_probs(
    lambda_home: float, lambda_away: float, total_line: float | None = None
) -> dict[str, float]:
    """Model-implied outcome probabilities under independent Poisson.

    Returns 1X2 (home/draw/away), BTTS (btts_yes/btts_no), and — if a
    ``total_line`` is given — over/under that line.
    """
    ph = [poisson_pmf(h, lambda_home) for h in range(_MAX_GOALS + 1)]
    pa = [poisson_pmf(a, lambda_away) for a in range(_MAX_GOALS + 1)]

    home = draw = away = btts_yes = over = 0.0
    for h in range(_MAX_GOALS + 1):
        for a in range(_MAX_GOALS + 1):
            p = ph[h] * pa[a]
            if h > a:
                home += p
            elif h == a:
                draw += p
            else:
                away += p
            if h >= 1 and a >= 1:
                btts_yes += p
            if total_line is not None and (h + a) > total_line:
                over += p

    out = {
        "home": home,
        "draw": draw,
        "away": away,
        "btts_yes": btts_yes,
        "btts_no": 1.0 - btts_yes,
    }
    if total_line is not None:
        out["over"] = over
        out["under"] = 1.0 - over
    return out


def score_matrix(lambda_home: float, lambda_away: float) -> dict[str, float]:
    """Full score-line distribution as {"home-away": prob} over the goal grid."""
    ph = [poisson_pmf(h, lambda_home) for h in range(_MAX_GOALS + 1)]
    pa = [poisson_pmf(a, lambda_away) for a in range(_MAX_GOALS + 1)]
    return {
        f"{h}-{a}": ph[h] * pa[a]
        for h in range(_MAX_GOALS + 1)
        for a in range(_MAX_GOALS + 1)
    }


# --- Parsing market probabilities into fit targets --------------------------
def _build_targets(
    market_probs: Iterable[MarketProb],
) -> tuple[dict[str, float], float | None]:
    """Map MarketProb records to (targets, total_line) the fitter understands.

    Recognized: h2h (home/draw/away), totals (over/under, line parsed from the
    market string, e.g. 'totals_over_2.5'), btts (yes/no). Unknown markets are
    ignored so a richer feed degrades gracefully.
    """
    targets: dict[str, float] = {}
    total_line: float | None = None
    for mp in market_probs:
        market, outcome = mp.market.lower(), mp.outcome.lower()
        if market.startswith("h2h") and outcome in ("home", "draw", "away"):
            targets[outcome] = mp.prob
        elif market.startswith("totals") and outcome in ("over", "under"):
            m = re.search(r"(\d+(?:\.\d+)?)", market)
            if m:
                total_line = float(m.group(1))
                targets[outcome] = mp.prob
        elif market.startswith("btts") and outcome in ("yes", "no"):
            targets[f"btts_{outcome}"] = mp.prob
    return targets, total_line


def _loss(lh: float, la: float, targets: dict[str, float], total_line: float | None) -> float:
    model = model_probs(lh, la, total_line)
    return sum((model[k] - v) ** 2 for k, v in targets.items() if k in model)


def _golden_min(f, lo: float, hi: float, tol: float = 1e-5):
    """1D golden-section minimization of a (near-)unimodal f on [lo, hi]."""
    gr = (math.sqrt(5) - 1) / 2
    c, d = hi - gr * (hi - lo), lo + gr * (hi - lo)
    fc, fd = f(c), f(d)
    while hi - lo > tol:
        if fc < fd:
            hi, d, fd = d, c, fc
            c = hi - gr * (hi - lo)
            fc = f(c)
        else:
            lo, c, fc = c, d, fd
            d = lo + gr * (hi - lo)
            fd = f(d)
    return (lo + hi) / 2


def fit_team_goals(
    fixture_id: str,
    home_team_fpl_id: int,
    away_team_fpl_id: int,
    market_probs: list[MarketProb],
) -> TeamGoalModel:
    """Infer (lambda_home, lambda_away) consistent with the fixture's fair
    market probabilities under independent Poisson, then compute clean-sheet
    probabilities and the score-line distribution.

    Fitting is coordinate descent with golden-section line searches — the loss
    is smooth and effectively unimodal in each lambda, so this converges in a
    handful of sweeps without needing scipy.

    TODO(step 4): Dixon–Coles low-score correction once the baseline is trusted.
    """
    targets, total_line = _build_targets(market_probs)
    if not targets:
        raise ValueError(
            f"no usable markets for fixture {fixture_id}; need h2h/totals/btts probabilities"
        )

    lh, la = 1.4, 1.1  # sensible EPL priors as the starting point
    for _ in range(50):
        prev_lh, prev_la = lh, la
        lh = _golden_min(lambda x: _loss(x, la, targets, total_line), _LAMBDA_LO, _LAMBDA_HI)
        la = _golden_min(lambda x: _loss(lh, x, targets, total_line), _LAMBDA_LO, _LAMBDA_HI)
        if abs(lh - prev_lh) + abs(la - prev_la) < 1e-6:
            break

    model = model_probs(lh, la, total_line)
    residuals = {k: model[k] - targets[k] for k in targets if k in model}
    fit_loss = sum(r**2 for r in residuals.values())
    market_provenance = {
        "markets": sorted(set(mp.market for mp in market_probs)),
        "n_books": max((mp.n_books for mp in market_probs), default=0),
        "total_line": total_line,
        "targets": targets,
    }

    return TeamGoalModel(
        fixture_id=fixture_id,
        home_team_fpl_id=home_team_fpl_id,
        away_team_fpl_id=away_team_fpl_id,
        lambda_home=lh,
        lambda_away=la,
        # A clean sheet = the OTHER team fails to score.
        p_clean_sheet_home=poisson_pmf(0, la),
        p_clean_sheet_away=poisson_pmf(0, lh),
        score_dist=score_matrix(lh, la),
        fit_loss=fit_loss,
        residuals=residuals,
        market_provenance=market_provenance,
    )


def fit_fixture_from_duckdb(
    connection: Any,
    fixture_fpl_id: int,
    provider_key: str = "propline",
    captured_at: datetime | None = None,
) -> FixtureTeamXG:
    """Step 4: DuckDB consensus -> fit_team_goals() -> FixtureTeamXG."""
    market_probs = consensus_from_latest_odds(
        connection, fixture_fpl_id, provider_key=provider_key
    )
    if not market_probs:
        raise ValueError(
            f"No usable complete market odds found in DuckDB for fixture {fixture_fpl_id} (provider={provider_key})"
        )

    fixture = load_fixture(connection, fixture_fpl_id)
    if fixture is None:
        raise ValueError(f"Fixture {fixture_fpl_id} not found in fixtures table")

    event_ids, captured_min, captured_max, _ = latest_odds_snapshot_provenance(
        connection, fixture_fpl_id, provider_key
    )
    c_at = captured_at or captured_max or datetime.now(timezone.utc)
    model = fit_team_goals(
        str(fixture_fpl_id), fixture.team_h_fpl_id, fixture.team_a_fpl_id, market_probs
    )
    return FixtureTeamXG(
        fixture_fpl_id=fixture_fpl_id,
        provider_key=provider_key,
        captured_at=c_at,
        lambda_home=model.lambda_home,
        lambda_away=model.lambda_away,
        p_clean_sheet_home=model.p_clean_sheet_home,
        p_clean_sheet_away=model.p_clean_sheet_away,
        fit_loss=model.fit_loss,
        residuals=model.residuals,
        market_provenance=model.market_provenance,
    )


def fit_and_persist_fixture_team_xg(
    connection: Any,
    fixture_fpl_id: int,
    provider_key: str = "propline",
    captured_at: datetime | None = None,
) -> FixtureTeamXG:
    """Step 4: DuckDB consensus -> fit_team_goals() -> persisted team-xG in DuckDB."""
    projection = build_and_persist_team_goal_projection(
        connection,
        fixture_fpl_id,
        provider_key=provider_key,
        generated_at=captured_at,
    )
    return projection.to_fixture_team_xg()


def fit_fpl_team_goals(
    fixture_id: str,
    home_team_fpl_id: int,
    away_team_fpl_id: int,
    home_strength: int,
    away_strength: int,
) -> TeamGoalModel:
    """Fallback: Estimate expected goals directly from FPL's 1-5 strength ratings.
    
    Used when the Odds API is unavailable or bypassed via --mock-odds.
    Maps FPL's crude 1-5 strength metric (FDR) into attacking and defensive
    multipliers to compute independent Poisson lambdas.
    """
    # Map FPL 1-5 scale to attacking/defending multipliers
    # 2=weak, 3=average, 4=strong, 5=elite
    atk_mult = {1: 0.60, 2: 0.75, 3: 1.00, 4: 1.25, 5: 1.50}
    def_mult = {1: 1.40, 2: 1.25, 3: 1.00, 4: 0.80, 5: 0.65}
    
    # Base Premier League goal expectations
    base_home = 1.55
    base_away = 1.25
    
    # Clip strengths just in case FPL returns something weird
    h_str = max(1, min(5, home_strength))
    a_str = max(1, min(5, away_strength))
    
    lh = base_home * atk_mult[h_str] * def_mult[a_str]
    la = base_away * atk_mult[a_str] * def_mult[h_str]
    
    return TeamGoalModel(
        fixture_id=fixture_id,
        home_team_fpl_id=home_team_fpl_id,
        away_team_fpl_id=away_team_fpl_id,
        lambda_home=lh,
        lambda_away=la,
        p_clean_sheet_home=poisson_pmf(0, la),
        p_clean_sheet_away=poisson_pmf(0, lh),
        score_dist=score_matrix(lh, la),
    )


def team_goal_fit_loss(model: TeamGoalModel, market_probs: Iterable[MarketProb]) -> float:
    """Return the fitted sum-of-squared market-probability error."""
    if model.fit_loss:
        return model.fit_loss
    targets, total_line = _build_targets(market_probs)
    return _loss(model.lambda_home, model.lambda_away, targets, total_line)


def model_market_comparisons(
    model: TeamGoalModel, market_probs: Iterable[MarketProb]
) -> tuple[MarketModelComparison, ...]:
    """Pair supported fair market probabilities with their model equivalents."""
    probabilities = list(market_probs)
    _, total_line = _build_targets(probabilities)
    implied = model_probs(model.lambda_home, model.lambda_away, total_line)
    comparisons: list[MarketModelComparison] = []
    for probability in probabilities:
        market, outcome = probability.market.lower(), probability.outcome.lower()
        if market == "h2h" and outcome in {"home", "draw", "away"}:
            model_prob = implied[outcome]
        elif market == "btts" and outcome in {"yes", "no"}:
            model_prob = implied[f"btts_{outcome}"]
        elif market.startswith("totals_") and outcome in {"over", "under"}:
            model_prob = implied[outcome]
        else:
            continue
        comparisons.append(
            MarketModelComparison(
                market=probability.market,
                outcome=probability.outcome,
                market_prob=probability.prob,
                model_prob=model_prob,
                n_books=probability.n_books,
            )
        )
    return tuple(comparisons)


def mapped_fixture_ids_with_odds(
    connection: Any,
    provider_key: str = "propline",
    upcoming_only: bool = False,
    now: datetime | None = None,
) -> list[int]:
    """Return fixture IDs with mapped provider outcome snapshots."""
    query = """
        SELECT DISTINCT mapping.fpl_fixture_id
        FROM odds_event_fixture_mappings AS mapping
        JOIN odds_outcome_snapshots AS snapshot
          ON snapshot.provider_key = mapping.provider_key
         AND snapshot.provider_event_id = mapping.provider_event_id
        JOIN fixtures AS fixture
          ON fixture.fpl_id = mapping.fpl_fixture_id
        WHERE mapping.provider_key = ?
          AND mapping.fpl_fixture_id IS NOT NULL
    """
    params: list[Any] = [provider_key]
    if upcoming_only:
        current_time = now or datetime.now(timezone.utc)
        query += """
            AND fixture.finished = FALSE
            AND fixture.kickoff_time IS NOT NULL
            AND fixture.kickoff_time > ?
        """
        params.append(current_time)
    query += " ORDER BY mapping.fpl_fixture_id"
    rows = connection.execute(query, params).fetchall()
    return [fixture_fpl_id for (fixture_fpl_id,) in rows]


def upcoming_fixture_ids_with_odds(
    connection: Any,
    provider_key: str = "propline",
    now: datetime | None = None,
) -> list[int]:
    """Return future FPL fixtures with at least one mapped provider outcome."""
    return mapped_fixture_ids_with_odds(
        connection, provider_key=provider_key, upcoming_only=True, now=now
    )


def build_and_persist_team_goal_projection(
    connection: Any,
    fixture_fpl_id: int,
    provider_key: str = "propline",
    generated_at: datetime | None = None,
) -> TeamGoalProjection:
    """Fit and persist one live team-goal projection from DuckDB consensus."""
    market_probs = consensus_from_latest_odds(connection, fixture_fpl_id, provider_key)
    if not market_probs:
        raise ValueError(f"no complete match-market consensus for fixture {fixture_fpl_id}")

    fixture = load_fixture(connection, fixture_fpl_id)
    if fixture is None:
        raise ValueError(f"unknown FPL fixture {fixture_fpl_id}")

    model = fit_team_goals(
        str(fixture_fpl_id),
        fixture.team_h_fpl_id,
        fixture.team_a_fpl_id,
        market_probs,
    )
    event_ids, captured_min, captured_max, snapshot_count = latest_odds_snapshot_provenance(
        connection, fixture_fpl_id, provider_key
    )
    gen_at = generated_at or datetime.now(timezone.utc)
    projection = TeamGoalProjection(
        fixture_fpl_id=fixture_fpl_id,
        generated_at=gen_at,
        provider_key=provider_key,
        provider_event_ids=event_ids,
        source_captured_at_min=captured_min or gen_at,
        source_captured_at_max=captured_max or gen_at,
        source_market_snapshot_count=snapshot_count,
        model=model,
        fit_loss=model.fit_loss,
        comparisons=model_market_comparisons(model, market_probs),
    )
    insert_team_goal_projection(connection, projection)
    return projection


def resolve_fixture_team_goals(
    connection: Any,
    fixture: Fixture,
    home_strength: int = 3,
    away_strength: int = 3,
    provider_key: str = "propline",
    home_team_name: str | None = None,
    away_team_name: str | None = None,
) -> tuple[TeamGoalModel, dict[int, float]]:
    """Resolve team goals for a fixture: market-implied from DB if available, FPL fallback otherwise.

    Returns (TeamGoalModel, clean_sheet_prob_dict).
    """
    fid_label = f"{home_team_name or fixture.team_h_fpl_id}_v_{away_team_name or fixture.team_a_fpl_id}"
    m_rec = load_latest_fixture_team_xg(connection, fixture.fpl_id, provider_key=provider_key)
    if m_rec is not None:
        model = TeamGoalModel(
            fixture_id=fid_label,
            home_team_fpl_id=fixture.team_h_fpl_id,
            away_team_fpl_id=fixture.team_a_fpl_id,
            lambda_home=m_rec.lambda_home,
            lambda_away=m_rec.lambda_away,
            p_clean_sheet_home=m_rec.p_clean_sheet_home,
            p_clean_sheet_away=m_rec.p_clean_sheet_away,
            score_dist=score_matrix(m_rec.lambda_home, m_rec.lambda_away),
            fit_loss=m_rec.fit_loss,
            residuals=m_rec.residuals,
            market_provenance=m_rec.market_provenance,
        )
        cs = {fixture.team_h_fpl_id: m_rec.p_clean_sheet_home, fixture.team_a_fpl_id: m_rec.p_clean_sheet_away}
    else:
        model = fit_fpl_team_goals(
            fid_label,
            fixture.team_h_fpl_id,
            fixture.team_a_fpl_id,
            home_strength,
            away_strength,
        )
        cs = {fixture.team_h_fpl_id: model.p_clean_sheet_home, fixture.team_a_fpl_id: model.p_clean_sheet_away}
    return model, cs
