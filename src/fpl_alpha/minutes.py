"""Expected-minutes / start-probability model (Plan step 7).

Turns FPL availability plus last-season volume into a per-fixture expected-minutes
estimate and a start probability. Both use **empirical-Bayes shrinkage** toward a
prior, weighted by how much evidence (minutes played) backs the player:

    estimate = w · own_signal + (1 − w) · prior,   w = minutes / (minutes + k)

so a heavy-history player keeps their own signal, while a thin-history player
(new signing, promoted-club squad member) falls back to the prior instead of a
hard zero. This is what stops one historied player in an otherwise data-less
squad from hoovering up the whole team's allocation (the "Lukić" artifact).

The fitness gate lives here too (`availability_factor`), since availability is a
minutes concern; it is re-exported from :mod:`fpl_alpha.allocation` for callers
that imported it there.

All priors/strengths are league-rough and **tunable** — calibrate against realized
minutes once backtest data exists. Manual overrides (press-conference news,
expected line-ups) are meant to supersede these estimates upstream. Pure stdlib.
"""
from __future__ import annotations

GAMES_PER_SEASON = 38
FULL_MATCH = 90.0

# FPL status codes meaning "not available" when no explicit chance-% is given.
_UNAVAILABLE_STATUS = frozenset({"i", "s", "u", "n"})  # injured/suspended/unavailable/not-in-squad

# Expected-minutes shrinkage.
PRIOR_MINUTES = 45.0   # a fit player of unknown role (~half a match)
K_MINUTES = 500.0      # pseudo-minutes of prior weight (~5-6 matches before own history dominates)

# Start-probability shrinkage (uses minutes as the evidence weight).
PRIOR_START = 0.45


def availability_factor(status: str | None, chance_next: float | int | None) -> float:
    """Fitness weight in [0, 1] from FPL availability signals.

    ``chance_of_playing_next_round`` (0/25/50/75/100) is authoritative when
    present. Otherwise: injured/suspended/unavailable → 0.0; everything else
    (available, or an unlabelled doubt) → 1.0. Gates *fitness* only, not rotation
    — rotation is captured by :func:`expected_minutes` / :func:`start_probability`.
    """
    if chance_next is not None:
        return max(0.0, min(1.0, float(chance_next) / 100.0))
    return 0.0 if status in _UNAVAILABLE_STATUS else 1.0


def expected_minutes(
    minutes_last_season: float,
    availability: float,
    *,
    prior: float = PRIOR_MINUTES,
    k: float = K_MINUTES,
) -> float:
    """Per-fixture expected minutes in [0, 90]: fitness-gated, shrunk to ``prior``.

    A player's own minutes-per-game (last-season minutes / 38, capped at 90) is
    blended with ``prior`` by evidence weight ``minutes / (minutes + k)``, then
    scaled by ``availability``. Zero-history fit players land at
    ``availability · prior`` rather than 0.
    """
    mins = max(0.0, float(minutes_last_season))
    mpg = min(FULL_MATCH, mins / GAMES_PER_SEASON)
    w = mins / (mins + k) if (mins + k) > 0 else 0.0
    est = w * mpg + (1.0 - w) * prior
    return availability * min(FULL_MATCH, est)


def start_probability(
    starts_last_season: float,
    minutes_last_season: float,
    availability: float,
    *,
    prior: float = PRIOR_START,
    k: float = K_MINUTES,
) -> float:
    """Probability of starting in [0, 1]: fitness-gated, shrunk to ``prior``.

    Uses the observed start rate (starts / 38) as the signal and *minutes* as the
    evidence weight — so a high-minute perennial sub (0 starts) correctly shrinks
    toward a low start prob, while a 0-minute new player falls back to ``prior``.
    """
    mins = max(0.0, float(minutes_last_season))
    rate = min(1.0, max(0.0, float(starts_last_season)) / GAMES_PER_SEASON)
    w = mins / (mins + k) if (mins + k) > 0 else 0.0
    est = w * rate + (1.0 - w) * prior
    return availability * min(1.0, est)
