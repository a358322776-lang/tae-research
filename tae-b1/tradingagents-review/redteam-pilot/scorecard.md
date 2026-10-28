# 红队对照测试记分卡（隔离沙盒小规模试点）

## 0. 结论先行

**打平：两臂全部 10/10，无一方更有效。** 普通审计（确定性脚本＋M3 机械执行）与单人 AI 红队审计在植入版上均检出全部 10 个缺陷（关键召回率 5/5、一般召回率 5/5、精确率 10/10、覆盖率 10/10），在干净版上误报均为 0。本测试**不能**据此宣称任何一方“显著更优/更差”——样本仅 10 个缺陷，1–2 个之差就是噪声，且两臂同时触顶，本测试无法区分二者。

**初步判断（只给判断，不搭建）：不值得为此搭建完整多智能体系统。** 单人 AI 审计已追平脚本；多智能体（辩论、评审团）只会增加成本、延迟与相关性风险，而本次测试未证明它能带来任何检出增益。值得保留的审计栈是“脚本＋单人 AI 审计”两层：脚本负责确定性、可复现的底线，单人 AI 负责语义解释与量级判断。若未来要再测，应上更难的缺陷（统计类、跨文件、生产规模）并做重复运行测方差，而不是先搭多智能体。

本测试回答的是“AI 审计是否比普通审计更有效”，不是“TAE 是否赚钱”。

## 1. 设计

- **沙盒**：`redteam-pilot/` 目录，与生产 B1/扫描器/执行器/前向观察系统零复制、零修改（生产文件 mtime 未动）。
- **微型引擎**：B1-like 机制（摆动簇关键带、单根收盘突破、回踩测试、EMA50 出场、maker/taker 费、资金费占位），合成数据，3 个品种（1 只提前结束、1 只含时间戳缺口）。干净版 332 行，植入版 328 行，均可独立运行。
- **植入缺陷**：10 个，每类 1 个（`key.json` 为答案，审计臂不得读取）。严重度按机制判定：关键 5 个（D01/D04/D05/D06/D07）、一般 5 个（D02/D03/D08/D09/D10）。
- **A 臂“普通审计”**：确定性脚本检查（C01–C10，类级别通用规则，先于植入定稿）＋M3 清单机械执行，禁止任何 LLM 自由推理。检查器全文见附录 A。
- **B 臂“AI 红队审计”**：单个 LLM 审计员（不是多智能体——多智能体正是本次要决定的对象），只读引擎文件＋10 类缺陷定义，不知道自己拿到的是植入版还是干净版，禁止读其他文件（盲法靠指令约束，非技术隔离）。
- **干净副本**：两臂各再跑一次干净版，误报单独计。
- **计分规则**：每条发现经协调员对照 `key.json` 逐条核验真伪后才计分，不凭审计员自述计分；严重度以 `key.json` 为准。

## 2. 两臂结果对照表

| 指标 | A 臂：普通审计（脚本＋M3） | B 臂：单人 AI 审计 |
|---|---|---|
| 关键缺陷召回率 | 5/5（100%） | 5/5（100%） |
| 一般缺陷召回率 | 5/5（100%） | 5/5（100%） |
| 精确率（植入版） | 10/10（100%，10 项 FLAG 全真） | 10/10（100%，10 条发现全真） |
| 干净副本误报数 | 0（脚本 10/10 PASS，M3 13/13 PASS） | 0（0 条发现；4 项边界事项明确未计入） |
| 干净副本关键误报 | 0 | 0 |
| 覆盖率 | 10/10 类 | 10/10 类 |
| 严重度一致率 | —（脚本不猜严重度） | 9/10（仅 D09 分歧，见 §5） |
| 成本 | 脚本运行约 0.02 秒/文件；检查器编写为一次性沉没成本，不计入边际成本 | 2 次审计会话，分钟级完成（未精确计时）；LLM 调用次数无法从协调员侧观测；美元成本不估算（无模型定价表） |

## 3. 逐类命中/漏检矩阵

| 缺陷 | 严重度（key） | A 脚本 | A 的 M3 | B 的 AI | 备注 |
|---|---|---|---|---|---|
| D01 未来函数（bars[j+1] 确认突破） | 关键 | C01 FLAG | M3-9 FAIL | 发现 | 三方全中；AI 另证 EMA 预算全序列但因果、find_levels 只传 bars[:j+1]，不构成同类问题 |
| D02 手续费遗漏（止损腿 fee=0.0） | 一般 | C02 FLAG | M3-6 FAIL | 发现 | 三方全中；AI 估算量级约 0.0125R/单 |
| D03 资金费遗漏（定义了 apply_funding 但零调用） | 一般 | C03 FLAG | M3-6 FAIL | 发现 | 三方全中；AI 指出 FUNDING_EVERY 亦未被使用 |
| D04 幸存者偏差（完整历史过滤剔除 SYM-B） | 关键 | C04 FLAG | —（无对应项） | 发现 | 脚本＋AI 命中；**M3 本身无幸存者偏差对应项，是 M3 的真实缺口** |
| D05 样本选择偏差（[400,900) 窗口标 VALIDATION） | 关键 | C05 FLAG | M3-13 FAIL | 发现 | 三方全中；AI 诚实注明代码未证明窗口系事后挑拣，缺陷在“同数据选参＋验证标签”本身 |
| D06 多重检验未校正（四档网格取最优） | 关键 | C06 FLAG | M3-7 FAIL、M3-8 FAIL | 发现 | 三方全中；见 §5 网格效应说明 |
| D07 同根排序（enter_same_bar 入场优先） | 关键 | C07 FLAG | M3-10 FAIL | 发现 | 三方全中；见 §5 触发说明 |
| D08 带陈旧（无带龄上限，last_idx 死字段） | 一般 | C08 FLAG | M3-11 FAIL | 发现 | 三方全中；AI 另指出 bars[-400:] 触摸窗口只是间接过滤，不能替代带龄上限 |
| D09 数据缺口（复制前一根 OHLC 静默补齐） | 一般 | C09 FLAG | M3-12 FAIL | 发现（但 AI 定为关键） | 三方全中；严重度分歧见 §5 |
| D10 执行价假设（止损按触发价精确成交） | 一般 | C10 FLAG | M3-6 FAIL | 发现 | 三方全中；AI 另指出入场固定百分比滑点亦未按开盘/跳空定价（未单独立项） |

**只有一方抓到的类：无。只有脚本抓到的：无。只有 AI 抓到的：无。两边都漏的：无。**

## 4. 成本对照

- **A 臂**：脚本运行约 0.02 秒/文件，确定性、可重复、边际成本趋近于 0。真实成本在检查器编写（一次性，约 200 行规则），不在每次运行。
- **B 臂**：2 次审计会话，分钟级完成。精确耗时未插桩；LLM 内部调用次数无法从协调员侧观测；美元成本不编造（无模型定价表，无法换算）。
- **成本结论**：边际成本上脚本碾压；AI 的增量价值不在检出数量，而在解释深度（量级估算、不确定性标注、死字段与间接过滤这类语义观察）与对模糊项的裁决纪律（干净版 4 项边界事项主动未计入）。

## 5. 诚实记录（计分前必须说明的事项）

1. **检查器 bug 修复 2 处（试点中发现，已修复并重跑，计分用修复后结果）**：C10 的“零值”正则误把 `0.0005` 判为 0（词边界 bug），致干净版初版误报 1 项；C04 的 `len(x)` 模式看不见 `len(s["bars"])` 下标，致植入版初版漏检 D04。两处修复均为通用模式修正（精确零值匹配、允许下标），非针对植入位置特写；修复后两版重跑，A 臂才达到上表成绩。初版成绩为：干净版 9/10 PASS（C10 误报）、植入版 9/10 FLAG（C04 漏检）。
2. **M3 缺口**：M3 清单 13 项中无幸存者偏差对应项，M3 单独只能得 9/10；D04 靠脚本 C04 检出。M3 是门禁清单，不是缺陷分类表，此缺口应记入 M3 的改进项，而非算 A 臂漏检（A 臂定义即脚本＋M3）。
3. **D06 网格效应可忽略**：植入版四档结果四舍五入后均为 3 笔、-0.05R，最优 0.5 实为并列首个值。D06 的缺陷（无校正的选择报告）在代码层面成立，但本次合成数据上数值效应为零。
4. **D07 未在运行中触发**：植入版全部网格运行中 `same_bar_entries` 恒为 0。D07 是代码路径缺陷，不是运行观测；审计对象是代码，此项计分不受影响。
5. **D09 严重度分歧**：AI 将 D09 定为关键（理由：补齐 bar 进入 EMA/ATR/序列计数，可产生不存在的信号时序），`key.json` 定为一般（理由：改变数量与数值，不伪造未来信息、不挑选样本）。计分以 `key.json` 为准，D09 计入一般召回；分歧本身记为 AI 严重度一致率 9/10。
6. **AI 干净版边界事项**：AI 列出 4 项未计入发现（出场费按入场名义计、EMA 出场按收盘价无滑点、缺口 bar 仍处理已有仓位/挂单、收尾未平仓位未计入）。4 项均不在 10 类口径内，不计误报；其中收尾未平仓位是真实观察，但超出本次口径，不影响记分。
7. **盲法局限**：两名 AI 审计员均被指令禁止读其他文件（含 `key.json`），报告中未见 `key.json` 原文引用、缺陷编号（D01–D10）或答案措辞；D09 严重度分歧与干净版边界事项进一步支持其独立阅读。但指令约束不是技术隔离，不能排除审计员推测测试结构的可能。
8. **运行数值不可比**：植入版（过滤后 2 品种、[400,900) 窗口、网格）3 笔 -0.05R，干净版（3 品种、全区间、固定参数）12 笔 -0.56R。两者宇宙与窗口不同，数值差异不得读作“植入版更优”或任何方向性结论。

## 6. 局限（必须写明）

- 样本仅 10 个缺陷，1–2 个之差就是噪声；两臂同时触顶，本测试无法区分二者，不得据此宣称“AI 红队显著更优/更差”。
- 单次运行、无重复：AI 的方差（同一审计重跑是否稳定）未测量；脚本是确定性的，AI 不是。
- 盲法靠指令约束，非技术隔离（见 §5.7）。
- 微型引擎不等于生产 B1：约 330 行、合成数据、简化项已在文件头注明（同 timeframe 趋势门、20 根缓存刷新、单种拒绝 bar、无日历日）。结论外推到生产 B1 需谨慎。
- 缺陷全部静态可见：本测试未包含统计类缺陷（如功效不足、分布外推）、跨文件不一致、时序数据库类问题——而这些恰是脚本模式最可能失效、AI 可能占优的领域。
- 本测试回答的是“AI 审计是否比普通审计更有效”，不是“TAE 是否赚钱”；记分卡通过 ≠ 策略可交易。

## 7. 初步判断：是否值得搭建完整多智能体系统

**不值得（基于本次证据）。** 理由：(1) 检出上打平，多智能体没有展示任何增量；(2) 单人 AI 已覆盖语义层，多智能体加的是协调成本与相关性风险（同一模型族、同批证据下的“辩论”可能只是形式分工——TradingAgents 审查中已见此模式）；(3) 真正的瓶颈不在审计员数量，而在缺陷难度与审计可重复性。

**更值得的下一步（按优先级）**：(1) 把 M3 补上幸存者偏差对应项（本次实测缺口）；(2) 若还要测 AI，用更难的缺陷集＋重复运行（测 AI 方差与脚本盲区），而不是先搭多智能体；(3) 脚本检查器作为常驻门禁（每次规则变更跑一遍，边际成本为零）；(4) 单人 AI 审计作为抽查层，重点看脚本看不见的语义项（量级、时序、跨项一致性）。

## 附录 A：Arm A 检查器全文（工作底稿，存放于 /tmp；本记分卡收录以便复现）

```python
#!/usr/bin/env python3
"""Arm A: deterministic generic audit checks for the red-team pilot.

Rules are class-level patterns derived from the 10 defect classes in the
red-team acceptance plan + the M3 checklist. They are NOT written against
any implant location: each rule states a generic integrity property and
fires wherever that property is violated. Run: python3 this.py <file.py>
Output: one verdict line per check (PASS/FLAG) with evidence lines.
Stdlib only.
"""
import ast
import re
import sys
import time

t0 = time.time()
path = sys.argv[1]
src = open(path, encoding="utf-8").read()
lines = src.splitlines()
tree = ast.parse(src)
low = src.lower()

def ev(n):
    return f"L{n}: {lines[n - 1].strip()[:110]}" if 0 < n <= len(lines) else f"L{n}"

def func_bodies():
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            seg = ast.get_source_segment(src, node) or ""
            out[node.name] = (node.lineno, node.end_lineno or node.lineno, seg)
    return out

F = func_bodies()
results = []

def verdict(cid, name, flagged, evidence):
    results.append((cid, name, "FLAG" if flagged else "PASS", evidence))

# C01 lookahead: future-bar reference inside signal/breakout/entry code.
flag, evd = False, []
for name, (a, b, seg) in F.items():
    if re.search(r"signal|breakout|pullback|entry|detect", name, re.I):
        for m in re.finditer(r"\bbars\s*\[\s*[a-zA-Z_]\w*\s*\+\s*([1-9]\d*)\s*\]", seg):
            flag = True
            evd.append(ev(a + seg[: m.start()].count("\n")) + f" [future index +{m.group(1)}]")
        if re.search(r"\.shift\s*\(\s*-", seg):
            flag = True
            evd.append(f"{name} uses shift(-) (future data)")
        if re.search(r"\bnext_bar\b|\bfuture_bar\b", seg):
            flag = True
            evd.append(f"{name} references next/future bar")
if re.search(r"\bbars\s*\[\s*[a-zA-Z_]\w*\s*\+\s*[1-9]", src):
    flag = True
    evd.append("file-level future index bars[i+k]")
verdict("C01", "lookahead (future bar in signal code)", flag, evd or ["no future-bar reference found"])

# C02 fee omission: any exit/close branch that zeroes fees, or lacks a fee term.
flag, evd = False, []
for name, (a, b, seg) in F.items():
    if re.search(r"close|exit", name, re.I):
        if re.search(r"\bfee\s*=\s*0(\.0)?\b", seg):
            flag = True
            evd.append(ev(a) + f" [{name} zeroes fee]")
        branches = re.split(r"if\s+reason\s*==|elif\s+reason\s*==", seg)
        for br in branches[1:]:
            if "fee" not in br.lower():
                flag = True
                evd.append(f"{name}: an exit branch has no fee term")
verdict("C02", "fee omission (exit leg)", flag, evd or ["all exit branches reference fee"])

# C03 funding omission: funding defined but never applied in run/P&L code.
defined = bool(re.search(r"def\s+apply_funding|FUNDING_RATE\s*=", src))
calls = len(re.findall(r"apply_funding\s*\(", src))
flag = defined and calls <= 1  # 1 = the def itself; a real call site would add more
evd = [f"funding defined={defined}, apply_funding call sites={calls}"]
verdict("C03", "funding omission (defined, never applied)", flag, evd)

# C04 survivorship: universe filter on history completeness.
flag, evd = False, []
for m in re.finditer(r".{0,60}len\s*\([^)]*\)\s*>=.{0,40}", src):
    if re.search(r"symbol|universe|history", m.group(0), re.I):
        flag = True
        evd.append("universe filter on length: " + m.group(0).strip()[:110])
if re.search(r"dropna\s*\(|complete_history|full_history_only", src):
    flag = True
    evd.append("completeness filter present in universe construction")
verdict("C04", "survivorship (completeness filter)", flag, evd or ["no completeness filter found"])

# C05 sample selection: eval window is a strict sub-window labelled validation.
flag, evd = False, []
m = re.search(r"EVAL_START\s*=\s*(\d+).*?EVAL_END\s*=\s*(\d+)", src, re.S)
if m and "validation" in low:
    flag = True
    evd.append(f"eval window [{m.group(1)}, {m.group(2)}) labelled validation (sub-window needs rationale)")
elif re.search(r"eval\w*\s*=\s*\(?\s*\d+\s*,\s*\d+", src, re.I) and "validation" in low:
    flag = True
    evd.append("named eval sub-window labelled validation")
verdict("C05", "sample selection (cherry window as validation)", flag, evd or ["no sub-window labelled validation"])

# C06 multiplicity: parameter grid + best pick + no correction term.
grid = bool(re.search(r"itertools\.product|for\s+\w+\s+in\s+\w*grid|for\s+\w+\s+in\s+\[", src)) and bool(
    re.search(r"best", low))
corr = bool(re.search(r"bonferroni|holm|correction|adjusted|family", low))
flag = grid and not corr
verdict("C06", "multiplicity (grid best-pick, no correction)", flag,
        [f"grid+best={grid}, correction term present={corr}"])

# C07 same-bar ordering (structural rule): the ambiguous-bar handler must
# resolve stop-first. FLAG if it can return an entry without any stop-first
# return in the same function (i.e. the combined trigger+stop case is not
# resolved conservatively before plain entry).
flag, evd = False, []
for name, (a, b, seg) in F.items():
    if re.search(r"same", name, re.I):
        has_stop_first = bool(re.search(r'return\s+["\']stop_first["\']', seg))
        returns_enter = bool(re.search(r'return\s+["\']enter', seg))
        if returns_enter and not has_stop_first:
            flag = True
            evd.append(f"{name}: entry returned with no stop-first return in handler")
        elif has_stop_first:
            evd.append(f"{name}: stop-first return present (conservative)")
verdict("C07", "same-bar ordering (entry-first)", flag, evd or ["no entry-returning same-bar handler found"])

# C08 stale bands: no BAND-age staleness mechanism (sequence expiry alone
# does not count: it limits sequences, not the age of the band itself).
flag = not bool(re.search(r"STALE|band_age\s*>|band.*stale", src, re.I))
verdict("C08", "stale bands (no band-age expiry)", flag,
        ["no STALE/band_age mechanism found"] if flag else ["band-age expiry mechanism present"])

# C09 gaps: missing bars are repaired/filled (ffill, fillna, copy-carry,
# "repaired" series, "carry forward") without any gap manifest/marking.
fill = bool(re.search(r"ffill|fillna|repaired|carry\w*\s+(the\s+)?last|fill\w*\s+missing|forward.?fill", src, re.I))
manifest = bool(re.search(r"gap_manifest|gap_mask|gap_flag|is_gap", src))
flag = fill and not manifest
verdict("C09", "data gaps (repaired, unmarked)", flag,
        [f"repair pattern={fill}, gap marking={manifest}"])

# C10 execution price: stop fill at exact stop price with no slippage term.
flag, evd = False, []
for m in re.finditer(r"fill\s*=\s*stop_price\b[^\n]*", src):
    line_no = src[: m.start()].count("\n") + 1
    if "slippage" not in m.group(0).lower():
        flag = True
        evd.append(f"L{line_no}: stop fill at exact stop price, no slippage term on the line: " + m.group(0).strip()[:110])
if re.search(r"SLIPPAGE_STOP\s*=\s*0(\.0*)?\s*(?:#.*)?$", src, re.M):
    flag = True
    evd.append("SLIPPAGE_STOP is zero")
verdict("C10", "execution price (stop fill, zero slippage)", flag, evd or ["stop fills carry a slippage term"])

# M3 mechanical gate evaluation (deterministic rules on the code).
m3 = []
m3.append(("M3-1 single-trade risk", "PASS" if re.search(r"RISK_PCT\s*=\s*0\.0[12]", src) else "FAIL"))
m3.append(("M3-2 total exposure", "PASS" if re.search(r"MAX_POSITION|POSITION_CAP|exposure", src, re.I) else "FAIL"))
m3.append(("M3-3/4 breakers", "PASS" if re.search(r"DAILY_LOSS_LIMIT|circuit|breaker", src, re.I) else "FAIL"))
m3.append(("M3-5 leverage cap", "PASS" if re.search(r"MAX_LEVERAGE\s*=\s*(1?\d|20)\b", src) else "FAIL"))
cost_ok = (not results[1][2] == "FLAG") and (not results[2][2] == "FLAG") and (not results[9][2] == "FLAG")
m3.append(("M3-6 cost triple (fee+funding+slippage)", "PASS" if cost_ok else "FAIL"))
m3.append(("M3-7 sample power", "PASS" if re.search(r"MIN_TRADES|power|sample.*note", src, re.I) else "FAIL"))
m3.append(("M3-8 multiplicity alpha", "PASS" if corr else "FAIL"))
m3.append(("M3-9 no lookahead", "PASS" if results[0][2] == "PASS" else "FAIL"))
m3.append(("M3-10 same-bar conservative", "PASS" if results[6][2] == "PASS" else "FAIL"))
m3.append(("M3-11 band staleness", "PASS" if results[7][2] == "PASS" else "FAIL"))
m3.append(("M3-12 data gaps", "PASS" if results[8][2] == "PASS" else "FAIL"))
m3.append(("M3-13 forward validation only", "PASS" if "validation" not in low or results[4][2] == "PASS" else "FAIL"))

print(f"FILE: {path}")
for cid, name, v, evd in results:
    print(f"{cid} {v} :: {name}")
    for e in evd:
        print(f"    - {e}")
print("M3 mechanical:")
for name, v in m3:
    print(f"  {v} :: {name}")
print(f"ELAPSED: {time.time() - t0:.2f}s")
```

## 附录 B：运行输出摘要

- 干净版：`SYM-A 7 单 -0.37R，SYM-B 1 单 -0.06R，SYM-C 4 单 -0.13R，TOTAL 12 单 -0.56R`，样本低于 MIN_TRADES，标注 exploratory only；缺口 manifest 1 条（SYM-C）。
- 植入版：四档网格均为 `3 单 -0.05R`（SYM-A 3 单，SYM-C 0 单；SYM-B 被 D04 剔除），`same_bar_entries` 恒为 0，headline 为 `VALIDATION: best multiplier=0.5`。
- 两版宇宙与窗口不同，数值不可直接比较。
