T=pd.read_csv(VD+'verify2/my_scan_full.csv') if False else pd.read_csv('/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens/context_filters/verify2/my_scan_full.csv')
Th=pd.read_csv('/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens/context_filters/out/scan_full.csv')
Th['f']=Th.feature.replace({'side':'sideb','qtier':'qt'}); Th['b']=Th.bucket
J=T.merge(Th,on=['tf','kind','f','b','scope'],suffixes=('','_h'))
print(len(T),len(Th),len(J)); print('max |d diff|',np.nanmax(np.abs(J.d-J.d_h)), 'corr se',np.corrcoef(J.se.fillna(0),J.se_h.fillna(0))[0,1], 'median se ratio CR/boot',np.nanmedian(J.se/J.se_h))
def show(tf,kind,f,b):
    x=T[(T.tf==tf)&(T.kind==kind)&(T.f==f)&(T.b==b)][['scope','nin','nout','d','se','p','t','t_4','t_day','df_day']]
    print(tf,kind,f,b); print(x.round(3).to_string(index=False))
for tf in ['15m','30m']:
    show(tf,'strategy','sideb','long'); show(tf,'ds200','sideb','long')
    show(tf,'strategy','session','europe'); show(tf,'ds200','session','europe')
    show(tf,'strategy','qt','best'); show(tf,'strategy','qt','base')
    show(tf,'strategy','adx_b','ge30'); show(tf,'strategy','stop_t','wide')
    show(tf,'strategy','htfpos_s','middle'); show(tf,'ds200','htfpos_s','middle')
