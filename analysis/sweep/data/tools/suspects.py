"""Suspect single-bar spikes. Flags bar t when
  ratio = rng_t / medR_t > 8, rng=(h-l)/prev_close, medR = rolling median of rng over the previous 288 bars
  (excludes bar t, min 72 bars, floored at 5bp), AND the excursion fully reverts:
  E = max(h_t - c_{t-1}, c_{t-1} - l_t);  'wick'  : |c_t - c_{t-1}| <= 0.25*E  (retraced inside the bar)
                                          'close' : |c_t - c_{t-1}| >  0.25*E and |c_{t+1} - c_{t-1}| <= 0.25*E
  AND it is isolated ("single-bar"): rng of bar t-1 and of the first bar after the reversion < 4*medR.
  Bars t-1/t+1 must be contiguous (5m apart). Nothing is clipped; this only lists.
usage: suspects.py out.csv coin [coin...]"""
import sys, pandas as pd, numpy as np
out = sys.argv[1]; rows = []
for c in sys.argv[2:]:
    d = pd.read_csv(f'work/{c}usd-5m-stitched-raw.csv'); d['ts'] = pd.to_datetime(d.timestamp, utc=True); d = d.set_index('ts')
    o, h, l, cl = d.open, d.high, d.low, d.close
    pc = cl.shift(1); nc = cl.shift(-1)
    step = pd.Timedelta(minutes=5)
    idx = d.index.to_series()
    cont_prev = (idx - idx.shift(1)) == step
    cont_next = (idx.shift(-1) - idx) == step
    cont_next2 = (idx.shift(-2) - idx.shift(-1)) == step
    rng = (h - l) / pc
    medr = rng.shift(1).rolling(288, min_periods=72).median().clip(lower=0.0005)
    ratio = rng / medr
    E = np.maximum(h - pc, pc - l)
    wick = (cl - pc).abs() <= 0.25 * E
    closev = (~wick) & ((nc - pc).abs() <= 0.25 * E) & cont_next
    iso_prev = (rng.shift(1) < 4 * medr)
    iso_after_w = (rng.shift(-1) < 4 * medr) & cont_next
    iso_after_c = (rng.shift(-2) < 4 * medr) & cont_next2
    base = (ratio > 8) & cont_prev & iso_prev
    fw = base & wick & iso_after_w
    fc = base & closev & iso_after_c
    for kind, m in (('wick', fw), ('close', fc)):
        for t in d.index[m.fillna(False).values]:
            side = 'up' if (h[t] - pc[t]) >= (pc[t] - l[t]) else 'down'
            rows.append(dict(symbol=c.upper() + 'USD', ts=t.strftime('%Y-%m-%dT%H:%M:%SZ'), kind=kind, side=side,
                             prev_close=pc[t], open=o[t], high=h[t], low=l[t], close=cl[t], next_close=nc[t],
                             volume=d.volume[t], range_pct=round(rng[t] * 100, 4), med_range_pct=round(medr[t] * 100, 4),
                             ratio=round(ratio[t], 2), excursion_pct=round(E[t] / pc[t] * 100, 4)))
    print(c, 'wick', int(fw.sum()), 'close', int(fc.sum()), ' (no-isolation count:', int(((ratio > 8) & cont_prev & (wick | closev)).sum()), ')')
s = pd.DataFrame(rows).sort_values(['symbol', 'ts'])
s.to_csv(out, index=False)
print('total', len(s))
