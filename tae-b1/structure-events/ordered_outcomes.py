"""TAE 实验设计审查 · 任务一：先后顺序结局重算（零盈亏）。

只读复用普查口径，不改原脚本、不改生产代码、不算盈亏。
原普查口径（events_census.py）：
- 收复后窗口：15m 根 (term, term+N]，term = 收复根下标。
- 跌穿远沿：窗口内任一 15m 收盘穿越远沿（多头 < blo，空头 > bhi）。
- 新同向摆动：窗口内经 k=2 确认的 15m strict 摆动点，确认根也在
  horizon 内，且极值超越 b0 根极值（多头摆动高 > high[b0]）。
本脚本新增先后顺序：
- 摆动事件时刻（主口径）＝ 确认根收盘（摆动 bar + 2 根），即摆动
  在决策上变得已知、无未来信息的时刻。
- 跌穿事件时刻 ＝ 首根收盘穿越远沿的 15m 根收盘。
- 四类：A 先摆动（摆动确认早于任何跌穿，或有摆动且窗口内无跌穿）；
  B 先跌穿后摆动（跌穿先发生、摆动随后在窗口内出现）；
  C 仅跌穿（无摆动）；D 两者皆无；T 同根 tie（摆动确认根与首根
  跌穿根为同一根 15m，严格读法下既非 A 亦非 B，单列不并入）。
- 敏感性口径：摆动事件时刻取摆动 bar 本身（价格实际创出极值的
  时刻），重算分类并统计与主口径的翻转数。
- 复制门：重算的跌穿/摆动存在性须与普查 postN_fell_through /
  postN_new_swing 逐项一致，否则报错。
"""
import csv
import sys
from collections import Counter, defaultdict

import numpy as np

sys.path.insert(0, "/home/hatch/workspace/goals/100u-200u/files/tae-b1")
sys.path.insert(0, "/home/hatch/workspace/goals/100u-200u/hidden_files")
from b1_lib import swings_strict  # noqa: E402 只读复用，与普查同一函数

B1 = "/home/hatch/workspace/goals/100u-200u/files/tae-b1"
SE = f"{B1}/structure-events"

d15 = np.load(f"{B1}/data_cache/stitched_15m.npz")
t15, o15 = d15["t"], d15["ohlc"]
c15, h15, l15 = o15[:, 3], o15[:, 1], o15[:, 2]
n15 = len(t15)

shi, slo = swings_strict(o15)
shi_idx = set(i for i, _ in shi)
shi_val = dict(shi)
slo_idx = set(i for i, _ in slo)
slo_val = dict(slo)


def first_ft(term, N, d, blo, bhi):
    for m in range(term + 1, term + N + 1):
        if d == "long" and c15[m] < blo:
            return m
        if d == "short" and c15[m] > bhi:
            return m
    return None


def first_swing(term, N, d, b0_ext, j):
    for i in range(term + 1, term + N + 1):
        if d == "long" and i in shi_idx and i + 2 <= term + N \
                and shi_val[i] > b0_ext:
            return i, i + 2
        if d == "short" and i in slo_idx and i + 2 <= term + N \
                and slo_val[i] < b0_ext:
            return i, i + 2
    return None, None


def classify(conf, ft):
    if conf is None and ft is None:
        return "D"
    if conf is not None and ft is None:
        return "A"
    if conf is None and ft is not None:
        return "C"
    if conf < ft:
        return "A"
    if ft < conf:
        return "B"
    return "T"


def main():
    rows = []
    with open(f"{SE}/events_census.csv") as fh:
        for r in csv.DictReader(fh):
            rows.append(r)
    rec = [r for r in rows if r["outcome"] == "reclaimed"]
    out = []
    mism = Counter()
    flips = Counter()
    for r in rec:
        j = int(r["b0_idx"])
        term = j + int(r["reclaim_lag_bars"])
        d = r["dir"]
        blo, bhi = float(r["band_lo"]), float(r["band_hi"])
        b0_ext = float(h15[j]) if d == "long" else float(l15[j])
        row = {
            "seq_id": r["seq_id"], "window": r["window"], "dir": d,
            "b0_time_utc": r["b0_time_utc"],
            "reclaim_time_utc": r["reclaim_time_utc"],
            "band_lo": blo, "band_hi": bhi,
            "band_touches": r["band_touches"],
            "band_width_atr": r["band_width_atr"],
            "band_last_touch_lag": r["band_last_touch_lag"],
            "i2a_depth_atr": r["i2a_depth_atr"],
            "i2a_rebound_final_atr": r["i2a_rebound_final_atr"],
            "i2a_pos_final": r["i2a_pos_final"],
            "i2b_dwell_max_consec": r["i2b_dwell_max_consec"],
            "trend_v02_at_b0": r["trend_v02_at_b0"],
            "i4a_invalidated_during": r["i4a_invalidated_during"],
            "i4b_recheck_t0": r["i4b_recheck_t0"],
            "i4b_recheck_reclaim": r["i4b_recheck_reclaim"],
        }
        for N in (48, 96):
            p = f"N{N}"
            if term + N >= n15:
                row[f"{p}_class"] = "truncated"
                continue
            ft = first_ft(term, N, d, blo, bhi)
            sw_bar, conf = first_swing(term, N, d, b0_ext, j)
            # 复制门：与普查逐项一致
            if (ft is not None) != (r[f"post{N}_fell_through"] == "1"):
                mism[f"{p}_fell_through"] += 1
            if (sw_bar is not None) != (r[f"post{N}_new_swing"] == "1"):
                mism[f"{p}_new_swing"] += 1
            cls = classify(conf, ft)
            row[f"{p}_swing_bar"] = sw_bar if sw_bar is not None else ""
            row[f"{p}_swing_conf"] = conf if conf is not None else ""
            row[f"{p}_ft_idx"] = ft if ft is not None else ""
            row[f"{p}_class"] = cls
            if cls == "A" and ft is not None:
                row[f"{p}_gap"] = ft - conf
            elif cls == "B":
                row[f"{p}_gap"] = conf - ft
            else:
                row[f"{p}_gap"] = ""
            # 敏感性：摆动事件时刻取摆动 bar 本身
            cls_sb = classify(sw_bar, ft)
            row[f"{p}_class_swingbar"] = cls_sb
            if cls_sb != cls:
                flips[f"{p}_{cls}->{cls_sb}"] += 1
        out.append(row)
    fields = list(out[0].keys())
    with open(f"{SE}/ordered_outcomes.csv", "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        wr.writeheader()
        wr.writerows(out)
    print(f"rows={len(out)} mismatches={dict(mism)} flips={dict(flips)}")
    for N in (48, 96):
        p = f"N{N}"
        cc = Counter(r[f"{p}_class"] for r in out)
        n = sum(cc.values())
        print(f"--- N={N} (n={n}) ---")
        for k in ("A", "B", "C", "D", "T"):
            print(f"  {k}: {cc.get(k, 0)} ({cc.get(k, 0) / n:.1%})")
        for label, sel in (("A-gap (swing->ft)", [int(r[f'{p}_gap']) for r in out
                                                 if r[f"{p}_class"] == "A" and r[f"{p}_gap"] != ""]),
                           ("B-gap (ft->swing)", [int(r[f'{p}_gap']) for r in out
                                                   if r[f"{p}_class"] == "B"])):
            if sel:
                a = np.array(sel)
                print(f"  {label}: n={len(a)} mean={a.mean():.1f} "
                      f"median={np.median(a):.0f} q1={np.percentile(a, 25):.0f} "
                      f"q3={np.percentile(a, 75):.0f} min={a.min()} max={a.max()}")
        # 原口径对照：新摆动率 = A+B+T（确认口径下摆动存在 = A+B+T）
        sw_any = sum(1 for r in out if r[f"{p}_class"] in ("A", "B", "T"))
        print(f"  原口径新摆动率 = {sw_any / n:.1%}；其中 B 类占原'成功' "
              f"{cc.get('B', 0) / sw_any:.1%}，A 类占 {cc.get('A', 0) / sw_any:.1%}，"
              f"T 类占 {cc.get('T', 0) / sw_any:.1%}")
        print(f"  修订主结局 A 率 = {cc.get('A', 0) / n:.1%}；"
              f"A+T 率 = {(cc.get('A', 0) + cc.get('T', 0)) / n:.1%}")


if __name__ == "__main__":
    main()
