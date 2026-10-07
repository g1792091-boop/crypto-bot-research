# args: d3_shadows.csv replay_signals.csv out_csv
d=pd.read_csv(args[0]); P=pd.read_csv(args[1]); P=P[(P.run=='current')&(P.kind=='ds200')]
d['bc']=d.key.str.split('|').str[-1].astype('int64')
d=d[d.account_id.str.match(r'^F\d+_')]
rows=[]
P['account_id']=P.strategy+'@'+P.timeframe
for kind in ['skipped','limit']:
    x=d[d.kind==kind].merge(P[['account_id','symbol','bar_close','status','roe','R','stop_frac','leverage']],left_on=['account_id','symbol','bc'],right_on=['account_id','symbol','bar_close'],how='left')
    for tf,g in x.groupby('timeframe'):
        r={'kind':kind,'timeframe':tf,'rows':len(g),'matched_replay':int(g.status.notna().sum())}
        if kind=='skipped':
            b=g[(g.resolved==1)&g.roe_x.notna()&(g.status=='TRADED')]
            r.update(n_both=len(b),d3_mean_roe=b.roe_x.mean(),replay_mean_roe=b.roe_y.mean(),
                     abs_diff_median=(b.roe_x-b.roe_y).abs().median(),same_sign_share=float((np.sign(b.roe_x)==np.sign(b.roe_y)).mean()) if len(b) else np.nan)
        else:
            r['fill_rate']=float(g.filled.mean())
            b=g[(g.filled==1)&(g.resolved==1)&g.roe_x.notna()&(g.status=='TRADED')]
            r.update(n_both=len(b),limit_mean_roe=b.roe_x.mean(),market_replay_mean_roe_same=b.roe_y.mean(),
                     diff_roe=(b.roe_x-b.roe_y).mean(),
                     diff_R_approx=((b.roe_x-b.roe_y)/(b.leverage*b.stop_frac)).mean(),
                     unfilled_market_mean_roe=g[(g.filled==0)&(g.status=='TRADED')].roe_y.mean(),
                     unfilled_market_mean_R=g[(g.filled==0)&(g.status=='TRADED')].R.mean(),
                     n_unfilled_traded=int(((g.filled==0)&(g.status=='TRADED')).sum()))
        rows.append(r)
D=pd.DataFrame(rows); D.to_csv(args[2],index=False); print(D.round(4).to_string())
# totals in R units per signal (limit: filled -> limit R approx = limit roe/(lev*stop_frac); unfilled -> 0)
x=d[d.kind=='limit'].merge(P[['account_id','symbol','bar_close','status','roe','R','stop_frac','leverage']],left_on=['account_id','symbol','bc'],right_on=['account_id','symbol','bar_close'],how='left')
x=x[(x.status=='TRADED')&((x.filled==0)|((x.resolved==1)&x.roe_x.notna()))]
x['R_lim']=np.where(x.filled==1,x.roe_x/(x.leverage*x.stop_frac),0.0)
out=[]
for tf,g in x.groupby('timeframe'):
    out.append({'timeframe':tf,'signals':len(g),'fill_rate':g.filled.mean(),'market_R_per_signal':g.R.mean(),'limit_R_per_signal':g.R_lim.mean(),
                'limit_R_per_filled_trade':g.loc[g.filled==1,'R_lim'].mean(),'market_R_filled_subset':g.loc[g.filled==1,'R'].mean(),'market_R_unfilled_subset':g.loc[g.filled==0,'R'].mean()})
O2=pd.DataFrame(out); O2.to_csv(args[2].replace('.csv','_limitR.csv'),index=False); print(O2.round(3).to_string())
