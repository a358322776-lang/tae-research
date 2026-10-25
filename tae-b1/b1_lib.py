"""TAE-B1 v0.1 共用库：数据拼接、指标、E 形态（复用 v4.1 口径）。

数据：币安 ETHUSDT 永续公开 K 线。t = bar OPEN 时间（ms, UTC）。
OHLC 列顺序：o, h, l, c。所有判定只用已收盘 K 线。
指标口径（与 v4.1/净 R 审计一致）：
- ATR(14) = 最近 14 根 TR 的算术均值，TR = max(h-l, |h-pc|, |l-pc|)。
- EMA50：SMA50 种子，k = 2/51，15m 收盘价序列。
- SMA20：最近 20 根收盘价均值。
- swings：两个版本——key_levels 版（严格 > / <）用于 find_levels；
  scanner 版（等于 max/min 也算）用于 1H 大趋势 big_trend_dir。
- E 形态：逐字复用 tae-scanner.py 的 bull/bear_engulf、hammer、
  shooting_star、morning_star、evening_star、_is_signal_bar；
  C 组唯一改动：hammer/shooting_star 增加 body > 0（C10）。
"""
import json
import sys

import numpy as np

sys.path.insert(0, "/home/hatch/workspace/goals/100u-200u/hidden_files")
from key_levels import find_levels  # noqa: E402  纯函数模块，无副作用

ROB = "/home/hatch/workspace/goals/100u-200u/files/robustness-v41/data_cache"
B1 = "/home/hatch/workspace/goals/100u-200u/files/tae-b1/data_cache"
BOUNDARY_MS = 1760666400000  # 2025-10-17T02:00Z：v4.1 已冻结样本内/外分界
STEP = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000}


def stitch():
    """拼接 oos 缓存 + 新取数据，去重、排序、缺口与重叠校验。返回 dict。"""
    out = {}
    for tf in ("5m", "15m", "1h"):
        o = np.load(f"{ROB}/oos_{tf}.npz")
        f = np.load(f"{B1}/fresh_{tf}.npz")
        t = np.concatenate([o["t"], f["t"]])
        v = np.concatenate([o["ohlc"], f["ohlc"]])
        order = np.argsort(t, kind="stable")
        t, v = t[order], v[order]
        keep = np.ones(len(t), dtype=bool)
        keep[1:] = t[1:] != t[:-1]
        t, v = t[keep], v[keep]
        gaps = int(np.sum(np.diff(t) != STEP[tf]))
        out[tf] = {"gaps": gaps,
                   "first": int(t[0]), "last": int(t[-1]), "n": len(t)}
        np.savez_compressed(f"{B1}/stitched_{tf}.npz", t=t, ohlc=v)
    # 资金费：oos csv + fresh csv，去重排序
    fr = {}
    for path in (f"{ROB}/funding_oos.csv", f"{B1}/fresh_funding.csv"):
        with open(path) as fh:
            next(fh)
            for line in fh:
                ts, rate = line.strip().split(",")
                fr[int(ts)] = float(rate)
    fts = sorted(fr)
    with open(f"{B1}/stitched_funding.csv", "w") as fh:
        fh.write("fundingTime,fundingRate\n")
        for ts in fts:
            fh.write(f"{ts},{fr[ts]}\n")
    out["funding"] = {"n": len(fts), "first": fts[0], "last": fts[-1]}
    # 重叠校验：fresh 与 insample 缓存对比（2025-10-17→2026-10-22）
    checks = {}
    for tf in ("5m", "15m", "1h"):
        ins = np.load(f"{ROB}/insample_{tf}.npz")
        fr2 = np.load(f"{B1}/fresh_{tf}.npz")
        m = {int(t): row for t, row in zip(fr2["t"], fr2["ohlc"])}
        n_cmp = n_bad = 0
        for t, row in zip(ins["t"], ins["ohlc"]):
            if int(t) in m:
                n_cmp += 1
                if not np.allclose(m[int(t)], row):
                    n_bad += 1
        checks[tf] = {"overlap_bars": n_cmp, "mismatch": n_bad}
    out["overlap_check"] = checks
    with open(f"{B1}/stitched_manifest.json", "w") as fh:
        json.dump(out, fh, indent=1, default=int)
    return out


def tr_array(ohlc):
    """TR 数组（与收盘价对齐，tr[0] = nan）。"""
    o, h, l, c = ohlc[:, 0], ohlc[:, 1], ohlc[:, 2], ohlc[:, 3]
    pc = np.empty_like(c)
    pc[0] = np.nan
    pc[1:] = c[:-1]
    return np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))


def atr_series(ohlc, n=14):
    """ATR 数组（atr[i] = 最近 n 根 TR 均值，含 i；不足 n 根为 nan）。"""
    tr = tr_array(ohlc)
    out = np.full(len(ohlc), np.nan)
    cs = np.nancumsum(np.where(np.isnan(tr), 0, tr))
    cnt = np.cumsum(~np.isnan(tr))
    for i in range(n - 1, len(ohlc)):
        s = cs[i] - (cs[i - n] if i - n >= 0 else 0)
        c = cnt[i] - (cnt[i - n] if i - n >= 0 else 0)
        out[i] = s / c if c else np.nan
    return out


def ema50_series(c):
    """EMA50（SMA50 种子，k=2/51），与 v4.1 审计一致；不足 50 根为 nan。"""
    out = np.full(len(c), np.nan)
    if len(c) < 50:
        return out
    k = 2 / 51
    out[49] = float(np.mean(c[:50]))
    for i in range(50, len(c)):
        out[i] = c[i] * k + out[i - 1] * (1 - k)
    return out


def sma20_series(c):
    out = np.full(len(c), np.nan)
    cs = np.cumsum(c)
    for i in range(19, len(c)):
        out[i] = (cs[i] - (cs[i - 20] if i - 20 >= 0 else 0)) / 20
    return out


def swings_strict(ohlc):
    """key_levels.swings：严格 > / <（用于 find_levels）。"""
    h, l = ohlc[:, 1], ohlc[:, 2]
    hi, lo = [], []
    for i in range(2, len(ohlc) - 2):
        if all(h[i] > h[j] for j in range(i - 2, i + 3) if j != i):
            hi.append((i, h[i]))
        if all(l[i] < l[j] for j in range(i - 2, i + 3) if j != i):
            lo.append((i, l[i]))
    return hi, lo


def swings_tie(ohlc):
    """tae-scanner.swings：等于 max/min 也算摆动点（用于 1H 大趋势）。"""
    h, l = ohlc[:, 1], ohlc[:, 2]
    hi, lo = [], []
    for i in range(2, len(ohlc) - 2):
        if h[i] == max(h[i - 2:i + 3]):
            hi.append((i, h[i]))
        if l[i] == min(l[i - 2:i + 3]):
            lo.append((i, l[i]))
    return hi, lo


def big_trend_dir(ohlc_1h, atr_1h_last):
    """1H 严版大趋势（tae-scanner.big_trend_dir 原样）：
    最后 3 摆动高逐级抬高、每级 ≥0.5×ATR(1H)，摆动低同样；否则 None。
    调用方须保证 ohlc_1h 只含已收盘 1H 且长度 ≥60（不足返回 None）。"""
    if len(ohlc_1h) < 60:
        return None
    hi, lo = swings_tie(ohlc_1h)
    if len(hi) < 3 or len(lo) < 3:
        return None
    thr = 0.5 * atr_1h_last
    hv = [v for _, v in hi][-3:]
    lv = [v for _, v in lo][-3:]
    hs = [hv[i + 1] - hv[i] for i in range(2)]
    ls = [lv[i + 1] - lv[i] for i in range(2)]
    if all(x >= thr for x in hs) and all(x >= thr for x in ls):
        return "long"
    if all(x <= -thr for x in hs) and all(x <= -thr for x in ls):
        return "short"
    return None


# ---- E 形态：逐字复用 tae-scanner.py（C 组仅 hammer/shooting_star 加 body > 0） ----

def bull_engulf(p, q):
    return bool(p[3] < p[0] and q[3] > q[0]
                and q[0] <= p[3] * 1.001 and q[3] >= p[0] * 0.999)


def bear_engulf(p, q):
    return bool(p[3] > p[0] and q[3] < q[0]
                and q[0] >= p[3] * 0.999 and q[3] <= p[0] * 1.001)


def hammer(q, fix_doji=False):
    body = abs(q[0] - q[3])
    rng = q[1] - q[2]
    if rng <= 0:
        return False
    if fix_doji and body <= 0:
        return False
    lower = min(q[0], q[3]) - q[2]
    return bool(lower >= 2 * body and body <= 0.3 * rng)


def shooting_star(q, fix_doji=False):
    body = abs(q[0] - q[3])
    rng = q[1] - q[2]
    if rng <= 0:
        return False
    if fix_doji and body <= 0:
        return False
    upper = q[1] - max(q[0], q[3])
    return bool(upper >= 2 * body and body <= 0.3 * rng)


def morning_star(ohlc5, i):
    if i < 2:
        return False
    a, b, c = ohlc5[i - 2], ohlc5[i - 1], ohlc5[i]
    body_a = a[0] - a[3]
    if body_a <= 0:
        return False
    if abs(b[0] - b[3]) > 0.5 * body_a:
        return False
    if c[3] <= c[0]:
        return False
    return bool(c[3] > (a[0] + a[3]) / 2)


def evening_star(ohlc5, i):
    if i < 2:
        return False
    a, b, c = ohlc5[i - 2], ohlc5[i - 1], ohlc5[i]
    body_a = a[3] - a[0]
    if body_a <= 0:
        return False
    if abs(b[0] - b[3]) > 0.5 * body_a:
        return False
    if c[3] >= c[0]:
        return False
    return bool(c[3] < (a[0] + a[3]) / 2)


def is_signal_bar(ohlc5, i, direction, fix_doji=False):
    q = ohlc5[i]
    if direction == "long":
        return bool(hammer(q, fix_doji)
                    or (i > 0 and bull_engulf(ohlc5[i - 1], q))
                    or morning_star(ohlc5, i))
    return bool(shooting_star(q, fix_doji)
                or (i > 0 and bear_engulf(ohlc5[i - 1], q))
                or evening_star(ohlc5, i))
