import pandas as pd, numpy as np, glob, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import run_backtest, stats, book_weights
D=os.environ.get("TR3_DATA", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),"data"))
def load(s):
    d=pd.read_csv(os.path.join(D,s+"_1d.csv")); d["date"]=pd.to_datetime(d["date"])
    return d.set_index("date").sort_index().close.astype(float)
syms=sorted(os.path.basename(p).replace("_1d.csv","") for p in glob.glob(D+"/*USDT_1d.csv"))
panel=pd.DataFrame({s:load(s) for s in syms}).sort_index(); panel=panel[panel.index>="2018-01-01"]
NC=panel.shape[1]
print("NC (columns) = %d"%NC)
print("alive on last day = %d"%panel.iloc[-1].notna().sum())

print("\n=== H5: parameter plane sweep (48 combos, ON THE FROZEN 60-coin panel) ===")
rows=[]
for en in [10,15,20,25,30,40,55,70]:
    line="entry=%3d "%en
    for xn in [5,10,15,20,25,30]:
        r=run_backtest(panel,dict(entry_n=en,exit_n=xn,slot=1.0/NC,max_pos=60))
        s=stats(r["equity"]); rows.append((en,xn,s["cagr"],s["sharpe"],s["mdd"]))
        line+="%7.1f/%4.2f"%(s["cagr"]*100,s["sharpe"])
    print(line)
pos=sum(1 for r in rows if r[2]>0); sh=sum(1 for r in rows if r[3]>0.7)
print("\n%d combos: positive=%d/%d  sharpe>0.7=%d/%d  median_cagr=%.1f%%"%(
  len(rows),pos,len(rows),sh,len(rows),np.median([r[2] for r in rows])*100))
pd.DataFrame(rows,columns=["entry","exit","cagr","sharpe","mdd"]).to_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)),"param_sweep.csv"),index=False)
print("saved -> out/param_sweep.csv")