import os, sys, json
import numpy as np, pandas as pd
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,HERE)
import hb_5y as H
exec(open(os.path.join(HERE,'hb_roll2.py')).read().split("r=json.load")[0])
r=json.load(open(os.path.join(HERE,'out','combo.json')))
A6=r['A/greedy/전체로 고름']['members']; A5=[m for m in A6 if not m.startswith('F7_RF_ONLY')]
out={}
for lab,mems in (('A안 6개',A6),('A안에서 F7_RF_ONLY 뺀 5개',A5)):
    T=[H.trades(*parse(m)) for m in mems]
    for lab2,TT in ((lab,T),(lab+' + BTC추세 같은 방향만',[x[btc_ok(x)] for x in T])):
        M=H.merge(TT); f=M[(M.t>=ms('2026-10-05 15:00'))&(M.t<ms('2026-10-24 14:12'))]; mid=ms('2026-10-15 03:00')
        q=np.linspace(ms('2026-10-05 15:00'),ms('2026-10-24 14:12'),5)
        o={'19일':round(float(np.prod(1+f.w)),2),'앞':round(float(np.prod(1+f.w[f.t<mid])),2),'뒤':round(float(np.prod(1+f.w[f.t>=mid])),2),
           '4구간':[round(float(np.prod(1+f.w[(f.t>=q[i])&(f.t<q[i+1])])),2) for i in range(4)],
           'n19':len(f),'win19':round(float((f.w>0).mean()),3),'숏':int((f.side<0).sum()),'dd19':round(float((np.cumprod(1+f.w)/np.maximum.accumulate(np.cumprod(1+f.w))-1).min()),2)}
        for fl in (0.5,0.7):
            o[f'2026 1~9월 시작 (멈춤 {fl})']=roll(M,ms('2026-01-01'),ms('2026-09-25'),fl)
            o[f'2020~2025 시작 (멈춤 {fl})']=roll(M,ms('2020-03-01'),ms('2025-12-02'),fl)
        o['10월 1~4일 시작']=roll(M,ms('2026-10-01'),ms('2026-10-05'),0.5)
        mo=H.by_period(M[M.t>=ms('2026-01-01')],'M'); o['2026월별']={p:round(v.x,2) for p,v in mo.iterrows()}
        f.to_csv(os.path.join(HERE,'out',f'trades19_{len(out)}.csv'),index=False)
        out[lab2]=o; print(lab2,o,flush=True)
json.dump(out,open(os.path.join(HERE,'out','final_variants.json'),'w'),ensure_ascii=False,indent=1)
