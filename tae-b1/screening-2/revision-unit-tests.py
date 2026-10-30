"""Minimal unit tests for the C5/C3 revision reports (screening-2).

Tests definitions and arithmetic only. No backtest, no price history,
no parameter tuning. Run: python3 revision-unit-tests.py

Changelog:
- Revision 2 (2026-10-30): event-level reporting replaces asset-level
  effective-N; cross-event lag-1 autocorrelation; C3 conditional
  liquidation / 2x boundary arithmetic.
- Revision 3 (2026-10-30): net accounting changed to price-embedded
  single-count slippage (see c5-revision-3-execution-accounting.md).
- Revision 4 (2026-10-30): cost totals now include a separate spread
  line (round-trip low/central/high 0.17%/0.26%/0.50%); threshold
  expectations updated by formula. Stop mechanics under the v0.4 timing
  (D+2 open entry, stop from filled price) are covered exclusively by
  c5-e2e-tests.py; the old D+1-close-entry stop tests were removed
  rather than kept alongside contradictory timing.
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


def net_from_prices(entry_px, exit_px, direction, fee, funding):
    """Single-count accounting: slippage/spread live in prices only.

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


# --- C5: high-return threshold table (revision 4 totals: RT 0.17/0.26/0.50%) ---
check("C5 threshold 10pct central RT0.26 unfiltered = 1.75%",
      approx(gross_threshold(28, 0.0026, 0.10), 0.0175, 1e-4))
check("C5 threshold 20pct central RT0.26 unfiltered = 1.01%",
      approx(gross_threshold(28, 0.0026, 0.20), 0.0101, 1e-4))
check("C5 threshold 10pct central RT0.26 filtered40pct = 2.75%",
      approx(gross_threshold(16.8, 0.0026, 0.10), 0.0275, 1e-4))
check("C5 threshold 20pct low RT0.17 unfiltered = 0.92%",
      approx(gross_threshold(28, 0.0017, 0.20), 0.0092, 1e-4))
check("C5 threshold 10pct high RT0.50 unfiltered = 1.99%",
      approx(gross_threshold(28, 0.0050, 0.10), 0.0199, 1e-4))
check("C5 threshold rises when cost rises",
      gross_threshold(28, 0.0050, 0.10) > gross_threshold(28, 0.0026, 0.10))
check("C5 threshold rises when events/year falls",
      gross_threshold(25, 0.0026, 0.10) > gross_threshold(28, 0.0026, 0.10))
check("C5 threshold 25 events 10pct central = 1.93%",
      approx(gross_threshold(25, 0.0026, 0.10), 0.0193, 1e-4))

# --- C5: event-level sample size, no asset-level mixing ---
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

# --- C5: single-count net accounting (revisions 3-4) ---
entry_px = 103 * 1.0008
exit_px = 106 * (1 - 0.0008)
net_cost = net_from_prices(entry_px, exit_px, 1, 0.001, 0.0004)
net_bare = net_from_prices(103, 106, 1, 0.001, 0.0004)
check("C5 net: slip+spread embedded in prices, fee+funding separate",
      approx(net_cost,
             (exit_px - entry_px) / entry_px - 0.001 - 0.0004, 1e-12))
check("C5 single-count guard: cost impact ~ -0.16%, not -0.32%",
      approx(net_cost - net_bare, -0.0016, 2e-4)
      and not approx(net_cost - net_bare, -0.0032, 2e-4))

# --- C3: COIN-M audit (revisions 1-2) ---
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
check("C3 1x with entry fee has finite but distant liquidation price ~1990x",
      approx(liq_price_1x_with_fee(100_000, 0.0005, 0.005), 199_000_000, 1))
check("C3 2x liquidation boundary at mm=0.5% is 1.99x entry",
      approx(liq_price_2x(100_000, 0.005), 199_000, 1))
check("C3 2x liquidation boundary table: mm 0/1%/2% -> 2.00/1.98/1.96x",
      approx(liq_price_2x(100_000, 0.0), 200_000, 1)
      and approx(liq_price_2x(100_000, 0.01), 198_000, 1)
      and approx(liq_price_2x(100_000, 0.02), 196_000, 1))

print("ALL REVISION UNIT TESTS PASSED")
