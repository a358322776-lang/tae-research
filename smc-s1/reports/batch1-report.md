# SMC-S1 第一批验收报告（2026-11-05）

- 批准：用户 2026-11-05 00:55 第一批工程开发批复（D1–D6 +
  7 条额外约束），仅限第一批范围。基线 main `56e0ee5`。
- 费用：$0。零正式回测，零参数优化，零实盘接口。
- 结论：第一批按批准范围完成；不产生任何收益结论（系统正确
  性优先，策略优势待第二批、第三批验证）。

## 1. 文件变更清单（22 个文件，全新增，零修改）

```
smc-s1/_deps.py            依赖加载（复用 validator.Bar 与统一成本函数）
smc-s1/config.py           冻结配置 v1.0（不可变）
smc-s1/structure.py        Pivot、HH/HL/LH/LL、Wilder ATR
smc-s1/bos.py              结构突破识别
smc-s1/fvg.py              FVG 检测
smc-s1/signals.py          交易信号状态机
smc-s1/execution.py        限价单/成交/撤单模拟（5m 代理 + 1m 保留接口）
smc-s1/risk.py             仓位、止损、止盈
smc-s1/cost_model.py       成本薄适配层（复用 A1 统一成本函数）
smc-s1/backtest.py         事件驱动回测骨架（合成驱动 + 段位守卫）
smc-s1/metrics.py          净 R、PF、回撤、置信区间、D5 评估门
smc-s1/splits.py           切分清单与数据哈希（D4）
smc-s1/tests/helpers.py    合成 Bar 构造
smc-s1/tests/test_structure.py
smc-s1/tests/test_bos_fvg.py
smc-s1/tests/test_signals.py
smc-s1/tests/test_execution.py
smc-s1/tests/test_risk_cost.py
smc-s1/tests/test_metrics_splits.py
smc-s1/tests/test_backtest.py
smc-s1/reports/smc-s1-rules-v1.0.md   冻结规则文档
smc-s1/reports/split-manifest-v1.json 切分清单与数据哈希
```

`git status` 证明：除 `smc-s1/` 外无任何文件变动——TAE、B1、
C5 策略代码与历史记录零修改（约束 1）。

代码哈希：以提交的 git blob 哈希为准，可用
`git ls-tree -r <commit> -- smc-s1/` 复核；工作树实测 SHA256
与 blob 内容一致（同一内容同一哈希）。

## 2. 测试结果

SMC-S1 合成数据测试 **47 项，0 失败**（structure 7、bos/fvg 7、
signals 7、execution 8、risk/cost 7、metrics/splits 8、backtest 3）；
全仓库复跑 **189 项，0 失败**（research-lab 142 + SMC-S1 47）。
测试覆盖：Wilder ATR 手算值、Pivot 确认时序（未确认不可用）、
OHLC 字段契约回归（D-ENG-1 类）、BOS 阈值与未确认结构排除、
FVG 缺口与镜像、状态机全流程/窗口过期/止损距离过滤/单仓、
严格穿透（相等不成交）/生效前不成交/同 bar 止损优先/1m 保留
报错、成本恒等式与资金费缺口拒算、D5 三档门、最终测试段
拒绝、切分边界与清单哈希。全部测试只用合成数据。

## 3. 批复逐项核对

| 批复 | 落实 |
|---|---|
| D1 15m ATR(14) Wilder RMA、收盘后可用 | `structure.atr_wilder`，值与 bar 对齐、首值在 period-1 处 |
| D2 5m 代理成交、保留 1m 接口、标记代理 | `execution` + `proxy_fill=True` 全链路标记；`OneMinuteBarSource` 明确报错 |
| D3 严格穿透、同 bar 保守规则、禁未来函数 | 穿透/生效/歧义三规则实现并测试；信号只用已收盘数据 |
| D4 50/20/30 切分、只建清单与哈希、不算最终测试绩效 | `splits.py` + 清单 JSON（`performance_computed: false`）；引擎拒跑 final_test |
| D5 100/200 笔门、INCONCLUSIVE | `metrics.evaluation_gate` 三档 + 阻塞 |
| D6 复用 A1 成本函数、薄适配、无公式复刻 | `cost_model.py` 只调统一模型原语；费率调用方传入+来源必填 |
| 约束 2–5 | 只开发所列模块；未跑回测；未调参；无实盘接口 |
| 约束 6 | 第二批、第三批未启动，须另批 |

切分实测（15m 238,978 根）：训练 [0, 119489) 2020-01-01→
2023-05-29；验证 [119489, 167284) →2024-10-24；最终测试
[167284, 238978) →2026-10-25。数据文件 SHA256 记入清单。

## 4. 未解决风险（须第二批前处理）

1. **R1**：1m 数据仍不存在；5m 代理模型的成交乐观/悲观偏差
   未量化，第二批前须决定是否拉取 1m 有界窗口。
2. **R5**：maker/taker 费率表未实测核实；成本适配层无硬编码
   费率，第二批须先核实费率来源并写入密封规格。
3. **R6**：资金费三项检查（重复时间戳、异常数值、结算时间
   完整性）未做；清单只含哈希与计数，未做内容校验。
4. **解释 I1**：止损锚取“最近反向结构点”的解释已冻结写入规则
   文档；用户若改判，须在第二批前以规则 v1.1 改判并重新登记。
5. **注册**：SMC-S1 尚未在登记库登记（SCREEN 评分 + 实质区别
   陈述）；按 v1.1，登记须在第二批任何实验之前完成。
6. **多时间框架对齐**：1H 趋势 + 15m 信号 + 5m 成交的时间戳
   对齐尚未实现（骨架为单 TF 合成驱动）；第二批接线时须以
   时间戳对齐测试钉住，不得以 bar 下标混用。
7. **仓位风险比例**：任务书未定每笔风险比例，`risk.py` 不设
   默认值；第二批须由用户定 risk_amount 口径后才可算仓位。
