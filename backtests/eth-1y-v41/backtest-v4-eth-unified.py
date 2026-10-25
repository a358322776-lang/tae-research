"""v4.0 ETH 回测（2026-10-22 用户要求）：币安 ETHUSDT 永续 12 个月逐 15m 回放。
口径与现行机一致：决策点=15m 收盘；定位窗 400 根 15m；T=market_structure(v3.1+1H 共振)；
入场=key_signals.evaluate（回踩二测/突破阶梯）；止损=带沿外 1×ATR；
出场=初始止损（区间内 5m 逐根）或 15m 收盘越 EMA50 先到者（track_v3 同语义，入场根不判）；
同向平仓冷却 2h；隐含杠杆 >20x 的信号放弃（同 trade_plan）；单仓回放（现行机同向拦截，
反向并发未模拟——已知简化）。R 口径与台账一致（不含手续费）。"""
import importlib.util, json, sys, time, urllib.request
from datetime import datetime, timezone

HID = "/home/hatch/workspace/goals/100u-200u/hidden_files"
sys.path.insert(0, HID)
from key_levels import find_levels
from key_signals import evaluate

spec = importlib.util.spec_from_file_location("tf", f"{HID}/tae-scanner-tradfi.py")
tf = importlib.util.module_from_spec(spec); spec.loader.exec_module(tf)

STEP = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000}

def fetch_all(sym, iv, start_ms, end_ms):
    out, cur = {}, start_ms
    while cur < end_ms:
        url = (f"https://www.binance.com/fapi/v1/klines?symbol={sym}&interval={iv}"
               f"&limit=1500&startTime={cur}&endTime={end_ms}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = json.load(urllib.request.urlopen(req, timeout=30))
        if not raw:
            break
        for r in raw:
            out[r[0]] = {"t": r[0], "o": float(r[1]), "h": float(r[2]),
                         "l": float(r[3]), "c": float(r[4]), "ts": r[0]}
        cur = raw[-1][0] + STEP[iv]
        time.sleep(0.05)
    return [out[k] for k in sorted(out)]

END = int(datetime(2026, 10, 22, 2, 0, tzinfo=timezone.utc).timestamp() * 1000)   # 10:00 CST 前
START = END - 370 * 24 * 3600 * 1000
print("拉取数据…", flush=True)
c15 = fetch_all("ETHUSDT", "15m", START, END)
c1h = fetch_all("ETHUSDT", "1h", START, END)
c5 = fetch_all("ETHUSDT", "5m", START, END)
print(f"15m={len(c15)} 1h={len(c1h)} 5m={len(c5)}", flush=True)
b5 = {b["t"]: b for b in c5}

# EMA50(15m) 全程因果计算（与扫描器 ema50_series 同定义）
closes = [c["c"] for c in c15]
ema = {}
e = sum(closes[:50]) / 50
for i in range(49, len(c15)):
    if i > 49:
        e = closes[i] * 2 / 51 + e * (1 - 2 / 51)
    ema[i] = e


def _strict_dir(candles, a, k=2):
    """用户 2026-10-22 严版趋势：最后 3 个摆动高逐级抬高、每级台阶 ≥0.5×ATR，
    最后 3 个摆动低同样，才算多头（空头镜像）；缺一即无趋势。"""
    hi, lo = tf.swings(candles, k=k)
    if len(hi) < 3 or len(lo) < 3:
        return None
    thr = 0.5 * a
    hv = [v for _, v in hi][-3:]; lv = [v for _, v in lo][-3:]
    hs = [hv[i + 1] - hv[i] for i in range(2)]; ls = [lv[i + 1] - lv[i] for i in range(2)]
    if all(x >= thr for x in hs) and all(x >= thr for x in ls):
        return "long"
    if all(x <= -thr for x in hs) and all(x <= -thr for x in ls):
        return "short"
    return None

def market_structure_strict(c15, c1h):
    a15, a1h = tf.atr(c15), tf.atr(c1h)
    d15 = _strict_dir(c15[-96:], a15)
    d1h = _strict_dir(c1h, a1h)
    return (d15 if d15 and d15 == d1h else None), None, None, a15


def _contacts_sided(c15, level, a):
    """带侧别的到达计数：每次到达记录来向（above=从带上方来）。位翻转后，
    来向自动只剩新角色一侧——回踩与阶梯共用同一计数（用户：两者其实是一个）。"""
    from key_signals import DEPART
    blo, bhi = level["band"]
    out, in_c, away, prev_above = [], False, True, True
    for i, cd in enumerate(c15):
        hit = cd["l"] <= bhi and cd["h"] >= blo
        if hit and not in_c and away:
            out.append((i, "above" if prev_above else "below"))
            in_c, away = True, False
        elif not hit:
            in_c = False
            if cd["l"] >= bhi + DEPART * a:
                away, prev_above = True, True
            elif cd["h"] <= blo - DEPART * a:
                away, prev_above = True, False
    return out

def evaluate_unified(c15, c5, levels, a, big_dir, is_signal_bar):
    """统一入场（用户 2026-10-22：回踩单和阶梯单其实是一个）：
    顺大趋势（1H 严版）方向，价格回到关键带、第 ≥2 次同侧测试 + 信号 K。
    位是老支撑还是突破翻转来的，不区别——翻转只改变测试的来向。"""
    from key_signals import _touching_now, _e_signal, TEST_WINDOW
    if big_dir not in ("long", "short"):
        return None
    price = c15[-1]["c"]
    for lv in levels:
        if big_dir == "long":
            if price < lv["band"][0]:
                continue
            ct = [i for i, sd in _contacts_sided(c15[-TEST_WINDOW:], lv, a) if sd == "above"]
            if len(ct) >= 2 and _touching_now(c15, lv) and _e_signal(c5, "long", is_signal_bar):
                return {"kind": "unified", "direction": "long", "level": lv,
                        "entry_ref": price, "stop": lv["band"][0] - a, "tests": len(ct)}
        else:
            if price > lv["band"][1]:
                continue
            ct = [i for i, sd in _contacts_sided(c15[-TEST_WINDOW:], lv, a) if sd == "below"]
            if len(ct) >= 2 and _touching_now(c15, lv) and _e_signal(c5, "short", is_signal_bar):
                return {"kind": "unified", "direction": "short", "level": lv,
                        "entry_ref": price, "stop": lv["band"][1] + a, "tests": len(ct)}
    return None

WARM = 420           # 15m 根数热身（≥400 定位窗 + EMA 播种余量）
COOL = 8             # 2h = 8 根 15m
trades, pos = [], None
cool_until = {"long": -1, "short": -1}
skipped_lev = 0

for i in range(WARM, len(c15)):
    bar = c15[i]
    # —— 出场：逐区间推进（入场根不判）——
    if pos is not None and i > pos["i"]:
        trio = [b5.get(bar["t"] + k * 300_000) for k in range(3)]
        res = None
        if all(trio):
            for b in trio:
                if (pos["dir"] == "long" and b["l"] <= pos["sl"]) or \
                   (pos["dir"] == "short" and b["h"] >= pos["sl"]):
                    res = ("stop", pos["sl"]); break
        if res is None and i in ema:
            cp, em = bar["c"], ema[i]
            if (pos["dir"] == "long" and cp < em) or (pos["dir"] == "short" and cp > em):
                res = ("ema50_close", cp)
        if res:
            reason, px = res
            rr = -1.0 if reason == "stop" else round(
                ((px - pos["entry"]) if pos["dir"] == "long" else (pos["entry"] - px)) / pos["risk"], 2)
            trades.append({**pos, "exit_i": i, "exit_px": round(px, 2), "reason": reason,
                           "r": rr, "hold_h": round((i - pos["i"]) * 0.25, 1),
                           "open_t": datetime.fromtimestamp(pos["t"] / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")})
            cool_until[pos["dir"]] = i + COOL
            pos = None
    # —— 入场 ——
    if pos is None:
        w15 = c15[i - 399: i + 1]
        w1h = [h for h in c1h if h["t"] + 3_600_000 <= bar["t"] + 900_000][-100:]
        w5 = [b for b in c5 if bar["t"] - 500 * 60_000 < b["t"] <= bar["t"] + 600_000][-100:]
        if len(w1h) < 60 or len(w5) < 30:
            continue
        a = tf.atr(w15)
        big_dir = _strict_dir(w1h, tf.atr(w1h))
        levels = find_levels(w15, a)
        sig = evaluate_unified(w15, w5, levels, a, big_dir, tf._is_signal_bar)
        if sig:
            d = sig["direction"]
            if i <= cool_until[d]:
                continue
            entry, sl = bar["c"], sig["stop"]
            risk = abs(entry - sl)
            if risk <= 0:
                continue
            if 0.02 / (risk / entry) > 20:
                skipped_lev += 1
                continue
            pos = {"i": i, "t": bar["t"], "dir": d, "entry": entry, "sl": sl,
                   "risk": risk, "kind": sig["kind"],
                   "level": sig["level"]["line"]}

# —— 统计 ——
def stats(ts):
    if not ts:
        return {"n": 0}
    rs = [t["r"] for t in ts]
    wins = [r for r in rs if r > 0]
    eq, peak, dd = 0.0, 0.0, 0.0
    for r in rs:
        eq += r; peak = max(peak, eq); dd = min(dd, eq - peak)
    return {"n": len(ts), "win%": round(100 * len(wins) / len(ts), 1),
            "avgR": round(sum(rs) / len(rs), 3), "totalR": round(sum(rs), 2),
            "avgWin": round(sum(wins) / len(wins), 2) if wins else 0,
            "avgLoss": round(sum(r for r in rs if r <= 0) / max(1, len(rs) - len(wins)), 2),
            "maxDD_R": round(dd, 2), "tail>3R": sum(1 for r in rs if r > 3),
            "best": max(rs), "worst": min(rs),
            "avgHoldH": round(sum(t["hold_h"] for t in ts) / len(ts), 1)}

out = {"all": stats(trades),
       "pullback": stats([t for t in trades if t["kind"] == "pullback"]),
       "ladder": stats([t for t in trades if t["kind"] == "ladder"]),
       "long": stats([t for t in trades if t["dir"] == "long"]),
       "short": stats([t for t in trades if t["dir"] == "short"]),
       "stop_exits": sum(1 for t in trades if t["reason"] == "stop"),
       "ema_exits": sum(1 for t in trades if t["reason"] == "ema50_close"),
       "skipped_lev20x": skipped_lev,
       "open_at_end": None if pos is None else pos["dir"]}
json.dump({"summary": out, "trades": trades}, open("/tmp/bt-v4-eth-unified.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
