import sys; exec(open(sys.argv[0].rsplit("/",1)[0]+"/h.py").read())
OUT=sys.argv[0].rsplit("/",1)[0]; pd.set_option('display.width',250)
rng=np.random.default_rng(7)
BLK=4*3600*1000
def bci(v,blk,nb=2000):
    v=np.asarray(v);blk=np.asarray(blk); u=np.unique(blk); idx=[np.where(blk==b)[0] for b in u]
    ms=[v[np.concatenate([idx[k] for k in rng.integers(0,len(u),len(u))])].mean() for _ in range(nb)]
    return np.percentile(ms,[2.5,97.5]).round(3).tolist()
def deff(v,cl):
    v=np.asarray(v,float); r=v-v.mean(); s=pd.Series(r).groupby(np.asarray(cl)).sum()
    return float((s**2).sum()/(r**2).sum())
cf=pd.read_csv(f'{OUT}/cf3.csv'); print('cf rows',len(cf), cf.st.value_counts().to_dict())
cf['blk']=cf.bc//BLK
T=cf[cf.st=='T']
print('== exhaustive CF (30x->20x), v3b+v4 traded')
for tf in ['15m','30m','1h','4h']:
    g=T[T.tf==tf]; a=cf[cf.tf==tf]
    print(tf,'n',len(g),'blocks',g.blk.nunique(),'meanR',round(g.R.mean(),3),bci(g.R,g.blk),'cost',round(g.cost_R.mean(),3),'gross',round((g.R+g.cost_R).mean(),3),
          'incl_unres',round(a[a.st!='REJ'].R.mean(),3),'unres',(a.st=='U').sum(),'rej',(a.st=='REJ').sum(),'sd',round(g.R.std(),2))
print('== by run x side (plain mean, traded)')
print(T.groupby(['run','tf','side']).R.mean().unstack().round(3).to_string())
# per coin v4 15m long-minus-short
x=T[(T.run=='v4')&(T.tf=='15m')].groupby(['symbol','side']).R.mean().unstack(); print('v4 15m L-S by coin', (x[1]-x[-1]).round(2).to_dict())
sg=pd.read_csv(f'{OUT}/sig3.csv'); sg['blk']=sg.bc//BLK; sg['h1']=sg.bc//3600000
print('sig rows',len(sg))
P=sg.pivot_table(index=['run','kind','strategy','tf','symbol','bc'],columns='which',values='R').dropna().reset_index()
S=sg[sg.which=='own'].set_index(['run','kind','strategy','tf','symbol','bc'])
P=P.join(S[['st','side','out','ok20','ok30']],on=['run','kind','strategy','tf','symbol','bc'])
P['blk']=P.bc//BLK; P['h1']=P.bc//3600000; P['ex']=(P.own-P.flip)/2
# use both resolved (st T) only for fair comparison? keep all with mark, report traded subset
Pt=P[P.st=='T']
print('== timing-matched side flip (own vs flipped, 30x), traded own')
for k in ['strategy','ds200']:
    for tf in ['15m','30m','1h','4h']:
        g=Pt[(Pt.kind==k)&(Pt.tf==tf)]
        if len(g)==0: continue
        # block sign-flip p for mean excess
        bs=g.groupby('blk').ex.sum().to_numpy(); obs=bs.sum()
        sims=np.array([(bs*rng.choice([-1,1],len(bs))).sum() for _ in range(4000)]); p=(np.abs(sims)>=abs(obs)).mean()
        print(k,tf,'n',len(g),'own',round(g.own.mean(),3),'flip',round(g.flip.mean(),3),'excess(own-flip)/2',round(g.ex.mean(),3),'p2',round(p,3),'blocks',len(bs),
              'deff4h',round(deff(g.own,g.blk),2),'neff',round(len(g)/deff(g.own,g.blk)),'deff_h1',round(deff(g.own,g.h1),2),'long',round((g.side>0).mean(),2))
P.to_csv(f'{OUT}/pairs3.csv',index=False)
