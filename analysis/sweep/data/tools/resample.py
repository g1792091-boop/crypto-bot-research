"""resample open-labelled OHLCV. usage: resample.py in.csv out.csv RULE(e.g. 15min) base_min"""
import sys, pandas as pd
src, dst, rule, base = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
d = pd.read_csv(src); d['ts'] = pd.to_datetime(d.timestamp, utc=True); d = d.set_index('ts')
r = d.resample(rule, label='left', closed='left')
o = pd.DataFrame({'open': r.open.first(), 'high': r.high.max(), 'low': r.low.min(), 'close': r.close.last(),
                  'volume': r.volume.sum(), 'n': r.close.count()})
need = int(pd.Timedelta(rule) / pd.Timedelta(minutes=base))
o = o[o.n > 0]
# drop trailing incomplete bin (in-progress)
last_end = o.index[-1] + pd.Timedelta(rule)
if o.n.iloc[-1] < need and d.index[-1] + pd.Timedelta(minutes=base) < last_end:
    o = o.iloc[:-1]
partial = int((o.n < need).sum())
o['timestamp'] = o.index.strftime('%Y-%m-%dT%H:%M:%S+0000')
o[['timestamp', 'open', 'high', 'low', 'close', 'volume']].to_csv(dst, index=False)
print(dst, 'rows', len(o), 'partial_bins(<%d constituents)' % need, partial, 'first', o.index[0], 'last', o.index[-1])
