# 独立验证器测试报告（Stage 1 第四项，G4）

- 文件：`research-lab/validator.py`（仅标准库）、
  `research-lab/test_validator.py`（18 项检查全过）、
  `research-lab/validation-standards-v1.json` + `.sha256`（密封标准）。
- 授权：用户 2026-11-04 12:43 第一条。验证器只检查、不修复、
  不运行策略；参考算术独立重写，与引擎/上一轮验证无共享代码。

## 1. 覆盖与结果

| 授权要求 | 实现 | 测试证据 |
|---|---|---|
| 训练/验证/最终测试集时间边界 | `check_split`（严格有序、互不重叠）、`check_event_within_split`（事件窗口不得跨界） | 重叠/跨界/空区间均判失败 |
| 数据时间戳、可用时间、信号时间 | `check_bars`（单调/重复/缺口/截止）、`check_availability`（成交 ≥ 信号收盘且 ≥ 数据可用时间） | 早于收盘/可用时间均判失败 |
| 未来函数与标签重叠 | `check_no_label_overlap` + `static_scan`（仅提示）+ 行为级“追加未来数据不改变结果”模式（上一轮引擎测试已证） | 标签提前开始判失败；扫描产 REVIEW 级提示，永不单独定罪 |
| OHLC 字段顺序与类型契约 | `Bar`（显式字段名；`from_ohlc_row`/`from_klines_row`/`from_dict`；歧义行拒绝）、`audit_day_builder` | 歧义 5 列行、高<低、低>开盘等均拒绝 |
| 成交时序、手续费、滑点、资金费率 | `check_stop_exit`、`check_fee_r`、`funding_exact_sum`、`check_funding_interval`（前缀极值）、`check_drawdown` | 止损价/费率/区间边界均含正反用例 |
| 基准比较与结果复现 | `benchmark_return`/`check_benchmark`、`check_reproducibility` | 基准错位/非确定性均判失败 |
| 防篡改（最终测试集与验证标准） | `seal_directory`/`verify_sealed_directory`（哈希清单，改动可发现）；`load_sealed_standards`（哈希不符拒绝运行） | 改文件/增文件均被发现；标准被改后验证器拒绝 |

密封标准 SHA256（`validation-standards-v1.sha256`）：
`739d2b7ff4d046625ebf9d5912f07ebc13c610bd15c40c34598492549653914b`。
标准内容：成本常量、三档费率、资金费窗口 `(t0,t1]`、切分规则、
容差、沙箱/预算上限。改动标准须同步更新哈希记录并经用户批准，
否则验证器拒绝——这是“改动可发现”，不是访问控制（见 validator
模块文档）。

## 2. D-ENG-1 回归测试与漏网原因证明

- 回归：`audit_day_builder` 对原始 passthrough 构造（OHLC 行原样作
  腿输入）判缺陷（`field-order mismatch`），对 `Bar.to_leg_day()` 契约
  转换判通过（`test_validator.py::test_audit_day_builder_flags_raw_passthrough`）。
- 漏网证明（`test_why_existing_tests_missed_d_eng_1`，三段同时成立）：
  1. C5 `verify()` 通过（33 项 e2e + 资金费边界）；
  2. 同一日数据：OHLC 顺序腿函数判 `close`，契约顺序判 `stop`，
     边界审计判失败；
  3. 结论：旧门从未覆盖“OHLC 行 → 腿输入”这一步——腿函数按自身
     约定正确，`valid_bar` 按 OHLC 正确，缺陷只活在交接处。
     今后任何引擎接入须先过 `audit_day_builder`，这是强制关口。

## 3. 局限

- 静态扫描只能提示，不能证明无未来函数；行为级对照（截断/追加未来
  数据）须由各引擎的对照测试补足。
- 密封是哈希检测，不是权限隔离；能改标准又能改哈希记录者仍可绕过，
  但改动留痕于 git。最终测试集的真正隔离（独立目录 + 只读权限）
  属 Stage 2 启动条件（见 Stage 2 清单）。
- 验证器未覆盖：策略逻辑正确性、标的池 survivorship、实盘执行
  （撮合/拒单/部分成交）——均不在本阶段授权内。
