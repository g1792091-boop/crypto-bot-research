import sys, site
sys.path.append(site.getusersitepackages())
import pandas as pd, numpy as np
pd.set_option('display.width', 250)
T = pd.read_csv(sys.argv[1])
keys = [('session','europe'),('htfpos_s','middle'),('ema_s','with'),('di_s','with'),('stop_t','tight'),('stop_t','wide'),('qtier','best'),('qtier','base'),
        ('consensus','many'),('consensus','alone'),('conflict','yes'),('regime_s','trend_with'),('regime_s','trend_against'),('regime_s','box'),('er_t','high'),('er_t','low'),('side','long'),('brk','yes'),('adx_b','ge30'),('session','late'),('boxpos_s','far_edge'),('boxpos_s','cheap_edge')]
for tf in ['15m','30m']:
    print('=====', tf)
    rows=[]
    for f,b in keys:
        r={'feature':f,'bucket':b}
        for sc,kind in [('v3a','strategy'),('v3b','strategy'),('v4','strategy'),('v4','ds200'),('all','strategy')]:
            x=T[(T.tf==tf)&(T.feature==f)&(T.bucket==b)&(T.scope==sc)&(T.kind==kind)]
            if len(x):
                x=x.iloc[0]; tag=sc if kind=='strategy' else 'ds'
                r[tag+'_n']=int(x.n_in); r[tag+'_d']=round(x.d,3); r[tag+'_p']=round(x.p_two,3)
        rows.append(r)
    print(pd.DataFrame(rows).to_string())
