"""One sheet: the hopeful candidates on the same footing. Forward trades only (10/06-10/24), price return per trade net of each
source's own costs, one position per wallet. Wallet move per trade = exposure x price return."""
import json, numpy as np, pandas as pd
SP='/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad'
RV='/home/user/crypto-bot-research/analysis/review1024'
KST=9*3600*1000
A0=int(pd.Timestamp('2026-10-06 03:35').value//10**6)-KST; Z0=int(pd.Timestamp('2026-10-24 23:11').value//10**6)-KST
MID=int(pd.Timestamp('2026-10-15 13:23').value//10**6)-KST
T=pd.read_csv(f'{SP}/review1024_rb/data1024/current/trades.csv')
D=pd.read_csv(f'{SP}/review1024_rb/data1024/current/d3_shadows.csv')
def actual(acc):
    v=T[T.account_id==acc]; n=(v.qty*v.entry_price).abs()
    return pd.DataFrame({'t':v.entry_time.values,'x':v.exit_time.values,'r':(v.pnl/n).values,'side':v.side.values})
def shadow(acc,kind):
    v=D[(D.account_id==acc)&(D.kind==kind)&(D.resolved==1)&D.roe.notna()].copy()
    js=v.data.map(json.loads)
    return pd.DataFrame({'t':v.key.str.split('|').str[-1].astype('int64').values,'x':js.map(lambda d:d.get('exit_time')).values,
                         'r':(v.roe/js.map(lambda d:d.get('leverage'))).values,'side':v.side.values})
S=pd.read_csv(f'{RV}/combos/signals_sim.csv.gz')
def short_top3():
    m=(((S.strategy=='N24_DMI')&(S.tf=='4h'))|((S.strategy=='N06_MACD_ORB')&(S.tf=='15m'))|((S.strategy=='N09_ALLIG_AROON')&(S.tf=='1h')))&(S.side==-1)&S.ret_not.notna()
    v=S[m]; return pd.DataFrame({'t':v.bar_close.values+1,'x':v.exit_time.values,'r':v.ret_not.values,'side':v.side.values})
L=pd.read_csv(f'{RV}/league/trades_norm.csv')
def league(acc):
    v=L[L.account_id==acc]; return pd.DataFrame({'t':v.entry_ms.values,'x':v.exit_ms.values,'r':(v.return_on_margin/v.leverage).values,'side':v.side.values})
def roles(b):
    v=pd.read_csv(f'{RV}/roles/livebot/trades/trades_{b}.csv.gz'); v=v[v.period=='fwd']
    return pd.DataFrame({'t':v.t.values,'x':(v.t+v.tb_k*60000).values,'r':v.tb_r.values,'side':v.side.values})
def one_pos(df):
    df=df.dropna().sort_values('t'); out=[]; free=-1
    for row in df.itertuples():
        if row.t>=free and A0<=row.t<Z0: out.append(row); free=row.x
    return pd.DataFrame(out)
C={'V39_ALL@1h (실제 페이퍼)':actual('V39_ALL@1h'),
   'V39_ALL@1h + 첫 잠금 15% (그림자)':shadow('V39_ALL@1h','lock15'),
   'F9_FVG@1h + 고정 익절 1.5R (그림자)':shadow('F9_FVG@1h','tp1.5R'),
   'N13_3OUTSIDE@30m + 고정 익절 1.5R (그림자)':shadow('N13_3OUTSIDE@30m','tp1.5R'),
   'S3_CMO_SANDWICH@1h + 첫 잠금 30% (그림자)':shadow('S3_CMO_SANDWICH@1h','lock30'),
   'F2_DEMARK@30m + 고정 익절 3R (그림자)':shadow('F2_DEMARK@30m','tp3R'),
   '숏 전용 상위 3개 (조합)':short_top3(),
   '레인지필터 3중 1시간 + 익절 10% (리그, 10/13~)':league('ds-F7_RF_TRIPLE-1h-1-tp10'),
   'OBV 추세형 30분 ldv (리그, 10/13~)':league('core-OBV_S-30m-2-ldv'),
   '추세판단 봇 친구식 B3 (역할)':roles('B3'),
   '추세판단 봇 친구식 B6 (역할)':roles('B6')}
C['합침1: V39 + F9 익절1.5R']=pd.concat([C['V39_ALL@1h (실제 페이퍼)'],C['F9_FVG@1h + 고정 익절 1.5R (그림자)']])
C['합침2: V39 + F9 + N13 + S3']=pd.concat([C[k] for k in ('V39_ALL@1h (실제 페이퍼)','F9_FVG@1h + 고정 익절 1.5R (그림자)','N13_3OUTSIDE@30m + 고정 익절 1.5R (그림자)','S3_CMO_SANDWICH@1h + 첫 잠금 30% (그림자)')])
C['합침3: V39 + 숏 상위3']=pd.concat([C['V39_ALL@1h (실제 페이퍼)'],C['숏 전용 상위 3개 (조합)']])
C['합침4: V39 + F9 + 숏 상위3']=pd.concat([C[k] for k in ('V39_ALL@1h (실제 페이퍼)','F9_FVG@1h + 고정 익절 1.5R (그림자)','숏 전용 상위 3개 (조합)')])
rng=np.random.default_rng(20261025); N=20000
def sim(r,perday,E,floor=0.5,goal=6.0):
    lam=perday*30; reach=bust=0; ends=np.empty(N)
    ks=rng.poisson(lam,N); draws=rng.integers(0,len(r),size=(N,int(ks.max())+1))
    for i in range(N):
        eq=1.0
        for j in range(ks[i]):
            eq*=max(1+E*r[draws[i,j]],0.0)
            if eq>=goal: reach+=1; break
            if eq<=floor: bust+=1; break
        ends[i]=eq
    return reach/N,bust/N,float(np.median(ends))
rows=[]
for name,df in C.items():
    p=one_pos(df); 
    if len(p)==0: continue
    r=p.r.to_numpy(); days=(min(Z0,p.x.max())-max(A0,p.t.min()))/86400000; days=max(days,(Z0-max(A0,p.t.min()))/86400000)
    perday=len(r)/days
    eq12=np.cumprod(np.maximum(1+12*r,0)); real12=float(eq12[-1])
    h1=r[p.t.to_numpy()<MID]; h2=r[p.t.to_numpy()>=MID]
    row={'후보':name,'거래':len(r),'하루':round(perday,1),'승률':round((r>0).mean()*100),'거래당 가격%':round(r.mean()*100,3),
         '앞절반 거래당%':round(h1.mean()*100,3) if len(h1) else None,'뒤절반 거래당%':round(h2.mean()*100,3) if len(h2) else None,
         '롱/숏':f"{(p.side>0).sum()}/{(p.side<0).sum()}",'실제 기간 12배':round(real12,2)}
    for E in (9,12,15,20):
        a,b,m=sim(r,perday,E); row[f'{E}배 ×6/반토막/가운데']=f"{a*100:.0f}% / {b*100:.0f}% / ×{m:.1f}"
    if len(h2)>=5:
        a,b,m=sim(h2,perday,12); row['뒤절반만 12배']=f"{a*100:.0f}% / {b*100:.0f}% / ×{m:.1f}"
    rows.append(row); print(row, flush=True)
pd.DataFrame(rows).to_csv('onesheet.csv',index=False)
