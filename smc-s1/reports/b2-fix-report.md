# SMC-S1 B2-FIX 修复与预注册报告（2026-11-05）

- 批准：用户 2026-11-05 07:58（B2-PRE 有条件验收通过；B2-FIX
  范围 1–5）。基线 main `3b46959`。
- 费用：$0。**未跑正式回测、最终测试集未解锁、参数未改、
  TAE/B1/C5 未动、未接实盘。**全部测试只用合成数据。
- 结论：B2-FIX 5 项全部完成；B2 正式回测仍须单独批准。

## 1. 修复文件清单（只改 smc-s1/ 内文件）

新增：

```
smc-s1/anchor.py                  止损锚点解析器（唯一锚来源）
smc-s1/alignment.py               多时间框架事件时间定义与时序校验
smc-s1/access.py                  段访问控制 + 只追加哈希链访问日志
smc-s1/funding_gate.py            资金费三项门禁
smc-s1/tests/test_anchor.py       锚点解析器测试
smc-s1/tests/test_alignment.py    对齐测试（含未来函数对照）
smc-s1/tests/test_access.py       隔离测试（含篡改检出）
smc-s1/tests/test_funding_gate.py 资金费门禁测试
smc-s1/reports/spec-v1.0.md       SPEC v1.0 冻结文档
smc-s1/reports/spec-v1.0.json     SPEC v1.0 机器可读版（含文件哈希）
smc-s1/reports/b2-fix-report.md   本报告
```

修改（仅 smc-s1/ 内）：

```
smc-s1/signals.py      on_15m_close 改传 pivots、内部调解析器；
                       删除 opposite_swing_px 参数，外部止损值
                       无法再传入
smc-s1/backtest.py     删除 opposite_swing_fn 注入；改传 pivots；
                       入口加时间戳严格递增 + 等步长校验
smc-s1/cost_model.py   price_trade 调用统一模型前先过资金费门禁
                       （records=None 时跳过，unknown 语义不变）
smc-s1/tests/test_signals.py   改传 pivots（用例语义不变）
smc-s1/tests/test_backtest.py  删除注入函数；金标场景不变
```

未动：`config.py`（哈希 `3032bc1f…` 与第一批一致，参数值零
改动）、`structure.py`、`bos.py`、`fvg.py`、`risk.py`、
`execution.py`、`metrics.py`、`splits.py`、
`reports/split-manifest-v1.json`；TAE/B1/C5/research-lab 零改动。

## 2. 测试结果

SMC-S1 合成数据测试 **86 项，0 失败**：

| 文件 | 项数 |
|---|---|
| test_structure | 7 |
| test_bos_fvg | 7 |
| test_signals | 7 |
| test_execution | 8 |
| test_risk_cost | 7 |
| test_metrics_splits | 8 |
| test_backtest | 3 |
| test_anchor（新增） | 12 |
| test_alignment（新增） | 11 |
| test_access（新增） | 9 |
| test_funding_gate（新增） | 7 |

全仓库复跑：**228 项，0 失败**（research-lab 142 项含引擎验证
40 项 + SMC-S1 86 项）。金标场景保持：原 test_backtest 场景
仍产出 entry 105.75 / stop 99.0 的订单（止损锚现由 15m Pivot
解析器算出，与原注入值一致，证明接线正确）。

新增测试覆盖：无锚点/未确认锚点/错误方向/距离不合格/
confirmed_at 边界（==as_of 可用、+1 不可用、首根附近）；
高周期 bar 恰在决策时刻收盘可用、差 1ms 不可用、同时间收盘、
缺一根即检出、前缀运行与全量运行订单一致（未来函数对照）；
final_test 拒绝+日志记 denial、train/val 切片、越界拒绝、
日志追加与篡改/删行检出；资金费重复/抖动 61s+ 报错/异常值
报错/干净通过。`test_risk_cost` 的 coverage_gap 语义仍通过
（门禁不重复完整性检查）。

## 3. SPEC 文档与哈希

- `smc-s1/reports/spec-v1.0.md`（SHA256
  `1188a0469c16fb267d3d07a3435dd6b018ea344378e0d5bbe225bed95948ef42`）
- `smc-s1/reports/spec-v1.0.json`（机器可读，含 §1–§9 全部冻结
  内容 + 11 个关键文件 SHA256，已逐项重算核对一致；config
  哈希与第一批一致，证明参数未改）
- 冻结内容：策略规则与全部参数（逐字抄 config）、止损锚定义
  I1 + 解析器语义、数据时间边界与 4 文件 SHA256、5m 代理成交
  模型、中央档（maker 0.0002/taker 0.0005，标注待官方最终核实
  的研究假设）与保守档（费率加倍 + 每边滑点价差 0.0020，依据
  A1 密封规格 C5 high 档 exec）、资金费容差 60s、D5 样本门、
  7 项指标、PASS/INCONCLUSIVE/FAIL 判定规则、零参数试验 +
  3 项消融 + 成本加倍压力测试 + 训练/验证段内滚动样本外验证。

## 4. 数据隔离证明

- `access.SegmentStore`：只放行 train/validation 并返回
  `[start_idx, end_idx)` 切片；`final_test` 一律抛
  `FinalTestBlocked`，无任何解锁开关/后门；越界与未知段名
  均报错；每次访问尝试（含被拒）追加哈希链 JSONL 日志
  （段名、用途、结果、manifest 版本、调用方），`verify_log`
  校验链完整——测试证明篡改字段与删除行均被检出。
- 隔离测试输出摘要：`test_access` 9 项全过（拒绝+denial 日志、
  切片正确、越界拒绝、追加/篡改/删行检出、版本记录）。
- 诚实口径：隔离在 API 层执行，不宣称文件系统级隔离（同
  UID 可直接读文件）；该口径已写入 `access.py` docstring。
  默认日志路径 `research-lab/state/smc-s1-access-log.jsonl`
  （gitignored）；本批测试均用临时日志路径，未在默认路径
  写入生产日志。
- `backtest.py` 与 `metrics.py` 的 final_test 段位守卫保留；
  清单 `performance_computed: false` 未变；未读取任何真实
  数据、未计算最终测试集绩效。

## 5. SCREEN 复核

重申：SCREEN 总分 **6/10 暂定、临界准入，不得擅自提高**。
B2-FIX 未改动登记行——核查登记库：`HYP-20261105-01` 仍为
`screen_total=6`、`status=IDEA`；已用 `registry.audit` 追加
审计日志一条（actor=`b2-fix`、action=`screen-recheck`、
result=`ok`，记复核结论）；登记库为本地-only，不进仓。

## 6. 剩余风险

1. **R4/R6 已关闭（本批）**：锚点接线缺失与多时间框架对齐
   未实现已由 `anchor.py`/`alignment.py` + 39 项新测试覆盖
   修复；但 1H 趋势 + 15m 信号 + 5m 成交的真实三时间框架
   驱动仍属 B2 接线（单 TF 合成驱动未冒充多 TF），B2 须以
   时间戳对齐测试钉住。
2. **费率官方核实仍待补**：中央档为二级来源一致的研究假设，
   官方页文本未读到表、账户 VIP 档位未知；实盘前结论须重读。
3. **保守档滑点/价差接线待 B2**：当前适配层滑点/价差取 0；
   保守档运行前 B2 须扩展适配层经统一模型传入滑点/价差参数。
4. **1m 数据仍缺失**：5m 代理偏差未量化，B2 输出须全程标
   proxy_fill，不得称真实成交验证。
5. **隔离为 API 层**：强制隔离（只读访问器、密封目录）属
   B2/B3，尚未建设；同 UID 直接读文件不受本模块阻止。
6. **风险比例未定**：R 空间评估不受影响；资金映射/仓位结论
   须用户定 risk_amount 口径后才可出。
7. **SPEC 冻结后的改动流程**：任何参数/规则/成本假设改动须
   SPEC 新版本 + 重新登记 + 重新批准；B2 内零参数试验。

## 7. 待批事项

B2 正式历史绩效回测（训练/验证段，含 3 项消融、成本加倍
压力测试、滚动样本外验证）须单独批准；最终测试集运行须
B3 单独批准。本报告与 SPEC 冻结后，等待 B2 批准。
