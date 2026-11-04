"""引擎可信度验证测试：全部合成数据，零真实策略回测。

用法：python3 test_engine_verification.py
每个用例先写出手算期望值（注释内逐步推导），再调用引擎比对。
手算数值的推导（美元换算仅用于说明，引擎原生单位是 R）：
- B1 已知交易：多头 ETH，entry 2400，stop 2352，risk 48，sd=0.02。
  止损成交价 = 2352*(1-0.0005) = 2350.824；
  gross = (2350.824-2400)/48 = -1.0245R；
  fee = 2*0.0005/0.02 = 0.05R；
  funding 和 0.0002 -> 0.0002/0.02 = 0.01R；
  net = -1.0245-0.05-0.01 = -1.0845R。
  按 B1 仓位公式 1R = 本金 2%：$1000 本金下净亏 $21.69。
- C5 已知交易（central 档，exec=0.0008）：多头 ETH，D+2 open 2400。
  entry = 2400*1.0008 = 2401.92；stop = 2401.92*0.98 = 2353.8816；
  止损成交价 = 2353.8816*0.9992 = 2351.99849472；
  gross = (2351.99849472-2401.92)/2401.92 = -0.020784；
  资金费区间 (0.0003, 0.0005) -> net_lo = -0.020784-0.001-0.0005
  = -0.022284，net_hi = -0.020784-0.001-0.0003 = -0.022084。
"""

import math
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from engine_verification import (  # noqa: E402
    b1, c5, TOL, ref_b1_trade, ref_stats, ref_c5_leg,
    fake_b1_data, synthetic_b1_bars, b1_entry,
    c5_bars_funding, C5_DAYS_STOP,
)

PASSED = []


def check(name, cond, detail=""):
    assert cond, f"{name} FAILED: {detail}"
    PASSED.append(name)
    print(f"PASS {name}")


def approx(a, b, tol=TOL):
    return abs(a - b) <= tol


# --------------------------------------------------------------- B1
def test_b1_known_trade_stop_exit():
    D = synthetic_b1_bars(stop_low=2350.0)
    e = b1_entry()
    out = b1.simulate_exit(D, e, "T0", "EMA50")
    check("b1-stop-exit", out is not None and out["reason"] == "stop"
          and approx(out["exit_px"], 2350.824)
          and out["exit_close_ms"] == 2_100_000, str(out))
    nums = b1.trade_numbers(D, e, out)
    ref = ref_b1_trade(2400.0, 2352.0, 2350.824, 0.0002, "long")
    check("b1-known-net", approx(nums["gross"], -1.0245)
          and approx(nums["fee"], 0.05)
          and approx(nums["funding"], 0.01)
          and approx(nums["net"], -1.0845), str(nums))
    check("b1-known-ref-agree", all(approx(nums[k], ref[k]) for k in ref),
          f"engine={nums} ref={ref}")
    # 美元换算（推导见模块注释）：1R = $1000 本金的 2% = $20。
    check("b1-known-dollars", approx(nums["net"] * 20, -21.69, 1e-9),
          str(nums["net"] * 20))
    # 止损档 T1/T2 只改触发时机不改成交价公式（P6）：low 2350 时 T2
    # 阈值 2349.648 未触发、返回 None 是正确的档位敏感性；low 压到
    # 2349 时三档均触发且成交价相同。
    out_t1 = b1.simulate_exit(D, e, "T1", "EMA50")
    check("b1-stop-exit-T1", out_t1 == out, str(out_t1))
    check("b1-stop-tier-sensitivity",
          b1.simulate_exit(D, e, "T2", "EMA50") is None,
          "T2 thr 2349.648 must not trigger on low 2350")
    D2 = synthetic_b1_bars(stop_low=2349.0)
    outs = [b1.simulate_exit(D2, e, t, "EMA50") for t in ("T0", "T1", "T2")]
    check("b1-stop-price-tier-invariant",
          all(o is not None and o["reason"] == "stop"
              and approx(o["exit_px"], 2350.824) for o in outs), str(outs))


def test_b1_funding_window_boundaries():
    # 结算点 (t0, t1]：恰在 t0 的排除、恰在 t1 的计入。
    D = fake_b1_data([1000, 2000, 3000], [0.0001, 0.0002, 0.0004])
    check("b1-funding-half-open",
          approx(D.funding_sum(1000, 3000), 0.0006)
          and approx(D.funding_sum(1000, 2000), 0.0002)
          and approx(D.funding_sum(3000, 3000), 0.0)
          and approx(D.funding_sum(0, 1000), 0.0001)
          and approx(D.funding_sum(0, 999), 0.0),
          "boundary semantics wrong")


def test_b1_fee_scales_with_stop_distance():
    # 止损减半（risk 24，sd=0.01）时 fee_r 翻倍：0.001/0.01=0.1R。
    D = fake_b1_data([], [])
    e = b1_entry(entry=2400.0, stop=2376.0)
    out = {"exit_px": 2376.0 * 0.9995, "exit_close_ms": 2_100_000}
    nums = b1.trade_numbers(D, e, out)
    check("b1-fee-scales", approx(nums["fee"], 0.1)
          and approx(nums["gross"], (2374.812 - 2400.0) / 24.0)
          and approx(nums["net"], (2374.812 - 2400.0) / 24.0 - 0.1),
          str(nums))


def test_b1_short_trade_negative_funding():
    # 空头，负费率和 -0.0002：空头为负费率付费，成本 +0.01R。
    D = fake_b1_data([1_500_000], [-0.0002])
    e = b1_entry(direction="short", entry=2400.0, stop=2448.0)
    out = {"exit_px": 2448.0 * 1.0005, "exit_close_ms": 2_100_000}
    nums = b1.trade_numbers(D, e, out)
    ref = ref_b1_trade(2400.0, 2448.0, 2449.224, -0.0002, "short")
    check("b1-short", approx(nums["gross"], -1.0255)
          and approx(nums["fee"], 0.05)
          and approx(nums["funding"], 0.01)
          and approx(nums["net"], -1.0855)
          and all(approx(nums[k], ref[k]) for k in ref), str(nums))


def test_b1_ema_exit_uses_close():
    # EMA 出场：成交价即收盘价（P7：只计 taker 费，不另扣滑点）。
    # 这是规则本身的乐观假设，测试只证明引擎如实执行了它。
    D = synthetic_b1_bars(exit_close=2399.0)
    e = b1_entry()
    out = b1.simulate_exit(D, e, "T0", "EMA50")
    check("b1-ema-exit", out["reason"] == "EMA50"
          and approx(out["exit_px"], 2399.0)
          and out["exit_close_ms"] == 2_700_000, str(out))
    D.fund_ts, D.fund_pre = [], __import__("numpy").array([0.0])
    nums = b1.trade_numbers(D, e, out)
    check("b1-ema-numbers", approx(nums["gross"], -1.0 / 48.0)
          and approx(nums["fee"], 0.05)
          and approx(nums["funding"], 0.0)
          and approx(nums["net"], -1.0 / 48.0 - 0.05), str(nums))


def test_b1_stats_known_sequence():
    nets = [0.5, -1.0845, 0.3]
    got = b1.stats_for(nets)
    ref = ref_stats(nets)
    check("b1-stats", got["n"] == 3 and got["wins"] == 2
          and approx(got["win_rate"], 2 / 3)
          and approx(got["total_net"], -0.2845)
          and approx(got["avg_net"], -0.2845 / 3)
          and approx(got["max_dd"], -1.0845)
          and approx(got["profit_factor"], 0.8 / 1.0845),
          str(got))
    check("b1-stats-ref-agree",
          all(approx(got[k], ref[k]) for k in
              ("win_rate", "total_net", "avg_net", "max_dd",
               "profit_factor")), f"engine={got} ref={ref}")
    check("b1-stats-empty", b1.stats_for([]) == {"n": 0},
          str(b1.stats_for([])))
    all_win = b1.stats_for([1.0, 2.0])
    check("b1-stats-all-win", all_win["profit_factor"] == math.inf
          and approx(all_win["max_dd"], 0.0), str(all_win))


def test_b1_reproducibility_and_no_lookahead():
    D = synthetic_b1_bars(stop_low=2350.0)
    e = b1_entry()
    out1 = b1.simulate_exit(D, e, "T0", "EMA50")
    out2 = b1.simulate_exit(D, e, "T0", "EMA50")
    n1 = b1.trade_numbers(D, e, out1)
    n2 = b1.trade_numbers(D, e, out2)
    check("b1-reproducible", out1 == out2 and n1 == n2, "not deterministic")
    # 出场后追加未来 bars 不改变已触发的出场（行为级无未来泄漏）。
    import numpy as np
    D2 = synthetic_b1_bars(stop_low=2350.0)
    D2.t15 = np.concatenate([D2.t15, [5_400_000, 6_300_000]])
    D2.o15 = np.concatenate([D2.o15, [[2000.0, 2000.0, 2000.0, 2000.0]] * 2])
    D2.c15 = D2.o15[:, 3]
    D2.ema50 = np.concatenate([D2.ema50, [2000.0, 2000.0]])
    D2.sma20 = np.concatenate([D2.sma20, [2000.0, 2000.0]])
    out3 = b1.simulate_exit(D2, e, "T0", "EMA50")
    check("b1-no-lookahead", out3 == out1, f"{out3} vs {out1}")


# --------------------------------------------------------------- C5
def test_c5_known_leg_central():
    ex = c5.TIERS["central"]["exec"]
    got = c5.run_leg_prices(1, 2400.0, C5_DAYS_STOP, ex)
    ref = ref_c5_leg(2400.0, 1, C5_DAYS_STOP, ex)
    check("c5-known-leg", got[0] == "stop" and got[1] == 1
          and approx(got[2], 2401.92) and approx(got[3], 2351.99849472)
          and approx(got[4], -0.020784), str(got))
    check("c5-known-leg-ref", got == ref, f"engine={got} ref={ref}")
    # 空头对照：entry=2398.08，stop=2446.0416，day1 high 穿止损。
    days_s = [(2400.0, 2380.0, 2420.0, 2410.0),
              (2410.0, 2400.0, 2450.0, 2400.0),
              (2400.0, 2400.0, 2400.0, 2400.0),
              (2400.0, 2400.0, 2400.0, 2400.0)]
    got_s = c5.run_leg_prices(-1, 2400.0, days_s, ex)
    ref_s = ref_c5_leg(2400.0, -1, days_s, ex)
    check("c5-short-leg", got_s[0] == "stop" and got_s[1] == 1
          and approx(got_s[2], 2398.08, 1e-9)
          and approx(got_s[3], 2446.0416 * 1.0008, 1e-9)
          and got_s == ref_s, str(got_s))
    # 追加未来日不改变已出场腿的结果（行为级无未来泄漏）。
    longer = list(C5_DAYS_STOP) + [(100.0, 50.0, 150.0, 100.0)]
    check("c5-no-lookahead",
          c5.run_leg_prices(1, 2400.0, longer, ex) == got, "future leaked")


def test_c5_funding_close_and_stop():
    # close 窗口为 (entry, entry+4d]，覆盖须无 >24h 缺口：用 8h 步长
    # 8..88h 共 11 笔，精确和 0.0011。
    std_close = [(h * 3600000, 0.0001) for h in range(8, 89, 8)]
    kind, v = c5.funding_for_leg(std_close, 0, "close", 3)
    check("c5-funding-close", kind == "exact" and approx(v, 0.0011),
          f"{kind} {v}")
    std = [(h * 3600000, 0.0001) for h in (8, 16, 24, 32, 40)]
    kind, lo, hi = c5.funding_for_leg(std, 0, "stop", 1)
    check("c5-funding-stop", kind == "interval"
          and approx(lo, 0.0003) and approx(hi, 0.0005), f"{kind} {lo} {hi}")
    mixed = [(8 * 3600000, 0.0001), (16 * 3600000, 0.0001),
             (24 * 3600000, 0.0001), (32 * 3600000, -0.0005),
             (40 * 3600000, 0.0001)]
    kind, lo, hi = c5.funding_for_leg(mixed, 0, "stop", 1)
    check("c5-funding-mixed-sign", kind == "interval"
          and approx(lo, -0.0002) and approx(hi, 0.0003),
          f"{kind} {lo} {hi}")
    gapped = [(8 * 3600000, 0.0001), (40 * 3600000, 0.0001)]
    check("c5-funding-gap", c5.funding_for_leg(gapped, 0, "close", 3) is None,
          "gap >24h must return None")
    # close 窗口外追加记录不改变和（行为级无未来泄漏）。
    extended = std_close + [(200 * 3600000, 0.0099)]
    check("c5-funding-no-lookahead",
          c5.funding_for_leg(extended, 0, "close", 3) == ("exact", 0.0011),
          "future funding leaked")


def test_c5_tier_single_eth_trade():
    # 用 stop-gap 触发（只看开盘价，与 high/low 顺序无关），避免触及
    # 下面单独记录的 high/low 换位缺陷。OHLC 行：D+2 [2400,2420,2360,
    # 2410]，D+3 开盘 2350 <= stop 2353.8816 -> stop-gap。
    # exit = 2350*0.9992 = 2348.12；gross = (2348.12-2401.92)/2401.92
    # = -0.02239874766853173；net_lo = gross-0.001-0.0005，
    # net_hi = gross-0.001-0.0003。
    days_gap = [(2400.0, 2420.0, 2360.0, 2410.0),
                (2350.0, 2420.0, 2340.0, 2400.0),
                (2400.0, 2400.0, 2400.0, 2400.0),
                (2400.0, 2400.0, 2400.0, 2400.0)]
    bars, funding, directions, events = c5_bars_funding(
        days_gap, [(h, 0.0001) for h in (8, 16, 24, 32, 40)])
    trades, logs = c5.run_tier("central", events, bars, funding, directions)
    check("c5-tier-one-trade", len(trades) == 1, str(trades))
    t = trades[0]
    exp_gross = (2350.0 * 0.9992 - 2401.92) / 2401.92
    check("c5-tier-leg", len(t["legs"]) == 1
          and t["legs"][0]["symbol"] == "ETHUSDT"
          and t["legs"][0]["exit_type"] == "stop-gap"
          and t["legs"][0]["exit_day"] == 1
          and approx(t["legs"][0]["entry_px"], 2401.92)
          and approx(t["legs"][0]["exit_px"], 2348.12)
          and approx(t["legs"][0]["gross"], exp_gross)
          and approx(t["legs"][0]["fund_lo"], 0.0003)
          and approx(t["legs"][0]["fund_hi"], 0.0005)
          and approx(t["legs"][0]["net_lo"], exp_gross - 0.001 - 0.0005)
          and approx(t["legs"][0]["net_hi"], exp_gross - 0.001 - 0.0003),
          str(t))
    check("c5-tier-nets", approx(t["net_lo"], -0.02389874766853173)
          and approx(t["net_hi"], -0.023698747668531733)
          and approx(t["contrib_lo"], 0.10 * -0.02389874766853173)
          and approx(t["contrib_hi"], 0.10 * -0.023698747668531733), str(t))
    check("c5-tier-btc-no-trade",
          any(l[2] == "BTCUSDT" for l in logs["no_trade"]), str(logs))
    # 同输入再跑一次，结果完全一致。
    trades2, _ = c5.run_tier("central", events, bars, funding, directions)
    check("c5-tier-reproducible", trades2 == trades, "not deterministic")


def test_c5_high_low_swap_known_defect():
    """已知缺陷 D-ENG-1（未修复，冻结代码零触摸、修复须另批）：

    真实数据行是标准 OHLC [o, high, low, c]（valid_bar 亦按此校验），
    但 run_tier 把同一行原样传给 run_leg_prices，后者按
    (o, low, high, c) 解包：high/low 被互换。
    后果：多头止损在 high<=stop 才触发（应为 low<=stop），空头在
    low>=stop 才触发（应为 high>=stop）——止损触发是正确规则的子集，
    引擎跑的不是冻结稿写明的止损规则。verify() 的 e2e 门测不到它，
    因为 e2e 直接用 (o, low, high, c) 元组调用，两边约定一致。
    本用例把当前（错误）行为钉住：真 low 穿止损而 high 未穿时，
    引擎走到 close；同一日按 (o, low, high, c) 重排后引擎判 stop。
    修复后本用例必须改写，不得悄悄调期望值蒙混。
    """
    ex = c5.TIERS["central"]["exec"]
    # 真实 OHLC 日：low 2340 穿 stop，high 2420 未穿。
    ohlc_days = [(2400.0, 2420.0, 2360.0, 2410.0),
                 (2410.0, 2420.0, 2340.0, 2400.0),
                 (2400.0, 2400.0, 2400.0, 2400.0),
                 (2400.0, 2400.0, 2400.0, 2400.0)]
    got_ohlc = c5.run_leg_prices(1, 2400.0, ohlc_days, ex)
    check("c5-swap-defect-pinned", got_ohlc[0] == "close",
          f"expected current buggy 'close', got {got_ohlc}")
    # 同一日按腿函数约定 (o, low, high, c) 重排：判 stop。
    olhc_days = [(2400.0, 2360.0, 2420.0, 2410.0),
                 (2410.0, 2340.0, 2420.0, 2400.0),
                 (2400.0, 2400.0, 2400.0, 2400.0),
                 (2400.0, 2400.0, 2400.0, 2400.0)]
    got_olhc = c5.run_leg_prices(1, 2400.0, olhc_days, ex)
    check("c5-swap-cause", got_olhc[0] == "stop" and got_olhc[1] == 1,
          f"reordered day must stop, got {got_olhc}")
    # 经 run_tier（真实 OHLC 路径）同样走到 close，证实缺陷在数据边界。
    bars, funding, directions, events = c5_bars_funding(
        ohlc_days, [(h, 0.0001) for h in range(8, 89, 8)])
    trades, _ = c5.run_tier("central", events, bars, funding, directions)
    check("c5-swap-via-tier",
          len(trades) == 1 and trades[0]["legs"][0]["exit_type"] == "close",
          str(trades))


def test_c5_tier_close_exit():
    # OHLC 行；收盘出场只看 close，与 high/low 顺序无关。
    days = [(2400.0, 2450.0, 2390.0, 2420.0),
            (2420.0, 2460.0, 2410.0, 2440.0),
            (2440.0, 2480.0, 2430.0, 2470.0),
            (2470.0, 2520.0, 2460.0, 2500.0)]
    bars, funding, directions, events = c5_bars_funding(
        days, [(h, 0.0001) for h in range(8, 89, 8)])
    trades, _ = c5.run_tier("central", events, bars, funding, directions)
    leg = trades[0]["legs"][0]
    exp_gross = (2498.0 - 2401.92) / 2401.92
    check("c5-close-exit", leg["exit_type"] == "close"
          and leg["exit_day"] == 3
          and approx(leg["exit_px"], 2498.0)
          and approx(leg["gross"], exp_gross)
          and approx(leg["net_lo"], exp_gross - 0.001 - 0.0011)
          and approx(leg["net_hi"], exp_gross - 0.001 - 0.0011),
          str(leg))


def test_c5_build_equity_single_leg():
    # 单腿 day0 出场：出场后权益恒为 1+0.10*net；回撤 = 峰值 1.0 之差。
    leg = {"symbol": "ETHUSDT", "direction": 1, "exit_day": 0,
           "entry_px": 2400.0, "net_lo": -0.05, "net_hi": -0.04}
    trades = [{"date": "2026-01-05", "series": "TEST", "legs": [leg]}]
    # build_equity 只在 bars 有该日时才计入该腿：须铺满入场日到
    # 2026-10-30 的全部日期（真实数据本就全覆盖），否则出场后权益
    # 会在缺日上回落到 1.0。
    from datetime import date as _date, timedelta as _td
    bars = {"ETHUSDT": {}}
    _cur = _date(2026, 1, 7)
    while _cur <= _date(2026, 10, 30):
        bars["ETHUSDT"][_cur.isoformat()] = [2400.0, 2400.0, 2400.0, 2400.0]
        _cur += _td(days=1)
    eq = c5.build_equity(trades, bars, {"ETHUSDT": []})
    check("c5-equity", approx(eq["final_lo"], 0.995)
          and approx(eq["final_hi"], 0.996)
          and approx(eq["mdd_lo_cost_curve"], 0.005)
          and approx(eq["mdd_hi_cost_curve"], 0.004), str(eq))


def test_c5_constants_and_gate():
    check("c5-constants", approx(c5.TIERS["central"]["exec"], 0.0008)
          and approx(c5.TIERS["central"]["roundtrip"], 0.0026)
          and approx(c5.FEE_RT, 0.001) and approx(c5.STOP_PCT, 0.02),
          str(c5.TIERS))
    check("c5-execution-gate-closed", c5.EXECUTION_APPROVED is False,
          "gate must stay False")
    check("c5-verify-gate", c5.verify() is True, "own e2e gate failed")


if __name__ == "__main__":
    test_b1_known_trade_stop_exit()
    test_b1_funding_window_boundaries()
    test_b1_fee_scales_with_stop_distance()
    test_b1_short_trade_negative_funding()
    test_b1_ema_exit_uses_close()
    test_b1_stats_known_sequence()
    test_b1_reproducibility_and_no_lookahead()
    test_c5_known_leg_central()
    test_c5_funding_close_and_stop()
    test_c5_tier_single_eth_trade()
    test_c5_high_low_swap_known_defect()
    test_c5_tier_close_exit()
    test_c5_build_equity_single_leg()
    test_c5_constants_and_gate()
    print(f"\nENGINE VERIFICATION: {len(PASSED)} checks passed, 0 failed.")
