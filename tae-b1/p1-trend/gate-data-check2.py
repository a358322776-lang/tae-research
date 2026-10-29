"""Gate P1 六合约核查补测：修正解析（orderbook 为 {p,s} 对象、K 线为 {t,v,o,c,h,l,sum} 对象）。
只做公开市场数据描述性统计，不算策略收益、不回测。"""
import json, urllib.request, datetime

BASE = "https://api.gateio.ws/api/v4/futures/usdt"
CONTRACTS = ["SPY_USDT", "QQQ_USDT", "TLT_USDT", "GLD_USDT", "BTC_USDT", "ETH_USDT"]

def get(path):
    req = urllib.request.Request(BASE + path, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def dt(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")

out = {}
contracts = {c["name"]: c for c in get("/contracts")}
for name in CONTRACTS:
    c = contracts[name]
    q = float(c["quanto_multiplier"]); row = {}
    # ticker
    tk = get(f"/tickers?contract={name}")[0]
    row["ticker"] = {"last": tk["last"], "volume_24h_contracts": tk["volume_24h"],
                     "volume_24h_usdt": tk["volume_24h_quote"], "change_pct": tk["change_percentage"],
                     "highest_bid": tk["highest_bid"], "lowest_ask": tk["lowest_ask"],
                     "funding_rate": tk["funding_rate"]}
    # orderbook top 20
    ob = get(f"/order_book?contract={name}&limit=20")
    bids = [(float(x["p"]), float(x["s"])) for x in ob["bids"]]
    asks = [(float(x["p"]), float(x["s"])) for x in ob["asks"]]
    mid = (bids[0][0] + asks[0][0]) / 2
    def depth_usd(levels):
        return sum(p * s * q for p, s in levels)
    def depth_within(levels, band, side):
        tot = 0.0
        for p, s in levels:
            if (side == "bid" and p >= mid * (1 - band)) or (side == "ask" and p <= mid * (1 + band)):
                tot += p * s * q
        return tot
    row["orderbook"] = {"bid1": bids[0], "ask1": asks[0], "mid": mid,
                        "spread_pct": (asks[0][0] - bids[0][0]) / mid * 100,
                        "bid_depth_top20_usdt": depth_usd(bids), "ask_depth_top20_usdt": depth_usd(asks),
                        "bid_depth_within_0.1pct_usdt": depth_within(bids, 0.001, "bid"),
                        "ask_depth_within_0.1pct_usdt": depth_within(asks, 0.001, "ask"),
                        "bid_depth_within_0.5pct_usdt": depth_within(bids, 0.005, "bid"),
                        "ask_depth_within_0.5pct_usdt": depth_within(asks, 0.005, "ask")}
    # funding history, larger limit
    try:
        fr = get(f"/funding_rate?contract={name}&limit=1000")
        rates = [float(x["r"]) for x in fr]
        ts = [int(x["t"]) for x in fr]
        row["funding"] = {"n": len(rates), "first": dt(ts[-1]), "last": dt(ts[0]),
                          "mean": sum(rates) / len(rates), "median": sorted(rates)[len(rates)//2],
                          "max": max(rates), "min": min(rates),
                          "pos_share": sum(1 for r in rates if r > 0) / len(rates),
                          "zero_share": sum(1 for r in rates if r == 0) / len(rates)}
    except Exception as e:
        row["funding_error"] = str(e)
    # daily klines
    kl = get(f"/candlesticks?contract={name}&interval=1d&limit=1000")
    row["daily"] = {"n": len(kl), "first": dt(int(kl[0]["t"])), "last": dt(int(kl[-1]["t"])),
                    "mean_vol_contracts": sum(float(k["v"]) for k in kl) / len(kl),
                    "median_vol_contracts": sorted(float(k["v"]) for k in kl)[len(kl)//2],
                    "mean_quote_usdt": sum(float(k["sum"]) for k in kl) / len(kl)}
    # weekend vs weekday 1h (no limit param, Gate paginates by from/to)
    def window_1h(frm, to):
        return get(f"/candlesticks?contract={name}&interval=1h&from={frm}&to={to}")
    f_we = int(datetime.datetime(2026, 10, 24, tzinfo=datetime.timezone.utc).timestamp())
    t_we = int(datetime.datetime(2026, 10, 26, tzinfo=datetime.timezone.utc).timestamp())
    f_wd = int(datetime.datetime(2026, 10, 27, tzinfo=datetime.timezone.utc).timestamp())
    t_wd = int(datetime.datetime(2026, 10, 28, tzinfo=datetime.timezone.utc).timestamp())
    for label, frm, to in [("weekend_oct24_25", f_we, t_we), ("weekday_oct27", f_wd, t_wd)]:
        wk = window_1h(frm, to)
        vols = [float(k["v"]) for k in wk]
        moved = sum(1 for k in wk if float(k["h"]) != float(k["l"]))
        row[label] = {"n_candles": len(wk), "nonzero_vol": sum(1 for v in vols if v > 0),
                      "moved_candles": moved, "total_vol_contracts": sum(vols)}
    out[name] = row
    print(f"--- {name} done ---")

with open("/home/hatch/workspace/goals/100u-200u/files/tae-b1/p1-trend/gate-data-check2.json", "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("WROTE gate-data-check2.json")
