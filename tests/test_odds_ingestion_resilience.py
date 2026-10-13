"""Resilience, atomicity, failure-injection, and idempotency tests for odds ingestion."""
from datetime import datetime, timedelta, timezone
import pytest

from fpl_alpha.markets import consensus_from_latest_odds
from fpl_alpha.schemas import (
    Fixture,
    OddsBookmaker,
    OddsEventFixtureMapping,
    OddsOutcomeSnapshot,
    OddsPlayerMapping,
    OddsProviderEvent,
    Team,
)
from fpl_alpha.storage import (
    IngestionValidationError,
    load_odds_ingestion_run,
    open_database,
    store_odds_snapshot_bundle,
    upsert_fixtures,
    upsert_teams,
)


def _setup_fixture(connection):
    upsert_teams(
        connection,
        [
            Team(1, "Arsenal", "ARS"),
            Team(2, "Chelsea", "CHE"),
        ],
    )
    upsert_fixtures(
        connection,
        [
            Fixture(
                fpl_id=99,
                code=1001,
                event=1,
                kickoff_time="2026-08-21T19:00:00Z",
                finished=False,
                finished_provisional=False,
                minutes=0,
                provisional_start_time=False,
                started=False,
                team_a_fpl_id=2,
                team_a_score=None,
                team_a_difficulty=3,
                team_h_fpl_id=1,
                team_h_score=None,
                team_h_difficulty=2,
            )
        ],
    )


def _sample_bundle(captured_at: datetime, count: int = 50, event_id: str = "evt_1"):
    event = OddsProviderEvent("propline", event_id, "soccer_epl", "Arsenal", "Chelsea", "2026-08-21T19:00:00Z")
    mapping = OddsEventFixtureMapping("propline", event_id, 99, "home_away_kickoff_exact")
    bookmaker = OddsBookmaker("propline", "draftkings", "DraftKings")
    player_mapping = OddsPlayerMapping("propline", event_id, "Bukayo Saka", 10, "explicit_alias")

    snapshots = [
        OddsOutcomeSnapshot(
            provider_key="propline",
            provider_event_id=event_id,
            bookmaker_key="draftkings",
            market_key="h2h" if i < 3 else f"prop_{i // 10}",
            market_ordinal=i // 3,
            market_description="Match Winner" if i < 3 else "Player Prop",
            market_team="Arsenal",
            outcome_ordinal=i % 3,
            selection_description=None if i < 3 else f"Player {i}",
            fpl_player_id=10 if i >= 3 else None,
            outcome_name="Arsenal" if i == 0 else ("Draw" if i == 1 else ("Chelsea" if i == 2 else f"Player {i}")),
            american_price=-110 + i,
            point=None,
            last_update=None,
            last_change_at=None,
            captured_at=captured_at,
        )
        for i in range(count)
    ]
    return [event], [mapping], [player_mapping], [bookmaker], snapshots


def test_successful_bundle_ingestion_and_audit_run(tmp_path):
    connection = open_database(tmp_path / "test.duckdb")
    try:
        _setup_fixture(connection)
        now = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
        events, mappings, player_mappings, bookmakers, snapshots = _sample_bundle(now, count=100)

        run = store_odds_snapshot_bundle(
            connection,
            provider_key="propline",
            events=events,
            event_fixture_mappings=mappings,
            player_mappings=player_mappings,
            bookmakers=bookmakers,
            snapshots=snapshots,
        )

        assert run.status == "COMPLETED"
        assert run.records_parsed == 100
        assert run.records_inserted == 100
        assert run.records_updated == 0
        assert run.failure_stage is None
        assert run.duration_ms is not None and run.duration_ms >= 0

        # Verify audit record in DB
        db_run = load_odds_ingestion_run(connection, run.run_id)
        assert db_run is not None
        assert db_run.status == "COMPLETED"
        assert db_run.records_inserted == 100

        # Verify snapshots tagged with run_id
        count_tagged = connection.execute(
            "SELECT count(*) FROM odds_outcome_snapshots WHERE run_id = ?",
            [run.run_id],
        ).fetchone()[0]
        assert count_tagged == 100
    finally:
        connection.close()


def test_idempotent_retry_preserves_timestamps_and_updates_counts(tmp_path):
    connection = open_database(tmp_path / "test.duckdb")
    try:
        _setup_fixture(connection)
        t_capture = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)
        events, mappings, player_mappings, bookmakers, snapshots = _sample_bundle(t_capture, count=60)

        run1 = store_odds_snapshot_bundle(
            connection,
            provider_key="propline",
            events=events,
            event_fixture_mappings=mappings,
            player_mappings=player_mappings,
            bookmakers=bookmakers,
            snapshots=snapshots,
        )
        assert run1.records_inserted == 60
        assert run1.records_updated == 0

        # Run exact same bundle again (idempotent retry)
        run2 = store_odds_snapshot_bundle(
            connection,
            provider_key="propline",
            events=events,
            event_fixture_mappings=mappings,
            player_mappings=player_mappings,
            bookmakers=bookmakers,
            snapshots=snapshots,
        )
        assert run2.status == "COMPLETED"
        assert run2.records_inserted == 0
        assert run2.records_updated == 60

        # Total rows in table must remain exactly 60
        total_rows = connection.execute("SELECT count(*) FROM odds_outcome_snapshots").fetchone()[0]
        assert total_rows == 60

        # Timestamps preserved
        stored_ts = connection.execute(
            "SELECT count(DISTINCT CAST(captured_at AS VARCHAR)) FROM odds_outcome_snapshots"
        ).fetchone()[0]
        assert stored_ts == 1
    finally:
        connection.close()


def test_failure_injection_required_fields_rolls_back_and_records_failure(tmp_path):
    connection = open_database(tmp_path / "test.duckdb")
    try:
        _setup_fixture(connection)
        now = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
        events, mappings, player_mappings, bookmakers, snapshots = _sample_bundle(now, count=10)

        # Inject an invalid snapshot with None in a required field (outcome_name)
        invalid_snapshot = OddsOutcomeSnapshot(
            provider_key="propline",
            provider_event_id="evt_1",
            bookmaker_key="draftkings",
            market_key="h2h",
            market_ordinal=999,
            market_description=None,
            market_team=None,
            outcome_ordinal=0,
            selection_description=None,
            fpl_player_id=None,
            outcome_name=None,  # Invalid NULL!
            american_price=100,
            point=None,
            last_update=None,
            last_change_at=None,
            captured_at=now,
        )
        snapshots.append(invalid_snapshot)

        with pytest.raises(IngestionValidationError, match="NULL in required"):
            store_odds_snapshot_bundle(
                connection,
                provider_key="propline",
                events=events,
                event_fixture_mappings=mappings,
                player_mappings=player_mappings,
                bookmakers=bookmakers,
                snapshots=snapshots,
            )

        # Verify rollback: 0 outcomes and 0 events stored
        assert connection.execute("SELECT count(*) FROM odds_outcome_snapshots").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM odds_provider_events").fetchone()[0] == 0

        # Verify failed run record survived rollback
        runs = connection.execute(
            "SELECT run_id, status, failure_stage, error_message FROM odds_ingestion_runs"
        ).fetchall()
        assert len(runs) == 1
        run_id, status, failure_stage, err = runs[0]
        assert status == "FAILED"
        assert failure_stage == "validation_required_fields"
        assert "NULL in required" in err
    finally:
        connection.close()


def test_failure_injection_duplicate_keys_rolls_back(tmp_path):
    connection = open_database(tmp_path / "test.duckdb")
    try:
        _setup_fixture(connection)
        now = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
        events, mappings, player_mappings, bookmakers, snapshots = _sample_bundle(now, count=5)

        # Duplicate the first snapshot
        snapshots.append(snapshots[0])

        with pytest.raises(IngestionValidationError, match="duplicate primary key"):
            store_odds_snapshot_bundle(
                connection,
                provider_key="propline",
                events=events,
                event_fixture_mappings=mappings,
                player_mappings=player_mappings,
                bookmakers=bookmakers,
                snapshots=snapshots,
            )

        assert connection.execute("SELECT count(*) FROM odds_outcome_snapshots").fetchone()[0] == 0
        db_run = connection.execute(
            "SELECT status, failure_stage FROM odds_ingestion_runs"
        ).fetchone()
        assert db_run == ("FAILED", "validation_duplicate_keys")
    finally:
        connection.close()


def test_recovery_after_failure_succeeds_cleanly(tmp_path):
    connection = open_database(tmp_path / "test.duckdb")
    try:
        _setup_fixture(connection)
        now = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
        events, mappings, player_mappings, bookmakers, snapshots = _sample_bundle(now, count=10)

        # First run fails due to duplicate key
        bad_snapshots = list(snapshots) + [snapshots[0]]
        with pytest.raises(IngestionValidationError):
            store_odds_snapshot_bundle(
                connection,
                provider_key="propline",
                events=events,
                event_fixture_mappings=mappings,
                player_mappings=player_mappings,
                bookmakers=bookmakers,
                snapshots=bad_snapshots,
            )

        # Second run with valid data succeeds cleanly
        run2 = store_odds_snapshot_bundle(
            connection,
            provider_key="propline",
            events=events,
            event_fixture_mappings=mappings,
            player_mappings=player_mappings,
            bookmakers=bookmakers,
            snapshots=snapshots,
        )

        assert run2.status == "COMPLETED"
        assert connection.execute("SELECT count(*) FROM odds_outcome_snapshots").fetchone()[0] == 10

        # Both runs (1 FAILED, 1 COMPLETED) exist in audit table
        run_statuses = connection.execute(
            "SELECT status FROM odds_ingestion_runs ORDER BY started_at"
        ).fetchall()
        assert [r[0] for r in run_statuses] == ["FAILED", "COMPLETED"]
    finally:
        connection.close()


def test_consensus_refuses_incomplete_runs_and_consumes_completed_runs(tmp_path):
    connection = open_database(tmp_path / "test.duckdb")
    try:
        _setup_fixture(connection)
        now = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)

        # Prepare 3 books for h2h
        events = [OddsProviderEvent("propline", "evt_1", "soccer_epl", "Arsenal", "Chelsea", "2026-08-21T19:00:00Z")]
        mappings = [OddsEventFixtureMapping("propline", "evt_1", 99, "home_away_kickoff_exact")]
        bookmakers = [
            OddsBookmaker("propline", "book1", "Book 1"),
            OddsBookmaker("propline", "book2", "Book 2"),
            OddsBookmaker("propline", "book3", "Book 3"),
        ]
        snapshots = []
        for bk in ["book1", "book2", "book3"]:
            snapshots.extend([
                OddsOutcomeSnapshot("propline", "evt_1", bk, "h2h", 0, "Match winner", None, 0, None, None, "Arsenal", -120, None, None, None, now),
                OddsOutcomeSnapshot("propline", "evt_1", bk, "h2h", 0, "Match winner", None, 1, None, None, "Draw", 260, None, None, None, now),
                OddsOutcomeSnapshot("propline", "evt_1", bk, "h2h", 0, "Match winner", None, 2, None, None, "Chelsea", 320, None, None, None, now),
            ])

        # Step A: Ingest with a run marked FAILED
        fake_run_id = "failed_run_123"
        connection.execute(
            """
            INSERT INTO odds_ingestion_runs (
                run_id, provider_key, provider_event_ids, input_fingerprint,
                status, started_at
            ) VALUES (?, 'propline', ['evt_1'], 'fingerprint', 'FAILED', ?)
            """,
            [fake_run_id, now],
        )
        # Directly insert snapshots pointing to the failed run
        connection.execute(
            """
            INSERT INTO odds_provider_events VALUES ('propline', 'evt_1', 'soccer_epl', 'Arsenal', 'Chelsea', ?)
            """,
            [now],
        )
        connection.execute(
            """
            INSERT INTO odds_event_fixture_mappings VALUES ('propline', 'evt_1', 99, 'home_away_kickoff_exact')
            """
        )
        for s in snapshots:
            connection.execute(
                """
                INSERT INTO odds_outcome_snapshots (
                    provider_key, provider_event_id, bookmaker_key, market_key, market_ordinal,
                    market_description, market_team, outcome_ordinal, selection_description,
                    fpl_player_id, outcome_name, american_price, point, last_update,
                    last_change_at, captured_at, run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    s.provider_key, s.provider_event_id, s.bookmaker_key, s.market_key, s.market_ordinal,
                    s.market_description, s.market_team, s.outcome_ordinal, s.selection_description,
                    s.fpl_player_id, s.outcome_name, s.american_price, s.point, s.last_update,
                    s.last_change_at, s.captured_at, fake_run_id,
                ],
            )

        # Consensus MUST return empty because the run is FAILED
        market_probs = consensus_from_latest_odds(connection, fixture_fpl_id=99)
        assert market_probs == []

        # Step B: Mark run as COMPLETED
        connection.execute(
            "UPDATE odds_ingestion_runs SET status = 'COMPLETED' WHERE run_id = ?",
            [fake_run_id],
        )

        # Consensus now successfully reads the completed run
        market_probs = consensus_from_latest_odds(connection, fixture_fpl_id=99)
        assert len(market_probs) == 3
        outcomes = {mp.outcome for mp in market_probs}
        assert outcomes == {"home", "draw", "away"}
    finally:
        connection.close()


def test_historical_snapshot_preservation(tmp_path):
    connection = open_database(tmp_path / "test.duckdb")
    try:
        _setup_fixture(connection)
        t1 = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)

        events1, mappings1, player_mappings1, bookmakers1, snapshots1 = _sample_bundle(t1, count=10)
        run1 = store_odds_snapshot_bundle(
            connection, "propline", events1, mappings1, player_mappings1, bookmakers1, snapshots1
        )

        events2, mappings2, player_mappings2, bookmakers2, snapshots2 = _sample_bundle(t2, count=10)
        run2 = store_odds_snapshot_bundle(
            connection, "propline", events2, mappings2, player_mappings2, bookmakers2, snapshots2
        )

        # Both runs must be COMPLETED
        assert run1.status == "COMPLETED"
        assert run2.status == "COMPLETED"

        # Total snapshots should be 20 (both historical snapshots preserved)
        total_snapshots = connection.execute("SELECT count(*) FROM odds_outcome_snapshots").fetchone()[0]
        assert total_snapshots == 20

        # Two distinct timestamps
        distinct_captured = connection.execute(
            "SELECT count(DISTINCT captured_at) FROM odds_outcome_snapshots"
        ).fetchone()[0]
        assert distinct_captured == 2
    finally:
        connection.close()
