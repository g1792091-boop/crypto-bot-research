"""A/greedy (runs today) with a BTC-trend condition (combined bot when btc_trend "with": the last closed BTC 4h close vs
EMA50 agrees with the side) and with a quit rule (stop the bot at -30 % / -40 %): 19 days, 2026 months, rolling odds."""
import os, sys, json
import numpy as np, pandas as pd
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,HERE)
import hb_5y as H
exec(open(os.path.join(HERE,'hb_5yrun.py')).read().split('out={}')[0])
from common import ms, bars
b=bars('BTCUSDT','4h'); ema=b.close.ewm(span=50,adjust=False).mean().to_numpy(); sgn=np.sign(b.close.to_numpy()-ema)
close_t=b.ts.to_numpy()+4*3600000
def btc_ok(T):
    j=np.searchsorted(close_t,T.t.to_numpy(),side='right')-1
    return sgn[np.clip(j,0,None)]==T.side.to_numpy()
DAY=86400000
def roll(M,a,b_,floor=0.5,goal=5):
    t=M.t.to_numpy(); w=M.w.fillna(0).to_numpy(); res=[]
    for s in range(a,b_,DAY):
        i=np.searchsorted(t,s); eq=1.0; r=0
        while i<len(t) and t[i]<s+30*DAY:
            eq*=1+w[i]; i+=1
            if eq>=goal: r=1; break
            if eq<=floor: r=-1; break
        res.append((r,eq))
    R=np.array(res); return {'goal':round(float((R[:,0]==1).mean()),3),'floor':round(float((R[:,0]==-1).mean()),3),'median_end':round(float(np.median(R[:,1])),3)}
r=json.load(open(os.path.join(HERE,'out','combo.json')))
out={}
for key in ['A/greedy/전체로 고름','A/top5/전체로 고름','B/greedy/전체로 고름']:
    T=[H.trades(*parse(m)) for m in r[key]['members']]
    for lab,TT in ((key,T),(key+' + BTC추세 같은 방향만',[x[btc_ok(x)] for x in T])):
        M=H.merge(TT)
        f=M[(M.t>=ms('2026-10-05 15:00'))&(M.t<ms('2026-10-24 14:12'))]
        mid=ms('2026-10-15 03:00')
        o={'19일':round(float(np.prod(1+f.w)),2),'앞':round(float(np.prod(1+f.w[f.t<mid])),2),'뒤':round(float(np.prod(1+f.w[f.t>=mid])),2),'n19':len(f)}
        for fl in (0.5,0.6,0.7):
            o[f'2026 1~9월 시작 (멈춤 {fl})']=roll(M,ms('2026-01-01'),ms('2026-09-25'),fl)
            o[f'2020~2025 시작 (멈춤 {fl})']=roll(M,ms('2020-03-01'),ms('2025-12-02'),fl)
        mo=H.by_period(M[M.t>=ms('2026-01-01')],'M'); o['2026월별']={p:round(v.x,2) for p,v in mo.iterrows()}
        out[lab]=o; print(lab,o,flush=True)
json.dump(out,open(os.path.join(HERE,'out','roll2.json'),'w'),ensure_ascii=False,indent=1)
