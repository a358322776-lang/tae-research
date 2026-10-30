#!/usr/bin/env python3
"""P1-v2 独立复核：不用探索引擎代码重算两条序列，验证引擎无系统性错误。

原运行 2026-10-29（输出见探索报告“方法与复核”一节）：
  等权买入持有（无成本）164.46x；主规格毛收益（无成本）9.60x；
  2020-12-31 形成月与引擎逐项一致（N=11、全多、IT 压缩因子 0.7333、
  现金目标值 14.55% vs 引擎取整后 14.65%）。
本文件为提交版（原 /tmp  scratch 版已转存至此，逻辑未变）。
只读本地数据文件，不算引擎之外的任何策略变体。
"""
import json, math

raw = json.load(open("/home/hatch/workspace/goals/100u-200u/files/tae-b1/p1-v2/p1v2-yahoo-data.json"))
POOL = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "SNDK", "MU", "AVGO", "PLTR", "AMD", "NFLX"]
IT = {"AAPL", "MSFT", "NVDA", "MU", "SNDK", "AVGO", "PLTR", "AMD"}
S = {}
for tk in POOL + ["SPY"]:
    d = raw["tickers"][tk]
    S[tk] = ({x: v for x, v in zip(d["dates"], d["adjclose"])}, d["dates"])
spy_dates = S["SPY"][1]
by_ym = {}
for dt in spy_dates:
    by_ym.setdefault(dt[:7], []).append(dt)
month_ends = [by_ym[ym][-1] for ym in sorted(by_ym)]
execs = []
for i, me in enumerate(month_ends):
    idx = spy_dates.index(me)
    execs.append(spy_dates[idx + 1] if idx + 1 < len(spy_dates) else None)

def pob(tk, date):
    mp, dl = S[tk]
    cand = [d for d in dl if d <= date]
    return cand[-1] if cand else None

def minus12(dstr):
    y, m, dd = int(dstr[:4]), int(dstr[5:7]), int(dstr[8:10])
    y -= 1
    mdays = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28, 31, 30, 31, 30,
             31, 31, 30, 31, 30, 31][m - 1]
    return f"{y:04d}-{m:02d}-{min(dd, mdays):02d}"

def elig_sig(tk, fdate):
    mp, dl = S[tk]
    ref_lim = minus12(fdate)
    cands = [d for d in dl if d <= ref_lim]
    if not cands:
        return None
    rdate = cands[-1]
    fpx = mp.get(fdate) or mp.get(pob(tk, fdate))
    if fpx is None:
        return None
    n_win = sum(1 for d in dl if rdate < d <= fdate)
    spy_win = sum(1 for d in spy_dates if rdate < d <= fdate)
    if n_win < 200 or spy_win == 0 or (1 - n_win / spy_win) > 0.05:
        return None
    r = fpx / mp[rdate] - 1
    return (1 if r > 0 else -1) if r != 0 else None

# 1) 等权买入持有（无成本、无量化）：每月按合格池等权做多
nav = 1.0; n = 0
for k in range(len(month_ends) - 1):
    if execs[k] is None or execs[k + 1] is None:
        continue
    elig = [t for t in POOL if elig_sig(t, month_ends[k]) is not None]
    if not elig:
        continue
    w = 1 / len(elig); g = 0.0
    for t in elig:
        p0 = S[t][0].get(execs[k]) or S[t][0].get(pob(t, execs[k]))
        p1 = S[t][0].get(execs[k + 1]) or S[t][0].get(pob(t, execs[k + 1]))
        g += w * (p1 / p0 - 1)
    nav *= (1 + g); n += 1
print(f"复核等权买入持有(无成本): 月数={n} 总倍数={nav:.2f}x")

# 2) 主规格毛收益（无成本、无量化）：等权+单股20%+IT40%
nav = 1.0; n = 0
for k in range(len(month_ends) - 1):
    if execs[k] is None or execs[k + 1] is None:
        continue
    sig = {}
    for t in POOL:
        s = elig_sig(t, month_ends[k])
        if s is not None:
            sig[t] = s
    if not sig:
        continue
    N = len(sig)
    w = {t: s * min(1 / N, 0.20) for t, s in sig.items()}
    s_it = sum(abs(w[t]) for t in sig if t in IT)
    if s_it > 0.40:
        f = 0.40 / s_it
        w = {t: (w[t] * f if t in IT else w[t]) for t in sig}
    g = 0.0
    for t, wi in w.items():
        p0 = S[t][0].get(execs[k]) or S[t][0].get(pob(t, execs[k]))
        p1 = S[t][0].get(execs[k + 1]) or S[t][0].get(pob(t, execs[k + 1]))
        g += wi * (p1 / p0 - 1)
    nav *= (1 + g); n += 1
print(f"复核主规格毛收益(无成本): 月数={n} 总倍数={nav:.2f}x")

# 3) 手工抽查：形成日 2020-12-31 的持仓与权重
fdate = "2020-12-31"
sig = {t: elig_sig(t, fdate) for t in POOL}
sig = {t: s for t, s in sig.items() if s is not None}
N = len(sig)
w = {t: s * min(1 / N, 0.20) for t, s in sig.items()}
s_it = sum(abs(w[t]) for t in sig if t in IT)
f = 0.40 / s_it if s_it > 0.40 else 1.0
w = {t: (w[t] * f if t in IT else w[t]) for t in sig}
print(f"抽查 2020-12-31: N={N} 信号={sig}")
print(f"  IT原始占比={s_it:.4f} 缩放因子={f:.4f} 现金={1 - sum(abs(v) for v in w.values()):.4f}")
print(f"  权重={ {t: round(v, 4) for t, v in w.items()} }")
eng = json.load(open("/home/hatch/workspace/goals/100u-200u/files/tae-b1/p1-v2/p1v2-exploration-results.json"))
row = [r for r in eng["monthly_main"] if r["formation"] == fdate]
print(f"  引擎同月: {row[0] if row else '无'}")
