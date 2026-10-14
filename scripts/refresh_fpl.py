#!/usr/bin/env python3
"""Refresh the cached FPL core data (bootstrap + fixtures).

Cache-first: does nothing over the wire if the cache is still fresh
(see FPL_API.cache_ttl_s). Pass --force to bypass.

    python scripts/refresh_fpl.py
    python scripts/refresh_fpl.py --force
"""
import argparse
from fpl_alpha.ingestion.refresh import refresh_fpl_database


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="ignore cache TTL")
    args = ap.parse_args()

    result = refresh_fpl_database(force=args.force)
    print(
        f"FPL cache refreshed: {result.player_count} players, "
        f"{result.team_count} teams, {result.fixture_count} fixtures."
    )


if __name__ == "__main__":
    main()
