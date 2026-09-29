"""Compare my resampled bars with direct Astral pulls. usage: xcheck.py mine.csv astral.csv [from_ts]"""
import sys, json, pandas as pd, numpy as np
a = pd.read_csv(sys.argv[1]); a['ts'] = pd.to_datetime(a.ts, utc=True); a = a.set_index('ts')
b = pd.read_csv(sys.argv[2]); b['ts'] = pd.to_datetime(b.timestamp, utc=True); b = b.set_index('ts')[['open','high','low','close','volume']]
if len(sys.argv) > 3:
    f = pd.Timestamp(sys.argv[3], tz='UTC'); a = a[a.index >= f]; b = b[b.index >= f]
lo, hi = max(a.index.min(), b.index.min()), min(a.index.max(), b.index.max())
a = a[(a.index >= lo) & (a.index <= hi)]; b = b[(b.index >= lo) & (b.index <= hi)]
common = a.index.intersection(b.index)
res = dict(window=[str(lo), str(hi)], mine_bars=len(a), astral_bars=len(b), common=len(common),
           only_mine=[str(t) for t in a.index.difference(b.index)][:10], only_astral=[str(t) for t in b.index.difference(a.index)][:10],
           n_only_mine=len(a.index.difference(b.index)), n_only_astral=len(b.index.difference(a.index)))
x, y = a.loc[common], b.loc[common]
for c in ['open', 'high', 'low', 'close', 'volume']:
    r = ((x[c] - y[c]).abs() / y[c].abs().clip(lower=1e-12))
    res[c] = dict(exact=round(float((r <= 1e-9).mean()) * 100, 3), within_1bp=round(float((r <= 1e-4).mean()) * 100, 3),
                  within_10bp=round(float((r <= 1e-3).mean()) * 100, 3), max_rel=float(r.max()), n_gt_1pct=int((r > 0.01).sum()),
                  worst_ts=str(r.idxmax()))
print(json.dumps(res, indent=1))
