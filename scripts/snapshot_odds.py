#!/usr/bin/env python3
"""Capture a timestamped odds snapshot (Plan step 2).

Run this on a SCHEDULE (e.g. Mon/Wed/Fri/deadline-day), never in a loop — the
free-tier object/credit budgets are tiny. Pass the capture time explicitly so
the snapshot is reproducible.

    python scripts/snapshot_odds.py --provider the-odds-api --scope epl-gw3 \
        --captured-at 2026-08-21T17:30:00Z
"""
import argparse

from fpl_alpha.ingestion import odds
from fpl_alpha.snapshots import write_snapshot


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--provider", choices=["the-odds-api", "sportsgameodds"], required=True)
    ap.add_argument("--scope", required=True, help="e.g. epl-gw3")
    ap.add_argument("--captured-at", required=True, help="ISO-8601 capture time")
    ap.add_argument("--force", action="store_true", help="ignore cache TTL")
    args = ap.parse_args()

    if args.provider == "the-odds-api":
        payload = odds.the_odds_api_epl(force=args.force)
    else:
        payload = odds.sportsgameodds_events(force=args.force)

    path = write_snapshot(args.provider, args.scope, args.captured_at, payload)
    print(f"Snapshot written: {path}")


if __name__ == "__main__":
    main()
