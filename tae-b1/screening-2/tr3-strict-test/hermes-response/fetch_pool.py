import ccxt, pandas as pd, os, time
PROX={"http":"http://127.0.0.1:7890","https":"http://127.0.0.1:7890"}
ex=ccxt.binance({"enableRateLimit":True,"timeout":30000,"proxies":PROX})
syms=["BTCUSDT","ETHUSDT","BNBUSDT","XRPUSDT","LTCUSDT","BCHUSDT","ADAUSDT","EOSUSDT","XLMUSDT","TRXUSDT",
"ETCUSDT","NEOUSDT","XMRUSDT","DASHUSDT","ZECUSDT","DOGEUSDT","VETUSDT","LINKUSDT","ATOMUSDT","ONTUSDT",
"IOTXUSDT","QTUMUSDT","ZILUSDT","ALGOUSDT","SOLUSDT","DOTUSDT","UNIUSDT","AVAXUSDT","LUNAUSDT","FTTUSDT",
"THETAUSDT","AXSUSDT","SANDUSDT","MANAUSDT","GRTUSDT","CHZUSDT","ENJUSDT","SUSHIUSDT","CRVUSDT","COMPUSDT",
"SNXUSDT","YFIUSDT","APTUSDT","OPUSDT","ARBUSDT","SUIUSDT","TIAUSDT","SEIUSDT","WIFUSDT","JUPUSDT",
"PEPEUSDT","INJUSDT","RUNEUSDT","MATICUSDT","1INCHUSDT","KSMUSDT","ICPUSDT","FILUSDT","NEARUSDT","FTMUSDT"]
ok=fail=0
for i,sym in enumerate(syms):
    fp=os.path.join(os.environ.get("TR3_DATA","."), sym+"_1d.csv")
    if os.path.exists(fp):
        ok+=1; continue
    try:
        since=ex.parse8601("2017-01-01T00:00:00Z"); rows=[]; guard=0
        while guard<6:
            guard+=1
            o=ex.fetch_ohlcv(sym,"1d",since=since,limit=1000)
            if not o: break
            rows+=o; since=o[-1][0]+86400000
            if len(o)<1000: break
        if len(rows)<250: print("skip",sym,len(rows),flush=True); fail+=1; continue
        df=pd.DataFrame(rows,columns=["ts","open","high","low","close","volume"]).drop_duplicates("ts").sort_values("ts")
        df["date"]=pd.to_datetime(df.ts,unit="ms").dt.strftime("%Y-%m-%d")
        df.to_csv(fp,index=False)
        print("%2d %-10s bars=%5d %s->%s  %s"%(i,sym,len(df),df.date.iloc[0],df.date.iloc[-1],
              "DEAD" if pd.to_datetime(df.date.iloc[-1])<pd.Timestamp("2026-06-01") else "live"),flush=True)
        ok+=1
    except Exception as e:
        print("FAIL",sym,type(e).__name__,str(e)[:60],flush=True); fail+=1
    time.sleep(0.15)
print("done ok=%d fail=%d"%(ok,fail),flush=True)