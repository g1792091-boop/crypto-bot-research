"""Grid over indicator conventions; compare with Astral trade lists."""
import itertools, sys, time, json
import numpy as np, pandas as pd
import doge_strategy as ds

df = ds.load_ohlcv('dogeusd-5m-last40k.csv')
A_short = pd.read_csv('astral/backtest-bt_4d7868c2f1791cc6_trades.csv', parse_dates=['entry_ts', 'exit_ts'])
A_long = pd.read_csv('astral/backtest-bt_eabbc51538b849c6_trades.csv', parse_dates=['entry_ts', 'exit_ts'])
W = {'short': (df.loc['2026-09-11 00:00':'2026-09-28 23:55'], A_short),
     'long': (df.loc['2026-05-13 03:05':'2026-09-28 23:55'], A_long)}

def match(tr, A):
    k_ours = set(zip(tr.entry_ts, tr.exit_ts)); k_a = set(zip(A.entry_ts, A.exit_ts))
    ent_ours = set(tr.entry_ts); ent_a = set(A.entry_ts)
    return dict(n=len(tr), nA=len(A), both=len(k_ours & k_a), entry_both=len(ent_ours & ent_a),
                only_ours=len(k_ours - k_a), only_A=len(k_a - k_ours))

grid = dict(ema_seed=['first', 'sma', 'adjust'], rsi_method=['wilder_sma', 'wilder_first', 'ewm_adjust', 'ema', 'sma'],
            atr_method=['wilder_sma', 'wilder_first', 'sma'], minmax_minp=['full', 'one'], cross=['le', 'lt'], tr0=['hl', 'nan'])
which = sys.argv[1] if len(sys.argv) > 1 else 'short'
rows = []
t0 = time.time()
for combo in itertools.product(*grid.values()):
    pr = dict(zip(grid.keys(), combo))
    w, A = W[which]
    tr = ds.simulate(w, pr)
    m = match(tr, A)
    rows.append({**pr, **m})
res = pd.DataFrame(rows).sort_values(['both', 'entry_both'], ascending=False)
res.to_csv(f'replicate_grid_{which}.csv', index=False)
print(res.head(25).to_string()); print('elapsed', time.time() - t0)
