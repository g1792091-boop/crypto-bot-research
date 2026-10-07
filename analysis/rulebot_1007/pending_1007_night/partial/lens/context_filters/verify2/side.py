sys.path.insert(0,'/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens/context_filters/verify2')
from lib import *
D,cut=load()
for tf in ['15m','30m']:
    x=D[(D.kind=='strategy')&(D.timeframe==tf)]
    xs=x.assign(run=x.run+x.sideb)
    for f,b in [('di_s','with'),('boxpos_s','far_edge'),('rangepos_s','far_edge'),('ema_s','with'),('consensus','many'),('qt','best'),('htfpos_s','middle'),('adx_b','ge30'),('stop_t','wide')]:
        a=contrast(x,f,b,2); s=contrast(xs,f,b,2); s4=contrast(xs,f,b,'day')
        print(tf,f,b,'pooled',round(a['d'],3),'within side',round(s['d'],3),'se',round(s['se'],3),'z',round(s['t'],2),'t_day',round(s4['t'],2))
