# P1 数据审计脚本（仅覆盖/缺口/字段，不算信号、不算收益、不回测）。
# Yahoo: query1 chart API, period1/period2 分段拉取，interval=1d。
# 币安镜像: www.binance.com/fapi/v1/klines, interval=1d, startTime 分页。
# 输出仅为覆盖统计摘要（起止、根数、缺口、字段、空值），不保存逐根 OHLCV。
import json, time, urllib.request, datetime

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}

def get_json(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def audit_yahoo(sym):
    # 分 5 年一段拉取，避免 range=max 的月度密度问题
    t_end = int(time.time())
    t_start = 631152000  # 1990-01-01 UTC
    bars = {}  # ts -> (close, adjclose, volume)
    chunk = 5 * 365 * 86400
    t0 = t_start
    while t0 < t_end:
        t1 = min(t0 + chunk, t_end)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1={t0}&period2={t1}&interval=1d"
        d = get_json(url)
        res = (d.get("chart", {}).get("result") or [None])[0]
        if res:
            ts = res.get("timestamp") or []
            q = (res.get("indicators", {}).get("quote") or [{}])[0]
            adj = (res.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose") or []
            for i, t in enumerate(ts):
                c = q.get("close", [None] * len(ts))[i] if i < len(q.get("close", [])) else None
                a = adj[i] if i < len(adj) else None
                v = q.get("volume", [None] * len(ts))[i] if i < len(q.get("volume", [])) else None
                bars[t] = (c, a, v)
        t0 = t1
    ts_sorted = sorted(bars)
    gaps = []  # 相邻 bar 间隔 > 4 天（周末=3天，节日周末=4天）
    for a, b in zip(ts_sorted, ts_sorted[1:]):
        gap_days = (b - a) / 86400.0
        if gap_days > 4.0:
            gaps.append({"from": datetime.datetime.utcfromtimestamp(a).strftime("%Y-%m-%d"),
                         "to": datetime.datetime.utcfromtimestamp(b).strftime("%Y-%m-%d"),
                         "gap_days": round(gap_days, 1)})
    null_close = sum(1 for t in ts_sorted if bars[t][0] is None)
    null_adj = sum(1 for t in ts_sorted if bars[t][1] is None)
    zero_vol = sum(1 for t in ts_sorted if bars[t][2] == 0)
    return {
        "source": "Yahoo chart API (period1/period2 分段, interval=1d)",
        "symbol": sym,
        "first": datetime.datetime.utcfromtimestamp(ts_sorted[0]).strftime("%Y-%m-%d") if ts_sorted else None,
        "last": datetime.datetime.utcfromtimestamp(ts_sorted[-1]).strftime("%Y-%m-%d") if ts_sorted else None,
        "bars": len(ts_sorted),
        "fields": ["open", "high", "low", "close", "volume", "adjclose"],
        "adjclose_present": all(bars[t][1] is not None for t in ts_sorted),
        "null_close": null_close, "null_adjclose": null_adj,
        "zero_volume_bars": zero_vol,
        "gaps_over_4d": len(gaps), "gap_list": gaps[:20],
    }

def audit_binance(sym):
    url0 = "https://www.binance.com/fapi/v1/klines"
    bars = []
    start = 0
    while True:
        url = f"{url0}?symbol={sym}&interval=1d&limit=1500&startTime={start}"
        d = get_json(url)
        if not d:
            break
        bars.extend(d)
        last_close = d[-1][6]
        if len(d) < 1500:
            break
        start = last_close + 1
        if len(bars) > 20000:
            break
    dates = [datetime.datetime.utcfromtimestamp(b[0] / 1000).strftime("%Y-%m-%d") for b in bars]
    dset = set(dates)
    # 24/7 交易：每个自然日都应有一根
    first = datetime.date.fromisoformat(dates[0]); last = datetime.date.fromisoformat(dates[-1])
    missing = []
    cur = first
    while cur <= last:
        if cur.isoformat() not in dset:
            missing.append(cur.isoformat())
        cur += datetime.timedelta(days=1)
    dupes = len(dates) - len(dset)
    return {
        "source": "币安镜像 fapi/v1/klines (interval=1d, startTime 分页)",
        "symbol": sym,
        "first": dates[0] if dates else None,
        "last": dates[-1] if dates else None,
        "bars": len(bars),
        "fields": ["open_time", "open", "high", "low", "close", "volume", "close_time"],
        "missing_calendar_days": len(missing), "missing_list": missing[:20],
        "duplicate_days": dupes,
    }

out = {}
for s in ["SPY", "QQQ", "TLT", "GLD"]:
    try:
        out[s] = audit_yahoo(s)
        print(s, "OK", out[s]["first"], "->", out[s]["last"], out[s]["bars"], "bars, gaps>4d:", out[s]["gaps_over_4d"])
    except Exception as e:
        out[s] = {"error": repr(e)}
        print(s, "FAILED", repr(e))
for s in ["BTCUSDT", "ETHUSDT"]:
    try:
        out[s] = audit_binance(s)
        print(s, "OK", out[s]["first"], "->", out[s]["last"], out[s]["bars"], "bars, missing days:", out[s]["missing_calendar_days"])
    except Exception as e:
        out[s] = {"error": repr(e)}
        print(s, "FAILED", repr(e))
with open("/home/hatch/workspace/goals/100u-200u/files/tae-b1/p1-trend/p1-data-audit.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("summary written")
