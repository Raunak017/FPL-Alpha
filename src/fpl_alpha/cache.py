"""Cache-first HTTP gateway — the single choke point for every external call.

Rules (from CLAUDE.md): never poll in a loop, always cache, respect per-provider
throttles. All ingestion routes through :func:`fetch` so no code path can
accidentally blow a free-tier budget.

The Odds API additionally reports its own usage budget on every live response
(``x-requests-remaining`` / ``-used`` / ``-last``). :func:`fetch` records those
authoritative counts to ``data/raw/<provider>/_usage.json`` and logs a warning
when the remaining credits dip below ``ProviderLimits.low_budget_threshold`` —
so the credit budget is tracked from the source of truth, not a counter we keep.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .config import RAW, USER_AGENT, ProviderLimits

log = logging.getLogger(__name__)

# Tracks the last live call per provider to enforce min_interval_s within a run.
_last_call: dict[str, float] = {}

# The Odds API usage headers (case-insensitive lookup via http.client.HTTPMessage).
_USAGE_HEADERS = {
    "remaining": "x-requests-remaining",  # credits left until the quota resets
    "used": "x-requests-used",            # credits spent since the last reset
    "last_cost": "x-requests-last",       # cost of the request that just returned
}


def _cache_path(provider: str, key: str) -> Path:
    safe = key.replace("/", "_").replace("?", "_").replace("&", "_").strip("_")
    return RAW / provider / f"{safe}.json"


def _usage_path(provider: str) -> Path:
    return RAW / provider / "_usage.json"


def _fresh(path: Path, ttl_s: float) -> bool:
    return path.exists() and (time.time() - path.stat().st_mtime) < ttl_s


def read_usage(provider_name: str) -> dict[str, Any] | None:
    """Last-known usage snapshot for a provider, or None if never recorded.

    Reflects the most recent live call's ``x-requests-*`` headers (see
    :func:`fetch`). The file's mtime records when it was captured.
    """
    path = _usage_path(provider_name)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _record_usage(provider: ProviderLimits, headers: Any) -> None:
    """Persist the provider's self-reported usage and warn if the budget is low.

    No-op for providers that don't send usage headers (e.g. the FPL API).
    """
    raw = {field: headers.get(name) for field, name in _USAGE_HEADERS.items()}
    if all(v is None for v in raw.values()):
        return

    def _as_int(v: Any) -> int | None:
        try:
            return int(float(v)) if v is not None else None
        except (TypeError, ValueError):
            return None

    usage = {k: _as_int(v) for k, v in raw.items()}
    usage["monthly_budget"] = provider.monthly_budget
    path = _usage_path(provider.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(usage, indent=2))

    remaining = usage["remaining"]
    threshold = provider.low_budget_threshold
    if remaining is not None and threshold is not None and remaining < threshold:
        log.warning(
            "%s: only %s credit(s) left this period (last call cost %s). "
            "Snapshot sparingly — you are within %d of the monthly budget.",
            provider.name, remaining, usage["last_cost"], threshold,
        )


def fetch(
    provider: ProviderLimits,
    path: str,
    *,
    key: str | None = None,
    headers: dict[str, str] | None = None,
    force: bool = False,
    timeout: int = 30,
) -> Any:
    """Return JSON for ``provider.base_url + path``, cache-first.

    Serves a cached copy younger than ``provider.cache_ttl_s`` unless ``force``.
    On a live call, sleeps to honor ``provider.min_interval_s`` first, then
    records any usage headers and writes the response to
    ``data/raw/<provider>/`` before returning it.
    """
    key = key or path
    cache_file = _cache_path(provider.name, key)

    if not force and _fresh(cache_file, provider.cache_ttl_s):
        return json.loads(cache_file.read_text())

    # Throttle: respect the minimum interval between live calls per provider.
    elapsed = time.time() - _last_call.get(provider.name, 0.0)
    if elapsed < provider.min_interval_s:
        time.sleep(provider.min_interval_s - elapsed)

    url = provider.base_url + path
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read())
            _record_usage(provider, r.headers)
    finally:
        _last_call[provider.name] = time.time()

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(body, indent=2, ensure_ascii=False))
    return body
