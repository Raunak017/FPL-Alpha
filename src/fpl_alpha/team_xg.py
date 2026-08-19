"""Market-implied team xG (Plan step 4).

Turn match markets (1X2, over/under totals, BTTS) into per-team Poisson goal
rates, then derive clean-sheet probabilities and a score distribution. This is
the bridge from raw market probabilities to player-level modelling.

Status: interface fixed against schemas.TeamGoalModel; the solver that fits
(lambda_home, lambda_away) to the market probs is the core step-4 task.
"""
from __future__ import annotations

from .schemas import MarketProb, TeamGoalModel


def fit_team_goals(
    fixture_id: str,
    home_team_fpl_id: int,
    away_team_fpl_id: int,
    market_probs: list[MarketProb],
) -> TeamGoalModel:
    """Infer (lambda_home, lambda_away) consistent with the fixture's fair
    market probabilities under a (bivariate) Poisson model, then compute
    clean-sheet probs and the score-line distribution.

    TODO(step 4):
      1. Start with independent Poisson; calibrate lambdas to totals + 1X2.
      2. Derive P(clean sheet) and score_dist from the fitted lambdas.
      3. Consider Dixon–Coles low-score correction once the baseline works.
    """
    raise NotImplementedError("team-xG solver not implemented yet")
