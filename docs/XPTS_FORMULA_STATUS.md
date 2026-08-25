# xPts Formula — Status & Build Plan

Companion to [`PROJECT_PLAN.md`](PROJECT_PLAN.md). That doc tracks the pipeline
stages (1–12); this one drills into the **player expected-points formula** we're
actually trying to compute, maps each term to code that exists today, and names
the single structural gap that blocks the rest.

*Status as of 2026-08-23. Legend: ✅ done · 🟡 partial · ⬜ not started.*

## The target formula

$$\text{xPts} = P(\text{start}) \times \Big[\, P(\text{CS})\cdot \text{CS}_{pts} \;+\; xG\cdot g_{pts} \;+\; xA\cdot a_{pts} \;+\; E[\text{bonus}] \;+\; E[\text{defcon}] \,\Big]$$

Every term except `CS`/`bonus`/`defcon` is **per-player, per-fixture, forward-looking**.
That "forward-looking, this-fixture" requirement is the whole game (see
[FPL API vs Market](#fpl-api-vs-market-why-odds-are-not-redundant) below) — it's
why season-average stats alone don't finish the job.

## FPL scoring reference (the point constants)

These are stable game rules; hardcode them (a `scoring.py` constants block), don't
fetch them per-run. Position order is GKP / DEF / MID / FWD.

| Event | GKP | DEF | MID | FWD | Notes |
|-------|-----|-----|-----|-----|-------|
| Goal (`g_pts`) | 6 | 6 | 5 | 4 | |
| Assist (`a_pts`) | 3 | 3 | 3 | 3 | position-independent |
| Clean sheet (`CS_pts`) | 4 | 4 | 1 | 0 | requires 60+ mins played |
| Defensive contribution (`defcon`) | — | 2 | 2 | 2 | DEF: ≥10 CBIT · MID/FWD: ≥12 (CBIT + recoveries); max 2/match |
| Bonus | 1–3 | 1–3 | 1–3 | 1–3 | top-3 BPS in the match |
| Appearance | 1–2 | 1–2 | 1–2 | 1–2 | 1 pt (<60'), 2 pts (60'+) — **omitted by this formula, see below** |

## Term-by-term status

| Term | Status | What exists today | The gap | Plan step |
|------|--------|-------------------|---------|-----------|
| **P(CS)** | 🟡 ~80% | `team_xg.fit_team_goals` → `p_clean_sheet_home/away` from fitted Poisson λ; tested | Attach team CS prob to that team's players | 4 ✅ (team) |
| **CS_pts** | 🟡 trivial | `Player.position` known | Write the position→points table | 8 |
| **xG** (per player) | 🟡 ~80% | `attack_weights_from_bootstrap` → shrunk per-90 rate × expected minutes, split by `allocate_fixture` | Calibrate priors; props as an alt source | 5 |
| **g_pts** | 🟡 trivial | position known | constant table | 8 |
| **xA** (per player) | 🟡 ~80% | same builder splits `λ × ASSISTED_GOAL_FRACTION` by shrunk xA weight | calibrate priors | 6 |
| **a_pts** | 🟡 trivial | — | constant | 8 |
| **E[bonus]** | 🔴 0% | bootstrap has `bps`, `bonus` (season totals) | BPS model — within-match ranking; hardest term | 10 |
| **E[defcon]** | 🔴 0% | bootstrap has `defensive_contribution`, `clearances_blocks_interceptions`, `tackles`, `recoveries` | Threshold model → P(≥ threshold)·2 | 10 |
| **P(start)** (gate) | 🟡 ~70% | `minutes.py`: `availability_factor` (fitness) + `expected_minutes` / `start_probability` with EB shrinkage; expected-minutes wired into allocation weights | Calibrate priors vs realized minutes; manual line-up overrides | 7 |
| **Assembly** (the product) | 🔴 0% | typed contracts (`schemas.py`) ready | No `scoring`/`projections` module ties terms together | 8 |

**Tally:** the team→player bridge and the two attacking terms (`xG`, `xA`) are now
built (`allocation.py`); `P(CS)` is done at team level. Three constant tables are
trivial-but-unwritten. `P(start)`, `E[defcon]`, `E[bonus]` have their raw inputs
cached in bootstrap but no model. The product itself has no home yet.

## The structural blocker: team → player allocation — ✅ built

The formula is **per-player**; the engine's team_xg stage outputs **per-team** (λ,
CS, scorelines). The bridge that splits a team's expected goals/assists across its
players is now `allocation.py` — this was the keystone that unblocks `xG` and `xA`.

Two sources, not mutually exclusive:

1. **Historical shares — ✅ built (`allocation.py`), free, cached.** Distributes
   team λ across a squad in proportion to each player's *season-total*
   `expected_goals` / `expected_assists` (totals, not per-90, so playing time is
   folded in without a minutes model). Assists = `λ × ASSISTED_GOAL_FRACTION` split
   by xA share. Zero API cost; runs end-to-end in
   `scripts/demo_epl_market_to_xg.py`. Tested in `tests/test_allocation.py`.
   *Remaining:* fold in expected minutes (step 7) by switching to per-90 keys × a
   minutes weight; handle new-signing / promoted-club zero-history players.
2. **Player props (later — paid, thin).** Anytime-goalscorer odds → implied
   per-player goal prob directly. More accurate but US-books-only, credit-costly,
   and only ~2–3 books quote each player. Endpoint researched in `ingestion/odds.py`;
   wire alongside step 5. Reuse `markets.consensus` (a yes/no pair de-vigs like a
   2-outcome h2h) and `identity.match_odds_name` for names.

### Availability gate + minutes model (`P(start)`) — ✅ built

`minutes.availability_factor(status, chance_of_playing_next_round)` scales each
player in [0,1]: injured/suspended → 0, doubtful (75%) → 0.75. A zeroed player
drops out and `allocate` renormalizes, so **his share flows to the teammates who'll
actually play** (verified: an injured striker no longer leads his team's threat
list). On top of that, `expected_minutes` / `start_probability` shrink last-season
volume toward a prior (empirical-Bayes, evidence-weighted by minutes), so rotation
lowers a share and thin-history players fall back to a baseline rather than 0.
Refresh the bootstrap cache near the deadline (`refresh_fpl.py --force`) so injury
news is current — the gate is only as fresh as the cache.

### Shrinkage (thin-squad fix) — ✅ built

`attack_weights_from_bootstrap` blends each player's per-90 xG/xA *rate* toward a
**positional prior** (`shrink_rate`, evidence-weighted by minutes) and scales by
expected minutes. Because `allocate` renormalizes, only *relative* weights matter,
so a zero-history teammate going from 0 → positional-prior is what breaks the
one-player monopoly. **Verified:** Ipswich's threat went from `Lukić 0.95xG`
(74% of the team) to their forwards sharing ~0.13xG each.

### Sanity check vs FPL `ep_next` (GW1)

`scripts/compare_ep_next.py` computes a *partial* xPts (appearance + attacking +
clean sheet; **no** bonus/defcon/saves) and lines it up against FPL's own
`ep_next`. After the shrinkage + minutes model:

- **Directionally strong.** Pearson **+0.79** / Spearman **+0.70** across all 592
  players (was +0.61 / +0.67 before shrinkage — the Lukić outlier had been
  wrecking Pearson). Our top-20 is now genuinely elite (B.Fernandes, Haaland,
  Gabriel, Mbeumo, Raya) with tight deltas.
- **Thin-squad artifact resolved.** Lukić's 9.1-vs-1.5 blowout is gone; the
  largest remaining over-rate is ~+2 for attacking fullbacks (we credit
  appearance + CS + a defender's 6-pt goal but not the negative side).
- **Systematic under-count remains** at every position (GKs largest) — the
  still-missing positive terms: **saves**, **defcon**, **bonus**. This maps
  cleanly to what's left to build (steps 8/10), not a bug.

## What this formula omits vs full FPL scoring

Called out so the gaps are deliberate, not forgotten. The current formula is an
**attacking + clean-sheet + bonus + defcon** model gated by start probability. It
does **not** yet include:

- **Appearance points (1–2 pts).** Material for low-return players — a nailed
  defender's *floor* is mostly appearance + defcon, not goals. Consider folding a
  `P(start)·(1 + P(60')·1)` base term into the bracket.
- **Saves** (GKP: 1 pt / 3 saves) — needed for a real GKP model. `saves` is in
  bootstrap.
- **Goals-conceded penalty** (GKP/DEF: −1 per 2 conceded) — derivable from the
  same team λ that gives `P(CS)`; cheap to add once allocation exists.
- **Cards** (−1 / −3) — small EV; `player_to_receive_card` props exist but low value.
- **Penalty miss / own goal** — negligible EV, skip.

## FPL API vs Market — why odds are *not* redundant

The sharp question: *if bootstrap already carries per-player xG/xA/xGC, are odds
useless?* Short answer: **no — they measure different things.**

- **FPL API = backward-looking rates.** `expected_goals`, `expected_assists`, etc.
  are season-to-date (pre-season: *last* season) **cumulative, realized** stats,
  averaged over a mix of opponents. They tell you a player's *quality/rate* — what
  he has done. They carry **no opponent adjustment and no information about the
  specific upcoming fixture**.
- **Market = forward, fixture-specific expectation.** De-vigged 1X2/totals price
  *this exact match* — already baking in opponent strength, home advantage,
  injuries, rotation/lineup news, and motivation, aggregated by money. It yields a
  **forward team λ for the next fixture**, which is precisely the quantity backward
  averages can't give you directly.

They compose cleanly, and that's the intended architecture:

> **FPL rates decide _who_ and _how good_; the market decides _how many, this week, against this opponent_.**

Use each where it's strongest:

| Quantity | Best source | Why |
|----------|-------------|-----|
| Team goals **this fixture** (λ) | **Market** | forward, opponent- & news-adjusted; FPL's own version needs a model |
| Clean-sheet prob **this fixture** | **Market** (via λ) | falls out of the fitted Poisson |
| Player **share** of team goals/assists | **FPL** | per-90 rates are free and dense; props are thin/paid |
| Minutes / start probability | **FPL** (+ manual news) | `status`, `chance_of_playing`, `starts_per_90` |
| DefCon / saves rates | **FPL** | only source; bootstrap has the counting stats |

**Why the market earns its keep — concretely, from our own cache.** Pre-season
(today, 2026-08-23) the FPL API's forward signals are largely **empty or stale**:
`strength_attack_home/away` and `strength_defence_home/away` are **all `0`**,
team `form`/`position`/`points` are unset, and player `form`/`threat`/`value_form`
read `0.0`. The only forward signal FPL offers now is `ep_next` (its own opaque
projection) and last season's cumulative rates. **The betting market, by contrast,
is fully priced for GW1 before a ball is kicked** — it's the *only* source with a
calibrated forward view early in the season and the fastest to move on team news
near a deadline. That's the edge: the market fills exactly the window where FPL's
own numbers are weakest.

**Could we skip odds entirely?** Partly. You *can* build a forward team model from
FPL alone (each team's xG-for rate vs the opponent's xGC rate, × home/away). That's
a legitimate free fallback and worth having. But it (a) is a model *we'd* have to
build and calibrate, (b) reacts slowly — it's a season average, blind to today's
team news, and (c) is near-useless in the first few GWs when those very fields are
zeroed. The market is a well-calibrated, continuously-updated, news-aware forward
prior for the one term that matters most and is hardest to get right. **Keep odds
for team λ and clean sheets; lean on FPL for everything player-level.** Even if we
later trust our own team model, the market stays the benchmark to validate it
against (that's what `snapshots.py` backtests are for).

## Build sequence (next commits)

1. ✅ **`allocation.py`** — historical-shares team→player split of λ and assists,
   from bootstrap season xG/xA. **Unlocks `xG` and `xA`.** *(steps 5–6)*
2. **`scoring.py` constants** — the three position→points tables + a `PlayerXPts`
   schema record. Unblocks every downstream assembly. *(trivial)*
3. **`P(start)` / minutes** — extract `status` + `chance_of_playing` +
   `starts_per_90` into the schema; simple start-prob first, override hook for news.
   Then fold the minutes weight back into `allocation.py`. *(step 7)*
4. **Deterministic `xPts` assembler** — multiply the terms; ship the attacking +
   CS + appearance baseline. *(step 8)*
5. **`E[defcon]`** — P(≥ threshold)·2 from the defensive counting stats. *(step 10)*
6. **`E[bonus]`** — BPS model; hardest, do last. *(step 10)*

Steps 1–4 produce a usable, interpretable xPts baseline entirely from **already-cached
data** — no new API spend. Step 1 is done.
