import site,sys; sys.path.append(site.getusersitepackages())
import pandas as pd, numpy as np
V,TE=sys.argv[1],sys.argv[2]
R=pd.read_csv(V+'/vsignals.csv')
R=R[R.base_st.isin(['TRADED','OPEN'])&R.kind.isin(['strategy','ds200'])].copy()
R['rs']=R.run.map({'run-20261005T183457Z':'v3b','current':'v4'})
TFM={'15m':15,'30m':30,'1h':60,'4h':240}
print('== giveback on every-signal replay (v3b+v4) ==')
for kind in ['strategy','ds200']:
  for tf in ['15m','30m','1h']:
    g=R[(R.kind==kind)&(R.timeframe==tf)]
    mfe=g.base_mfe; sl=g.base_exit=='SL'
    gb05=((mfe>=0.5)&sl).mean(); gb10=((mfe>=1)&sl).mean()
    slR=g.base_R[(mfe>=0.5)&sl].mean()
    # first rung: reached +1R and closed on lock 0.10
    fr=((mfe>=1)&(g.base_exit=='LOCK')&(np.isclose(g.base_lock,0.10))).mean()
    print(kind,tf,'n',len(g),'gb05_SL %.3f'%gb05,'R of those %.2f'%slR,'gb10_SL %.3f'%gb10,'reach1R %.3f'%(mfe>=1).mean(),'1R->firstlock %.3f'%fr)
print('== real trades (house exits), all runs ==')
T=pd.read_csv(TE); T=T[T.exits=='house']
T['rs']=T.run.map({'run-20261005T014624Z':'v3a','run-20261005T183457Z':'v3b','current':'v4'})
for kind in ['strategy','ds200']:
  for tf in ['15m','30m','1h']:
    g=T[(T.kind==kind)&(T.tf==tf)]
    if not len(g): continue
    gb=((g.mfe_R>=0.5)&(g.exit_reason=='SL')).mean()
    print(kind,tf,'n',len(g),'gb05_SL %.3f'%gb)
print('== first rung: reached +1R but closed on first 10% lock (real trades) ==')
for rs in ['v3a','v3b','v4']:
  for kind in ['strategy','ds200']:
    g=T[(T.rs==rs)&(T.kind==kind)&(T.tf=='15m')]
    if not len(g): continue
    m=(g.mfe_R>=1)&(g.exit_reason=='LOCK')&np.isclose(g.lock_roe.fillna(-1),0.10)
    print(rs,kind,'15m n',len(g),'share %.3f'%m.mean(),'kept R %.2f'%g.R[m].mean(),'MFE %.2f'%g.mfe_R[m].mean(), 'lev mix',g.leverage[m].value_counts().to_dict())
print('== hindsight UB (signals): BE on losers that saw +0.5R + cut dead losers (<0.2 MFE) at -0.5R [+ half-MFE comp] ; oracle ==')
for kind in ['strategy','ds200']:
  for tf in ['15m','30m','1h']:
    g=R[(R.kind==kind)&(R.timeframe==tf)].copy()
    n=len(g); Rr=g.base_R.to_numpy(); mfe=g.base_mfe.to_numpy()
    cost=(0.0012)/g.base_sf.to_numpy()  # approx entry fee+exit fee+exit slip in R
    lose=Rr<0
    ub_gb=np.where((mfe>=0.5)&lose,-Rr,0).sum()/n
    dead=lose&(mfe<0.2); rc=-0.5-cost
    ub_dead=np.where(dead&(Rr<rc),rc-Rr,0).sum()/n
    half=(mfe>=1)&(Rr>=0)&(Rr<0.5*mfe); ub_half=np.where(half,0.5*mfe-Rr,0).sum()/n
    orc=np.maximum(mfe-cost-Rr,0).sum()/n
    print(kind,tf,'n',n,'gb %.3f dead %.3f half %.3f  sum2 %.3f sum3 %.3f oracle %.3f'%(ub_gb,ub_dead,ub_half,ub_gb+ub_dead,ub_gb+ub_dead+ub_half,orc))
print('== AIH-5 time stats ==')
for kind in ['strategy','ds200']:
  for tf in ['15m','30m','1h']:
    g=R[(R.kind==kind)&(R.timeframe==tf)]; m=TFM[tf]
    lose=g.base_R<0; dead=(lose&(g.base_mfe<0.2)).sum()/lose.sum()
    sl=g[g.base_exit=='SL']
    pk2=(sl.p_t_mfe_max/m<=2).mean()
    # exclude trivially dead (mfe<0.05) to see
    sl_alive=sl[sl.base_mfe>=0.2]; pk2a=(sl_alive.p_t_mfe_max/m<=2).mean()
    print(kind,tf,'dead_of_losers %.2f'%dead,'SL peak<=2bars %.2f'%pk2,'(SL with mfe>=0.2: %.2f n%d)'%(pk2a,len(sl_alive)),
          'med bars to SL %.1f'%(sl.base_hold/m).median(),'dead SL %.1f'%(sl[sl.base_mfe<0.2].base_hold/m).median(),
          'bars to .3R %.2f'%(g['p_t_0.3']/m).median(),'.5R %.2f'%(g['p_t_0.5']/m).median(),'reach1R %.2f'%g['p_t_1.0'].notna().mean(),
          'MAE before .5 %.2f'%g['p_mae_before_0.5'].median())
