"""Historical-shares player allocation (Plan steps 5-6).

The bridge from team-level market xG (:mod:`fpl_alpha.team_xg`) to per-player
attacking expectations — the ``xG`` and ``xA`` terms of the xPts formula
(see ``docs/XPTS_FORMULA_STATUS.md``).

Baseline model
--------------
The market gives a team's expected goals for a fixture
(``TeamGoalModel.lambda_home`` / ``lambda_away``). We treat that as a budget and
split it across the team's players in proportion to each player's *historical*
attacking output — their season ``expected_goals`` / ``expected_assists`` from
FPL bootstrap-static.

Weighting by season **totals** (not per-90) is deliberate: totals already fold in
how much each player featured, so a nailed starter outweighs a high-rate cameo
*without* a separate minutes model. When the expected-minutes model lands
(Plan step 7), inject it by weighting per-90 rates by expected minutes and passing
those as the stat keys — the share math below is unchanged.

Expected team assists are taken as ``team goals × ASSISTED_GOAL_FRACTION`` (not
every goal earns an FPL assist — roughly three in four do), then split by
``expected_assists`` share. The fraction is a tunable constant; a per-team
xA/xG ratio is a natural later refinement.

Pure stdlib. The share math (:func:`allocate`) is source-agnostic and unit-tested
independently of any bootstrap parsing.

Known baseline limitations (addressed by step 7 + manual overrides)
-------------------------------------------------------------------
- Pre-season, shares come from *last* season, so new signings / promoted-club
  players with no history get ~0 share until this season's stats accrue.
- No minutes/rotation adjustment yet; a rested starter is over-credited.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .schemas import PlayerFixtureAttack, PlayerRates, TeamGoalModel

# Share of goals that earn an FPL assist (~3 in 4 league-wide). Tunable; a
# per-team xA/xG ratio would be more precise but noisier for thin/promoted sides.
ASSISTED_GOAL_FRACTION = 0.75


def allocate(team_total: float, weights: Mapping[int, float]) -> dict[int, float]:
    """Split ``team_total`` across ids in proportion to non-negative ``weights``.

    Returns ``{id: value}`` summing to ``team_total`` (up to float error). If every
    weight is zero — or ``weights`` is empty — there is no basis to allocate, so
    every id gets ``0.0``; callers should read that as "unallocated" rather than
    trust the zeros (mirrors the identity matcher's return-None-on-miss ethos).
    """
    if any(w < 0 for w in weights.values()):
        raise ValueError("weights must be non-negative")
    total_w = sum(weights.values())
    if total_w <= 0:
        return {i: 0.0 for i in weights}
    return {i: team_total * w / total_w for i, w in weights.items()}


def allocate_fixture(
    model: TeamGoalModel,
    rates: Mapping[int, PlayerRates],
    *,
    assisted_fraction: float = ASSISTED_GOAL_FRACTION,
) -> list[PlayerFixtureAttack]:
    """Allocate a fixture's team xG (and derived xA) to individual players.

    ``rates`` maps ``fpl_id -> PlayerRates`` for (at least) the players on both
    sides; each is bucketed by ``team_fpl_id``. Goals are split by
    ``expected_goals`` share of the team's ``lambda``; assists by
    ``expected_assists`` share of a team assist budget (``lambda × assisted_fraction``).
    Goalkeepers and other zero-xG players naturally receive ~0 with no special case.
    """
    out: list[PlayerFixtureAttack] = []
    for team_id, lam in (
        (model.home_team_fpl_id, model.lambda_home),
        (model.away_team_fpl_id, model.lambda_away),
    ):
        squad = {i: r for i, r in rates.items() if r.team_fpl_id == team_id}
        g_weights = {i: r.xg for i, r in squad.items()}
        a_weights = {i: r.xa for i, r in squad.items()}
        goals = allocate(lam, g_weights)
        assists = allocate(lam * assisted_fraction, a_weights)
        g_total = sum(g_weights.values())
        a_total = sum(a_weights.values())
        for i in squad:
            out.append(
                PlayerFixtureAttack(
                    fpl_id=i,
                    fixture_id=model.fixture_id,
                    team_fpl_id=team_id,
                    exp_goals=goals[i],
                    exp_assists=assists[i],
                    goal_share=(g_weights[i] / g_total) if g_total > 0 else 0.0,
                    assist_share=(a_weights[i] / a_total) if a_total > 0 else 0.0,
                )
            )
    return out


def _to_float(v: Any) -> float:
    """Bootstrap reports xG/xA as strings ('0.07'); coerce, treating missing as 0."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def attack_rates_from_bootstrap(
    bootstrap: dict[str, Any],
    *,
    goal_key: str = "expected_goals",
    assist_key: str = "expected_assists",
) -> dict[int, PlayerRates]:
    """Extract per-player attacking weights from bootstrap-static ``elements``.

    Defaults to season-total xG/xA (robust to minutes without a minutes model).
    Pass ``goal_key="expected_goals_per_90"`` / ``assist_key="expected_assists_per_90"``
    to weight by rate instead — but note per-90 over-credits low-minute cameos, so
    only do that once an expected-minutes weight is applied on top (step 7).
    """
    return {
        e["id"]: PlayerRates(
            fpl_id=e["id"],
            team_fpl_id=e["team"],
            xg=_to_float(e.get(goal_key)),
            xa=_to_float(e.get(assist_key)),
        )
        for e in bootstrap["elements"]
    }
