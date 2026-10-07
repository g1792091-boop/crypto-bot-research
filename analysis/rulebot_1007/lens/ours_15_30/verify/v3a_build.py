"""My own v3a every-signal build (strategy kind, 15m/30m).
entered: raw trades.csv, R = pnl/(qty*|entry-stop_initial|)
skipped: d3_shadows 'skipped' ROE -> R = ROE/(lev*sf), lev from MY OWN tier-walk sizing (fresh $5,000)
usage: python3 -I v3a_build.py <export_dir> <out_dir>
"""
import os,sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import vlib
import json, math
import numpy as np, pandas as pd
E, OUT = sys.argv[1:3]
RUN='run-20261005T014624Z'
EQ=5000.0; TAKER=0.0005; SLIP=0.0002; MAXLOSS=0.15
BR = {  # (cap, maxlev, mmr, cum) -- bracket constants as inferred from export liq prices
    "BTCUSDT": [(1e12, 50, 0.004, 0.0)],
    "ETHUSDT": [(1e12, 50, 0.004, 0.0)],
    "SOLUSDT": [(50_000, 50, 0.005, 0.0), (1e12, 50, 0.0065, 75.0)],
    "DOGEUSDT": [(80_000, 50, 0.0065, 0.0), (1e12, 50, 0.01, 280.0)],
    "BCHUSDT": [(10_000, 50, 0.005, 0.0), (100_000, 50, 0.01, 50.0), (1e12, 40, 0.0125, 300.0)],
    "LTCUSDT": [(10_000, 50, 0.005, 0.0), (50_000, 50, 0.01, 50.0), (1e12, 40, 0.015, 300.0)],
}
CANDS=[(0.40,50),(0.40,40),(0.30,30),(0.20,20)]
tr=pd.read_csv(f'{E}/{RUN}/trades.csv')
# qty step per symbol from traded qty
STEP={}
for s,g in tr.groupby('symbol'):
    q=g.qty.to_numpy(float)
    for k in range(-2,9):
        if np.all(np.abs(q*10.0**k-np.round(q*10.0**k))<1e-6*np.maximum(1,q*10.0**k)):
            STEP[s]=10.0**-k; break
def bracket(sym,notional):
    for cap,ml,mmr,cum in BR[sym]:
        if notional<=cap: return ml,mmr,cum
    return BR[sym][-1][1:]
def size(sym, side, ref, atr, liq_mult):
    entry=ref*(1+side*SLIP); stop=ref-side*2*atr
    buf=max(0.002*entry, liq_mult*atr)
    for m,lev in CANDS:
        qty=math.floor(EQ*m*lev/entry/STEP[sym]+1e-9)*STEP[sym]
        notional=qty*entry; margin=notional/lev
        ml,mmr,cum=bracket(sym,notional)
        if lev>ml: continue
        liq=(margin+cum-side*qty*entry)/(qty*mmr-side*qty)
        if (stop-liq)*side<buf: continue
        exitp=stop*(1-side*SLIP)
        loss=qty*abs(entry-stop)+qty*abs(stop-exitp)+notional*TAKER+qty*exitp*TAKER
        if loss>MAXLOSS*EQ: continue
        return lev, entry, stop
    return np.nan, entry, stop
sig=pd.read_csv(f'{E}/{RUN}/signal_log.csv'); sig=sig[sig.status=='SUBMITTED']
sig['acct']=sig.strategy+'@'+sig.timeframe
sigk=sig.set_index(['acct','symbol','bar_close'])
d=pd.read_csv(f'{E}/{RUN}/d3_shadows.csv')
d['bc']=d.key.str.split('|').str[-1].astype('int64')
# ---- validation of my sizing on base rows (fresh-account leverage recorded)
val=[]
for liq_mult in (1.0,3.0):
    b=d[d.kind=='base']
    ok=tot=0
    for r in b.itertuples():
        k=(r.account_id,r.symbol,r.bc)
        if k not in sigk.index: continue
        s=sigk.loc[k]
        if isinstance(s,pd.DataFrame): s=s.iloc[0]
        lev,_,_=size(r.symbol,int(r.side),s.ref_price,s.atr,liq_mult)
        dd=json.loads(r.data); tot+=1; ok+= (lev==dd['leverage'])
    print('liq_mult',liq_mult,'base rows',tot,'lev match',ok, ok/tot)
LIQ=1.0
# ---- entered trades
tr['acct']=tr.account_id
tr=tr[~tr.account_id.str.startswith('RANDOM')]
tr['R']=tr.pnl/(tr.qty*(tr.entry_price-tr.stop_initial).abs())
tr['sf']=(tr.entry_price-tr.stop_initial).abs()/tr.entry_price
tr['bar_close']=tr.signal_ts+1
tr['strategy']=tr.account_id.str.split('@').str[0]; tr['tf']=tr.account_id.str.split('@').str[1]
ent=pd.DataFrame({'run':RUN,'strategy':tr.strategy,'tf':tr.tf,'symbol':tr.symbol,'bar_close':tr.bar_close,'side':tr.side,
   'src':'entered','R':tr.R,'lev':tr.leverage,'sf':tr.sf,'roe':tr.roe,'exit_reason':tr.exit_reason,'resolved':1})
# ---- skipped shadows
sk=d[(d.kind=='skipped')&~d.account_id.str.startswith('RANDOM')].copy()
rows=[]
miss=0
for r in sk.itertuples():
    k=(r.account_id,r.symbol,r.bc)
    if k not in sigk.index: miss+=1; lev=np.nan; sf=np.nan
    else:
        s=sigk.loc[k]
        if isinstance(s,pd.DataFrame): s=s.iloc[0]
        lev,en,st=size(r.symbol,int(r.side),s.ref_price,s.atr,LIQ); sf=abs(en-st)/en
    R=r.roe/(lev*sf) if (r.roe==r.roe and lev==lev) else np.nan
    st_,tf_=r.account_id.split('@')
    rows.append(dict(run=RUN,strategy=st_,tf=tf_,symbol=r.symbol,bar_close=r.bc,side=r.side,src='skipped',R=R,lev=lev,sf=sf,roe=r.roe,exit_reason=r.exit_reason,resolved=r.resolved))
SK=pd.DataFrame(rows)
print('skipped shadows not in signal_log:',miss)
A=pd.concat([ent,SK],ignore_index=True)
lo,hi=SK.bar_close.min(),SK.bar_close.max()
A['in_win']=(A.bar_close>=lo)&(A.bar_close<=hi)
A.to_csv(f'{OUT}/my_v3a_rows.csv',index=False)
x=A[A.tf.isin(['15m','30m'])]
print(x.groupby(['tf','src','in_win']).agg(n=('R','size'),nR=('R',lambda v:v.notna().sum()),unres=('resolved',lambda v:(v==0).sum()),meanR=('R','mean')))
print('unresolved skipped all tfs:',(SK.resolved==0).sum(), ' 15/30m:',((SK.resolved==0)&SK.tf.isin(['15m','30m'])).sum())
print('resolved no trade (roe nan):',((SK.resolved==1)&SK.roe.isna()).sum())
# coverage: outcomes SKIPPED in window vs shadows
o=pd.read_csv(f'{E}/{RUN}/outcomes.csv'); o=o[~o.account_id.str.startswith('RANDOM')]
o['bc']=o.sig_ts+1; o['tf']=o.account_id.str.split('@').str[1]
ow=o[(o.bc>=lo)&(o.bc<=hi)&o.tf.isin(['15m','30m'])]
print(ow.groupby(['tf','status']).size())
skk=set(zip(SK.strategy+'@'+SK.tf,SK.symbol,SK.bar_close))
ows=ow[ow.status=='SKIPPED']
cov=np.mean([ (a,s,b) in skk for a,s,b in zip(ows.account_id,ows.symbol,ows.bc)])
print('share of SKIPPED outcomes in window with a shadow row:',cov, len(ows))
