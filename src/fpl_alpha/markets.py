"""No-vig market probabilities (Plan step 3).

De-vig bookmaker odds into fair probabilities and combine across books.
The two low-level helpers below are real (and unit-tested); the higher-level
consensus builder over many books/fixtures is the next task.

Split into a ``markets/`` package (normalization / no_vig / consensus) only if
this file outgrows itself.
"""
from __future__ import annotations

from collections.abc import Sequence

from .schemas import MarketProb


def implied_prob(decimal_odds: float) -> float:
    """Raw implied probability from decimal odds (includes the vig)."""
    if decimal_odds <= 1.0:
        raise ValueError(f"decimal odds must be > 1.0, got {decimal_odds}")
    return 1.0 / decimal_odds


def devig_proportional(decimal_odds: Sequence[float]) -> list[float]:
    """Remove bookmaker margin by normalizing implied probs to sum to 1
    (the standard proportional / 'multiplicative' method). Returns fair probs
    in the same order as the input outcomes."""
    raw = [implied_prob(o) for o in decimal_odds]
    overround = sum(raw)
    if overround <= 0:
        raise ValueError("implied probabilities sum to <= 0")
    return [p / overround for p in raw]


def _robust_center(values: Sequence[float]) -> float:
    """A single outlier-resistant estimate of the center of ``values``.

    One stray book (a mispriced or slow-to-move line) shouldn't drag the
    consensus, so we don't use the plain mean. Sort, drop the single lowest and
    single highest value, and average what's left:
      - n == 1 -> the value itself
      - n == 2 -> their mean (can't tell which of two is the outlier)
      - n == 3 -> the median (both extremes dropped, middle remains)
      - n >= 4 -> mean of the interior (a symmetric trimmed mean)
    This matters most for thin markets (e.g. player props with 2-3 US books).
    """
    s = sorted(values)
    n = len(s)
    if n <= 2:
        return sum(s) / n
    interior = s[1:-1]
    return sum(interior) / len(interior)


def consensus(
    fixture_id: str,
    market: str,
    outcomes: Sequence[str],
    books: Sequence[Sequence[float]],
) -> list[MarketProb]:
    """Combine de-vigged probabilities across multiple books into consensus
    MarketProb records.

    ``books`` is one row of decimal odds per book, each aligned to ``outcomes``.
    Each book is de-vigged on its own, then combined per outcome with an
    outlier-resistant center (:func:`_robust_center`). Because trimming happens
    independently per outcome the centers needn't sum to 1, so we renormalize
    back to a proper distribution.

    TODO(step 3): weight surviving books by sharpness rather than equally.
    """
    if not books:
        raise ValueError("no books supplied")
    per_book = [devig_proportional(row) for row in books]
    n = len(per_book)
    centers = [_robust_center([book[i] for book in per_book]) for i in range(len(outcomes))]
    total = sum(centers)
    if total <= 0:
        raise ValueError("consensus probabilities sum to <= 0")
    probs = [c / total for c in centers]
    return [
        MarketProb(fixture_id=fixture_id, market=market, outcome=o, prob=p, n_books=n)
        for o, p in zip(outcomes, probs)
    ]
