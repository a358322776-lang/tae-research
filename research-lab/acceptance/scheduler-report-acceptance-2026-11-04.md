# 调度器与周报模板验收报告（Stage 1 第六项，G6/G7）

- 文件：`research-lab/scheduler.py`、
  `research-lab/test_scheduler_report.py`（6 项检查全过）。
- 授权：用户 2026-11-04 12:43 第四条——**只开发，不启动**。
  调度器默认关闭，禁止接入现有生产 cron；周报为模板（DRAFT），
  不发送、不含策略收益结论。

## 1. 调度器

- 状态机：PENDING → RUNNING → SUCCEEDED；失败时按 attempts ≤2
  回 PENDING，耗尽后终态 FAILED，不再分派（无无限循环）。
- 默认关闭：`Scheduler(enabled=False)`；关闭时 `tick()` 返回
  `ran=0` 且不产生分派记录（测试已证：仅 submitted 一行日志）。
- 启用须显式 `enable(by=...)` 并留名；启用状态仅内存，不写任何
  cron/系统配置。本模块无 cron 集成、无 APScheduler 依赖、无线程/
  子进程/网络（AST 级检查已证）；调度器自身不执行代码，只把任务
  分派给调用方提供的 handler。
- 状态变迁只追加 `scheduler-log.jsonl`（本地-only，`state/` 目录）。
- 生产 cron 现状：未改动（本 VM 无 crontab 命令；仓库内现有生产
  cron 配置文件未被触碰，`git status` 无相关修改）。

## 2. 周报模板

- `build_weekly_report()` 生成 Markdown 草稿，七节齐全（测试逐节
  断言）：研究任务数量、实验登记状态、失败任务与错误原因、
  数据质量问题、资源使用情况、安全门禁状态、下一阶段待审批事项。
- 缺数据写“无/未知”，不编造数字；调用方须保证数字来自登记库/
  日志真实汇总。
- `collect_safety_gates()` 只读采集：验证标准密封状态、C5 执行门、
  live 门（`.live-ok` 是否存在）、调度器开关、自主研究权限状态。
  实测：标准 SEALED_OK、C5 门 CLOSED、live 门 CLOSED、调度器
  DISABLED、自主研究 NOT_APPROVED。

## 3. 未做事项（边界）

未创建/修改任何 cron、未启动调度器、未发送周报、未接入
APScheduler、未连接 Codex/验证器自动运行。周报的首次真实生成
与发送须 Stage 2 批准。
