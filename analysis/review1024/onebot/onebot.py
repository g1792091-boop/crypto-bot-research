"""One combo bot (one wallet, one position) built from the rule bot's replayed forward signals (combos/signals_sim.csv.gz:
every 15m-4h signal 10/06-10/24 with the house exit: 2 ATR stop + ladder, rule-bot costs). Member = strategy@tf x side mode."""
import numpy as np, pandas as pd, itertools, json
RV='/home/user/crypto-bot-research/analysis/review1024'
KST=9*3600*1000
A0=int(pd.Timestamp('2026-10-06 03:35').value//10**6)-KST; Z0=int(pd.Timestamp('2026-10-24 23:11').value//10**6)-KST
MID=int(pd.Timestamp('2026-10-15 13:23').value//10**6)-KST
TFM={'15m':15,'30m':30,'1h':60,'4h':240}
S=pd.read_csv(f'{RV}/combos/signals_sim.csv.gz')
S=S[S.ret_not.notna()&S.exit_time.notna()&S.tf.isin(TFM)].copy()
S['t']=S.bar_close.astype('int64')+1; S['x']=S.exit_time.astype('int64'); S['r']=S.ret_not.astype(float)
S=S[(S.t>=A0)&(S.t<Z0)]
S['cell']=S.strategy+'@'+S.tf; S['tfm']=S.tf.map(TFM)
S=S.sort_values(['t','tfm'],ascending=[True,False]).reset_index(drop=True)
E=12.0
cells=sorted(S.cell.unique())
idx={c:np.flatnonzero((S.cell==c).to_numpy()) for c in cells}
side=S.side.to_numpy(); t=S.t.to_numpy(); x=S.x.to_numpy(); r=S.r.to_numpy()
def rows_of(member):
    c,mode=member; i=idx[c]
    if mode=='S': i=i[side[i]<0]
    elif mode=='L': i=i[side[i]>0]
    return i
def run(members,a=A0,z=Z0):
    if not members: return 1.0,0.0,0,[]
    ii=np.sort(np.concatenate([rows_of(m) for m in members])); free=-1; eq=1.0; peak=1.0; dd=0.0; took=[]
    for i in ii:
        if t[i]<a or t[i]>=z or t[i]<free: continue
        eq*=max(1+E*r[i],0.0); free=x[i]; took.append(i)
        peak=max(peak,eq); dd=min(dd,eq/peak-1)
    return eq,dd,len(took),took
members_all=[(c,m) for c in cells for m in ('B','S','L')]
def solo(m,a,z):
    eq,dd,n,_=run([m],a,z); return eq,n
def greedy(a,z,min_n=4,max_k=8):
    cand=[m for m in members_all if solo(m,a,z)[1]>=min_n]
    chosen=[]; best=1.0
    for _ in range(max_k):
        top=None
        for m in cand:
            if any(m[0]==c[0] for c in chosen): continue
            eq,dd,n,_=run(chosen+[m],a,z)
            if eq>best*1.02 and (top is None or eq>top[0]): top=(eq,m)
        if top is None: break
        best,m=top; chosen.append(m)
    return chosen,best
def report(name,members):
    out={'name':name,'members':[f"{c} {'숏만' if m=='S' else ('롱만' if m=='L' else '양방향')}" for c,m in members]}
    for wn,(a,z) in {'19일':(A0,Z0),'앞절반':(A0,MID),'뒤절반':(MID,Z0)}.items():
        eq,dd,n,took=run(members,a,z)
        out[wn]={'x':round(eq,2),'dd':round(dd,2),'n':n,'win':round(float((r[took]>0).mean()),2) if n else None,
                 'short':int((side[took]<0).sum()) if n else 0}
    return out
res=[]
# (1) whole-window greedy (after the fact)
g_all,_=greedy(A0,Z0); res.append(report('① 19일 전체로 고른 최적(사후)',g_all))
# (2) robust rule: every member positive alone in BOTH halves with >=3 trades each, side mode chosen the same way
rob=[]
for c in cells:
    best=None
    for mode in ('B','S','L'):
        e1,n1=solo((c,mode),A0,MID); e2,n2=solo((c,mode),MID,Z0)
        if n1>=3 and n2>=3 and e1>1 and e2>1:
            score=min(e1,e2)
            if best is None or score>best[0]: best=(score,(c,mode))
    if best: rob.append(best)
rob.sort(reverse=True)
for k in (3,5,8,len(rob)):
    res.append(report(f'② 두 절반 모두 플러스인 멤버 상위 {k}개',[m for _,m in rob[:k]]))
# (3) honest check: greedy on first half, read second half; and the reverse
g1,_=greedy(A0,MID); res.append(report('③ 앞 절반으로 고름 → 뒤 절반이 확인',g1))
g2,_=greedy(MID,Z0); res.append(report('④ 뒤 절반으로 고름 → 앞 절반이 확인',g2))
# references
res.append(report('참고: V39_ALL@1h 혼자',[('V39_ALL@1h','B')]))
res.append(report('참고: V39 + 숏 전용 상위 3개',[('V39_ALL@1h','B'),('N24_DMI@4h','S'),('N06_MACD_ORB@15m','S'),('N09_ALLIG_AROON@1h','S')]))
res.append(report('참고: 지금 추세판단 봇 멤버 18개(규칙봇 신호·하우스 청산)',[(f"{m['strategy']}@{m['tf']}",'B') for m in json.load(open('/home/user/crypto-bot-research/deploy/combo.trend.json'))['members'] if f"{m['strategy']}@{m['tf']}" in idx]))
json.dump({'rob_count':len(rob),'rob':[(c,m,round(s,2)) for s,(c,m) in rob],'res':res},open('onebot.json','w'),ensure_ascii=False,indent=1)
for o in res:
    print(o['name']); print('   멤버:',', '.join(o['members']))
    for w in ('19일','앞절반','뒤절반'): print('  ',w,o[w])
print('두 절반 모두 플러스인 멤버 수:',len(rob)); print([(c,m,round(s,2)) for s,(c,m) in rob[:15]])
