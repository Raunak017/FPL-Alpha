#!/usr/bin/env python3
"""Compare our market-driven GW1 xPts against FPL's own ``ep_next`` (offline).

Runs the pipeline on cached data — cached odds → team λ → availability-gated
allocation — then computes a **PARTIAL** expected-points figure per player and
lines it up against FPL bootstrap's ``ep_next`` (FPL's expected points for the
next gameweek).

⚠️ This xPts is deliberately PARTIAL — it is *not* the real engine output (the
assembler isn't built yet). It models only:

    xPts_partial = P(start)·appearance
                 + xG·goal_pts + xA·assist_pts        (from our allocator)
                 + P(start)·P(CS)·cleansheet_pts

and is MISSING bonus, defensive-contribution, saves, and the goals-conceded
penalty — plus a real minutes model (``P(start)`` here is a crude proxy:
fitness × last-season start rate). So expect our numbers to sit BELOW ep_next for
defenders/keepers (we omit their biggest components) and to over-rate fit-but-
rotated attackers. Read this as a directional / rank sanity check, not a
precision benchmark.

    PYTHONPATH=src python scripts/compare_ep_next.py
"""
from __future__ import annotations

import json

from fpl_alpha.allocation import allocate_fixture, attack_rates_from_bootstrap
from fpl_alpha.config import RAW
from fpl_alpha.identity import match_odds_name, teams_from_bootstrap
from fpl_alpha.ingestion import odds
from fpl_alpha.markets import consensus
from fpl_alpha.team_xg import fit_team_goals

# --- Minimal FPL scoring constants (partial; lives here, not in the engine) --
POS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
GOAL_PTS = {"GKP": 6, "DEF": 6, "MID": 5, "FWD": 4}
CS_PTS = {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0}
ASSIST_PTS = 3
APPEARANCE_PTS = 2  # assume a starter plays 60'+
_STARTS_FOR_NAILED = 30  # last-season starts treated as "nailed" (crude P(start))


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# --- stdlib correlation helpers ---------------------------------------------
def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    return cov / (sx * sy) if sx > 0 and sy > 0 else float("nan")


def _ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # 1-based average rank for ties
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _spearman(xs: list[float], ys: list[float]) -> float:
    return _pearson(_ranks(xs), _ranks(ys))


def main() -> None:
    boot = json.loads((RAW / "fpl" / "bootstrap-static.json").read_text())
    teams = teams_from_bootstrap(boot)
    rates = attack_rates_from_bootstrap(boot)  # availability-gated

    el = {e["id"]: e for e in boot["elements"]}
    events = json.loads((RAW / "the-odds-api" / "theoddsapi-epl-h2h+totals-uk.json").read_text())
    fixtures = odds.parse_the_odds_api_events(events)

    rows: list[dict] = []
    for fo in fixtures:
        home = match_odds_name(fo.home_team, teams)
        away = match_odds_name(fo.away_team, teams)
        if home is None or away is None:
            continue
        fid = f"{home.short_name}_v_{away.short_name}"
        mps = consensus(fid, "h2h", ["home", "draw", "away"], fo.h2h)
        if fo.totals:
            mps += consensus(fid, f"totals_{fo.totals_line}", ["over", "under"], fo.totals)
        model = fit_team_goals(fid, home.fpl_id, away.fpl_id, mps)
        cs = {home.fpl_id: model.p_clean_sheet_home, away.fpl_id: model.p_clean_sheet_away}

        for r in allocate_fixture(model, rates):
            e = el[r.fpl_id]
            pos = POS.get(e["element_type"], "UNK")
            # Crude P(start): fitness × last-season start rate (capped). Stand-in
            # for the real minutes model (step 7); flagged in the header.
            avail = rates[r.fpl_id].available
            p_start = avail * min(1.0, _f(e.get("starts")) / _STARTS_FOR_NAILED)
            xpts = (
                p_start * APPEARANCE_PTS
                + r.exp_goals * GOAL_PTS.get(pos, 0)
                + r.exp_assists * ASSIST_PTS
                + p_start * cs[r.team_fpl_id] * CS_PTS.get(pos, 0)
            )
            rows.append({
                "name": e["web_name"], "team": home.short_name if r.team_fpl_id == home.fpl_id else away.short_name,
                "pos": pos, "ours": xpts, "ep_next": _f(e.get("ep_next")),
                "xg": r.exp_goals, "xa": r.exp_assists, "p_start": p_start,
            })

    print(__doc__.split("\n\n")[0])
    print(f"\n{len(rows)} players across {sum(1 for _ in fixtures)} GW1 fixtures "
          f"(cached, availability-gated).\n")

    # (a) Top 20 by OUR partial xPts
    print("=" * 74)
    print("TOP 20 BY OUR PARTIAL xPts   (ours | ep_next | Δ)")
    print("=" * 74)
    for r in sorted(rows, key=lambda r: r["ours"], reverse=True)[:20]:
        d = r["ours"] - r["ep_next"]
        print(f"  {r['name']:18} {r['team']:4} {r['pos']:3}  "
              f"{r['ours']:5.2f} | {r['ep_next']:5.2f} | {d:+5.2f}")

    # (b) Top 20 by FPL's ep_next — who FPL rates that we (mis)rank
    print("\n" + "=" * 74)
    print("TOP 20 BY FPL ep_next        (ours | ep_next | Δ)")
    print("=" * 74)
    for r in sorted(rows, key=lambda r: r["ep_next"], reverse=True)[:20]:
        d = r["ours"] - r["ep_next"]
        print(f"  {r['name']:18} {r['team']:4} {r['pos']:3}  "
              f"{r['ours']:5.2f} | {r['ep_next']:5.2f} | {d:+5.2f}")

    # (c) Position breakdown — where we systematically diverge
    print("\n" + "=" * 74)
    print("MEAN BY POSITION (players with ep_next > 0)")
    print("=" * 74)
    for pos in ("GKP", "DEF", "MID", "FWD"):
        sub = [r for r in rows if r["pos"] == pos and r["ep_next"] > 0]
        if sub:
            mo = sum(r["ours"] for r in sub) / len(sub)
            me = sum(r["ep_next"] for r in sub) / len(sub)
            print(f"  {pos}:  ours {mo:4.2f}   ep_next {me:4.2f}   Δ {mo - me:+4.2f}   (n={len(sub)})")

    # (d) Correlation on the players that matter for selection
    print("\n" + "=" * 74)
    print("CORRELATION vs ep_next")
    print("=" * 74)
    for label, sub in (
        ("all slate players", rows),
        ("ep_next >= 3.0 (selection-relevant)", [r for r in rows if r["ep_next"] >= 3.0]),
        ("MID + FWD, ep_next >= 3.0", [r for r in rows if r["pos"] in ("MID", "FWD") and r["ep_next"] >= 3.0]),
    ):
        if len(sub) >= 2:
            o = [r["ours"] for r in sub]
            e_ = [r["ep_next"] for r in sub]
            print(f"  {label:38} n={len(sub):3}  "
                  f"Pearson {_pearson(o, e_):+.2f}  Spearman {_spearman(o, e_):+.2f}")


if __name__ == "__main__":
    main()
