"""TAE-B1 pass 1：逐根 15m 重算 find_levels + 1H 趋势 + 突破候选事件。

输出 candidates.jsonl：每行 {j, dir, blo, bhi}，其中 j 为 15m 下标，
band 为该根 trailing 400 根窗口算出的 find_levels 带；
候选条件（多头）：kind=resistance 且 close[j-1] <= bhi < close[j]（穿越），
且 1H 严版大趋势为 long；空头镜像。
趋势判定只用 1H 收盘 ≤ 该 15m 收盘的 bar（指针法，无未来函数）。
本脚本只检测候选，不做序列状态机（冷却/重叠/持仓互斥由 pass 2 处理）。
用法：python3 levels_pass.py  （约 10-40 分钟，后台跑）
"""
import bisect
import json
import sys
import time

import numpy as np

sys.path.insert(0, "/home/hatch/workspace/goals/100u-200u/files/tae-b1")
sys.path.insert(0, "/home/hatch/workspace/goals/100u-200u/hidden_files")
from key_levels import find_levels  # noqa: E402
from b1_lib import (atr_series, swings_tie)  # noqa: E402

B1 = "/home/hatch/workspace/goals/100u-200u/files/tae-b1/data_cache"


def main():
    d15 = np.load(f"{B1}/stitched_15m.npz")
    d1h = np.load(f"{B1}/stitched_1h.npz")
    t15, o15 = d15["t"], d15["ohlc"]
    t1h, o1h = d1h["t"], d1h["ohlc"]
    c15 = o15[:, 3]
    atr15 = atr_series(o15)
    # 1h TR/ATR
    tr1 = np.full(len(o1h), np.nan)
    for i in range(1, len(o1h)):
        tr1[i] = max(o1h[i][1] - o1h[i][2], abs(o1h[i][1] - o1h[i - 1][3]),
                     abs(o1h[i][2] - o1h[i - 1][3]))
    atr1 = np.full(len(o1h), np.nan)
    for i in range(13, len(o1h)):
        atr1[i] = float(np.nanmean(tr1[i - 13:i + 1]))
    # 1h 摆动点（tie 语义，全序列一次算出；指针处只取下标 <= p-3 的点）
    hi_all, lo_all = swings_tie(o1h)
    hi_idx = [i for i, _ in hi_all]
    hi_val = [v for _, v in hi_all]
    lo_idx = [i for i, _ in lo_all]
    lo_val = [v for _, v in lo_all]
    t1h_close = t1h + 3_600_000
    t15_close = t15 + 900_000

    def trend_at(j):
        p = int(np.searchsorted(t1h_close, t15_close[j], side="right"))
        if p < 60 or np.isnan(atr1[p - 1]):
            return None
        a = atr1[p - 1]
        thr = 0.5 * a
        hi = [v for idx, v in zip(hi_idx, hi_val) if idx <= p - 3][-3:]
        lo = [v for idx, v in zip(lo_idx, lo_val) if idx <= p - 3][-3:]
        if len(hi) < 3 or len(lo) < 3:
            return None
        hs = [hi[i + 1] - hi[i] for i in range(2)]
        ls = [lo[i + 1] - lo[i] for i in range(2)]
        if all(x >= thr for x in hs) and all(x >= thr for x in ls):
            return "long"
        if all(x <= -thr for x in hs) and all(x <= -thr for x in ls):
            return "short"
        return None

    n = len(t15)
    # 断点续跑：已有 candidates 文件时从最大已完成 bar 的下一根继续
    import os
    cand_path = f"{B1}/candidates.jsonl"
    start_j, n_cand = 399, 0
    if os.path.exists(cand_path) and os.path.getsize(cand_path) > 0:
        good = []
        with open(cand_path) as fh:
            for line in fh:
                try:
                    c = json.loads(line)
                    good.append(line)
                    start_j = max(start_j, c["j"] + 1)
                    n_cand += 1
                except Exception:
                    pass  # 撕裂行丢弃
        with open(cand_path, "w") as fh:
            fh.writelines(good)
        print(f"resume from bar {start_j}, existing candidates={n_cand}", flush=True)
    out = open(cand_path, "a", buffering=1)
    t0 = time.time()
    for j in range(start_j, n):
        if j % 20000 == 0:
            print(f"bar {j}/{n} cand={n_cand} elapsed={time.time()-t0:.0f}s", flush=True)
        win = [{"o": float(r[0]), "h": float(r[1]), "l": float(r[2]), "c": float(r[3])}
               for r in o15[j - 399:j + 1]]
        lv = find_levels(win, float(atr15[j]))
        if not lv:
            continue
        tr = trend_at(j)
        if tr is None:
            continue
        cj, pj = float(c15[j]), float(c15[j - 1])
        if tr == "long":
            for L in lv:
                if L["kind"] != "resistance":
                    continue
                blo, bhi = L["band"]
                if pj <= bhi and cj > bhi:
                    out.write(json.dumps({"j": j, "dir": "long",
                                          "blo": blo, "bhi": bhi}) + "\n")
                    n_cand += 1
        else:
            for L in lv:
                if L["kind"] != "support":
                    continue
                blo, bhi = L["band"]
                if pj >= blo and cj < blo:
                    out.write(json.dumps({"j": j, "dir": "short",
                                          "blo": blo, "bhi": bhi}) + "\n")
                    n_cand += 1
    out.close()
    print(f"DONE bars={n} candidates={n_cand} elapsed={time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
