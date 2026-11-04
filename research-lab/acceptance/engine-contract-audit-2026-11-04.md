# 旧回测引擎字段契约 / 时间顺序 / 成交判断系统性审计

- 审计基准：main HEAD `eb84663`（C5 原始代码未动）+ goals 目录内
  M1/M3 文件（只读，未改动）。
- 方法：源码通读关键路径（数据加载 → 字段解包 → 信号/出场 → 成本），
  逐项核对字段顺序、时间下标、成交时点；不运行任何正式回测。
- 结论先说：**D-ENG-1 式的位置元组换位只在 C5 发现**，B1 与其他引擎
  均使用具名字段/具名数组，未发现同类换位。但所有引擎都依赖文件边界
  的隐式位置契约（npz `ohlc` 列序、JSON 行数组、CSV 列），加载时无
  schema 校验——这是系统性风险，控制措施是验证器的 `Bar` 契约与
  入库检查（见 `validator.py`）。本审计不解封任何已封存引擎。

## 1. 逐引擎结论

| 引擎 | 状态 | 数据格式 → 消费点 | 字段契约 | 时间顺序 / 成交 | 结论 |
|---|---|---|---|---|---|
| C5 `screening-2/c5-exploratory-backtest.py` | 已退出候选池 | JSON 行 `[o,h,l,c]` → `run_tier` 原样 `tuple()` → `run_leg_prices` 按 `(o,low,high,c)` 解包 | **换位：DEFECT D-ENG-1** | gap→日内→收盘顺序正确；stop 日资金费为区间（正确界定） | 缺陷已钉住，分支修复中（见 D-ENG-1 报告）；历史数字不可信为文档规则估计 |
| B1 `tae-b1/b1_engine.py` + `b1_lib.py` | 已封存 | npz `ohlc` 列 → `tr_array` 按 `[:,0..3]` 解为 o/h/l/c；`simulate_exit` 用 `o5[m][1]`=high、`[2]`=low | 一致：fetch（`r[1..4]`→o/h/l/c）→ npz → 解包全链一致，无换位 | 止损 5m 优先于 EMA 收盘；EMA 用收盘价成交（规则乐观假设）；`resolve_sequence` 有 `c15[r+1]` 单格前瞻（见 O-1） | 未发现换位/时序缺陷；残留见 O-1～O-3、U-1 |
| v4.1 `robustness-v41/v41_engine.py` 及 `backtests/` 两脚本 | 已封存 | 具名数组 `o/h/l/c`（`Data` 分列）；脚本用 dict candle（fetch 映射 `r[1..4]` 正确） | 一致，无位置元组消费 | ATR/EMA 因果（cumsum 恒等式核对）；`_held_*` 用摆动后 ≤ 决策 bar 的数据，非决策后未来数据（见 §2） | 未发现换位/未来函数缺陷；等价性未验证（U-2） |
| 忠实版 `tae-b1/faithful-teo/backtest.py` | 已封存 | JSON 行 `r[1..4]` → 具名数组 o/h/l/c | 一致 | 摆动只取 `≤ t-2`（确认摆动），ATR/SMA cumsum 恒等式正确 | 信号/水平路径无未来函数；出场/资金费核算未重审（U-3） |
| M1 `active-strategies/m1-15m/backtest.py`（goals 目录，仓外） | 已封存 | npz 分键 `t/o/h/l/c` 具名数组 | 一致 | 确认用 `i+1` 收盘，入场在确认收盘，出场只看收盘（closes-only，代码自述局限） | 未发现换位；收盘判止损偏乐观（自述局限，非隐藏 bug） |
| M3 `active-strategies/m3-15m/m3_backtest.py`（仓外） | 已封存 | npz 分键 `t/o/h/l/c` 具名数组 | 一致 | 下一根收盘突破极值入场（`e=i+1`），资金费窗口 `(T_entry_close, T_exit_close]` 与文档一致 | 未发现换位/时序缺陷；统计部分未重审（U-4） |
| P1-v2 `tae-b1/p1-v2/p1v2-exploration-backtest.py` | 已封存（K-V4 终止） | 日线 adjclose（无 OHLC） | 不适用 | 形成日月末、执行日为下一 SPY 交易日（T+1），持有收益 exec→exec_next | 时序正确；标的池 survivorship 未审计（U-5） |
| TR-3 strict-test `screening-2/tr3-strict-test/core.py` | 已退出候选池（与 Hermes 运行器不同文件） | 收盘价 panel | 不适用 | Donchian `shift(1)` + 次根执行（T+1），成本按换手计 | 时序正确；标的池 survivorship 未审计；Hermes 运行器不在本次审计内（U-6） |

## 2. 关键核查细节

- **B1 全链**：`fetch_klines.py:34-37`（`r[1]`→o、`r[2]`→h、`r[3]`→l、
  `r[4]`→c）→ `fetch_incremental.py` 写 npz `ohlc` → `b1_lib.stitch`
  拼接不改列序 → `tr_array`（`ohlc[:,0..3]`）与 `hammer/shooting_star/
  engulf`（`q[0..3]`）→ `simulate_exit`（`o5[m][1]` high 触发空头止损、
  `o5[m][2]` low 触发多头止损）。`is_signal_bar` 只用 `i-1/i/i-2` 根，
  因果。EMA/SMA/ATR 只用截至当根数据（已核对）。
- **v4.1 `_held_*`**：`find_levels_np` 每根在 400 根窗口（截至当根 `i`）
  内重算；`_held_res/_held_sup` 检查摆动后 `idx+1..idx+9` 的数据，
  但这些数据全部 ≤ 决策 bar `i`（窗口截断），属于“摆动后确认”，
  不是决策后的未来数据。故不构成未来函数缺陷；但批量窗口重算与
  实时增量计算的等价性未验证（U-2），复用前须用验证器做
  incremental-vs-batch 对照。
- **C5 门盲区**：`verify()` 与 e2e 均用 `(o, low, high, c)` 元组直接
  调用腿函数，`valid_bar` 用 OHLC 校验——两个约定在各自路径内自洽，
  唯独 `run_tier` 的交接处无人校验。验证器的 `audit_day_builder`
  正是为这类边界而设（见 `test_validator.py::test_why_existing_tests_missed_d_eng_1`）。

## 3. 观察项（非缺陷，复用前须处理）

- O-1：B1 `resolve_sequence` 在 k==2 时读 `c15[r+1]`（下一根 15m 收盘）
  做 coincident-void 判断——文档化的单格前瞻，全路径复用前须裁决。
- O-2：B1/v4.1 的 EMA/收盘出场按收盘价成交（无滑点），是规则本身的
  乐观假设，真实成交可能更差。
- O-3：5m 桶内 high/low 先后顺序无 tick 数据，不可验证；止损优先于
  EMA 的设定在桶内同根触发时无法证实。
- O-4：全部引擎的加载路径均无 schema 校验：npz `ohlc` 列序、JSON 行
  顺序、CSV 列名一旦被上游改动，引擎会静默算错。验证器 `Bar` +
  `check_bars` 是强制关口，今后任何引擎接入须先过此关。

## 4. 未验证清单（U）

- U-1：B1 `run_group` 全路径（序列检测/冷却/重叠过滤）与真实 `Data`
  加载路径。
- U-2：v4.1 `find_levels` 批量重算与实时增量等价性；`backtests/`
  两脚本 `evaluate_unified` 的完整成交时序。
- U-3：忠实版出场/资金费核算与 bootstrap 统计。
- U-4：M1/M3 的统计/bootstrap 与 npz 文件契约（文件在仓外，加载时
  须同样过 `Bar` 关口）。
- U-5/U-6：P1-v2 与 TR-3 的标的池 survivorship / 退市处理；Hermes
  TR-3 运行器与执行器设计稿不在本次审计内。

## 5. 复用裁决（审计意见，非授权）

任何旧引擎（包括 B1）重入新循环前，必须：① 过验证器全部关口
（含 `audit_day_builder` 与增量对照）；② 按新协议重新登记并证明
实质区别；③ 经用户单独批准。本审计本身不批准任何重入。
已封存/退出状态不变。
