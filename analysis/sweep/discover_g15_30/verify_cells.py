"""Independent re-computation of selected gate cells from the raw IS CSVs + cached signals:
own window logic, own forward returns, brute-force np.roll null with the pre-registered shifts."""
import numpy as np, pandas as pd, sys
from scipy.stats import norm
sys.path.insert(0, '.')
import sweep_lib as L
DATA = '/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/sweep/data/is'
COINS = L.COINS
cells = [("N17_KC_RSI", "15m", 4), ("V45_AMB", "30m", 64), ("N03_ADX_GC", "30m", 4), ("S2_ST_ROC", "30m", 16), ("DOGE_L", "15m", 16)]
gate = pd.read_csv('gate_cells.csv')
out = []
for strat, tf, H in cells:
    sig = L.load_signals(f'out/signals_is_{tf}.npz')[strat]
    m = L.tf_minutes(tf); wu = 200 if tf == '1d' else max(300, int(np.ceil(30 * 1440 / m)))
    segs = {}
    for c in COINS:
        df = pd.read_csv(f'{DATA}/{c.lower()}-{tf}.csv')
        ts = pd.to_datetime(df['ts'], utc=True)
        assert ts.max() < pd.Timestamp('2024-07-01', tz='UTC')
        o = df['open'].to_numpy(float)
        idx = np.arange(len(df))
        adm = (ts >= pd.Timestamp('2021-08-01', tz='UTC')).to_numpy() & (idx >= wu) & (idx + 1 + H <= len(df) - 1)
        t = idx[adm]
        r = o[t + 1 + H] / o[t + 1] - 1
        lr = np.log(o)
        rv = np.array([np.sqrt(np.sum(np.diff(lr[tt + 1: tt + 2 + H]) ** 2)) for tt in t]) if len(t) < 0 else None
        segs[c] = (sig[c][t].astype(float), r)
    n = sum(np.abs(d).sum() for d, r in segs.values())
    fwd = sum(d @ r for d, r in segs.values()) / n
    Nmin = min(len(r) for d, r in segs.values())
    sh = L.gate_shifts(tf, H, Nmin, 600)
    null = np.array([sum(np.roll(d, k) @ r for d, r in segs.values()) / n for k in sh])
    z = (fwd - null.mean()) / null.std(ddof=1)
    eabs = np.mean(np.abs(np.concatenate([r for d, r in segs.values()])))
    mu = 0.0014 + 0.0001 * H * m / 480 + 0.091 * eabs
    g = gate[(gate.strategy == strat) & (gate.tf == tf) & (gate.H == H)].iloc[0]
    out.append(dict(cell=f'{strat} {tf} H{H}', n=n, n_h=g.n, fwd=fwd, fwd_h=g.fwd, z=z, z_h=g.z, null_sd=null.std(ddof=1),
                    null_sd_h=g.null_sd, mu=mu, mu_h=g.mu_star, eabs=eabs, eabs_h=g.E_abs_r))
pd.set_option('display.width', 250)
r = pd.DataFrame(out)
print(r.to_string(index=False))
for a in ['n', 'fwd', 'z', 'null_sd', 'mu', 'eabs']:
    print(a, 'max abs diff', np.max(np.abs(r[a] - r[a + '_h'])))
