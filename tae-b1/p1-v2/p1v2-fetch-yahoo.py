#!/usr/bin/env python3
"""P1-v2 探索回测数据拉取：Yahoo chart API 日线 adjclose（总收益口径）。

只拉价格数据，不算任何策略收益。输出 p1v2-yahoo-data.json：
每标的 {dates[], adjclose[], first, last, n, missing_adjclose}。
缺口不插值；缺失 adjclose 的日期直接丢弃（报告中披露缺失占比）。
"""
import json, time, urllib.request, urllib.error
from datetime import datetime, timezone

TICKERS = ["AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","SNDK","MU",
            "AVGO","PLTR","AMD","NFLX","SPY"]
OUT = "/home/hatch/workspace/goals/100u-200u/files/tae-b1/p1-v2/p1v2-yahoo-data.json"
P1 = 1262304000  # 2010-01-01 UTC
P2 = int(time.time())

def fetch(tk):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{tk}"
           f"?period1={P1}&period2={P2}&interval=1d&events=div,split")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                time.sleep(5 * (attempt + 1)); continue
            raise
        except urllib.error.URLError:
            if attempt < 2:
                time.sleep(5 * (attempt + 1)); continue
            raise

out = {"meta": {"fetched_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                 "source": "Yahoo chart API v8, interval=1d, adjclose",
                 "note": "adjclose 为分红/拆分调整后总收益口径；缺失日丢弃不插值。"},
       "tickers": {}}
for tk in TICKERS:
    try:
        d = fetch(tk)
        res = d["chart"]["result"][0]
        ts = res["timestamp"]
        adj = res["indicators"]["adjclose"][0]["adjclose"]
        dates, vals, miss = [], [], 0
        for t, a in zip(ts, adj):
            if a is None:
                miss += 1; continue
            dates.append(datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d"))
            vals.append(round(float(a), 4))
        out["tickers"][tk] = {"first": dates[0] if dates else None, "last": dates[-1] if dates else None,
                              "n": len(vals), "missing_adjclose": miss,
                              "dates": dates, "adjclose": vals}
        print(f"{tk}: {out['tickers'][tk]['first']} -> {out['tickers'][tk]['last']} n={len(vals)} miss={miss}", flush=True)
    except Exception as e:
        out["tickers"][tk] = {"error": str(e)}
        print(f"{tk}: ERROR {e}", flush=True)
    time.sleep(0.5)
json.dump(out, open(OUT, "w"), ensure_ascii=False)
print("saved", OUT)
