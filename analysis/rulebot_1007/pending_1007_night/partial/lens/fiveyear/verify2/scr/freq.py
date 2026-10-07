import sys, os, numpy as np
sys.path.append('/root/.local/lib/python3.11/site-packages')
import pandas as pd
E, SIG, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
RUNS = {'v3a': ('run-20261005T014624Z', 2.6075569791666666), 'v3b': ('run-20261005T183457Z', 0.6986111111111111), 'v4': ('current', 1.5034722222222223)}
COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
S0, S1 = pd.Timestamp("2021-08-01").value, pd.Timestamp("2026-09-30").value
days5 = (S1 - S0) / 86400e9
# 5y core counts from the npz (own count)
fy = {}
for tf in ("5m", "15m", "30m", "1h", "4h"):
    for coin in COINS:
        z = np.load(os.path.join(SIG, f"sig_{tf}_{coin}.npz"))
        ts = z['ts']; m = (ts >= S0) & (ts < S1)
        for k in z.files:
            if k.startswith('s__'):
                fy[(k[3:], tf)] = fy.get((k[3:], tf), 0) + int((z[k][m] != 0).sum())
# DS 5y counts from my DS sim csvs (signals incl. unsized)
for tf in ("15m", "30m", "1h", "4h"):
    p = os.path.join(OUT, f"my_ds_{tf}.csv")
    if os.path.exists(p):
        d = pd.read_csv(p, usecols=['strategy'])
        for st, n in d['strategy'].value_counts().items():
            fy[(st, tf)] = int(n)
rows = []
for lab, (r, L) in RUNS.items():
    s = pd.read_csv(os.path.join(E, r, 'signal_log.csv'))
    print(lab, s['status'].value_counts().to_dict())
    s = s[~s['symbol'].isin(['XRPUSDT'])]
    for (st, tf), g in s.groupby(['strategy', 'timeframe']):
        rows.append(dict(run=lab, strategy=st, tf=tf, n=len(g), n_sub=int((g.status == 'SUBMITTED').sum()), days=L))
R = pd.DataFrame(rows)
R['kind'] = np.where(R.strategy.str.match(r'^F\d'), 'ds200', np.where(R.strategy.str.startswith('RANDOM'), 'random', np.where(R.strategy.str.startswith('REEL'), 'reel', 'strategy')))
R['fy_n'] = [fy.get((a, b), np.nan) for a, b in zip(R.strategy, R.tf)]
R.to_csv(os.path.join(OUT, 'freq_cells.csv'), index=False)
for kind in ('strategy', 'ds200'):
    for tf in ("5m", "15m", "30m", "1h", "4h"):
        x = R[(R.kind == kind) & (R.tf == tf)]
        if not len(x): continue
        live_n = x['n'].sum(); live_days = x.groupby('run')['days'].first().sum()
        names = x.strategy.unique()
        fyn = sum(fy.get((st, tf), 0) for st in names)
        allfy = sum(v for (st, t), v in fy.items() if t == tf and ((st.startswith('F') and st[1].isdigit()) == (kind == 'ds200')))
        print(kind, tf, 'runs', sorted(x.run.unique()), 'live/day', round(live_n / live_days, 1), '5y/day(all defs)', round(allfy / days5, 1), 'ratio', round(live_n / live_days / (allfy / days5), 3))
# cell level log-frequency correlation for cells with >=1 5y signal/day
c = R.groupby(['kind', 'strategy', 'tf']).agg(n=('n', 'sum'), days=('days', 'sum'), fy_n=('fy_n', 'first')).reset_index()
c = c[c.kind.isin(['strategy', 'ds200'])]
c['fy_pd'] = c.fy_n / days5; c['live_pd'] = c.n / c.days
cc = c[c.fy_pd >= 1]
lr = np.log(cc.live_pd.clip(lower=1e-3) / cc.fy_pd)
print('cells>=1/day', len(cc), 'corr log', np.corrcoef(np.log(cc.live_pd.clip(lower=1e-3)), np.log(cc.fy_pd))[0, 1], 'share within 0.5-2x', float(((cc.live_pd / cc.fy_pd).between(0.5, 2)).mean()))
print(c[(c.strategy == 'N17_KC_RSI') & (c.tf == '4h')])
