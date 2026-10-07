sys.path.insert(0,'/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens/context_filters/verify2')
from lib import *
D,cut=load()
FAM={}
for s in "S1_EMA_RSI_CHOP S2_ST_ROC S4_BB_BBP S5_DONCHIAN_MFI N01_ST_EMA N02_ST_KST N03_ADX_GC N04_ST_KLINGER N05_PSAR_POC N06_MACD_ORB N07_ICHI_CMO N09_ALLIG_AROON N12_ICHI_AO N13_3OUTSIDE N15_KC_AO N18_VWMA_MACD N19_FIB_CHOP N23_HA_ST DOGE".split(): FAM[s]='trend'
for s in "N11_BREAKAWAY N17_KC_RSI N25_DST_CCI V45_AMB OBV_B".split(): FAM[s]='revert'
D['fam']=D.strategy.map(FAM).fillna('other')
HY=[('H1','trend','er_t','high','low',1),('H2','revert','er_t','low','high',1),('H3','revert','boxpos_s','cheap_edge','far_edge',1),
    ('H4','trend','di_s','with','against',1),('H5','trend','regime_s','trend_with','chop',1),('H6','revert','regime_s','box','chop',1),('H7','*','stop_t','wide','tight',1)]
rows=[]
for h,fam,f,hi,lo,s in HY:
    for tf in ['15m','30m']:
        for sc,runs in [('v3a',['v3a']),('v3b',['v3b']),('v4',['v4']),('all',['v3a','v3b','v4'])]:
            x=D[(D.kind=='strategy')&(D.timeframe==tf)&D.run.isin(runs)]
            if fam!='*': x=x[x.fam==fam]
            if f=='di_s':
                x=x.assign(di2=np.where(x.di_s.isna(),None,np.where(x.di_s=='with','with','against'))); col='di2'
            else: col=f
            c=contrast(x,col,hi,2,lo=lo,minr=5)
            rows.append(dict(h=h,tf=tf,scope=sc,nin=c['nin'],nout=c['nout'],d=c['d'],p1=p1(c['t'],c['df'],s)))
R=pd.DataFrame(rows); print(R.round(3).to_string(index=False))
m=(R.scope=='all')&(R.nin>=20)&(R.nout>=20); print('BH over all-run core 15m/30m H1-H7:'); R.loc[m,'q']=bh(R.loc[m,'p1'].values); print(R[m].round(3).to_string(index=False))
