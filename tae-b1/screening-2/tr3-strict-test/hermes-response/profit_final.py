import pandas as pd, numpy as np, glob, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import book_weights, stats
D=os.environ.get("TR3_DATA", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),"data"))
def load(s):
    d=pd.read_csv(os.path.join(D,s+"_1d.csv")); d["date"]=pd.to_datetime(d["date"])
    return d.set_index("date").sort_index().close.astype(float)

base_syms=[os.path.basename(p).replace("_1d.csv","") for p in glob.glob(D+"/*USDT_1d.csv")]
base_syms=[s for s in base_syms if s not in ("LUNA_NEW",)]          # 60 original files
panels={}
panels["A: frozen 60 (old LUNA only)"]=pd.DataFrame({s:load(s) for s in base_syms}).sort_index()

# B: same 60 but LUNA switches to NEW luna after 2022-05-31 (economic continuity)
p2=pd.DataFrame({s:load(s) for s in base_syms}).sort_index()
newl=load("LUNA_NEW"); newl=newl[newl.index>=pd.Timestamp("2022-05-31")]
merged=pd.concat([p2["LUNAUSDT"].dropna(), newl]).sort_index()
merged=merged[~merged.index.duplicated(keep="last")]
p2["LUNAUSDT"]=merged.reindex(p2.index)
panels["B: 60 + newLUNA spliced"]=p2
print("merged LUNA: %s .. %s (%d bars)"%(merged.index.min().date(),merged.index.max().date(),len(merged)))

for k in panels: panels[k]=panels[k][panels[k].index>="2018-01-01"]

def run(panel,cost_side=0.0015,lag=1):
    NC=panel.shape[1]
    W=book_weights(panel,dict(entry_n=20,exit_n=10,slot=1.0/NC,max_pos=60)).values
    R=np.nan_to_num(panel.pct_change().fillna(0.0).values,nan=0.0,posinf=0.0,neginf=0.0)
    We=np.vstack([np.zeros((lag,NC)),W[:-lag]])
    gross=(We*R).sum(axis=1)
    turn=np.abs(We-np.vstack([np.zeros((1,NC)),We[:-1]])).sum(axis=1)
    eq=pd.Series(np.cumprod(1+gross-turn*cost_side),index=panel.index)
    return eq

print("\n=== LUNA BIAS: how much does adding new LUNA cost? ===")
for nm,p in panels.items():
    eq=run(p); s=stats(eq); o=stats(eq[eq.index>="2022-01-01"]/(eq[eq.index>="2022-01-01"].iloc[0]))
    print("  %-32s FULL %6.1f%% sh%.2f | OOS %6.1f%% sh%.2f"%(nm,s["cagr"]*100,s["sharpe"],o["cagr"]*100,o["sharpe"]))

print("\n=== FINAL MATRIX (panel B = defects fixed) ===")
pB=panels["B: 60 + newLUNA spliced"]
print("  %-22s %8s %8s %8s %8s"%("scenario","FULLcagr","FULLmdd","OOScagr","OOSsh"))
rows=[]
for lab,cs,lag in [("best  6bp lag1",0.0006,1),("real 15bp lag1",0.0015,1),
                   ("real 25bp lag1",0.0025,1),("hard 25bp lag2",0.0025,2),
                   ("hard 40bp lag2",0.0040,2),("brutal 60bp lag3",0.0060,3)]:
    eq=run(pB,cost_side=cs,lag=lag); s=stats(eq)
    o=eq[eq.index>="2022-01-01"]; so=stats(o/o.iloc[0])
    rows.append((lab,s,so)); print("  %-22s %7.1f%% %7.1f%% %7.1f%% %8.2f"%(lab,s["cagr"]*100,s["mdd"]*100,so["cagr"]*100,so["sharpe"]))

print("\n=== YEARLY (panel B, 15bp lag1) ===")
eq=run(pB); y=eq.pct_change().dropna()
ann=y.groupby(y.index.year).apply(lambda g:(1+g).prod()-1)*100
print("  "+"  ".join("%d:%+.0f%%"%(i,v) for i,v in ann.items()))
print("  positive years: %d/%d"%((ann>0).sum(),len(ann)))

print("\n=== WHAT KILLS IT: worst drawdown & recovery ===")
dd=(eq/eq.cummax()-1); print("  max dd %.1f%%   current dd %.1f%%"%((dd.min()*100),(dd.iloc[-1]*100)))
cur=eq.index[-1]; pk=eq.loc[:cur].idxmax()
print("  last ATH %s (%d days ago)"%(pk.date(),(cur-pk).days))