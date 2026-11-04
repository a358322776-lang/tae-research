"""SMC-S1 冻结配置 v1.0（第一批）。

全部参数为任务书 v1.0 + 批复 D1–D6 的冻结值。配置不可变；
任何改动须新版本 + 重新登记，不得静默调参。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SMCConfig:
    version: str = "smc-s1-v1.0"
    symbol: str = "ETHUSDT"
    # 结构
    pivot_left: int = 2
    pivot_right: int = 2
    # ATR（D1）：15m ATR(14)，Wilder RMA，仅收盘后可用
    atr_period: int = 14
    atr_method: str = "wilder_rma"
    atr_timeframe: str = "15m"
    # BOS / FVG
    bos_min_atr: float = 0.1
    fvg_min_atr: float = 0.2
    fvg_entry_pct: float = 0.5
    bos_fvg_max_bars: int = 3
    order_max_wait_bars: int = 8
    # 风险
    stop_min_atr: float = 0.5
    stop_max_atr: float = 3.0
    target_r: float = 2.0
    max_open_orders: int = 1
    # 执行（D2）：5m 代理成交模型，保留 1m 适配接口
    fill_timeframe: str = "5m"
    proxy_fill: bool = True
    # 切分（D4）
    split_fractions: tuple = (0.50, 0.20, 0.30)
    # 评估门（D5）
    min_trades_no_screening: int = 100
    min_trades_formal: int = 200


DEFAULT_CONFIG = SMCConfig()
