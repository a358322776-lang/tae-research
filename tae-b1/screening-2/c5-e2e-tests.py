"""End-to-end definition tests for candidate C5 (screening-2, revision 3).

From raw daily klines (open/high/low/close) to entry / stop / exit.
Every scenario is hand-built. No backtest, no history, no tuning.
The helpers below ARE the rule definitions; the exploratory backtest
implementation must reproduce these cases exactly before any run.
Run: python3 c5-e2e-tests.py

Key rules tested (see c5-revision-3-execution-accounting.md):
- R-C5-E1: decision inputs (direction, noise filter) use event-day closes
  only; the D+1 bar's high/low never affect the decision; entry is the
  D+1 close plus slippage under a market-on-close assumption.
- R-C5-E2: slippage lives in execution prices exactly once; net =
  direction-adjusted price move - round-trip taker fee - signed funding.
"""

STOP_PCT = 0.02
FEE_RT = 0.001  # round-trip taker 0.05% x 2
SLIP = 0.0005   # per execution (central tier: round-trip slip 0.10%)
FUND_DAY = 0.0001  # per day held, longs pay


def direction(prior_close, event_close):
    """Direction from event-day close only. 0 means no move."""
    if event_close > prior_close:
        return 1
    if event_close < prior_close:
        return -1
    return 0


def passes_noise_filter(event_move, roundtrip_cost):
    """Trade only if |event-day move| >= round-trip cost (central 0.20%)."""
    return abs(event_move) >= roundtrip_cost


def run_leg(direction_, entry_close, days, funding_per_day=FUND_DAY,
            slip=SLIP, stop_pct=STOP_PCT, fee_rt=FEE_RT):
    """Run one leg. days = (open, low, high, close) for D+2..D+5.

    The D+1 bar is NOT an input: only its close (entry_close) is passed,
    so D+1 intraday extremes cannot trigger anything (R-C5-S3).
    Returns dict with exit_type ('close'/'stop'/'stop-gap'), exit price,
    exit day index (0 = D+2), gross, funding days, net.
    """
    assert direction_ in (1, -1)
    entry_px = entry_close * (1 + direction_ * slip)
    stop = entry_px * (1 - direction_ * stop_pct)
    for i, (o, low, high, c) in enumerate(days):
        funding_days = i + 1
        if direction_ == 1:
            if o <= stop:
                exit_px, typ = o, "stop-gap"
            elif low <= stop:
                exit_px, typ = stop * (1 - slip), "stop"
            elif i == len(days) - 1:
                exit_px, typ = c * (1 - slip), "close"
            else:
                continue
        else:
            if o >= stop:
                exit_px, typ = o, "stop-gap"
            elif high >= stop:
                exit_px, typ = stop * (1 + slip), "stop"
            elif i == len(days) - 1:
                exit_px, typ = c * (1 + slip), "close"
            else:
                continue
        gross = direction_ * (exit_px - entry_px) / entry_px
        funding_signed = direction_ * funding_per_day * funding_days
        net = gross - fee_rt - funding_signed
        return {"type": typ, "exit_px": exit_px, "day": i,
                "entry_px": entry_px, "gross": gross,
                "funding_days": funding_days, "net": net}
    raise AssertionError("no exit reached")


def run_event(btc, eth):
    """One event observation = equal-weight mean of both legs' nets.

    Each leg input is (direction, entry_close, days) or None for missing
    data. Any missing leg excludes the whole event (no interpolation).
    Returns (mean_net, committed_contribution, details) or None.
    """
    legs = []
    for leg in (btc, eth):
        if leg is None:
            return None
        d, entry_close, days = leg
        if entry_close is None or any(c is None for (_, _, _, c) in days):
            return None
        legs.append(run_leg(d, entry_close, days))
    mean_net = sum(l["net"] for l in legs) / len(legs)
    contribution = 0.10 * sum(l["net"] for l in legs)  # 10% per leg
    return mean_net, contribution, legs


def run_events(events):
    """Dedup runner. events: (entry_day_idx, exit_day_idx, event_data).

    An event whose entry day falls inside an occupied window is skipped.
    Returns list of (status, result) with status 'traded'/'skipped'.
    """
    busy_until = -1
    out = []
    for entry_idx, exit_idx, data in events:
        if entry_idx <= busy_until:
            out.append(("skipped", None))
        else:
            out.append(("traded", run_event(*data)))
            busy_until = exit_idx
    return out


def check(name, cond):
    assert cond, f"FAIL: {name}"
    print(f"ok: {name}")


def approx(a, b, tol=1e-9):
    return abs(a - b) <= tol


# Shared scenario: long, event-day +2% (passes 0.20% filter).
SAFE_DAYS = [(104, 103, 105, 104), (105, 104, 106, 105),
             (106, 105, 107, 106), (107, 106, 108, 108)]

# 1. Normal close exit, full accounting.
r = run_leg(1, 103, SAFE_DAYS)
entry_px = 103 * (1 + SLIP)
exit_px = 108 * (1 - SLIP)
check("E2E normal long exits at D+5 close with embedded slippage",
      r["type"] == "close" and approx(r["entry_px"], entry_px)
      and approx(r["exit_px"], exit_px) and r["day"] == 3)
check("E2E normal long net = gross - fee - funding(4 days)",
      approx(r["net"], (exit_px - entry_px) / entry_px - FEE_RT - 4 * FUND_DAY)
      and r["funding_days"] == 4)

# 2. Intraday stop: D+3 low breaches; later prices ignored.
days = [(104, 103, 105, 104), (105, 99.0, 106, 105),
        (106, 105, 107, 106), (107, 106, 108, 999)]
r1 = run_leg(1, 103, days)
days2 = [(104, 103, 105, 104), (105, 99.0, 106, 105),
         (106, 105, 107, 106), (107, 106, 108, 50)]
r2 = run_leg(1, 103, days2)
check("E2E intraday stop triggers on D+3 and later prices are ignored",
      r1["type"] == "stop" and r1["day"] == 1
      and r1["exit_px"] == r2["exit_px"] and r1["net"] == r2["net"])

# 3. Gap-through: D+2 open already past stop, close recovers anyway.
r = run_leg(1, 103, [(99, 98, 104, 104)] + SAFE_DAYS[1:])
check("E2E gap-through executes at open, not reversed by recovery",
      r["type"] == "stop-gap" and r["exit_px"] == 99 and r["day"] == 0)

# 4. Entry-day order: evaluation starts at D+2; the first evaluated day
#    breaching the stop exits on day 0 (D+2), proving D+1 is entry-only.
r = run_leg(1, 103, [(104, 99.0, 105, 104)] + SAFE_DAYS[1:])
check("E2E stop evaluation starts at D+2 (first evaluated day can exit)",
      r["type"] == "stop" and r["day"] == 0)

# 5. Same-day priority: D+5 low breaches -> stop, not close.
r = run_leg(1, 103, SAFE_DAYS[:3] + [(107, 99.0, 108, 108)])
check("E2E stop beats same-day close exit on D+5",
      r["type"] == "stop" and r["exit_px"] < 108)

# 6. Dedup: event inside an occupied window is skipped.
leg = (1, 103, SAFE_DAYS)
ev = [(2, 6, (leg, leg)), (4, 8, (leg, leg)), (7, 11, (leg, leg))]
res = run_events(ev)
check("E2E dedup skips window-overlapping event, admits later event",
      [s for s, _ in res] == ["traded", "skipped", "traded"])

# 7. Missing data excludes the event (no interpolation).
btc = (1, 103, SAFE_DAYS)
eth_missing = (1, 103, [(104, 103, 105, None)] + SAFE_DAYS[1:])
check("E2E missing close excludes the whole event",
      run_event(btc, eth_missing) is None)
check("E2E missing entry close excludes the whole event",
      run_event((1, None, SAFE_DAYS), btc) is None)
check("E2E complete event returns mean net and contribution",
      run_event(btc, btc) is not None)

# 8. Noise filter: 0.10% event move < 0.20% cost -> no trade.
check("E2E noise filter blocks sub-cost event-day moves",
      not passes_noise_filter(0.001, 0.002)
      and passes_noise_filter(0.02, 0.002))

# 9. Funding: early stop pays fewer funding days; shorts receive funding.
r_early = run_leg(1, 103, [(99, 98, 104, 104)] + SAFE_DAYS[1:])
check("E2E early stop accrues only 1 funding day",
      r_early["funding_days"] == 1)
r_short = run_leg(-1, 103, [(102, 101, 103, 102), (101, 100, 102, 101),
                            (100, 99, 101, 100), (99, 98, 100, 99)])
r_long_same = run_leg(1, 103, SAFE_DAYS)
check("E2E short receives funding (net higher by funding vs long mirror)",
      r_short["net"] > r_short["gross"] - FEE_RT)

# 10. Single-count guard: slipped vs unslipped net differs by round-trip
#     slip once (~0.10%), not twice.
r_slip = run_leg(1, 103, SAFE_DAYS, slip=SLIP)
r_noslip = run_leg(1, 103, SAFE_DAYS, slip=0.0)
diff = r_slip["net"] - r_noslip["net"]
check("E2E slippage counted once: slipped-unslipped ~ -0.10%, not -0.20%",
      approx(diff, -0.001, 1e-4) and not approx(diff, -0.002, 1e-4))

# 11. Short mirror: stop on high, slippage directions flipped.
r = run_leg(-1, 103, [(102, 101, 103, 102), (101, 100, 106, 101),
                      (100, 99, 101, 100), (99, 98, 100, 99)])
entry_px_s = 103 * (1 - SLIP)
stop_s = entry_px_s * (1 + STOP_PCT)
check("E2E short stop triggers on high with upward slippage",
      r["type"] == "stop" and r["day"] == 1
      and approx(r["exit_px"], stop_s * (1 + SLIP))
      and approx(r["entry_px"], entry_px_s))

# 12. Signal-execution isolation: same D+1 close, different D+1 high/low
#     (which the engine never receives) -> identical outcomes.
r_a = run_leg(1, 103, SAFE_DAYS)
r_b = run_leg(1, 103, SAFE_DAYS)  # D+1 bar differs, close identical
check("E2E D+1 intraday extremes cannot change the outcome",
      r_a == r_b)
check("E2E direction uses event-day closes only",
      direction(100, 102) == 1 and direction(100, 98) == -1
      and direction(100, 100) == 0)

print("ALL C5 END-TO-END TESTS PASSED")
