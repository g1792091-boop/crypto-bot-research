import sys,site; sys.path.append(site.getusersitepackages())
import pandas as pd, numpy as np
X=sys.argv[1]; T=pd.read_csv(sys.argv[2])
H=3600000
# NFP v3a
t=T[(T.run=='run-20261005T014624Z')&T.kind.isin(['strategy','ds200','random'])]
nfp=pd.Timestamp('2026-10-02T12:30:00Z').value//10**6
print('v3a first entry KST', pd.to_datetime(t.entry_time.min(),unit='ms')+pd.Timedelta(hours=9))
for lab,m in [('entered [nfp-2h,nfp+2h]',(t.entry_time>=nfp-2*H)&(t.entry_time<nfp+2*H)),('entered [nfp,nfp+2h)',(t.entry_time>=nfp)&(t.entry_time<nfp+2*H)),('held through',(t.entry_time<nfp)&(t.exit_time>=nfp)),('entered first 3.4h of run',(t.entry_time<t.entry_time.min()+3.4*H)),('other',~((t.entry_time>=nfp-2*H)&(t.entry_time<nfp+2*H)))]:
    g=t[m]; print(lab,len(g),round(g.R.mean(),3),'excl 5m',len(g[g.timeframe!='5m']),round(g[g.timeframe!='5m'].R.mean(),3))
# big hours from live bars
V=pd.read_csv('vr_signals.csv'); V=V[V.base_st.isin(['TRADED','OPEN'])]
for run in ['run-20261005T183457Z','current']:
    b=pd.read_csv(f'{X}/{run}/live_bars.csv',usecols=['ts','symbol','open','close'])
    b['h']=b.ts//H*H
    hh=b.sort_values('ts').groupby(['symbol','h']).agg(o=('open','first'),c=('close','last'),n=('ts','size')).reset_index()
    hh=hh[hh.n>=50]; hh['r']=hh.c/hh.o-1
    syms=hh.symbol.value_counts(); 
    ew=hh.groupby('h').agg(r=('r','mean'),k=('symbol','size'))
    ew=ew[ew.k>=ew.k.max()-1]
    thr=ew.r.abs().quantile(0.9); big=set(ew.index[ew.r.abs()>=thr])
    print(run,'coins',len(syms),'hours',len(ew),'big',sorted([(pd.to_datetime(x,unit='ms')+pd.Timedelta(hours=9)).strftime('%m/%d %H:%M')+f' {ew.r[x]:+.4f}' for x in big]))
    for kind in ['strategy','ds200']:
        g=V[(V.run==run)&(V.kind==kind)].copy()
        if not len(g): continue
        # signal bar_close falls in hour h -> entry in hour h
        g['h']=(g.bar_close)//H*H
        inb=g.h.isin(big); after=(g.h-H).isin(big)
        print(' ',kind,'in big hour',inb.sum(),round(g[inb].base_R.mean(),3),'hour after',after.sum(),round(g[after].base_R.mean(),3),'others',(~inb&~after).sum(),round(g[~inb&~after].base_R.mean(),3))
        # with vs against the big hour direction for entries in big hour
        d=g[inb].h.map(ew.r)
        w=np.sign(d)==g[inb].side
        print('   in-big with move',w.sum(),round(g[inb][w].base_R.mean(),3),'against',(~w).sum(),round(g[inb][~w].base_R.mean(),3))
