"""Data contracts between pipeline stages.

The engine is a linear DAG (ingest -> identity -> markets -> team_xg -> ...).
These typed records are the interface each stage produces and the next consumes,
so the two developers can build adjacent stages against a stable shape rather
than a raw dict. Kept as stdlib dataclasses to stay dependency-light; swap for
pydantic if/when validation is worth the dependency.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


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


# --- Stage 1 (persistence): timestamped FPL state, history, fixtures --------
@dataclass(frozen=True)
class PlayerSnapshot:
    """Time-varying FPL state for one player from bootstrap-static."""

    player_fpl_id: int
    captured_at: datetime
    now_cost: int
    selected_by_percent: float
    status: str
    total_points: int
    points_per_game: float
    form: float
    minutes: int
    starts: int
    goals_scored: int
    assists: int
    clean_sheets: int
    bonus: int
    bps: int
    expected_goals: float
    expected_assists: float
    expected_goal_involvements: float
    expected_goals_conceded: float
    clean_sheets_per_90: float
    defensive_contribution_per_90: float
    expected_goals_per_90: float
    expected_assists_per_90: float
    expected_goal_involvements_per_90: float
    expected_goals_conceded_per_90: float
    goals_conceded_per_90: float
    saves_per_90: float
    starts_per_90: float
    influence: float
    creativity: float
    threat: float
    ict_index: float
    chance_of_playing_next_round: int | None
    chance_of_playing_this_round: int | None
    transfers_in_event: int
    transfers_out_event: int
    transfers_in: int
    transfers_out: int

    @property
    def price_millions(self) -> float:
        """Current FPL price in pounds millions."""
        return self.now_cost / 10

    @property
    def points_per_million(self) -> float | None:
        """Season points divided by current price in pounds millions."""
        return self.total_points / self.price_millions if self.now_cost else None

    @property
    def points_per_90(self) -> float | None:
        """Season points per 90 minutes, when the player has played."""
        return self.total_points * 90 / self.minutes if self.minutes else None


@dataclass(frozen=True)
class PlayerGameweekHistory:
    """One player's completed FPL fixture record from element-summary.history."""

    player_fpl_id: int
    fixture_fpl_id: int
    gameweek: int
    kickoff_time: str | None
    opponent_team_fpl_id: int
    was_home: bool
    team_h_score: int | None
    team_a_score: int | None
    minutes: int
    total_points: int
    goals_scored: int
    assists: int
    clean_sheets: int
    goals_conceded: int
    own_goals: int
    penalties_saved: int
    penalties_missed: int
    yellow_cards: int
    red_cards: int
    saves: int
    bonus: int
    bps: int
    influence: float
    creativity: float
    threat: float
    ict_index: float
    starts: int | None
    expected_goals: float | None
    expected_assists: float | None
    expected_goal_involvements: float | None
    expected_goals_conceded: float | None
    # These gameweek activity fields are unavailable from /event/{gw}/live/.
    # Element-summary backfills populate them when available.
    value: int | None
    transfers_balance: int | None
    selected: int | None
    transfers_in: int | None
    transfers_out: int | None


@dataclass(frozen=True)
class Fixture:
    """Canonical FPL fixture record used by persistence and downstream stages."""

    fpl_id: int
    code: int
    event: int | None
    kickoff_time: str | None
    finished: bool
    finished_provisional: bool
    minutes: int
    provisional_start_time: bool
    started: bool
    team_a_fpl_id: int
    team_a_score: int | None
    team_a_difficulty: int
    team_h_fpl_id: int
    team_h_score: int | None
    team_h_difficulty: int


# --- Stage 2: normalized fixture odds (ingestion -> markets handoff) --------
@dataclass(frozen=True)
class FixtureOdds:
    """One fixture's decimal odds, aligned per book, ready for de-vig/consensus.

    Produced by the odds ingestion parsers (provider-specific JSON in, this
    normalized shape out) and consumed by ``markets.consensus``. Each row in
    ``h2h``/``totals`` is one book's decimal prices in a fixed outcome order:
    ``h2h`` -> [home, draw, away]; ``totals`` -> [over, under] at ``totals_line``.
    """

    source: str            # e.g. "the-odds-api"
    event_id: str
    commence_time: str     # ISO-8601 kickoff (from the feed, not generated)
    home_team: str         # odds-feed name; resolve to FPL id via identity
    away_team: str
    h2h: list[list[float]] = field(default_factory=list)
    totals: list[list[float]] = field(default_factory=list)
    totals_line: float | None = None


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


# --- Stage 5-6: player attacking allocation ---------------------------------
@dataclass(frozen=True)
class PlayerRates:
    """Per-player attacking weights used to split a team's xG across its squad.

    Sourced from FPL bootstrap-static — season totals by default (see
    ``allocation.attack_rates_from_bootstrap``), which fold in playing time
    without needing a separate minutes model.
    """

    fpl_id: int
    team_fpl_id: int
    xg: float          # expected goals   (share prior)
    xa: float          # expected assists (share prior)
    available: float = 1.0  # fitness weight in [0,1] from FPL status/chance-of-playing


@dataclass(frozen=True)
class PlayerFixtureAttack:
    """One player's market-implied attacking expectation for one fixture.

    ``exp_goals`` / ``exp_assists`` are the ``xG`` / ``xA`` terms of the xPts
    formula (see docs/XPTS_FORMULA_STATUS.md); ``*_share`` are the fractions of
    the team total, kept for transparency/debugging.
    """

    fpl_id: int
    fixture_id: str
    team_fpl_id: int
    exp_goals: float
    exp_assists: float
    goal_share: float = 0.0
    assist_share: float = 0.0
