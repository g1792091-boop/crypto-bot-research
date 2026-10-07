sys.path.insert(0,'/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens/context_filters/verify2')
from lib import *
D,cut=load(); T=pd.read_csv(VD+'my_scan_full.csv')
rng=np.random.default_rng(11)
for tf in ['15m','30m']:
  for pair in [('v3a','v4'),('v3a','v3b'),('v3b','v4')]:
    a=T[(T.scope==pair[0])&(T.kind=='strategy')&(T.tf==tf)&T.testable]; b=T[(T.scope==pair[1])&(T.kind=='strategy')&(T.tf==tf)&T.testable]
    J=a.merge(b,on=['f','b'],suffixes=('_a','_b'))
    J=J[J.f!='sideb'] if False else J
    keys=list(zip(J.f,J.b)); r=np.corrcoef(J.d_a,J.d_b)[0,1]; ag=np.mean(np.sign(J.d_a)==np.sign(J.d_b))
    J2=J[~J.f.isin(['sideb'])]; r_noside=np.corrcoef(J2.d_a,J2.d_b)[0,1]
    pre={}
    for run in pair:
        x=D[(D.run==run)&(D.timeframe==tf)&(D.kind=='strategy')].sort_values(['bar_close','sig_id'])
        pre[run]=(x.R.values,[(x[f].notna().values,(x[f]==bb).values) for f,bb in keys])
    nr=[];na=[]
    for _ in range(1000):
        e={}
        for run,(y0,ms) in pre.items():
            n=len(y0); y=np.roll(y0,int(rng.integers(n//6,5*n//6)))
            e[run]=np.array([y[m&i].mean()-y[m&~i].mean() if (m&i).sum()>=5 and (m&~i).sum()>=5 else np.nan for m,i in ms])
        ok=np.isfinite(e[pair[0]])&np.isfinite(e[pair[1]])
        nr.append(np.corrcoef(e[pair[0]][ok],e[pair[1]][ok])[0,1]); na.append(np.mean(np.sign(e[pair[0]][ok])==np.sign(e[pair[1]][ok])))
    nr=np.array(nr);na=np.array(na)
    print(tf,pair,'n',len(J),'corr',round(r,3),'(no side',round(r_noside,3),') p',np.mean(nr>=r),'null 5-95',np.round(np.percentile(nr,[5,95]),3),'agree',round(ag,3),'null mean',round(na.mean(),3),'p',np.mean(na>=ag))
