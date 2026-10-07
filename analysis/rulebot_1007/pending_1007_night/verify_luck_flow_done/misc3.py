import sys; exec(open(sys.argv[0].rsplit("/",1)[0]+"/h.py").read())
OUT=sys.argv[0].rsplit("/",1)[0]; rng=np.random.default_rng(5)
SY=['BTCUSDT','ETHUSDT','SOLUSDT','DOGEUSDT','LTCUSDT','BCHUSDT']
for run in RUNS:
    s=rd(run,'signal_log.csv'); s=s[s.symbol.isin(SY)].sort_values('ref_time')
    f=s.groupby('symbol').ref_price.first(); l=s.groupby('symbol').ref_price.last(); r1=(l/f-1)*100
    msg=f'{run} siglog EW {r1.mean():.2f}% '+str(r1.round(2).to_dict())
    if run!='v3a':
        b=rd(run,'live_bars.csv').sort_values('ts'); b=b[b.symbol.isin(SY)]
        r2=(b.groupby('symbol').close.last()/b.groupby('symbol').open.first()-1)*100; msg+=f' | bars EW {r2.mean():.2f}% '+str(r2.round(2).to_dict())
    print(msg)
# duplicates in v4 signal streams
s=rd('v4','signal_log.csv'); s=s[s.status=='SUBMITTED']
def key(st,tf): x=s[(s.strategy==st)&(s.timeframe==tf)]; return set(zip(x.bar_close,x.symbol,x.side))
def comp(a,b,tf):
    A,Bb=key(a,tf),key(b,tf); u=len(A|Bb); print(f'{a} vs {b} @{tf}: n {len(A)}/{len(Bb)} jaccard {len(A&Bb)/u if u else float("nan"):.2f}')
comp('F11_RAID','F11_TSOUP','15m'); comp('F11_RAID','F13_RAID_PD','15m'); comp('F17_Z','F17_Z_HL','1h'); comp('F17_Z','F17_Z_HL','15m'); comp('F5_BOX','F5_BOX_HTF','15m'); comp('F5_BOX','F5_BOX_HTF','30m'); comp('F11_RAID','F13_RAID_PD','1h'); comp('F10_OTE','F16_FIB618','4h')
x=s[s.strategy=='F15_OPEN0000']; print('F15_OPEN0000 per tf', x.groupby('timeframe').apply(lambda g: sorted(set(zip(g.symbol,g.side)))[:3]).to_dict() if len(x) else 'none', x.groupby('timeframe').size().to_dict())
# luck band: 50 trades from exhaustive 15m CF, block-clustered (2 trades per random 4h block, 25 blocks)
cf=pd.read_csv(f'{OUT}/cf3.csv'); t=cf[(cf.tf=='15m')&(cf.st=='T')].copy(); t['blk']=t.bc//(4*3600000)
G=[g.R.to_numpy() for _,g in t.groupby(['run','blk'])]
ms=np.array([np.concatenate([rng.choice(G[k],2) for k in rng.integers(0,len(G),25)]).mean() for _ in range(5000)])
print('15m CF 50-trade band', np.percentile(ms,[2.5,50,97.5]).round(3), 'P(>=0.099)', (ms>=0.099).mean().round(3))
iid=np.array([rng.choice(t.R.to_numpy(),50).mean() for _ in range(5000)]); print('iid band',np.percentile(iid,[2.5,97.5]).round(3),'P',(iid>=0.099).mean().round(3))
