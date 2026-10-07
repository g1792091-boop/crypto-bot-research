import sys; exec(open(sys.argv[0].rsplit("/",1)[0]+"/h.py").read())
OUT=sys.argv[0].rsplit("/",1)[0]
sg=pd.read_csv(f'{OUT}/sig3.csv'); cf=pd.read_csv(f'{OUT}/cf3.csv')
for tf in ['15m','30m','1h','4h']:
    a=sg[(sg.tf==tf)&(sg.st=='T')]; b=cf[(cf.tf==tf)&(cf.st=='T')]
    print(tf,'sig: cost',round(a.cost_R.mean(),3),'both-sides mean R',round(a.R.mean(),3),'| by run', a.groupby('run').R.mean().round(3).to_dict(), 'n',a.groupby('run').size().to_dict(),
          '|| CF cost',round(b.cost_R.mean(),3),'R',round(b.R.mean(),3),'by run',b.groupby('run').R.mean().round(3).to_dict(),'n',b.groupby('run').size().to_dict())
print(cf[(cf.tf=='4h')&(cf.st=='T')].groupby(['run','side']).R.agg(['mean','size']).round(3).to_string())
# stop distance in ATR for signals
o=pd.concat([rd(r,'outcomes.csv').assign(run=r) for r in ['v3b','v4']])
o['k']=(o.ref_price-o.sig_stop_price).abs()/o.sig_atr
print('stop/ATR by tf', o[o.sig_timeframe!='5m'].groupby('sig_timeframe').k.describe()[['mean','25%','50%','75%']].round(2).to_string())
