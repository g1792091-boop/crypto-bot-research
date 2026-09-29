"""compare two OHLCV csv on common timestamps. usage: compare.py a.csv b.csv [label]"""
import sys, pandas as pd, numpy as np
a = pd.read_csv(sys.argv[1]); b = pd.read_csv(sys.argv[2])
for x in (a, b): x['ts'] = pd.to_datetime(x.timestamp, utc=True)
m = a.merge(b, on='ts', suffixes=('_a', '_b'))
print(sys.argv[3] if len(sys.argv) > 3 else '', 'a rows', len(a), 'b rows', len(b), 'common', len(m),
      'only_a', len(set(a.ts) - set(b.ts)), 'only_b', len(set(b.ts) - set(a.ts)))
for c in ['open', 'high', 'low', 'close', 'volume']:
    r = (m[c+'_a'] / m[c+'_b'] - 1).abs()
    print(f'  {c:6s} exact={float((r<1e-12).mean())*100:7.3f}%  >1bp={int((r>1e-4).sum()):6d}  >10bp={int((r>1e-3).sum()):5d}  max={r.max()*100:.4f}%  p999={r.quantile(.999)*100:.4f}%')
bad = m[((m.close_a/m.close_b-1).abs() > 1e-3) | ((m.high_a/m.high_b-1).abs() > 1e-3) | ((m.low_a/m.low_b-1).abs() > 1e-3)]
if len(bad):
    print('  worst rows:')
    bad = bad.assign(err=np.maximum.reduce([(bad.close_a/bad.close_b-1).abs(), (bad.high_a/bad.high_b-1).abs(), (bad.low_a/bad.low_b-1).abs()]))
    print(bad.sort_values('err', ascending=False).head(8)[['ts','open_a','open_b','high_a','high_b','low_a','low_b','close_a','close_b','volume_a','volume_b']].to_string())
