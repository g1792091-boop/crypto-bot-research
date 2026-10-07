# Independent check of 5y per-notional/equity figures from the repo's own levstop.json (not the lens's c07 rerun)
import sys, json
exec(open('vb.py').read())
import numpy as np, pandas as pd
d=json.load(open(sys.argv[1])); C=d['columns']; MF={'10':0.2,'20':0.2,'30':0.3,'40':0.4,'50':0.4}
rows=[]
for cell,arms in d['cells'].items():
    s,tf=cell.split('|')
    for arm,v in arms.items():
        r=dict(zip(C,v)); lm,k=arm.split('|')
        rows.append(dict(strategy=s,tf=tf,lev=lm,k=float(k),**r))
D=pd.DataFrame(rows)
D=D[D.trades>0]
def agg(g):
    w=g.trades
    out=dict(trades=w.sum(),mean_roe=np.average(g.mean_roe,weights=w),mean_eq=np.average(g.mean_eq,weights=w),liq=np.average(g.liq_share,weights=w))
    return pd.Series(out)
A=D.groupby(['lev','k','tf']).apply(agg).reset_index()
A['bp_notl']=np.where(A.lev!='tiers',A.mean_roe/pd.to_numeric(A.lev,errors='coerce')*1e4,np.nan)
pd.set_option('display.width',200)
print(A[(A.k==2.0)].round(5).to_string())
B=D.groupby(['lev','k']).apply(agg).reset_index(); B['bp_notl']=np.where(B.lev!='tiers',B.mean_roe/pd.to_numeric(B.lev,errors='coerce')*1e4,np.nan)
print(B.round(5).to_string())
# excluding 5m
B2=D[D.tf!='5m'].groupby(['lev','k']).apply(agg).reset_index(); B2['bp_notl']=np.where(B2.lev!='tiers',B2.mean_roe/pd.to_numeric(B2.lev,errors='coerce')*1e4,np.nan)
print('no 5m'); print(B2[B2.k==2.0].round(5).to_string())
A.to_csv('out/a4_levstop_by_tf.csv',index=False); D.to_csv('out/a4_levstop_cells.csv',index=False)
