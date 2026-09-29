"""Check TSL stop level / watermark / stage vs Astral's risk_exit events, and test rejected alternatives."""
import json, numpy as np, pandas as pd
import doge_strategy as ds
df = ds.load_ohlcv('dogeusd-5m-last40k.csv')
w = df.loc['2026-05-13 03:05':'2026-09-28 23:55']
A = pd.read_csv('astral/backtest-bt_eabbc51538b849c6_trades.csv', parse_dates=['entry_ts', 'exit_ts'])
tr = ds.simulate(w)
m = tr.merge(A, on=['entry_ts', 'exit_ts'], suffixes=('', '_A'))
t = m[m.reason == 'tsl']
stage_map = {0: 'initial_risk', 1: 'profit_lock_1', 2: 'trend_runner'}
print('TSL exits', len(t), 'stop level max rel diff', np.nanmax(np.abs(t.stop_px / t.tsl_level - 1)),
      'watermark max rel diff', np.nanmax(np.abs(t.watermark / t.tsl_wm - 1)),
      'stage agree', (t.tsl_stage.map(stage_map) == t.tsl_stage_A).mean())
# fill vs stop: how often the close-fill is better/worse than the stop price
t = t.assign(fill_minus_stop_pct=(t.exit_px / t.stop_px - 1) * 100)
print('Astral TSL fill (close) relative to stop, %: mean', round(t.fill_minus_stop_pct.mean(), 4), 'median', round(t.fill_minus_stop_pct.median(), 4),
      'share fill>stop', round((t.fill_minus_stop_pct > 0).mean(), 3))
def cmp(label, **kw):
    params = kw.pop('params', None)
    r = ds.simulate(w, params, **kw)
    k1 = set(zip(r.entry_ts, r.exit_ts)); k2 = set(zip(A.entry_ts, A.exit_ts))
    s = ds.summarize(r, col='gross')
    print(f'{label:45s} n={len(r):4d} matched={len(k1 & k2):4d}/{len(A)}  WR={s["win_rate"]:.3f} mean={s["mean_pct"]:+.4f}% PF={s["pf"]:.3f} TR25={s["total_ret_pct"]:+.3f}%')
cmp('ASTRAL conventions (default)')
cmp('ATR Wilder (TA-Lib)', params=dict(atr_method='wilder_sma'))
cmp('RSI EMA 2/(n+1)', params=dict(rsi_method='ema'))
cmp('RSI Cutler SMA', params=dict(rsi_method='sma'))
cmp('EMA SMA-seeded', params=dict(ema_seed='sma'))
cmp('MIN/MAX exclude current bar', params=dict(minmax_include_current=False))
cmp('no same-bar suppression after TSL', params=dict(suppress_after_tsl=False))
cmp('stage boundary strict >', params=dict(stage_boundary='gt'))
cmp('CROSS strict <', params=dict(cross='lt'))
for mode in ['ohl_stop', 'olh_stop', 'close_only']:
    cmp(f'TSL {mode}', tsl_eval=mode)
cmp('fill next_open', fill='next_open')
cmp('no TSL (signal exits only)', params=dict(use_tsl=False))
