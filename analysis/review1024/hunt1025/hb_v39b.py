import os, sys, json
import numpy as np, pandas as pd
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,HERE)
import hb_5y as H
exec(open(os.path.join(HERE,'hb_roll2.py')).read().split("r=json.load")[0])
r=json.load(open(os.path.join(HERE,'out','combo.json')))
RAID=['F11_RAID@15m 숏만 · V39마지막신호@1h · 손절 ROE -50% · 익절 없음 · 계단 12→10 / 5']
RAID2=RAID+['F13_RAID_PD@15m 숏만 · V39마지막신호@1h · 손절 ROE -50% · 익절 없음 · 계단 12→10 / 5',
            'C1_ENGULF@1h 숏만 · V39마지막신호@4h · 손절 ROE -75% · 익절 없음 · 계단 12→10 / 5']
out={}
for lab,mems in (('F11_RAID 15분 숏 + V3.9 1시간 마지막 신호',RAID),('위 + F13_RAID_PD + C1_ENGULF(V3.9 4시간)',RAID2),
                 ('A안 6개 + F11_RAID(V3.9)',r['A/greedy/전체로 고름']['members']+RAID)):
    M=H.merge([H.trades(*parse(m)) for m in mems])
    f=M[(M.t>=ms('2026-10-05 15:00'))&(M.t<ms('2026-10-24 14:12'))]; mid=ms('2026-10-15 03:00')
    o={'19일':round(float(np.prod(1+f.w)),2),'앞':round(float(np.prod(1+f.w[f.t<mid])),2),'뒤':round(float(np.prod(1+f.w[f.t>=mid])),2),
       'n19':len(f),'win19':round(float((f.w>0).mean()),3),'5년 거래':len(M),'5년 승률':round(float((M.w>0).mean()),3),
       '5년 거래당 지갑':round(float(M.w.mean()),4)}
    for fl in (0.5,0.7):
        o[f'2026 1~9월 시작 (멈춤 {fl})']=roll(M,ms('2026-01-01'),ms('2026-09-25'),fl)
        o[f'2020~2025 시작 (멈춤 {fl})']=roll(M,ms('2020-03-01'),ms('2025-12-02'),fl)
    mo=H.by_period(M[M.t>=ms('2026-01-01')],'M'); o['2026월별']={p:(round(v.x,2),int(v.n)) for p,v in mo.iterrows()}
    y=H.by_period(M,'Y'); o['연도별']={p:(round(v.x,3),int(v.n),round(v.win,2)) for p,v in y.iterrows()}
    out[lab]=o; print(lab,o,flush=True)
json.dump(out,open(os.path.join(HERE,'out','v39_5y.json'),'w'),ensure_ascii=False,indent=1)
