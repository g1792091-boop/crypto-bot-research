import sys, time
sys.path[:0] = ['/home/user/crypto-bot-research', '/root/.local/lib/python3.11/site-packages', '/home/user/crypto-bot-research/research/deepseek200']
import numpy as np, pandas as pd, importlib.util
S='/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/binance'
import lib_c
for tf in ['1h']:
    b=pd.read_csv(f'{S}/bars/btcusd-{tf}.csv.gz')
    b['ts']=pd.to_datetime(b['ts'],utc=True)
    t=time.time(); E=lib_c.entries(b.copy(),tf,ctx=None,coin='BTCUSD'); print('entries',time.time()-t)
    for k in ['F6_VWAP_CROSS','F5_BOX','F9_FVG']:
        print(k, E[k][0].sum(), E[k][1].sum())
for nm in ['N10_HA_PSAR','N23_HA_ST','N16_BBRSI','OBV_B','N17_KC_RSI','S2_ST_ROC','N24_DMI','N06_MACD_ORB']:
    p=f'/home/user/crypto-bot-research/research/entry_study/param_defs/{nm}.py'
    spec=importlib.util.spec_from_file_location('pd_'+nm, p); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    z=np.load(f'{S}/signals/sig_15m_BTCUSD.npz')
    df=pd.DataFrame({'ts':pd.to_datetime(z['ts'],utc=True),'open':z['o'],'high':z['h'],'low':z['l'],'close':z['c'],'volume':z['v']}); df.attrs['tf']='15m'
    t=time.time(); L,Sh=m.signals(df,'15m'); dt=time.time()-t
    sig=np.where(L,1,np.where(Sh,-1,0)); ref=z['s__'+nm]
    print(nm, 't %.2f'%dt, 'mismatch', int((sig!=ref).sum()), int((ref!=0).sum()))
