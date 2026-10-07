import sys; exec(open(sys.argv[0].rsplit("/",1)[0]+"/h.py").read())
OUT=sys.argv[0].rsplit("/",1)[0]; rng=np.random.default_rng(11)
P=pd.read_csv(f'{OUT}/pairs3.csv'); cf=pd.read_csv(f'{OUT}/cf3.csv')
P=P[P.st=='T'].copy(); P['d']=P.own-P.flip
cfm=cf[cf.st=='T'].groupby(['run','tf','side']).R.mean()
P['ss']=[cfm.get((r,t,s),np.nan) for r,t,s in zip(P.run,P.tf,P.side)]; P['timing']=P.own-P.ss
def signp(v,cl,nb=4000):
    s=pd.Series(v).groupby(np.asarray(cl)).sum().to_numpy(); o=s.sum()
    sims=np.array([(s*rng.choice([-1,1],len(s))).sum() for _ in range(nb)]); return (np.abs(sims)>=abs(o)).mean(), len(s)
def bh(p):
    p=np.asarray(p); n=len(p); o=np.argsort(p); q=np.empty(n); m=1
    for i,k in enumerate(o[::-1]): rank=n-i; m=min(m,p[k]*n/rank); q[k]=m
    return q
rows=[]
for (k,s),g in P[P.tf.isin(['15m','30m'])].groupby(['kind','strategy']):
    p,nc=signp(g.d,g.h1) if len(g)>1 else (np.nan,0)
    pt,_=signp(g.timing,g.h1) if len(g)>1 else (np.nan,0)
    rows.append(dict(kind=k,strategy=s,n=len(g),cl=nc,long=(g.side>0).mean(),own=g.own.mean(),flip=g.flip.mean(),d=g.d.mean(),p=p,timing=g.timing.mean(),p_t=pt,
                     d_v3b=g[g.run=='v3b'].d.mean(),d_v4=g[g.run=='v4'].d.mean()))
U=pd.DataFrame(rows); ok=U.p.notna()&(U.cl>=10)
U.loc[ok,'q']=bh(U.loc[ok,'p']); U.loc[ok,'q_t']=bh(U.loc[ok,'p_t'])
U.to_csv(f'{OUT}/units3.csv',index=False)
print('units',len(U),'testable',ok.sum(),'min p',U.loc[ok].sort_values('p').head(6)[['strategy','n','cl','d','p','q','timing','p_t']].round(3).to_string())
print('min q_t', U.loc[ok].sort_values('p_t').head(5)[['strategy','n','timing','p_t','q_t','long']].round(3).to_string())
for s in ['N20_EMA9_CHOP','N13_3OUTSIDE','N17_KC_RSI','N24_DMI','F16_FIB500']:
    print(U[U.strategy==s][['strategy','n','cl','long','own','flip','d','p','timing','p_t','d_v3b','d_v4']].round(3).to_string(header=False))
# 1h / 4h cells
r2=[]
for (k,s,tf),g in P[P.tf.isin(['1h','4h'])].groupby(['kind','strategy','tf']):
    if len(g)<2: continue
    p,nc=signp(g.d,g.h1); pt,_=signp(g.timing,g.h1); r2.append(dict(kind=k,strategy=s,tf=tf,n=len(g),cl=nc,d=g.d.mean(),p=p,timing=g.timing.mean(),p_t=pt,long=(g.side>0).mean()))
U2=pd.DataFrame(r2); ok2=U2.cl>=10; U2.loc[ok2,'q']=bh(U2.loc[ok2,'p'])
print('1h/4h min p', U2[ok2].sort_values('p').head(5).round(3).to_string())
# 4h strategy replay with 20x filter
A=pd.read_csv(f'{OUT}/ai_sig3.csv'); h=A[(A.tf=='4h')&(A.kind=='strategy')]
print('strategy 4h signals',len(h),'not ok20',(~h.ok20).sum(),'ok20 traded n',((h.st=='T')&h.ok20).sum(),'mean',round(h[(h.st=='T')&h.ok20].R.mean(),3),'incl unres',round(h[h.ok20].R.mean(),3),'unres',((h.st=='U')&h.ok20).sum(),'long',round((h[h.ok20].side>0).mean(),2))
h=A[(A.tf=='4h')&(A.kind=='ds200')]; print('ds200 4h',len(h),'not ok20',(~h.ok20).sum(),'mean ok20 incl unres',round(h[h.ok20].R.mean(),3))
