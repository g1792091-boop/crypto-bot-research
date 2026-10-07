sys.path.insert(0,'/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens/context_filters/verify2')
from lib import *
T=pd.read_csv(VD+'my_scan_full.csv')
def direc(ds,ts,dk='strategy',tk='strategy',name=''):
    a=T[(T.scope==ds)&(T.kind==dk)].set_index(['tf','f','b']); b=T[(T.scope==ts)&(T.kind==tk)].set_index(['tf','f','b'])
    J=a.join(b,lsuffix='_d',rsuffix='_t',how='left').reset_index(); J['dir']=name
    J['prim']=J.tf.isin(['15m','30m'])
    J['carried']=J.testable_d.fillna(False)&(J.p_d<0.05)
    J['tt']=J.testable_t.fillna(False)
    sg=np.sign(J.d_d)
    J['p1']=[p1(t,df,s) if c and tt else np.nan for t,df,s,c,tt in zip(J.t_t,J.df_t,sg,J.carried,J.tt)]
    J['p1_4']=[p1(t,df,s) if c and tt else np.nan for t,df,s,c,tt in zip(J.t_4_t,J.df_4_t,sg,J.carried,J.tt)]
    J['p1_day']=[p1(t,df,s) if c and tt else np.nan for t,df,s,c,tt in zip(J.t_day_t,J.df_day_t,sg,J.carried,J.tt)]
    J['q']=np.nan
    for pr in [True,False]:
        m=(J.prim==pr)&J.carried&J.tt; J.loc[m,'q']=bh(J.loc[m,'p1'].values)
    J['rep']=(J.q<0.05)&(J.p1_4<0.05)&(np.sign(J.d_d)==np.sign(J.d_t))
    P=J[J.prim]
    print(name,'testable disc',int((P.testable_d==True).sum()),'raw p<.05',int(P.carried.sum()),'disc BH q<.10',int((bh(P.loc[P.testable_d==True,'p_d'].values)<0.10).sum()),
          'carried&testable',int((P.carried&P.tt).sum()),'p1<.05',int((P.p1<0.05).sum()),'q<.05',int((P.q<0.05).sum()),'rep',int(P.rep.sum()),
          'same sign',int(((np.sign(P.d_d)==np.sign(P.d_t))&P.carried&P.tt).sum()))
    print(P[P.carried&P.tt].sort_values('p1')[['tf','f','b','d_d','d_t','nin_t','p1','p1_4','p1_day','q']].head(8).round(4).to_string(index=False))
    return J
A=direc('v3a','v3b+v4',name='A'); B=direc('v4','v3a+v3b',name='B'); X=direc('v3a','v4',tk='ds200',name='T')
AL=pd.concat([A,B,X]); AL=AL[AL.prim&AL.carried&AL.tt]
AL['q_all']=bh(AL.p1.values)
print('all OOS tests pooled (A+B+T, primary):',len(AL)); print(AL.sort_values('p1')[['dir','tf','f','b','p1','q_all']].head(5).round(4).to_string(index=False))
AL2=pd.concat([A,B,X]); AL2=AL2[AL2.carried&AL2.tt]; AL2['q_all']=bh(AL2.p1.values); print('incl 1h',len(AL2)); print(AL2.sort_values('p1')[['dir','tf','f','b','p1','q_all']].head(3).round(4).to_string(index=False))
