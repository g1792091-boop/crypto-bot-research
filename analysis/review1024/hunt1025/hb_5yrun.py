"""5-year read of the in-sample best bots and V39 alone (same exits, sizing, costs)."""
import os, sys, json, time
import numpy as np, pandas as pd
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,HERE)
import hb_5y as H
EX=pd.read_csv(os.path.join(HERE,'out','exits.csv')); XID=dict(zip(EX.name,EX.exit))
MODE={'숏만':'S','롱만':'L','양방향':'B'}
def parse(s):
    cell,rest=s.split(' ',1); mode,filt,xn=rest.split(' · ',2); name,tf=cell.split('@')
    return name,tf,MODE[mode],filt,XID[xn]
r=json.load(open(os.path.join(HERE,'out','combo.json')))
BOTS={'V39 혼자 (1h 양방향, 손절 2ATR, 계단)':['V39_ALL@1h 양방향 · none · 손절 2ATR · 익절 없음 · 계단 12→10 / 5']}
for k in ['A/greedy/전체로 고름','A/top5/전체로 고름','A/top20/전체로 고름','B/greedy/전체로 고름']: BOTS[k]=r[k]['members']
out={}
t0=time.time()
for lab,mems in BOTS.items():
    T=[H.trades(*parse(m)) for m in mems]
    for m,Ti in zip(mems,T):
        out.setdefault('members',{})[m]={'n':len(Ti),'avg_w':round(float(Ti.w.mean()),4),'win':round(float((Ti.w>0).mean()),3),
            'x_2026':round(float(np.prod(1+Ti.w[Ti.t>=1767225600000-9*3600000])),3)}
    M=H.merge(T); M['w']=M.w.fillna(0)
    Y=H.by_period(M,'Y'); 
    last=M[M.t>=1767225600000-9*3600000]; Mo=H.by_period(last,'M')
    out[lab]={'years':{p:{'x':round(v.x,3),'n':int(v.n),'win':round(v.win,3)} for p,v in Y.iterrows()},
              '2026_months':{p:{'x':round(v.x,3),'n':int(v.n),'win':round(v.win,3)} for p,v in Mo.iterrows()},
              'n':len(M),'avg_w':round(float(M.w.mean()),4),'win':round(float((M.w>0).mean()),3)}
    print('==',lab,'trades',len(M),'avg wallet/trade',out[lab]['avg_w'],'win',out[lab]['win'],round(time.time()-t0),'s',flush=True)
    print('  years', {p:(v['x'],v['n']) for p,v in out[lab]['years'].items()})
    print('  2026 months', {p:(v['x'],v['n']) for p,v in out[lab]['2026_months'].items()},flush=True)
json.dump(out,open(os.path.join(HERE,'out','fiveyear.json'),'w'),ensure_ascii=False,indent=1)
