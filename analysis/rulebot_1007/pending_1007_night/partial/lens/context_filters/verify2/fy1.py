sys.path.insert(0,'/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens/context_filters/verify2')
from lib import *
X=pd.read_pickle(VD+'fy.pkl'); X=X[X.R.notna()].reset_index(drop=True)
s=X.side.values
X['day']=(X.close_t+9*H)//(24*H); X['year']=pd.to_datetime(X.close_t+9*H,unit='ms').dt.year
h=X.kst_hour.values
X['europe']=(h>=16)&(h<=21)
X['adx30']=X.adx>=30
p=np.where(s>0,X.htf_pos,1-X.htf_pos); X['htfmid']=np.where(np.isnan(p),np.nan,((p>=0.2)&(p<0.8)).astype(float))
e=s*X.ema_dist; X['emawith']=(e>=0.5)&(e<1.5)
X['diwith']=np.where(X.dip.isna(),np.nan,(s*(X.dip-X.dim)>0).astype(float))
p=np.where(s>0,X.box_pos,1-X.box_pos); X['boxfar']=np.where(np.isnan(p),np.nan,(p>=0.8).astype(float))
p=np.where(s>0,X.range_pos,1-X.range_pos); X['rngfar']=np.where(np.isnan(p),np.nan,(p>=0.8).astype(float))
X['wide']=np.where(X.tf=='15m',X.stop_pct>=0.7,X.stop_pct>=1.0)
X['many']=X.n_same>=4
X['cost']=2*(0.0005+0.0002)*100/X.stop_pct
X['gross']=X.R+X.cost
def strat_contrast(x,col,strata,oc='R',minn=10):
    x=x[x[col].notna()]
    inb=x[col].astype(bool).values; y=x[oc].values; d=x.day.values
    key=pd.MultiIndex.from_frame(x[strata]).codes if False else x.groupby(strata).ngroup().values
    df=pd.DataFrame({'k':key,'in':inb,'y':y,'day':d})
    g=df.groupby(['k','in']).y.agg(['sum','size']).unstack(fill_value=0)
    ok=(g[('size',True)]>=minn)&(g[('size',False)]>=minn)
    g=g[ok]; nk=g[('size',True)]+g[('size',False)]; w=nk/nk.sum()
    mi=g[('sum',True)]/g[('size',True)]; mo=g[('sum',False)]/g[('size',False)]
    dd=float((w*(mi-mo)).sum())
    df=df[df.k.isin(g.index)]
    W=w.reindex(df.k).values; MI=mi.reindex(df.k).values; MO=mo.reindex(df.k).values
    NI=g[('size',True)].reindex(df.k).values; NO=g[('size',False)].reindex(df.k).values
    inf=W*np.where(df['in'],(df.y-MI)/NI,-(df.y-MO)/NO)
    cs=pd.Series(inf).groupby(df.day.values).sum().values; G=len(cs)
    se_day=np.sqrt(G/(G-1)*np.sum(cs**2))
    # wrong way: per-stratum day clusters, variances summed (ignores cross-strategy same-day correlation)
    cs2=pd.Series(inf).groupby([df.k.values,df.day.values]).sum().values
    se_naive=np.sqrt(np.sum(cs2**2))
    # week clusters
    cs3=pd.Series(inf).groupby(df.day.values//7).sum().values; G3=len(cs3); se_wk=np.sqrt(G3/(G3-1)*np.sum(cs3**2))
    return dd,se_day,se_naive,se_wk
res=[]
for tf in ['15m','30m']:
    x=X[X.tf==tf]
    for col in ['europe','adx30','htfmid','emawith','diwith','boxfar','rngfar','wide','many']:
        d,sd,sn,sw=strat_contrast(x,col,['strategy','year','side'])
        yrs=[strat_contrast(x[x.year==yy],col,['strategy','side'])[0] for yy in sorted(x.year.unique())]
        r=dict(tf=tf,c=col,d=d,z_day=d/sd,z_stratum_only=d/sn,z_week=d/sw,years_same_sign=f"{sum(np.sign(yrs)==np.sign(d))}/{len(yrs)}")
        if col=='wide':
            r['d_roe']=strat_contrast(x,col,['strategy','year','side'],'roe')[0]; r['d_gross']=strat_contrast(x,col,['strategy','year','side'],'gross')[0]
            r['d_lev_strata']=strat_contrast(x,col,['strategy','year','side','lev'])[0]
        res.append(r)
print(pd.DataFrame(res).round(4).to_string(index=False))
