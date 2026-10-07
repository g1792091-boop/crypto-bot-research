sys.path.insert(0,'/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens/context_filters/verify2')
from lib import *
D,cut=load(); T=pd.read_csv(VD+'my_scan_full.csv')
for kind,sc in [('strategy','all'),('strategy','v4'),('strategy','v3a'),('ds200','v4')]:
    for tf in ['15m','30m']:
        x=T[(T.kind==kind)&(T.scope==sc)&(T.tf==tf)&T.testable&(T.f!='sideb')]
        mde=(stats.t.ppf(0.975,x.df)+stats.t.ppf(0.8,x.df))*x.se
        mde4=(stats.t.ppf(0.975,x.df_4)+stats.t.ppf(0.8,x.df_4))*x.se_4
        print(kind,sc,tf,'n contrasts',len(x),'median MDE80 2h',round(mde.median(),3),'4h',round(mde4.median(),3))
def de(y,bc,hours):
    cl=bc//int(hours*H); u,inv=np.unique(cl,return_inverse=True); G=len(u)
    r=y-y.mean(); s=np.bincount(inv,r,G); v=G/(G-1)*np.sum(s**2)/len(y)**2; return v/(y.var(ddof=1)/len(y)),G
for run in ['v3a','v4']:
  for tf in ['15m','30m']:
    x=D[(D.run==run)&(D.kind=='strategy')&(D.timeframe==tf)]
    print(run,tf,len(x),[ (h,round(de(x.R.values,x.bar_close.values,h)[0],1),de(x.R.values,x.bar_close.values,h)[1]) for h in [1,2,4,8,12]])
