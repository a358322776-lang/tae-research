# ETH v4.1 稳健性验证 —— 交付物说明

> 规则冻结声明：本目录所有脚本复用 v4.1 原规则（`hidden_files/backtest-v4-eth-unified.py`
> 的统一入场 + `key_levels`/`key_signals`/`tae-scanner-tradfi` 原模块），未修改任何
> 入场、止损、出场、冷却参数；未改动扫描器、执行器与任何 live 配置；未向 GitHub 推送。

## 复现方法

依赖：Python 3.10+、numpy（已验证 1.26）。数据来自币安公开镜像
`https://www.binance.com/fapi/v1/klines` 与 `.../fapi/v1/fundingRate`
（与原回测脚本同一通道；已收盘 K 线历史不可变，重取即重现）。

```bash
# 数据缓存统一放在 data_cache/（工作区内持久化；/tmp 会在 VM 重启时清空，
# 2026-10-25 实测一次重启丢过全部 /tmp 缓存，故不用 /tmp）
# 1. 取数（样本外 2020-01-01→2025-10-17T02:00Z；样本内 2025-10-17→2026-10-22T02:00Z）
python3 fetch_data.py --out data_cache

# 2. 校验 numpy 移植与原模块逐项一致（须 0 失败）
python3 validate_helpers.py

# 3. 样本内复现门（须 46 单；T0 净 0.506/23.28、T1 0.0771/2.78、T2 0.0112/0.34）
python3 run_study.py --window insample --out data_cache

# 4. 样本外主运行
python3 run_study.py --window oos --out data_cache

# 5. Bootstrap 与附加分析
python3 bootstrap_v41.py --exec-json data_cache/trades_oos_exec.json --fill T0 --var s0
python3 bootstrap_v41.py --exec-json data_cache/trades_oos_exec.json --fill T1 --var s0
python3 analysis_extra.py --exec-json data_cache/trades_oos_exec.json --out-dir .

# 6. 极端单法医
python3 forensic_max_trade.py --data data_cache --out forensic_max_trade.txt
```

随机种子：Bootstrap 固定为 20261025；T0 排队 haircut 种子 1–5。

## 文件

| 文件 | 内容 |
|---|---|
| `fetch_data.py` | 取数（15m/1h/5m + 资金费），写 npz 缓存与 manifest |
| `v41_engine.py` | numpy 移植引擎 + 执行后处理（成交档/费用/资金费/出场修正） |
| `validate_helpers.py` | numpy 移植 vs 原模块逐项校验 |
| `run_study.py` | 主运行：纸面引擎 → 执行档 → 年份/regime 切分 → 压力测试 |
| `bootstrap_v41.py` | IID + 区块 Bootstrap、集中度 |
| `analysis_extra.py` | 逐笔 CSV、T0 排队 haircut |
| `forensic_max_trade.py` | 2026-07-26 极端单逐根 K 线还原 |
| `trades_insample.csv` / `trades_oos.csv` | 逐笔交易表（样本内/样本外分开） |
| `report.md` | 四阶段审计报告 + A/B/C 结论 |
| `forensic_max_trade.txt` | 极端单法医记录 |

## 关键口径（与净 R 审计一致）

- 入场：信号根 15m 收盘价限价 maker，有效期仅下一根 15m；T0 触及 / T1 穿透 0.05% / T2 穿透 0.1%。
- 费用：入场 maker 0.02%、出场 taker 0.05%；费用 R = 费率% ÷ 止损距离%。
- 出场：初始止损（5m 逐根先判）或 15m 收盘越 EMA50；执行器口径跳过 entry bar（成交 bar），出场从成交 bar 后一根起判；同根止损与 EMA 同时触发时止损优先。
- 资金费：8h 结算（00/08/16 UTC），名义 = 1.1232U ÷ 止损距离%。
- 时间：全部 UTC；样本内/样本外以 2025-10-17T02:00Z 为界，无共享信号 bar、无共享回望窗。
