"""Historic goal odds: start the bot on every day 2020-03 .. 2026-09 and run 30 days (stop at x5 / x6 or -50 %)."""
import os, sys, json
import numpy as np, pandas as pd
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,HERE)
import hb_5y as H
exec(open(os.path.join(HERE,'hb_5yrun.py')).read().split('out={}')[0])
BOTS['V39 + 숏 전용 3 (하우스 청산)']=['V39_ALL@1h 양방향 · none · 손절 2ATR · 익절 없음 · 계단 12→10 / 5',
  'N24_DMI@4h 숏만 · none · 손절 2ATR · 익절 없음 · 계단 12→10 / 5','N06_MACD_ORB@15m 숏만 · none · 손절 2ATR · 익절 없음 · 계단 12→10 / 5',
  'N09_ALLIG_AROON@1h 숏만 · none · 손절 2ATR · 익절 없음 · 계단 12→10 / 5']
DAY=86400000
def roll(M, a, b):
    t=M.t.to_numpy(); w=M.w.fillna(0).to_numpy(); res=[]
    for s in range(a, b, DAY):
        i=np.searchsorted(t,s); eq=1.0; hit5=hit6=bust=False
        while i<len(t) and t[i]<s+30*DAY:
            eq*=1+w[i]; i+=1
            if eq>=5 and not hit5: hit5=True
            if eq>=6: hit6=True; break
            if eq<=0.5: bust=True; break
        res.append((hit5,hit6,bust and not hit5,eq))
    R=np.array(res,dtype=float)
    return {'starts':len(R),'x5':round(R[:,0].mean(),3),'x6':round(R[:,1].mean(),3),'half_first':round(R[:,2].mean(),3),'median_end':round(float(np.median(R[:,3])),3)}
from common import ms
out={}
for lab,mems in BOTS.items():
    M=H.merge([H.trades(*parse(m)) for m in mems])
    out[lab]={'2020-03~2025-12':roll(M,ms('2020-03-01'),ms('2025-12-02')),'2026-01~09':roll(M,ms('2026-01-01'),ms('2026-09-25')),
              '10월 시작(10/01~10/24, 끝까지 못 감)':roll(M,ms('2026-10-01'),ms('2026-10-05'))}
    print(lab, out[lab], flush=True)
json.dump(out,open(os.path.join(HERE,'out','roll.json'),'w'),ensure_ascii=False,indent=1)
