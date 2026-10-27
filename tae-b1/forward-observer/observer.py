"""TAE 前向观察系统（forward observer）——只记录、不交易、不发信号。

用途：在真实新数据上持续记录突破 / 触碰 / 收复事件、特征与后续路径，
让研究与前向数据同步积累，不必等所有定义完美。系统不产生交易信号，
不改变 B1，不连接实盘，不推送任何消息。

检测口径：逐字复用 B1 Phase-A mechanics（rules-v0.1-frozen.md +
levels_pass.py 候选生成 + events_census.py Phase A 状态机）：
- 每根 15m 收盘时 trailing 400 根 find_levels 重算关键带；
- 候选：单根收盘穿越（多头 close[j-1] <= bhi < close[j]，空头镜像）
  且 1H 严版大趋势同向（B1 指针法：1H 收盘 <= 该 15m 收盘）；
- P3：每方向每根只取最贴近现价的一条带（多头取最大 bhi，空头取
  最小 blo），其余记 p3_shadowed；与同方向活跃序列带重叠则记
  overlap_active 并跳过；
- 序列状态机：先更新活跃序列（远沿收盘穿越作废 → 触碰标记 →
  收盘收复 → b0+48 根过期），再接入本根新候选；
- 收复后 N=48/96 窗口的先后顺序结局（A/B/C/D/T）与审查口径
  （ordered_outcomes.py）一致：摆动事件时刻 = 确认根收盘。

围栏（硬性，见 design.md 与 check_fences.py）：
- 只读复用 key_levels.py / b1_lib.py，绝不修改它们；不读、不写
  B1、扫描器、执行器的任何文件；不写任何推送 cron 或信号文件。
- 只访问一个公开接口：www.binance.com/fapi/v1/klines（公开行情，
  无密钥、无签名、无账户操作）。绝不调用下单、撤单、改杠杆等
  任何交易接口；绝不读取 .env / .env.live / 任何密钥文件。
- 只写 forward-observer/ 目录（state/、ledger.csv、skipped.csv、
  timeline.jsonl、manifest.json、freeze.json 除外——freeze.json
  仅由显式的冻结操作写入，本程序只在缺失时创建占位）。
- 不向 WhatsApp 或 App 发任何消息；cron 运行时只写 state/
  observer.log，不向用户侧输出。

存储语义：
- 原始 K 线：bar 级 append-only（只追加 t 更大的 bar；已存 bar 永不
  改写；内容冲突记入 manifest 并保留旧值）。文件以 atomic
  replace 写入（临时文件 + os.replace），防崩溃撕裂。
- 事件时间线 timeline.jsonl：append-only，每行一次状态变迁。
- ledger.csv：当前快照（行永不删除；状态字段随演化更新；
  created_at / outcome_resolved_at 等时间戳保留，供日后按冻结
  时刻切分“冻结前探索数据”与“冻结后验证数据”）。
- 待冻结的度量选择（I2-A 阈值、Theta 种子定义、I4-B 时刻约定、
  A 率主结局）一律不在记录时定死：本系统存下算出它们所需的
  原始输入（1H 摆动点清单、1H 收盘序列、两种种子读法下的 Theta
  取值），阈值与分组留待分析时计算。

运行：python3 observer.py --run（幂等：无新 bar 时直接退出；
有缺口时先回补再处理）。每 15 分钟由 cron 静默运行一次。
"""

import csv
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

import numpy as np

# 围栏：禁止写字节码缓存——import b1_lib / key_levels 时不得在
# hidden_files/__pycache__ 或 tae-b1/__pycache__ 落任何文件。
sys.dont_write_bytecode = True

sys.path.insert(0, "/home/hatch/workspace/goals/100u-200u/files/tae-b1")
sys.path.insert(0, "/home/hatch/workspace/goals/100u-200u/hidden_files")
from b1_lib import atr_series, is_signal_bar, swings_strict, swings_tie  # noqa: E402
from key_levels import find_levels  # noqa: E402

BASE = "/home/hatch/workspace/goals/100u-200u/files/tae-b1/forward-observer"
STATE = os.path.join(BASE, "state")
MIRROR = "https://www.binance.com/fapi/v1/klines"
SYMBOL = "ETHUSDT"
STEP = {"15m": 900_000, "1h": 3_600_000, "5m": 300_000}
WARMUP_DAYS = 45          # 首次运行拉取的历史长度（保证 trailing 400 根窗口完整）
VERSION = 1


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M")


def now_ms():
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def wall_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


# ---------------- 公开行情拉取（无密钥、无签名） ----------------

def fetch_klines(interval, start_ms, end_ms=None):
    """拉取公开 K 线（Binance klines 数组格式），分页取尽。
    返回 [(t_open, o, h, l, c)]，按 t 升序。只做公开行情读取。"""
    rows = []
    cur = start_ms
    step = STEP[interval]
    guard = 0
    while guard < 10000:
        guard += 1
        url = (f"{MIRROR}?symbol={SYMBOL}&interval={interval}&limit=1000"
               f"&startTime={cur}")
        if end_ms is not None:
            url += f"&endTime={end_ms}"
        req = urllib.request.Request(url, headers={"User-Agent": "TAE-forward-observer/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        if not data:
            break
        for r in data:
            rows.append((int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])))
        last_t = int(data[-1][0])
        if len(data) < 1000:
            break
        if end_ms is not None and last_t >= end_ms:
            break
        cur = last_t + step
    return rows


def closed_only(rows, interval, at_ms):
    """只保留已收盘 bar（open + step <= 当前时刻）。形成中的 bar 排除。"""
    step = STEP[interval]
    return [r for r in rows if r[0] + step <= at_ms]


# ---------------- 原始 K 线存储（bar 级 append-only） ----------------

def store_path(tf):
    return os.path.join(STATE, f"klines_{tf}.npz")


def load_store(tf):
    p = store_path(tf)
    if not os.path.exists(p) or os.path.getsize(p) == 0:
        return (np.array([], dtype=np.int64),
                np.zeros((0, 4), dtype=np.float64))
    d = np.load(p)
    return d["t"], d["ohlc"]


def save_store(tf, t, ohlc):
    # 注意：np.savez 会给不以 .npz 结尾的文件名自动补后缀，故临时名
    # 本身须以 .npz 结尾，否则 os.replace 找不到文件。
    tmp = store_path(tf) + ".tmp.npz"
    np.savez_compressed(tmp, t=t, ohlc=ohlc)
    os.replace(tmp, store_path(tf))


def merge_bars(t_old, o_old, new_rows):
    """合并新 bar：只追加 t 更大的 bar；已存 bar 永不改写。
    返回 (t, ohlc, n_added, conflicts, gaps)，gaps 为 (prev_t, next_t)。"""
    old = {int(t): row for t, row in zip(t_old, o_old)}
    conflicts = []
    added = 0
    for (t, o, h, l, c) in new_rows:
        if t in old:
            prev = old[t]
            if not (prev[0] == o and prev[1] == h and prev[2] == l and prev[3] == c):
                conflicts.append({"t": t, "stored": [float(x) for x in prev],
                                  "fetched": [o, h, l, c]})
            continue
        old[t] = np.array([o, h, l, c], dtype=np.float64)
        added += 1
    ts = sorted(old.keys())
    t = np.array(ts, dtype=np.int64)
    ohlc = np.array([old[x] for x in ts], dtype=np.float64)
    return t, ohlc, added, conflicts


def find_gaps(t, step):
    """返回 [(prev_t, next_t)]，其中 next_t - prev_t > step（缺 bar）。"""
    gaps = []
    for a, b in zip(t[:-1], t[1:]):
        if int(b) - int(a) > step:
            gaps.append((int(a), int(b)))
    return gaps


def backfill_gaps(tf, t, ohlc, at_ms):
    """对缺口做历史回补（公开 K 线可拉取，漏跑可自愈）。
    返回 (t, ohlc, filled_gaps, unfilled_gaps)。"""
    step = STEP[tf]
    filled, unfilled = [], []
    for _ in range(5):  # 最多 5 轮回补
        gaps = find_gaps(t, step)
        if not gaps:
            break
        progressed = False
        for (a, b) in gaps:
            rows = closed_only(fetch_klines(tf, a + step, b - step), tf, at_ms)
            if rows:
                t, ohlc, added, _ = merge_bars(t, ohlc, rows)
                if added:
                    filled.append((a, b, added))
                    progressed = True
        if not progressed:
            break
    remaining = find_gaps(t, step)
    for (a, b) in remaining:
        unfilled.append((a, b))
    return t, ohlc, filled, unfilled


# ---------------- 指标与趋势门（复用 B1 口径） ----------------

def atr1h_series(o1h):
    """1H ATR(14)，与 events_census.py 逐字相同的均值型算法。"""
    tr = np.full(len(o1h), np.nan)
    for i in range(1, len(o1h)):
        tr[i] = max(o1h[i][1] - o1h[i][2], abs(o1h[i][1] - o1h[i - 1][3]),
                    abs(o1h[i][2] - o1h[i - 1][3]))
    atr = np.full(len(o1h), np.nan)
    for i in range(13, len(o1h)):
        atr[i] = float(np.nanmean(tr[i - 13:i + 1]))
    return atr


class TrendGates:
    """1H 趋势门两种读法（与 events_census.py 一致，分开记录，不得混用）。
    B1 指针法：可用 1H = 收盘 <= T，摆动点 idx <= p-3；
    v0.2 严格早于法：可用 1H = 收盘 < T，摆动点 idx <= last-2。"""

    def __init__(self, t1h, o1h):
        self.t1h = t1h
        self.o1h = o1h
        self.t1h_close = t1h + 3_600_000
        self.atr1 = atr1h_series(o1h)
        hi_all, lo_all = swings_tie(o1h)
        self.hi_idx = np.array([i for i, _ in hi_all])
        self.hi_val = np.array([v for _, v in hi_all])
        self.lo_idx = np.array([i for i, _ in lo_all])
        self.lo_val = np.array([v for _, v in lo_all])

    def _eval(self, hi, lo, a):
        if len(hi) < 3 or len(lo) < 3:
            return "na", None, None, None
        hs = [(hi[i + 1] - hi[i]) / a for i in range(2)]
        ls = [(lo[i + 1] - lo[i]) / a for i in range(2)]
        if all(x >= 0.5 for x in hs) and all(x >= 0.5 for x in ls):
            return "long", hs, ls, a
        if all(x <= -0.5 for x in hs) and all(x <= -0.5 for x in ls):
            return "short", hs, ls, a
        return None, hs, ls, a

    def gate_b1(self, T):
        p = int(np.searchsorted(self.t1h_close, T, side="right"))
        if p < 60 or np.isnan(self.atr1[p - 1]):
            return "na", None, None, None
        a = float(self.atr1[p - 1])
        hi = [v for idx, v in zip(self.hi_idx, self.hi_val) if idx <= p - 3][-3:]
        lo = [v for idx, v in zip(self.lo_idx, self.lo_val) if idx <= p - 3][-3:]
        return self._eval(hi, lo, a)

    def gate_v02(self, T):
        cnt = int(np.searchsorted(self.t1h_close, T, side="left"))
        if cnt < 60:
            return "na", None, None, None
        last = cnt - 1
        if np.isnan(self.atr1[last]):
            return "na", None, None, None
        a = float(self.atr1[last])
        hi = [v for idx, v in zip(self.hi_idx, self.hi_val) if idx <= last - 2][-3:]
        lo = [v for idx, v in zip(self.lo_idx, self.lo_val) if idx <= last - 2][-3:]
        return self._eval(hi, lo, a)


def tg_label(g, d):
    if g == "na":
        return "na"
    if g is None:
        return "fail"
    return "pass_same" if g == d else "pass_opp"


# ---------------- 带元数据（find_levels_meta，逐字引自 events_census.py） ----------------
# 说明：key_levels.find_levels 本身不输出 first_touch_idx / touch_idx，
# 故此处沿用普查脚本里“与 key_levels 逐字相同的 valid-touch 逻辑”
# 的元数据版，仅用于 touches / last_touch_lag / span 三个描述字段；
# 带的取舍一律以 key_levels.find_levels 的返回为准，两者不一致时
# span 置空并记 meta_mismatch（与普查脚本行为一致）。

def _held_res(candles, idx, price, band_top, a):
    after = candles[idx + 1: idx + 9]
    if not after:
        return False
    if any(c["c"] > band_top for c in candles[idx + 1: idx + 5]):
        return False
    return price - min(c["l"] for c in after) >= 1.0 * a


def _held_sup(candles, idx, price, band_bottom, a):
    after = candles[idx + 1: idx + 9]
    if not after:
        return False
    if any(c["c"] < band_bottom for c in candles[idx + 1: idx + 5]):
        return False
    return max(c["h"] for c in after) - price >= 1.0 * a


def _clusters(points, tol):
    pts = sorted(points, key=lambda x: x[1])
    out, cur = [], [pts[0]]
    for p in pts[1:]:
        if p[1] - cur[-1][1] <= tol:
            cur.append(p)
        else:
            out.append(cur)
            cur = [p]
    out.append(cur)
    return out


def _swings_dict(candles, k=2):
    hi, lo = [], []
    for i in range(k, len(candles) - k):
        h = candles[i]["h"]
        l = candles[i]["l"]
        if all(h > candles[j]["h"] for j in range(i - k, i + k + 1) if j != i):
            hi.append((i, h))
        if all(l < candles[j]["l"] for j in range(i - k, i + k + 1) if j != i):
            lo.append((i, l))
    return hi, lo


def find_levels_meta(candles, a):
    hi, lo = _swings_dict(candles)
    out = []
    for cl in _clusters(hi, 0.35 * a):
        band = (min(v for _, v in cl), max(v for _, v in cl))
        valid = [(i, v) for i, v in cl if _held_res(candles, i, v, band[1], a)]
        if len(valid) < 3:
            continue
        valid = valid[-9:]
        vals = [v for _, v in valid]
        last_i = max(i for i, _ in valid)
        if len(candles) - 1 - last_i > 96:
            continue
        out.append({"kind": "resistance", "line": min(vals),
                    "band": (min(vals), max(vals)), "touches": len(valid),
                    "last_touch_idx": last_i, "first_touch_idx": min(i for i, _ in valid),
                    "touch_idx": [i for i, _ in valid]})
    remaining = list(lo)
    while remaining:
        best_line, best_touch = None, []
        for _, cand in remaining:
            touch = [p for p in remaining if abs(p[1] - cand) <= 0.2 * a]
            if len(touch) > len(best_touch):
                best_line, best_touch = cand, touch
        if len(best_touch) < 3:
            break
        members = [p for p in remaining if abs(p[1] - best_line) <= 0.6 * a]
        members.sort(key=lambda x: abs(x[1] - best_line))
        members = members[:12]
        band = (min(v for _, v in members), max(v for _, v in members))
        valid = [(i, v) for i, v in members if _held_sup(candles, i, v, band[0], a)]
        used = set(id(p) for p in members)
        remaining = [p for p in remaining if id(p) not in used]
        if len(valid) < 3:
            continue
        valid = valid[-9:]
        vals = [v for _, v in valid]
        last_i = max(i for i, _ in valid)
        if len(candles) - 1 - last_i > 96:
            continue
        out.append({"kind": "support", "line": best_line,
                    "band": (min(vals), max(vals)), "touches": len(valid),
                    "last_touch_idx": last_i, "first_touch_idx": min(i for i, _ in valid),
                    "touch_idx": [i for i, _ in valid]})
    out.sort(key=lambda x: -x["touches"])
    kept = []
    for L in out:
        dup = False
        for K in kept:
            lo_ = max(L["band"][0], K["band"][0])
            hi_ = min(L["band"][1], K["band"][1])
            if hi_ > lo_ and (hi_ - lo_) >= 0.5 * min(L["band"][1] - L["band"][0],
                                                     K["band"][1] - K["band"][0]):
                dup = True
                break
        if not dup:
            kept.append(L)
    kept.sort(key=lambda x: x["line"])
    return kept


# ---------------- I4-A 失效扫描（两种种子读法，描述性度量） ----------------
# 读法 M（普查实现）：种子 = 截至 b0 全部已确认摆动极值的极值
#   （多头取最大摆动低，空头取最小摆动高），之后新确认摆动继续取极值。
# 读法 L（文档本意）：种子 = 截至 b0 最新已确认摆动极值（最大 idx），
#   之后每次新确认摆动出现即跟踪最新者。两种读法确认时序相同：
#   新摆动纳入条件与普查一致（摆动 bar open > b0_close 且 idx <= k-2）。
# 两者只相差种子聚合方式；本系统把两种取值都存下来，冻结时再选。

def i4a_scan(t1h, o1h, t1h_close, atr1, hi_idx, hi_val, lo_idx, lo_val,
             b0_close_ms, end_close_ms, direction, reading):
    """扫描 (b0_close, end_close] 内的 1H 收盘，返回
    (first_invalid, seed, theta_at_end)。first_invalid 为
    (k, close_ms, close, theta, depth_atr) 或 None；theta_at_end 为
    末根评价 bar 时的 Theta（无评价 bar 时为种子）。评价根本身可用；
    盘中触及不算；吸收态（首次即停）。"""
    k0 = int(np.searchsorted(t1h_close, b0_close_ms, side="right"))
    k1 = int(np.searchsorted(t1h_close, end_close_ms, side="right")) - 1
    if k1 < k0:
        return None, None, None
    last_at_b0 = int(np.searchsorted(t1h_close, b0_close_ms, side="right")) - 1
    if direction == "long":
        idx_arr, val_arr, agg = lo_idx, lo_val, max
    else:
        idx_arr, val_arr, agg = hi_idx, hi_val, min
    conf = [(idx, v) for idx, v in zip(idx_arr, val_arr) if idx <= last_at_b0 - 2]
    if not conf:
        return None, None, None
    if reading == "M":
        theta = agg(v for _, v in conf)
    else:
        theta = max(conf, key=lambda p: p[0])[1]
    seed = theta
    for k in range(k0, k1 + 1):
        new = [(idx, v) for idx, v in zip(idx_arr, val_arr)
               if idx <= k - 2 and int(t1h[idx]) + 3_600_000 > b0_close_ms]
        if new:
            if reading == "M":
                theta = agg([theta] + [v for _, v in new])
            else:
                theta = max(new, key=lambda p: p[0])[1]
        cl = float(o1h[k][3])
        hit = (direction == "long" and cl <= theta) or \
              (direction == "short" and cl >= theta)
        if hit:
            a = float(atr1[k])
            depth = ((theta - cl) / a if direction == "long"
                     else (cl - theta) / a) if a and not np.isnan(a) else None
            return (k, int(t1h_close[k]), cl, theta, depth), seed, theta
    return None, seed, theta


# ---------------- E 信号（仅描述性特征，不触发任何动作） ----------------

def e_stage(t5, o5, t15, c15, r, d, blo, bhi):
    """收复根 r 之后 3 根已收盘 5m 内是否出现顺方向 E 信号。
    返回 (signal_any, status, signal_bar_close_ms)。
    status：signal / timeout / coincident_void / no_reclaim。
    不算触发价、不算成交、不算杠杆——那些是交易 mechanics，本系统不做。
    coincident 规则与普查一致：信号恰在第 3 根 5m 且下一根 15m 收盘
    穿越远沿时记 coincident_void（信号本身仍记入 signal_any）。"""
    if r is None:
        return 0, "no_reclaim", ""
    tr_close = int(t15[r]) + 900_000
    m0 = int(np.searchsorted(t5, tr_close, side="left"))
    sig_any = 0
    sig_close = ""
    status = "timeout"
    for k in range(3):
        m = m0 + k
        if m >= len(t5):
            break
        if is_signal_bar(o5, m, d, False):
            if sig_any == 0:
                sig_close = int(t5[m]) + 300_000
            sig_any = 1
            if k == 2 and r + 1 < len(t15):
                c_next = float(c15[r + 1])
                if (d == "long" and c_next < blo) or \
                   (d == "short" and c_next > bhi):
                    status = "coincident_void"
                    return sig_any, status, sig_close
            if status == "timeout":
                status = "signal"
    return sig_any, status, sig_close


# ---------------- 收复后窗口先后顺序结局（与审查口径一致） ----------------

def ordered_class(t15, c15, h15, l15, shi_idx, shi_val, slo_idx, slo_val,
                  term, N, d, blo, bhi, b0_idx):
    """返回 dict：class ∈ {A,B,C,D,T}，swing_bar/conf，ft_idx，gap，
    fell_back，fell_through。摆动事件时刻 = 确认根收盘（摆动 bar + 2）。
    窗口为 (term, term+N]；确认根须在窗口内。"""
    b0_ext = float(h15[b0_idx]) if d == "long" else float(l15[b0_idx])
    ft = None
    for m in range(term + 1, term + N + 1):
        if d == "long" and c15[m] < blo:
            ft = m
            break
        if d == "short" and c15[m] > bhi:
            ft = m
            break
    sw_bar, conf = None, None
    for i in range(term + 1, term + N + 1):
        if d == "long" and i in shi_idx and i + 2 <= term + N \
                and shi_val[i] > b0_ext:
            sw_bar, conf = i, i + 2
            break
        if d == "short" and i in slo_idx and i + 2 <= term + N \
                and slo_val[i] < b0_ext:
            sw_bar, conf = i, i + 2
            break
    if conf is None and ft is None:
        cls = "D"
    elif conf is not None and ft is None:
        cls = "A"
    elif conf is None and ft is not None:
        cls = "C"
    elif conf < ft:
        cls = "A"
    elif ft < conf:
        cls = "B"
    else:
        cls = "T"
    seg_c = c15[term + 1:term + N + 1]
    fell_back = int(np.any((seg_c >= blo) & (seg_c <= bhi)))
    gap = ""
    if cls == "A" and ft is not None:
        gap = ft - conf
    elif cls == "B":
        gap = conf - ft
    return {"class": cls, "swing_bar": sw_bar, "swing_conf": conf,
            "ft_idx": ft, "gap": gap, "fell_back": fell_back,
            "fell_through": int(ft is not None)}


# ---------------- 状态与输出 ----------------

def atomic_write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, ensure_ascii=False, default=str)
    os.replace(tmp, path)


def load_state():
    p = os.path.join(STATE, "sequences.json")
    if os.path.exists(p) and os.path.getsize(p) > 0:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    return {"version": VERSION, "sequences": [], "skipped": [],
            "last_processed_idx": 398, "next_seq_no": 1, "next_skip_no": 1}


def save_state(st):
    atomic_write_json(os.path.join(STATE, "sequences.json"), st)


def timeline_append(events):
    if not events:
        return
    with open(os.path.join(BASE, "timeline.jsonl"), "a", encoding="utf-8") as fh:
        for ev in events:
            fh.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")


LEDGER_FIELDS = [
    "seq_id", "dir", "b0_time_utc", "b0_idx", "band_lo", "band_hi", "band_line",
    "band_width_atr", "band_touches", "band_last_touch_lag", "band_span_bars",
    "band_meta_mismatch", "trend_gate_b1", "trend_v02_at_b0",
    "trend_step_high_min_atr", "trend_step_low_min_atr", "atr1h_at_b0",
    "outcome", "outcome_time_utc", "touched", "first_touch_time_utc",
    "first_touch_lag_bars", "reclaim_time_utc", "reclaim_lag_bars",
    "window_type", "touch_count_bars", "extreme_value", "anchor_time_utc",
    "i2a_depth_atr", "i2a_rebound_final_atr", "i2a_rebound_max_atr",
    "i2a_pos_final", "i2b_dwell_max_consec",
    "e_signal_any", "e_status", "e_time_utc",
    "i4a_M_invalidated_during", "i4a_M_invalidation_time_utc", "i4a_M_depth_atr",
    "i4a_L_invalidated_during", "i4a_L_invalidation_time_utc", "i4a_L_depth_atr",
    "theta_seed_M", "theta_seed_L", "theta_M_at_reclaim", "theta_L_at_reclaim",
    "i4b_recheck_t0", "i4b_recheck_reclaim",
    "post48_status", "post48_class", "post48_fell_back", "post48_fell_through",
    "post48_swing_bar", "post48_swing_conf", "post48_ft_idx", "post48_gap",
    "post48_i4a_M_invalidated", "post48_i4a_L_invalidated", "post48_trend_gate_end",
    "post96_status", "post96_class", "post96_fell_back", "post96_fell_through",
    "post96_swing_bar", "post96_swing_conf", "post96_ft_idx", "post96_gap",
    "post96_i4a_M_invalidated", "post96_i4a_L_invalidated", "post96_trend_gate_end",
    "created_at", "updated_at", "outcome_resolved_at",
    "post48_resolved_at", "post96_resolved_at",
]

SKIPPED_FIELDS = ["skip_id", "bar_time_utc", "bar_idx", "dir", "band_lo",
                  "band_hi", "reason", "recorded_at"]


def write_ledger(sequences):
    rows = sorted(sequences, key=lambda s: (s["b0_time_ms"], s["dir"]))
    with open(os.path.join(BASE, "ledger.csv"), "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=LEDGER_FIELDS, extrasaction="ignore")
        wr.writeheader()
        for s in rows:
            out = dict(s)
            for k in ("b0_time_ms",):
                out.pop(k, None)
            wr.writerow(out)


def write_skipped(skipped):
    with open(os.path.join(BASE, "skipped.csv"), "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=SKIPPED_FIELDS, extrasaction="ignore")
        wr.writeheader()
        wr.writerows(skipped)


# ---------------- 主处理：增量 Phase-A ----------------

class Ctx:
    def __init__(self, t15, o15, t1h, o1h, t5, o5):
        self.t15, self.o15 = t15, o15
        self.c15, self.h15, self.l15 = o15[:, 3], o15[:, 1], o15[:, 2]
        self.t15_close = t15 + 900_000
        self.atr15 = atr_series(o15)
        self.t1h, self.o1h = t1h, o1h
        self.t1h_close = t1h + 3_600_000
        self.gates = TrendGates(t1h, o1h)
        self.t5, self.o5 = t5, o5
        shi, slo = swings_strict(o15)
        self.shi_idx = set(i for i, _ in shi)
        self.shi_val = dict(shi)
        self.slo_idx = set(i for i, _ in slo)
        self.slo_val = dict(slo)


def band_meta_at(ctx, j):
    """b0 时刻 trailing 400 根窗口的带元数据（与普查脚本一致）。"""
    win = [{"o": float(r[0]), "h": float(r[1]), "l": float(r[2]), "c": float(r[3])}
           for r in ctx.o15[j - 399:j + 1]]
    a = float(ctx.atr15[j])
    lv = find_levels(win, a)
    lv_meta = find_levels_meta(win, a)
    return lv, lv_meta


def match_band(lv, blo, bhi):
    for L in lv:
        if abs(L["band"][0] - blo) < 1e-9 and abs(L["band"][1] - bhi) < 1e-9:
            return L
    return None


def compute_window_features(ctx, s):
    """终端时刻的窗口特征（[t0, terminal]，与普查脚本公式一致）。"""
    d, t0, term = s["dir"], s["first_touch_idx"], s["terminal_idx"]
    blo, bhi = s["band_lo"], s["band_hi"]
    seg_l = ctx.l15[t0:term + 1]
    seg_h = ctx.h15[t0:term + 1]
    seg_c = ctx.c15[t0:term + 1]
    touch_bars = [i for i in range(t0, term + 1)
                  if ctx.l15[i] <= bhi and ctx.h15[i] >= blo]
    max_consec = cur = 0
    for i in range(t0, term + 1):
        ok = (ctx.l15[i] <= bhi and ctx.h15[i] >= blo) and \
             ((d == "long" and ctx.c15[i] >= blo) or (d == "short" and ctx.c15[i] <= bhi))
        cur = cur + 1 if ok else 0
        max_consec = max(max_consec, cur)
    atr_term = float(ctx.atr15[term])
    if d == "long":
        anchor = float(np.min(seg_l))
        anchor_rel = int(np.argmin(seg_l))
        depth = (bhi - anchor) / atr_term
        reb_final = (float(seg_c[-1]) - anchor) / atr_term
        reb_max = max((float(c) - anchor) / atr_term for c in seg_c[anchor_rel:])
    else:
        anchor = float(np.max(seg_h))
        anchor_rel = int(np.argmax(seg_h))
        depth = (anchor - blo) / atr_term
        reb_final = (anchor - float(seg_c[-1])) / atr_term
        reb_max = max((anchor - float(c)) / atr_term for c in seg_c[anchor_rel:])
    hb, lb, cb = float(ctx.h15[term]), float(ctx.l15[term]), float(ctx.c15[term])
    pos_final = (cb - lb) / (hb - lb) if hb > lb else ""
    s.update({
        "window_type": "reclaim" if s["outcome"] == "reclaimed" else "truncated",
        "touch_count_bars": len(touch_bars),
        "extreme_value": anchor,
        "anchor_time_utc": iso(int(ctx.t15[t0 + anchor_rel])),
        "i2a_depth_atr": depth,
        "i2a_rebound_final_atr": reb_final,
        "i2a_rebound_max_atr": reb_max,
        "i2a_pos_final": pos_final,
        "i2b_dwell_max_consec": max_consec,
    })


def compute_i4a_i4b(ctx, s):
    """终端时刻的 I4-A（两种种子读法）与 I4-B 重检（v0.2 严格早于法）。"""
    d = s["dir"]
    b0_close = int(ctx.t15_close[s["b0_idx"]])
    term_close = int(ctx.t15_close[s["terminal_idx"]])
    for reading in ("M", "L"):
        inv, seed, theta_end = i4a_scan(
            ctx.t1h, ctx.o1h, ctx.t1h_close, ctx.gates.atr1,
            ctx.gates.hi_idx, ctx.gates.hi_val, ctx.gates.lo_idx, ctx.gates.lo_val,
            b0_close, term_close, d, reading)
        s[f"theta_seed_{reading}"] = seed
        s[f"i4a_{reading}_invalidated_during"] = int(inv is not None)
        s[f"i4a_{reading}_invalidation_time_utc"] = iso(inv[1]) if inv else ""
        s[f"i4a_{reading}_depth_atr"] = inv[4] if inv else ""
        if s["outcome"] == "reclaimed":
            s[f"theta_{reading}_at_reclaim"] = theta_end
        else:
            s[f"theta_{reading}_at_reclaim"] = ""
    if s["touched"]:
        Tt0 = int(ctx.t15_close[s["first_touch_idx"]])
        g_t0, _, _, _ = ctx.gates.gate_v02(Tt0)
        s["i4b_recheck_t0"] = tg_label(g_t0, d)
        if s["outcome"] == "reclaimed":
            Tr = int(ctx.t15_close[s["terminal_idx"]])
            i_t0 = int(np.searchsorted(ctx.t1h_close, Tt0, side="left"))
            i_r = int(np.searchsorted(ctx.t1h_close, Tr, side="left"))
            if i_t0 < len(ctx.t1h_close) and i_r < len(ctx.t1h_close) \
                    and int(ctx.t1h_close[i_t0]) == int(ctx.t1h_close[i_r]):
                s["i4b_recheck_t0"] = "merged_into_reclaim"
            g_r, _, _, _ = ctx.gates.gate_v02(Tr)
            s["i4b_recheck_reclaim"] = tg_label(g_r, d)
        else:
            s["i4b_recheck_reclaim"] = "na_no_reclaim"
    else:
        s["i4b_recheck_t0"] = "na_no_touch"
        s["i4b_recheck_reclaim"] = "na_no_touch"


def resolve_post_window(ctx, s, N):
    """收复后 N 根窗口的先后顺序结局（审查口径）与附带结构量。"""
    d, term = s["dir"], s["terminal_idx"]
    blo, bhi = s["band_lo"], s["band_hi"]
    oc = ordered_class(ctx.t15, ctx.c15, ctx.h15, ctx.l15,
                       ctx.shi_idx, ctx.shi_val, ctx.slo_idx, ctx.slo_val,
                       term, N, d, blo, bhi, s["b0_idx"])
    p = f"post{N}"
    s[f"{p}_status"] = "resolved"
    s[f"{p}_class"] = oc["class"]
    s[f"{p}_fell_back"] = oc["fell_back"]
    s[f"{p}_fell_through"] = oc["fell_through"]
    s[f"{p}_swing_bar"] = oc["swing_bar"] if oc["swing_bar"] is not None else ""
    s[f"{p}_swing_conf"] = oc["swing_conf"] if oc["swing_conf"] is not None else ""
    s[f"{p}_ft_idx"] = oc["ft_idx"] if oc["ft_idx"] is not None else ""
    s[f"{p}_gap"] = oc["gap"]
    b0_close = int(ctx.t15_close[s["b0_idx"]])
    term_close = int(ctx.t15_close[term])
    win_close = int(ctx.t15_close[term + N])
    for reading in ("M", "L"):
        inv, _, _ = i4a_scan(
            ctx.t1h, ctx.o1h, ctx.t1h_close, ctx.gates.atr1,
            ctx.gates.hi_idx, ctx.gates.hi_val, ctx.gates.lo_idx, ctx.gates.lo_val,
            b0_close, win_close, d, reading)
        s[f"{p}_i4a_{reading}_invalidated"] = int(
            inv is not None and inv[1] > term_close)
    g_end, _, _, _ = ctx.gates.gate_v02(win_close)
    s[f"{p}_trend_gate_end"] = tg_label(g_end, d)
    s[f"{p}_resolved_at"] = wall_iso()


def process_bars(ctx, st, start_j, end_j):
    """增量 Phase-A：处理 15m bar [start_j, end_j]（闭区间）。
    返回 (n_new_seq, n_resolved, timeline_events)。"""
    events = []
    n_new = 0
    active = [s for s in st["sequences"] if s["outcome"] == "active"]
    for j in range(start_j, end_j + 1):
        cj, hj, lj = float(ctx.c15[j]), float(ctx.h15[j]), float(ctx.l15[j])
        nxt = []
        for s in active:
            d = s["dir"]
            blo, bhi = s["band_lo"], s["band_hi"]
            terminal = None
            if d == "long":
                if cj < blo:
                    terminal = "voided"
                else:
                    if not s["touched"] and lj <= bhi and hj >= blo:
                        s["touched"] = 1
                        s["first_touch_idx"] = j
                        s["first_touch_time_utc"] = iso(int(ctx.t15[j]))
                        s["first_touch_lag_bars"] = j - s["b0_idx"]
                        events.append({"ts": wall_iso(), "bar_time_utc": iso(int(ctx.t15[j])),
                                       "event": "touched", "seq_id": s["seq_id"]})
                    if s["touched"] and cj > bhi:
                        terminal = "reclaimed"
                    elif j >= s["b0_idx"] + 48:
                        terminal = "expired"
            else:
                if cj > bhi:
                    terminal = "voided"
                else:
                    if not s["touched"] and lj <= bhi and hj >= blo:
                        s["touched"] = 1
                        s["first_touch_idx"] = j
                        s["first_touch_time_utc"] = iso(int(ctx.t15[j]))
                        s["first_touch_lag_bars"] = j - s["b0_idx"]
                        events.append({"ts": wall_iso(), "bar_time_utc": iso(int(ctx.t15[j])),
                                       "event": "touched", "seq_id": s["seq_id"]})
                    if s["touched"] and cj < blo:
                        terminal = "reclaimed"
                    elif j >= s["b0_idx"] + 48:
                        terminal = "expired"
            if terminal:
                s["outcome"] = terminal
                s["terminal_idx"] = j
                s["outcome_time_utc"] = iso(int(ctx.t15_close[j]))
                s["outcome_resolved_at"] = wall_iso()
                if terminal == "reclaimed":
                    s["reclaim_time_utc"] = iso(int(ctx.t15_close[j]))
                    s["reclaim_lag_bars"] = j - s["b0_idx"]
                if s["touched"]:
                    compute_window_features(ctx, s)
                else:
                    s.update({"window_type": "", "touch_count_bars": 0,
                              "extreme_value": "", "anchor_time_utc": "",
                              "i2a_depth_atr": "", "i2a_rebound_final_atr": "",
                              "i2a_rebound_max_atr": "", "i2a_pos_final": "",
                              "i2b_dwell_max_consec": 0})
                compute_i4a_i4b(ctx, s)
                if terminal == "reclaimed":
                    s["e_status"] = "pending"
                else:
                    s["e_signal_any"] = 0
                    s["e_status"] = "no_reclaim"
                    s["e_time_utc"] = ""
                s["updated_at"] = wall_iso()
                events.append({"ts": wall_iso(), "bar_time_utc": iso(int(ctx.t15[j])),
                               "event": terminal, "seq_id": s["seq_id"]})
            else:
                nxt.append(s)
        active = nxt
        # ---- 本根新候选（levels_pass 口径 + P3 + 重叠跳过）----
        win = [{"o": float(r[0]), "h": float(r[1]), "l": float(r[2]), "c": float(r[3])}
               for r in ctx.o15[j - 399:j + 1]]
        lv = find_levels(win, float(ctx.atr15[j]))
        if lv:
            tr, _, _, _ = ctx.gates.gate_b1(int(ctx.t15_close[j]))
            if tr in ("long", "short"):
                cj_prev = float(ctx.c15[j - 1])
                cands = []
                for L in lv:
                    blo, bhi = L["band"]
                    if tr == "long" and L["kind"] == "resistance" \
                            and cj_prev <= bhi and cj > bhi:
                        cands.append(("long", blo, bhi))
                    if tr == "short" and L["kind"] == "support" \
                            and cj_prev >= blo and cj < blo:
                        cands.append(("short", blo, bhi))
                for d in ("long", "short"):
                    dc = [c for c in cands if c[0] == d]
                    if not dc:
                        continue
                    if d == "long":
                        pick = max(dc, key=lambda c: c[2])
                    else:
                        pick = min(dc, key=lambda c: c[1])
                    for c in dc:
                        if c is not pick:
                            st["skipped"].append({
                                "skip_id": f"X{st['next_skip_no']:04d}",
                                "bar_time_utc": iso(int(ctx.t15[j])), "bar_idx": j,
                                "dir": d, "band_lo": c[1], "band_hi": c[2],
                                "reason": "p3_shadowed", "recorded_at": wall_iso()})
                            st["next_skip_no"] += 1
                            events.append({"ts": wall_iso(),
                                           "bar_time_utc": iso(int(ctx.t15[j])),
                                           "event": "skipped_p3_shadowed",
                                           "dir": d, "band_lo": c[1], "band_hi": c[2]})
                    blo, bhi = pick[1], pick[2]
                    overlap = any(s["dir"] == d and not (bhi < s["band_lo"] or blo > s["band_hi"])
                                  for s in active)
                    if overlap:
                        st["skipped"].append({
                            "skip_id": f"X{st['next_skip_no']:04d}",
                            "bar_time_utc": iso(int(ctx.t15[j])), "bar_idx": j,
                            "dir": d, "band_lo": blo, "band_hi": bhi,
                            "reason": "overlap_active", "recorded_at": wall_iso()})
                        st["next_skip_no"] += 1
                        events.append({"ts": wall_iso(),
                                       "bar_time_utc": iso(int(ctx.t15[j])),
                                       "event": "skipped_overlap", "dir": d,
                                       "band_lo": blo, "band_hi": bhi})
                        continue
                    lv_m, lv_meta = band_meta_at(ctx, j)
                    meta = match_band(lv_m, blo, bhi)
                    meta_m = match_band(lv_meta, blo, bhi)
                    mismatch = 0
                    if meta is None or meta_m is None \
                            or meta["touches"] != meta_m["touches"] \
                            or meta["last_touch_idx"] != meta_m["last_touch_idx"]:
                        mismatch = 1
                        touches = meta["touches"] if meta else ""
                        lag = (399 - meta["last_touch_idx"]) if meta else ""
                        span = ""
                        line = meta["line"] if meta else ""
                    else:
                        touches = meta["touches"]
                        lag = 399 - meta["last_touch_idx"]
                        span = meta_m["last_touch_idx"] - meta_m["first_touch_idx"]
                        line = meta["line"]
                    Tb0 = int(ctx.t15_close[j])
                    g_b1, _, _, _ = ctx.gates.gate_b1(Tb0)
                    g_v02, hs_v02, ls_v02, a_v02 = ctx.gates.gate_v02(Tb0)
                    seq = {
                        "seq_id": f"FO-{st['next_seq_no']:04d}",
                        "dir": d, "b0_idx": j, "b0_time_ms": int(ctx.t15[j]),
                        "b0_time_utc": iso(int(ctx.t15[j])),
                        "band_lo": blo, "band_hi": bhi, "band_line": line,
                        "band_width_atr": (bhi - blo) / float(ctx.atr15[j]),
                        "band_touches": touches, "band_last_touch_lag": lag,
                        "band_span_bars": span, "band_meta_mismatch": mismatch,
                        "trend_gate_b1": tg_label(g_b1, d),
                        "trend_v02_at_b0": tg_label(g_v02, d),
                        "trend_step_high_min_atr": min(hs_v02) if hs_v02 else "",
                        "trend_step_low_min_atr": min(ls_v02) if ls_v02 else "",
                        "atr1h_at_b0": a_v02 if a_v02 else "",
                        "outcome": "active", "outcome_time_utc": "",
                        "touched": 0, "first_touch_idx": None,
                        "first_touch_time_utc": "", "first_touch_lag_bars": "",
                        "reclaim_time_utc": "", "reclaim_lag_bars": "",
                        "window_type": "", "touch_count_bars": "",
                        "extreme_value": "", "anchor_time_utc": "",
                        "i2a_depth_atr": "", "i2a_rebound_final_atr": "",
                        "i2a_rebound_max_atr": "", "i2a_pos_final": "",
                        "i2b_dwell_max_consec": "",
                        "e_signal_any": "", "e_status": "", "e_time_utc": "",
                        "i4a_M_invalidated_during": "",
                        "i4a_M_invalidation_time_utc": "", "i4a_M_depth_atr": "",
                        "i4a_L_invalidated_during": "",
                        "i4a_L_invalidation_time_utc": "", "i4a_L_depth_atr": "",
                        "theta_seed_M": "", "theta_seed_L": "",
                        "theta_M_at_reclaim": "", "theta_L_at_reclaim": "",
                        "i4b_recheck_t0": "", "i4b_recheck_reclaim": "",
                        "post48_status": "", "post48_class": "", "post48_fell_back": "",
                        "post48_fell_through": "", "post48_swing_bar": "",
                        "post48_swing_conf": "", "post48_ft_idx": "", "post48_gap": "",
                        "post48_i4a_M_invalidated": "", "post48_i4a_L_invalidated": "",
                        "post48_trend_gate_end": "",
                        "post96_status": "", "post96_class": "", "post96_fell_back": "",
                        "post96_fell_through": "", "post96_swing_bar": "",
                        "post96_swing_conf": "", "post96_ft_idx": "", "post96_gap": "",
                        "post96_i4a_M_invalidated": "", "post96_i4a_L_invalidated": "",
                        "post96_trend_gate_end": "",
                        "created_at": wall_iso(), "updated_at": wall_iso(),
                        "outcome_resolved_at": "", "post48_resolved_at": "",
                        "post96_resolved_at": "",
                    }
                    st["sequences"].append(seq)
                    active.append(seq)
                    st["next_seq_no"] += 1
                    n_new += 1
                    events.append({"ts": wall_iso(), "bar_time_utc": iso(int(ctx.t15[j])),
                                   "event": "sequence_opened", "seq_id": seq["seq_id"],
                                   "dir": d, "band_lo": blo, "band_hi": bhi})
    return n_new, events


def resolve_pending(ctx, st, last_j):
    """结算待定项：E 信号（需 5m 覆盖 + 下一根 15m 已处理）与收复后窗口。"""
    events = []
    n_res = 0
    t5_last_close = int(ctx.t5[-1]) + 300_000 if len(ctx.t5) else 0
    for s in st["sequences"]:
        if s["outcome"] == "reclaimed" and s["e_status"] == "pending":
            r = s["terminal_idx"]
            tr_close = int(ctx.t15_close[r])
            if r + 1 <= last_j and t5_last_close >= tr_close + 900_000:
                sig_any, status, sig_close = e_stage(
                    ctx.t5, ctx.o5, ctx.t15, ctx.c15, r, s["dir"],
                    s["band_lo"], s["band_hi"])
                s["e_signal_any"] = sig_any
                s["e_status"] = status
                s["e_time_utc"] = iso(sig_close) if sig_close else ""
                s["updated_at"] = wall_iso()
                events.append({"ts": wall_iso(), "bar_time_utc": iso(tr_close),
                               "event": "e_resolved", "seq_id": s["seq_id"],
                               "e_status": status})
                n_res += 1
        if s["outcome"] == "reclaimed":
            term = s["terminal_idx"]
            for N in (48, 96):
                if s[f"post{N}_status"] in ("", "pending") and last_j >= term + N:
                    resolve_post_window(ctx, s, N)
                    events.append({"ts": wall_iso(),
                                   "bar_time_utc": iso(int(ctx.t15_close[term + N])),
                                   "event": f"post{N}_resolved", "seq_id": s["seq_id"],
                                   "class": s[f"post{N}_class"]})
                    n_res += 1
    return n_res, events


# ---------------- 主流程 ----------------

def run_once():
    at_ms = now_ms()
    os.makedirs(STATE, exist_ok=True)
    manifest = {}
    for tf in ("15m", "1h", "5m"):
        t, ohlc = load_store(tf)
        step = STEP[tf]
        if len(t) == 0:
            start = (at_ms - WARMUP_DAYS * 86_400_000) // step * step
            rows = closed_only(fetch_klines(tf, start), tf, at_ms)
            t, ohlc, added, conflicts = merge_bars(t, ohlc, rows)
        else:
            rows = closed_only(fetch_klines(tf, int(t[-1]) + step), tf, at_ms)
            t, ohlc, added, conflicts = merge_bars(t, ohlc, rows)
        t, ohlc, filled, unfilled = backfill_gaps(tf, t, ohlc, at_ms)
        save_store(tf, t, ohlc)
        manifest[tf] = {
            "first_bar": iso(int(t[0])) if len(t) else "",
            "last_bar": iso(int(t[-1])) if len(t) else "",
            "n_bars": int(len(t)),
            "added_this_run": int(added),
            "conflicts_this_run": conflicts,
            "gaps_filled": filled,
            "gaps_unfilled": unfilled,
        }
    t15, o15 = load_store("15m")
    t1h, o1h = load_store("1h")
    t5, o5 = load_store("5m")
    if len(t15) < 400 or len(t1h) < 60:
        print("insufficient history (15m=%d 1h=%d), exit" % (len(t15), len(t1h)))
        return 1
    st = load_state()
    ctx = Ctx(t15, o15, t1h, o1h, t5, o5)
    last_j = len(t15) - 1
    start_j = max(399, st["last_processed_idx"] + 1)
    n_new, events = (0, [])
    if start_j <= last_j:
        n_new, events = process_bars(ctx, st, start_j, last_j)
        st["last_processed_idx"] = last_j
    n_res, events2 = resolve_pending(ctx, st, last_j)
    events = events + events2
    save_state(st)
    write_ledger(st["sequences"])
    write_skipped(st["skipped"])
    timeline_append(events)
    freeze_p = os.path.join(BASE, "freeze.json")
    if not os.path.exists(freeze_p):
        atomic_write_json(freeze_p, {
            "freeze_time_utc": None,
            "note": "Set freeze_time_utc when the user freezes definitions; "
                    "analysis splits sequences by b0_time_utc vs freeze_time_utc "
                    "into pre-freeze exploration data and post-freeze validation data.",
        })
    manifest.update({
        "version": VERSION,
        "data_source": MIRROR + " (public klines, no key, no signature)",
        "last_processed_15m_idx": int(st["last_processed_idx"]),
        "last_processed_15m_time": iso(int(t15[st["last_processed_idx"]])),
        "sequences_total": len(st["sequences"]),
        "active_count": sum(1 for s in st["sequences"] if s["outcome"] == "active"),
        "skipped_total": len(st["skipped"]),
        "last_run_at": wall_iso(),
    })
    atomic_write_json(os.path.join(STATE, "manifest.json"), manifest)
    log_line = (f"{wall_iso()} bars15m={len(t15)} new_bars={manifest['15m']['added_this_run']} "
                f"processed_to={st['last_processed_idx']} new_seq={n_new} "
                f"resolved={n_res} total_seq={len(st['sequences'])} "
                f"active={manifest['active_count']}\n")
    with open(os.path.join(STATE, "observer.log"), "a", encoding="utf-8") as fh:
        fh.write(log_line)
    if "--quiet" not in sys.argv:
        print(log_line.strip())
    return 0


if __name__ == "__main__":
    if "--run" in sys.argv:
        sys.exit(run_once())
    print("usage: observer.py --run [--quiet]")
    sys.exit(2)
