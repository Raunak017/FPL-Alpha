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

Availability gate
-----------------
Before allocating, each player's weight is scaled by an availability factor from
FPL's own injury/suspension signals (``status`` + ``chance_of_playing_next_round``).
An injured player (factor 0) drops out entirely and — because :func:`allocate`
renormalizes over the survivors — *his share flows to the teammates who will
actually play*, rather than vanishing. Doubtful players (e.g. 75%) get a reduced
share. This is the fitness half of the ``P(start)`` term.

Two builders produce the share weights:

- :func:`attack_rates_from_bootstrap` — the simple baseline: raw season-total
  xG/xA scaled by fitness. Fast, but concentrates in thin/promoted squads and
  ignores rotation.
- :func:`attack_weights_from_bootstrap` — the step-7 upgrade: per-90 rates
  **shrunk toward a positional prior** (so zero-history teammates fall back to a
  baseline instead of 0) and scaled by **expected minutes** (so rotation lowers a
  player's share). This is what dissolves the thin-squad concentration artifact.

Remaining limitations (manual overrides are the intended escape hatch)
----------------------------------------------------------------------
- Shrinkage priors and the minutes model are league-rough constants, not yet
  calibrated against realized data (needs a backtest).
- A genuinely key new signing with no FPL history still gets only the positional
  prior until stats accrue or an override is supplied.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .minutes import FULL_MATCH, availability_factor, expected_minutes
from .schemas import PlayerFixtureAttack, PlayerRates, TeamGoalModel

__all__ = [
    "ASSISTED_GOAL_FRACTION",
    "availability_factor",  # re-exported from .minutes for back-compat
    "allocate",
    "allocate_fixture",
    "attack_rates_from_bootstrap",
    "attack_weights_from_bootstrap",
    "shrink_rate",
]

# Share of goals that earn an FPL assist (~3 in 4 league-wide). Tunable; a
# per-team xA/xG ratio would be more precise but noisier for thin/promoted sides.
ASSISTED_GOAL_FRACTION = 0.75

# --- Shrinkage priors (Plan step 7) -----------------------------------------
# Rough league per-90 attacking baselines by position. A player's own per-90 rate
# is shrunk toward these, so thin/zero-history players fall back to a sensible
# positional level instead of 0 (which is what let one historied player dominate
# a promoted squad). Only *relative* weights matter — allocate() renormalizes to
# team λ — so these values steer the shape, not the scale. Tunable.
_POSITION = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
POS_XG90_PRIOR = {"GKP": 0.0, "DEF": 0.03, "MID": 0.08, "FWD": 0.22, "UNK": 0.05}
POS_XA90_PRIOR = {"GKP": 0.0, "DEF": 0.04, "MID": 0.08, "FWD": 0.09, "UNK": 0.05}
K_RATE = 500.0  # pseudo-minutes of prior weight (~5-6 matches before own rate dominates)


def shrink_rate(rate90: float, minutes: float, prior90: float, *, k: float = K_RATE) -> float:
    """Empirical-Bayes shrink a per-90 rate toward ``prior90``, weighted by minutes.

    ``(minutes·rate90 + k·prior90) / (minutes + k)`` — a player with lots of
    minutes keeps their own rate; one with few (or zero) is pulled to the prior.
    """
    denom = minutes + k
    return (minutes * rate90 + k * prior90) / denom if denom > 0 else prior90


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
        # Availability scales the share weight: an injured player (available=0)
        # drops out and allocate() redistributes his share to fit teammates.
        g_weights = {i: r.xg * r.available for i, r in squad.items()}
        a_weights = {i: r.xa * r.available for i, r in squad.items()}
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
    gate_availability: bool = True,
) -> dict[int, PlayerRates]:
    """Extract per-player attacking weights from bootstrap-static ``elements``.

    Defaults to season-total xG/xA (robust to minutes without a minutes model).
    Pass ``goal_key="expected_goals_per_90"`` / ``assist_key="expected_assists_per_90"``
    to weight by rate instead — but note per-90 over-credits low-minute cameos, so
    only do that once an expected-minutes weight is applied on top (step 7).

    ``gate_availability`` (default on) records each player's fitness weight from
    ``status`` + ``chance_of_playing_next_round`` (see :func:`availability_factor`);
    set it False to ignore injuries (e.g. to reproduce the pre-gate behaviour).
    """
    return {
        e["id"]: PlayerRates(
            fpl_id=e["id"],
            team_fpl_id=e["team"],
            xg=_to_float(e.get(goal_key)),
            xa=_to_float(e.get(assist_key)),
            available=(
                availability_factor(e.get("status"), e.get("chance_of_playing_next_round"))
                if gate_availability
                else 1.0
            ),
        )
        for e in bootstrap["elements"]
    }


def attack_weights_from_bootstrap(
    bootstrap: dict[str, Any],
    *,
    gate_availability: bool = True,
) -> dict[int, PlayerRates]:
    """Per-match attacking weights with minutes + shrinkage (Plan steps 5-7).

    The upgrade over :func:`attack_rates_from_bootstrap` (which uses raw season
    totals): each player's weight is a **per-match expected contribution**

        weight = shrink_rate(xg_per_90 → positional prior) · expected_minutes / 90

    which fixes two things at once:

    - **Thin-squad concentration.** A zero-history teammate no longer weighs 0 —
      :func:`shrink_rate` pulls them to a positional baseline — so one historied
      player can't absorb the whole team λ (the "Lukić" artifact).
    - **Rotation.** Expected minutes scale the weight, so a fit-but-rotated player
      contributes less than a nailed starter of the same rate.

    Availability is folded into ``expected_minutes``, so the returned
    ``PlayerRates.available`` is 1.0 (already applied). The result plugs straight
    into :func:`allocate_fixture`.
    """
    out: dict[int, PlayerRates] = {}
    for e in bootstrap["elements"]:
        pos = _POSITION.get(e.get("element_type"), "UNK")
        mins = _to_float(e.get("minutes"))
        avail = (
            availability_factor(e.get("status"), e.get("chance_of_playing_next_round"))
            if gate_availability
            else 1.0
        )
        emin = expected_minutes(mins, avail)
        play_frac = emin / FULL_MATCH
        wx = shrink_rate(_to_float(e.get("expected_goals_per_90")), mins, POS_XG90_PRIOR[pos]) * play_frac
        wa = shrink_rate(_to_float(e.get("expected_assists_per_90")), mins, POS_XA90_PRIOR[pos]) * play_frac
        out[e["id"]] = PlayerRates(
            fpl_id=e["id"], team_fpl_id=e["team"], xg=wx, xa=wa, available=1.0
        )
    return out
