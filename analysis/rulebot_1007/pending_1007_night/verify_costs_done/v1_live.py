# Live trades from the RAW export: R identity, cost decomposition, SL overshoot, LOCK gap. Own code.
import sys, os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'boot.py')).read())
import numpy as np, pandas as pd
E, OUT = sys.argv[1], sys.argv[2]
RUNS = {'run-20261005T014624Z': 'v3a', 'run-20261005T183457Z': 'v3b', 'current': 'v4'}
SL = 2e-4
rows = []
for r, tag in RUNS.items():
    t = pd.read_csv(f'{E}/{r}/trades.csv', usecols=lambda c: c != 'context')
    a = pd.read_csv(f'{E}/{r}/accounts.csv')[['account_id', 'kind']]
    t = t.merge(a, on='account_id', how='left'); t['run'] = tag
    rows.append(t)
T = pd.concat(rows, ignore_index=True)
T = T[T.exit_reason.notna() & T.exit_price.notna()]
s = T.side.astype(float); q = T.qty; Ef = T.entry_price; Xf = T.exit_price
risk = q * (Ef - T.stop_initial).abs()
# pnl identity check
pnl_chk = s * q * (Xf - Ef) - T.fees - T.funding
print('pnl identity max abs err', float((pnl_chk - T.pnl).abs().max()), 'n', len(T))
T['R'] = T.pnl / risk
Eref = Ef / (1 + s * SL); Xref = Xf / (1 - s * SL)
T['feeR'] = T.fees / risk; T['fundR'] = T.funding / risk
T['slipinR'] = q * (Ef - Eref).abs() / risk; T['slipoutR'] = q * (Xf - Xref).abs() / risk
T['grossR'] = T.R + T.feeR + T.fundR + T.slipinR + T.slipoutR
T['costR'] = T.grossR - T.R
T['stop_pct'] = (Ef - T.stop_initial).abs() / Ef
# cluster = 2h block of entry time (signals minutes apart on correlated coins are not independent)
T['cl'] = T.run + '_' + (T.entry_time // 7_200_000).astype(str)
rng = np.random.default_rng(1)
def ci(df, col, B=1000):
    g = df.groupby('cl')[col].agg(['sum', 'count']); S = g['sum'].values; N = g['count'].values; k = len(g)
    bs = [S[i].sum() / N[i].sum() for i in (rng.integers(0, k, k) for _ in range(B))]
    return np.percentile(bs, [2.5, 97.5]), k
T['grp'] = np.where(T.kind == 'strategy', 'core36', T.kind)
out = []
for (g, tf), d in T[T.kind.isin(['strategy', 'ds200', 'random'])].groupby(['grp', 'timeframe']):
    lo_hi, k = ci(d, 'grossR')
    out.append(dict(grp=g, tf=tf, n=len(d), clusters=k, netR=d.R.mean(), grossR=d.grossR.mean(), g_lo=lo_hi[0], g_hi=lo_hi[1],
                    costR=d.costR.mean(), feeR=d.feeR.mean(), slip_in=d.slipinR.mean(), slip_out=d.slipoutR.mean(), fund=d.fundR.mean(),
                    med_stop_pct=100 * d.stop_pct.median(), liq=(d.exit_reason == 'LIQ').sum(), lev_med=d.leverage.median()))
O = pd.DataFrame(out); O.to_csv(f'{OUT}/v1_live_by_tf.csv', index=False)
print(O.round(3).to_string())
# SL overshoot and LOCK gap
sl = T[(T.exit_reason == 'SL') & T.kind.isin(['strategy', 'ds200'])].copy()
sl['gap_bp'] = 1e4 * s[sl.index] * (sl.stop_initial - Xref[sl.index]) / sl.entry_price  # >0 = filled worse than stop (excl. slip)
print('SL by tf: n, meanR, fee, slipout, share |gap|<0.1bp')
print(sl.groupby('timeframe').apply(lambda d: pd.Series(dict(n=len(d), R=d.R.mean(), fee=d.feeR.mean(), so=d.slipoutR.mean(), gapR=(d.gap_bp*1e-4*d.entry_price*d.qty/ (d.qty*(d.entry_price-d.stop_initial).abs())).mean(), at_stop=(d.gap_bp.abs() < 0.1).mean()))).round(4).to_string())
lk = T[(T.exit_reason == 'LOCK') & T.kind.isin(['strategy', 'ds200'])].copy()
gp = s[lk.index] * (lk.stop_price - Xref[lk.index]) / lk.entry_price * 1e4  # bp beyond lock level
lk['gap_bp'] = gp; lk['gapR'] = gp * 1e-4 * lk.entry_price / (lk.entry_price - lk.stop_initial).abs()
print('LOCK by tf: n, share gapped>0.1bp, mean gap bp, mean gapR, lev median, grossR, costR')
print(lk.groupby('timeframe').apply(lambda d: pd.Series(dict(n=len(d), gapped=(d.gap_bp > 0.1).mean(), gap_bp=d.gap_bp.clip(lower=0).mean(), gapR=d.gapR.clip(lower=0).mean(), lev=d.leverage.median(), gross=d.grossR.mean(), cost=d.costR.mean()))).round(3).to_string())
print('exit reasons strategy/ds200:', T[T.kind.isin(['strategy','ds200'])].exit_reason.value_counts().to_dict())
T.drop(columns=[c for c in T.columns if c in ('context',)]).to_csv(f'{OUT}/v1_trades.csv.gz', index=False)
