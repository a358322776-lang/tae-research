# research-lab（自主策略发现实验室 · Stage 1）

> 依据：实施方案 v1.1（HEAD `4dc52e9`）§2/§6/§8；Stage 1 建设批准见 `tae-b1/approvals/approval-2026-11-04-v11-stage1.md`。
> 本目录只放代码与 schema；运行状态（SQLite 库）放在 `research-lab/state/`，该目录已入 `.gitignore`、永不进仓（库内只有登记元数据，仍按本地-only 处理，避免二进制文件进仓）。

## 文件

| 文件 | 说明 |
|---|---|
| `registry-schema-v1.sql` | 登记 schema v1：rounds / hypotheses / experiments / attempts / multiplicity / knowledge / budgets / audit_log；attempts、knowledge、audit_log 只追加（触发器禁 UPDATE/DELETE） |
| `registry.py` | 登记实现（标准库 only）：计数器硬上限（每轮假设 ≤ 3、每周正式实验 ≤ 20）、SCREEN 打分（≥ 6/10 且实质区别 ≠ 0）、指纹查重、只追加写入 |
| `test_registry.py` | 单元测试：计数器拒绝、SCREEN 门槛、指纹重复拒绝、只追加触发器 |

## 使用（只读示例，不启动策略搜索）

```bash
# 初始化空库（默认位置 research-lab/state/registry.sqlite）
python3 -c "import sys; sys.path.insert(0, 'research-lab'); import registry; registry.init_db('research-lab/state/registry.sqlite'); print('ok')"

# 跑测试（只用临时库，不碰生产库）
python3 -m unittest discover -s research-lab -p "test_registry.py" -v
```

## 规则

- 实验 ID：`EXP-YYYYMMDD-NNN`；假设 ID：`HYP-YYYYMMDD-NN`；轮次 ID：`ROUND-YYYY-Www`。ID 永不复用。
- 更正历史只能追加新行，不得 UPDATE/DELETE 历史行；触发器会直接拒绝。
- 计数器超限时登记函数抛错，调用方不得绕过、不得改上限（上限变更须用户批准）。
- 本模块不读、不写交易接口，不接触密钥与冻结目录，不产生收益数字（收益数字只由回测引擎产出）。
- 策略搜索尚未开放：登记库现为空库（0 假设、0 实验），Stage 2 试运行批准前不得登记任何真实假设。

## 数据引擎（Stage 1 第二项，2026-11-04 验收）

| 文件 | 说明 |
|---|---|
| `data_engine.py` | 仅标准库：公开接口只读取数、质量检查、快照写入（SHA256 + 只读 0o444）、哈希复核、ledger 只追加、连通性探针 |
| `fetch_snapshot.py` | 单标的快照 CLI；取数层丢弃未收盘 bar（记入 manifest），质量失败不写快照 |
| `probe_connectivity.py` | 固定 4 个只读探针（镜像 ping/klines/fundingRate + 直连 fapi ping），不重试，不存响应体 |
| `test_data_engine.py` | 18 个测试，全过；验收记录见 `acceptance/snapshot-connectivity-2026-11-04.md` |

## 引擎验证（Stage 1 第三项第 1 条，2026-11-04 验收）

| 文件 | 说明 |
|---|---|
| `engine_verification.py` | 只读导入 B1/C5 引擎（冻结代码零改动；C5 执行门保持关闭）；独立手算参考 + 合成数据构造 |
| `test_engine_verification.py` | 40 项检查全过：B1/C5 已知答案 ETH 交易、费用/滑点/资金费/权益/回撤、可复现、无未来泄漏（行为级）；含缺陷 D-ENG-1 钉住测试 |

**缺陷 D-ENG-1**：C5 `run_tier` 把标准 OHLC 行原样传给按 `(open, low,
high, close)` 解包的 `run_leg_prices`，high/low 互换，止损触发集小于
文档规则。既往 C5 收益数字不可信为文档规则估计；C5 已退出候选池，
本轮不修复，修复须另批。验收记录见
`acceptance/stage1-item3-acceptance-2026-11-04.md`。

## 资金费率快照管道（Stage 1 第三项第 4 条，2026-11-04 验收）

| 文件 | 说明 |
|---|---|
| `funding_snapshot.py` | 资金费质量检查（单调/无未来/缺口≤24h，8h 网格对齐）、只读冻结、哈希复核、ledger 只追加 |
| `fetch_funding_snapshot.py` | 单标的资金费快照 CLI（公开接口，limit ≤ 100） |
| `test_funding_snapshot.py` | 14 个测试，全过（离线合成数据） |

快照只写 `state/funding-snapshots/`（本地-only）。仅管道验证：不恢复
CA-1/P4，不做资金费率策略回测。

## 独立验证器 / 沙箱 / 调度器（Stage 1 第四～六项，2026-11-04 验收）

| 文件 | 说明 |
|---|---|
| `validator.py` + `validation-standards-v1.json`（密封） | 时间边界/可用时间/字段契约（`Bar`）/成本/基准复现/防篡改；18 项测试全过；含 D-ENG-1 回归与漏网证明 |
| `engine-contract-audit-2026-11-04.md`（acceptance/） | B1 等 8 个引擎/文件组的契约审计：换位只在 C5 发现，其余未发现同类缺陷；未验证清单见报告 |
| `codex_sandbox.py` | `unshare --net` + rlimits + env 白名单 + AST 扫描；11 项安全测试全过；`run_codex_task` 一律拒绝（自主研究未批） |
| `scheduler.py` | 状态机 + 重试（≤2）+ 默认关闭（无 cron 集成）；周报模板七节齐全（DRAFT）；6 项测试全过 |

验收报告见 `acceptance/validator-acceptance-2026-11-04.md`、
`acceptance/sandbox-safety-acceptance-2026-11-04.md`、
`acceptance/scheduler-report-acceptance-2026-11-04.md`；
结项核对与 Stage 2 条件见 `acceptance/stage1-closeout-checklist-2026-11-04.md`、
`acceptance/stage2-startup-conditions-2026-11-04.md`。
Stage 1 暂不正式结项，Stage 2 只批设计/准备/隔离环境建设。

## 依赖（Stage 1 第三项第 2 条，2026-11-04 核实）

隔离 venv `~/workspace/tae-research-venv/`（仓库树外，不进仓）：ccxt==4.5.91、
pyarrow==26.0.1、duckdb==2.0.0，锁定见 `requirements-lock.txt`，往返验证
通过。生产代码零导入；实际接入与格式迁移须另批。详见
`acceptance/dependency-review-2026-11-04.md`。本轮 VPS 复测：镜像 200、
直连 fapi 451（2026-11-04T04:37Z 时点测量），见 Stage 1 第三项验收报告 §3。

快照只写 `state/snapshots/`（本地-only），manifest 含“历史可交易集合未声明”注记。
