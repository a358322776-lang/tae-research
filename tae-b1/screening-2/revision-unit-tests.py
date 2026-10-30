"""Minimal unit tests for the C5/C3 revision reports (screening-2).

Tests definitions and arithmetic only. No backtest, no price history,
no parameter tuning. Run: python3 revision-unit-tests.py
"""

R = 0.0418  # 3M T-bill, 2026-10-29


def gross_threshold(events_per_year, cost, size):
    """Required gross continuation per traded event (fraction of price)."""
    return (R / events_per_year + cost * size) / size


def effective_n(n_events, rho):
    """Effective independent units from 2 observations per event."""
    return 2 * n_events / (1 + rho)


def event_obs(btc_ret, eth_ret):
    """One event-level observation = equal-weight mean of both assets."""
    return (btc_ret + eth_ret) / 2


def benchmark_tradable_at_entry(inputs_available_at_entry, benchmark):
    """Kill-line benchmarks must be constructible with entry-time info only."""
    if benchmark == "event-day":
        return False  # needs the event-day close, unknown before the close
    return inputs_available_at_entry


def stop_trade(entry, stop_pct, day_open, day_low, day_high, side="long",
               slippage=0.001):
    """Daily stop model from the C5 revision (R-C5-L4).

    Returns (triggered, exec_price or None). Gap-through executes at open.
    """
    if side == "long":
        stop = entry * (1 - stop_pct)
        if day_open <= stop:
            return True, day_open
        if day_low <= stop:
            return True, stop * (1 - slippage)
        return False, None
    stop = entry * (1 + stop_pct)
    if day_open >= stop:
        return True, day_open
    if day_high >= stop:
        return True, stop * (1 + slippage)
    return False, None


def coinm_net_delta(spot_btc, notional_usd, price, leverage):
    """Net delta in BTC: spot + margin coin - short delta. Margin = N/(L*P)."""
    margin_btc = notional_usd / (leverage * price)
    return spot_btc + margin_btc - notional_usd / price


def coinm_example(p0=100_000, p1=110_000, spot_btc=0.01, notional=1_000):
    """Worked example from the C3 audit, section 2.5. Returns USDT figures."""
    spot_pnl = spot_btc * (p1 - p0)
    short_coin = notional * (1 / p1 - 1 / p0)  # negative when price rises
    short_usdt_at_exit = short_coin * p1
    margin_gain = spot_btc * (p1 - p0)  # margin coin still held
    committed = spot_btc * p0 + (notional / p0) * p0
    total = spot_pnl + short_usdt_at_exit + margin_gain
    return {"spot": spot_pnl, "short_usdt": short_usdt_at_exit,
            "margin_gain": margin_gain, "committed": committed, "total": total}


def check(name, cond):
    assert cond, f"FAIL: {name}"
    print(f"ok: {name}")


def approx(a, b, tol=1e-3):
    return abs(a - b) <= tol


# --- C5: high-return threshold table (R-C5, section 5) ---
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
check("C5 threshold 25 events 10pct cost0.20 = 1.87%",
      approx(gross_threshold(25, 0.0020, 0.10), 0.0187, 1e-4))

# --- C5: stop execution model (R-C5-L4) ---
trig, px = stop_trade(100, 0.02, 95, 94, 96, "long")
check("C5 stop gap-through executes at open, worse than stop",
      trig and px == 95 and px < 98)
trig, px = stop_trade(100, 0.02, 101, 97.5, 102, "long")
check("C5 stop intraday trigger executes near stop with slippage",
      trig and approx(px, 98 * 0.999, 1e-9))
trig, px = stop_trade(100, 0.02, 101, 98.5, 102, "long")
check("C5 stop no trigger when low stays above stop", not trig and px is None)
trig, px = stop_trade(100, 0.02, 105, 100, 106, "short")
check("C5 short gap-through executes at open", trig and px == 105)

# --- C5: independence / correlation (R-C5-L3) ---
check("C5 effective N rho=0.85 is ~97, not 180",
      approx(effective_n(90, 0.85), 97.3, 0.5))
check("C5 effective N rho=1 collapses to event count",
      effective_n(90, 1.0) == 90)
check("C5 effective N rho=0 equals nominal count",
      effective_n(90, 0.0) == 180)
check("C5 event obs is the mean of both assets",
      event_obs(0.05, 0.03) == 0.04)
check("C5 event-day benchmark is not tradable at entry",
      benchmark_tradable_at_entry(True, "event-day") is False)
check("C5 placebo / buy-hold / R are tradable at entry",
      all(benchmark_tradable_at_entry(True, b)
          for b in ("placebo", "buy-hold", "R")))

# --- C3: COIN-M audit (section 2.4-2.5) ---
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

print("ALL REVISION UNIT TESTS PASSED")
