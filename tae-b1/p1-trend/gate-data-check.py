"""Gate P1 六合约专项核查：只做公开市场数据描述性统计，不算策略收益、不回测。
合约：SPY_USDT, QQQ_USDT, TLT_USDT, GLD_USDT, BTC_USDT, ETH_USDT
来源：Gate 公开 API https://api.gateio.ws/api/v4/futures/usdt/
"""
import json, time, urllib.request, datetime

BASE = "https://api.gateio.ws/api/v4/futures/usdt"
CONTRACTS = ["SPY_USDT", "QQQ_USDT", "TLT_USDT", "GLD_USDT", "BTC_USDT", "ETH_USDT"]

def get(path):
    req = urllib.request.Request(BASE + path, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def dt(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d")

out = {}
contracts = {c["name"]: c for c in get("/contracts")}
for name in CONTRACTS:
    c = contracts.get(name)
    if not c:
        out[name] = {"error": "not in contracts list"}
        continue
    row = {"status": c.get("status"), "in_delisting": c.get("in_delisting"),
           "contract_type": c.get("contract_type"),
           "launch_time": c.get("launch_time"), "launch_date_utc": dt(c["launch_time"]) if c.get("launch_time") else None,
           "create_time": c.get("create_time"),
           "quanto_multiplier": c.get("quanto_multiplier"),
           "order_size_min": c.get("order_size_min"), "order_size_max": c.get("order_size_max"),
           "leverage_min": c.get("leverage_min"), "leverage_max": c.get("leverage_max"),
           "maintenance_rate": c.get("maintenance_rate"),
           "funding_interval_sec": c.get("funding_interval"),
           "funding_rate_now": c.get("funding_rate"),
           "maker_fee_rate": c.get("maker_fee_rate"), "taker_fee_rate": c.get("taker_fee_rate"),
           "last_price": c.get("last_price"), "mark_price": c.get("mark_price"), "index_price": c.get("index_price"),
           "position_size_contracts": c.get("position_size"), "trade_size": c.get("trade_size"),
           "long_users": c.get("long_users"), "short_users": c.get("short_users")}
    try:
        q = float(c["quanto_multiplier"]); p = float(c["last_price"]); smin = float(c["order_size_min"])
        row["min_notional_usdt_at_min_size"] = smin * q * p if smin else None
        row["one_contract_notional_usdt"] = q * p
    except Exception as e:
        row["notional_error"] = str(e)
    # tickers
    try:
        tk = get(f"/tickers?contract={name}")
        if isinstance(tk, list):
            tk = tk[0] if tk else {}
        row["ticker"] = tk
    except Exception as e:
        row["ticker_error"] = str(e)
    # order book
    try:
        ob = get(f"/order_book?contract={name}&limit=20&interval=0")
        bids = ob.get("bids", []); asks = ob.get("asks", [])
        def depth(levels):
            tot = 0.0
            for px, sz in levels:
                tot += float(px) * float(sz) * float(c["quanto_multiplier"])
            return tot
        if bids and asks:
            b1, a1 = float(bids[0][0]), float(asks[0][0])
            mid = (b1 + a1) / 2
            row["orderbook"] = {"bid1": b1, "ask1": a1, "mid": mid,
                                "spread_pct": (a1 - b1) / mid * 100,
                                "bid_depth_top20_usdt": depth(bids),
                                "ask_depth_top20_usdt": depth(asks)}
    except Exception as e:
        row["orderbook_error"] = str(e)
    # funding history: try funding_rate endpoint
    try:
        fr = get(f"/funding_rate?contract={name}&limit=100")
        if isinstance(fr, list) and fr:
            rates = [float(x.get("r", x.get("funding_rate", 0))) for x in fr if isinstance(x, dict)]
            if rates:
                row["funding_history_n"] = len(rates)
                row["funding_mean"] = sum(rates) / len(rates)
                row["funding_median"] = sorted(rates)[len(rates)//2]
                row["funding_pos_share"] = sum(1 for r in rates if r > 0) / len(rates)
                row["funding_first_t"] = fr[-1].get("t"); row["funding_last_t"] = fr[0].get("t")
        else:
            row["funding_history_raw"] = str(fr)[:200]
    except Exception as e:
        row["funding_history_error"] = str(e)
    # daily klines: earliest + coverage (limit 1000 covers ~2.7y; stocks contracts are younger)
    try:
        kl = get(f"/candlesticks?contract={name}&interval=1d&limit=1000")
        if isinstance(kl, list) and kl:
            row["daily_klines_n_returned"] = len(kl)
            row["daily_first_date_utc"] = dt(int(kl[0][0]))
            row["daily_last_date_utc"] = dt(int(kl[-1][0]))
            vols = [float(k[1]) for k in kl]
            row["daily_volume_contracts_mean"] = sum(vols) / len(vols)
            row["daily_volume_contracts_median"] = sorted(vols)[len(vols)//2]
    except Exception as e:
        row["klines_error"] = str(e)
    # weekend trading check: 1h klines Sat 2026-10-24 00:00 UTC -> Mon 2026-10-26 00:00 UTC
    try:
        frm = int(datetime.datetime(2026, 10, 24, tzinfo=datetime.timezone.utc).timestamp())
        to = int(datetime.datetime(2026, 10, 26, tzinfo=datetime.timezone.utc).timestamp())
        wk = get(f"/candlesticks?contract={name}&interval=1h&from={frm}&to={to}&limit=100")
        row["weekend_1h_candles_oct24_25"] = len(wk) if isinstance(wk, list) else wk
    except Exception as e:
        row["weekend_error"] = str(e)
    out[name] = row
    print(f"--- {name} done ---")

with open("/home/hatch/workspace/goals/100u-200u/files/tae-b1/p1-trend/gate-data-check.json", "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("WROTE gate-data-check.json")
