"""Trade-level comparison of the port (Astral conventions, zero cost) vs Astral's own trade lists."""
import sys, json
import numpy as np, pandas as pd
import doge_strategy as ds

df = ds.load_ohlcv('dogeusd-5m-last40k.csv')
runs = [
    ('bt_4d7868c2f1791cc6', '2026-09-11 00:00', '2026-09-28 23:55', 0.0, 0.0),
    ('bt_eabbc51538b849c6', '2026-05-13 03:05', '2026-09-28 23:55', 0.0, 0.0),
    ('bt_f27f67940a55d5ea', '2026-09-11 00:00', '2026-09-28 23:55', 0.0005, 0.0002),
    ('bt_4f34e72413d4b066', '2026-05-13 03:05', '2026-09-28 23:55', 0.0005, 0.0002),
]
extra = sys.argv[1:]
for x in extra:
    bid, a, b = x.split(',')
    runs.append((bid, a, b, 0.0, 0.0))
for bid, a, b, fee, slip in runs:
    A = pd.read_csv(f'astral/backtest-{bid}_trades.csv', parse_dates=['entry_ts', 'exit_ts'])
    meta = json.load(open(f'astral/backtest-{bid}.json'))
    w = df.loc[a:b]
    tr = ds.simulate(w, costs=dict(fee_side=fee, slip_side=slip, model='astral'))
    # Astral's price-based cost model: buy fill = close*(1+slip), sell fill = close*(1-slip), fee on notional
    tr['astral_ret'] = tr['net']
    m = tr.merge(A, on=['entry_ts', 'exit_ts'], how='outer', suffixes=('', '_A'), indicator=True)
    both = m[m._merge == 'both']
    pxd = np.maximum(np.abs(both.entry_px * (1 + slip) / both.entry_px_A - 1), np.abs(both.exit_px * (1 - slip) / both.exit_px_A - 1))
    reason_eq = (both.reason == both.reason_A).mean() if len(both) else np.nan
    rd = np.abs(both.astral_ret - both.ret)
    ours = ds.astral_metrics(tr, w, col='astral_ret', start_ts=meta['backtest_period']['warmup_end'], slip=slip)
    pm, ts = meta['performance_metrics'], meta['trade_statistics']
    print(f'== {bid} {a}..{b} fee={fee} slip={slip}')
    print(f'   trades ours={len(tr)} astral={len(A)} matched(entry&exit ts)={len(both)} only_ours={(m._merge=="left_only").sum()} only_astral={(m._merge=="right_only").sum()}'
          f' reason_agree={reason_eq:.3f} max|px diff|={pxd.max():.2e} max|ret diff|={rd.max():.2e}')
    print('   ours  :', {k: round(v, 6) for k, v in ours.items()})
    print('   astral:', dict(total_trades=ts['total_trades'], win_rate=round(ts['win_rate'], 6), profit_factor=round(pm['profit_factor'], 6),
                            average_trade_return=round(ts['average_trade_return'], 6), total_return=round(pm['total_return'], 6), max_drawdown=round(pm['max_drawdown'], 6)))
    bad = m[(m._merge != 'both')]
    if len(bad):
        print(bad[['entry_ts', 'exit_ts', 'entry_px', 'exit_px', 'entry_px_A', 'exit_px_A', 'reason', 'reason_A', '_merge']].to_string())
    diff = both[pxd > 1e-9]
    if len(diff):
        print('   price mismatches:'); print(diff[['entry_ts', 'exit_ts', 'entry_px', 'entry_px_A', 'exit_px', 'exit_px_A', 'reason', 'reason_A']].to_string())
