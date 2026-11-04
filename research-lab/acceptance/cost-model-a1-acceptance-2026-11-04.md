# A1 统一成本函数验收报告（G3，2026-11-04）

- 批准：用户 2026-11-04 17:02（A1 先行，验收通过后再 B1；
  A2/A3/B2/B3 未批准；Stage 1 不结项、Stage 2 不启动）。
- 文件：`research-lab/cost_model.py`、`research-lab/test_cost_model.py`
  （13 项测试全过）、`research-lab/cost-specs-v1.json` +
  `.sha256`（密封规格，SHA256 `1d1acc8a…69599ee`）。
- 费用：$0。零正式回测，零策略搜索。

## 1. 代码变更

仅新增 4 个文件。`git diff` 证明 `tae-b1/`（B1/C5 引擎与历史
收益记录）零改动；既往测试套件复跑全部通过（registry 6 +
data_engine 18 + engine_verification 40 + funding 14 + validator 18
+ sandbox 11 + scheduler 6 + cost_model 13 = **126 项，0 失败**）。

## 2. 理论价 / 成交价分离与防重复扣除（批准条件逐项核对）

| 批准条件 | 实现 | 测试证据 |
|---|---|---|
| 明确理论价与实际成交价的区别 | `theoretical_*`（信号/规则参考价）与 `fill_*`（成交价）分字段；`gross_theoretical_pct` 只用理论价，`gross_fill_pct` 只用成交价 | `test_theoretical_untouched_by_slip`：改滑点不改变理论毛收益 |
| 防止滑点/价差重复扣除 | 唯一调整点 `fill_price()`：滑点+价差一次加总乘法；手续费永不折进成交价，单独列 `fee_pct`；资金费单独列；恒等式 net = gross_fill − fee − funding 逐项核对 | `test_fill_applied_once`（1.0011 一次加总、手续费不进成交价）、全部 golden 测试含恒等式断言 |
| 合成数据验证、可复现 | 全部测试用字面量合成数据，不导入、不调用引擎，不读历史记录 | B1 已知交易复现净 −1.0845R；C5 central 腿复现净区间 (−0.022284, −0.022084)；`test_reproducible` 两次运行逐项相等 |
| 不改 B1/C5 引擎与历史记录 | 无引擎导入（仅标准库 + 本模块），`tae-b1/` diff 为空 | 见 §1 |

费用基准显式化：`fee_mode` 写进密封规格——B1 用
`two_sided_entry`（2×0.0005，原文 `fee_r=2*FEE/sd`），C5 用
`fixed`（FEE_RT 0.001）；C5 档 exec（slip+spread 合并值）以
slip 字段一次计入、spread 字段置 0 并在规格 source 中注明，
防止合并值被拆成两项重复扣除。B1 止损滑点仅止损出场
（`exit_cost_applies_to=stop_only`），收盘出场不扣滑点——
与引擎原文一致。

资金费：精确和取 (t0, t1]；区间模式精确复现 C5 `funding_for_leg`
止损日语义（base = (t0, 触发日开盘] 之和，前缀取极值；上界
结算点排除）；覆盖缺口 >24h 拒绝计算（net=None），不插值。
区间语义在实现中曾错一次（前缀起点理解偏差），对照引擎原文
修正后通过——修正过程见测试 `test_c5_central_leg_interval` 与
`test_prefix_interval`。

## 3. 风险清单

1. **规格仍是审计常量，不是实时费率**：密封值取自引擎原文
   （币安 VIP0 档假设），未对照币安官方费率表实时核实；费率
   档变化时须重新审计并更新规格（须批）。
2. **C5 exec 合并表示法**：slip 字段承载 slip+spread 合并值是
   为防重复扣除的有意选择，阅读时须看 source 注明，不得误读
   为“纯滑点”。
3. **B1 费用近似**：`two_sided_entry` 沿用引擎的 2×FEE 近似
   （双边按入场名义计），与按实际成交名义计费有微差——这是
   引擎原文口径，本模块如实保留并显式标注，不擅自“修正”。
4. **未覆盖**：适配器（A2）、登记库字段（A3）均未批未建；
   本模块目前只能被测试调用，尚无生产调用方——这是有意为之
   的隔离，调用方须另批。
5. **密封机制局限**：与验证标准同理，哈希防篡改是“改动可发现”，
   不是访问控制（见 validator 报告）。

## 4. 验收结论与下一步

A1 按批准范围完成，13 项测试全过，引擎与历史零触碰。
**B1 须待用户验收通过本报告后开始**（顺序门）；A2/A3/B2/B3
继续禁止。G3 仍为部分完成（统一成本函数已建；`run_group`
全路径未验证、适配器未建——见结项核对表）。
