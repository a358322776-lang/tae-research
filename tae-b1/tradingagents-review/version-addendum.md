# TradingAgents 审查报告版本补遗：v0.7.1 对照

> **性质**：本文件只对照版本，不修改原报告（`tradingagents-review.md` 原文不动）。原报告的结论若无下文标注，一律视为在 v0.7.1 下仍成立。
> **方法**：静态通读，未运行代码、未调用任何 LLM、未产生任何交易、未推仓。

## 0. 版本定位（必读，先说清楚什么能确定、什么不能）

### 原审查 commit：不可考（直接证据已灭失）

- 原审查称 2026-10-28 将上游 main 分支 depth-1 clone 到 `/tmp/tradingagents-src` 后静态通读。但该目录现已不存在，且原审查未在报告中记录 commit hash，**原 commit 无法直接验证**。
- 本补遗不假装知道原 commit。下面用上游时间线重建最可能的快照，并写明重建的依据与残余不确定性。

### 重建基线：原审查看到的快照极大概率就是 v0.7.1 本身

- 上游 `TauricResearch/TradingAgents` 的 main 分支在 2026-10-27 之后再无新提交：截至本次复核（2026-10-28），main HEAD 仍是 `c4544913`（2026-10-27 01:38 -0700，`Merge pull request #1613 from TauricResearch/v0.7.1`）。
- `v0.7.1` 标签（`git ls-remote --tags` 查得）为轻量标签，正指向 `c4544913`。
- release 分支头 `3e44faa`（`release: 0.7.1`，2026-10-27 01:17 UTC）与合并提交 `c4544913` 的树 0 差异（`git diff --stat` 为空）。
- 推论：只要原审查确实如其 header 所称于 2026-10-28 clone 了 main，则它拿到的必然是 `c4544913`，即 v0.7.1 标签指向的提交。**"报告没有锁定 commit"是一个记录缺失问题，不是内容错位问题**——原审查大概率已经是在 v0.7.1 内容上做出的。
- 残余不确定性：若原审查实际 clone 的不是 main、不是 2026-10-28、或用的是缓存副本，则上述重建不成立。除此之外，本补遗的对照结论均以 v0.7.1 树（`c4544913`）为准，行号均指该树。
- 建议补锁定（本补遗不改原报告）：原报告 header 应补记 `commit c4544913（v0.7.1，2026-10-27）`。

### v0.7.1 定位方法

1. `git ls-remote --tags https://github.com/TauricResearch/TradingAgents.git`：`v0.7.1 → c4544913`（另有 `v0.7.0 → e8f5503`、`v0.6.0 → 1394a3f`）。
2. 全量 clone 后核对：`git rev-parse v0.7.1` = `c4544913`，`git cat-file -t v0.7.1` = `commit`（轻量标签）；`CHANGELOG.md` 有 `[0.7.1] — 2026-10-27` 条目。
3. 对照方法：以 `c4544913` 树逐项核对原报告结论；另以 `git diff e8f5503..c4544913`（v0.7.0 → v0.7.1，37 文件，+688/−117）确认哪些文件在该版本区间动过、哪些没动。

### v0.7.1 实际改了什么（只列与原报告相关的）

**结算（回测结算修复，确有其事）**

- 决策只按最终收盘价打分：`tradingagents/memory/settlement.py:44` `_by_day` 改为 "Final closes keyed by the calendar day"——今日仍在交易的 bar（其收盘价即实时价）不再计分（CHANGELOG #1548）。
- 窗口未交易满不结算、长假后恢复交易即结算：`settlement.py:79-82`（窗口未满直接返回未结算）、`:101`（跨越长于一周的停市后向今日重问收盘价，#1539）。
- 回测上报末次结算失败：`tradingagents/backtest.py:196/202`（`settlement_failures` 收集进结果，#1557）。
- 同秒启动不再共享 run 目录：`backtest.py:130` `_new_run`（目录 claimed 制，#1549）。

**历史数据时间一致性修复（确有其事）**

- `as_of` 一律输出 `YYYY-MM-DD` 规范形：`tradingagents/dataflows/date_window.py:79-84`——未补零日期（如 `2024-7-5`）不再因字符串比较误判为晚于盘后 filing，SEC EDGAR 不再因此误服盘后财报（#1488）。
- 起止倒置的窗口改抛错回传模型：`date_window.py:93-105`（#1595）；语句频率非年/季改回传而非冒充年报（#1593，属 `sec_edgar.py`）。
- 记忆最近 lessons 与 rotation 一律按决策日期排序：`tradingagents/memory/log.py:112`（`get_past_context` 按决策日期取最新）、`:276-277`（`_apply_rotation` 删最旧决策日期条目）——回填旧日期不再挤占近期 lessons（#1603）。

**组合与价格（输入卫生加强，不是账本）**

- 加载拒非有限数：`tradingagents/portfolio.py:26/34`（`ConfigDict(allow_inf_nan=False)`，#1509）。
- 经纪商拼写归一匹配：`portfolio.py:40` `positions_in`（`BTCUSDT`、`700.HK` 归一到被分析标的，#1556）。
- 次分价不再印成 0.00、货币对保留 pips（#1567）；SEC 报表一期一行、100 万以下数字不再印 0（#1517、#1589）。

**该版本区间没动的文件（v0.7.0 → v0.7.1 diff 无此文件）**

- `tradingagents/default_config.py`、`tradingagents/graph/conditional_logic.py`、`tradingagents/agents/schemas.py`、`tradingagents/agents/trader/`、`tradingagents/agents/risk_mgmt/`、`tradingagents/agents/managers/`、`tradingagents/dataflows/symbols.py`。
- `README.md` 有改动，但只是新闻条目（新增 v0.7.1 发布消息）与 Docker 说明；免责段落逐字未动，仅行号 404 → 405（见 §10）。

---

## 1. 逐项对照：原报告 §2 / §3 / §4 / §6 / §10

判定符号：**成立** = v0.7.1 下原文照用；**需修订** = 方向不变但措辞或精度须改；**被推翻** = 原文在 v0.7.1 下不成立。本次对照结果：**被推翻 0 项**。

### §2 多空辩论机制

| 原结论 | v0.7.1 证据 | 判定 |
|---|---|---|
| 默认每方 1 轮，共 2 条辩论消息 | `tradingagents/default_config.py:133` `max_debate_rounds: 1`；`:134` `max_risk_discuss_rounds: 1`；`tradingagents/graph/conditional_logic.py:12` `should_continue_debate`、`:23` `should_continue_risk_analysis`（该两文件在 v0.7.0→v0.7.1 未动） | 成立 |
| Bull 恒先发言 | `tradingagents/graph/setup.py:166` `workflow.add_edge(first_steps, "Bull Researcher")` | 成立 |
| 裁决读全文但无结构化裁决（无打分/投票/置信度） | `managers/` 与 `schemas.py` 在 v0.7.0→v0.7.1 未动；未新增任何打分、投票、置信度字段 | 成立 |
| RM prompt 明令"冲突本身不是 Hold 的理由，要选更强的一方"——机制上压制"证据不足"结论，倾向于在任何情况下都给出方向 | `tradingagents/agents/managers/research_manager.py:36` 原文："conflict alone is not a reason to Hold. Commit to the side with the stronger case, sized by how decisively it wins. **Choose Hold only when the evidence is still balanced after that weighing, or too thin to support a call; do not manufacture a direction to appear decisive.** … independent of which side spoke first or last." | **需修订（措辞，与 v0.7.1 无关）** |

**§2 修订说明**：原报告"倾向于在任何情况下都给出方向"过强。v0.7.1（且该文件在 v0.7.0→v0.7.1 未动，说明原报告表述本身就略过强，与版本无关）的 prompt 实际是：**压制的是"以冲突为由直接 Hold"，Hold 通道仍保留**——证据称量后仍平衡、或过薄时可选 Hold，且明令"不要为显得果断而编造方向"。应弱化为："方向偏好：先称量再决定，冲突本身不自动等于 Hold；但 Hold 通道保留给证据平衡/过薄情形。"无结构化裁决、固定顺序、同源证据三点不受影响。

### §3 交易决策流程

| 原结论 | v0.7.1 证据 | 判定 |
|---|---|---|
| 信号 = 五档评级＋可选价格；`position_sizing` 是自由文本 | `tradingagents/agents/schemas.py:146` `TraderProposal`、`:164` `entry_price`、`:172` `stop_loss`、`:180` `position_sizing`（str）、`:185` `field_validator`；`:33` `_coerce_optional_float` 仅做格式清洗（该文件在 v0.7.0→v0.7.1 未动） | 成立 |
| 无 sizing 规则、无执行接口 | `tradingagents/portfolio.py:33` `PortfolioContext`、`:51` `render`（仅渲染文本）；全仓 grep `place_order` / `execute_order` / `alpaca` 0 命中（v0.7.1 树） | 成立 |
| `portfolio.py` 只是把调用方给定的持仓渲染成文本，不是账本 | 同上；补充见下 | 成立（补充） |

**§3 补充**：v0.7.1 给 portfolio 加了两层输入卫生——`portfolio.py:26/34` 加载拒非有限数、`portfolio.py:40` `positions_in` 经纪商拼写归一——但仍无现金扣减、持仓更新、成交记录。"只是渲染文本"成立，补充"加载层校验已加强"即可。

### §4 风险管理模块

| 原结论 | v0.7.1 证据 | 判定 |
|---|---|---|
| 仓位上限、回撤熔断、单笔风险、相关性控制、止损触发全部无代码；风控是"风险视角的文本辩论" | v0.7.1 全仓 grep `max_position` / `position_limit` / `drawdown` / `circuit_breaker` / 止损触发逻辑 0 命中；`risk_mgmt/` 在 v0.7.0→v0.7.1 未动；止损仍为 `TraderProposal` 的可选字段，无触发、无执行 | 成立 |

**§4 说明（直接回应用户的"执行部分"担忧）**：执行与风控部分在 v0.7.0 → v0.7.1 **零变化**。v0.7.1 的 portfolio 改动是输入校验与符号匹配，不产生任何仓位约束、熔断或执行能力。原报告 §4 可照用。

### §6 回测验证方法

| 原结论 | v0.7.1 证据 | 判定 |
|---|---|---|
| 有回测器但不是盈亏回测（非组合模拟器） | `tradingagents/backtest.py:9` docstring "It is not a portfolio simulator"；`:143` `run_backtest`；cells 间不结转仓位（该语义未变） | 成立 |
| 方向打分；Hold 不产生方向得分；REVIEW 不计入分子分母，只报 `unscored` | `backtest.py:206` `summarize`、`:216`（unscored 说明）、`:226` `hit_rate`、`:229` `RATING_REVIEW → unscored`、`:102` `BacktestSummary`、`:106` `unscored` 字段 | 成立 |
| 作者自承不可重复 | `backtest.py:125` "these figures are indicative rather than repeatable" | 成立 |
| 成本模型为零；alpha 是裸价差 | `backtest.py` 与 `settlement.py` 全仓 grep `commission` / `slippage` / `funding` 0 命中 | 成立 |
| 结算语义：入场 = 决策日后首个收盘价，持有 5 日，alpha = 标的涨幅 − 基准涨幅 | `tradingagents/memory/settlement.py:60` `fetch_returns`、`:66` "entered at the first close after `trade_date`"`、`:157` `holding_period_days` 默认 5 | 成立（补充精度） |
| 记忆：只有成功结算者进入上下文（温和幸存者偏差） | `tradingagents/memory/log.py:105` `get_past_context` 排除 `pending`（`if not e.get("pending")`） | 成立（补充） |

**§6 补充精度（v0.7.1 新增，原报告未写错但可更精确）**：

1. 评分只用最终收盘价：`settlement.py:44` `_by_day`——今日仍在交易的 bar（收盘价即实时价）不再计分（#1548）。原报告"评分窗口起点假设可立即以次日收盘价入场、真实执行有滑点"的 caveat 仍成立（成本仍零建模），但"用未收完的 bar 计分"这个口子已被堵上。
2. 长假后恢复交易即结算：`settlement.py:79-82`（窗口未满不结算）、`:101`（跨越长于一周停市后向今日重问收盘价，#1539）。原报告"要求完整窗口已交易，否则保持 pending"仍成立，补充"长假不再导致永久 pending"。
3. 回测透明度提升：`backtest.py:196/202` 末次结算失败计入 `settlement_failures`（#1557）；`:130` `_new_run` 同秒启动不再共享 run 目录（#1549）。"单次采样无置信区间、标的与时段自选"两点未变。
4. 记忆 rotation：`log.py:112` 最近 lessons 按决策日期取最新、`:276-277` rotation 按决策日期删最旧（#1603）。原报告 §5 "rotation 可丢弃历史"中的"回填旧日期挤占近期 lessons"子项已被修复；但"截断本身仍存在"不变。

### §10 宣传与实现不符清单

| 原条目 | v0.7.1 证据 | 判定 |
|---|---|---|
| "多智能体辩论"（多轮）→ 默认每方 1 轮 | `default_config.py:133` 仍为 1 | 成立 |
| "风险管理团队" → 无硬约束 | 见 §4，全仓 0 命中 | 成立 |
| "回测" → 方向打分、无成本、无复利、作者自承不可重复 | 见 §6 行号 | 成立 |
| "交易员给出交易方案" → 方向词＋可选未校验价格、无执行 | 见 §3 行号 | 成立 |
| "从历史中学习" → 5 日 alpha＋LLM 自写反思、仅结算者入选 | `log.py:105` 仍排除 pending；`reflection.py` 机制未变（该文件在 v0.7.0→v0.7.1 未动） | 成立（补充：rotation 已按决策日期，见 §6.4） |
| "支持 crypto" → 仅 Yahoo 现货代号、无 Binance/永续/资金费/杠杆 | `tradingagents/dataflows/symbols.py:76-77`（仅 `<BASE>-USD`，非 USDT/USDC 对）；全仓 grep `binance` 0 命中 | 成立 |
| 默认模型开箱即用 → 可用性未核实 | `default_config.py:93` `gpt-6-sol`、`:94` `gpt-6-luna`（该文件在 v0.7.0→v0.7.1 未动）；本次亦未核实可用性 | 成立 |
| 论文/外部收益率 → 仓内无固定收益表；README 免责 | `README.md:405` 免责原文逐字未动（v0.7.0 时为 L404，仅因新增新闻行漂移 1 行） | 成立 |

**§10 补充（时间一致性修复，原报告 §7.2 的肯定项在 v0.7.1 下更强）**：原报告已肯定工具层点到点防护；v0.7.1 在此之上补了三处——`date_window.py:79-84`（`as_of` 规范形，未补零日期不再误读盘后 filing，#1488）、`date_window.py:93-105`（起止倒置抛错回传，#1595）、`sec_edgar.py`（语句频率非年/季改回传，#1593）。但**"模型权重泄漏无法消除"不受影响**：v0.7.1 未引入任何针对训练截止日后见知识的缓解措施（代码层面也无法缓解）。

---

## 2. 版本敏感结论（表述依赖 v0.7.1 细节；对照 v0.7.0 会不同）

1. 结算只用最终收盘价，今日仍在交易的 bar 不计分（`settlement.py:44`，#1548）。
2. 长假（>1 周停市）后恢复交易即结算，不再永久 pending（`settlement.py:79-82, :101`，#1539）。
3. 回测上报末次结算失败（`backtest.py:196/202`，#1557）；同秒启动不再共享 run 目录（`backtest.py:130`，#1549）。
4. `as_of` 一律输出 `YYYY-MM-DD` 规范形，未补零日期不再误读盘后 filing（`date_window.py:79-84`，#1488）；起止倒置窗口抛错回传（`date_window.py:93-105`，#1595）。
5. 记忆最近 lessons 与 rotation 一律按决策日期排序，回填旧日期不再挤占（`log.py:112, :276-277`，#1603）。
6. portfolio 加载拒非有限数、经纪商拼写归一匹配（`portfolio.py:26/34, :40`，#1509、#1556）。
7. RM prompt Hold 措辞的弱化（§2 修订）——**注意：此项与版本无关**，是原报告表述本身需修正（该文件在 v0.7.0→v0.7.1 未动），为避免混淆单列于此。

## 3. 结构性结论（不受 v0.7.1 影响；对照 v0.7.0 同样成立）

1. 定位：研报生成器流水线，不是交易策略；无下单接口、无仓位账本、无 sizing 规则。
2. 辩论：默认每方 1 轮、Bull 恒先、同源证据、无结构化裁决（无打分/投票/置信度）。
3. 风控：仓位上限、回撤熔断、单笔风险、相关性控制、止损触发全部无代码；风控 = 风险视角的文本辩论。
4. 回测：方向打分（非盈亏）、Hold/REVIEW 不计分、零成本模型、作者自承不可重复、单次采样无置信区间、标的与时段自选。
5. 记忆：仅成功结算者进入上下文（温和幸存者偏差）；反思由同一模型自写（自证循环结构未变）。
6. 泄漏：模型权重里的后见知识无法消除；live run 记忆不过滤的口子未变（`log.py` 的 `as_of=None` 行为在 v0.7.0→v0.7.1 未动）。
7. 永续缺口：crypto 仅 Yahoo 现货代号，无 Binance、无永续、无资金费、无杠杆概念；默认模型名 `gpt-6-sol`/`gpt-6-luna` 可用性仍未核实；README 免责逐字未动。
8. 可借鉴项与分阶段方案不受影响：M1/M2/M3 是零代码文档工作，不依赖上游版本；第一阶段验收标准、第三阶段"须另行批准"、"LLM 信号不进 TAE"红线全部照用。

## 4. 无法核实的部分（单独列明）

1. **原审查 commit**：直接证据已灭失（`/tmp/tradingagents-src` 不存在且无 `.git`）。§0 的重建依赖两点——原报告 header 自述（2026-10-28 clone main）与上游时间线（main 在 2026-10-28 全天唯一 HEAD = `c4544913`）。若原审查实际 clone 的不是 main 或不是该日期，重建不成立。
2. **本次未运行代码、未调用 LLM**：与原报告相同，以下仍未核实——默认模型名在供应商处是否可用、真实运行成本（代码只计 token 数）、多轮辩论是否优于单轮、记忆 lessons 是否提升后续决策质量、任何论文/外部文章中的收益率数字。
3. **v0.7.1 之后的上游变动**：截至本次复核 main 仍停在 `c4544913`，但这只是本次 clone 时点的快照；之后若上游发布新版，本补遗须重新对照。
4. **CHANGELOG 之外的行为变化**：本补遗只核对了与原报告结论相关的文件与 v0.7.0→v0.7.1 diff；未写入 CHANGELOG 的小改动未逐行核对。
5. **原报告 §1/§5/§7–§9/§11–§13 的其余细节**：本次任务范围限定为 §2/§3/§4/§6/§10 的对照；其余章节未逐项重核，但本次 diff 显示 `managers/`、`risk_mgmt/`、`reflection.py`、`tools.py`（除 8 行外）在版本区间基本未动，无迹象表明其余章节结论被版本变化推翻。
