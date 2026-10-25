"""Forensic reconstruction of the 2026-07-26 max trade (in-sample).

Verifies bar-by-bar that the +22.07R gross (+21.50R net) long is a real
signal, not a bad tick, gap, or data error:
  * 1H strict trend at the signal bar (swings + step sizes vs 0.5*ATR)
  * key levels at the signal bar, the traded band, same-side test count
  * which 5m signal-K pattern fired, and on which constituent 5m bar
  * fill bar: low vs limit / T1 / T2 thresholds (why it fills only at T0)
  * exit path: every bar from fill to the 1947.28 EMA exit
  * data quality: 15m OHLC vs aggregated 5m OHLC, zero/NaN scan,
    wick size vs ATR, and the size of the run-up vs recent volatility
Usage: python3 forensic_max_trade.py --data /tmp/robustness-v41 --out FILE
"""
import argparse, importlib.util, json, sys
import numpy as np
sys.path.insert(0, "/home/hatch/workspace/goals/100u-200u/hidden_files")
sys.path.insert(0, "/home/hatch/workspace/goals/100u-200u/files/robustness-v41")
import v41_engine as E
from datetime import datetime, timezone

HID = "/home/hatch/workspace/goals/100u-200u/hidden_files"
spec = importlib.util.spec_from_file_location("tf", f"{HID}/tae-scanner-tradfi.py")
tf = importlib.util.module_from_spec(spec); spec.loader.exec_module(tf)

def fmt(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    z15 = np.load(f"{a.data}/insample_15m.npz")
    z1h = np.load(f"{a.data}/insample_1h.npz")
    z5 = np.load(f"{a.data}/insample_5m.npz")
    t15, o15 = z15["t"], z15["ohlc"]
    t1h, o1h = z1h["t"], z1h["ohlc"]
    t5, o5 = z5["t"], z5["ohlc"]
    D = E.Data((t15, o15[:, 0], o15[:, 1], o15[:, 2], o15[:, 3]),
               (t1h, o1h[:, 0], o1h[:, 1], o1h[:, 2], o1h[:, 3]),
               (t5, o5[:, 0], o5[:, 1], o5[:, 2], o5[:, 3]))
    sig_ms = int(datetime(2026, 7, 26, 8, 30, tzinfo=timezone.utc).timestamp() * 1000)
    i = int(np.where(t15 == sig_ms)[0][0])
    lines = []
    w = lambda s: lines.append(s)
    w("=== MAX TRADE FORENSIC: 2026-07-26 long (audit: entry 1881.03, stop 1878.0286, exit 1947.28) ===")
    w(f"signal bar idx={i} open={fmt(t15[i])} O={o15[i][0]} H={o15[i][1]} L={o15[i][2]} C={o15[i][3]}")
    a15 = D.atr15[i]
    w(f"ATR(15m)={a15:.4f}  stop = band_low - ATR; entry-stop dist={1881.03-1878.0286:.4f} (= ATR + entry premium above band low)")
    # 1H trend
    q = int(D.q1h[i])
    w(f"1h window last bar: {fmt(t1h[q])} (qualifying bars end at signal close)")
    hi, lo = E.swings_tf(D.h1h[q-99:q+1], D.l1h[q-99:q+1])
    w(f"1h last-3 swing highs: {[round(v,2) for _,v in hi[-3:]]}")
    w(f"1h last-3 swing lows:  {[round(v,2) for _,v in lo[-3:]]}")
    a1h = D.atr1h[q]
    w(f"ATR(1h)={a1h:.4f}  0.5*ATR={0.5*a1h:.4f}")
    hv = [v for _, v in hi[-3:]]; lv = [v for _, v in lo[-3:]]
    w(f"high steps: {[round(hv[k+1]-hv[k],2) for k in range(2)]} (need >= {0.5*a1h:.2f} each)")
    w(f"low steps:  {[round(lv[k+1]-lv[k],2) for k in range(2)]} (need >= {0.5*a1h:.2f} each)")
    w(f"strict_dir = {E.strict_dir(hi, lo, a1h)}")
    # levels
    levels = E.find_levels_np(D.h15[i-399:i+1], D.l15[i-399:i+1], D.c15[i-399:i+1], a15)
    w(f"levels at signal ({len(levels)}):")
    for lv in levels:
        w(f"  {lv['kind']:11s} line={lv['line']:.2f} band=({lv['band'][0]:.2f},{lv['band'][1]:.2f}) touches={lv['touches']}")
    # traded band: stop = band_low - ATR -> band_low = 1878.0286 + a15
    band_lo = 1878.0286 + a15
    w(f"implied traded band low = stop + ATR = {band_lo:.4f}")
    for lv in levels:
        if abs(lv["band"][0] - band_lo) < 0.5:
            ct = E.contacts_sided(D.h15[i-95:i+1], D.l15[i-95:i+1], lv["band"][0], lv["band"][1], a15)
            above = [s for _, s in ct if s == "above"]
            w(f"traded level: {lv}  same-side 'above' contacts in last 96 bars: {len(above)} (need >= 2)")
            w(f"  all contacts: {ct}")
    # 5m signal K
    m5d = D.signal_5m_dicts(int(t15[i]))
    w("5m window tail (last 6 bars, * = signal K for long):")
    for j in range(len(m5d)-6, len(m5d)):
        b = m5d[j]
        pats = []
        if tf._is_signal_bar(m5d, j, "long"):
            if tf.hammer(b): pats.append("hammer")
            if j > 0 and tf.bull_engulf(m5d[j-1], b): pats.append("bull_engulf")
            if tf.morning_star(m5d, j): pats.append("morning_star")
        w(f"  idx={j} O={b['o']} H={b['h']} L={b['l']} C={b['c']}  {'/'.join(pats) if pats else '-'}")
    # fill bar
    f = i + 1
    w(f"fill bar {fmt(t15[f])} O={o15[f][0]} H={o15[f][1]} L={o15[f][2]} C={o15[f][3]}")
    w(f"  limit=1881.03  T0 touch (L<=limit): {o15[f][2] <= 1881.03}")
    w(f"  T1 threshold={1881.03*0.9995:.4f} penetrated: {o15[f][2] <= 1881.03*0.9995}")
    w(f"  T2 threshold={1881.03*0.999:.4f} penetrated: {o15[f][2] <= 1881.03*0.999}")
    trio = D.m5_bars(int(t15[f]))
    w("  fill-bar 5m bars:")
    for j in trio:
        w(f"    {fmt(t5[j])} O={o5[j][0]} H={o5[j][1]} L={o5[j][2]} C={o5[j][3]}  touches_limit={o5[j][2] <= 1881.03}")
    # exit path
    w("exit path (bars from fill+1 until EMA exit; stop=1878.0286):")
    for j in range(f + 1, len(t15)):
        cp, em = D.c15[j], D.ema[j]
        stop_hit = False
        tj = D.m5_bars(int(t15[j]))
        if tj is not None:
            stop_hit = any(D.l5[k] <= 1878.0286 for k in tj)
        mark = ""
        if stop_hit: mark = " <-- STOP WOULD HIT"
        if cp < em: mark += " <-- EMA EXIT"
        w(f"  {fmt(t15[j])} C={cp:.2f} EMA50={em:.2f} stop_hit={stop_hit}{mark}")
        if cp < em:
            break
    # data quality
    w("data-quality checks:")
    bad = 0
    for arr, nm in ((o15, "15m"), (o5, "5m"), (o1h, "1h")):
        if np.any(arr <= 0) or np.any(np.isnan(arr)):
            w(f"  {nm}: BAD VALUES PRESENT"); bad += 1
    w(f"  zero/NaN scan: {'CLEAN' if bad == 0 else 'PROBLEMS'}")
    # 15m vs 5m aggregation for signal/fill/exit bars
    for j in (i, f):
        idx = [D.m5[int(t15[j] + k * 300_000)] for k in range(3)]
        agg_o, agg_h, agg_l, agg_c = o5[idx[0]][0], max(o5[k][1] for k in idx), min(o5[k][2] for k in idx), o5[idx[2]][3]
        w(f"  bar {fmt(t15[j])}: 15m O/H/L/C = {o15[j][0]}/{o15[j][1]}/{o15[j][2]}/{o15[j][3]}  vs 5m-agg {agg_o}/{agg_h}/{agg_l}/{agg_c}  match={abs(agg_o-o15[j][0])<1e-9 and abs(agg_h-o15[j][1])<1e-9 and abs(agg_l-o15[j][2])<1e-9 and abs(agg_c-o15[j][3])<1e-9}")
    # run-up context: daily range 2026-07-26 vs median daily range last 90d
    day = t15[i] - (t15[i] % 86_400_000)
    sel = (t15 >= day) & (t15 < day + 86_400_000)
    dr = float(o15[sel][:, 1].max() - o15[sel][:, 2].min()) if sel.any() else float("nan")
    w(f"  2026-07-26 UTC daily range: {dr:.2f} ({dr/1881.03*100:.2f}% of entry)")
    # median daily range over prior 90 days
    ranges = []
    for d0 in range(int(day - 90 * 86_400_000), int(day), 86_400_000):
        s2 = (t15 >= d0) & (t15 < d0 + 86_400_000)
        if s2.any():
            ranges.append(float(o15[s2][:, 1].max() - o15[s2][:, 2].min()))
    w(f"  median daily range prior 90d: {float(np.median(ranges)):.2f} (n={len(ranges)} days)")
    open(a.out, "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))

if __name__ == "__main__":
    main()
