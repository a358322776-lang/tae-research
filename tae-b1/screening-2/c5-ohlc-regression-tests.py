"""D-ENG-1 OHLC regression tests (branch fix/d-eng-1-ohlc-mapping only).

Usage: python3 c5-ohlc-regression-tests.py
Synthetic data only; never calls main(); EXECUTION_APPROVED must stay
False. The intraday-stop test FAILS on the original code (leg exits
'close' instead of 'stop') and PASSES on the fixed code -- run it
against the main-branch copy to reproduce the defect.
"""

import importlib.util
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))


def _load_fixed():
    spec = importlib.util.spec_from_file_location(
        "c5_fixed", os.path.join(BASE, "c5-exploratory-backtest.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _event(days_eth, funding_offsets):
    entry_ms = None
    c5 = _load_fixed()
    entry_ms = c5.utc_ms(2026, 1, 5) + 2 * 86400000
    bars = {
        "ETHUSDT": {
            "2026-01-04": [2400.0, 2400.0, 2400.0, 2400.0],
            "2026-01-05": [2500.0, 2500.0, 2500.0, 2500.0],
            "2026-01-07": list(days_eth[0]),
            "2026-01-08": list(days_eth[1]),
            "2026-01-09": list(days_eth[2]),
            "2026-01-10": list(days_eth[3]),
        },
        "BTCUSDT": {
            "2026-01-04": [100.0, 100.0, 100.0, 100.0],
            "2026-01-05": [100.1, 100.1, 100.1, 100.1],
            "2026-01-07": [100.0, 101.0, 99.0, 100.0],
            "2026-01-08": [100.0, 101.0, 99.0, 100.0],
            "2026-01-09": [100.0, 101.0, 99.0, 100.0],
            "2026-01-10": [100.0, 101.0, 99.0, 100.0],
        },
    }
    funding = {
        "ETHUSDT": sorted((entry_ms + h * 3600000, r)
                          for h, r in funding_offsets),
        "BTCUSDT": [],
    }
    directions = {("2026-01-05", "TEST", "ETHUSDT"): 1,
                  ("2026-01-05", "TEST", "BTCUSDT"): 1}
    return c5, bars, funding, directions, [("2026-01-05", "TEST")]


def _approx(a, b, tol=1e-12):
    return abs(a - b) <= tol


def test_gate_closed():
    c5 = _load_fixed()
    assert c5.EXECUTION_APPROVED is False, "execution gate must stay closed"
    print("PASS gate-closed")


def test_intraday_stop_via_ohlc():
    # OHLC rows: D+3 true low 2340 breaches stop 2353.8816, high 2420 not.
    # Fixed code must exit 'stop' on day 1 (original code: 'close').
    days = [(2400.0, 2420.0, 2360.0, 2410.0),
            (2410.0, 2420.0, 2340.0, 2400.0),
            (2400.0, 2400.0, 2400.0, 2400.0),
            (2400.0, 2400.0, 2400.0, 2400.0)]
    c5, bars, funding, directions, events = _event(
        days, [(h, 0.0001) for h in range(8, 89, 8)])
    trades, logs = c5.run_tier("central", events, bars, funding, directions)
    assert len(trades) == 1, trades
    leg = [l for l in trades[0]["legs"] if l["symbol"] == "ETHUSDT"][0]
    assert leg["exit_type"] == "stop" and leg["exit_day"] == 1, leg
    assert _approx(leg["entry_px"], 2401.92), leg
    assert _approx(leg["exit_px"], 2351.99849472), leg
    assert _approx(leg["gross"], -0.020784), leg
    assert _approx(leg["net_lo"], -0.022284), leg
    assert _approx(leg["net_hi"], -0.022084), leg
    print("PASS intraday-stop-via-ohlc")


def test_close_exit_via_ohlc():
    days = [(2400.0, 2450.0, 2390.0, 2420.0),
            (2420.0, 2460.0, 2410.0, 2440.0),
            (2440.0, 2480.0, 2430.0, 2470.0),
            (2470.0, 2520.0, 2460.0, 2500.0)]
    c5, bars, funding, directions, events = _event(
        days, [(h, 0.0001) for h in range(8, 89, 8)])
    trades, _ = c5.run_tier("central", events, bars, funding, directions)
    leg = [l for l in trades[0]["legs"] if l["symbol"] == "ETHUSDT"][0]
    assert leg["exit_type"] == "close" and leg["exit_day"] == 3, leg
    assert _approx(leg["exit_px"], 2498.0), leg
    print("PASS close-exit-via-ohlc")


def test_original_passthrough_was_buggy():
    # Reconstruction of the ORIGINAL run_tier boundary: OHLC rows passed
    # positionally into run_leg_prices. Must yield 'close' -- proving
    # this test discriminates (it fails on unfixed code via run_tier).
    c5 = _load_fixed()
    days_ohlc = [(2400.0, 2420.0, 2360.0, 2410.0),
                 (2410.0, 2420.0, 2340.0, 2400.0),
                 (2400.0, 2400.0, 2400.0, 2400.0),
                 (2400.0, 2400.0, 2400.0, 2400.0)]
    got = c5.run_leg_prices(1, 2400.0, days_ohlc, c5.TIERS["central"]["exec"])
    assert got[0] == "close", got
    days_fixed = [c5.ohlc_to_leg_day(r) for r in days_ohlc]
    got2 = c5.run_leg_prices(1, 2400.0, days_fixed, c5.TIERS["central"]["exec"])
    assert got2[0] == "stop", got2
    print("PASS original-passthrough-was-buggy (discrimination check)")


def test_verify_gate_still_passes():
    c5 = _load_fixed()
    assert c5.verify() is True
    print("PASS verify-gate")


def test_helper_rejects_invalid_rows():
    c5 = _load_fixed()
    assert c5.ohlc_to_leg_day([2400.0, 2420.0, 2360.0, 2410.0]) == \
        (2400.0, 2360.0, 2420.0, 2410.0)
    try:
        c5.ohlc_to_leg_day([2400.0, 2350.0, 2360.0, 2410.0])
    except AssertionError:
        print("PASS helper-rejects-invalid-rows")
        return
    raise AssertionError("invalid OHLC row was not rejected")


if __name__ == "__main__":
    test_gate_closed()
    test_intraday_stop_via_ohlc()
    test_close_exit_via_ohlc()
    test_original_passthrough_was_buggy()
    test_verify_gate_still_passes()
    test_helper_rejects_invalid_rows()
    print("\nD-ENG-1 REGRESSION: 6 checks passed, 0 failed.")
