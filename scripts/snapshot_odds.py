#!/usr/bin/env python3
"""Capture a timestamped odds snapshot (Plan step 2).

Run this on a SCHEDULE (e.g. Mon/Wed/Fri/deadline-day), never in a loop — the
free-tier credit budget is tiny (~500/mo; credits = #markets x #regions). Pass
the capture time explicitly so the snapshot is reproducible.

    python scripts/snapshot_odds.py --scope epl-gw3 \
        --captured-at 2026-08-21T17:30:00Z
"""
import argparse

from fpl_alpha.cache import read_usage
from fpl_alpha.ingestion import odds
from fpl_alpha.snapshots import write_snapshot

PROVIDER = "the-odds-api"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scope", required=True, help="e.g. epl-gw3")
    ap.add_argument("--captured-at", required=True, help="ISO-8601 capture time")
    ap.add_argument("--markets", default="h2h,totals", help="the-odds-api markets")
    ap.add_argument("--regions", default="uk",
                    help="the-odds-api regions; cost = #markets x #regions credits")
    ap.add_argument("--force", action="store_true", help="ignore cache TTL")
    args = ap.parse_args()

    cost = len(args.markets.split(",")) * len(args.regions.split(","))
    print(f"{PROVIDER}: {args.markets} x {args.regions} = up to {cost} credit(s)")

    payload = odds.the_odds_api_epl(
        markets=args.markets, regions=args.regions, force=args.force
    )
    path = write_snapshot(PROVIDER, args.scope, args.captured_at, payload)
    print(f"Snapshot written: {path}")

    usage = read_usage(PROVIDER)
    if usage and usage.get("remaining") is not None:
        print(f"Credits: {usage['remaining']} remaining, {usage['used']} used "
              f"(last call cost {usage['last_cost']})")


if __name__ == "__main__":
    main()
