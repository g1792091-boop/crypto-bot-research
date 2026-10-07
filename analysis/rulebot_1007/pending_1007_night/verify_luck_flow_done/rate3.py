import sys; exec(open(sys.argv[0].rsplit("/",1)[0]+"/h.py").read())
import json
P=json.load(open('/home/user/crypto-bot-research/research/strategy_profiles/out_binance/profiles.json'))['profiles']
A=pd.read_csv(sys.argv[0].rsplit("/",1)[0]+'/flow_accounts3.csv')
A=A[A.kind=='strategy']
g=A.groupby(['strategy','timeframe']).agg(sub=('sub','sum'),days=('days','sum')).reset_index()
g['live']=g['sub']/g.days
g['y5']=[P.get(s,{}).get(tf,{}).get('signals_per_day',np.nan) for s,tf in zip(g.strategy,g.timeframe)]
g['ratio']=g.live/g.y5
for tf in ['5m','15m','30m','1h','4h']:
    x=g[(g.timeframe==tf)&(g.y5>0)]
    print(tf, 'n',len(x),'median ratio',round(x.ratio.median(),3),'sum live/sum5y', round(x.live.sum()/x.y5.sum(),3))
x=g[(g.y5>0)&(g.live>0)&(g.timeframe!='5m')]
print('core no5m cells',len(x),'median',x.ratio.median(), 'IQR',x.ratio.quantile([.25,.75]).tolist(),'logcorr',np.corrcoef(np.log(x.live),np.log(x.y5))[0,1])
for s in ['N21_ST_RSI_ADX','N14_ICHI_RSI','N15_KC_AO','S1_EMA_RSI_CHOP','N11_BREAKAWAY','N08_ICHI_WR','S5_DONCHIAN_MFI']:
    print(s, {tf:(P.get(s,{}).get(tf,{}).get('signals'), round(P.get(s,{}).get(tf,{}).get('signals_per_day',np.nan),3)) for tf in ['15m','30m','1h','4h']}, 'live', g[g.strategy==s][['timeframe','sub','live']].round(2).values.tolist())
print('coins in 5y?', P['meta'] if 'meta' in P else '')
