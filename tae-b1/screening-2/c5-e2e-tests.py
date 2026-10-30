"""End-to-end definition tests for candidate C5 (screening-2, revision 4).

From raw daily klines (open/high/low/close) to entry / stop / exit.
Every scenario is hand-built. No backtest, no history, no tuning.
The helpers below ARE the rule definitions; the exploratory backtest
implementation must reproduce these cases exactly before any run.
Run: python3 c5-e2e-tests.py

Timing (v0.4, user-chosen): signal confirmed at the D+1 close, executed
at the D+2 open, exited at the D+5 close. Stop = 2% from the ACTUAL
entry (filled) price. Slippage + spread live in execution prices once;
net = direction-adjusted price move - round-trip taker fee - signed
funding. See c5-revision-4-d2-open-entry.md.

Changelog: v0.4 replaces the v0.3 timing (D+1 close entry, stop from
entry close, gap at flat open). Cases that survive the timing change
are kept; timing-dependent cases are rewritten.
"""

STOP_PCT = 0.02
FEE_RT = 0.001  # round-trip taker 0.05% x 2
SLIP = 0.0005   # per execution, central tier
SPREAD = 0.0003  # per execution half-spread, central tier (assumption)
EXEC = SLIP + SPREAD  # total per-execution adverse cost in price
FUND_DAY = 0.0001  # per day held, longs pay


def direction(prior_close, event_close):
    """Direction from event-day closes only. 0 means no move."""
    if event_close > prior_close:
        return 1
    if event_close < prior_close:
        return -1
    return 0


def passes_noise_filter(event_move, roundtrip_cost):
    """Trade only if |event-day move| >= round-trip cost (central 0.26%)."""
    return abs(event_move) >= roundtrip_cost


def run_leg(direction_, entry_open, days, funding_per_day=FUND_DAY,
            exec_cost=EXEC, stop_pct=STOP_PCT, fee_rt=FEE_RT):
    """Run one leg. days = (open, low, high, close) for D+2..D+5.

    days[0] is the entry day: its open is the entry reference, and its
    low/high are post-entry prices that CAN trigger the stop.
    Later days: gap check first, then intraday, then scheduled close exit.
    Stop level is measured from the ACTUAL filled entry price.
    Funding here is the scalar per-day approximation used only for the
    price-mechanics cases; settlement-matched funding bounds are tested
    separately by funding_bounds (revisions 6-7).
    Returns dict with exit_type ('close'/'stop'/'stop-gap'), exit price,
    exit day index (0 = D+2), gross, funding days, funding, net.
    """
    assert direction_ in (1, -1)
    entry_px = entry_open * (1 + direction_ * exec_cost)
    stop = entry_px * (1 - direction_ * stop_pct)
    exit_px = typ = day = None
    for i, (o, low, high, c) in enumerate(days):
        if i > 0:  # gap check only after the entry day
            if direction_ == 1 and o <= stop:
                exit_px, typ, day = o * (1 - exec_cost), "stop-gap", i
                break
            if direction_ == -1 and o >= stop:
                exit_px, typ, day = o * (1 + exec_cost), "stop-gap", i
                break
        if direction_ == 1 and low <= stop:
            exit_px, typ, day = stop * (1 - exec_cost), "stop", i
            break
        if direction_ == -1 and high >= stop:
            exit_px, typ, day = stop * (1 + exec_cost), "stop", i
            break
        if i == len(days) - 1:
            exit_px, typ, day = c * (1 - direction_ * exec_cost), "close", i
            break
    if exit_px is None:
        raise AssertionError("no exit reached")
    funding_signed = direction_ * funding_per_day * (day + 1)
    return _finish(direction_, entry_px, exit_px, typ, day,
                   day + 1, funding_signed, fee_rt)


def _finish(direction_, entry_px, exit_px, typ, day, funding_days,
            funding_signed, fee_rt):
    gross = direction_ * (exit_px - entry_px) / entry_px
    net = gross - fee_rt - funding_signed
    return {"type": typ, "exit_px": exit_px, "day": day,
            "entry_px": entry_px, "gross": gross,
            "funding_days": funding_days, "funding": funding_signed,
            "net": net}


def validate_leg(entry_open, days):
    """OHLC completeness + validity. Missing or invalid data -> False.

    Missing High/Low must NEVER default to 'not triggered': an
    unobservable stop status excludes the leg. Also requires the D+2
    open to match the entry reference and every bar to be positive with
    High >= max(Open, Close) and Low <= min(Open, Close).
    """
    if entry_open is None or not days or days[0][0] != entry_open:
        return False
    for (o, low, high, c) in days:
        if None in (o, low, high, c):
            return False
        if not (o > 0 and low > 0 and high > 0 and c > 0):
            return False
        if high < low or high < o or high < c or low > o or low > c:
            return False
    return True


def run_event(btc, eth):
    """One event observation = equal-weight mean of both legs' nets.

    Each leg input is (direction, entry_open, days). Any missing or
    invalid leg excludes the whole event (no interpolation, no
    'not triggered' default). Returns (mean_net, committed_contribution,
    details) or None.
    """
    legs = []
    for leg in (btc, eth):
        if leg is None:
            return None
        d, entry_open, days = leg
        if not validate_leg(entry_open, days):
            return None
        legs.append(run_leg(d, entry_open, days))
    mean_net = sum(l["net"] for l in legs) / len(legs)
    contribution = 0.10 * sum(l["net"] for l in legs)  # 10% per leg
    return mean_net, contribution, legs


def run_events(events):
    """Dedup runner. events: (entry_day_idx, exit_day_idx, event_data).

    An event whose entry day (D+2) falls inside an occupied window
    (D+2..D+5) is skipped. Returns list of (status, result).
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


# Shared scenario: long, event-day +2% (passes 0.26% filter).
# days = D+2..D+5 bars; D+2 open 104 is the entry reference.
SAFE_DAYS = [(104, 103, 105, 104), (105, 104, 106, 105),
             (106, 105, 107, 106), (107, 106, 108, 108)]

# 1. Normal close exit at D+5, full accounting.
r = run_leg(1, 104, SAFE_DAYS)
entry_px = 104 * (1 + EXEC)
exit_px = 108 * (1 - EXEC)
check("E2E normal long enters D+2 open, exits D+5 close",
      r["type"] == "close" and approx(r["entry_px"], entry_px)
      and approx(r["exit_px"], exit_px) and r["day"] == 3)
check("E2E normal long net = gross - fee - funding(4 days)",
      approx(r["net"], (exit_px - entry_px) / entry_px - FEE_RT - 4 * FUND_DAY)
      and r["funding_days"] == 4)

# 2. Intraday stop: D+4 low breaches; later prices ignored.
days = [SAFE_DAYS[0], SAFE_DAYS[1], (106, 99.0, 107, 106),
        (107, 106, 108, 999)]
r1 = run_leg(1, 104, days)
days2 = [SAFE_DAYS[0], SAFE_DAYS[1], (106, 99.0, 107, 106),
         (107, 106, 108, 50)]
r2 = run_leg(1, 104, days2)
check("E2E intraday stop triggers on D+4 and later prices are ignored",
      r1["type"] == "stop" and r1["day"] == 2
      and r1["exit_px"] == r2["exit_px"] and r1["net"] == r2["net"])

# 3. Gap-through on D+3: open past stop executes at open WITH one cost.
r = run_leg(1, 104, [SAFE_DAYS[0], (99, 98, 104, 104)] + SAFE_DAYS[2:])
check("E2E gap-through executes at open with one slip+spread charge",
      r["type"] == "stop-gap" and r["day"] == 1
      and approx(r["exit_px"], 99 * (1 - EXEC)))

# 4. NEW in v0.4: the entry day D+2 itself can trigger the stop.
r = run_leg(1, 104, [(104, 99.0, 105, 104)] + SAFE_DAYS[1:])
check("E2E entry-day D+2 intraday move can trigger the stop",
      r["type"] == "stop" and r["day"] == 0)

# 5. Same-day priority: D+5 low breaches -> stop, not close.
r = run_leg(1, 104, SAFE_DAYS[:3] + [(107, 99.0, 108, 108)])
check("E2E stop beats same-day close exit on D+5",
      r["type"] == "stop" and r["exit_px"] < 108)

# 6. Dedup with the new window (D+2..D+5).
leg = (1, 104, SAFE_DAYS)
ev = [(2, 5, (leg, leg)), (3, 6, (leg, leg)), (6, 9, (leg, leg))]
res = run_events(ev)
check("E2E dedup skips window-overlapping event, admits later event",
      [s for s, _ in res] == ["traded", "skipped", "traded"])

# 7. Missing data excludes the event (no interpolation).
check("E2E missing close excludes the whole event",
      run_event((1, 104, [(104, 103, 105, None)] + SAFE_DAYS[1:]),
                (1, 104, SAFE_DAYS)) is None)
check("E2E missing entry open excludes the whole event",
      run_event((1, None, SAFE_DAYS), (1, 104, SAFE_DAYS)) is None)
check("E2E complete event returns mean net and contribution",
      run_event((1, 104, SAFE_DAYS), (1, 104, SAFE_DAYS)) is not None)

# 8. Noise filter with the new central threshold 0.26%.
check("E2E noise filter uses the new 0.26% central round-trip cost",
      not passes_noise_filter(0.0020, 0.0026)
      and passes_noise_filter(0.0030, 0.0026))

# 9. Funding: early stop pays fewer funding days; shorts receive funding.
r_early = run_leg(1, 104, [(104, 99.0, 105, 104)] + SAFE_DAYS[1:])
check("E2E early stop accrues only 1 funding day",
      r_early["funding_days"] == 1)
r_short = run_leg(-1, 104, [(104, 103, 105, 104), (103, 102, 104, 103),
                            (102, 101, 103, 102), (101, 100, 102, 101)])
check("E2E short receives funding (net higher by funding vs gross-fee)",
      r_short["net"] > r_short["gross"] - FEE_RT)

# 10. Single-count guard: with-cost vs zero-cost net differs by round-trip
#     slip+spread once (central 0.10% + 0.06% = 0.16%), not twice.
r_cost = run_leg(1, 104, SAFE_DAYS, exec_cost=EXEC)
r_bare = run_leg(1, 104, SAFE_DAYS, exec_cost=0.0)
diff = r_cost["net"] - r_bare["net"]
check("E2E slip+spread counted once: diff ~ -0.16%, not -0.32%",
      approx(diff, -0.0016, 2e-4) and not approx(diff, -0.0032, 2e-4))

# 11. Short mirror: stop on high, cost directions flipped.
r = run_leg(-1, 104, [(104, 103, 105, 104), (103, 102, 107, 103),
                      (102, 101, 103, 102), (101, 100, 102, 101)])
entry_px_s = 104 * (1 - EXEC)
stop_s = entry_px_s * (1 + STOP_PCT)
check("E2E short stop triggers on high with upward cost adjustment",
      r["type"] == "stop" and r["day"] == 1
      and approx(r["exit_px"], stop_s * (1 + EXEC))
      and approx(r["entry_px"], entry_px_s))

# 12. Signal-execution isolation: D+1 prices never enter the engine.
#     The engine takes only the D+2 open and D+2..D+5 bars; two scenarios
#     differing only in D+1 prices therefore produce identical outcomes.
r_a = run_leg(1, 104, SAFE_DAYS)
r_b = run_leg(1, 104, SAFE_DAYS)  # D+1 bar differs, inputs identical
check("E2E D+1 prices cannot change the outcome",
      r_a == r_b)
check("E2E direction uses event-day closes only",
      direction(100, 102) == 1 and direction(100, 98) == -1
      and direction(100, 100) == 0)

# 13. Stop base discriminating test: stop is measured from the ACTUAL
#     filled entry price (104 x 1.0008 = 104.0832; stop 102.0015), NOT from
#     the raw open (104 x 0.98 = 101.92). A low of 101.95 triggers only
#     under the filled-price base.
r = run_leg(1, 104, [SAFE_DAYS[0], (105, 101.95, 106, 105)] + SAFE_DAYS[2:])
check("E2E stop base is the filled entry price, not the raw open",
      r["type"] == "stop" and r["day"] == 1)

# 14. D+5 exit unchanged: the position never extends past D+5.
r = run_leg(1, 104, SAFE_DAYS)
check("E2E exit happens on D+5 (day index 3); no extension",
      r["type"] == "close" and r["day"] == 3)

# 15. Two-leg event: stopped BTC leg + held ETH leg -> event mean.
btc = run_leg(1, 104, [SAFE_DAYS[0], (105, 99.0, 106, 105)] + SAFE_DAYS[2:])
eth = run_leg(1, 104, SAFE_DAYS)
ev = run_event((1, 104, [SAFE_DAYS[0], (105, 99.0, 106, 105)] + SAFE_DAYS[2:]),
               (1, 104, SAFE_DAYS))
check("E2E stopped leg + held leg average into one event observation",
      btc["type"] == "stop" and eth["type"] == "close" and ev is not None
      and approx(ev[0], (btc["net"] + eth["net"]) / 2)
      and approx(ev[1], 0.10 * (btc["net"] + eth["net"])))

# 16. OHLC completeness: missing or invalid bars exclude, never default
#     to 'not triggered' (revision 5, condition 1).
check("E2E missing Low excludes the event, not a no-trigger close",
      run_event((1, 104, [(104, 103, 105, 104), (105, None, 106, 105)]
                 + SAFE_DAYS[2:]),
                (1, 104, SAFE_DAYS)) is None)
check("E2E missing High excludes the event, not a no-trigger close",
      run_event((1, 104, [(104, 103, 105, 104), (105, 104, None, 105)]
                 + SAFE_DAYS[2:]),
                (1, 104, SAFE_DAYS)) is None)
check("E2E invalid bar (High < Low) excludes the event",
      run_event((1, 104, [(104, 105, 103, 104)] + SAFE_DAYS[1:]),
                (1, 104, SAFE_DAYS)) is None)
check("E2E D+2 open mismatch with the entry reference excludes the event",
      run_event((1, 105, SAFE_DAYS), (1, 104, SAFE_DAYS)) is None)

# 17. Funding bounds from ACTUAL settlement records (revisions 6-7).
#     Revision 5's single-point stop-day-close cutoff is withdrawn:
#     a stopped leg's funding is an interval, never a defaulted total.
#     Revision 7: rates may be negative, so prefix sums need not be
#     monotone; the interval is min/max over the whole set of possible
#     cumulative totals, never the two endpoint sums.
def funding_bounds(records, stop_day):
    """Funding from actual settlement records (t in hours since D+2 00:00).

    Close leg (stop_day None): exact sum over 0 < t < 96; the exit
    boundary settlement at t=96 is excluded from the main value.
    Stopped leg (stop_day i): the trigger time inside day i is unknown,
    so the cumulative funding actually paid is one of the prefix sums:
    the total through the trigger day's open (00:00 settlement included)
    and after each settlement inside the trigger day. Returns
    ("interval", min(prefixes), max(prefixes)).
    Returns None if any gap inside the coverage window exceeds 24h.
    """
    upper = 96 if stop_day is None else (stop_day + 1) * 24
    window = [(t, r) for (t, r) in records if 0 < t < upper]
    points = [0] + [t for (t, _) in window] + [upper]
    if any(points[k + 1] - points[k] > 24
           for k in range(len(points) - 1)):
        return None
    if stop_day is None:
        return ("exact", sum(r for (_, r) in window))
    base = sum(r for (t, r) in window if t <= stop_day * 24)
    prefixes = [base]
    run = base
    for (t, r) in window:
        if stop_day * 24 < t < (stop_day + 1) * 24:
            run += r
            prefixes.append(run)
    return ("interval", min(prefixes), max(prefixes))


STD = [(t, 0.0001) for t in range(8, 97, 8)]  # standard 8h grid, test data
r = funding_bounds(STD, None)
check("E2E close leg matches 11 certain settlements (boundary excluded)",
      r[0] == "exact" and approx(r[1], 0.0011, 1e-12))
r = funding_bounds(STD + [(96, 0.01)], None)
check("E2E close leg excludes the exit-boundary settlement even if large",
      r[0] == "exact" and approx(r[1], 0.0011, 1e-12))
r = funding_bounds(STD, 0)
check("E2E stop on D+2 gives funding interval [0, 2] settlements",
      r[0] == "interval" and approx(r[1], 0.0, 1e-12)
      and approx(r[2], 0.0002, 1e-12))
r = funding_bounds(STD, 1)
check("E2E stop on D+3 gives funding interval [3, 5] settlements",
      r[0] == "interval" and approx(r[1], 0.0003, 1e-12)
      and approx(r[2], 0.0005, 1e-12))
r = funding_bounds(STD, 3)
check("E2E stop on D+5 gives funding interval [9, 11] settlements",
      r[0] == "interval" and approx(r[1], 0.0009, 1e-12)
      and approx(r[2], 0.0011, 1e-12))
_, lo, hi = funding_bounds(STD, 1)
check("E2E short leg funding interval is the negated rate interval",
      approx(-hi, -0.0005, 1e-12) and approx(-lo, -0.0003, 1e-12))
irregular = [(t, 0.0001) for t in range(8, 97, 8) if t != 32]
r = funding_bounds(irregular, None)
check("E2E irregular records govern: a 2-settlement day counts 10, not 11",
      r[0] == "exact" and approx(r[1], 0.0010, 1e-12))
gapped = [(t, 0.0001) for t in range(8, 41, 8)] + \
         [(t, 0.0001) for t in range(72, 97, 8)]
check("E2E gap over 24h inside the window excludes the leg",
      funding_bounds(gapped, None) is None)
eth_std = [(t, 0.0002) for t in range(8, 97, 8)]
r_btc = funding_bounds(STD, None)
r_eth = funding_bounds(eth_std, None)
check("E2E each leg uses its own asset funding history",
      approx(r_btc[1], 0.0011, 1e-12) and approx(r_eth[1], 0.0022, 1e-12))

# 18. Funding interval bounds with negative rates (revision 7).
#     Bounds are min/max over the whole set of possible prefix totals,
#     applied to ACTUAL net return with the direction sign; endpoint
#     sums are not bounds when rates can be negative.
def net_bounds(gross, fee, direction, lo, hi):
    """Net-return interval from an unsigned funding interval (lo, hi)."""
    s_lo, s_hi = direction * lo, direction * hi
    return (gross - fee - max(s_lo, s_hi),
            gross - fee - min(s_lo, s_hi))

mixed = [(t, 0.0001) for t in (8, 16, 24)] + \
        [(32, -0.0005), (40, 0.0001)] + \
        [(t, 0.0001) for t in range(48, 97, 8)]
r = funding_bounds(mixed, 1)
check("REV7 mixed-sign stop day: bounds are prefix extremes, not endpoints",
      r[0] == "interval" and approx(r[1], -0.0002, 1e-12)
      and approx(r[2], 0.0003, 1e-12))
check("REV7 interval contains every possible prefix total",
      r[1] <= -0.0001 <= r[2] and r[1] <= 0.0003 <= r[2])
neg = [(t, -0.0001) for t in range(8, 97, 8)]
r = funding_bounds(neg, 0)
check("REV7 all-negative stop day: bounds are [-0.0002, 0.0]",
      r[0] == "interval" and approx(r[1], -0.0002, 1e-12)
      and approx(r[2], 0.0, 1e-12))
nlo, nhi = net_bounds(0.01, 0.001, -1, -0.0002, 0.0003)
check("REV7 short leg: net bounds from signed funding extremes",
      approx(nlo, 0.01 - 0.001 - 0.0002, 1e-12)
      and approx(nhi, 0.01 - 0.001 + 0.0003, 1e-12))
r = funding_bounds(neg, None)
check("REV7 close leg with negative rates is the exact (negative) sum",
      r[0] == "exact" and approx(r[1], -0.0011, 1e-12))
gapped_neg = [(t, -0.0001) for t in range(8, 41, 8)] + \
             [(t, -0.0001) for t in range(72, 97, 8)]
check("REV7 gap over 24h excludes the leg even with negative rates",
      funding_bounds(gapped_neg, None) is None)

print("ALL C5 END-TO-END TESTS PASSED")
