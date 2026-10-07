"""per strategy x tf cells (36 x 15m/30m) with my bootstrap, BH, per-run signs, tiers by the analyst's stated rules.
usage: python3 -I cells.py <out_real_dir> <export_dir>"""
import os,sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import vlib
import pandas as pd, numpy as np, zlib
from boot import cboot, bh
OR,E=sys.argv[1:3]
A=pd.read_csv('my_es_rows_all.csv'); T=A[A.status=='TRADED']
F5=pd.read_csv(OR+'/fiveyear_ref.csv'); F5=F5[F5.source=='profiles_binance']
strats=sorted(F5.strategy.unique()); print('n strategies',len(strats))
SF=pd.read_csv(OR+'/coinflip_sideflip.csv'); SF=SF[(SF.kind=='strategy')&(SF.level=='strategy_tf')].set_index(['strategy','timeframe'])
rows=[]
for st in strats:
    for tf in ['15m','30m']:
        g=T[(T.strategy==st)&(T.tf==tf)]
        seed=zlib.crc32(f'{st}{tf}'.encode())
        b=cboot(g,'R','blk4',seed=seed) if len(g)>=1 else {}
        d=dict(strategy=st,tf=tf,n=len(g),mean=g.R.mean(),lo=b.get('lo'),hi=b.get('hi'),p_pos=b.get('p_le0'),p_neg=b.get('p_ge0'),ncl=b.get('ncl'),win=100*(g.R>0).mean() if len(g) else np.nan)
        for rn in ['v3a','v3b','v4']:
            x=g[g.rn==rn]; d[f'n_{rn}']=len(x); d[f'm_{rn}']=x.R.mean() if len(x) else np.nan
        lat=g[g.rn!='v3a']; d['n_later']=len(lat); d['m_later']=lat.R.mean() if len(lat) else np.nan
        f=F5[(F5.strategy==st)&(F5.timeframe==tf)]
        if len(f):
            f=f.iloc[0]; d.update(y5_notional=f.mean_ret_notional,y5_t=f.mean_roe_t,y5_is=f.mean_roe_is,y5_cf=f.mean_roe_cf,y5_n=f.n_signals,y5_perday=f.per_day)
        d['sf_excess']=SF.loc[(st,tf),'excess_R'] if (st,tf) in SF.index else np.nan
        d['sf_p']=SF.loc[(st,tf),'p_better'] if (st,tf) in SF.index else np.nan
        d['sf_n']=SF.loc[(st,tf),'n_pairs'] if (st,tf) in SF.index else np.nan
        rows.append(d)
C=pd.DataFrame(rows)
test=(C.n>=10)&(C.ncl>=5)
C.loc[test,'q_pos']=bh(C.loc[test,'p_pos']); C.loc[test,'q_neg']=bh(C.loc[test,'p_neg'])
def tier(r):
    signs=[np.sign(r[f'm_{p}']) for p in ['v3a','v3b','v4'] if r[f'n_{p}']>=5]
    k=len(signs); pos=sum(s>0 for s in signs); neg=sum(s<0 for s in signs)
    y5neg=(r.y5_notional<0) and (r.y5_t<-2)
    if r.n>=30 and r['mean']>0 and r.lo>0 and k>=2 and pos==k and r.sf_excess>0 and not y5neg: return 'A'
    if r.n>=20 and r['mean']<0 and y5neg and ((k>=2 and neg==k) or r.hi<0): return 'D'
    if r.n>=20 and r['mean']>0 and ((k>=2 and pos>=2 and neg<=1) or (k>=1 and pos==k)): return 'B'
    return 'C'
C['tier']=C.apply(tier,axis=1)
C['signs']=C.apply(lambda r:' '.join(('+' if r[f'm_{p}']>0 else '-')+f"({r[f'n_{p}']})" if r[f'n_{p}']>0 else 'na' for p in ['v3a','v3b','v4']),axis=1)
C.to_csv('my_cells.csv',index=False)
print('testable',test.sum(),' q_pos<0.05',(C.q_pos<0.05).sum(),' q_neg<0.05',(C.q_neg<0.05).sum(), ' q_neg<0.10',(C.q_neg<0.10).sum())
c20=C[C.n>=20]; print('n>=20:',len(c20),' mean<0',(c20['mean']<0).sum(),' hi<0',(c20.hi<0).sum(),' lo>0',(c20.lo>0).sum())
print(C.tier.value_counts().to_dict()); print(C.groupby('tf').tier.value_counts().unstack())
print(C[C.tier=='B'][['strategy','tf','n','mean','lo','hi','signs','m_later']].round(3).to_string())
print(C[C.q_neg<0.05][['strategy','tf','n','mean','lo','hi','q_neg','signs']].round(3).to_string())
print('zero n:',(C.n==0).sum(), C[C.n==0][['strategy','tf']].values.tolist())
# compare with analyst cards
K=pd.read_csv(sys.argv[3]) if len(sys.argv)>3 else None
