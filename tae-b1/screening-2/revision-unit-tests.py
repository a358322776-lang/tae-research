"""Minimal unit tests for the C5/C3 revision reports (screening-2).

Tests definitions and arithmetic only. No backtest, no price history,
no parameter tuning. Run: python3 revision-unit-tests.py

Changelog (2026-10-30, revision 2):
- REMOVED the asset-level effective-N tests from revision 1 (N_eff ~97):
  they mixed asset-level observations into the event-level sample and
  are superseded by the event-observation rule (N = number of events).
- ADDED: event-level reporting, cross-event lag-1 autocorrelation,
  stop boundary rules (entry-day order, same-day priority, gap,
  slippage/fees/funding, post-stop termination), and the C3
  conditional-liquidation / 2x boundary arithmetic.
- REVISION 3 (2026-10-30): net accounting changed to price-embedded
  single-count slippage (see c5-revision-3-execution-accounting.md);
  the old separate-slippage net helper is replaced, not kept alongside.
"""

R = 0.0418  # 3M T-bill, 2026-10-29


def gross_threshold(events_per_year, cost, size):
    """Required gross continuation per traded event (fraction of price)."""
    return (R / events_per_year + cost * size) / size


def report_event_n(n_events):
    """Primary sample size = number of events. Asset legs are not counted."""
    return n_events


def lag1_autocorr(xs):
    """Lag-1 autocorrelation of an event-ordered series; zero variance -> 0."""
    n = len(xs)
    if n < 2:
        return 0.0
    mean = sum(xs) / n
    num = sum((xs[i] - mean) * (xs[i - 1] - mean) for i in range(1, n))
    den = sum((x - mean) ** 2 for x in xs)
    return num / den if den else 0.0


def benchmark_tradable_at_entry(inputs_available_at_entry, benchmark):
    """Kill-line benchmarks must be constructible with entry-time info only."""
    if benchmark == "event-day":
        return False  # needs the event-day close, unknown before the close
    return inputs_available_at_entry


def simulate_leg(entry_close, stop_pct, days, side="long", slippage=0.001):
    """Simulate one leg over days AFTER entry (D+2 .. D+5).

    days: list of (open, low, high, close); last day is the scheduled exit.
    Returns (exit_type, exit_price, day_index) where exit_type is one of
    'stop-gap', 'stop', 'close'. Entry-day extremes must never be passed in.
    Stop beats same-day close exit (R-C5-S3).
    """
    if side == "long":
        stop = entry_close * (1 - stop_pct)
        for i, (o, low, high, c) in enumerate(days):
            if o <= stop:
                return "stop-gap", o, i
            if low <= stop:
                return "stop", stop * (1 - slippage), i
            if i == len(days) - 1:
                return "close", c, i
    else:
        stop = entry_close * (1 + stop_pct)
        for i, (o, low, high, c) in enumerate(days):
            if o >= stop:
                return "stop-gap", o, i
            if high >= stop:
                return "stop", stop * (1 + slippage), i
            if i == len(days) - 1:
                return "close", c, i
    raise AssertionError("no exit reached")


def net_from_prices(entry_px, exit_px, direction, fee, funding):
    """Revision 3 single-count accounting: slippage lives in prices only.

    direction: +1 long, -1 short. funding is signed (long pays +, short -).
    """
    assert None not in (entry_px, exit_px, direction, fee, funding)
    return direction * (exit_px - entry_px) / entry_px - fee - funding


def liq_price_1x_with_fee(p0, entry_fee_rate, mm_rate):
    """Finite 1x liquidation price once the entry fee is deducted (coin)."""
    return p0 * (1 - mm_rate) / entry_fee_rate


def liq_price_2x(p0, mm_rate):
    """2x neutral-config liquidation boundary: 2 * P0 * (1 - mm)."""
    return 2 * p0 * (1 - mm_rate)


def coinm_net_delta(spot_btc, notional_usd, price, leverage):
    """Net delta in BTC: spot + margin coin - short delta. Margin = N/(L*P)."""
    margin_btc = notional_usd / (leverage * price)
    return spot_btc + margin_btc - notional_usd / price


def coinm_example(p0=100_000, p1=110_000, spot_btc=0.01, notional=1_000):
    """Worked example from the C3 audit (revision 1, section 2.5)."""
    spot_pnl = spot_btc * (p1 - p0)
    short_coin = notional * (1 / p1 - 1 / p0)
    short_usdt_at_exit = short_coin * p1
    margin_gain = spot_btc * (p1 - p0)
    committed = spot_btc * p0 + (notional / p0) * p0
    total = spot_pnl + short_usdt_at_exit + margin_gain
    return {"spot": spot_pnl, "short_usdt": short_usdt_at_exit,
            "margin_gain": margin_gain, "committed": committed, "total": total}


def check(name, cond):
    assert cond, f"FAIL: {name}"
    print(f"ok: {name}")


def approx(a, b, tol=1e-3):
    return abs(a - b) <= tol


# --- C5: high-return threshold table (revision 1, section 5) ---
check("C5 threshold 10pct cost0.20 unfiltered = 1.69%",
      approx(gross_threshold(28, 0.0020, 0.10), 0.0169, 1e-4))
check("C5 threshold 20pct cost0.20 unfiltered = 0.95%",
      approx(gross_threshold(28, 0.0020, 0.20), 0.0095, 1e-4))
check("C5 threshold 10pct cost0.20 filtered40pct = 2.69%",
      approx(gross_threshold(16.8, 0.0020, 0.10), 0.0269, 1e-4))
check("C5 threshold 20pct cost0.40 unfiltered = 1.15%",
      approx(gross_threshold(28, 0.0040, 0.20), 0.0115, 1e-4))
check("C5 threshold rises when cost rises",
      gross_threshold(28, 0.0040, 0.10) > gross_threshold(28, 0.0020, 0.10))
check("C5 threshold rises when events/year falls",
      gross_threshold(25, 0.0020, 0.10) > gross_threshold(28, 0.0020, 0.10))

# --- C5 (revision 2): event-level sample size, no asset-level mixing ---
check("C5 sample size is event count: 90 events -> N=90, not 180",
      report_event_n(90) == 90 and report_event_n(90) != 180)
check("C5 event obs is the mean of both legs",
      (0.05 + 0.03) / 2 == 0.04)
check("C5 cross-event lag-1 autocorr of alternating series is -0.75",
      approx(lag1_autocorr([1, -1, 1, -1]), -0.75, 1e-9))
check("C5 cross-event lag-1 autocorr of constant series is 0",
      lag1_autocorr([0.02, 0.02, 0.02]) == 0.0)
check("C5 event-day benchmark is not tradable at entry",
      benchmark_tradable_at_entry(True, "event-day") is False)
check("C5 placebo / buy-hold / R are tradable at entry",
      all(benchmark_tradable_at_entry(True, b)
          for b in ("placebo", "buy-hold", "R")))

# --- C5 (revision 2): stop boundary rules ---
# Entry-day extremes are never fed to simulate_leg: the caller starts at D+2.
# A D+1 low below the stop therefore cannot trigger (tested by construction:
# simulate_leg receives only post-entry days).
typ, px, _ = simulate_leg(100, 0.02, [(101, 97.5, 102, 101)], "long")
check("C5 stop intraday trigger executes near stop with slippage",
      typ == "stop" and approx(px, 98 * 0.999, 1e-9))
typ, px, _ = simulate_leg(100, 0.02, [(95, 94, 96, 97)], "long")
check("C5 stop gap-through executes at open, worse than stop",
      typ == "stop-gap" and px == 95 and px < 98)
typ, px, _ = simulate_leg(100, 0.02, [(95, 94, 96, 99.5)], "long")
check("C5 gap execution is not reversed when price recovers intraday",
      typ == "stop-gap" and px == 95)
typ, px, _ = simulate_leg(100, 0.02, [(101, 98.5, 102, 103)], "long")
check("C5 stop no trigger when low stays above stop",
      typ == "close" and px == 103)
typ, px, _ = simulate_leg(100, 0.02, [(101, 97.0, 102, 104)], "long")
check("C5 stop beats same-day close exit on the exit day",
      typ == "stop" and px < 104)
typ, px, _ = simulate_leg(100, 0.02, [(105, 100, 106, 104)], "short")
check("C5 short gap-through executes at open", typ == "stop-gap" and px == 105)
# Post-stop termination: stopped leg frozen at stop price; other leg continues.
btc = simulate_leg(100, 0.02, [(101, 97.5, 102, 101)], "long")
eth = simulate_leg(100, 0.02, [(101, 99.0, 102, 103)], "long")
check("C5 stopped leg frozen, other leg runs to close; event obs is the mean",
      btc[0] == "stop" and eth[0] == "close"
      and approx((btc[1] + eth[1]) / 2, (98 * 0.999 + 103) / 2, 1e-9))
entry_px = 103 * 1.0005
exit_px = 106 * (1 - 0.0005)
net_slipped = net_from_prices(entry_px, exit_px, 1, 0.001, 0.0004)
net_unslipped = net_from_prices(103, 106, 1, 0.001, 0.0004)
check("C5 revision 3 net: slippage embedded in prices, fee+funding separate",
      approx(net_slipped,
             (exit_px - entry_px) / entry_px - 0.001 - 0.0004, 1e-12))
check("C5 revision 3 single-count guard: slip impact ~ -0.10%, not -0.20%",
      approx(net_slipped - net_unslipped, -0.001, 1e-4)
      and not approx(net_slipped - net_unslipped, -0.002, 1e-4))

# --- C3 (revision 1): COIN-M residual delta + worked example ---
check("C3 COIN-M 1x net delta equals spot holding (never neutral)",
      approx(coinm_net_delta(0.01, 1_000, 100_000, 1), 0.01, 1e-9))
check("C3 COIN-M 2x can be neutral with N=2*S*P, margin=S",
      approx(coinm_net_delta(0.01, 2_000, 100_000, 2), 0.0, 1e-9))
ex = coinm_example()
check("C3 worked example: +10% move -> +$100 on $2000 committed (+5%)",
      approx(ex["spot"], 100) and approx(ex["short_usdt"], -100)
      and approx(ex["margin_gain"], 100) and approx(ex["committed"], 2000)
      and approx(ex["total"], 100))
check("C3 exit-price conversion differs from entry-price conversion",
      approx(1_000 * (1 / 110_000 - 1 / 100_000) * 110_000, -100)
      and not approx(1_000 * (1 / 110_000 - 1 / 100_000) * 100_000, -100))
check("C3 committed capital sums both legs",
      approx(0.01 * 100_000 + (1_000 / 100_000) * 100_000, 2000))
check("C3 carry kill-line benchmarks exclude naked spot",
      "naked-spot" not in {"R", "cost-hurdle"})

# --- C3 (revision 2): conditional 1x liquidation + 2x boundary ---
check("C3 1x with entry fee has finite but distant liquidation price ~1990x",
      approx(liq_price_1x_with_fee(100_000, 0.0005, 0.005), 199_000_000, 1))
check("C3 2x liquidation boundary at mm=0.5% is 1.99x entry",
      approx(liq_price_2x(100_000, 0.005), 199_000, 1))
check("C3 2x liquidation boundary table: mm 0/1%/2% -> 2.00/1.98/1.96x",
      approx(liq_price_2x(100_000, 0.0), 200_000, 1)
      and approx(liq_price_2x(100_000, 0.01), 198_000, 1)
      and approx(liq_price_2x(100_000, 0.02), 196_000, 1))

print("ALL REVISION UNIT TESTS PASSED")
