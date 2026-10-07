import pandas as pd, numpy as np, json
O='/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens/fiveyear/out/'
TFM={'15m':15,'30m':30,'1h':60,'4h':240}; TFR={'4h':0,'1h':1,'30m':2,'15m':3}
T={'F16_FIB382':['15m','1h'],'F16_FIB500':['15m'],'F9_FVG':['15m','4h'],'N02_ST_KST':['15m','4h'],'N07_ICHI_CMO':['15m','30m','4h'],'N10_HA_PSAR':['30m'],
'F4_FAN':['15m','30m','4h'],'F7_RF_TRIPLE':['15m','30m','1h'],'DOGE':['1h'],'S2_ST_ROC':['15m','4h'],
'F9_IFVG':['15m','4h'],'N12_ICHI_AO':['15m','30m'],'N01_ST_EMA':['15m'],'V39_ALL':['15m','4h'],'N18_VWMA_MACD':['15m'],'N09_ALLIG_AROON':['15m','1h','4h'],'F6_VWAP_CROSS':['15m','4h'],'N24_DMI':['1h'],'N04_ST_KLINGER':['15m'],'N23_HA_ST':['1h','4h']}
need=set(T)
D=[]
for tf in TFM:
    for f in ('fy36','fyds'):
        x=pd.read_pickle(O+f'{f}_{tf}.pkl.gz'); x=x[x.strategy.astype(str).isin(need)&x.v4n_done]
        x=x[['strategy','coin','ts','side','stop_frac','v4n_R','v4n_gross','v4n_held']].copy(); x['tf']=tf; x['strategy']=x.strategy.astype(str); x['coin']=x.coin.astype(str); D.append(x)
D=pd.concat(D); D['g']=D.v4n_gross/D.stop_frac; D['t0']=D.ts//60_000_000_000; D['t1']=D.t0+D.v4n_held*D.tf.map(TFM)
days=1885.9; res={}; iv={}
for k,tfs in T.items():
    s=k.replace('_all','')
    x=D[(D.strategy==s)&D.tf.isin(tfs)].copy(); x['r']=x.tf.map(TFR)
    x=x.sort_values(['t0','r','stop_frac'],ascending=[True,True,False])
    busy=-1; take=[]
    for t0,t1 in zip(x.t0.to_numpy(),x.t1.to_numpy()):
        if t0>=busy: take.append(True); busy=t1
        else: take.append(False)
    y=x[np.array(take)]; iv[k]=y[['coin','side','t0','t1']].to_numpy()
    cut=pd.Timestamp('2024-07-01').value//60_000_000_000
    res[k]=dict(tfs=tfs,sig_day=round(len(x)/days,1),trades_day=round(len(y)/days,2),netR=round(y.v4n_R.mean(),3),grossR=round(y.g.mean(),4),
      gross_IS=round(y[y.t0<cut].g.mean(),4),gross_CF=round(y[y.t0>=cut].g.mean(),4),costR=round((y.g-y.v4n_R).mean(),3),
      se_wk=round(float(y.assign(w=y.t0//10080).groupby('w').g.agg(['sum','count']).pipe(lambda z: np.sqrt(((z['sum']-z['count']*y.g.mean())**2).sum())/z['count'].sum())),4),tf_mix={t:round((y.tf==t).mean(),2) for t in tfs},occupancy=round(((y.t1-y.t0).sum())/(days*1440),2))
for k,v in res.items(): print(k,json.dumps(v,default=float))
# position overlap among wave1
W=['F16_FIB382','F16_FIB500','F9_FVG','N02_ST_KST','N07_ICHI_CMO','N10_HA_PSAR','F4_FAN','F7_RF_TRIPLE','DOGE','S2_ST_ROC']
def ov(a,b):
    tot=0
    for coin in set(a[:,0]):
        A=a[a[:,0]==coin];B=b[b[:,0]==coin]
        for side in (1,-1):
            A2=A[A[:,1]==side];B2=B[B[:,1]==side]
            if len(A2)==0 or len(B2)==0: continue
            i=j=0;A2=A2[np.argsort(A2[:,2].astype(np.int64))];B2=B2[np.argsort(B2[:,2].astype(np.int64))]
            while i<len(A2) and j<len(B2):
                lo=max(A2[i,2],B2[j,2]);hi=min(A2[i,3],B2[j,3])
                if hi>lo: tot+=hi-lo
                if A2[i,3]<B2[j,3]: i+=1
                else: j+=1
    da=(a[:,3]-a[:,2]).sum(); db=(b[:,3]-b[:,2]).sum()
    return tot/min(da,db)
print('pos overlap (same coin+side concurrent / min held time):')
for i,a in enumerate(W):
    for b in W[i+1:]:
        o=ov(iv[a],iv[b])
        if o>=0.08: print(a,b,round(o,2))
