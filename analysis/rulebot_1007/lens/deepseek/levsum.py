# summarize lev_replay_signals.csv: args = [lev_replay_signals.csv, replay_signals.csv(pipeline), out_csv]
L=pd.read_csv(args[0]); P=pd.read_csv(args[1]); P=P[(P.kind=='ds200')&(P.run=='current')]
# parity: L=30 vs pipeline where pipeline leverage==30
m=L[L.lev_fixed==30].merge(P[['sig_id','status','R','leverage','roe']],on='sig_id',suffixes=('','_p'))
mm=m[(m.status_p=='TRADED')&(m.leverage_p==30)]
print('parity n',len(mm),'traded both',(mm.status=='TRADED').sum(),'max|dR|',(mm.R-mm.R_p).abs().max())
print('pipeline 30x traded but fixed30 rejected:', ((m.status_p=='TRADED')&(m.leverage_p==30)&(m.status!='TRADED')).sum(),
      'pipeline 20x (fell from 30):', (m.leverage_p==20).sum())
L['fam']=L.strategy.str.split('_').str[0]
# value per signal: R if traded, mark_R if unresolved
L['Rv']=np.where(L.status=='TRADED',L.R,np.where(L.status=='UNRESOLVED',L.mark_R,np.nan))
L['ROEv']=np.where(L.status=='TRADED',L.roe,np.where(L.status=='UNRESOLVED',L.mark_roe,np.nan))
rows=[]
for tf,g in L.groupby('timeframe'):
    w=g.pivot_table(index="sig_id",columns="lev_fixed",values="Rv").reindex(columns=[10,20,30,40,50])
    wr=g.pivot_table(index="sig_id",columns="lev_fixed",values="ROEv").reindex(columns=[10,20,30,40,50])
    st=g.pivot_table(index='sig_id',columns='lev_fixed',values='status',aggfunc='first')
    for lev in sorted(g.lev_fixed.unique()):
        x=g[g.lev_fixed==lev]
        rows.append({'timeframe':tf,'lev':lev,'signals':len(x),'entered_share':float(x.status.isin(['TRADED','UNRESOLVED']).mean()),
                     'n_valued':int(x.Rv.notna().sum()),'mean_R_all_entered':x.Rv.mean(),'mean_ROE_all_entered':x.ROEv.mean(),
                     'lock_share':float((x.exit_reason=='LOCK').sum()/max(1,(x.status=='TRADED').sum())),
                     'win_pct':100*float((x.Rv>0).sum()/max(1,x.Rv.notna().sum()))})
    # common set: signals entered at 10,20,30
    cs=w[[10,20,30]].dropna()
    for lev in [10,20,30]:
        rows.append({'timeframe':tf,'lev':lev,'basis':'common_10_20_30','n_valued':len(cs),'mean_R_all_entered':cs[lev].mean(),
                     'mean_ROE_all_entered':wr.loc[cs.index,lev].mean()})
    cs4=w[[10,20,30,40]].dropna()
    for lev in [10,20,30,40]:
        rows.append({'timeframe':tf,'lev':lev,'basis':'common_10_20_30_40','n_valued':len(cs4),'mean_R_all_entered':cs4[lev].mean(),
                     'mean_ROE_all_entered':wr.loc[cs4.index,lev].mean()})
    cs5=w[[10,20,30,40,50]].dropna()
    for lev in [10,20,30,40,50]:
        rows.append({'timeframe':tf,'lev':lev,'basis':'common_all5','n_valued':len(cs5),'mean_R_all_entered':cs5[lev].mean(),
                     'mean_ROE_all_entered':wr.loc[cs5.index,lev].mean()})
S=pd.DataFrame(rows); S['basis']=S['basis'].fillna('own_entered')
S.to_csv(args[2],index=False)
print(S.round(4).to_string())
# rejection reasons at 40/50
for lev in [40,50]:
    x=L[(L.lev_fixed==lev)&(L.status=='REJECTED_SIZING')]
    r=x.reject_reasons.astype(str)
    print(lev, 'loss>15%:', r.str.contains('of equity').sum(), 'liq:', r.str.contains('too close to liq').sum(), 'bracket:', r.str.contains('bracket').sum(), 'n',len(x))
    print(x.groupby('timeframe').size().to_dict(), L[L.lev_fixed==lev].groupby('timeframe').size().to_dict())
