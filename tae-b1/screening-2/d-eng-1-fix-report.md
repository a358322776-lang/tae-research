# D-ENG-1 缺陷复现及隔离修复报告（分支 `fix/d-eng-1-ohlc-mapping`）

- 授权：用户 2026-11-04 12:43 第二条——批准隔离修复，不批准恢复
  C5 策略。原始 C5 代码、原始实验结果与缺陷记录保留在 main
  （`eb84663` / `a3ca2cc`），本分支仅含修复 + 回归测试 + 本报告。
- **未做**：未重新执行 C5 正式策略回测；未重算任何历史结果；
  未将 C5 重新加入候选池；`main()` 从未调用；
  `EXECUTION_APPROVED` 保持 `False`。

## 1. 缺陷复现

缺陷：`run_tier` 把标准 OHLC 行 `[open, high, low, close]` 原样
`tuple()` 传给按 `(open, low, high, close)` 解包的
`run_leg_prices`，high/low 互换。多头止损在 high ≤ stop 才触发
（应为 low ≤ stop），空头在 low ≥ stop 才触发（应为 high ≥ stop），
触发集是正确规则的子集。

复现（合成数据，与 `c5-ohlc-regression-tests.py` 同构）：
D+2 `[2400, 2420, 2360, 2410]`，D+3 `[2410, 2420, 2340, 2400]`
（真 low 2340 穿止损 2353.8816，high 2420 未穿）。原始代码判
`close`，修复后判 `stop`。复现方法：对 `eb84663` 的原始文件
运行同一回归测试，第一项出场断言失败（见 §3）。

## 2. 修复代码差异（本分支唯一生产代码改动）

文件：`tae-b1/screening-2/c5-exploratory-backtest.py`，共 3 处：

1. 新增 `ohlc_to_leg_day(row)`：显式字段名解包 OHLC 行，校验
   `high ≥ low/open/close`、`low ≤ open/close`，返回
   `(open, low, high, close)`；非法行抛错，不静默重排。
   `run_leg_prices` 文档注明输入约定为 `(open, low, high, close)`，
   调用方须经 helper 构造。
2. `run_tier` 内 `days.append(tuple(b[day]))` →
   `days.append(ohlc_to_leg_day(b[day]))`。
3. `main()` 内零执行成本复核的 days 构造同样改经 helper
   （同一缺陷的第二处调用点）。

未改动：`run_leg_prices` 力学、`funding_for_leg`、`build_equity`、
`verify()`、三档成本、事件/方向逻辑、任何结果文件。

## 3. 修复前后合成交易结果（同一合成事件，central 档，exec 0.0008）

| | 原始（`eb84663`） | 修复后（本分支） |
|---|---|---|
| 出场 | `close`，D+5（day 3） | `stop`，D+3（day 1） |
| 入场价 | 2401.92 | 2401.92 |
| 出场价 | 2398.08 | 2351.99849472 |
| gross | −0.00159872 | −0.020784 |
| net_lo / net_hi | −0.00369872 / −0.00369872 | −0.022284 / −0.022084 |
| 资金费区间 | (0.0011, 0.0011) | (0.0003, 0.0005) |

差异方向符合缺陷机理：原始代码把 high 当 low，止损触发过晚，
亏得更少——既往 C5 数字高估了该规则下的存活率，偏误符号不定，
不得当作冻结稿规则的证据。

## 4. 受影响历史实验范围（定性界定，未量化）

受影响：全部经 `run_tier` 计算的历史结果——`c5-exploratory-results.json`
三档（central/high/low）全部交易、placebo 对照、零执行成本复核，
以及引用这些结果的探索报告（`c5-exploratory-backtest-report.md` 等）
中的收益/回撤/胜率数字。凡涉及日内止损触发的交易都可能改变出场
与收益；仅收盘出场的交易不受影响。

精确受影响交易数与修正后收益**无法在不重跑正式回测的前提下确定**，
而重跑未批准，故本报告不给出量化修正数。如需量化，须用户单独
批准重跑并重新登记实验。

## 5. 新增回归测试结果

`tae-b1/screening-2/c5-ohlc-regression-tests.py`：6 项全过
（修复后）；对原始文件运行同一测试，出场断言失败，确证测试
能区分缺陷与修复：

1. gate-closed（执行门保持关闭）；
2. intraday-stop-via-ohlc（OHLC 日内止损，§3 数值逐项核对）；
3. close-exit-via-ohlc（无触发时收盘出场不变）；
4. original-passthrough-was-buggy（原样传入判 close、helper 传入
   判 stop——区分性证明）；
5. verify-gate（C5 自身 `verify()` 33 项 e2e + 资金费边界仍通过）；
6. helper-rejects-invalid-rows（非法 OHLC 行被拒）。

分支工作树另有 `c5-e2e-tests.py` 全过（未改动文件，复核用）。

## 6. 保留与处置

- 原始代码：main 分支 `eb84663`/`a3ca2cc` 未动；缺陷记录
  `research-lab/acceptance/stage1-item3-acceptance-2026-11-04.md`
  与验证器钉住测试未动。
- 原始结果：`c5-exploratory-results.json` 等结果文件未动（本分支
  `git status` 仅含本报告列出的 3 个文件）。
- C5 状态：仍退出候选池，永久归档；本修复不改变该状态。
- 分支处置待用户裁决：合并入 main / 保留分支备查 / 废弃。
  在裁决前，main 上的 C5 代码仍为原始缺陷版本，验证器钉住测试
  仍按“缺陷存在”断言——这是有意为之的记录一致性。
