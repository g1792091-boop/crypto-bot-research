import sys,os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from vc import *
from scipy.stats import poisson
OUT=os.path.dirname(os.path.abspath(__file__))
O="/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/rb_analyze/out_real"
A=pd.read_csv(f"{OUT}/flow_accounts_v.csv")
for lab in RUNS:
    s=load(lab,"signal_log"); print(lab, sorted(s.symbol.unique()))
ref=pd.read_csv(f"{O}/fiveyear_ref.csv")
r36=ref[ref.source=="profiles_binance"][["strategy","timeframe","n_signals","per_day","long_share"]]
rds=ref[(ref.source=="deepseek200")&(ref.variant=="X5_TRAIL2")][["strategy","timeframe","n_signals","per_day"]]
P=A[A.kind.isin(["strategy","ds200"])].groupby(["kind","strategy","timeframe"]).agg(sub=("sub","sum"),days=("days","sum"),trades=("trades","sum")).reset_index()
P["live_pd"]=P["sub"]/P["days"]
M=pd.concat([P[P.kind=="strategy"].merge(r36,on=["strategy","timeframe"],how="left"),P[P.kind=="ds200"].merge(rds,on=["strategy","timeframe"],how="left")])
M["ratio"]=M.live_pd/M.per_day
M["p_le"]=poisson.cdf(M["sub"],M.per_day*M.days)
M.to_csv(f"{OUT}/rate_vs5y_v.csv",index=False)
ok=M[(M.per_day>0)&(M["sub"]>0)]
print("cells with both>0:",len(ok),"median ratio",ok.ratio.median(),ok.ratio.quantile([.25,.75]).tolist(),"logcorr",np.corrcoef(np.log(ok.live_pd),np.log(ok.per_day))[0,1])
for k in ["strategy","ds200"]:
  for tf in ["15m","30m","1h","4h"]:
    x=ok[(ok.kind==k)&(ok.timeframe==tf)]; print(k,tf,len(x),round(x.ratio.median(),2))
x=M[M.kind=="strategy"]; print("core cells with 5y per_day>0 but live 0:", ((x.per_day>0)&(x["sub"]==0)).sum())
print(M[M.strategy.isin(["N21_ST_RSI_ADX","N14_ICHI_RSI","N15_KC_AO","S1_EMA_RSI_CHOP","N11_BREAKAWAY","N08_ICHI_WR","S5_DONCHIAN_MFI","N03_ADX_GC"])].round(3).to_string())
print(r36[r36.strategy.isin(["N21_ST_RSI_ADX","N14_ICHI_RSI"])])
