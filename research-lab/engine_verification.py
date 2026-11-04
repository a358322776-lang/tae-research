"""Stage 1 第三项：回测引擎可信度验证（确定性已知答案测试）。

范围（用户 2026-11-04 12:31 授权）：
- 只审计现有 B1、C5 引擎，不得直接认定其可靠。
- 只用人工构造数据 / 固定测试样本验证引擎，不批准正式策略回测。
- 本模块不修改任何冻结代码：B1/C5 源码只读导入；B1 的 Data.__init__
  （加载真实拼接数据）从不实例化，测试用 object.__new__ 构造的合成
  Data 桩；C5 模块只导入不调用 main()，且断言 EXECUTION_APPROVED 为 False。
- 每个已知答案用例：先用独立手算（本模块 ref_*，按规则文字重写，
  不调用引擎内部函数）得出期望值，再调用引擎函数比对，容差 1e-12
  （C5 自身 approx 默认 1e-9；此处更严）。

结论口径：本模块证明的是“单笔交易算术”——入场/出场价、手续费、
滑点、资金费、净 R、权益/回撤在合成数据上与手算一致；不证明任何
策略有效，不证明真实数据路径（B1 真实 Data 加载、C5 真实 bars/
funding 文件）无误。已知局限见验收报告。
"""

import importlib.util
import math
import os

import numpy as np

REPO = os.path.expanduser("~/workspace/tae-research")
B1_PATH = os.path.join(REPO, "tae-b1", "b1_engine.py")
C5_PATH = os.path.join(REPO, "tae-b1", "screening-2",
                       "c5-exploratory-backtest.py")
TOL = 1e-12


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


b1 = _load("b1_engine_under_test", B1_PATH)
c5 = _load("c5_engine_under_test", C5_PATH)

# C5 执行门必须关闭：导入本身绝不能打开任何收益回测。
assert c5.EXECUTION_APPROVED is False, "C5 EXECUTION_APPROVED must be False"


# ---------------------------------------------------------- 独立手算参考
def ref_b1_trade(entry, stop, exit_px, funding_sum, direction):
    """B1 单笔 R 分解的独立重写（规则 P6/P7/P8 文字版）。

    gross = 顺势价差 / risk；fee = 双边 0.05% / (risk/entry)；
    funding：多头付正费率 fsum/sd，空头收正费率 -fsum/sd；
    net = gross - fee - funding。滑点已包含在 exit_px 内，不另加。
    """
    risk = abs(entry - stop)
    sd = risk / entry
    if direction == "long":
        gross = (exit_px - entry) / risk
    else:
        gross = (entry - exit_px) / risk
    fee = 2 * 0.0005 / sd
    funding = funding_sum / sd if direction == "long" else -funding_sum / sd
    return {"gross": gross, "fee": fee, "funding": funding,
            "net": gross - fee - funding}


def ref_stats(nets):
    """stats_for 的独立重写：累计曲线、峰值、最大回撤（负值表示深度）。"""
    curve, peak, dd = 0.0, 0.0, 0.0
    for x in nets:
        curve += x
        peak = max(peak, curve)
        dd = min(dd, curve - peak)
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x < 0]
    gp, gl = sum(wins), abs(sum(losses))
    return {"n": len(nets), "wins": len(wins),
            "win_rate": len(wins) / len(nets),
            "avg_net": sum(nets) / len(nets), "total_net": sum(nets),
            "max_dd": dd,
            "profit_factor": gp / gl if gl > 0 else math.inf}


def ref_c5_leg(entry_open, direction, days, exec_cost):
    """C5 单腿价格力学的独立重写（冻结稿 v0.8 文字版）。

    entry = open*(1+dir*exec)；stop = entry*(1-dir*2%)；
    i>0 日开盘穿止损先判 gap；日内 low/high 穿止损判 stop；
    最后一日收盘出场。返回 (exit_type, day_idx, entry_px, exit_px, gross)。
    """
    entry_px = entry_open * (1 + direction * exec_cost)
    stop = entry_px * (1 - direction * 0.02)
    for i, (o, low, high, c) in enumerate(days):
        if i > 0:
            if direction == 1 and o <= stop:
                px = o * (1 - exec_cost)
                return ("stop-gap", i, entry_px, px,
                        (px - entry_px) / entry_px)
            if direction == -1 and o >= stop:
                px = o * (1 + exec_cost)
                return ("stop-gap", i, entry_px, px,
                        (entry_px - px) / entry_px)
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


# ---------------------------------------------------------- 合成数据构造
def fake_b1_data(fund_ts, fund_rates):
    """合成 B1 Data 桩：只含 funding_sum 所需的 fund_ts/fund_pre。"""
    D = object.__new__(b1.Data)
    D.fund_ts = list(fund_ts)
    D.fund_pre = np.cumsum([0.0] + list(fund_rates))
    return D


def synthetic_b1_bars(stop_low=None, exit_close=None):
    """合成 B1 15m/5m 桩（价格 2400 附近）。

    15m 6 根（open 0 起每 900_000ms），5m 18 根（每 300_000ms）。
    fill 在 5m 下标 4（t=1_200_000，属 15m bar 1）。
    stop_low：5m 下标 6 的 low（触发止损用）；exit_close：15m 下标 2
    的 close（EMA 出场用）。其余 5m low 均为 2390，高于止损阈值。
    """
    D = object.__new__(b1.Data)
    t15 = np.array([i * 900_000 for i in range(6)], dtype=np.int64)
    closes = [2400.0, 2400.0,
              2400.0 if exit_close is None else float(exit_close),
              2400.0, 2400.0, 2400.0]
    o15 = np.array([[2400.0, 2410.0, 2390.0, c] for c in closes], dtype=float)
    t5 = np.array([i * 300_000 for i in range(18)], dtype=np.int64)
    o5 = np.tile(np.array([2400.0, 2410.0, 2390.0, 2400.0]), (18, 1))
    if stop_low is not None:
        o5[6] = [2400.0, 2410.0, float(stop_low), 2400.0]
    D.t15, D.o15, D.t5, D.o5 = t15, o15, t5, o5
    D.c15 = o15[:, 3]
    D.ema50 = np.full(6, 2400.0)
    D.sma20 = np.full(6, 2400.0)
    # 资金费：两笔 0.0001，结算点 1_500_000 / 1_800_000，
    # 均在 (fill_open=1_200_000, exit_close=2_100_000] 内，和为 0.0002。
    D.fund_ts = [1_500_000, 1_800_000]
    D.fund_pre = np.cumsum([0.0, 0.0001, 0.0001])
    return D


def b1_entry(direction="long", entry=2400.0, stop=2352.0):
    return {"dir": direction, "entry": float(entry), "stop": float(stop),
            "risk": abs(float(entry) - float(stop)), "fill_idx": 4,
            "fill_open_ms": 1_200_000}


# C5 合成事件：2026-01-05 事件，ETH 做多、BTC 因波动不足不交易。
C5_EVENT = ("2026-01-05", "TEST")
C5_DAYS_STOP = [(2400.0, 2360.0, 2420.0, 2410.0),
                (2410.0, 2350.0, 2420.0, 2400.0),
                (2400.0, 2400.0, 2400.0, 2400.0),
                (2400.0, 2400.0, 2400.0, 2400.0)]


def c5_bars_funding(days_eth, funding_rates_eth):
    """返回 (bars, funding, directions, events)；funding 用绝对 ms。

    bars 行是标准 OHLC [open, high, low, close]（valid_bar 与真实
    数据文件的约定）。注意：run_leg_prices 按 (open, low, high, close)
    解包同一行，见 test_c5_high_low_swap_known_defect。
    entry_ms = utc_ms(2026,1,5) + 2d；funding_rates_eth 为
    [(offset_hours, rate), ...]，offset 相对 entry_ms。
    """
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
                          for h, r in funding_rates_eth),
        "BTCUSDT": [],
    }
    directions = {("2026-01-05", "TEST", "ETHUSDT"): 1,
                  ("2026-01-05", "TEST", "BTCUSDT"): 1}
    return bars, funding, directions, [C5_EVENT]
