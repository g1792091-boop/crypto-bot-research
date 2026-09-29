"""Build full/, is/, oos/, final/ files for one coin from the stitched 5m series.
Resample rules: UTC, open-labelled, left-closed bins; O=first, H=max, L=min, C=last, V=sum over the available
5m bars; bins with zero bars dropped; only bins lying entirely inside the window [start, end) are kept (so no
partial leading/trailing bins and no leakage across split boundaries); for the open-ended window the in-progress
last bin (bin end > last 5m bar end) is dropped. 1w bins start Monday 00:00 UTC (origin 1970-01-05).
usage: build.py coin clean_from(YYYY-MM-DD)"""
import sys, json, pandas as pd, numpy as np
coin, clean_from = sys.argv[1], sys.argv[2]
sym = coin + 'usd'
d = pd.read_csv(f'work/{sym}-5m-stitched-raw.csv'); d['ts'] = pd.to_datetime(d.timestamp, utc=True)
d = d.set_index('ts')[['open', 'high', 'low', 'close', 'volume']]
assert d.index.is_monotonic_increasing and not d.index.duplicated().any()
FIVE = pd.Timedelta(minutes=5)
data_end = d.index[-1] + FIVE                       # exclusive end of available data
TF = {'5m': '5min', '15m': '15min', '30m': '30min', '1h': '1h', '2h': '2h', '4h': '4h', '1d': '1D', '1w': '7D'}
U = lambda s: pd.Timestamp(s, tz='UTC')
WIN = {'full': (d.index[0], data_end), 'is': (U(clean_from), U('2024-07-01')),
       'oos': (U('2024-01-01'), U('2025-08-07')), 'final': (U('2025-02-01'), data_end)}
def resample(x, tf, start, end):
    if tf == '5m':
        o = x.copy(); o['n'] = 1
    else:
        origin = U('1970-01-05') if tf == '1w' else 'epoch'
        r = x.resample(TF[tf], label='left', closed='left', origin=origin)
        o = pd.DataFrame({'open': r.open.first(), 'high': r.high.max(), 'low': r.low.min(),
                          'close': r.close.last(), 'volume': r.volume.sum(), 'n': r.close.count()})
        o = o[o.n > 0]
        width = pd.Timedelta(TF[tf])
        o = o[(o.index >= start) & (o.index + width <= end)]
    return o
def write(o, path):
    w = o[['open', 'high', 'low', 'close', 'volume']].copy()
    w.insert(0, 'ts', o.index.strftime('%Y-%m-%dT%H:%M:%SZ'))
    w.to_csv(path, index=False)
summary = {}
for split, (start, end) in WIN.items():
    x = d[(d.index >= start) & (d.index < end)]
    for tf in TF:
        if split == 'full' and tf == '5m':
            o = x.copy(); o['n'] = 1
        else:
            o = resample(x, tf, start, end)
        need = int(pd.Timedelta(TF[tf]) / FIVE)
        path = f'{split}/{sym}-{tf}.csv'
        write(o, path)
        if split == 'is':
            assert o.index.max() < U('2024-07-01') and (o.index + pd.Timedelta(TF[tf])).max() <= U('2024-07-01'), 'IS leak'
        summary[path] = dict(rows=int(len(o)), first=o.index[0].strftime('%Y-%m-%dT%H:%M:%SZ'),
                             last=o.index[-1].strftime('%Y-%m-%dT%H:%M:%SZ'),
                             partial_bins=int((o.n < need).sum()), constituent_5m_bars=int(o.n.sum()))
json.dump(summary, open(f'work/build_{coin}.json', 'w'), indent=1)
print(coin, 'files', len(summary))
