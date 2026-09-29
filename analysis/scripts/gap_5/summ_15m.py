import os, numpy as np, pandas as pd
G=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
d=pd.read_csv(f"{G}/out/c_1m_15m_trades.csv")
def pf(x):
    x=np.asarray(x); gl=-x[x<=0].sum(); return x[x>0].sum()/gl if gl>0 else np.inf
def se(x): return np.std(x,ddof=1)/np.sqrt(len(x))*100 if len(x)>1 else np.nan
def summ(g):
    dd=g.m1_PESS-g.r15_PESS
    return pd.Series(dict(n=len(g),orig=g.orig_net.mean()*100,r15=g.r15_PESS.mean()*100,m1=g.m1_PESS.mean()*100,
        d_orig_r15=(g.r15_PESS-g.orig_net).mean()*100,
        d_m1_r15=dd.mean()*100,se_d=se(dd),ci95_hi=abs(dd.mean()*100)+1.96*se(dd),
        r15_opt_m_pess=(g.r15_OPT-g.r15_PESS).mean()*100, m1_det_m_pess=(g.m1_DET-g.m1_PESS).mean()*100, m1_opt_m_pess=(g.m1_OPT-g.m1_PESS).mean()*100,
        pf_r15=pf(g.r15_PESS),pf_m1=pf(g.m1_PESS),pf_m1_opt=pf(g.m1_OPT),pf_r15_opt=pf(g.r15_OPT),
        wr_r15=(g.r15_PESS>0).mean()*100,wr_m1=(g.m1_PESS>0).mean()*100,
        reason_agree=(g.m1_PESS_reason==g.r15_PESS_reason).mean()))
pd.set_option("display.width",300); pd.set_option("display.max_columns",30)
PRIM=["S5_DONCHIAN_MFI","S6_EMA_DMI_ADX","V39_15M","OBV_S"]
p=d[d.strategy.isin(PRIM)]
print("=== primary 4 strategies, per strategy x exit (L50 / trail / best fixed) ===")
sel=p[p.exit.isin(["L50_sl15","L50_sl20","T_sl1.5_tr1.5","T_sl1.5_tr2.5","F_sl2.0_tp3.0"])]
a=sel.groupby(["strategy","exit"]).apply(summ,include_groups=False); print(a.round(4).to_string())
print("=== primary 4 pooled, by exit ===")
b=p.groupby("exit").apply(summ,include_groups=False); print(b.round(4).to_string())
print("=== ALL strategies pooled, by exit ===")
c=d.groupby("exit").apply(summ,include_groups=False); print(c.round(4).to_string())
print("=== ALL strategies pooled, by exit mode ===")
d["emode"]=d.exit.str[0]
e=d.groupby("emode").apply(summ,include_groups=False); print(e.round(4).to_string())
a.to_csv(f"{G}/out/c_1m_15m_summary_primary.csv"); b.to_csv(f"{G}/out/c_1m_15m_summary_primary_pooled.csv"); c.to_csv(f"{G}/out/c_1m_15m_summary_all_pooled.csv")
# per strategy x exit, max |d| across all combos with n>=30
f=d.groupby(["strategy","exit"]).apply(summ,include_groups=False); f=f[f.n>=30]
print("combos with n>=30:",len(f)," max|d_m1_r15|=%.4f  combos |d|>0.01: %d  combos with 95%%CI upper |d| > 0.01: %d"%(f.d_m1_r15.abs().max(),(f.d_m1_r15.abs()>0.01).sum(),(f.ci95_hi>0.01).sum()))
print(f[f.d_m1_r15.abs()>0.01].round(4)[["n","r15","m1","d_m1_r15","se_d","pf_r15","pf_m1"]].to_string())
f.to_csv(f"{G}/out/c_1m_15m_summary_all_combos.csv")
