"""Focused PropLine odds normalization and persistence tests."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from fpl_alpha.ingestion import odds
from fpl_alpha.schemas import Fixture, Player, Team
from fpl_alpha.storage import (
    insert_odds_outcome_snapshots,
    open_database,
    upsert_odds_bookmakers,
    upsert_odds_event_fixture_mappings,
    upsert_odds_player_mappings,
    upsert_odds_provider_events,
)


def _fixture() -> Fixture:
    return Fixture(
        fpl_id=99,
        code=123456,
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


def _liverpool_fixture() -> Fixture:
    return replace(
        _fixture(),
        fpl_id=14,
        team_h_fpl_id=14,
        team_a_fpl_id=18,
    )


def _payload() -> dict:
    return {
        "id": "propline-event-1",
        "sport_key": "soccer_epl",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "commence_time": "2026-08-21T19:00:00Z",
        "bookmakers": [
            {
                "key": "draftkings",
                "title": "DraftKings",
                "markets": [
                    {
                        "key": "h2h",
                        "description": "Match winner",
                        "last_update": "2026-08-20T12:00:00Z",
                        "outcomes": [
                            {"name": "Arsenal", "price": -120},
                            {"name": "Chelsea", "price": 220},
                        ],
                    },
                    {
                        "key": "anytime_goal_scorer",
                        "description": "Anytime goalscorer",
                        "outcomes": [
                            {
                                "name": "Yes",
                                "description": "Bukayo Saka",
                                "price": 145,
                                "last_change_at": "2026-08-20T12:01:00Z",
                            }
                        ],
                    },
                ],
            }
        ],
    }


def _liverpool_payload(selection: str) -> dict:
    payload = _payload()
    payload["home_team"] = "Liverpool Fc"
    payload["away_team"] = "Nottingham Forest"
    payload["bookmakers"][0]["markets"][-1]["outcomes"][0]["description"] = selection
    return payload


def test_propline_odds_client_uses_query_auth_and_selected_markets(monkeypatch):
    calls = []

    def fake_fetch(provider, path, **kwargs):
        calls.append((provider, path, kwargs))
        return {"id": "propline-event-1"}

    monkeypatch.setattr(odds, "PROPLINE_API_KEY", "test-key")
    monkeypatch.setattr(odds, "fetch", fake_fetch)

    assert odds.propline_epl_event_odds("propline-event-1", ("h2h", "totals")) == {
        "id": "propline-event-1"
    }
    _, path, kwargs = calls[0]
    assert path.endswith("?apiKey=test-key&markets=h2h%2Ctotals")
    assert kwargs == {"key": "propline-epl-event-propline-event-1-h2h-totals", "force": False}


def test_normalize_and_append_propline_outcomes(tmp_path):
    captured_at = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
    event, mapping, player_mappings, bookmakers, snapshots = odds.normalize_propline_event_odds(
        _payload(),
        [Team(1, "Arsenal", "ARS"), Team(2, "Chelsea", "CHE")],
        [Player(10, "Saka", "Bukayo Saka", 1, "MID", 100)],
        [_fixture()],
        captured_at,
    )

    assert mapping.fpl_fixture_id == 99
    assert mapping.match_method == "home_away_kickoff_exact"
    assert len(bookmakers) == 1
    assert len(snapshots) == 3
    player_prop = snapshots[-1]
    assert player_prop.selection_description == "Bukayo Saka"
    assert player_prop.fpl_player_id == 10
    assert player_prop.american_price == 145
    assert player_prop.last_change_at == "2026-08-20T12:01:00Z"
    assert player_mappings[-1].fpl_player_id == 10

    connection = open_database(tmp_path / "fpl_alpha.duckdb")
    try:
        upsert_odds_provider_events(connection, [event])
        upsert_odds_event_fixture_mappings(connection, [mapping])
        upsert_odds_player_mappings(connection, player_mappings)
        upsert_odds_bookmakers(connection, bookmakers)
        insert_odds_outcome_snapshots(connection, snapshots)
        insert_odds_outcome_snapshots(
            connection,
            [
                replace(
                    snapshots[0],
                    captured_at=captured_at + timedelta(minutes=10),
                    american_price=-125,
                )
            ],
        )
        stored = connection.execute(
            """
            SELECT count(*), min(american_price), max(american_price)
            FROM odds_outcome_snapshots
            WHERE market_key = 'h2h' AND outcome_name = 'Arsenal'
            """
        ).fetchone()
        mapped = connection.execute(
            "SELECT fpl_fixture_id FROM odds_event_fixture_mappings"
        ).fetchone()[0]
        mapped_player = connection.execute(
            "SELECT fpl_player_id FROM odds_player_mappings"
        ).fetchone()[0]
    finally:
        connection.close()

    assert stored == (2, -125, -120)
    assert mapped == 99
    assert mapped_player == 10


def test_prop_name_outside_the_fixture_stays_unmatched():
    _, _, player_mappings, _, snapshots = odds.normalize_propline_event_odds(
        _payload(),
        [Team(1, "Arsenal", "ARS"), Team(2, "Chelsea", "CHE")],
        [Player(11, "Palmer", "Cole Palmer", 2, "MID", 100)],
        [_fixture()],
        datetime(2026, 8, 20, 12, tzinfo=timezone.utc),
    )

    assert player_mappings[-1].selection_description == "Bukayo Saka"
    assert player_mappings[-1].fpl_player_id is None
    assert player_mappings[-1].match_method == "unmatched"
    assert snapshots[-1].fpl_player_id is None


def test_prop_team_suffix_and_extra_fpl_surname_map_without_fuzzy_matching():
    payload = _payload()
    prop = payload["bookmakers"][0]["markets"][-1]["outcomes"][0]
    prop["description"] = "Bukayo Saka (ARS)"
    _, _, player_mappings, _, snapshots = odds.normalize_propline_event_odds(
        payload,
        [Team(1, "Arsenal", "ARS"), Team(2, "Chelsea", "CHE")],
        [Player(10, "Saka", "Bukayo Saka Rowe", 1, "MID", 100)],
        [_fixture()],
        datetime(2026, 8, 20, 12, tzinfo=timezone.utc),
    )

    assert player_mappings[-1].fpl_player_id == 10
    assert player_mappings[-1].match_method == "full_name_token_subset"
    assert snapshots[-1].fpl_player_id == 10


def test_prop_extra_provider_name_maps_when_only_one_fixture_player_matches():
    payload = _payload()
    prop = payload["bookmakers"][0]["markets"][-1]["outcomes"][0]
    prop["description"] = "Mathis Rayan Cherki"
    _, _, player_mappings, _, snapshots = odds.normalize_propline_event_odds(
        payload,
        [Team(1, "Arsenal", "ARS"), Team(2, "Chelsea", "CHE")],
        [Player(10, "Cherki", "Rayan Cherki", 1, "MID", 100)],
        [_fixture()],
        datetime(2026, 8, 20, 12, tzinfo=timezone.utc),
    )

    assert player_mappings[-1].fpl_player_id == 10
    assert player_mappings[-1].match_method == "full_name_token_subset"
    assert snapshots[-1].fpl_player_id == 10


def test_explicit_calvin_ramsay_alias_is_liverpool_fixture_scoped():
    _, _, player_mappings, _, snapshots = odds.normalize_propline_event_odds(
        _liverpool_payload("Calvin Ramsey (LIV)"),
        [Team(14, "Liverpool", "LIV"), Team(18, "Nott'm Forest", "NFO")],
        [Player(365, "Ramsay", "Calvin Ramsay", 14, "DEF", 45)],
        [_liverpool_fixture()],
        datetime(2026, 8, 20, 12, tzinfo=timezone.utc),
    )

    assert player_mappings[-1].fpl_player_id == 365
    assert player_mappings[-1].match_method == "explicit_alias"
    assert snapshots[-1].fpl_player_id == 365


def test_explicit_calvin_ramsay_alias_does_not_apply_outside_liverpool():
    payload = _payload()
    payload["bookmakers"][0]["markets"][-1]["outcomes"][0]["description"] = "Calvin Ramsey (LIV)"
    _, _, player_mappings, _, snapshots = odds.normalize_propline_event_odds(
        payload,
        [Team(1, "Arsenal", "ARS"), Team(2, "Chelsea", "CHE")],
        [Player(365, "Ramsay", "Calvin Ramsay", 14, "DEF", 45)],
        [_fixture()],
        datetime(2026, 8, 20, 12, tzinfo=timezone.utc),
    )

    assert player_mappings[-1].fpl_player_id is None
    assert player_mappings[-1].match_method == "unmatched"
    assert snapshots[-1].fpl_player_id is None


@pytest.mark.parametrize(
    "selection",
    ["Eric da Silva Moreira (NFO)", "Ryan McAidoo", "Ryan Mcaidoo (MCI)"],
)
def test_absent_explicit_labels_remain_unmatched(selection: str):
    _, _, player_mappings, _, snapshots = odds.normalize_propline_event_odds(
        _liverpool_payload(selection),
        [Team(14, "Liverpool", "LIV"), Team(18, "Nott'm Forest", "NFO")],
        [Player(403, "Savinho", "Sávio Moreira de Oliveira", 15, "MID", 65)],
        [_liverpool_fixture()],
        datetime(2026, 8, 20, 12, tzinfo=timezone.utc),
    )

    assert player_mappings[-1].fpl_player_id is None
    assert player_mappings[-1].match_method == "unmatched"
    assert snapshots[-1].fpl_player_id is None
