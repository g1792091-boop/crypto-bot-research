import os, sys, numpy as np, pandas as pd
G=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
f=sys.argv[1]; d=pd.read_csv(f)
FEEADJ=2*(0.0005-0.0001)
def pf(x): 
    x=np.asarray(x); gl=-x[x<=0].sum(); return x[x>0].sum()/gl if gl>0 else np.inf
def se(x): return np.std(x,ddof=1)/np.sqrt(len(x))*100
out=[]
for (s,ex),g in d.groupby(["strategy","exit"]):
    r=dict(strategy=s,exit=ex,n=len(g),
      orig=g.orig_net.mean()*100, r5=g.r5_PESS.mean()*100, m1=g.m1_PESS.mean()*100,
      d_m1_r5=(g.m1_PESS-g.r5_PESS).mean()*100, se_d=se(g.m1_PESS-g.r5_PESS),
      r5_opt_minus_pess=(g.r5_OPT-g.r5_PESS).mean()*100, m1_det_minus_pess=(g.m1_DET-g.m1_PESS).mean()*100,
      m1_opt_minus_pess=(g.m1_OPT-g.m1_PESS).mean()*100,
      pf_r5=pf(g.r5_PESS), pf_m1=pf(g.m1_PESS), pf_m1_opt=pf(g.m1_OPT),
      wr_r5=(g.r5_PESS>0).mean()*100, wr_m1=(g.m1_PESS>0).mean()*100, wr_m1_opt=(g.m1_OPT>0).mean()*100,
      m1_opt_fee01_s0=(g.m1_OPT_s0+FEEADJ).mean()*100, pf_m1_opt_fee01_s0=pf(g.m1_OPT_s0+FEEADJ), wr_m1_opt_fee01_s0=((g.m1_OPT_s0+FEEADJ)>0).mean()*100,
      wr_m1_fee01=((g.m1_PESS+FEEADJ)>0).mean()*100)
    out.append(r)
o=pd.DataFrame(out); pd.set_option("display.width",400); pd.set_option("display.max_columns",40)
print(o.round(4).to_string(index=False))
o.to_csv(f.replace("_trades_","_summary_"),index=False)
