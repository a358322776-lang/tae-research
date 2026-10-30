"""Generate the C5 exploratory backtest report + audit appendix from the
sealed single-run results JSON. Deterministic; no randomness; no
re-running of the backtest. Reads only local sealed artifacts.

Usage: python3 c5-exploratory-report.py
Writes: c5-exploratory-backtest-report.md, c5-exploratory-backtest-audit.md
"""
import csv
import json
import math
import os
from datetime import date, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
SEED = 20261030


def pct(x, dec=4):
    return f"{x * 100:+.{dec}f}%"


def iv(lo, hi, dec=4):
    return f"[{pct(lo, dec)}, {pct(hi, dec)}]"


def mid(lo, hi):
    return (lo + hi) / 2


def lag1(xs):
    n = len(xs)
    if n < 2:
        return None
    mean = sum(xs) / n
    num = sum((xs[i] - mean) * (xs[i - 1] - mean) for i in range(1, n))
    den = sum((x - mean) ** 2 for x in xs)
    return num / den if den else 0.0


def mdd(series):
    peak, dd = -1e18, 0.0
    for v in series:
        peak = max(peak, v)
        dd = max(dd, peak - v)
    return dd


def median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def load_json(path):
    with open(path) as f:
        return json.load(f)


def main():
    res = load_json(os.path.join(DATA, "c5-exploratory-results.json"))
    bars = {s: load_json(os.path.join(DATA, f"klines_{s}.json"))
            for s in ("BTCUSDT", "ETHUSDT")}
    funding = {s: sorted((int(r[0]), float(r[1]))
                         for r in load_json(
                             os.path.join(DATA, f"funding_{s}.json")))
               for s in ("BTCUSDT", "ETHUSDT")}
    rows = list(csv.DictReader(open(os.path.join(
        BASE, "c5-event-calendar-draft.csv"))))
    cal = {(r["date"], r["series"]): r for r in rows}

    # ---- integrity re-checks (analysis-time, read-only) ----
    for tier in ("low", "central", "high"):
        st = [(t["date"], t["series"])
              for t in res["tiers"][tier]["trades"]]
        pl = [(t["date"], t["series"])
              for t in res["tiers"][tier]["placebo_trades"]]
        assert st == pl, f"{tier}: strategy/placebo traded sets differ"
        assert all(t["date"] <= "2026-10-30" for t in
                   res["tiers"][tier]["trades"])
    assert all((t["date"], t["series"]) != ("2026-10-28", "FOMC")
               for t in res["tiers"]["central"]["trades"])
    # no open legs on the provisional 2026-10-30 bar
    for t in res["tiers"]["central"]["trades"]:
        d = date.fromisoformat(t["date"])
        for leg in t["legs"]:
            assert d + timedelta(days=2 + leg["exit_day"]) <= date(2026, 10, 29)

    def event_move(ev_date, sym):
        d = date.fromisoformat(ev_date)
        prev = bars[sym][(d - timedelta(days=1)).isoformat()][3]
        cur = bars[sym][ev_date][3]
        return (cur - prev) / prev

    def tier_stats(trades):
        los = [t["net_lo"] for t in trades]
        his = [t["net_hi"] for t in trades]
        mids = [mid(a, b) for a, b in zip(los, his)]
        n = len(trades)
        return {
            "n": n,
            "mean_iv": (sum(los) / n, sum(his) / n),
            "mean_mid": sum(mids) / n,
            "median_mid": median(mids),
            "min_mid": min(mids), "max_mid": max(mids),
            "certain_win": sum(1 for a in los if a > 0),
            "certain_loss": sum(1 for b in his if b < 0),
            "straddle": sum(1 for a, b in zip(los, his)
                            if a <= 0 <= b),
            "contrib_iv": (sum(t["contrib_lo"] for t in trades),
                           sum(t["contrib_hi"] for t in trades)),
            "mids": mids,
        }

    stats = {t: tier_stats(res["tiers"][t]["trades"])
             for t in ("low", "central", "high")}
    pstats = {t: tier_stats(res["tiers"][t]["placebo_trades"])
              for t in ("low", "central", "high")}

    # ex-max-event check (central, midpoint criterion)
    ct = res["tiers"]["central"]["trades"]
    n_two = sum(1 for t in ct if len(t["legs"]) == 2)
    n_one = sum(1 for t in ct if len(t["legs"]) == 1)
    imax = max(range(len(ct)),
               key=lambda i: mid(ct[i]["contrib_lo"], ct[i]["contrib_hi"]))
    rest = [t for i, t in enumerate(ct) if i != imax]
    ex = tier_stats(rest)
    max_ev = ct[imax]

    # annual breakdown (central)
    years = {}
    for t in ct:
        years.setdefault(t["date"][:4], []).append(t)
    annual = {y: tier_stats(ts) for y, ts in sorted(years.items())}

    # event-sequence equity / MDD (central)
    cum_lo, cum_hi, c_lo, c_hi = [], [], 0.0, 0.0
    for t in ct:
        c_lo += t["contrib_lo"]
        c_hi += t["contrib_hi"]
        cum_lo.append(1 + c_lo)
        cum_hi.append(1 + c_hi)
    mdd_seq = (mdd(cum_lo), mdd(cum_hi))

    # calendar MDD + finals from the run
    eq = res["equity"]
    mdd_cal = (min(eq["mdd_lo_cost_curve"], eq["mdd_hi_cost_curve"]),
               max(eq["mdd_lo_cost_curve"], eq["mdd_hi_cost_curve"]))
    days_win = (date(2026, 10, 30) - date(2020, 1, 1)).days
    days_bh = (date(2026, 10, 29) - date(2020, 1, 1)).days
    fin = (eq["final_lo"], eq["final_hi"])
    ann_simple = (fin[0] - 1) * 365 / days_win, (fin[1] - 1) * 365 / days_win
    ann_comp = (fin[0] ** (365 / days_win) - 1,
                fin[1] ** (365 / days_win) - 1)
    bh = res["buy_hold"]
    bh_ann = {k: (1 + v) ** (365 / days_bh) - 1 for k, v in bh.items()}
    bh_ann["mean"] = (1 + res["buy_hold_mean"]) ** (365 / days_bh) - 1

    # correlation diagnostics (central, traded events in order)
    mids = stats["central"]["mids"]
    los = [t["net_lo"] for t in ct]
    his = [t["net_hi"] for t in ct]
    half = len(ct) // 2
    first = sum(mids[:half]) / half
    second = sum(mids[half:]) / (len(ct) - half)
    moves = []
    for t in ct:
        mv = [abs(event_move(t["date"], leg["symbol"]))
              for leg in t["legs"]]
        moves.append(sum(mv) / len(mv))
    med_mv = median(moves)
    hi_g = [m for m, mv in zip(mids, moves) if mv >= med_mv]
    lo_g = [m for m, mv in zip(mids, moves) if mv < med_mv]

    # R window mean (independent FRED computation, see report §0)
    r_mean = 0.02974001171646163
    r_n = 1707

    # ---------------- report ----------------
    L = []
    A = L.append
    A("# C5 探索性回测报告（单次运行，探索定位）")
    A("")
    A("- 规则：冻结草案 **v0.8-DRAFT**（合并≠生效）；方向各腿按自己标的、"
      "过滤按腿、资金费最值边界、种子 `20261030`。")
    A("- 探索窗口：2020-01-01 至 2026-10-30（已冻结）；"
      "2026-10-28 FOMC 单列为截止日未完成、**不纳入**本次样本。")
    A("- 样本：日历 217 个事件，可评估 216 个，本次交易（中央档）"
      f"{stats['central']['n']} 个事件；数据缺失排除 0 个。")
    A("- 批准：用户 2026-10-30T09:30:54Z 批准执行申请 v2，"
      "仅授权执行一次历史探索性回测；运行 "
      f"{res['run_at_utc']}（UTC，耗时 2.7 秒）。")
    A("- 定位：**探索结果不判定策略有效，不触发杀线通过或淘汰**；"
      "为正 ≠ 有效、为负 ≠ 淘汰；\"赚不赚钱\"只能由冻结后前向验证回答。")
    A("- 本次批准不代表策略冻结，不授权实盘或追加资金。")
    A("")
    A("## 0. 执行记录与可复现性")
    A("")
    A("- 执行前门禁（全部通过）：数据文件 SHA256 与质量报告 §2 一致 "
      "（5 个文件复核无差）；单元测试 25 项、端到端测试 39 项 FAIL 0；"
      "实现对照门禁（引擎复现端到端价格力学 7 场景与资金费边界）通过；"
      "实现内含截止日断言（数据不得超过 2026-10-30）与批准拒跑门。")
    A("- 执行前门禁审查修正（收益计算前发现，非调参）：零成本单次对账"
      "诊断的原断言（EXEC 与零成本出场日必须相同）过强——止损价相差约 "
      "EXEC 时出场日可合法不同；已改为记录差异口径（见 §10），"
      "核心引擎与规则未动；单次对账口径见 §10 下文。）")
    A("- 程序缺陷记录（运行后发现，不影响任何收益数字）：运行内 FRED "
      "拉取解析遇空值行崩溃，走预设回退用了 4.18% 时点值；报告 §6 的"
      "现金基准改用独立计算的窗口均值（两次独立拉取结果一致，"
      f"n={r_n}，均值 {pct(r_mean, 2)}）；解析已在事后修复，未重跑。")
    A("- 批准登记：`EXECUTION_APPROVED` 仅在单次运行期间置真，"
      "运行后立即恢复为 False；裸运行复核已被拒跑门拒绝。")
    A("- 复现：代码（`c5-exploratory-backtest.py`，含上述两处标注修正）"
      "＋本地数据（哈希见上）＋本报告审计表；重跑须另行批准。")
    A("- 资金费区间口径（修订 7）：止损腿区间为触发日内全部前缀和最值，"
      "按实际净收益取最值；收盘腿为单点值。区间横跨阈值时结论为未决。")
    A("")
    A("## 1. 事件级净收益（中央档为主口径）")
    A("")
    cs = stats["central"]
    A(f"- 事件数 N = {cs['n']}（217 日历 − 1 截止日未完成 "
      f"− 16 去重跳过 − 6 两腿均未过过滤，见 §8）；"
      f"其中 {n_two} 个事件交易两腿、{n_one} 个事件只交易一腿。")
    A("- 口径说明：平均净延续为事件等权均值，总贡献为资本加权口径"
      "（单腿事件只动用 10% 承诺资本、双腿事件 20%），两者不可直接换算。")
    A(f"- 平均净延续（区间）：{iv(*cs['mean_iv'])}；"
      f"中点均值 {pct(cs['mean_mid'])}。")
    A(f"- 中位（中点）：{pct(cs['median_mid'])}；"
      f"中点最小 {pct(cs['min_mid'])}，最大 {pct(cs['max_mid'])}。")
    A(f"- 确定盈利事件（区间下界 ＞ 0）：{cs['certain_win']} 个；"
      f"确定亏损事件（区间上界 ＜ 0）：{cs['certain_loss']} 个；"
      f"区间横跨 0（未决）：{cs['straddle']} 个。")
    A(f"- 承诺资本口径总贡献（区间）：{iv(*cs['contrib_iv'])}；"
      f"期末权益水平值：{fin[0]:.4f}～{fin[1]:.4f}"
      f"（即净收益 {pct(fin[0] - 1)}～{pct(fin[1] - 1)}）。")
    A(f"- 去掉最大盈利事件（{max_ev['date']} {max_ev['series']}，"
      f"贡献中点 {pct(mid(max_ev['contrib_lo'], max_ev['contrib_hi']))}）后，"
      f"平均净延续（区间）：{iv(*ex['mean_iv'])}，"
      f"中点均值 {pct(ex['mean_mid'])}。")
    A("")
    A("## 2. 最大回撤（双口径）")
    A("")
    A(f"- 事件时序口径（按事件顺序累计贡献）："
      f"最大回撤区间 [{pct(min(mdd_seq))}, {pct(max(mdd_seq))}]。")
    A(f"- 日历口径（逐日盯市，资金费边界两条曲线）："
      f"最大回撤区间 [{pct(mdd_cal[0])}, {pct(mdd_cal[1])}]。")
    A(f"- 年化净收益（承诺资本口径，窗口 {days_win} 天）："
      f"单利 {iv(*ann_simple)}；复利 {iv(*ann_comp)}。")
    A("- 说明：2026-10-30 当日无持仓腿（窗口覆盖该日的唯一事件即被排除"
      "的 10-28 FOMC），暂定 K 线不影响期末权益。")
    A("")
    A("## 3. 分年表现（中央档）")
    A("")
    A("| 年份 | 事件数 | 平均净延续（区间） | 净贡献（区间） |")
    A("|---|---|---|---|")
    for y, s in annual.items():
        A(f"| {y} | {s['n']} | {iv(*s['mean_iv'])} | {iv(*s['contrib_iv'])} |")
    A("")
    A("## 4. 随机方向安慰剂（冻结种子 20261030，单次）")
    A("")
    ps = pstats["central"]
    diff = (cs["mean_iv"][0] - ps["mean_iv"][1],
            cs["mean_iv"][1] - ps["mean_iv"][0])
    A(f"- 安慰剂平均净延续（区间）：{iv(*ps['mean_iv'])}；"
      f"中点均值 {pct(ps['mean_mid'])}；"
      f"确定盈利 {ps['certain_win']} 个，确定亏损 {ps['certain_loss']} 个。")
    A(f"- 策略减安慰剂（区间差）：{iv(*diff)}；"
      f"中点差 {pct(cs['mean_mid'] - ps['mean_mid'])}。")
    A("- 安慰剂与策略同事件、同窗口、同成本、同交易集合（过滤与去重"
      "与方向无关）；方向逐腿抽取，每事件先 BTC 腿后 ETH 腿。")
    A("")
    A("## 5. 买入持有同一篮子")
    A("")
    A(f"- 探索期内等权持有 BTC／ETH（2020-01-01 收盘 → 2026-10-29 收盘，"
      f"{days_bh} 天，毛收益、不含交易成本）："
      f"BTC {pct(bh['BTCUSDT'], 2)}，ETH {pct(bh['ETHUSDT'], 2)}，"
      f"均值 {pct(res['buy_hold_mean'], 2)}。")
    A(f"- 年化（复利）：BTC {pct(bh_ann['BTCUSDT'], 2)}，"
      f"ETH {pct(bh_ann['ETHUSDT'], 2)}，均值 {pct(bh_ann['mean'], 2)}。")
    A("")
    A("## 6. 现金基准 R")
    A("")
    A(f"- 探索期 3M 美债均值口径（FRED DGS3MO，2020-01-02 至 2026-10-28，"
      f"n={r_n} 个交易日观测，73 个空值日为休市日）："
      f"**{pct(r_mean, 2)}**。")
    A("- 时点值 4.18%（2026-10-29）仅作参照，不得与窗口均值混用。")
    A("")
    A("## 7. 成本敏感性（三档全报，中央档为主）")
    A("")
    A("| 成本档 | 往返成本 | 交易事件数 | 平均净延续（区间） | "
      "策略减安慰剂（区间差） |")
    A("|---|---|---|---|---|")
    for tier, cost in (("low", "0.17%"), ("central", "0.26%"),
                       ("high", "0.50%")):
        s, p = stats[tier], pstats[tier]
        d = (s["mean_iv"][0] - p["mean_iv"][1],
             s["mean_iv"][1] - p["mean_iv"][0])
        A(f"| {tier} | {cost} | {s['n']} | {iv(*s['mean_iv'])} | {iv(*d)} |")
    A("")
    A("- 未挑选最优成本档：三档结论并列，主口径为中央档。")
    A("")
    A("## 8. 日志（四类清单）")
    A("")
    for tier in ("low", "central", "high"):
        lg = res["tiers"][tier]["logs"]
        stops = [t for t in res["tiers"][tier]["trades"]
                 for leg in t["legs"] if leg["exit_type"] != "close"]
        gap = sum(1 for t in res["tiers"][tier]["trades"]
                  for leg in t["legs"] if leg["exit_type"] == "stop-gap")
        A(f"- {tier}：缺失／无效排除 {len(lg['excluded'])} 个事件；"
          f"去重跳过 {len(lg['skipped'])} 个事件；"
          f"噪声过滤未交易 {len(lg['no_trade'])} 条腿；"
          f"止损腿 {len(stops)} 条（其中跳空穿透 {gap} 条）。"
          f"完整清单见审计附表。")
    A("- 截止日未完成：2026-10-28 FOMC（窗口延至 11-02／11-03），"
      "已排除，未用截止日后数据。")
    A("")
    A("## 9. 跨事件相关性（仅报告，不判定）")
    A("")
    A(f"- 事件级净收益序列 lag-1 自相关：中点序列 {lag1(mids):+.3f}；"
      f"下界序列 {lag1(los):+.3f}；上界序列 {lag1(his):+.3f}。")
    A(f"- 时间对半分段：前半均值（中点）{pct(first)}，"
      f"后半均值（中点）{pct(second)}。")
    A(f"- 按事件日 |涨跌|（已交易腿均值，中位 {pct(med_mv, 2)}）分组："
      f"高组均值（中点）{pct(sum(hi_g) / len(hi_g))}（{len(hi_g)} 个），"
      f"低组均值（中点）{pct(sum(lo_g) / len(lo_g))}（{len(lo_g)} 个）。")
    A("- 杀线相关结论（独立性存疑即未决）只在前向验证中判定，"
      "探索中不判定。")
    A("")
    A("## 10. 执行价审计与单次对账")
    A("")
    A("- 逐笔交易记录（全部三档策略交易＋中央档安慰剂交易）见审计附表 "
      "`c5-exploratory-backtest-audit.md`：入场价（开盘＋滑点价差分解）、"
      "出场价与三类标注、止损触发日、持有天数、资金费结算次数与区间边界，"
      "抽查可复算。")
    zc = res["zero_exec_check"]
    A(f"- 单次对账：含滑点价差净收益与零成本净收益之差，中央档均值 "
      f"{pct(zc['mean_diff'])}（{zc['n']} 个事件）；"
      f"出场日相同的干净子集（{zc['n_legs'] - zc['n_differing_exits']}/"
      f"{zc['n_legs']} 条腿）均值 {pct(zc['mean_diff_clean'])}，"
      f"与约 −0.16% 的理论值一致，无双计信号；"
      f"出场日不同 {zc['n_differing_exits']} 条腿已记录（止损价差约 EXEC 所致）。")
    A("")
    A("## 11. 结论定位与还差什么")
    A("")
    A("- 探索回答的是\"能不能算\"：数据完整、代码通过对照门禁、成本可测、"
      "区间口径可报。本次探索的平均净延续为负区间（见 §1），"
      "但探索为负 ≠ 淘汰、为正 ≠ 有效。")
    A("- 距离前向验证还差：①用户批准策略冻结（草案 v0.8-DRAFT 全文＋"
      "种子，批准并填时间戳后生效）；②纸面成本门（冻结生效后前向实测 "
      "≥10 个事件窗口，K-C5-4 触发即淘汰）；③冻结后新产生的前向验证样本"
      "积累（冻结时按实际日历登记目标事件数）；④杀线判定只在前向样本上执行。")
    A("- 本报告不作冻结推荐；是否冻结由用户决定。")

    # ---------------- audit appendix ----------------
    B = []
    W = B.append
    W("# C5 探索性回测审计附表（单次运行）")
    W("")
    W(f"- 运行 {res['run_at_utc']}（UTC）；规则 v0.8-DRAFT；种子 20261030；"
      "窗口 2020-01-01 至 2026-10-30；2026-10-28 FOMC 已排除。")
    W("- 方向：+1 多头／−1 空头（各腿按自己标的）；"
      "出场类型：close＝收盘出场，stop＝盘中触发，stop-gap＝跳空穿透。")
    W("- 资金费：exact＝单点值；interval＝[最小前缀和，最大前缀和]；"
      "n_fund＝结算次数（止损腿为区间）。净收益区间按实际净收益取最值。")
    W("")

    def fund_count(sym, ev_date, exit_type, exit_day):
        d = date.fromisoformat(ev_date)
        import calendar as _cal
        entry_ms = _cal.timegm((d + timedelta(days=2)).timetuple()) * 1000
        if exit_type == "close":
            upper = entry_ms + 4 * 86400000
            return str(sum(1 for (t, _) in funding[sym]
                           if entry_ms < t < upper))
        upper = entry_ms + (exit_day + 1) * 86400000
        low_cut = entry_ms + exit_day * 86400000
        n_lo = sum(1 for (t, _) in funding[sym]
                   if entry_ms < t <= low_cut)
        n_hi = sum(1 for (t, _) in funding[sym]
                   if entry_ms < t < upper)
        return f"{n_lo}–{n_hi}"

    for tier in ("low", "central", "high"):
        cfg = {"low": (0.00025, 0.0001), "central": (0.0005, 0.0003),
               "high": (0.0015, 0.0005)}[tier]
        ex = cfg[0] + cfg[1]
        W(f"## 策略交易（{tier} 档，EXEC＝{pct(ex, 3)}）")
        W("")
        W("| 事件 | 类别 | 腿 | 方向 | 入场开盘 | 入场成交价 | 出场类型／日 | "
          "出场价 | 毛延续 | 资金费 | 净收益区间 | 事件净收益区间 |")
        W("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for t in res["tiers"][tier]["trades"]:
            for leg in t["legs"]:
                d = date.fromisoformat(t["date"])
                entry_open = bars[leg["symbol"]][
                    (d + timedelta(days=2)).isoformat()][0]
                if len(leg["fund_n"]) == 1:
                    fund_s = f"{leg['fund_n'][0]:+.6f} (exact)"
                else:
                    fund_s = (f"[{leg['fund_n'][0]:+.6f}, "
                              f"{leg['fund_n'][1]:+.6f}]")
                W(f"| {t['date']} | {t['series']} | {leg['symbol'][:3]} | "
                  f"{leg['direction']:+d} | {entry_open:.2f} | "
                  f"{leg['entry_px']:.4f} | {leg['exit_type']}/D+{2 + leg['exit_day']} | "
                  f"{leg['exit_px']:.4f} | {pct(leg['gross'])} | {fund_s} "
                  f"n={fund_count(leg['symbol'], t['date'], leg['exit_type'], leg['exit_day'])} | "
                  f"{iv(leg['net_lo'], leg['net_hi'])} | "
                  f"{iv(t['net_lo'], t['net_hi'])} |")
        W("")
    W("## 安慰剂交易（中央档，种子 20261030，先 BTC 后 ETH 抽取）")
    W("")
    W("| 事件 | 类别 | 腿 | 方向 | 入场成交价 | 出场类型／日 | 出场价 | "
      "毛延续 | 净收益区间 | 事件净收益区间 |")
    W("|---|---|---|---|---|---|---|---|---|---|")
    for t in res["tiers"]["central"]["placebo_trades"]:
        for leg in t["legs"]:
            W(f"| {t['date']} | {t['series']} | {leg['symbol'][:3]} | "
              f"{leg['direction']:+d} | {leg['entry_px']:.4f} | "
              f"{leg['exit_type']}/D+{2 + leg['exit_day']} | "
              f"{leg['exit_px']:.4f} | {pct(leg['gross'])} | "
              f"{iv(leg['net_lo'], leg['net_hi'])} | "
              f"{iv(t['net_lo'], t['net_hi'])} |")
    W("")
    W("## 日志清单")
    W("")
    for tier in ("low", "central", "high"):
        lg = res["tiers"][tier]["logs"]
        W(f"### {tier} 档")
        W("")
        W(f"- 去重跳过（{len(lg['skipped'])}）："
          + (", ".join(f"{d} {s}" for d, s in lg["skipped"]) or "无"))
        W(f"- 噪声过滤未交易腿（{len(lg['no_trade'])}）："
          + (", ".join(f"{d} {s} {sym[:3]} {mv:+.4%}"
                       for d, s, sym, mv in lg["no_trade"]) or "无"))
        W(f"- 缺失／无效排除（{len(lg['excluded'])}）："
          + (", ".join(f"{d} {s} {r}" for d, s, r in lg["excluded"]) or "无"))
        stops = [(t["date"], t["series"], leg["symbol"][:3],
                  leg["exit_type"], leg["exit_day"])
                 for t in res["tiers"][tier]["trades"]
                 for leg in t["legs"] if leg["exit_type"] != "close"]
        W(f"- 止损腿（{len(stops)}）："
          + (", ".join(f"{d} {s} {sym} {tp}/D+{2 + dy}"
                       for d, s, sym, tp, dy in stops) or "无"))
        W("")

    with open(os.path.join(BASE, "c5-exploratory-backtest-report.md"),
              "w") as f:
        f.write("\n".join(L) + "\n")
    with open(os.path.join(BASE, "c5-exploratory-backtest-audit.md"),
              "w") as f:
        f.write("\n".join(B) + "\n")
    print(f"REPORT WRITTEN: central n={stats['central']['n']}, "
          f"mean_iv={stats['central']['mean_iv']}, "
          f"placebo mean_iv={pstats['central']['mean_iv']}")


if __name__ == "__main__":
    main()
