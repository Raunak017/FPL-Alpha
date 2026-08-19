"""Official FPL API client (Plan step 1). Public, no key.

Refactored from the original ``fpl_data_probe.py``: every call now goes through
the cache-first gateway, so repeated dev runs read ``data/raw/fpl/`` instead of
hitting the endpoint. Returns raw dicts; normalization into schemas.Player /
schemas.Team lives in :mod:`fpl_alpha.identity`.
"""
from __future__ import annotations

from typing import Any

from ..cache import fetch
from ..config import FPL_API


def bootstrap_static(force: bool = False) -> dict[str, Any]:
    """Players, teams, gameweeks, prices, ownership, xG/xA — the core dump."""
    return fetch(FPL_API, "/bootstrap-static/", key="bootstrap-static", force=force)


def fixtures(force: bool = False) -> list[dict[str, Any]]:
    """All fixtures incl. FDR difficulty and kickoff times."""
    return fetch(FPL_API, "/fixtures/", key="fixtures", force=force)


def element_summary(player_id: int, force: bool = False) -> dict[str, Any]:
    """Per-player history + upcoming fixtures for one element id."""
    return fetch(
        FPL_API,
        f"/element-summary/{player_id}/",
        key=f"element-summary-{player_id}",
        force=force,
    )


def entry(team_id: int | str, force: bool = False) -> dict[str, Any]:
    """A manager's entry (name, rank, value). Public by Team ID."""
    return fetch(FPL_API, f"/entry/{team_id}/", key=f"entry-{team_id}", force=force)


def entry_history(team_id: int | str, force: bool = False) -> dict[str, Any]:
    return fetch(
        FPL_API, f"/entry/{team_id}/history/", key=f"entry-{team_id}-history", force=force
    )


def entry_picks(team_id: int | str, gw: int, force: bool = False) -> dict[str, Any]:
    """A manager's squad for a gameweek. NOTE: only public once the GW locks."""
    return fetch(
        FPL_API,
        f"/entry/{team_id}/event/{gw}/picks/",
        key=f"entry-{team_id}-picks-gw{gw}",
        force=force,
    )
