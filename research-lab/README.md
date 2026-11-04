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

快照只写 `state/snapshots/`（本地-only），manifest 含“历史可交易集合未声明”注记。
本轮未安装 ccxt/pyarrow/duckdb（须另行申请），未测 VPS，未建资金费率快照。
