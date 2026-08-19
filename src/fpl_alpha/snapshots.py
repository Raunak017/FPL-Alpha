"""Timestamped snapshot writer + manifest.

Odds are only meaningful with the time they were captured (line movement,
deadline-day drift). This module names snapshots deterministically and appends
to a manifest so a backtest can reconstruct "what the market said at time T".

Snapshots are written to ``data/snapshots/`` and tracked in ``manifest.jsonl``.
Timestamps are always passed in by the caller — never generated here — so runs
stay reproducible.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import SNAPSHOTS

MANIFEST = SNAPSHOTS / "manifest.jsonl"


def snapshot_name(provider: str, scope: str, captured_at: str) -> str:
    """e.g. ('sportsgameodds', 'epl-gw3', '2026-08-21T17:30:00Z') ->
    'sportsgameodds__epl-gw3__2026-08-21T173000Z.json'."""
    stamp = captured_at.replace(":", "").replace("-", "")
    return f"{provider}__{scope}__{stamp}.json"


def write_snapshot(provider: str, scope: str, captured_at: str, payload: Any) -> Path:
    """Persist a snapshot and append a manifest row. ``captured_at`` is an
    ISO-8601 string supplied by the caller (keeps runs reproducible)."""
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    name = snapshot_name(provider, scope, captured_at)
    path = SNAPSHOTS / name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    row = {
        "file": name,
        "provider": provider,
        "scope": scope,
        "captured_at": captured_at,
    }
    with MANIFEST.open("a") as fh:
        fh.write(json.dumps(row) + "\n")
    return path
