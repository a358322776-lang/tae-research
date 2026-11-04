# 依赖核实与隔离安装记录（2026-11-04）

授权：用户 2026-11-04 12:31 第 2 条——先核实必要性/兼容性/具体版本，
仅在隔离虚拟环境中安装实际需要的依赖，固定版本并记录安装结果，
不修改生产环境；系统级安装/生产变更/新增费用另行申请。

## 1. 必要性核实（安装前）

| 依赖 | 方案中的用途 | 当前代码是否需要 | 本轮结论 |
|---|---|---|---|
| ccxt | Data Engine 多 venue 统一行情/资金费接口（方案 §6） | 否：现有快照只用 urllib + 币安公开行情镜像，已跑通 | 仅在 venv 内安装做兼容性验证；**生产代码零导入**，实际接入须另批 |
| pyarrow | Parquet 快照格式（方案 §6） | 否：当前快照为 JSON，质量门/哈希已跑通 | venv 内安装 + 写/读往返验证；Parquet 格式迁移本身未做、须另批 |
| duckdb | Parquet 上的分析查询（方案 §6） | 否：当前无分析查询 | venv 内安装 + 读 Parquet 验证；分析查询未做 |

三者均不是本轮引擎验证/资金费快照的运行时依赖。安装目的只有
一个：证明在当前 Python 3.12.3 环境下可装、可导入、可往返，
把版本锁定下来，避免将来真正需要时才发现不兼容。

## 2. 隔离安装结果

- 环境：Python 3.12.3（本 VM 系统 Python）。
- 虚拟环境：`~/workspace/tae-research-venv/`（仓库树之外——venv 内的
  第三方库源码含 `BEGIN ... PRIVATE KEY` 字样（ccxt/cryptography 的
  测试与代码常量），放在仓库内会触发凭证扫描误报，故 venv 必须在
  仓库树外；`python3 -m venv`，未动系统 Python；安装后系统 Python
  仍无法 `import ccxt/pyarrow/duckdb`，已实测确认生产环境未改）。
  已用锁定文件在新位置完整重建一次，版本与往返验证均一致。
- 安装命令：`.venv/bin/pip install ccxt pyarrow duckdb`（pip 24.0，
  公共 PyPI 免费包，费用 $0；无系统级安装）。
- 锁定版本（`requirements-lock.txt`，`pip freeze` 全量，含传递依赖）：
  - ccxt==4.5.91
  - pyarrow==26.0.1
  - duckdb==2.0.0
  - 其余传递依赖见锁定文件（aiohttp/cryptography 等，随 ccxt 引入，
    仓库代码目前不导入它们）。
- `.venv/` 已入 `.gitignore`，不进仓；可凭锁定文件重建。venv 实际位于
  仓库树外的 `~/workspace/tae-research-venv/`（仓库内第三方库源码会
  触发凭证扫描误报，见上）。
- 体积：venv 约 374MB（本地-only 成本，重建即删即建）。

## 3. 兼容性往返验证（venv 内，离线，无交易所网络请求）

- ccxt：`__version__ 4.5.91`，104 个交易所，含 `binance`；
  `ccxt.binance()` 可离线实例化（未调用任何 fetch/load_markets）。
- pyarrow：`26.0.1`，写/读 Parquet 往返 2 行一致。
- duckdb：`2.0.0`，`read_parquet` 计数 2、求和 -0.0001 一致。
- 结论：ROUNDTRIP OK（2026-11-04 实测）。

## 4. 风险与边界

- venv 体积大（374MB），仅本地存在；磁盘剩余充足（148GB，11-04 测），
  不影响生产。
- 锁定版本是“装机时点”的最新版；将来重建时如需复现须用锁定文件
  全量安装，不可用浮动版本。
- ccxt 接入交易所、Parquet/DuckDB 格式迁移、任何依赖升级，均不在
  本轮授权内，须另行申请。
- 系统 Python、生产 cron、生产配置均未改动。
