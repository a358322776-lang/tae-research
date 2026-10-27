"""TAE 无收益结构特征研究 · 任务二：描述性观察（零盈亏）。
输入 events_census.csv，输出 features_observation.md。
分档原则（结局盲分档）：连续特征的四分位切点只用该特征在已收复
序列中的分布算出，不按结局调整；不排序、不标最优、不找阈值。
样本量标注：n<30 标注"谨慎解读"，n<10 标注"仅记录、不可解读"。
主 horizon N=48 根 15m（12h，与序列过期窗同窗），次 horizon N=96
（24h）附录，两者都报告、不挑较好者。窗口末不足者记 truncated，
不进分母并单独报告截断数。
"""
import csv
from collections import Counter, defaultdict

import numpy as np

BASE = "/home/hatch/workspace/goals/100u-200u/files/tae-b1/structure-events"

rows = []
with open(f"{BASE}/events_census.csv") as fh:
    for r in csv.DictReader(fh):
        rows.append(r)

seqs = [r for r in rows if r["seq_id"].startswith("S")]
rec = [r for r in seqs if r["outcome"] == "reclaimed"]


def f(r, k):
    v = r.get(k, "")
    if v == "" or v is None:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def rate(sub, key):
    n = len(sub)
    if n == 0:
        return None, 0
    return sum(1 for r in sub if r.get(key) == "1") / n, n


OUT_KEYS = [("fell_back", "再次跌回带内"),
            ("fell_through", "收盘跌穿远沿"),
            ("new_swing", "形成新同向摆动"),
            ("i4a_invalidated", "I4-A 失效")]


def trend_end_same(sub, N):
    s = [r for r in sub if r.get(f"post{N}_trend_gate_end") in
         ("pass_same", "pass_opp", "fail", "na")]
    if not s:
        return None, 0
    return sum(1 for r in s if r[f"post{N}_trend_gate_end"] == "pass_same") / len(s), len(s)


def fmt_rate(x):
    return "—" if x is None else f"{x:.1%}"


def caution(n):
    if n < 10:
        return " ⚠仅记录、不可解读"
    if n < 30:
        return " ⚠谨慎解读"
    return ""


def table_for(N, bin_fn, pool):
    sub = [r for r in pool if r.get(f"post{N}_truncated") == "0"]
    bins = defaultdict(list)
    for r in sub:
        b = bin_fn(r)
        if b is not None:
            bins[b].append(r)
    lines = []
    for b in sorted(bins, key=str):
        g = bins[b]
        cells = [f"**{b}**", str(len(g))]
        for key, _ in OUT_KEYS:
            v, _ = rate(g, f"post{N}_{key}")
            cells.append(fmt_rate(v))
        v, _ = trend_end_same(g, N)
        cells.append(fmt_rate(v))
        lines.append("| " + " | ".join(cells) + " |" + caution(len(g)))
    return lines


def quartile_bins(values):
    return np.percentile(values, [25, 50, 75])


def qbin(v, qs):
    if v is None or np.isnan(v):
        return None
    if v <= qs[0]:
        return f"Q1 ≤{qs[0]:.3g}"
    if v <= qs[1]:
        return f"Q2 ({qs[0]:.3g},{qs[1]:.3g}]"
    if v <= qs[2]:
        return f"Q3 ({qs[1]:.3g},{qs[2]:.3g}]"
    return f"Q4 >{qs[2]:.3g}"


HDR = "| 分档 | n | 再次跌回带内 | 收盘跌穿远沿 | 新同向摆动 | I4-A 失效 | 窗口末趋势门同向 |"
SEP = "|---|---|---|---|---|---|---|"

sections = []
sections.append("# TAE 结构特征观察报告（无收益·探索性）\n")
sections.append("> **红线声明（首页大字）：即使不计算收益，只要根据后续价格表现选择定义，也仍然属于模型研究，不能当作独立验证；本阶段全部观察与结论均为探索性；最终验证必须用规则冻结之后新产生的前向数据。**\n")
sections.append("> 本报告及配套实验设计书均标注**未冻结、未验证，不得作为交易规则使用**。全文区分【客观事实】/【交易假设】/【未经验证的判断】。\n")

oc = Counter(r["outcome"] for r in seqs)
oc_oos = Counter(r["outcome"] for r in seqs if r["window"] == "oos")
oc_ins = Counter(r["outcome"] for r in seqs if r["window"] == "ins")
sk = [r for r in rows if r["seq_id"].startswith("X")]
sections.append("## 1. 普查窗口与序列结局分布\n")
sections.append("【客观事实】数据为 B1 同一套 ETH 15m 拼接缓存：238,978 根，2020-01-01T00:00Z → 2026-10-25T08:30Z（收盘），0 缺口。样本外/内分界 2025-10-17T02:00Z（按 bar OPEN 时间归属）。\n")
sections.append(f"【客观事实】候选 514 = 成序列 497 + 未成序列 17（P3 同根落选/与活跃序列重叠）。成序列结局：收复 {oc['reclaimed']}、远沿作废 {oc['voided']}、过期 {oc['expired']}、数据末尾未决 0。\n")
sections.append("| 窗口 | 成序列 | 收复 | 远沿作废 | 过期 | 未成序列 |\n|---|---|---|---|---|---|")
sections.append(f"| 全窗口 | {len(seqs)} | {oc['reclaimed']} | {oc['voided']} | {oc['expired']} | {len(sk)} |")
sections.append(f"| 样本外（≤2025-10-17T02:00Z） | {sum(oc_oos.values())} | {oc_oos['reclaimed']} | {oc_oos['voided']} | {oc_oos['expired']} | {sum(1 for r in sk if r['window'] == 'oos')} |")
sections.append(f"| 样本内 | {sum(oc_ins.values())} | {oc_ins['reclaimed']} | {oc_ins['voided']} | {oc_ins['expired']} | {sum(1 for r in sk if r['window'] == 'ins')} |")
sections.append("")
ec = Counter(r["e_outcome_b"] for r in seqs)
sections.append(f"【客观事实】已收复序列的 E 阶段（B 组参考字段，非 Phase B 接受）：filled {ec['filled']}、missed {ec['missed']}、E 超时 {ec['e_timeout']}、coincident 作废 {ec['coincident_void']}；未收复序列 {ec['no_reclaim']}（= 作废 + 过期）。\n")
sections.append("## 2. 后续结构结局的定义（零盈亏）\n")
sections.append("- **N**：收复根 r 之后的 N 根 15m，主 horizon N=48（12h，与序列过期窗同窗），次 horizon N=96（24h）。窗口末超出数据者记 truncated，不进分母。\n")
sections.append("- **再次跌回带内**：(r, r+N] 内任一 15m 收盘价落在 [blo, bhi] 内。\n")
sections.append("- **收盘跌穿远沿**：(r, r+N] 内任一 15m 收盘穿越远沿（多头 < blo，空头 > bhi）。\n")
sections.append("- **新同向摆动**：(r, r+N] 内经 k=2 确认的新摆动点（15m strict swings，确认根也在 horizon 内），且极值超越 b0 根极值（多头摆动高 > high[b0]，空头摆动低 < low[b0]）。\n")
sections.append("- **I4-A 失效**：按 v0.2 的 Θ 扫描，收复后窗口内首次出现 1H 收盘 ≤ Θ（多头）/ ≥ Θ（空头）。\n")
sections.append("- **窗口末趋势门同向**：窗口末收盘时刻的 v0.2 趋势门（严格早于规则）方向与序列方向一致的比例。\n")
sections.append("- **分档**：连续特征四分位切点只用已收复序列的特征分布算出（结局盲分档），不按结局调整；不排序、不标最优、不找阈值。\n")
sections.append("- **结局不是互斥分类**：同一序列可同时满足多项后续结局（如既跌回带内、又形成新同向摆动），各列发生率不得相加为 100%。\n")
sections.append("- **I4-A 吸收态提醒**：post 窗口内的 I4-A 失效指“首次失效落在收复后窗口内”；序列内已失效者按定义不可能再有收复后新失效，故按“序列内是否失效”分档时，已失效档的收复后新失效率恒为 0.0%，该数不是发现。\n")

pool48 = [r for r in rec if r.get("post48_truncated") == "0"]
pool96 = [r for r in rec if r.get("post96_truncated") == "0"]
sections.append(f"## 3. 主 horizon N=48 的描述性交叉（已收复序列 n={len(pool48)}，截断 {len(rec) - len(pool48)}）\n")
sections.append("### 3.0 全体基线\n")
lines = [HDR, SEP]
cells = ["**全体**", str(len(pool48))]
for key, _ in OUT_KEYS:
    v, _ = rate(pool48, f"post48_{key}")
    cells.append(fmt_rate(v))
v, _ = trend_end_same(pool48, 48)
cells.append(fmt_rate(v))
lines.append("| " + " | ".join(cells) + " |")
sections.append("\n".join(lines) + "\n")


def touches_bin(r):
    t = f(r, "band_touches")
    if t is None:
        return None
    return "3" if t <= 3 else ("4" if t <= 4 else ("5" if t <= 5 else "≥6"))


qs_w = quartile_bins([f(r, "band_width_atr") for r in rec if f(r, "band_width_atr") is not None])
qs_s = quartile_bins([f(r, "band_last_touch_lag") for r in rec if f(r, "band_last_touch_lag") is not None])
qs_d = quartile_bins([f(r, "i2a_depth_atr") for r in rec if f(r, "i2a_depth_atr") is not None])
qs_r = quartile_bins([f(r, "i2a_rebound_final_atr") for r in rec if f(r, "i2a_rebound_final_atr") is not None])
qs_rm = quartile_bins([f(r, "i2a_rebound_max_atr") for r in rec if f(r, "i2a_rebound_max_atr") is not None])


def pos_bin(r):
    v = f(r, "i2a_pos_final")
    if v is None:
        return None
    return "<0.25" if v < 0.25 else ("0.25–0.5" if v < 0.5 else ("0.5–0.75" if v < 0.75 else "≥0.75"))


def dwell_bin(r):
    v = f(r, "i2b_dwell_max_consec")
    if v is None:
        return None
    return "1" if v <= 1 else ("2" if v <= 2 else "≥3")


def trend_bin(r):
    g = r.get("trend_v02_at_b0", "")
    if g in ("pass_same", "pass_opp", "fail", "na"):
        return g
    # 兼容旧标签（方向值）
    if g in ("long", "short"):
        return "pass_same" if g == r["dir"] else "pass_opp"
    return "fail"


def i4a_bin(r):
    v = r.get("i4a_invalidated_during", "")
    return "已失效" if v == "1" else ("未失效" if v == "0" else None)


def i4b_bin(r):
    t0 = r.get("i4b_recheck_t0", "")
    rc = r.get("i4b_recheck_reclaim", "")
    if t0 == "na_no_touch" or rc == "na_no_touch":
        return None
    if t0 == "merged_into_reclaim":
        return f"合并重检={rc}"
    return f"t0={t0},收复={rc}"


def dir_bin(r):
    return f"{r['dir']}/{r['window']}"


for title, fn in [
    ("3.1 带质量：触碰次数（现行 find_levels 的有效触碰数）", touches_bin),
    ("3.2 带质量：带宽（ATR 倍数，四分位）", lambda r: qbin(f(r, "band_width_atr"), qs_w)),
    ("3.3 带质量：陈旧度（最后触碰距 b0 的 15m 根数，四分位）", lambda r: qbin(f(r, "band_last_touch_lag"), qs_s)),
    ("3.4 回踩深度（I2-A depth，ATR 倍数，四分位；仅已触碰序列）", lambda r: qbin(f(r, "i2a_depth_atr"), qs_d)),
    ("3.5 拒绝力度：收复时反弹幅度（I2-A rebound_final，ATR 倍数，四分位）", lambda r: qbin(f(r, "i2a_rebound_final_atr"), qs_r)),
    ("3.6 拒绝力度：窗口内最大反弹幅度（I2-A rebound_max，ATR 倍数，四分位）【注：已收复序列中 rebound_max 与 rebound_final 恒等，见 7】", lambda r: qbin(f(r, "i2a_rebound_max_atr"), qs_rm)),
    ("3.7 收盘位置分位（I2-A pos_final）", pos_bin),
    ("3.8 停留（I2-B dwell_max_consec：连续满足极值相交且收盘不穿越远沿的最长根数）", dwell_bin),
    ("3.9 趋势状态：b0 时 v0.2 趋势门（按与序列方向的关系）", trend_bin),
    ("3.10 趋势状态：I4-A 序列内是否失效", i4a_bin),
    ("3.11 趋势状态：I4-B 重检（t0 与收复根）", i4b_bin),
    ("3.12 方向与窗口（描述性拆分，不比较优劣）", dir_bin),
]:
    sections.append(f"### {title}\n")
    sections.append(HDR + "\n" + SEP)
    sections.append("\n".join(table_for(48, fn, rec)) + "\n")

sections.append(f"## 4. 次 horizon N=96 附录（已收复序列 n={len(pool96)}，截断 {len(rec) - len(pool96)}；与 N=48 同口径，不挑较好者）\n")
sections.append("### 4.0 全体基线\n")
lines = [HDR, SEP]
cells = ["**全体**", str(len(pool96))]
for key, _ in OUT_KEYS:
    v, _ = rate(pool96, f"post96_{key}")
    cells.append(fmt_rate(v))
v, _ = trend_end_same(pool96, 96)
cells.append(fmt_rate(v))
lines.append("| " + " | ".join(cells) + " |")
sections.append("\n".join(lines) + "\n")
for title, fn in [
    ("4.1 触碰次数", touches_bin),
    ("4.2 带宽四分位", lambda r: qbin(f(r, "band_width_atr"), qs_w)),
    ("4.3 陈旧度四分位", lambda r: qbin(f(r, "band_last_touch_lag"), qs_s)),
    ("4.4 回踩深度四分位", lambda r: qbin(f(r, "i2a_depth_atr"), qs_d)),
    ("4.5 收复时反弹四分位", lambda r: qbin(f(r, "i2a_rebound_final_atr"), qs_r)),
    ("4.6 停留", dwell_bin),
    ("4.7 b0 趋势门", trend_bin),
]:
    sections.append(f"### {title}\n")
    sections.append(HDR + "\n" + SEP)
    sections.append("\n".join(table_for(96, fn, rec)) + "\n")

sections.append("## 6. 最值得注意的模式（只描述、不评优）\n")
sections.append("### 模式一：收复后“回落”与“新摆动”并存，不是二选一\n")
sections.append("N=48 内，78.3% 再次跌回带内、80.7% 收盘跌穿远沿，同时 89.2% 形成新同向摆动；234/332（70.5%）同时满足跌回带内与新同向摆动，仅 36 笔两者皆无。N=96 内三项分别为 85.5%/87.0%/93.1%。【交易假设】“收复后干净离开”不是本普查中的常见形态；【未经验证的判断】这是否意味着“回踩完成”本身不足以描述收复后结构，待实验检验。\n")
sections.append("### 模式二：两种“趋势还在”的结构表述在收复后窗口内都极少维持\n")
sections.append("b0 时 v0.2 趋势门同向者 310/332，但窗口末仍同向者 N=48 仅 6.0%、N=96 仅 1.2%。I4-A 方面：序列内未失效的 159 笔中，157 笔（98.7%）在收复后 48 根内失效；序列内已失效的 173 笔在收复后窗口内的新失效率为 0.0%——该 0.0% 是吸收态定义所致，不是“失效后不再失效”的发现。机制描述（非结论）：Θ 取已确认摆动低的最大值，回踩低点一旦确认即抬升 Θ 使其贴近现价，此后一次 1H 收盘低于回踩低点即记失效。【未经验证的判断】Θ 是否过于贴近现价、是否应取其他统计量，属实验设计问题，不在本报告定论。\n")
sections.append("### 模式三：带质量分档中，“跌回带内”率随触碰次数与带宽上升\n")
sections.append("触碰 3/4 档跌回率 60.9%/58.5%，触碰 5/≥6 档 88.7%/86.1%；带宽 Q1 57.8% → Q4 88.0%。同时各档的跌穿远沿率（约 75–86%）与新摆动率（约 78–93%）未见同向梯度。机械性提醒：带宽越宽，带内区间越大，“跌回带内”在定义上越容易发生，故带宽档的梯度不能直接读作宽带更弱或更强；触碰次数档无此机械联系，但触碰数与带宽可能相关，本报告未做偏相关分解。\n")
sections.append("### 模式四（附带）：停留越长，序列内 I4-A 失效越多\n")
sections.append("停留 1/2/≥3 档的序列内失效率为 44.7%/60.3%/86.5%，收复后窗口内新失效率为 54.4%/39.7%/13.5%——后者下降是吸收所致（已在序列内失效者不再计入新失效），两数须合读，不可单读后者。停留窗口越长，序列内经历的 1H 收盘越多，Θ 被触及的机会也越多；本报告不分离“窗口长度”与“停留本身”的贡献。\n")
sections.append("## 7. 局限与算不出/数据不足的部分\n")
sections.append("- 【客观事实】本普查只覆盖 ETH 一只标的、一个 15m 周期；结论不可推广到其他品种或周期。【未经验证的判断】跨品种一致性未检验。\n")
sections.append("- 【客观事实】I2-A 的擦边锚点分类（D_graze、R_min、P_min、N）数值全部留空待拍板，本报告不做擦边/拒绝二分类，只报告连续特征分布。\n")
sections.append("- 【客观事实】I1-A 的时效上限 S 与带宽上下限 W_lo/W_hi 未冻结，本报告只报告带宽与陈旧度的四分位分布，不划合格/不合格。\n")
sections.append("- 【客观事实】I4-A 的 Θ 种子解释（b0 时最新已确认摆动低）是本普查的实现选择，v0.2 文本“自 b0 起”存在歧义；换种子定义会改变失效计数。\n")
sections.append("- 【客观事实】I4-B 重检中 t0 与收复根落在同一 1H bar 内的序列只做一次重检（以收复根为准），该子集在 3.11 中单列。\n")
sections.append("- 【客观事实】未收复序列（作废 140 + 过期 25）没有收复后窗口，故无后续结构结局；其 I2-A 特征在截断窗口上描述性计算，不与已收复序列的特征混算。\n")
sections.append("- 【客观事实】数据末尾附近的已收复序列 horizon 截断者不进分母；截断数见各节标题。\n")
sections.append("- 【客观事实】已收复序列中 rebound_max 与 rebound_final 恒等：收复根是窗口内首根收盘穿越近沿的 bar，故其收盘也是窗口内最利于反弹方向的收盘（多头最高收盘、空头最低收盘），3.6 与 3.5 两表必然相同，不构成独立证据。\n")
sections.append("- 【客观事实】I4-A 的 Θ 实现口径敏感性：本普查把“自 b0 起”读作摆动根收盘晚于 b0 的摆动点；若改读作“b0 之后才确认的摆动点”（含 b0 前最后两根内形成、b0 后才确认者），Θ（多头）只可能上调、失效只可能更多，不会逆转“收复后窗口内失效常见”的方向。\n")

with open(f"{BASE}/features_observation.md", "w") as fh:
    fh.write("\n".join(sections))
print("wrote features_observation.md")
print(f"rec={len(rec)} pool48={len(pool48)} pool96={len(pool96)}")
print("quartile edges: width", qs_w, "stale", qs_s, "depth", qs_d, "rebound", qs_r, "rebound_max", qs_rm)
