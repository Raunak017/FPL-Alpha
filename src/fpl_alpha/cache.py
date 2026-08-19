"""Cache-first HTTP gateway — the single choke point for every external call.

Rules (from CLAUDE.md): never poll in a loop, always cache, respect per-provider
throttles. All ingestion routes through :func:`fetch` so no code path can
accidentally blow a free-tier budget.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .config import RAW, USER_AGENT, ProviderLimits

# Tracks the last live call per provider to enforce min_interval_s within a run.
_last_call: dict[str, float] = {}


def _cache_path(provider: str, key: str) -> Path:
    safe = key.replace("/", "_").replace("?", "_").replace("&", "_").strip("_")
    return RAW / provider / f"{safe}.json"


def _fresh(path: Path, ttl_s: float) -> bool:
    return path.exists() and (time.time() - path.stat().st_mtime) < ttl_s


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
    writes the response to ``data/raw/<provider>/`` before returning it.
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
    finally:
        _last_call[provider.name] = time.time()

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(body, indent=2, ensure_ascii=False))
    return body
