import os, sys, json
import numpy as np, pandas as pd
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,HERE)
import hb_5y as H
exec(open(os.path.join(HERE,'hb_roll2.py')).read().split("r=json.load")[0])
r=json.load(open(os.path.join(HERE,'out','combo.json')))
A6=r['A/greedy/전체로 고름']['members']; A5=[m for m in A6 if not m.startswith('F7_RF_ONLY')]
V3=['V39_ALL@1h 양방향 · none · 손절 2ATR · 익절 없음 · 계단 12→10 / 5','N24_DMI@4h 숏만 · none · 손절 2ATR · 익절 없음 · 계단 12→10 / 5',
    'N06_MACD_ORB@15m 숏만 · none · 손절 2ATR · 익절 없음 · 계단 12→10 / 5','N09_ALLIG_AROON@1h 숏만 · none · 손절 2ATR · 익절 없음 · 계단 12→10 / 5']
for lab,mems,btc in (('A5',A5,False),('A6+BTC',A6,True),('V39+short3',V3,False)):
    T=[H.trades(*parse(m)) for m in mems]
    if btc: T=[x[btc_ok(x)] for x in T]
    M=H.merge(T); y=H.by_period(M,'Y')
    print(lab,'5y win',round(float((M.w>0).mean()),3),'avg',round(float(M.w.mean()),4),'n',len(M),{p:round(v.x,4) for p,v in y.iterrows()})
