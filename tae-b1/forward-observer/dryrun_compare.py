"""干跑对照：观察系统 vs 普查口径（只验证检测器，不作回测、不评优）。

对照内容：
1. Bar 一致性：观察系统拉取的镜像 15m K 线，与普查拼接缓存
   （data_cache/stitched_15m.npz）在重叠时间戳上逐根比对 o/h/l/c。
   若镜像数据与普查数据源不一致，检测器对照无意义，必须先报出。
2. 事件对照：取 b0 落在最近 30 天且在普查覆盖内（<= 普查最后收盘）
   的序列，按 (b0_time_utc, dir) 匹配，比较带上下沿（容差 1e-6）、
   结局（双方都已确定时）、E 信号存在性（普查 e_time_utc 非空）。
   普查未决而观察系统已结算的，单列为“观察系统后结算”，不算错配。
3. 数量级：双方在对照窗口内的序列数、结局分布。

通过标准（任务要求：数量级与关键字段一致）：
- Bar 错配 = 0；
- 匹配率 100%（双方窗口内序列一一对应）；
- 已确定结局一致率 100%；带一致率 100%；E 信号一致率 100%。
任一项不通过即判 FAIL 并列出全部错配行。
只读普查文件，不写 B1、不写扫描器、不写执行器。
输出：stdout 摘要 + dryrun_report.md（由调用方保存）。
"""

import csv
import sys
from collections import Counter

import numpy as np

FO = "/home/hatch/workspace/goals/100u-200u/files/tae-b1/forward-observer"
B1 = "/home/hatch/workspace/goals/100u-200u/files/tae-b1"


def main():
    obs_t, obs_o = None, None
    d = np.load(f"{FO}/state/klines_15m.npz")
    obs_t, obs_o = d["t"], d["ohlc"]
    c = np.load(f"{B1}/data_cache/stitched_15m.npz")
    cen_t, cen_o = c["t"], c["ohlc"]
    cen_map = {int(t): row for t, row in zip(cen_t, cen_o)}
    overlap = [int(t) for t in obs_t if int(t) in cen_map]
    bar_mismatch = 0
    bar_mismatch_ex = []
    obs_idx = {int(t): i for i, t in enumerate(obs_t)}
    for t in overlap:
        i = obs_idx[t]
        a, b = obs_o[i], cen_map[t]
        if not np.array_equal(a, b):
            bar_mismatch += 1
            if len(bar_mismatch_ex) < 5:
                bar_mismatch_ex.append((t, [float(x) for x in a], [float(x) for x in b]))

    # 事件对照
    obs_rows = list(csv.DictReader(open(f"{FO}/ledger.csv", encoding="utf-8")))
    cen_rows = [r for r in csv.DictReader(open(f"{B1}/structure-events/events_census.csv",
                                               encoding="utf-8"))
                if r["seq_id"].startswith("S")]
    cen_last_close_ms = int(cen_t[-1]) + 900_000
    # 对照窗口：b0 在最近 30 天内且在普查覆盖内
    from datetime import datetime, timezone
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    win_start_ms = now_ms - 30 * 86_400_000

    def to_ms(s):
        return int(datetime.strptime(s, "%Y-%m-%dT%H:%M").replace(
            tzinfo=timezone.utc).timestamp() * 1000)

    obs_w = [r for r in obs_rows if to_ms(r["b0_time_utc"]) >= win_start_ms]
    cen_w = [r for r in cen_rows
             if to_ms(r["b0_time_utc"]) >= win_start_ms
             and to_ms(r["b0_time_utc"]) <= cen_last_close_ms]
    obs_map = {(r["b0_time_utc"], r["dir"]): r for r in obs_w}
    cen_map2 = {(r["b0_time_utc"], r["dir"]): r for r in cen_w}
    only_obs = sorted(set(obs_map) - set(cen_map2))
    only_cen = sorted(set(cen_map2) - set(obs_map))
    band_mismatch, outcome_mismatch, e_mismatch = [], [], []
    later_resolved = []
    for k in sorted(set(obs_map) & set(cen_map2)):
        o, c = obs_map[k], cen_map2[k]
        if abs(float(o["band_lo"]) - float(c["band_lo"])) > 1e-6 or \
           abs(float(o["band_hi"]) - float(c["band_hi"])) > 1e-6:
            band_mismatch.append((k, o["band_lo"], c["band_lo"], o["band_hi"], c["band_hi"]))
        co = c["outcome"]
        oo = o["outcome"]
        if co in ("reclaimed", "voided", "expired") and oo in ("reclaimed", "voided", "expired"):
            if co != oo:
                outcome_mismatch.append((k, oo, co))
        elif co == "unresolved" and oo in ("reclaimed", "voided", "expired"):
            later_resolved.append((k, oo))
        elif co in ("reclaimed", "voided", "expired") and oo == "active":
            outcome_mismatch.append((k, oo, co))
        ce = 1 if c["e_time_utc"] else 0
        oe = int(o["e_signal_any"]) if o["e_signal_any"] != "" else -1
        if oo == "reclaimed" and oe != -1 and ce != oe:
            e_mismatch.append((k, oe, ce))
    print(f"bars: observer={len(obs_t)} census={len(cen_t)} overlap={len(overlap)} "
          f"mismatch={bar_mismatch}")
    for ex in bar_mismatch_ex:
        print("  bar mismatch ex:", ex)
    print(f"window: last30d from {win_start_ms}, census_last_close={cen_last_close_ms}")
    print(f"sequences in window: observer={len(obs_w)} census={len(cen_w)}")
    print(f"  only_observer={len(only_obs)} only_census={len(only_cen)}")
    for k in only_obs:
        print("  only_observer:", k)
    for k in only_cen:
        print("  only_census:", k)
    print(f"matched={len(set(obs_map) & set(cen_map2))} "
          f"band_mismatch={len(band_mismatch)} outcome_mismatch={len(outcome_mismatch)} "
          f"e_mismatch={len(e_mismatch)} later_resolved={len(later_resolved)}")
    for m in band_mismatch:
        print("  band mismatch:", m)
    for m in outcome_mismatch:
        print("  outcome mismatch:", m)
    for m in e_mismatch:
        print("  e mismatch:", m)
    for m in later_resolved:
        print("  later_resolved:", m)
    print("outcome dist observer:", dict(Counter(r["outcome"] for r in obs_w)))
    print("outcome dist census:", dict(Counter(r["outcome"] for r in cen_w)))
    ok = (bar_mismatch == 0 and not only_obs and not only_cen
          and not band_mismatch and not outcome_mismatch and not e_mismatch)
    print("VERDICT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
