import numpy as np, pandas as pd
from scipy import stats
VD='/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens/context_filters/verify2/'
H=3600000
ERC={'15m':(0.055,0.13),'30m':(0.065,0.155),'1h':(0.065,0.155)}
STC={'15m':(0.5,0.7),'30m':(0.74,1.0),'1h':(1.0,1.4)}
def cut3(x,a,b,n):
    x=np.asarray(x,float); o=np.where(x<a,n[0],np.where(x<b,n[1],n[2])).astype(object); o[np.isnan(x)]=None; return o
def load():
    D=pd.read_csv(VD+'my_signals.csv.gz',low_memory=False)
    D=D[D.kind.isin(['strategy','ds200'])&D.timeframe.isin(['15m','30m','1h'])].copy()
    D=D[D.regime.notna()]
    cut=D.loc[(D.run=='v3a')&(D.src=='shadow')&D.R.notna(),'bar_close'].max()
    D=D[(D.run!='v3a')|(D.bar_close<=cut)]
    D=D[D.R.notna()].copy()
    s=D.side.values
    def rs(col):
        r=D[col].astype(object).values; o=np.full(len(D),None,object)
        o[r=='chop']='chop'; o[r=='box']='box'; o[r=='unknown']='mid'
        o[((r=='trend_up')&(s>0))|((r=='trend_down')&(s<0))]='trend_with'
        o[((r=='trend_up')&(s<0))|((r=='trend_down')&(s>0))]='trend_against'; return o
    D['regime_s']=rs('regime'); D['htf_regime_s']=rs('htf_regime')
    D['er_t']=None; D['stop_t']=None
    for tf in ERC:
        m=D.timeframe.values==tf
        D.loc[m,'er_t']=cut3(D.er.values[m],*ERC[tf],['low','midER','high'])
        D.loc[m,'stop_t']=cut3(D.stop_pct.values[m],*STC[tf],['tight','midstop','wide'])
    D['adx_b']=cut3(D.adx,20,30,['lt20','20to30','ge30'])
    di=s*(D.di_plus.astype(float)-D.di_minus.astype(float)).values
    D['di_s']=np.where(np.isnan(di),None,np.where(di>0,'with','against'))
    e=s*D.ema20_dist_atr.astype(float).values
    D['ema_s']=np.where(np.isnan(e),None,np.where(e<-0.5,'fade',np.where(e<0.5,'near',np.where(e<1.5,'with','extended'))))
    D['age_b']=cut3(D.trend_age,2.5,10.5,['fresh','mid','old'])
    for a,b in [('box_pos','boxpos_s'),('htf_box_pos','htfpos_s'),('range_pct','rangepos_s')]:
        p=D[a].astype(float).values; p=np.where(s>0,p,1-p); D[b]=cut3(p,0.2,0.8,['cheap_edge','middle','far_edge'])
    D['room_b']=cut3(D.sr_room,0.15,0.5,['blocked','some','open']); D['floor_b']=cut3(D.sr_floor,0.15,0.5,['near','some','far'])
    for a,b in [('sr_level_before_lock','lbl'),('sr_support_before_stop','sbs'),('sr_breakout','brk')]:
        v=D[a].astype(float).values; D[b]=np.where(np.isnan(v),None,np.where(v>0.5,'yes','no'))
    h=D.kst_hour.values
    D['session']=np.where((h>=9)&(h<=15),'asia',np.where((h>=16)&(h<=21),'europe',np.where((h>=22)|(h<=3),'us','late')))
    D['coin']=D.symbol
    D['qt']=np.where(D.kind=='strategy',D.qtier,None)
    g=D.groupby(['run','kind','timeframe','symbol','bar_close','side']).size().rename('n_same').reset_index()
    D=D.merge(g,on=['run','kind','timeframe','symbol','bar_close','side'],how='left')
    g2=g.copy(); g2['side']=-g2.side
    D=D.merge(g2.rename(columns={'n_same':'n_opp'}),on=['run','kind','timeframe','symbol','bar_close','side'],how='left')
    D['n_opp']=D.n_opp.fillna(0)
    D['consensus']=np.where(D.n_same<=1,'alone',np.where(D.n_same<=3,'few','many'))
    D['conflict']=np.where(D.n_opp>0,'yes','no')
    D['sideb']=np.where(D.side>0,'long','short')
    return D,cut
FEAT={'regime_s':['chop','box','mid','trend_with','trend_against'],'htf_regime_s':['chop','box','mid','trend_with','trend_against'],
 'er_t':['low','midER','high'],'adx_b':['lt20','20to30','ge30'],'di_s':['with'],'ema_s':['fade','near','with','extended'],
 'age_b':['fresh','mid','old'],'boxpos_s':['cheap_edge','middle','far_edge'],'htfpos_s':['cheap_edge','middle','far_edge'],
 'rangepos_s':['cheap_edge','middle','far_edge'],'stop_t':['tight','midstop','wide'],'room_b':['blocked','some','open'],
 'floor_b':['near','some','far'],'lbl':['no'],'sbs':['no'],'brk':['yes'],'session':['asia','europe','us','late'],
 'coin':['BTCUSDT','ETHUSDT','SOLUSDT','DOGEUSDT','LTCUSDT','BCHUSDT'],'qt':['best','good','base'],
 'consensus':['alone','few','many'],'conflict':['yes'],'sideb':['long']}
CONTR=[(f,b) for f,bs in FEAT.items() for b in bs]
def clus(bc,mode):
    if mode=='day': return (bc+9*H)//(24*H)
    return bc//int(mode*H)
def one_run(y,inb,cl):
    u,inv=np.unique(cl,return_inverse=True); G=len(u)
    si=np.bincount(inv,np.where(inb,y,0),G); ni=np.bincount(inv,inb.astype(float),G)
    so=np.bincount(inv,np.where(~inb,y,0),G); no=np.bincount(inv,(~inb).astype(float),G)
    Ni,No=ni.sum(),no.sum(); mi,mo=si.sum()/Ni,so.sum()/No
    inf=(si-mi*ni)/Ni-(so-mo*no)/No
    return mi-mo, G/max(G-1,1)*np.sum(inf**2), G, mi, mo
def contrast(X,col,b,mode=2,outcome='R',minr=5,lo=None):
    """X: rows of one tf/kind across chosen runs. Within-run diff, n-weighted, CR1 SE."""
    ds=[];ws=[];vs=[];df=0;nin=0;nout=0
    for run,g in X.groupby('run'):
        g=g[g[col].notna()]
        if lo is not None: g=g[g[col].isin([b,lo])]
        inb=(g[col]==b).values; y=g[outcome].values.astype(float)
        if inb.sum()<minr or (~inb).sum()<minr: continue
        d,v,G,_,_=one_run(y,inb,clus(g.bar_close.values,mode))
        ds.append(d);ws.append(len(g));vs.append(v);df+=G-1;nin+=inb.sum();nout+=(~inb).sum()
    if not ds: return dict(d=np.nan,se=np.nan,df=0,t=np.nan,p=np.nan,nin=0,nout=0)
    w=np.array(ws,float)/sum(ws); d=float(np.dot(w,ds)); se=float(np.sqrt(np.dot(w**2,vs)))
    t=d/se if se>0 else np.nan; df=max(df,1)
    return dict(d=d,se=se,df=df,t=t,p=2*stats.t.sf(abs(t),df) if t==t else np.nan,nin=int(nin),nout=int(nout))
def p1(t,df,sgn): return stats.t.sf(t*sgn,df) if t==t else np.nan
def bh(p):
    p=np.asarray(p,float); q=np.full(len(p),np.nan); ok=~np.isnan(p); m=ok.sum()
    if not m: return q
    idx=np.where(ok)[0]; o=idx[np.argsort(p[ok])]; r=p[o]*m/np.arange(1,m+1)
    q[o]=np.minimum(np.minimum.accumulate(r[::-1])[::-1],1); return q
