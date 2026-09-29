"""Stitch chained Astral pulls, check seams, write canonical CSV.
usage: stitch.py <out_csv> <freq_minutes> <pull1.csv> [pull2.csv ...]   (pulls in any order)
"""
import sys, pandas as pd, numpy as np, json
out, fm = sys.argv[1], int(sys.argv[2])
files = sys.argv[3:]
dfs = []
for f in files:
    d = pd.read_csv(f)
    d['ts'] = pd.to_datetime(d['timestamp'], utc=True)
    d['src'] = f.split('/')[-1]
    dfs.append(d)
dfs.sort(key=lambda d: d.ts.iloc[0])
seams = []
for a, b in zip(dfs[:-1], dfs[1:]):
    ov = pd.merge(a, b, on='ts', suffixes=('_a', '_b'))
    diff = 0
    maxrel = 0.0
    if len(ov):
        for c in ['open', 'high', 'low', 'close']:
            r = (ov[c+'_a'] - ov[c+'_b']).abs() / ov[c+'_b']
            maxrel = max(maxrel, float(r.max()))
            diff += int((r > 1e-12).sum())
        vr = ((ov['volume_a'] - ov['volume_b']).abs() / ov['volume_b'].clip(lower=1e-12))
    gap_min = (b.ts.iloc[0] - a.ts.iloc[-1]).total_seconds() / 60
    seams.append(dict(a=a.src.iloc[0], b=b.src.iloc[0], a_last=str(a.ts.iloc[-1]), b_first=str(b.ts.iloc[0]),
                      overlap_bars=len(ov), overlap_price_mismatch_cells=diff, overlap_max_rel_diff=maxrel,
                      overlap_vol_max_rel=float(vr.max()) if len(ov) else None,
                      step_minutes_across_seam=gap_min))
allp = pd.concat(dfs, ignore_index=True)
nd_before = len(allp)
# keep the newer pull's version on overlap (later in list = newer data in time? use the pull whose range is later)
allp = allp.sort_values(['ts'], kind='mergesort').drop_duplicates('ts', keep='last')
allp = allp.sort_values('ts').reset_index(drop=True)
allp['timestamp'] = allp.ts.dt.strftime('%Y-%m-%dT%H:%M:%S+0000')
allp[['timestamp', 'open', 'high', 'low', 'close', 'volume']].to_csv(out, index=False)
# misalignment check
mis = int(((allp.ts.astype('int64') // 10**9) % (fm*60) != 0).sum())
print(json.dumps(dict(out=out, rows=len(allp), dup_removed=nd_before-len(allp), misaligned=mis,
                      first=str(allp.ts.iloc[0]), last=str(allp.ts.iloc[-1]), seams=seams), indent=1))
