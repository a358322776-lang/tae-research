# Codex 沙箱安全验收报告（Stage 1 第五项，G5）

- 文件：`research-lab/codex_sandbox.py`、
  `research-lab/test_codex_sandbox.py`（11 项检查全过）。
- 授权：用户 2026-11-04 12:43 第三条。沙箱已建并通过安全测试；
  **自主研究权限未开放**：`run_codex_task()` 一律抛 `NotApprovedError`，
  Codex 任务执行须 Stage 2 单独批准 + API 计量手段。

## 1. 隔离机制（本 VM 实测）

| 要求 | 实现 | 测试证据 |
|---|---|---|
| 不访问交易密钥 | env 白名单（仅 PATH/HOME/TMPDIR/LANG），HOME/TMPDIR 指向工作目录；继承 env 全丢弃 | env 构造测试：调用方标记不在沙箱 env 内 |
| 不挂载生产凭据 | 工作目录为全新临时目录；无任何凭据/密钥文件挂载或复制 | 工作目录内仅 task.py；写操作测试确认文件只落工作目录内 |
| 不具备实盘下单权限 | 沙箱内无密钥、无网络、无交易接口访问路径；Codex 入口拒绝 | 网络测试 + Codex 拒绝测试 |
| 默认限制网络访问 | `unshare --net`（独立网络命名空间），fail-closed：unshare 不可用时拒绝运行 | 绕过 AST 扫描的 socket 连接尝试被挡（Network unreachable），返回码非 0 |
| 限制 CPU/内存/磁盘/时间 | rlimits（CPU/地址空间 2GiB/单文件 100MB/进程数）+ wall-clock 超时 | 死循环 3 秒超时被杀；内存 hog（128MB 限额）被杀 |
| 代码执行与验证规则管理权限分离 | 验证标准/登记库在工作目录外；运行前后哈希复核受保护文件 | 受保护文件测试：运行后哈希不变；改动可被发现 |
| 禁止未经批准的生产部署 | 沙箱无部署路径、无生产写权限声明；`run_codex_task` 拒绝 | 拒绝测试通过；模块内无部署代码 |

AST 预扫描（lint 层）：拒绝 socket/subprocess/os/shutil/ctypes/
urllib/requests/http/asyncio/multiprocessing 等导入，拒绝 eval/exec/
`__import__`，拒绝绝对路径/`..` 路径的 `open()`。扫描是第一层，
运行时隔离是第二层——网络测试特意绕过扫描以证明第二层独立生效。

## 2. 残留风险（必须如实记录）

1. 本 VM 无 docker/podman/firejail/bwrap；v1 **不做 mount 命名空间
   bind 隔离**，文件隔离靠 cwd + AST 扫描 + env 隔离 + 事后哈希复核。
   有决心的攻击代码可能经未拦截路径访问文件系统。v1 只适用于
   “受监督的、已扫描的代码片段”，不得宣传为“可放心跑任意代码”。
2. 沙箱以同一 UID 运行（本 VM exec 为 root）；UID 隔离与 mount 隔离
   是 Stage 2 前须复核的加固项（容器/独立 VM 主机）。
3. `unshare --net` 在本 VM 实测可用；换主机须重测探针
   `network_isolation_available()`，不可用时沙箱拒绝运行（fail-closed）。
4. 资源限制为进程级 rlimits + 超时；多进程/线程逃逸受 NPROC 与
   CPU 限额约束，但未做 cgroup 级计量——资源计量属 Stage 2 条件。

## 3. 结论

沙箱 v1 达到“安全测试通过、暂不开放”的状态：11 项安全测试全过，
Codex 入口关闭。开放自主研究权限前，须另批：① 加固方案复核
（mount/UID 隔离或容器主机）；② API 花费计量；③ Stage 2 试运行
监督方案。三者均未批准。
