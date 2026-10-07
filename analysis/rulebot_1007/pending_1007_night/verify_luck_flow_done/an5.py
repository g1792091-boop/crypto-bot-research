import sys; exec(open(sys.argv[0].rsplit("/",1)[0]+"/h.py").read())
OUT=sys.argv[0].rsplit("/",1)[0]
o=pd.concat([rd(r,'outcomes.csv').assign(run=r).merge(rd(r,'accounts.csv')[['account_id','kind']],on='account_id') for r in ['v3b','v4']])
o['k']=(o.ref_price-o.sig_stop_price).abs()/o.sig_atr; o['sdpct']=(o.ref_price-o.sig_stop_price).abs()/o.ref_price*100
print(o[o.sig_timeframe!='5m'].groupby(['kind','sig_timeframe'])[['k','sdpct']].median().round(3).to_string())
print(o[(o.kind=='strategy')&(o.k>2.2)][['run','account_id','sig_atr','ref_price','sig_stop_price','stop_dist']].head(5).to_string())
sg=pd.read_csv(f'{OUT}/sig3.csv'); cf=pd.read_csv(f'{OUT}/cf3.csv')
for tf in ['15m','30m','1h','4h']:
    a=sg[(sg.tf==tf)&(sg.st=='T')&(sg.kind=='strategy')]
    print(tf,'strategy sig: cost',round(a.cost_R.mean(),3),'both-sides R',round(a.R.mean(),3), a.groupby('run').R.mean().round(3).to_dict())
