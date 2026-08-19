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


def consensus(
    fixture_id: str,
    market: str,
    outcomes: Sequence[str],
    books: Sequence[Sequence[float]],
) -> list[MarketProb]:
    """Combine de-vigged probabilities across multiple books into consensus
    MarketProb records.

    ``books`` is one row of decimal odds per book, each aligned to ``outcomes``.

    TODO(step 3): outlier handling and weighting by book sharpness; for now this
    averages the per-book de-vigged probabilities equally.
    """
    if not books:
        raise ValueError("no books supplied")
    per_book = [devig_proportional(row) for row in books]
    n = len(per_book)
    avg = [sum(book[i] for book in per_book) / n for i in range(len(outcomes))]
    return [
        MarketProb(fixture_id=fixture_id, market=market, outcome=o, prob=p, n_books=n)
        for o, p in zip(outcomes, avg)
    ]
