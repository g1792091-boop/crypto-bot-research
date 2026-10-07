T=pd.read_csv('/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens/context_filters/verify2/my_scan_full.csv')
Th=pd.read_csv('/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens/context_filters/out/scan_full.csv')
Th['f']=Th.feature.replace({'side':'sideb','qtier':'qt'}); Th['b']=Th.bucket
J=T.merge(Th,on=['tf','kind','f','b','scope'],suffixes=('','_h'))
J['dd']=np.abs(J.d-J.d_h)
print(J[J.dd>1e-6].groupby(['f']).size()); print(J[J.dd>1e-6][['tf','kind','f','b','scope','nin','n_in','d','d_h']].head(20).to_string())
