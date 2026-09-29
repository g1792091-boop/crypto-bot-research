"""Merge csvs; on duplicate timestamps keep the FIRST listed file's row (priority order).
usage: merge_priority.py out.csv start_iso file1 [file2 ...]"""
import sys, pandas as pd
out, start = sys.argv[1], sys.argv[2]
parts = []
for i, f in enumerate(sys.argv[3:]):
    d = pd.read_csv(f); d['prio'] = i; d['src'] = f.split('/')[-1]; parts.append(d)
a = pd.concat(parts, ignore_index=True)
a['ts'] = pd.to_datetime(a.timestamp, utc=True)
a = a[a.ts >= pd.Timestamp(start)]
a = a.sort_values(['ts', 'prio']).drop_duplicates('ts', keep='first').sort_values('ts')
a['timestamp'] = a.ts.dt.strftime('%Y-%m-%dT%H:%M:%S+0000')
a[['timestamp', 'open', 'high', 'low', 'close', 'volume']].to_csv(out, index=False)
print(out, 'rows', len(a), a.timestamp.iloc[0], '->', a.timestamp.iloc[-1], 'rows by source:', a.src.value_counts().to_dict())
