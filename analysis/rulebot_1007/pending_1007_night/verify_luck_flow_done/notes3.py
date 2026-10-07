import sys; exec(open(sys.argv[0].rsplit("/",1)[0]+"/h.py").read())
import json
OUT=sys.argv[0].rsplit("/",1)[0]
N=json.load(open(sys.argv[1]))['strategy_notes']
U=pd.read_csv(f'{OUT}/units3.csv').set_index('strategy'); A=pd.read_csv(f'{OUT}/flow_accounts3.csv'); T=pd.read_csv(f'{OUT}/trades3.csv',usecols=['strategy_id','timeframe','kind','R','run'])
AI=pd.read_csv(f'{OUT}/ai_trader3.csv'); AI=AI[AI.sc=='A_15m30m'].set_index('strategy')
P=json.load(open('/home/user/crypto-bot-research/research/strategy_profiles/out_binance/profiles.json'))['profiles']
from collections import Counter
print(Counter(n['grade'] for n in N))
pick=['N13_3OUTSIDE','N17_KC_RSI','N20_EMA9_CHOP','F16_FIB500','F4_PULL','N04_ST_KLINGER','S2_ST_ROC','F11_TSOUP','N08_ICHI_WR','S5_DONCHIAN_MFI','F12_MSS','N12_ICHI_AO']
for n in N:
    s=n['strategy'].split(' ')[0]
    if s not in pick: continue
    a=A[(A.strategy==s)&A.timeframe.isin(['15m','30m'])]
    sig=a['sub'].sum()/a.groupby('run').days.first().sum() if len(a) else np.nan
    y5=sum(P.get(s,{}).get(tf,{}).get('signals_per_day',0) for tf in ['15m','30m']) if s in P else np.nan
    lt=T[(T.strategy_id==s)&T.timeframe.isin(['15m','30m'])&(T.kind!='random')]
    u=U.loc[s] if s in U.index else None
    print('---',s,n['grade'],'|',n['numbers'][:330]); 
    print('   MINE: sig/d %.1f 5y %.1f AItr/d %.2f pairs n %s long %.2f halfexcess %+.2f p %.3f timing %+.2f live n %d R %+.2f'%(sig,y5,AI.loc[s].n_d if s in AI.index else np.nan,
          u.n if u is not None else 0,u.long if u is not None else np.nan,u.d/2 if u is not None else np.nan,u.p if u is not None else np.nan,u.timing if u is not None else np.nan,len(lt),lt.R.mean()))
    print('   note:',n['note'][:250])
