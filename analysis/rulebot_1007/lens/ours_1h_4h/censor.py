"""Censoring check: replayed signals still open at the run end (UNRESOLVED) marked to the last close, per tf.
    python3 -I censor.py <out_real_dir>"""
import site, sys
sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import pandas as pd, numpy as np
RP = pd.read_csv(sys.argv[1] + '/replay_signals.csv', low_memory=False)
RP = RP[RP.kind == 'strategy']
rows = []
for (run, tf), g in RP.groupby(['run', 'timeframe']):
    tr = g[g.status == 'TRADED']; un = g[g.status == 'UNRESOLVED']
    both = np.concatenate([tr.R.to_numpy(float), un.mark_R.dropna().to_numpy(float)])
    rows.append(dict(run=run, tf=tf, n_traded=len(tr), mean_R_traded=tr.R.mean(), n_unres=len(un),
                     mean_mark_R_unres=un.mark_R.mean(), mean_R_incl_unres=both.mean(),
                     n_rej=int((g.status == 'REJECTED_SIZING').sum()),
                     unres_share=len(un) / max(len(tr) + len(un), 1)))
D = pd.DataFrame(rows)
print(D.round(3).to_string())
D.to_csv('censoring_check.csv', index=False)
