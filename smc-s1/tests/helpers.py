"""SMC-S1 共享测试工具：合成 Bar 构造（不读真实数据）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _deps import Bar  # noqa: E402


def mk_bars(spec, start_ms=0, step_ms=900000):
    """spec: [(open, high, low, close), ...] -> list[Bar]（已收盘）。"""
    bars = []
    for i, (o, h, l, c) in enumerate(spec):
        bars.append(Bar(open_time=start_ms + i * step_ms, open=o, high=h,
                        low=l, close=c, volume=0.0,
                        close_time=start_ms + (i + 1) * step_ms - 1))
    return bars
