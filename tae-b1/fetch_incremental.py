"""TAE-B1 数据增量获取：币安 ETHUSDT 永续公开 K 线镜像。

从 robustness 缓存的最后时间点（2026-10-22T02:00Z）取到现在，
与缓存拼接、去重、缺口检查。只写本地 tae-b1/data_cache/。
数据来源：https://www.binance.com/fapi/v1/klines 与 fundingRate（公开接口，无需密钥）。
用法：python3 fetch_incremental.py
"""
import json
import time
import urllib.request
from datetime import datetime, timezone

BASE = "https://www.binance.com/fapi/v1"
SYMBOL = "ETHUSDT"
OUT = "/home/hatch/workspace/goals/100u-200u/files/tae-b1/data_cache"
START_MS = 1760666400000  # 2026-10-22T02:00Z（缓存最后一条 15m/5m/1h 的 open 时间，含该条，便于拼接去重）


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_klines(interval, start_ms, end_ms):
    out = []
    cur = start_ms
    while True:
        url = (f"{BASE}/klines?symbol={SYMBOL}&interval={interval}"
               f"&startTime={cur}&endTime={end_ms}&limit=1500")
        data = get_json(url)
        if not data:
            break
        out.extend(data)
        last_open = data[-1][0]
        if last_open >= end_ms or len(data) < 1500:
            break
        cur = last_open + 1
        time.sleep(0.15)
    return out


def fetch_funding(start_ms, end_ms):
    out = []
    cur = start_ms
    while True:
        url = (f"{BASE}/fundingRate?symbol={SYMBOL}"
               f"&startTime={cur}&endTime={end_ms}&limit=1000")
        data = get_json(url)
        if not data:
            break
        out.extend(data)
        last_t = data[-1]["fundingTime"]
        if last_t >= end_ms or len(data) < 1000:
            break
        cur = last_t + 1
        time.sleep(0.15)
    return out


def main():
    import os
    os.makedirs(OUT, exist_ok=True)
    now_ms = int(time.time() * 1000)
    step = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000}
    report = {}
    for interval in ("5m", "15m", "1h"):
        raw = fetch_klines(interval, START_MS, now_ms)
        # 去掉未收盘的最后一根：收盘时间 > now 的 bar 未收盘
        closed = [k for k in raw if k[6] <= now_ms]
        # 去重 + 排序 + 缺口检查
        seen = {}
        for k in closed:
            seen[k[0]] = k
        ts = sorted(seen)
        gaps = []
        for a, b in zip(ts, ts[1:]):
            if b - a != step[interval]:
                gaps.append((a, b, (b - a) // step[interval]))
        import numpy as np
        arr_t = np.array(ts, dtype=np.int64)
        arr_o = np.array([[float(seen[t][1]), float(seen[t][2]),
                           float(seen[t][3]), float(seen[t][4])] for t in ts])
        np.savez_compressed(f"{OUT}/fresh_{interval}.npz", t=arr_t, ohlc=arr_o)
        report[interval] = {
            "raw": len(raw), "closed": len(closed), "unique": len(ts),
            "first": datetime.fromtimestamp(ts[0] / 1000, timezone.utc).isoformat() if ts else None,
            "last": datetime.fromtimestamp(ts[-1] / 1000, timezone.utc).isoformat() if ts else None,
            "gaps": len(gaps), "gap_examples": gaps[:5],
        }
        print(interval, report[interval])
    fr = fetch_funding(START_MS, now_ms)
    with open(f"{OUT}/fresh_funding.csv", "w") as f:
        f.write("fundingTime,fundingRate\n")
        for r in fr:
            f.write(f"{r['fundingTime']},{r['fundingRate']}\n")
    report["funding"] = {"n": len(fr)}
    print("funding", report["funding"])
    with open(f"{OUT}/fresh_manifest.json", "w") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)
    print("done")


if __name__ == "__main__":
    main()
