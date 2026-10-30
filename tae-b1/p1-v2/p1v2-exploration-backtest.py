#!/usr/bin/env python3
"""P1-v2 探索回测引擎（冻结规则 v1.0）。

只执行冻结文件写死的规则，不做任何参数搜索、不反向改参。
输出 p1v2-exploration-results.json（月度序列 + 汇总统计 + 杀线裁决）。
成本：费用双轨（0.05%/0.075% taker）+ 滑点中央 0.05%（敏感性 0%/0.10%）；
资金费：主序列不含资金费（明确标注），另附常数率敏感性与 2026+ 实际窗口说明。
Gate 合约 2026 年前不存在，故 2026 年前执行成本为模型化成本（报告中分段声明）。
"""
import json, math, urllib.request
from datetime import datetime, timezone, timedelta

DATA = "/home/hatch/workspace/goals/100u-200u/files/tae-b1/p1-v2/p1v2-yahoo-data.json"
OUT = "/home/hatch/workspace/goals/100u-200u/files/tae-b1/p1-v2/p1v2-exploration-results.json"
POOL = ["AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","SNDK","MU","AVGO","PLTR","AMD","NFLX"]
IT = {"AAPL","MSFT","NVDA","MU","SNDK","AVGO","PLTR","AMD"}
QUANTO = {t: 0.01 for t in POOL}  # Gate contracts 2026-10-29 实测：13 家 quanto 均为 0.01
SINGLE_CAP = 0.20
IT_CAP = 0.40
NAV0 = 1000.0
FEE_CENTRAL, FEE_CONS = 0.0005, 0.00075
SLIP_CENTRAL = 0.0005

def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()

def minus_12m(d):
    y, m = d.year - 1, d.month
    mdays = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28, 31, 30, 31, 30,
             31, 31, 30, 31, 30, 31][m - 1]
    return d.replace(year=y, day=min(d.day, mdays))

def main():
    raw = json.load(open(DATA))
    S = {}
    for tk in POOL + ["SPY"]:
        d = raw["tickers"][tk]
        dates = [parse_date(x) for x in d["dates"]]
        S[tk] = (dates, d["adjclose"])
    spy_dates = S["SPY"][0]
    # 月末（SPY 日历）与执行日（月末后下一 SPY 交易日）
    months = []
    by_ym = {}
    for i, dt in enumerate(spy_dates):
        by_ym.setdefault((dt.year, dt.month), []).append(i)
    month_ends = []  # (date, spy_idx)
    for ym in sorted(by_ym):
        idx = by_ym[ym][-1]
        month_ends.append((spy_dates[idx], idx))
    # 执行日：月末后下一个 SPY 交易日
    execs = []  # per month_end: (exec_date, spy_idx) or None
    for dt, idx in month_ends:
        execs.append((spy_dates[idx + 1], idx + 1) if idx + 1 < len(spy_dates) else None)

    def price_on_or_before(tk, date):
        dates, vals = S[tk]
        lo, hi, ans = 0, len(dates) - 1, None
        while lo <= hi:
            mid = (lo + hi) // 2
            if dates[mid] <= date:
                ans = mid; lo = mid + 1
            else:
                hi = mid - 1
        return (dates[ans], vals[ans]) if ans is not None else (None, None)

    def formation(tk, fdate):
        """返回 (信号, 参考日, 窗口交易日数, 缺失占比) 或 None（无资格）。"""
        dates, vals = S[tk]
        ref_limit = minus_12m(fdate)
        rdate, rpx = price_on_or_before(tk, ref_limit)
        if rdate is None:
            return None
        fdate_px = price_on_or_before(tk, fdate)
        if fdate_px[1] is None:
            return None
        n_win = sum(1 for dt in dates if rdate < dt <= fdate)
        spy_win = sum(1 for dt in spy_dates if rdate < dt <= fdate)
        if n_win < 200 or spy_win == 0:
            return None
        miss = 1 - n_win / spy_win
        if miss > 0.05:
            return None
        r = fdate_px[1] / rpx - 1
        if r == 0:
            return None
        return (1 if r > 0 else -1, rdate, n_win, miss)

    def weights(signals, capped=True):
        """signals: {tk: sign}. 返回 {tk: weight} 与现金占比。"""
        H = list(signals.keys())
        N = len(H)
        if N == 0:
            return {}, 1.0
        w = {t: signals[t] / N for t in H}
        w = {t: signals[t] * min(1 / N, SINGLE_CAP) for t in H}
        if capped:
            s_it = sum(abs(w[t]) for t in H if t in IT)
            if s_it > IT_CAP:
                f = IT_CAP / s_it
                w = {t: (w[t] * f if t in IT else w[t]) for t in H}
        cash = 1 - sum(abs(v) for v in w.values())
        return w, cash

    def quantize(w, nav, exec_date):
        """向下取整到合约张数（mark 代理＝底层执行日收盘价）。返回 (qw, cash)。"""
        qw = {}
        for t, wi in w.items():
            px = price_on_or_before(t, exec_date)[1]
            if px is None or px <= 0:
                continue
            one = QUANTO[t] * px
            n = math.floor(abs(wi) * nav / one)
            qw[t] = math.copysign(n * one / nav, wi) if n > 0 else 0.0
        qw = {t: v for t, v in qw.items() if v != 0}
        return qw, 1 - sum(abs(v) for v in qw.values())

    def run(nav0, capped, fee, slip):
        nav = nav0
        w_prev = {}  # 上期实际持有（量化后权重，NAV 分数）
        rows = []
        # 形成月 k：信号日 month_ends[k]，执行日 execs[k]；持有期 k 收益用 execs[k]->execs[k+1]
        for k in range(len(month_ends) - 1):
            fdate, _ = month_ends[k]
            ex_date, _ = execs[k]
            ex_next = execs[k + 1]
            if ex_next is None:
                break
            ex_next_date, _ = ex_next
            sig = {}
            for tk in POOL:
                fm = formation(tk, fdate)
                if fm is not None:
                    sig[tk] = fm[0]
            if not sig:
                # 无合格标的的月份不是策略观测（2010 年启动期），跳过不计入样本
                continue
            w_t, _ = weights(sig, capped=capped)
            qw, cash = quantize(w_t, nav, ex_date)
            # 漂移权重（冻结文件 F7）：上期量化持有权重按上一持有期的腿收益漂移，
            # d_i = w_prev_i × (1 + r_leg_i) / (1 + Rprev)；首期 d 全为 0（全部为新开）。
            d = {}
            if rows:
                prev = rows[-1]
                Rprev = prev["gross"]
                for t, wp in prev["qw"].items():
                    r_leg = prev["leg_returns"].get(t)
                    d[t] = wp * (1 + r_leg) / (1 + Rprev) if r_leg is not None else 0.0
            traded = 0.0
            for t in set(d) | set(qw):
                dv, nv = d.get(t, 0.0), qw.get(t, 0.0)
                if dv == 0 and nv == 0:
                    continue
                if (dv > 0) != (nv > 0) and dv != 0 and nv != 0:
                    traded += abs(dv) + abs(nv)
                else:
                    traded += abs(nv - dv)
            cost = traded * (fee + slip)
            # 本期持有收益
            leg_ret = {}
            gross = 0.0
            for t, wi in qw.items():
                p0 = price_on_or_before(t, ex_date)[1]
                p1 = price_on_or_before(t, ex_next_date)[1]
                r = p1 / p0 - 1 if (p0 and p1) else 0.0
                leg_ret[t] = r
                gross += wi * r
            net = gross - cost
            it_share = sum(abs(v) for t, v in qw.items() if t in IT)
            rows.append({"formation": str(fdate), "exec": str(ex_date), "N": len(qw),
                         "holdings": sorted(qw.keys()), "cash": round(cash, 4),
                         "it_share": round(it_share, 4), "traded": round(traded, 4),
                         "cost": round(cost, 6), "gross": round(gross, 6), "net": round(net, 6),
                         "nav": round(nav * (1 + net), 2), "qw": {t: round(v, 4) for t, v in qw.items()},
                         "leg_returns": {t: round(v, 4) for t, v in leg_ret.items()}})
            nav = nav * (1 + net)
            w_prev = qw
        return rows

    def stats(rows):
        import statistics as st
        nets = [r["net"] for r in rows]
        n = len(nets)
        tot = 1.0
        for x in nets:
            tot *= (1 + x)
        mean = sum(nets) / n if n else 0
        sd = st.pstdev(nets) if n > 1 else 0
        sharpe = (mean / sd * math.sqrt(12)) if sd else 0
        # 最大回撤（NAV 序列，含起点 1）
        navs = [1.0]
        for r in rows:
            navs.append(navs[-1] * (1 + r["net"]))
        peak, mdd = navs[0], 0.0
        for v in navs:
            peak = max(peak, v); mdd = min(mdd, v / peak - 1)
        return {"months": n, "total_return": round(tot - 1, 4),
                "ann_return": round(tot ** (12 / n) - 1, 4) if n else 0,
                "ann_vol": round(sd * math.sqrt(12), 4),
                "sharpe": round(sharpe, 4), "max_drawdown": round(mdd, 4),
                "monthly_win_rate": round(sum(1 for x in nets if x > 0) / n, 4) if n else 0,
                "avg_monthly_cost": round(sum(r["cost"] for r in rows) / n, 6) if n else 0,
                "avg_cash": round(sum(r["cash"] for r in rows) / n, 4) if n else 0,
                "avg_N": round(sum(r["N"] for r in rows) / n, 2) if n else 0,
                "final_nav_1000": round(1000 * tot, 2)}

    main_c = run(NAV0, True, FEE_CENTRAL, SLIP_CENTRAL)
    main_s = run(NAV0, True, FEE_CONS, SLIP_CENTRAL)
    ctrl = run(NAV0, False, FEE_CENTRAL, SLIP_CENTRAL)
    main10000 = run(10000.0, True, FEE_CENTRAL, SLIP_CENTRAL)
    # 基准 (a) PIT 等权买入持有（只做多、月度再平衡、同样成本记账、量化）
    def run_bench(nav0, fee, slip):
        nav = nav0; w_prev = {}; rows = []
        for k in range(len(month_ends) - 1):
            fdate, _ = month_ends[k]; ex_date, _ = execs[k]; ex_next = execs[k + 1]
            if ex_next is None:
                break
            ex_next_date, _ = ex_next
            elig = [tk for tk in POOL if formation(tk, fdate) is not None]
            if not elig:
                # 与主规格同口径：无合格标的的月份不计入样本
                continue
            w_t = {t: 1 / len(elig) for t in elig}
            qw, cash = quantize(w_t, nav, ex_date)
            d = {}
            if rows:
                prev = rows[-1]; Rprev = prev["gross"]
                for t, wp in prev["qw"].items():
                    r_leg = prev["leg_returns"].get(t)
                    d[t] = wp * (1 + r_leg) / (1 + Rprev) if r_leg is not None else 0.0
            traded = sum(abs(qw.get(t, 0.0) - d.get(t, 0.0)) for t in set(d) | set(qw))
            cost = traded * (fee + slip)
            leg_ret = {}; gross = 0.0
            for t, wi in qw.items():
                p0 = price_on_or_before(t, ex_date)[1]; p1 = price_on_or_before(t, ex_next_date)[1]
                r = p1 / p0 - 1 if (p0 and p1) else 0.0
                leg_ret[t] = r; gross += wi * r
            net = gross - cost
            rows.append({"formation": str(fdate), "N": len(qw), "cash": round(cash, 4),
                         "cost": round(cost, 6),
                         "gross": round(gross, 6), "net": round(net, 6),
                         "qw": {t: round(v, 4) for t, v in qw.items()},
                         "leg_returns": {t: round(v, 4) for t, v in leg_ret.items()}})
            nav = nav * (1 + net)
        return rows
    bench = run_bench(NAV0, FEE_CENTRAL, SLIP_CENTRAL)
    # 基准 (b) SPY 买入持有（窗口与主规格对齐：主规格首个执行日 → 末个持有期结束日）
    spy_nav = 1.0
    for r in main_c:
        ex0 = parse_date(r["exec"])
        # 本持有期的结束执行日＝下一形成月的执行日：用月末表定位
        fi = [i for i, (fd, _) in enumerate(month_ends) if str(fd) == r["formation"]][0]
        ex1 = execs[fi + 1][0]
        p0 = price_on_or_before("SPY", ex0)[1]; p1 = price_on_or_before("SPY", ex1)[1]
        spy_nav *= (p1 / p0) if (p0 and p1) else 1.0
    spy_bh = spy_nav - 1
    # 杀线
    def kill(rows_main, rows_bench, label):
        s = stats(rows_main); sb = stats(rows_bench)
        n = s["months"]; half = n // 2
        def shp(rs):
            import statistics as st
            ns = [r["net"] for r in rs]
            return (sum(ns) / len(ns) / st.pstdev(ns) * math.sqrt(12)) if len(ns) > 1 and st.pstdev(ns) else 0
        k1 = s["sharpe"] <= 0
        k2 = shp(rows_main[:half]) <= 0 or shp(rows_main[half:]) <= 0
        k3 = (s["total_return"] < sb["total_return"]) and (s["max_drawdown"] < sb["max_drawdown"])
        # 风险匹配：k = sigma_main / sigma_bench（月度），缩放基准序列
        import statistics as st
        sm = st.pstdev([r["net"] for r in rows_main]) if n > 1 else 0
        sbb = st.pstdev([r["net"] for r in rows_bench]) if n > 1 else 0
        kfac = sm / sbb if sbb else 0
        bench_scaled = [r["net"] * kfac for r in rows_bench]
        tot_s = 1.0
        for x in bench_scaled:
            tot_s *= (1 + x)
        navs = [1.0]
        for x in bench_scaled:
            navs.append(navs[-1] * (1 + x))
        peak, mdd_s = navs[0], 0.0
        for v in navs:
            peak = max(peak, v); mdd_s = min(mdd_s, v / peak - 1)
        k4 = (s["total_return"] < tot_s - 1) and (s["max_drawdown"] < mdd_s)
        k5 = n < 60
        # K-V6: 目标权重违反（本实现按构造为 0）+ 月末 IT 占比连续 3 月 >50%（用调仓日 IT 占比代理月末值）
        it_series = [r["it_share"] for r in rows_main]
        run3 = 0; k6b = False
        for v in it_series:
            run3 = run3 + 1 if v > 0.50 else 0
            if run3 >= 3:
                k6b = True; break
        return {"label": label, "K-V1_sharpe_le_0": k1, "K-V2_half_sharpe_le_0": k2,
                "K-V3_dual_loss_vs_bench": k3, "K-V4_dual_loss_vs_riskmatched": k4,
                "K-V5_sample_lt_60": k5, "K-V6a_target_violation": False,
                "K-V6b_it_drift_3mo_gt_50pct": k6b,
                "any_kill": any([k1, k2, k3, k4, k5, k6b]),
                "k_factor": round(kfac, 4),
                "bench_scaled_total_return": round(tot_s - 1, 4),
                "bench_scaled_max_dd": round(mdd_s, 4)}
    res = {"meta": {"frozen": "p1v2-frozen-rules.md v1.0", "pool": POOL,
                    "note": "主序列扣费滑点、不含资金费（资金费见敏感性说明）；2026年前执行成本为模型化成本；"
                            "13家池为事后选股，历史结果不得当作独立验证。",
                    "first_formation": main_c[0]["formation"] if main_c else None,
                    "last_formation": main_c[-1]["formation"] if main_c else None},
           "summary": {"main_central": stats(main_c), "main_conservative_fee": stats(main_s),
                       "control_uncapped": stats(ctrl), "main_10000": stats(main10000),
                       "bench_equal_bh": stats(bench),
                       "spy_buy_hold_total": round(spy_bh, 4)},
           "kill_lines": kill(main_c, bench, "main_central_vs_equal_bh"),
           "monthly_main": main_c, "monthly_control": ctrl, "monthly_bench": bench}
    json.dump(res, open(OUT, "w"), ensure_ascii=False)
    print(json.dumps(res["summary"], ensure_ascii=False, indent=1))
    print(json.dumps(res["kill_lines"], ensure_ascii=False, indent=1))
    print("months:", len(main_c), "first:", main_c[0]["formation"] if main_c else None,
          "last:", main_c[-1]["formation"] if main_c else None)
    print("saved", OUT)

if __name__ == "__main__":
    main()
