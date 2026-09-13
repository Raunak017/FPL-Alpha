"""No-vig market probabilities (Plan step 3).

De-vig bookmaker odds into fair probabilities and combine across books.
The module builds a robust, equal-weighted consensus from complete bookmaker
snapshots for each fixture-market.

Split into a ``markets/`` package (normalization / no_vig / consensus) only if
this file outgrows itself.
"""
from __future__ import annotations

from collections.abc import Sequence
from math import log
from statistics import median
from typing import Any

from .identity import match_odds_name_strict, normalize_odds_name
from .schemas import MarketProb, Team


def implied_prob(decimal_odds: float) -> float:
    """Raw implied probability from decimal odds (includes the vig)."""
    if decimal_odds <= 1.0:
        raise ValueError(f"decimal odds must be > 1.0, got {decimal_odds}")
    return 1.0 / decimal_odds


def american_to_decimal(american_price: int) -> float:
    """Convert a non-zero American price to decimal odds."""
    if american_price == 0:
        raise ValueError("American price cannot be zero")
    return 1.0 + (
        american_price / 100 if american_price > 0 else 100 / abs(american_price)
    )


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

    Extreme bookmaker prices are removed with a robust median-absolute-
    deviation rule before the remaining books are averaged equally. Weighting
    books by perceived sharpness requires historical calibration evidence, so
    V1 intentionally gives each retained book equal weight.
    """
    if not books:
        raise ValueError("no books supplied")
    per_book = [devig_proportional(row) for row in _exclude_outlier_books(books)]
    n = len(per_book)
    avg = [sum(book[i] for book in per_book) / n for i in range(len(outcomes))]
    return [
        MarketProb(fixture_id=fixture_id, market=market, outcome=o, prob=p, n_books=n)
        for o, p in zip(outcomes, avg)
    ]


def _exclude_outlier_books(books: Sequence[Sequence[float]]) -> list[Sequence[float]]:
    """Remove only material robust-MAD price outliers.

    Fewer than three complete books have no defensible cross-book baseline.
    A rejected book is removed for every outcome in its market.
    """
    if len(books) < 3:
        return list(books)

    fair_books = [devig_proportional(book) for book in books]
    rejected: set[int] = set()
    for outcome_index in range(len(fair_books[0])):
        values = [_logit(book[outcome_index]) for book in fair_books]
        centre = median(values)
        deviations = [abs(value - centre) for value in values]
        mad = median(deviations)
        for book_index, deviation in enumerate(deviations):
            if deviation < 0.15:
                continue
            if mad == 0 or 0.67449 * deviation / mad > 3.5:
                rejected.add(book_index)

    retained = [book for index, book in enumerate(books) if index not in rejected]
    return retained if len(retained) >= 2 else list(books)


def _logit(probability: float) -> float:
    return log(probability / (1.0 - probability))


def consensus_from_latest_odds(
    connection: Any, fixture_fpl_id: int, provider_key: str = "propline"
) -> list[MarketProb]:
    """Build fair match-market probabilities from latest complete book snapshots.

    Prices are de-vigged within each bookmaker and averaged equally. A bookmaker
    contributes only when one captured market has every required outcome; player
    props and team totals are intentionally excluded from this Step 3 bridge.
    """
    rows = connection.execute(
        """
        WITH latest AS (
            SELECT
                s.provider_event_id, s.bookmaker_key, s.market_key, s.market_ordinal,
                max(s.captured_at) AS captured_at
            FROM odds_outcome_snapshots AS s
            JOIN odds_event_fixture_mappings AS m
              ON m.provider_key = s.provider_key
             AND m.provider_event_id = s.provider_event_id
            WHERE s.provider_key = ?
              AND m.fpl_fixture_id = ?
              AND s.market_key IN ('h2h', 'totals', 'both_teams_to_score')
            GROUP BY ALL
        )
        SELECT
            s.provider_event_id, s.bookmaker_key, s.market_key, s.market_ordinal,
            s.market_description, s.market_team, s.outcome_name, s.american_price,
            s.point, f.team_h_fpl_id, f.team_a_fpl_id,
            home.name, home.short_name, home.aliases,
            away.name, away.short_name, away.aliases
        FROM odds_outcome_snapshots AS s
        JOIN latest
          ON latest.provider_event_id = s.provider_event_id
         AND latest.bookmaker_key = s.bookmaker_key
         AND latest.market_key = s.market_key
         AND latest.market_ordinal = s.market_ordinal
         AND latest.captured_at = s.captured_at
        JOIN odds_event_fixture_mappings AS m
          ON m.provider_key = s.provider_key
         AND m.provider_event_id = s.provider_event_id
        JOIN fixtures AS f ON f.fpl_id = m.fpl_fixture_id
        JOIN teams AS home ON home.fpl_id = f.team_h_fpl_id
        JOIN teams AS away ON away.fpl_id = f.team_a_fpl_id
        WHERE s.provider_key = ?
          AND m.fpl_fixture_id = ?
        """,
        [provider_key, fixture_fpl_id, provider_key, fixture_fpl_id],
    ).fetchall()

    books: dict[tuple[str, str], dict[str, list[float]]] = {}
    for row in rows:
        (
            provider_event_id,
            bookmaker_key,
            market_key,
            market_ordinal,
            market_description,
            market_team,
            outcome_name,
            american_price,
            point,
            home_id,
            away_id,
            home_name,
            home_short_name,
            home_aliases,
            away_name,
            away_short_name,
            away_aliases,
        ) = row
        home = Team(home_id, home_name, home_short_name, tuple(home_aliases))
        away = Team(away_id, away_name, away_short_name, tuple(away_aliases))
        normalized = _normalize_match_outcome(
            market_key,
            outcome_name,
            point,
            market_team,
            market_description,
            home,
            away,
        )
        if normalized is None:
            continue
        market, outcome = normalized
        book_key = (market, f"{provider_event_id}:{bookmaker_key}:{market_ordinal}")
        books.setdefault(book_key, {}).setdefault(outcome, []).append(
            american_to_decimal(american_price)
        )

    grouped: dict[str, list[list[float]]] = {}
    for (market, _), outcomes in books.items():
        order = _market_outcome_order(market)
        if order is None or set(outcomes) != set(order) or any(len(outcomes[o]) != 1 for o in order):
            continue
        grouped.setdefault(market, []).append([outcomes[outcome][0] for outcome in order])

    total_markets = [market for market in grouped if market.startswith("totals_")]
    if total_markets:
        primary_total = min(
            total_markets,
            key=lambda market: (abs(float(market.removeprefix("totals_")) - 2.5), -len(grouped[market])),
        )
        grouped = {
            market: book_rows
            for market, book_rows in grouped.items()
            if not market.startswith("totals_") or market == primary_total
        }

    return [
        probability
        for market, book_rows in sorted(grouped.items())
        for probability in consensus(str(fixture_fpl_id), market, _market_outcome_order(market) or (), book_rows)
    ]


def _normalize_match_outcome(
    market_key: str,
    outcome_name: str,
    point: float | None,
    market_team: str | None,
    market_description: str | None,
    home: Team,
    away: Team,
) -> tuple[str, str] | None:
    outcome = normalize_odds_name(outcome_name)
    if market_key == "h2h":
        if outcome == "draw":
            return "h2h", "draw"
        matched = match_odds_name_strict(outcome_name, [home, away])
        if matched is None:
            return None
        return "h2h", "home" if matched[0].fpl_id == home.fpl_id else "away"
    if market_key == "both_teams_to_score" and outcome in {"yes", "no"}:
        return "btts", outcome
    if market_key != "totals" or point is None or not _is_match_total(
        market_team, market_description, home, away
    ):
        return None
    if outcome not in {"over", "under"}:
        return None
    return f"totals_{point:g}", outcome


def _is_match_total(
    market_team: str | None, market_description: str | None, home: Team, away: Team
) -> bool:
    if market_team is not None:
        return False
    description = normalize_odds_name(market_description or "")
    if "team total" in description:
        return False
    return not any(
        normalize_odds_name(name) in description
        for team in (home, away)
        for name in (team.name, team.short_name)
        if normalize_odds_name(name)
    )


def _market_outcome_order(market: str) -> tuple[str, ...] | None:
    if market == "h2h":
        return "home", "draw", "away"
    if market == "btts":
        return "yes", "no"
    if market.startswith("totals_"):
        return "over", "under"
    return None
