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

import math
import re
from collections.abc import Iterable

from .schemas import MarketProb, TeamGoalModel

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
    )
