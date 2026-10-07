import sys,site,json,re; sys.path.append(site.getusersitepackages())
import pandas as pd, numpy as np
d=json.load(open(sys.argv[1])); RP=pd.read_csv(sys.argv[2])
V=pd.read_csv('vr_signals.csv'); V=V[V.base_st.isin(['TRADED','OPEN'])].copy()
V['rs']=V.run.map({'run-20261005T183457Z':'v3b','current':'v4'})
RP=RP[RP.status.isin(['TRADED','UNRESOLVED'])].copy(); RP['flipR']=RP.flip_R.fillna(RP.flip_mark_R); RP['R2']=RP.R.fillna(RP.mark_R)
bad=[]
for x in d['strategy_notes']:
    s=x['strategy'].split(' (')[0]; tf=x['timeframe']
    g=V[(V.strategy==s)&(V.timeframe==tf)]
    num=x['numbers']
    m=re.search(r'sig n(\d+) \(v3b (\d+)/v4 (\d+)\) R ([+-]?[\d.]+)',num)
    rules={k:float(v) for k,v in re.findall(r'(CUT05|NP4|BE05|TP1) ([+-]?[\d.]+)',num)}
    mine={k:(g[f'{k}_R']-g.base_R).mean() for k in rules}
    fl=re.search(r'flip ([+-]?[\d.]+)',num)
    r=RP[(RP.strategy==s)&(RP.timeframe==tf)&RP.run.isin(['run-20261005T183457Z','current'])]
    flip=((r.R2-r.flipR)/2).mean()
    probs=[]
    if m:
        if int(m.group(1))!=len(g): probs.append(f'n {m.group(1)} vs {len(g)}')
        if abs(float(m.group(4))-g.base_R.mean())>0.011: probs.append(f'R {m.group(4)} vs {g.base_R.mean():.3f}')
    for k in rules:
        if abs(rules[k]-mine[k])>0.03: probs.append(f'{k} {rules[k]} vs {mine[k]:.3f}')
    if fl and abs(float(fl.group(1))-flip)>0.011: probs.append(f'flip {fl.group(1)} vs {flip:.3f}')
    if probs: bad.append((s,tf,probs))
print(len(d['strategy_notes']),'notes;',len(bad),'with differences'); [print(b) for b in bad]
# cells missing from notes
have={(x['strategy'].split(' (')[0],x['timeframe']) for x in d['strategy_notes']}
cnt=V[V.kind.isin(['strategy','ds200'])].groupby(['kind','strategy','timeframe']).size()
miss=cnt[[ (s,tf) not in have for (k,s,tf) in cnt.index]]
print('cells with >=10 signals not in notes, by kind x tf:'); print(miss[miss>=10].groupby(level=[0,2]).size())
