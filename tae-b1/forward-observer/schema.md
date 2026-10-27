# 前向观察系统 · 字段字典

> 全部字段均为描述性记录，不含盈亏、不含胜率、不含“最优”评价。
> 阈值类度量（I2-A 阈值、Theta 种子、I4-B 时刻约定、A 率主结局）
> 在记录时不定死；本表标注“分析时计算”的字段须由原始输入重算。

## ledger.csv（每条序列一行，随演化更新；行永不删除）

| 字段 | 含义 | 来源 / 计算 |
|---|---|---|
| seq_id | 序列编号 FO-####（按 b0 时间顺序） | 系统分配 |
| dir | 方向 long / short | 候选方向 |
| b0_time_utc / b0_idx | 突破根 open 时间（UTC）/ 15m 数组下标 | 候选 bar |
| band_lo / band_hi / band_line | 带下沿 / 上沿 / 定价线 | b0 时刻 trailing 400 根 find_levels |
| band_width_atr | 带宽（15m ATR(14) 倍数） | (bhi-blo) / ATR15(b0) |
| band_touches | 带触碰次数（valid-touch，≤9） | find_levels_meta |
| band_last_touch_lag | 带最后触碰距 b0 的根数（400 窗口内） | 399 - last_touch_idx |
| band_span_bars | 簇跨度（最后触碰 - 首次触碰，根数） | find_levels_meta；元数据不一致时置空 |
| band_meta_mismatch | find_levels 与 find_levels_meta 不一致标志 | 0/1 |
| trend_gate_b1 | b0 时刻 B1 指针法趋势门标签 | na / fail / pass_same / pass_opp |
| trend_v02_at_b0 | b0 时刻 v0.2 严格早于法趋势门标签 | 同上 |
| trend_step_high_min_atr / trend_step_low_min_atr | v0.2 法最后 3 摆动台阶的最小值（1H ATR 倍数） | v0.2 法 |
| atr1h_at_b0 | b0 时刻 1H ATR(14) | v0.2 法 |
| outcome | 序列结局：active / reclaimed / voided / expired | 状态机 |
| outcome_time_utc | 结局 bar 的收盘时间 | 状态机 |
| touched | 是否触碰过带（0/1） | 状态机 |
| first_touch_time_utc / first_touch_lag_bars | 首次触碰根时间 / 距 b0 根数 | 状态机 |
| reclaim_time_utc / reclaim_lag_bars | 收复根收盘时间 / 距 b0 根数 | 状态机（仅已收复） |
| window_type | 触碰窗口类型：reclaim / truncated | 终端时刻 |
| touch_count_bars | 窗口内触碰根数 | [t0, terminal] |
| extreme_value / anchor_time_utc | 锚点极值（多头最低 low / 空头最高 high）/ 锚点根时间 | [t0, terminal] |
| i2a_depth_atr | 触碰深度（带沿到锚点极值，ATR 倍数） | 终端 ATR；描述性，不分类 |
| i2a_rebound_final_atr | 终端收盘相对锚点极值的反弹（ATR 倍数） | 终端时刻 |
| i2a_rebound_max_atr | 窗口内锚点后最大反弹（ATR 倍数） | [t*, terminal] |
| i2a_pos_final | 终端收盘在当根振幅中的分位 [0,1] | 终端时刻 |
| i2b_dwell_max_consec | 最长连续停留根数（极值相交且收盘不穿越远沿） | [t0, terminal] |
| e_signal_any | 收复后 3 根 5m 内是否出现 E 信号（0/1） | 仅描述，不触发动作 |
| e_status | signal / timeout / coincident_void / no_reclaim / pending | E 窗口 |
| e_time_utc | 首根 E 信号 bar 收盘时间 | E 窗口 |
| i4a_M_invalidated_during / i4a_M_invalidation_time_utc / i4a_M_depth_atr | M 读法（普查实现种子）序列内失效标志 / 时刻 / 深度 | 1H 收盘扫描 |
| i4a_L_invalidated_during / i4a_L_invalidation_time_utc / i4a_L_depth_atr | L 读法（文档本意最新种子）同上 | 1H 收盘扫描 |
| theta_seed_M / theta_seed_L | b0 时刻两种种子读法下的 Theta | 见 design.md §2 |
| theta_M_at_reclaim / theta_L_at_reclaim | 收复时刻两种读法下的 Theta | 仅已收复 |
| i4b_recheck_t0 / i4b_recheck_reclaim | 首次触碰 / 收复时刻 v0.2 趋势门重检标签 | 严格早于法；同 1H bar 时 t0 记 merged_into_reclaim |
| post48_status / post96_status | 窗口状态：空（不适用）/ resolved | 仅已收复序列结算 |
| post48_class / post96_class | 先后顺序结局 A / B / C / D / T | 审查口径（摆动时刻=确认根收盘） |
| post48_fell_back / post96_fell_back | 窗口内任一收盘回到带内（0/1） | 结构量 |
| post48_fell_through / post96_fell_through | 窗口内任一收盘穿越远沿（0/1） | 结构量 |
| post48_swing_bar / post96_swing_bar | 首个新同向摆动 bar 下标 | strict 摆动，极值超越 b0 极值 |
| post48_swing_conf / post96_swing_conf | 摆动确认根下标（摆动 bar + 2） | 确认根须在窗口内 |
| post48_ft_idx / post96_ft_idx | 首根收盘穿越远沿的 bar 下标 | 结构量 |
| post48_gap / post96_gap | A 类：跌穿 - 摆动确认间隔；B 类：摆动确认 - 跌穿间隔 | 根数 |
| post48_i4a_M_invalidated / post48_i4a_L_invalidated | 窗口内（收复后）两种读法下是否新失效 | 1H 收盘扫描 |
| post48_trend_gate_end / post96_trend_gate_end | 窗口末收盘时刻 v0.2 趋势门标签 | 严格早于法 |
| created_at / updated_at | 记录创建 / 最近更新（墙钟 UTC） | 系统 |
| outcome_resolved_at / post48_resolved_at / post96_resolved_at | 结局 / 窗口被系统记录的墙钟时间 | 冻结切分用 |

注：非已收复序列的 post48/post96 字段恒为空（窗口不适用）；
`outcome=active` 的序列其终端字段为空，随演化补全。

## skipped.csv（未成序列候选，每行一个被跳过的候选）

| 字段 | 含义 |
|---|---|
| skip_id | X-#### |
| bar_time_utc / bar_idx | 候选 bar 时间 / 下标 |
| dir / band_lo / band_hi | 方向与带 |
| reason | p3_shadowed（同根同方向非最贴近带）/ overlap_active（与活跃序列带重叠） |
| recorded_at | 记录墙钟时间 |

## timeline.jsonl（append-only，每行一次状态变迁）

`{"ts": 墙钟, "bar_time_utc": bar 时间, "event": sequence_opened /
touched / reclaimed / voided / expired / e_resolved /
post48_resolved / post96_resolved / skipped_p3_shadowed /
skipped_overlap, "seq_id": ..., ...}`（事件相关字段随附）。

## state/（系统内部状态，不直接给分析用）

| 文件 | 内容 |
|---|---|
| klines_15m.npz / klines_1h.npz / klines_5m.npz | 原始 K 线（t, ohlc），bar 级 append-only |
| sequences.json | 全部序列与跳过候选的机器状态 + last_processed_idx + 编号计数器 |
| manifest.json | 各 timeframe 首末 bar、条数、本轮新增、缺口（已补 / 未补）、内容冲突、最后处理 bar、运行计数 |
| observer.log | 每轮运行一行摘要（时间、新 bar、处理进度、新序列、结算数） |
| freeze.json | 冻结占位：`freeze_time_utc`（null = 未冻结）；分析时以 b0_time_utc 对比切分探索 / 验证数据 |

## 分析时计算（本系统不预先定死，原始输入已存下）

- I2-A 擦边分类（D_graze）、拒绝证据组合（R_min / P_min / N）：
  由 i2a_* 三特征 + 终端收盘重算，阈值待冻结日拍板。
- Theta 种子定义（M 还是 L）：两种取值已存；分析时也可由 1H
  收盘序列 + swings_tie 摆动点清单重算任意读法。
- I4-B 时刻约定：本系统记 v0.2 严格早于法结果；原始 1H 收盘
  序列已存，替代约定可在分析时重算。
- A 率主结局：post48_class 已按审查口径（确认根时刻）记录；
  摆动 bar 时刻口径（swing_bar 字段）亦已存，敏感性口径可重算。
