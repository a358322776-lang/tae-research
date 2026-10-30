"""C5 exploratory backtest, single approved run (revision 8 rules).

APPROVAL STATUS (2026-10-30): the v1 execution approval ("批了") was
SUPERSEDED the same day by the user's postponement instruction, and
application v2 is still awaiting approval. NO backtest has been run.
This script MUST NOT execute a returns run until EXECUTION_APPROVED
is set True with the fresh v2 approval recorded. --verify-only runs
gates only and never touches returns data.
Rules: freeze draft v0.8-DRAFT. Exploration window 2020-01-01..2026-10-30.
NO tuning, NO freeze, NO live trading. One run; bug-fix re-runs must be
recorded, never silent.

DIRECTION (decided by user 2026-10-30, revision 8): PER_LEG — each leg
uses its own asset's event-day direction; the noise filter applies
per leg; the placebo draws per (event, leg), BTC leg before ETH leg.

Usage:
  python3 c5-exploratory-backtest.py --verify-only   # gates only, no run
  python3 c5-exploratory-backtest.py                # REFUSED until approved
"""
import calendar
import csv
import json
import math
import os
import random
import sys
import time
from datetime import date, datetime, timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
SEED = 20261030
FEE_RT = 0.001
STOP_PCT = 0.02
CUTOFF_DATE = "2026-10-30"
# Direction rule, decided by the user 2026-10-30 (revision 8).
DIRECTION_REFERENCE = "PER_LEG"
# Execution approval gate: False refuses ANY returns run. Set True only
# with the fresh v2 approval recorded (approver + UTC timestamp).
EXECUTION_APPROVED = False
TIERS = {
    "low": {"slip": 0.00025, "spread": 0.0001},
    "central": {"slip": 0.0005, "spread": 0.0003},
    "high": {"slip": 0.0015, "spread": 0.0005},
}
for t in TIERS.values():
    t["exec"] = t["slip"] + t["spread"]
    t["roundtrip"] = 2 * (t["slip"] + t["spread"]) + FEE_RT


def utc_ms(y, m, d, hh=0):
    return int(datetime(y, m, d, hh, tzinfo=timezone.utc).timestamp() * 1000)


def approx(a, b, tol=1e-9):
    return abs(a - b) <= tol


# ---------------------------------------------------------------- engine
def run_leg_prices(direction, entry_open, days, exec_cost):
    """Entry/stop/exit mechanics. Mirrors c5-e2e-tests.py run_leg (prices).

    days: (open, low, high, close) for D+2..D+5. Returns
    (exit_type, exit_day_idx, entry_px, exit_px, gross).
    """
    assert direction in (1, -1)
    entry_px = entry_open * (1 + direction * exec_cost)
    stop = entry_px * (1 - direction * STOP_PCT)
    for i, (o, low, high, c) in enumerate(days):
        if i > 0:
            if direction == 1 and o <= stop:
                return ("stop-gap", i, entry_px, o * (1 - exec_cost),
                        (o * (1 - exec_cost) - entry_px) / entry_px)
            if direction == -1 and o >= stop:
                return ("stop-gap", i, entry_px, o * (1 + exec_cost),
                        (entry_px - o * (1 + exec_cost)) / entry_px)
        if direction == 1 and low <= stop:
            px = stop * (1 - exec_cost)
            return ("stop", i, entry_px, px, (px - entry_px) / entry_px)
        if direction == -1 and high >= stop:
            px = stop * (1 + exec_cost)
            return ("stop", i, entry_px, px, (entry_px - px) / entry_px)
        if i == len(days) - 1:
            px = c * (1 - direction * exec_cost)
            return ("close", i, entry_px, px,
                    direction * (px - entry_px) / entry_px)
    raise AssertionError("no exit reached")


def funding_for_leg(records, entry_ms, exit_kind, exit_day_idx):
    """Funding from ACTUAL settlement records [(t_ms, rate)], sorted.

    exit_kind 'close': exact sum over entry_ms < t < exit_ms, where
    exit_ms = D+6 00:00 UTC (the exit boundary settlement is excluded).
    exit_kind 'stop': the trigger time inside the trigger day is
    unknown, so the cumulative funding actually paid is one of the
    prefix sums: the total through the trigger day's open (00:00
    settlement included) and after each settlement inside the trigger
    day. Rates may be negative, so prefix sums need not be monotone:
    returns ("interval", min(prefixes), max(prefixes)) over the whole
    set of possible totals, never the two endpoint sums. Returns None
    when any gap inside the coverage window exceeds 24h.
    """
    if exit_kind == "close":
        upper = entry_ms + 4 * 86400000  # D+2 00:00 + 4d = D+6 00:00
        window = [(t, r) for (t, r) in records if entry_ms < t < upper]
    else:
        upper = entry_ms + (exit_day_idx + 1) * 86400000
        window = [(t, r) for (t, r) in records if entry_ms < t < upper]
    points = [entry_ms] + [t for (t, _) in window] + [upper]
    if any(points[k + 1] - points[k] > 24 * 3600000
           for k in range(len(points) - 1)):
        return None
    if exit_kind == "close":
        return ("exact", sum(r for (_, r) in window))
    low_cut = entry_ms + exit_day_idx * 86400000
    base = sum(r for (t, r) in window if t <= low_cut)
    prefixes = [base]
    run = base
    for (t, r) in window:
        if low_cut < t < upper:
            run += r
            prefixes.append(run)
    return ("interval", min(prefixes), max(prefixes))


# ------------------------------------------------------------- verification
def verify():
    """Gate: engine must reproduce the e2e definitions exactly."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "c5_e2e", os.path.join(BASE, "c5-e2e-tests.py"))
    e2e = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(e2e)  # runs the 33 e2e checks; must pass
    safe = e2e.SAFE_DAYS
    scenarios = [
        (1, 104, safe),
        (1, 104, [safe[0], safe[1], (106, 99.0, 107, 106),
                  (107, 106, 108, 999)]),
        (1, 104, [safe[0], (99, 98, 104, 104)] + safe[2:]),
        (1, 104, [(104, 99.0, 105, 104)] + safe[1:]),
        (1, 104, safe[:3] + [(107, 99.0, 108, 108)]),
        (-1, 104, [(104, 103, 105, 104), (103, 102, 107, 103),
                   (102, 101, 103, 102), (101, 100, 102, 101)]),
        (1, 104, [safe[0], (105, 101.95, 106, 105)] + safe[2:]),
    ]
    for (d, eo, days) in scenarios:
        ref = e2e.run_leg(d, eo, days)
        got = run_leg_prices(d, eo, days, e2e.EXEC)
        assert got[0] == ref["type"], (got, ref)
        assert got[1] == ref["day"], (got, ref)
        assert approx(got[2], ref["entry_px"]), (got, ref)
        assert approx(got[3], ref["exit_px"]), (got, ref)
        assert approx(got[4], ref["gross"]), (got, ref)
    # funding bounds equivalence (hours -> ms); revision 7: prefix
    # extremes, including negative-rate cases where endpoint sums fail
    std = [(h * 3600000, 0.0001) for h in range(8, 97, 8)]
    kind, v = funding_for_leg(std, 0, "close", 3)
    assert kind == "exact" and approx(v, 0.0011, 1e-12), (kind, v)
    for day, (lo, hi) in [(0, (0.0, 0.0002)), (1, (0.0003, 0.0005)),
                          (3, (0.0009, 0.0011))]:
        kind, l, h = funding_for_leg(std, 0, "stop", day)
        assert kind == "interval" and approx(l, lo, 1e-12) \
            and approx(h, hi, 1e-12), (day, kind, l, h)
    mixed = [(h * 3600000, 0.0001) for h in (8, 16, 24)] + \
            [(32 * 3600000, -0.0005), (40 * 3600000, 0.0001)] + \
            [(h * 3600000, 0.0001) for h in range(48, 97, 8)]
    kind, l, h = funding_for_leg(mixed, 0, "stop", 1)
    assert kind == "interval" and approx(l, -0.0002, 1e-12) \
        and approx(h, 0.0003, 1e-12), ("mixed-sign", kind, l, h)
    neg = [(h * 3600000, -0.0001) for h in range(8, 97, 8)]
    kind, l, h = funding_for_leg(neg, 0, "stop", 0)
    assert kind == "interval" and approx(l, -0.0002, 1e-12) \
        and approx(h, 0.0, 1e-12), ("all-negative", kind, l, h)
    print("IMPLEMENTATION VERIFICATION PASSED: engine reproduces "
          "e2e price mechanics (7 scenarios) and funding bounds "
          "(close + stop days 0/1/3 + mixed-sign prefix extremes).")
    return True


# ------------------------------------------------------------------- data
def load_json(path):
    with open(path) as f:
        return json.load(f)


def valid_bar(b):
    o, h, l, c = b
    return all(x > 0 for x in b) and h >= l and h >= o and h >= c \
        and l <= o and l <= c


def run_tier(tier, events, bars, funding, directions):
    """Run one cost tier. directions: dict (date, series, symbol) -> +1/-1
    (revision 8: each leg uses its own asset's event-day direction).

    Returns (trades, logs) where trades carry per-leg detail and net
    intervals; logs carry no-trade / skipped / excluded lists.
    """
    cfg = TIERS[tier]
    ex = cfg["exec"]
    busy_until = None
    trades, logs = [], {"no_trade": [], "skipped": [], "excluded": []}
    for (ev_date, series) in sorted(events):
        d = date.fromisoformat(ev_date)
        dm1 = (d - timedelta(days=1)).isoformat()
        legs = {}
        ok = True
        for sym in ("BTCUSDT", "ETHUSDT"):
            b = bars[sym]
            if dm1 not in b or ev_date not in b:
                ok = False
                break
            prev_c = b[dm1][3]
            ev_c = b[ev_date][3]
            move = (ev_c - prev_c) / prev_c
            days = []
            for i in range(2, 6):
                day = (d + timedelta(days=i)).isoformat()
                if day not in b or not valid_bar(b[day]):
                    ok = False
                    break
                days.append(tuple(b[day]))
            if not ok:
                break
            legs[sym] = (move, days)
        if not ok:
            logs["excluded"].append((ev_date, series, "missing/invalid"))
            continue
        # per-leg noise filter (revision 8): a leg trades only if its
        # OWN |event-day move| >= the tier's round-trip cost
        passing = [sym for sym in ("BTCUSDT", "ETHUSDT")
                   if abs(legs[sym][0]) >= cfg["roundtrip"]]
        for sym in ("BTCUSDT", "ETHUSDT"):
            if sym not in passing:
                logs["no_trade"].append(
                    (ev_date, series, sym, round(legs[sym][0], 6)))
        if not passing:
            continue
        entry_day = d + timedelta(days=2)
        if busy_until is not None and entry_day <= busy_until:
            logs["skipped"].append((ev_date, series))
            continue
        leg_results = []
        for sym in passing:
            direction = directions[(ev_date, series, sym)]
            _, days = legs[sym]
            entry_open = days[0][0]
            typ, day_idx, entry_px, exit_px, gross = run_leg_prices(
                direction, entry_open, days, ex)
            entry_ms = utc_ms(d.year, d.month, d.day) + 2 * 86400000
            kind = "close" if typ == "close" else "stop"
            fund = funding_for_leg(funding[sym], entry_ms, kind, day_idx)
            if fund is None:
                leg_results = None
                break
            if fund[0] == "exact":
                s_lo = s_hi = direction * fund[1]
            else:
                # fund = ("interval", min_prefix, max_prefix) of UNSIGNED
                # cumulative totals; bounds on ACTUAL net return come
                # from the extremes of the direction-signed set.
                s_a = direction * fund[1]
                s_b = direction * fund[2]
                s_lo, s_hi = min(s_a, s_b), max(s_a, s_b)
            net_lo = gross - FEE_RT - max(s_lo, s_hi)
            net_hi = gross - FEE_RT - min(s_lo, s_hi)
            leg_results.append({
                "symbol": sym, "direction": direction,
                "exit_type": typ, "exit_day": day_idx,
                "entry_px": entry_px, "exit_px": exit_px, "gross": gross,
                "fund_lo": min(s_lo, s_hi), "fund_hi": max(s_lo, s_hi),
                "net_lo": net_lo, "net_hi": net_hi,
                "fund_n": fund[1:] if fund[0] == "exact" else fund[1:],
            })
        if leg_results is None:
            logs["excluded"].append((ev_date, series, "funding-coverage"))
            continue
        busy_until = d + timedelta(days=5)
        n = len(leg_results)
        net_lo = sum(l["net_lo"] for l in leg_results) / n
        net_hi = sum(l["net_hi"] for l in leg_results) / n
        trades.append({
            "date": ev_date, "series": series, "legs": leg_results,
            "net_lo": net_lo, "net_hi": net_hi,
            "contrib_lo": 0.10 * sum(l["net_lo"] for l in leg_results),
            "contrib_hi": 0.10 * sum(l["net_hi"] for l in leg_results),
        })
    return trades, logs


def lag1(xs):
    n = len(xs)
    if n < 2:
        return None
    mean = sum(xs) / n
    num = sum((xs[i] - mean) * (xs[i - 1] - mean) for i in range(1, n))
    den = sum((x - mean) ** 2 for x in xs)
    return num / den if den else 0.0


def main():
    verify()
    if "--verify-only" in sys.argv:
        print("Verify-only mode: no backtest run.")
        return
    if not EXECUTION_APPROVED:
        raise SystemExit(
            "REFUSED: no fresh execution approval (application v2 "
            "still awaiting approval); the script refuses any returns "
            "run until approval is recorded by setting "
            "EXECUTION_APPROVED = True.")
    t0 = time.time()
    bars = {s: load_json(os.path.join(DATA, f"klines_{s}.json"))
            for s in ("BTCUSDT", "ETHUSDT")}
    funding = {s: sorted((int(r[0]), float(r[1]))
                         for r in load_json(os.path.join(DATA, f"funding_{s}.json")))
               for s in ("BTCUSDT", "ETHUSDT")}
    # Cutoff guard (revision 7): no post-cutoff data may enter returns.
    assert max(d for b in bars.values() for d in b) <= CUTOFF_DATE
    assert max(t for recs in funding.values() for (t, _) in recs) \
        < utc_ms(2026, 10, 31)
    rows = list(csv.DictReader(open(os.path.join(
        BASE, "c5-event-calendar-draft.csv"))))
    events = [(r["date"], r["series"]) for r in rows]
    # Per-leg directions (revision 8, decided by user 2026-10-30):
    # each leg uses its own asset's event-day move. Cutoff-incomplete
    # events (window extends past CUTOFF_DATE) are listed separately
    # as pending and NEVER backfilled with post-cutoff data.
    if DIRECTION_REFERENCE != "PER_LEG":
        raise SystemExit(
            "REFUSED: unsupported DIRECTION_REFERENCE="
            f"{DIRECTION_REFERENCE!r}")
    directions = {}
    pending = []
    for (ev_date, series) in events:
        d = date.fromisoformat(ev_date)
        complete = True
        for sym in ("BTCUSDT", "ETHUSDT"):
            b = bars[sym]
            for i in range(-1, 6):
                day = (d + timedelta(days=i)).isoformat()
                if day not in b or (i >= 2 and not valid_bar(b[day])):
                    complete = False
        if not complete:
            pending.append((ev_date, series))
            continue
        for sym in ("BTCUSDT", "ETHUSDT"):
            prev_c = bars[sym][(d - timedelta(days=1)).isoformat()][3]
            ev_c = bars[sym][ev_date][3]
            directions[(ev_date, series, sym)] = \
                1 if ev_c > prev_c else -1
    evaluated = sorted({(d0, s0) for (d0, s0, _) in directions})
    # placebo stream: one draw per (event, leg), chronological events,
    # BTC leg before ETH leg within each event
    rng = random.Random(SEED)
    placebo_dirs = {}
    for key in evaluated:
        for sym in ("BTCUSDT", "ETHUSDT"):
            placebo_dirs[(key[0], key[1], sym)] = \
                1 if rng.random() >= 0.5 else -1
    results = {"run_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                           time.gmtime()),
               "seed": SEED, "window": ["2020-01-01", "2026-10-30"],
               "pending_excluded": pending, "tiers": {}}
    for tier in ("low", "central", "high"):
        trades, logs = run_tier(tier, evaluated, bars, funding, directions)
        ptrades, plogs = run_tier(tier, evaluated, bars, funding,
                                  placebo_dirs)
        assert [ (t["date"], t["series"]) for t in trades ] == \
               [ (t["date"], t["series"]) for t in ptrades ], \
            "strategy/placebo traded sets differ"
        results["tiers"][tier] = {"trades": trades, "logs": logs,
                                  "placebo_trades": ptrades,
                                  "placebo_logs": plogs}
    # zero-EXEC variant on the central traded set (double-count check)
    cfg = TIERS["central"]
    zero_diffs = []
    for t in results["tiers"]["central"]["trades"]:
        d = date.fromisoformat(t["date"])
        diffs = []
        for leg in t["legs"]:
            sym = leg["symbol"]
            days = [tuple(bars[sym][(d + timedelta(days=i)).isoformat()])
                    for i in range(2, 6)]
            typ, day_idx, e_px, x_px, gross0 = run_leg_prices(
                leg["direction"], days[0][0], days, 0.0)
            assert typ == leg["exit_type"] and day_idx == leg["exit_day"]
            diffs.append(((leg["net_lo"] + leg["net_hi"]) / 2)
                         - (gross0 - FEE_RT
                            - (leg["fund_lo"] + leg["fund_hi"]) / 2))
        zero_diffs.append(sum(diffs) / 2)
    results["zero_exec_check"] = {
        "mean_diff": sum(zero_diffs) / len(zero_diffs),
        "n": len(zero_diffs)}
    # buy-and-hold, gross, 2020-01-01 close -> 2026-10-29 close (final)
    bh = {}
    for sym in ("BTCUSDT", "ETHUSDT"):
        b = bars[sym]
        bh[sym] = b["2026-10-29"][3] / b["2020-01-01"][3] - 1
    results["buy_hold"] = bh
    results["buy_hold_mean"] = sum(bh.values()) / 2
    # R: FRED DGS3MO mean over the window
    import urllib.request
    try:
        req = urllib.request.Request(
            "https://fred.stlouisfed.org/graph/fredgraph.csv"
            "?id=DGS3MO&cosd=2020-01-01&coed=2026-10-30",
            headers={"User-Agent": "curl"})
        text = urllib.request.urlopen(req, timeout=60).read().decode()
        vals = [float(r[1]) for r in csv.reader(text.splitlines()[1:])
                if r and r[1] != "."]
        results["R"] = {"source": "FRED DGS3MO", "mean_pct": sum(vals) / len(vals),
                        "n_obs": len(vals), "last_pct": vals[-1]}
    except Exception as e:
        results["R"] = {"source": "fallback point value 4.18% (2026-10-29)",
                        "mean_pct": 4.18, "n_obs": 0, "error": str(e)}
    # calendar equity curves, central tier, funding-bound pair
    results["equity"] = build_equity(results["tiers"]["central"]["trades"],
                                     bars, funding)
    with open(os.path.join(DATA, "c5-exploratory-results.json"), "w") as f:
        json.dump(results, f)
    print(f"RUN COMPLETE in {time.time()-t0:.1f}s: "
          f"{len(evaluated)} evaluated, {len(pending)} pending-excluded, "
          f"central trades={len(results['tiers']['central']['trades'])}.")


def build_equity(trades, bars, funding):
    """Daily equity curves (central tier), funding-bound pair.

    equity_lo uses the lower funding-cost bound, equity_hi the upper.
    Open legs marked at daily close; exited legs at realized nets.
    """
    start = date(2020, 1, 1)
    end = date(2026, 10, 30)
    # per-leg daily value contributions
    legs = []
    for t in trades:
        d = date.fromisoformat(t["date"])
        for leg in t["legs"]:
            sym = leg["symbol"]
            entry_day = d + timedelta(days=2)
            exit_day = entry_day + timedelta(days=leg["exit_day"])
            legs.append((t, leg, sym, entry_day, exit_day))
    curves = {"lo": {}, "hi": {}}
    cur = start
    while cur <= end:
        vals = {"lo": 1.0, "hi": 1.0}
        for (t, leg, sym, entry_day, exit_day) in legs:
            b = bars[sym]
            day = cur.isoformat()
            if cur < entry_day or day not in b:
                continue
            if cur >= exit_day:
                v_lo = leg["net_lo"]
                v_hi = leg["net_hi"]
            else:
                close = b[day][3]
                mtm = leg["direction"] * (close - leg["entry_px"]) \
                    / leg["entry_px"] - FEE_RT
                # funding accrued through end of day (exact: settlements
                # already observed; the interval only bites on the stop day,
                # which is handled by the realized branch above)
                entry_ms = utc_ms(entry_day.year, entry_day.month,
                                  entry_day.day)
                day_end_ms = utc_ms(cur.year, cur.month, cur.day) + 86400000
                acc = sum(r for (ts, r) in funding[sym]
                          if entry_ms < ts < day_end_ms)
                signed = leg["direction"] * acc
                v_lo = v_hi = mtm - signed
            vals["lo"] += 0.10 * v_lo
            vals["hi"] += 0.10 * v_hi
        curves["lo"][cur.isoformat()] = vals["lo"]
        curves["hi"][cur.isoformat()] = vals["hi"]
        cur += timedelta(days=1)

    def mdd(curve):
        peak, dd = -1e18, 0.0
        for v in curve.values():
            peak = max(peak, v)
            dd = max(dd, peak - v)
        return dd
    return {"mdd_lo_cost_curve": mdd(curves["lo"]),
            "mdd_hi_cost_curve": mdd(curves["hi"]),
            "final_lo": curves["lo"]["2026-10-30"],
            "final_hi": curves["hi"]["2026-10-30"],
            "curves_local_only": True}


if __name__ == "__main__":
    main()
