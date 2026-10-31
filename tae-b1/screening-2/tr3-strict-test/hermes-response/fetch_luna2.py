import ccxt, pandas as pd, os
PROX={"http":"http://127.0.0.1:7890","https":"http://127.0.0.1:7890"}
ex=ccxt.binance({"enableRateLimit":True,"timeout":30000,"proxies":PROX})
for sym in ["LUNA/USDT","LUNA2/USDT","POL/USDT","S/USDT"]:
    try:
        since=ex.parse8601("2022-01-01T00:00:00Z"); rows=[]
        while True:
            o=ex.fetch_ohlcv(sym,"1d",since=since,limit=1000)
            if not o: break
            rows+=o; since=o[-1][0]+86400000
            if len(o)<1000: break
        if not rows: print(sym,"EMPTY"); continue
        df=pd.DataFrame(rows,columns=["ts","open","high","low","close","volume"]).drop_duplicates("ts").sort_values("ts")
        df["date"]=pd.to_datetime(df.ts,unit="ms").dt.strftime("%Y-%m-%d")
        fn=os.environ.get("TR3_DATA",".")+"/"+sym.replace("/","")+"_1d.csv"
        df.to_csv(fn,index=False)
        print("%-10s bars=%5d %s -> %s  first=%.6f last=%.6f"%(sym,len(df),df.date.iloc[0],df.date.iloc[-1],df.close.iloc[0],df.close.iloc[-1]))
    except Exception as e:
        print(sym,"FAIL",type(e).__name__,str(e)[:90])