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
from typing import Any


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
class PlayerConsistency:
    """Match selection and appearance regularity across past gameweeks."""

    player_fpl_id: int
    matches_played: int
    matches_started: int
    total_minutes: int
    games_played: float

    @property
    def appearance_consistency(self) -> float:
        """Fraction of team gameweeks where the player actually appeared on the pitch."""
        return min(1.0, max(0.0, self.matches_played / self.games_played)) if self.games_played > 0 else 0.0

    @property
    def start_consistency(self) -> float:
        """Fraction of team gameweeks where the player was in the starting XI."""
        return min(1.0, max(0.0, self.matches_started / self.games_played)) if self.games_played > 0 else 0.0

    @property
    def mins_per_appearance(self) -> float:
        """Average minutes played per match in which the player was featured."""
        return self.total_minutes / self.matches_played if self.matches_played > 0 else 0.0


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
    fit_loss: float = 0.0
    residuals: dict[str, float] = field(default_factory=dict)
    market_provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FixtureTeamXG:
    """Fitted Poisson team goal parameters and clean sheet probabilities for a fixture,
    persisted in DuckDB with market provenance and fit residuals.
    """

    fixture_fpl_id: int
    provider_key: str
    captured_at: datetime
    lambda_home: float
    lambda_away: float
    p_clean_sheet_home: float
    p_clean_sheet_away: float
    fit_loss: float
    residuals: dict[str, float] = field(default_factory=dict)
    market_provenance: dict[str, Any] = field(default_factory=dict)


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


# --- Step 8: persisted projection records -----------------------------------
@dataclass(frozen=True)
class ProjectionRun:
    """One immutable execution of a projection model for a target gameweek.

    ``input_fingerprint`` identifies the complete model-and-input state.  A
    repeated execution with the same fingerprint is a no-op; changed inputs or
    model code/configuration create a new run so forecasts remain backtestable.
    Timestamps are supplied by the caller to keep runs reproducible.
    """

    run_id: str
    gameweek: int
    model_name: str
    model_version: str
    scoring_rules_version: str
    input_fingerprint: str
    as_of: datetime
    created_at: datetime
    is_partial: bool = False
    notes: str | None = None


@dataclass(frozen=True)
class PlayerFixtureProjection:
    """One player's forecast for one FPL fixture in a projection run.

    Component fields are nullable because the initial partial xPts model does
    not yet estimate every FPL scoring component.  ``expected_points`` is the
    total for this fixture, not a gameweek aggregate; doubles are represented by
    two records and summed by the gameweek view.
    """

    run_id: str
    gameweek: int
    player_fpl_id: int
    fixture_fpl_id: int
    expected_points: float
    expected_goals: float | None = None
    expected_assists: float | None = None
    p_start: float | None = None
    p_60_plus: float | None = None
    p_clean_sheet: float | None = None
    appearance_points: float | None = None
    goal_points: float | None = None
    assist_points: float | None = None
    clean_sheet_points: float | None = None
    save_points: float | None = None
    defensive_contribution_points: float | None = None
    bonus_points: float | None = None
    goals_conceded_points: float | None = None
    card_points: float | None = None
# --- Stage 2: provider odds -------------------------------------------------
@dataclass(frozen=True)
class OddsProviderEvent:
    provider_key: str
    provider_event_id: str
    sport_key: str
    home_team: str
    away_team: str
    commence_time: str


@dataclass(frozen=True)
class OddsEventFixtureMapping:
    provider_key: str
    provider_event_id: str
    fpl_fixture_id: int | None
    match_method: str


@dataclass(frozen=True)
class OddsPlayerMapping:
    provider_key: str
    provider_event_id: str
    selection_description: str
    fpl_player_id: int | None
    match_method: str


@dataclass(frozen=True)
class OddsBookmaker:
    provider_key: str
    bookmaker_key: str
    title: str


@dataclass(frozen=True)
class OddsOutcomeSnapshot:
    provider_key: str
    provider_event_id: str
    bookmaker_key: str
    market_key: str
    market_ordinal: int
    market_description: str | None
    market_team: str | None
    outcome_ordinal: int
    selection_description: str | None
    fpl_player_id: int | None
    outcome_name: str
    american_price: int
    point: float | None
    last_update: str | None
    last_change_at: str | None
    captured_at: datetime
    run_id: str | None = None


@dataclass(frozen=True)
class OddsIngestionRun:
    """Audit and status record for an atomic odds ingestion run."""

    run_id: str
    provider_key: str
    provider_event_ids: tuple[str, ...]
    input_fingerprint: str | None
    status: str
    failure_stage: str | None
    error_message: str | None
    records_fetched: int
    records_parsed: int
    records_inserted: int
    records_updated: int
    records_rejected: int
    started_at: datetime
    finished_at: datetime | None
    duration_ms: float | None
    retry_of_run_id: str | None = None
    is_retry: bool = False


# --- Market-vs-model comparison ---------------------------------------------
@dataclass(frozen=True)
class MarketModelComparison:
    """One market consensus probability alongside the fitted model value."""

    market: str
    outcome: str
    market_prob: float
    model_prob: float
    n_books: int


@dataclass(frozen=True)
class TeamGoalProjection:
    """A persisted live team-goal fit and the consensus snapshot it used."""

    fixture_fpl_id: int
    generated_at: datetime
    provider_key: str
    provider_event_ids: tuple[str, ...]
    source_captured_at_min: datetime
    source_captured_at_max: datetime
    source_market_snapshot_count: int
    model: TeamGoalModel
    fit_loss: float
    comparisons: tuple[MarketModelComparison, ...]

    def to_fixture_team_xg(self) -> FixtureTeamXG:
        return FixtureTeamXG(
            fixture_fpl_id=self.fixture_fpl_id,
            provider_key=self.provider_key,
            captured_at=self.source_captured_at_max,
            lambda_home=self.model.lambda_home,
            lambda_away=self.model.lambda_away,
            p_clean_sheet_home=self.model.p_clean_sheet_home,
            p_clean_sheet_away=self.model.p_clean_sheet_away,
            fit_loss=self.fit_loss,
            residuals=self.model.residuals,
            market_provenance=self.model.market_provenance,
        )
