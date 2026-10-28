# TradingAgents 源码级技术审查报告

> **审查方式**：2026-10-28 将 `https://github.com/TauricResearch/TradingAgents`（main 分支，depth-1）clone 到 `/tmp/tradingagents-src` 后静态通读核心代码。**未运行代码、未调用任何 LLM、未产生任何交易**。每个关键论断标注源码文件与函数/类名。
>
> **结论先行**：TradingAgents 不是一个交易策略，而是一个**多智能体研报流水线**——输入一只股票代码与一个日期，输出一份结构化研报与一个五档评级。它最值得借鉴的不是"多智能体下单"，而是三样流程资产：**点到点的时间戳纪律、决策-结算-反思的日志骨架、以及强制写出反方论据的辩论模板**。它的辩论默认只有一轮、风控没有任何硬约束、回测不算盈亏、不含任何成本模型，因此**不能作为收益证据，也不能直接指导 ETHUSDT 永续交易**。TAE 保持独立确定性引擎的定位不变；本报告所有整合建议都不让 LLM 输出进入 TAE 信号链。
>
> **我方基线**（对比用）：`tae-b1/rules-v0.1-frozen.md`（B1 冻结规则）、`tae-b1/forward-observer/design.md`（前向观察系统）、`DISCIPLINE.md`（v4.1 纪律）、`tae-b1/structure-events/experiments_review.md`（先后顺序结局、I4-A 教训、135/组不可行、E2 主实验建议）。

---

## 0. 一句话画像

**TradingAgents = 12 个只读数据工具 + 11 个 LLM 节点串成的"研报生成器"**：4 名分析师并行写报告 → 多空各讲一轮 → 研究经理裁决 → 交易员给方向与可选价格 → 三名风控人设各讲一轮 → 基金经理给最终五档评级。**没有下单接口、没有仓位账本、没有成本模型、没有回撤熔断**；所谓的"回测"只是把评级方向与随后 5 天的超额收益做对照打分。

---

## 1. 多智能体协作架构

### 1.1 节点清单

| 节点 | 源码位置 | LLM 档位 | 输入 | 输出 | 工具 |
|---|---|---|---|---|---|
| Market 分析师 | `tradingagents/agents/analysts/market_analyst.py` `create_market_analyst` | quick | trade_date、ticker | 市场报告（自由文本＋指标表） | `get_stock_data`、`get_indicators`、`get_verified_market_snapshot` |
| Sentiment 分析师 | `tradingagents/agents/analysts/sentiment_analyst.py` | quick | 同上 | 情绪报告（结构化 `SentimentReport`：band＋0–10 分＋置信度） | Reddit / StockTwits 等社媒工具 |
| News 分析师 | `tradingagents/agents/analysts/news_analyst.py` | quick | 同上 | 新闻报告 | `get_news`、`get_global_news` |
| Fundamentals 分析师 | `tradingagents/agents/analysts/fundamentals_analyst.py` | quick | 同上 | 基本面报告 | `get_fundamentals`、三张表、SEC EDGAR |
| Bull 研究员 | `tradingagents/agents/researchers/bull_researcher.py` `create_bull_researcher` | quick | 四份报告＋辩论 history | 多头论据（文本） | 无（只读报告） |
| Bear 研究员 | `tradingagents/agents/researchers/bear_researcher.py` | quick | 同上＋对方上一论 | 空头论据（文本） | 无 |
| Research Manager | `tradingagents/agents/managers/research_manager.py` `create_research_manager` | **deep** | 辩论 history 全文 | 投资计划（结构化 `ResearchPlan`：五档推荐＋理由＋策略行动） | 无 |
| Trader | `tradingagents/agents/trader/trader.py` `create_trader` | quick | 投资计划＋市场报告＋持仓文本 | 交易提案（结构化 `TraderProposal`：Buy/Hold/Sell＋可选入场价/止损/仓位字符串） | 无 |
| Aggressive / Conservative / Neutral 风控辩手 | `tradingagents/agents/risk_mgmt/aggressive_debator.py` 等 | quick | 交易提案＋四份报告＋风控 history | 各自立场论据（文本） | 无 |
| Portfolio Manager | `tradingagents/agents/managers/portfolio_manager.py` `create_portfolio_manager` | **deep** | 风控 history＋投资计划＋交易提案＋记忆 lessons | 最终决策（结构化 `PortfolioDecision`：五档评级＋摘要＋论点＋可选目标价/持有期） | 无 |
| Memory Log（并行节点） | `tradingagents/graph/trading_graph.py` `_memory_step` | quick（结算时） | 全部待结算决策 | `past_context`（仅 Portfolio Manager 读取） | 读记忆日志、结算价 |

调用链（`tradingagents/graph/setup.py` `GraphSetup.setup_graph`）：

```
START → [4 分析师并行 ＋ Memory Log 并行] → Bull Researcher → Bear Researcher
→ Research Manager → Trader → Aggressive → Conservative → Neutral
→ Portfolio Manager → END
```

### 1.2 状态如何传递：共享字典＋字符串拼接，不是独立记忆

- 全部节点共享一个 `AgentState`（`tradingagents/agents/state.py`）：`MessagesState` 的扩展，含 `market_report`、`investment_debate_state`、`risk_debate_state`、`final_trade_decision`、`past_context` 等字段。
- 辩论 history 是**字符串拼接**：`bull_researcher.py` 里 `history + "\n" + argument`，`current_response` 恒为上一发言全文。分析师子图有私有消息历史（`setup.py` `_analyst_graph`），但只交出最终报告文本，工具调用过程不进入主图。
- 记忆的唯一入口是 `past_context`，且**只有 Portfolio Manager 的 prompt 读它**（`portfolio_manager.py` 的 `lessons_line`）。分析师、研究员、交易员全程看不到历史教训。
- 结论：这不是"多个独立智能体各持记忆"，而是**一条消息接力链**：每一步把前文全文拼进下一 prompt。好处是可审计（`_log_state` 把全部报告与辩论 history 存 JSON），坏处见 §7.1（错误相关性）。

### 1.3 LLM 调用次数与成本结构

- 档位（`tradingagents/default_config.py`）：quick 档服务分析师、研究员、辩手、交易员；deep 档只服务 Research Manager 与 Portfolio Manager。两档可配不同 provider，但默认同源（`llm_provider`＋`deep_think_llm`/`quick_think_llm` 两个模型名）。
- 单次 run 的 LLM 调用数（默认配置 `max_debate_rounds=1`、`max_risk_discuss_rounds=1`、`max_tool_rounds=20`）：
- 下限约 12 次：4 分析师各 1 次（零工具轮，实际不可能）＋ Bull、Bear、RM、Trader、3 风控、PM 各 1 次。
- 现实估计约 25–40 次：每名分析师平均 3–8 轮工具调用（每轮 = 1 次 LLM 调用）＋下游 8 次固定调用。
- 上限 92 次：4 名分析师各 20 工具轮＋wrap-up＋下游 8 次（`setup.py` 注释：超限强制 wrap-up，不会撞递归上限）。
- 另加结算：每个待结算决策 1 次 Reflector 调用（quick 档），发生在后续 run 的 Memory Log 节点。
- 成本观测：`cli/stats_handler.py` 的 `StatsCallbackHandler` 只统计 LLM 调用数、工具调用数、输入/输出 token 数，**代码里没有任何美元定价表**。因此"跑一次多少钱"在源码层面是算不出的，只能按 token 量自行乘单价。
- 默认模型名 `deep_think_llm=gpt-6-sol`、`quick_think_llm=gpt-6-luna`（`default_config.py`）：**本次审查未核实这两个名字在任何供应商处可用**，接入时须先映射到己方实际可用模型；开箱即用性未验证。

---

## 2. 多空辩论机制：默认只有一轮，裁决看全文但无结构化裁决

- 轮数（`tradingagents/graph/conditional_logic.py` `should_continue_debate`）：`count >= 2 * max_debate_rounds` 即结束；默认 `max_debate_rounds=1`，故序列恒为 **Bull（1）→ Bear（1）→ Research Manager**。所谓"多轮辩论"只在用户手动调大该参数时才存在；README 架构图未标明默认值。
- 发言顺序固定：`setup.py` 中 `workflow.add_edge(first_steps, "Bull Researcher")`，Bull 恒先发言；路由只看 `current_response` 是否以 "Bull" 开头。Bear 恒为回应方、最后发言方。
- 裁决者（Research Manager）读的是**辩论 history 全文**，不是只读最后一方——这是结构上做对的一点。但裁决依据是自由文本权衡，没有论点打分、没有投票、没有置信度传递；prompt 里写"不因发言顺序加权"（`research_manager.py`）只是**指令**，没有任何机制保证模型真的做到。
- 辩论影响最终决策的唯一通道：RM 的 prompt 上下文。辩论记录本身不产生任何结构化字段（无"多方分歧度"、无"反方最强论据"摘录），下游 Trader 与 PM 只能读到 RM 的裁决文本，看不到原始辩论。
- **"辩论只是走形式"的结构证据**：
1. 轮数固定为 1，不因双方分歧程度延长或提前收敛；
2. 双方读同一批分析师报告（`bull_researcher.py` 与 `bear_researcher.py` 的 prompt 资源段完全相同），分歧只来自人设指令，不是来自不同证据；
3. RM prompt 明令"冲突本身不是 Hold 的理由，要选更强的一方"——机制上**压制"证据不足"这个结论**，倾向于在任何情况下都给出方向。这与我方"证据不足就不开单"的纪律方向相反。
- 风控辩论同构：`should_continue_risk_analysis`，默认 `max_risk_discuss_rounds=1`，序列恒为 Aggressive → Conservative → Neutral → Portfolio Manager；PM 同样读 history 全文裁决。

---

## 3. 交易决策流程：信号 = 五档评级＋可选数字，无 sizing 规则

完整链路（`trading_graph.py` `propagate` → `_run_graph` → `record_decision`）：

```
ticker＋trade_date → 4 份分析师报告 → 多空辩论 → RM 五档推荐
→ Trader 三档行动＋可选入场价/止损/仓位 → 风控三方辩论
→ PM 五档最终评级（run_rating）→ 记入记忆日志（pending）
→ 后续 run 结算（5 日 alpha＋LLM 反思）
```

- 最终信号（`tradingagents/agents/rating.py` `run_rating`）：Buy / Overweight / Hold / Underweight / Sell 五档之一；解析失败时为 `"REVIEW"`（`portfolio_manager.py` 注释 #1170）。
- Trader 的"三件套"真相（`tradingagents/agents/schemas.py` `TraderProposal`）：
- `action`：Buy / Hold / Sell（必填）；
- `entry_price`、`stop_loss`：`float | None`，**可选**，缺失时渲染为 "not provided"；
- `position_sizing`：**自由文本字符串**（如 "5% of portfolio"），不是数值、不是公式、没有任何计算。
- 因此信号不是"方向＋仓位＋止损三件套"，而是**方向词＋可空的 LLM 自填数字**。
- 没有 sizing 规则：没有任何代码把账户规模、波动率、风险预算换算成数量。`portfolio.py` 的 `PortfolioContext` 只是把调用方给定的持仓与现金**渲染成一段文本**供 agent 阅读，不是账本：不扣减现金、不更新持仓、不记录成交。
- 没有执行接口：全仓 grep `alpaca`、`broker` 下单、`place_order`、`execute_order` 均为零命中（仅 `portfolio.py` 自述 "Broker-neutral" 与符号映射注释）。最终产物是 markdown 报告与 JSON 状态日志，不是订单。

---

## 4. 风险管理模块：纸面建议，无任何硬约束（已逐项核查）

| 风控要素 | 代码里的实际情况 | 结论 |
|---|---|---|
| 仓位上限 | 无。`position_sizing` 是 LLM 自由文本，无数值校验、无上限比较 | 无强制执行 |
| 回撤熔断 | 无。没有任何回撤计算、熔断阈值、停机逻辑 | 无强制执行 |
| 止损 | Trader 的 `stop_loss` 是可选字段；无触发逻辑、无执行、无"止损后冷却" | 仅为建议数字 |
| 单笔风险 | 无。本金×风险%→数量的公式不存在；TAE 的 2%/单、6%/日、10%/周熔断在对方代码里无对应物 | 无强制执行 |
| 相关性控制 | 无。多标的 run 之间 cells 独立（见 §6），不计算组合相关性 | 无强制执行 |
| 价格校验 | 无。`entry_price`/`stop_loss` 只经过 `_coerce_optional_float`（占位符/百分比/区间 → None），**不与市价、ATR、支撑阻力比对**；一个偏离市价 50% 的止损也能通过校验 | 无强制执行 |
| 唯一接近"硬约束"的东西 | `setup.py` 的工具轮上限、`conditional_logic.py` 的辩论轮上限、`trading_graph.py` 的 `_validate_trade_date`（日期格式与不晚于今天）——全是流程护栏，不是交易风控 | 流程级 |

风控辩论三人组（`risk_mgmt/aggressive_debator.py` 等）本质是三段人设 prompt：激进派"为高风险高回报辩护"、保守派反之、中立派居中。它们的输出是辩论 history 文本，PM 读后"综合"——**综合标准仍是 LLM 自由裁量**。把这套东西称为"风险管理模块"属于命名夸大；准确说法是"风险视角的文本辩论"。

与我方对照：TAE 的止损是带沿外 1×ATR 的确定性公式、止损后同方向冷却 2h（B1 C7）、杠杆硬上限 20x、单笔 2% 风险公式（DISCIPLINE.md v4.1）；对方以上全部没有。

---

## 5. 历史记忆机制：markdown 日志＋LLM 自写反思，有自证循环口子

- 存什么（`tradingagents/memory/log.py` `TradingMemoryLog`）：append-only markdown，每条 = `[日期 | 标的 | 评级 | pending]` 标签 ＋ 决策全文；结算后标签改为 `[日期 | 标的 | 评级 | raw% | alpha% | 5d]` 并追加 `REFLECTION` 段。`alpha` 存储时四舍五入到 0.1pp（`backtest.py` `_alpha` 注释），聚合精度止于 0.1pp。
- 何时写入：`propagate` 结束时 `record_decision` 记 pending（`trading_graph.py`）；结算发生在**后续 run 的 Memory Log 节点**（`_memory_step` 调 `settle_all_pending(wait=False)`），或 `backtest.py` 末尾的 `settle_pending` 补结算。
- 怎么检索（`log.py` `get_past_context`）：同标的最近 5 条全文 ＋ 跨标的最近 3 条仅反思；**仅 Portfolio Manager 读取**。
- 结算度量（`tradingagents/memory/settlement.py` `fetch_returns`）：入场 = 决策日后首个收盘价，持有 `holding_period_days`（默认 5）个交易日；alpha = 标的涨幅 − 基准涨幅（基准按后缀映射，默认 SPY）；要求完整窗口已交易，否则保持 pending；`resolution_date` = 窗口最后一根 bar 的日期。
- 点到点防护（值得肯定，见 §8）：`get_past_context(as_of=...)` 在历史 run 中只纳入 `resolved <= trade_date` 的条目（#1251）；`_memory_as_of` 对当日 run 返回 None（不过滤）。
- **自证循环口子（四处）**：
1. **反思由同一模型写**：`reflection.py` `Reflector` 用 quick 档 LLM 给自己的决策写 2–4 句"教训"，再喂给 PM。模型给自己的过去打分、再读自己的打分做新决策——没有独立评分者。
2. **只有成功结算的条目进入上下文**：pending（含价格/反思获取失败者）被 `get_past_context` 排除（`not e.get("pending")`）。结算失败的样本系统性缺席，聚合与"教训"都带温和幸存者偏差。
3. **live run 不过滤**：`as_of=None` 时不过滤，且无 `resolved` 字段的旧条目（迁移前数据）永远不过滤——实时使用时，未来信息的旧条目可混入。
4. **rotation 可丢弃历史**：`memory_log_max_entries` 一旦设置，结算时删除最旧已结算条目；长期"教训"分布会被截断，且删除标准是日期不是质量。
- 与我方对照：我方前向观察系统（`forward-observer/design.md` §3）用 `freeze.json` 做冻结切分、原始 K 线 append-only 永不改写、事件时间线与系统记录时间分开（`b0_time_utc` vs `outcome_resolved_at`）；对方 `resolution_date` 思想与此相通，但对方把"反思"这一主观层也写进了同一日志，而我方 ledger 只存可重算的原始字段——这是我方更干净的地方，应保持。

---

## 6. 回测验证方法：有回测器，但它不是盈亏回测

- 回测器存在（`tradingagents/backtest.py` `run_backtest`）：在 (ticker, date) 网格上跑完整图，每个 cell 一次 `propagate`，写入**独立于 live 日志**的记忆日志（避免污染真实 run 的上下文），末尾补结算。
- 但它**不是投资组合模拟器**，作者在模块 docstring 里明说："It is not a portfolio simulator, and must not grow one. Turning a rating into a filled order needs a quantity, a fill price and a cash ledger, none of which the system has." cells 之间独立；即使传入 portfolio，也是每个 cell 用同一份 standing book，不结转仓位。
- 评分方式（`backtest.py` `summarize`）：
- 每个已结算 cell：方向（Buy/Overweight=+1，Sell/Underweight=−1，Hold=0）对照 5 日 alpha 的符号 → hit_rate；同时报 mean_alpha。
- Hold 不产生方向得分（`hit_rate=None`，只计 mean_alpha）；评级解析失败的 REVIEW **不计入分子也不计入分母**，只报 `unscored` 数。
- 无置信区间、无显著性检验、无多重比较校正；样本量 = cells 数，单次模型采样。
- **成本模型：零**。全仓 grep 手续费/滑点/冲击成本/资金费在交易逻辑中零命中；评分用的 alpha 是**裸价格涨幅差**，不扣任何成本。任何把 mean_alpha 读作"策略收益"的解读都是错的。
- **可复现性：作者自承不可重复**。`BacktestSummary.render` 末尾原话："One model sampling per cell, and text feeds are not archived, so these figures are indicative rather than repeatable." 加上 temperature 默认 None（各 provider 默认值）、模型输出非比特一致（README 亦承认），同一网格重跑会得到不同数字。
- README 的免责（README.md 约 L405，原话）："Backtest results are not guaranteed to match any published figure. Returns depend on the model, the temperature, the date range, data quality, and the sampling above. Treat the framework as a research scaffold for studying multi-agent analysis, not as a strategy with a fixed, replicable return." ——**README 自身不承诺可复现的收益**。本审查在 README 里没有找到以表格形式宣称的固定收益率数字；若外部文章引用"TradingAgents 回测收益 XX%"，那是论文/文章口径，不在当前 repo 代码的验证范围内。
- 评价窗口与标的宇宙：全部由调用方自选（README 示例为 NVDA/AAPL，`run_backtest(["NVDA","AAPL"], dates,...)`），无固定宇宙、无默认基准期；选股与选期自由度本身就是过拟合口子（见 §7.5）。

---

## 7. 批判分析

### 7.1 多智能体之间的错误相关性：辩论的独立性只是表观

- **同源模型**：默认配置下 quick 与 deep 档可配不同模型，但同一 provider、同一模型家族是常见配置；即使配不同模型，全部节点仍共享同一批分析师报告、同一辩论 history 文本、同一套 prompt 模板（`context.py` 的 `report_or_absent`、`get_language_instruction` 处处复用）。
- **同源证据**：Bull 与 Bear 读的四份报告逐字相同；风控三方读的交易提案与报告也逐字相同。分歧的唯一来源是人设指令（"你要为多头辩护"），不是独立信息源。
- **同源裁决**：RM 与 PM 都读同一 history 字符串做自由裁量；没有任何节点做独立数据拉取来验证对方论据（研究员与风控辩手**没有工具**，`bull_researcher.py`、`aggressive_debator.py` 均无 tool 绑定）。
- **推论**：不能把"多空辩论＋三方风控＋两级经理"计为 5–6 个独立证据。它们是**同一证据链上的 5–6 次重述**，相关系数接近 1。把"三方一致"解读为"高置信度"是统计错误；正确做法是把整条链计为**一个**带内部一致性检查的观点。这一点与我方 E 实验的多重性教训同构：8 个实验共享同一前向流时不能各算各的 α（`experiments_review.md` §多重性），对方的多智能体一致性同样不能重复计分。

### 7.2 数据泄漏：工具层防护很强，但模型权重泄漏无法消除

**先肯定工具层**（这是本项目最扎实的工程部分，值得我方借鉴思路）：

- 全部 dated 工具从 graph state 注入 `trade_date`，并经 `as_of` / `as_of_window`（`tradingagents/dataflows/date_window.py`）钳制到决策日，模型乱传日期也走不过去。
- 新闻/社媒/研报类条目经 `in_window` 过滤到 `[start, end+1day)`；无日期条目仅在窗口触及当下时保留（#1126、#1220），否则视为不可证非未来而排除。
- 无历史版本的供应商数据一律扣留：公司概况（#1300）、无 filing date 的内幕交易、无 filing date 的财报（`withhold_live_profile`、`withhold_undisclosed_trades`、`withhold_undated_statements`）；SEC EDGAR 按 filing date 如实服务。
- 预测市场（Polymarket）只服务实时赔率，历史 run 直接扣留（`vendors/polymarket.py` `is_historical` 分支）。
- 身份解析（`agents/context.py` `build_instrument_context`）：历史 run 只注入**当前名称**（并明确标注"当时可能已更名"）， sector/industry/exchange 一律不给，不含任何价格数值。
- 测试覆盖：`tests/test_news_lookahead.py`、`test_social_lookahead.py`、`test_undated_tools_as_of.py`、`test_memory_pointintime.py` 专门测点到点行为。

**残余泄漏（工具层管不到的三处）**：

1. **模型权重泄漏（根本性）**：LLM 的训练数据截止日通常晚于所谓"历史回测"的评价窗口。模型在"分析 2023 年某日"时，权重里已经装着 2023 年之后发生的事（财报、并购、股价走势）。工具层把数据流管住了，但管不住参数记忆。任何早于训练截止日的回测窗口，其结论都混有"模型见过结局"的成分；这一点在对方代码里**没有任何缓解措施**（也没有办法用代码缓解，只能缩短评价窗口到截止日之后，或把回测结论降级为"演示"）。
2. **live run 的记忆过滤关闭**：`_memory_as_of` 对当日 run 返回 None，`get_past_context` 不过滤；无 `resolved` 字段的旧条目也永不过滤。实时使用时，记忆上下文可能混入"结局已知"的旧条目——对当日决策而言这些结局是历史，不算泄漏；但一旦把同一日志用于历史回测复盘，口径就变了。
3. **"决策日"语义模糊**：新闻窗口含决策日全天（含盘后），而结算入场在决策日后首个收盘（`settlement.py` 注释 #1518 自承"a run dated trade_date reads news published after that day's close"）。语义上可自洽（决策形成于 D 日收盘后、执行于 D+1 收盘），但若有人把决策日理解为"D 日开盘前"，则 D 日盘中/盘后信息就是未来函数。**我方借鉴时必须把"决策时刻"写成一句话定义**，不能留这种模糊（我方 B1 已做到：判定只用已收盘 K 线，信号在结构确认后形成）。

### 7.3 未来函数：逐项清单

| 环节 | 是否含决策时刻后才可知的数据 | 依据 |
|---|---|---|
| 分析师工具（价格/指标/新闻/财报） | 否（工具层钳制） | `agents/tools.py` 全工具经 `as_of`/`as_of_window`；`date_window.py` |
| 模型权重里的后见知识 | **是，无法消除** | 见 §7.2(1)；训练截止日晚于评价窗口即成立 |
| 结算评分（5 日 alpha） | 否（评分用，不进决策） | `settlement.py` 入场在决策日后首收盘；但注意：**评分窗口起点的选择本身假设"决策后可立即以次日收盘价入场"，真实执行有滑点与不可成交风险，评分偏乐观** |
| 记忆 lessons（live run） | 边缘：无 `resolved` 的旧条目不过滤 | `log.py` `get_past_context` |
| 决策日全天新闻（含盘后） | 语义模糊，见 §7.2(3) | `date_window.py` `in_window` 上界为 end+1day |
| 身份解析（当前名称） | 否（已标注，且不含价格） | `context.py` `build_instrument_context` |
| Trader 的入场价/止损 | **是，模型现写现编**：价格数字由 LLM 在决策时刻"想"出来，不锚定任何已收盘价；schema 只清洗格式不比对市价 | `schemas.py` `_coerce_optional_float` |

### 7.4 模型幻觉：校验只有 prompt 指令，没有代码拦截

- 唯一接近校验的机制：市场分析师 prompt 要求"写最终报告前先调 `get_verified_market_snapshot`，把它当作 exact claim 的 source of truth；冲突时 flag 出来，不要编一个调和数字"（`market_analyst.py`）。但这只是**指令**：没有任何代码检查分析师是否真的调了它，也没有任何代码把最终报告里的数字与 snapshot 比对。
- 下游全盘接受：研究员、RM、Trader、PM 读到的都是自由文本报告；报告里的一个编造数字（营收、目标价、支撑位）会原样进入辩论与裁决，无任何交叉核对节点。
- Trader 的数字幻觉直通最终决策：`entry_price`/`stop_loss`/`price_target` 只要是合法浮点就通过（`schemas.py`）；偏离市价、偏离 ATR、偏离报告支撑位都不触发任何告警。幻觉一旦进入"仓位决策"（在对方语境里即最终评级与交易提案），**没有任何拦截层**。
- 我方防呆对照：TAE 的全部价格字段（带沿、触发价、止损）都由确定性函数算出（`key_levels.py`、`b1_lib.py`），LLM 从不产生价格数字——这是必须保持的红线。

### 7.5 回测过拟合：选股、选期、调参三处自由度都不受控

- **标的自由**：宇宙由调用方自选；README 示例 NVDA/AAPL 是事后看来走势强的标的。用两只强势股做的演示不能外推到全市场；代码里没有任何"必须覆盖全宇宙/随机抽样"的要求。
- **时段自由**：`iter_grid` 的起止由调用方自选；`run_backtest` 不报告"试过多少个窗口、只展示了哪一个"，选择性报告无从核查。
- **参数自由**：`max_debate_rounds`、`max_risk_discuss_rounds`、`temperature`、`max_tool_rounds`、`holding_period_days`、`benchmark_ticker` 全部可调；`run_settings` 虽然记录了配置（`trading_graph.py` `run_settings`，且密钥/路径被排除在外），但没有任何机制把"调过参"与"未调过参"的 run 区分开，也没有对"同一网格跑多组配置取最优"做多重性校正。
- **样本量与结论强度不匹配**：`summarize` 只报 hit_rate 与 mean_alpha，不报 n 对应的置信区间；一个 n=20、hit_rate=60% 的结果与 n=200、hit_rate=60% 的结果在报告里看起来一样强。结合我方审查教训（60.5% 基线、5pp margin、80% 功效需约 1150/组，`experiments_review.md` §3.2），对方的"方向打分"在样本量上同样需要功效核算，而它没有。
- **单次采样**：每个 cell 只采样一次模型输出；同一 cell 重跑可得不同评级，hit_rate 的抽样方差包含模型采样方差，但报告里不体现。

### 7.6 交易成本问题：零建模，报告收益只会被向下修正

- 费用、滑点、冲击成本、资金费：**全部未建模**（§6）。评分 alpha 是裸价差。
- 定性折扣方向：**只向下**。任何真实执行都会在 alpha 上再扣一层：
- 股票场景：佣金＋买卖价差＋冲击（尤其小盘与高频调仓）；
- 若移植到 ETHUSDT 永续：taker/maker 费＋资金费（多空方向不对称、极端行情下资金费可观）＋滑点（止损市价单在插针时穿透）——对方代码里这些概念**一个都不存在**（全仓无 binance/perpetual/funding/leverage 命中；crypto 只是 Yahoo 现货代号 `ETH-USD`，见 `dataflows/symbols.py`："Yahoo lists only `<BASE>-USD` (not the USDT/USDC stablecoin pairs)"）。
- 因此：对方的 mean_alpha 即使为正，也**不能**与我方净 R（已扣 taker 0.05%×2、资金费、T0/T1/T2 滑点敏感性）放在同一张表比较；向永续移植时必须另建成本模型，否则就是把毛方向分当净收益用。

---

## 8. 架构对比表：TradingAgents vs MUSE＋TAE

| 维度 | TradingAgents（源码实测） | MUSE＋TAE（我方现状） |
|---|---|---|
| 决策主体 | LLM 链（11 节点，quick/deep 两档） | 确定性规则引擎（`key_levels.py`/`b1_lib.py`）＋ MUSE 人工审计 |
| 信号来源 | LLM 读研报文本后给五档评级 | 冻结规则：1H 严版趋势＋关键带同侧第 ≥2 次测试＋5m 六种 E（B1 C1–C12） |
| 信号形态 | 方向词＋可选 LLM 自填价格（无校验） | 方向＋触发价＋止损价（公式算出）＋数量（2% 风险公式） |
| 验证方式 | 评级方向 vs 5 日 alpha 打分；无仓位、无复利、无回撤 | 逐笔 R（毛/净）、T0/T1/T2 止损敏感性、EMA50/SMA20 退出敏感性、样本外 341 单稳健性 |
| 成本模型 | 无 | taker 0.05%×2、资金费名义模型、滑点敏感性档 |
| 时间粒度 | 日级（ticker＋date） | 15m/5m/1H K 线，事件时刻精确到根 |
| 可复现性 | 作者自承不可重复（单次采样、文本 feed 不存档、temperature 默认） | 脚本＋参数＋数据来源＋执行命令全记录；前向观察系统 8/8 对照 0 错配 |
| 点到点纪律 | 工具层极强（as_of/in_window/withhold 全套＋测试）；但权重泄漏无解 | 仅已收盘 bar、冻结切分（freeze.json）、探索/验证数据以 b0_time 切分 |
| 失败模式 | 幻觉数字直通决策；辩论形式化；评级解析失败变 REVIEW 不计分 | 规则错配（如 I4-A 种子错误校准）——但可被只读审计抓出（B1 审计 v0.1：实现错误 0 项） |
| 适用标的 | 美股为主；crypto 仅 Yahoo 现货代号，无永续/资金费/杠杆概念 | 币安 ETHUSDT 永续（及 XAU/CL/QQQ 纸面线） |
| 失败时的代价 | 一份错研报（无执行则无金钱损失） | 真钱单（故 live 已停、研究暂停、纸面与前向观察为主） |

---

## 9. 可复用模块清单

完整表见 `modules-table.csv`。摘要（按优先级排序，**前三为本次最值得借鉴**）：

### M1：结构化多空反证备忘录模板（成本：低，约 0.5 天文档工作，零代码）

- **是什么**：借 `bull_researcher.py` / `bear_researcher.py` / `research_manager.py` 的结构——正方最强论据、反方最强论据、裁决者"哪条论据决定了结论、什么证据会推翻它"——做成一份**策略审计备忘录模板**，用于我方每次规则审查、归因复盘、实验设计审查。
- **源码位置**：`tradingagents/agents/researchers/bull_researcher.py`、`bear_researcher.py`、`tradingagents/agents/managers/research_manager.py`、`tradingagents/agents/schemas.py`（`ResearchPlan` 三字段）。
- **预期收益**：把我方已有的"反证"习惯（B1 归因、实验审查）固化为必填字段，避免审计时只写支持结论的证据；尤其强制填写"什么证据会推翻本结论"（对应 PM prompt 里的 "what would change it"，`portfolio_manager.py`）。
- **风险与防呆**：模板里的数字栏**只许填 TAE/观察系统算出的确定性数字**，不许填 LLM 现想的数字；反方论据必须引用可核查来源（文件路径＋行/表），否则视为未完成。

### M2：假设-证伪登记表（成本：低，约 0.5 天文档工作，零代码）

- **是什么**：借 `backtest.py` "一格一决策＋结算＋反思"的骨架，但**去掉 LLM 反思**，改成确定性登记：假设陈述、预测度量、冻结日、证伪线（95% CI 上限 < margin）、检验数据（冻结后前向）、结果、复核人。
- **源码位置**：`tradingagents/backtest.py`（`run_backtest`、`summarize`、`BacktestSummary`）、`tradingagents/memory/log.py`（条目格式与 `resolution_date`）。
- **预期收益**：直接服务 E2 主实验与 L1 的 H-A1/H-A2/H-B1/H-C1：每个假设在检验前就把"什么算证伪"写死，杜绝事后改口径；与我方"冻结后前向数据才算验证"的铁律同构。
- **风险与防呆**：登记表一旦冻结不得改证伪线；检验数据必须来自前向观察系统（`forward-observer`），不得回填普查数据；未评分/未结算的假设单独列"未决"，不许并入通过或证伪。

### M3：风险检查清单（成本：低，约 0.5 天文档工作，零代码）

- **是什么**：把风控三人组（激进/中性/保守）**降维成一份检查清单**，不用 LLM 辩论：每次规则变更、每次实验冻结前逐项打勾——单笔风险、总敞口、日/周熔断、杠杆上限、止损是否可执行、成本是否计入、样本量是否够功效、多重性是否分配 α。
- **源码位置**：`tradingagents/agents/risk_mgmt/aggressive_debator.py`、`conservative_debator.py`、`neutral_debator.py`（三视角结构）、`tradingagents/graph/conditional_logic.py`（轮换逻辑的思想来源）。
- **预期收益**：把"风控辩论"从 LLM 表演变成可审计的硬检查；清单项直接对应我方已有硬约束（2%/6%/10%、20x、冷却 2h），不是建议。
- **风险与防呆**：清单是**门**不是参考：任一项未通过即冻结流程暂停；清单本身变更须用户批准并留档。

### M4：点到点时间戳纪律补丁（成本：低，文档级；代码级须另行批准）

- **是什么**：借 `date_window.py` 的两条具体规则补我方文档：①**无日期数据默认排除**（对方 `in_window` 对 undated 条目的处理）；②**缺口显式标注**（对方 `coverage_gap`：覆盖不到的窗口报"不可用"而不是"无信号"）。我方观察系统已有缺口记入 manifest 的做法（`design.md` §5），补的是"把'无数据'与'数据说无'区分开"的表述纪律。
- **源码位置**：`tradingagents/dataflows/date_window.py`（`in_window`、`coverage_gap`、`withhold_*`）。
- **预期收益**：审计报告里不再出现"某窗口无信号"这种含混表述；缺口与阴性结果分开统计，避免把数据缺失读成市场结论。
- **风险与防呆**：只改文档表述，不动 observer 代码；任何代码级时间戳改动走正常批准流程。

### M5：决策-结算日志格式（成本：中，约 1–2 天小脚本，不动 TAE 核心）

- **是什么**：借 `log.py` 的 markdown 条目格式（标签＋决策全文＋结算字段＋`resolution_date`），用于我方纸面单与审计结论的"决策时已知信息"快照：每条审计结论附带"决策时可见的数据范围、冻结版本、结算日期"三字段。
- **源码位置**：`tradingagents/memory/log.py`（`store_decision`、`update_with_outcome`、`_resolved_tag`）、`tradingagents/memory/settlement.py`（`fetch_returns` 的窗口语义）。
- **预期收益**：审计结论可追溯到"当时已知什么"；复盘时不再争论"当时到底能不能看到这个数"。
- **风险与防呆**：**反思栏只填确定性数字**（TAE 算出的 R、窗口结局），不许 LLM 写散文反思；日志 append-only，不得改写已结算条目；与 TAE 信号链物理隔离（只读 TAE 输出文件，不 import 扫描器）。

### M6：结构化输出清洗思想（成本：低，未来用 LLM 写审计结论时复用）

- **是什么**：借 `schemas.py` 的 `_coerce_optional_float`（占位符/百分比/区间 → None，宁缺毋滥）与"缺失字段显式标 not provided"的做法，用于未来任何 LLM 生成的结构化审计字段。
- **源码位置**：`tradingagents/agents/schemas.py`（`_coerce_optional_float`、`render_*` 系列）。
- **预期收益**：LLM 输出的结构化字段不再把"15%"读成 15、把区间读成单值。
- **风险与防呆**：清洗只是格式层，**不替代价格校验**；任何价格字段仍须与 TAE 确定性输出比对后才可用。

### 明确不采用的模块（附理由）

| 模块 | 不采用理由 |
|---|---|
| 多智能体辩论流水线本身（LangGraph 图＋11 节点） | 成本高（25–40 次 LLM 调用/run）、收益未经验证（辩论默认 1 轮、错误相关性高）；且我方审计是人工＋确定性脚本，不需要 LLM 扮演多方 |
| LLM 直接信号/仓位（Trader/PM 输出进执行） | 红线：TAE 不读 LLM 输出；对方信号本身无校验、无成本模型、无 sizing 规则 |
| 回测评分器（rating vs 5 日 alpha） | 无成本、无仓位、无复利，不能作为收益证据；仅借鉴其"Hold/REVIEW 未评分须显式报告"的报告纪律 |
| LLM 自写反思进记忆 | 自证循环（§5）；我方只存确定性数字 |
| 预测市场/社媒情绪工具链 | 标的与数据源都不匹配我方（美股新闻/Reddit/Polymarket vs 币安 K 线）；且情绪工具的历史 point-in-time 依赖供应商回放能力，未在我方数据条件下验证 |

---

## 10. 宣传与实现不符 / 未找到清单

| 宣传印象（README/架构图/项目名） | 源码实际情况 | 位置 |
|---|---|---|
| "多智能体辩论"（多轮） | 默认每方 1 轮，共 2 条辩论消息；多轮须手动调参 | `default_config.py`（`max_debate_rounds=1`）、`conditional_logic.py` |
| "风险管理团队" | 三段人设 prompt＋PM 自由裁量；无任何硬约束、无熔断、无仓位上限 | `risk_mgmt/*.py`、`portfolio_manager.py`、§4 表 |
| "回测"（易被读作策略收益回测） | 评级方向打分；无订单、无仓位、无成本、无复利；作者自承不可重复 | `backtest.py` docstring、`BacktestSummary.render` |
| "交易员给出交易方案" | 方向词＋可选未校验价格；`position_sizing` 是自由文本；无执行接口 | `schemas.py` `TraderProposal`、`trader.py` |
| "从历史中学习"（记忆） | 学的是 5 日 alpha＋LLM 自写散文反思，不是交易盈亏归因；且只有成功结算者入选 | `memory/log.py`、`memory/reflection.py`、`memory/settlement.py` |
| "支持 crypto" | 仅标签切换＋Yahoo 现货代号（ETH-USD）；无 Binance、无永续、无资金费、无杠杆 | `agents/context.py`、`dataflows/symbols.py`、全仓无 binance/perp 命中 |
| 默认模型开箱即用 | 默认 `gpt-6-sol`/`gpt-6-luna` 的可用性本次未核实，须映射到己方供应商模型 | `default_config.py` |
| 论文/外部文章中的收益率数字 | 当前 repo 内无固定收益表格；README 明言结果不保证与已发表数字一致 | README.md 约 L405 |

---

## 11. vs

### 已验证（源码中有，本次通读确认）

- 11 节点 LangGraph 流水线与并行分析师子图（`graph/setup.py`）。
- 工具层点到点防护全套（`dataflows/date_window.py`、`agents/tools.py`、各 vendor 的 withhold 分支）与 lookahead 测试。
- 结构化决策输出（`schemas.py` 三 schema＋清洗函数）与运行配置记录（`run_settings`）。
- 记忆日志的 append-only、原子写、幂等记账、结算窗口语义（`memory/log.py`、`memory/settlement.py`）。
- 回测网格运行器与方向打分汇总（`backtest.py`），含其全部局限（§6）。
- Token/调用计数回调（`cli/stats_handler.py`），但无美元定价。

### 尚未验证（README 声称或本报告提议，未落地/未实测）

- 任何"TradingAgents 在某标的/某时段赚了 X%"的数字：repo 内无此表，README 已免责。
- 默认模型名的可用性与真实运行成本：本次未运行、未调用 LLM，无法核实。
- 多轮辩论（max_debate_rounds>1）是否比单轮更好：无对比实验数据。
- 记忆 lessons 是否提升后续决策质量：反思机制存在，但"提升"本身未经对照验证（反思由同一模型写，无 A/B）。
- 本报告提议的全部整合模块（M1–M6）：均为提案，**一个都未实施**，须按 §12 分阶段验收。

---

## 12. 最大的三个局限 / 风险

1. **信号本身不可信为交易依据**：最终评级来自 LLM 自由裁量，价格字段无校验、无成本模型、无 sizing 规则。即使方向打分好看，也推不出可执行的期望收益；向 ETHUSDT 永续移植时，资金费、滑点、杠杆、强平概念全部缺失，缺口不是"调参"能补的，是**模型缺失**。
2. **评价体系自我优待**：回测只算方向、不算钱；Hold 与 REVIEW 不计分；只有成功结算者进入记忆；单次采样无置信区间；标的与时段自选。五个口子全部朝"显得更好"的方向开——这与我方"证伪优先、未决不算通过"的审查文化直接冲突。
3. **辩论与风控的形式化**：默认 1 轮、固定顺序、同源证据、无结构化裁决；风控无硬约束。把它当作"多方制衡"会高估结论稳健性；正确用法是把它当作**一份写得很认真的研报模板**，而不是决策机制。

---

## 13. 分阶段整合方案（摘要；完整版见 `phased-plan.md`）

- **第一阶段（零代码，只改文档模板）**：落地 M1 反证备忘录模板、M2 假设-证伪登记表、M3 风险检查清单。准入：无（文档工作）；验收：下一次策略审计实际使用三份模板产出文档；回滚：删除模板文件。
- **第二阶段（小脚本，不动 TAE 核心）**：落地 M5 决策-结算日志格式（只读 TAE 输出）＋ M4 时间戳表述纪律。准入：第一阶段验收通过；验收：抽查 3 条审计记录可还原"决策时已知"；回滚：停用新格式，旧记录不受影响。
- **第三阶段（须用户另行批准）**：隔离沙盒红队实验——LLM 审计员只读 TAE 输出、只产审计意见，不进信号链。准入：第二阶段验收通过＋用户明确批准；验收：审计意见命中至少一个经人工确认的真实问题，且未导致任何规则变更（意见仅供参考）；回滚：关闭沙盒目录，TAE 不受影响。
- **不在路线图内**：LLM 信号接入 TAE、LLM 仓位建议、任何自动执行。任何涉及 TAE 代码或执行的改动都须用户另行批准，本报告不预设。
