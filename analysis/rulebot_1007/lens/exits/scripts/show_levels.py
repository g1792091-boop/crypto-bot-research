import site, sys
sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path: sys.path.append(us)
import pandas as pd, numpy as np
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)
P = pd.read_csv(sys.argv[1])
L = pd.read_csv(sys.argv[2])
print(L.round(3).to_string(index=False))
M = P[(P.group=='house_all')&(P.set=='ALL')&(P.flip==0)]
for (run, tf), g in M.groupby(['run','tf']):
    g = g.sort_values('R_var', ascending=False)
    print(run, tf, 'n', int(g.n_paired.max()), 'base R %.3f gross %.3f' % (g.R_base.iloc[0], g.grossR_base.iloc[0]),
          '| best:', ', '.join(f"{r.variant} {r.R_var:+.3f}" for r in g.head(4).itertuples()),
          '| worst:', ', '.join(f"{r.variant} {r.R_var:+.3f}" for r in g.tail(3).itertuples()))
F = P[(P.group=='house_all')&(P.set=='ALL')&(P.flip==1)]
print('FLIP side base R:')
for (run, tf), g in F.groupby(['run','tf']):
    print(run, tf, 'n', int(g.n_paired.max()), 'flip base R %.3f gross %.3f' % (g.R_base.iloc[0], g.grossR_base.iloc[0]))
# group-level base R for core36 and ds200
for grp in ['core36','ds200']:
    G = P[(P.group==grp)&(P.set=='ALL')&(P.flip==0)&(P.variant=='geo20')]
    print(grp, G[['run','tf','n_paired','R_base','grossR_base','win_var']].round(3).to_string(index=False))
