"""Data contracts between pipeline stages.

The engine is a linear DAG (ingest -> identity -> markets -> team_xg -> ...).
These typed records are the interface each stage produces and the next consumes,
so the two developers can build adjacent stages against a stable shape rather
than a raw dict. Kept as stdlib dataclasses to stay dependency-light; swap for
pydantic if/when validation is worth the dependency.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# --- Stage 1: identity ------------------------------------------------------
@dataclass(frozen=True)
class Team:
    fpl_id: int
    name: str          # canonical (FPL) name
    short_name: str
    aliases: tuple[str, ...] = ()  # names seen in odds feeds, for matching


@dataclass(frozen=True)
class Player:
    fpl_id: int
    web_name: str
    full_name: str
    team_fpl_id: int
    position: str      # GKP / DEF / MID / FWD
    now_cost: int      # tenths of a million (FPL convention)
    aliases: tuple[str, ...] = ()


# --- Stage 3: no-vig market probabilities -----------------------------------
@dataclass(frozen=True)
class MarketProb:
    """A single fair (de-vigged, consensus) probability for one outcome."""

    fixture_id: str
    market: str        # e.g. "h2h", "totals_over_2.5", "btts", "anytime_goal"
    outcome: str       # e.g. "home", "over", "yes", "<player>"
    prob: float        # 0..1, margin-removed
    n_books: int = 1


# --- Stage 4: market-implied team goals -------------------------------------
@dataclass(frozen=True)
class TeamGoalModel:
    """Poisson goal expectations for one fixture, derived from match markets."""

    fixture_id: str
    home_team_fpl_id: int
    away_team_fpl_id: int
    lambda_home: float          # expected goals, home
    lambda_away: float          # expected goals, away
    p_clean_sheet_home: float
    p_clean_sheet_away: float
    score_dist: dict[str, float] = field(default_factory=dict)  # "h-a" -> prob
