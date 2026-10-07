sys.path.insert(0,'/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens/context_filters/verify2')
from lib import *
D,cut=load(); print('v3a cut',cut, pd.to_datetime(cut+9*H,unit='ms'))
print(D.groupby(['run','kind','timeframe']).size().to_string())
rows=[]
SC={'v3a':['v3a'],'v3b':['v3b'],'v4':['v4'],'v3b+v4':['v3b','v4'],'v3a+v3b':['v3a','v3b'],'all':['v3a','v3b','v4']}
for tf in ['15m','30m','1h']:
    for kind,scs in [('strategy',list(SC)),('ds200',['v4'])]:
        for f,b in CONTR:
            for sc in scs:
                X=D[(D.timeframe==tf)&(D.kind==kind)&D.run.isin(SC[sc])]
                r={'tf':tf,'kind':kind,'f':f,'b':b,'scope':sc}
                for mode in [2,4,'day']:
                    c=contrast(X,f,b,mode); 
                    if mode==2: r.update(c)
                    else: r['t_'+str(mode)]=c['t']; r['df_'+str(mode)]=c['df']; r['se_'+str(mode)]=c['se']
                rows.append(r)
T=pd.DataFrame(rows); T['testable']=(T.nin>=30)&(T.nout>=30)
T.to_csv(VD+'my_scan_full.csv',index=False)
print(len(T), T.testable.sum())
