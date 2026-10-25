"""TAE-B1 引擎单元测试（合成数据，只测逻辑，不跑回测）。
用法：python3 test_b1_engine.py
"""
import sys

import numpy as np

sys.path.insert(0, "/home/hatch/workspace/goals/100u-200u/files/tae-b1")
from b1_engine import simulate_exit, Data  # noqa: E402
from b1_lib import hammer, is_signal_bar  # noqa: E402

# ---- 形态 ----
assert hammer(np.array([100.0, 110.0, 90.0, 100.0])) is True  # body=0, lower=10 -> B 计入
assert hammer(np.array([100.0, 110.0, 90.0, 100.0]), fix_doji=True) is False  # C 排除
assert hammer(np.array([100.0, 105.0, 90.0, 102.0])) is True  # body=2, lower=12>=4, 2<=0.3*15
assert hammer(np.array([100.0, 105.0, 98.0, 102.0])) is False  # lower=2 < 2*body=4
print("patterns ok")


def stub_data():
    """合成：15m 10 根（open 从 0 起每 900000），5m 30 根，1h 不用。"""
    D = object.__new__(Data)
    t15 = np.array([i * 900_000 for i in range(10)], dtype=np.int64)
    # o,h,l,c：价格 100 附近，bar5 收盘跌破 EMA 做空头测试用
    o15 = np.array([
        [100, 101, 99, 100], [100, 102, 100, 101], [101, 103, 101, 102],
        [102, 104, 102, 103], [103, 105, 103, 104], [104, 104, 95, 96],
        [96, 97, 95, 96], [96, 98, 96, 97], [97, 99, 97, 98], [98, 100, 98, 99],
    ], dtype=float)
    t5 = np.array([i * 300_000 for i in range(30)], dtype=np.int64)
    o5 = np.tile(np.array([100, 101, 99, 100], dtype=float), (30, 1))
    D.t15, D.o15, D.t5, D.o5 = t15, o15, t5, o5
    D.c15 = o15[:, 3]
    D.ema50 = np.array([np.nan] * 5 + [100.0] * 5)
    D.sma20 = np.array([np.nan] * 5 + [100.0] * 5)
    D.fund_ts, D.fund_pre = [], np.array([0.0])
    return D


D = stub_data()
# 止损触发：long，stop=98，fill 在 5m bar 1（属 15m bar 0），5m bar 4 的 low 改为 97 -> T0 止损
D.o5[4] = [100, 101, 97, 100]
e = {"dir": "long", "stop": 98.0, "fill_idx": 1}
out = simulate_exit(D, e, "T0", "EMA50")
assert out is not None and out["reason"] == "stop", out
assert abs(out["exit_px"] - 98.0 * (1 - 0.0005)) < 1e-9, out
print("stop exit ok:", out)
# T2 穿透 0.1%：low 97 <= 98*(1-0.001)=97.902 -> 同样触发
out2 = simulate_exit(D, e, "T2", "EMA50")
assert out2 is not None and out2["reason"] == "stop", out2
# T1 且 low 只到 97.95（>97.951? no: 98*(1-0.0005)=97.951；97.95<=97.951 触发；改 97.96 不触发）
D.o5[4] = [100, 101, 97.96, 100]
out3 = simulate_exit(D, e, "T1", "EMA50")
assert out3 is not None and out3["reason"] == "EMA50", out3  # 15m bar5 收盘 96 < EMA100 -> EMA 出场
print("tier gating + EMA exit ok:", out3)
# 同根止损优先：5m bar 16（属 15m bar 5）low 触及止损，且 15m bar5 收盘破 EMA -> 应为止损
D.o5[16] = [96, 97, 90, 96]
e2 = {"dir": "long", "stop": 95.0, "fill_idx": 14}  # fill 在 5m bar14（属 15m bar4）
out4 = simulate_exit(D, e2, "T0", "EMA50")
assert out4 is not None and out4["reason"] == "stop", out4
print("stop-first-in-bar ok:", out4)
print("ALL ENGINE TESTS PASSED")
