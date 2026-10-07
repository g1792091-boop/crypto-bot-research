import sys, time
sys.path[:0] = ['/home/user/crypto-bot-research', '/root/.local/lib/python3.11/site-packages']
import numpy as np, pandas as pd, hashlib, importlib.util
S='/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/binance'
z=np.load(f'{S}/signals/sig_15m_BTCUSD.npz')
print(len(z.files), len(z['ts']), z['ts'][:1].astype('datetime64[ns]'), z['ts'][-1:].astype('datetime64[ns]'))
print([k for k in z.files if not k.startswith('s__')])
b=pd.read_csv(f'{S}/bars/btcusd-15m.csv.gz'); print(b.head(2), len(b))
p='/home/user/crypto-bot-research/research/entry_study/param_defs/S4_BB_BBP.py'
spec=importlib.util.spec_from_file_location('pd_s4', p); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
df=pd.DataFrame({'ts':pd.to_datetime(z['ts'],utc=True),'open':z['o'],'high':z['h'],'low':z['l'],'close':z['c'],'volume':z['v']}); df.attrs['tf']='15m'
t=time.time(); L,Sh=m.signals(df,'15m'); print('t',time.time()-t)
sig=np.where(L,1,np.where(Sh,-1,0)); ref=z['s__S4_BB_BBP']
print('match', (sig==ref).mean(), (ref!=0).sum(), (sig!=0).sum(), ((sig!=ref)).sum())
