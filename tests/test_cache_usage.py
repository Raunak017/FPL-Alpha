"""Tests for The Odds API credit tracking in cache.py (headers -> state + warn)."""
import logging

from fpl_alpha import cache
from fpl_alpha.config import ProviderLimits


def _provider() -> ProviderLimits:
    return ProviderLimits(
        name="test-odds",
        base_url="https://example.test",
        min_interval_s=0.0,
        cache_ttl_s=0.0,
        monthly_budget=500,
        low_budget_threshold=50,
    )


def test_records_usage_from_headers(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "RAW", tmp_path)
    # http.client headers are case-insensitive; a plain dict with the exact
    # lowercase keys is enough to exercise the .get() lookups.
    headers = {"x-requests-remaining": "420", "x-requests-used": "80",
               "x-requests-last": "2"}
    cache._record_usage(_provider(), headers)

    usage = cache.read_usage("test-odds")
    assert usage == {"remaining": 420, "used": 80, "last_cost": 2, "monthly_budget": 500}


def test_no_usage_headers_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "RAW", tmp_path)
    cache._record_usage(_provider(), {"content-type": "application/json"})
    assert cache.read_usage("test-odds") is None


def test_warns_when_budget_low(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(cache, "RAW", tmp_path)
    with caplog.at_level(logging.WARNING, logger="fpl_alpha.cache"):
        cache._record_usage(_provider(), {"x-requests-remaining": "12",
                                          "x-requests-used": "488",
                                          "x-requests-last": "4"})
    assert any("12 credit" in r.getMessage() for r in caplog.records)


def test_no_warning_when_budget_healthy(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(cache, "RAW", tmp_path)
    with caplog.at_level(logging.WARNING, logger="fpl_alpha.cache"):
        cache._record_usage(_provider(), {"x-requests-remaining": "300",
                                          "x-requests-used": "200",
                                          "x-requests-last": "1"})
    assert not caplog.records
