#!/usr/bin/env python3
"""Refresh the cached FPL core data (bootstrap + fixtures).

Cache-first: does nothing over the wire if the cache is still fresh
(see FPL_API.cache_ttl_s). Pass --force to bypass.

    python scripts/refresh_fpl.py
    python scripts/refresh_fpl.py --force
"""
import argparse

from fpl_alpha.ingestion import fpl


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="ignore cache TTL")
    args = ap.parse_args()

    boot = fpl.bootstrap_static(force=args.force)
    fx = fpl.fixtures(force=args.force)
    print(
        f"FPL cache refreshed: {len(boot['elements'])} players, "
        f"{len(boot['teams'])} teams, {len(fx)} fixtures."
    )


if __name__ == "__main__":
    main()
