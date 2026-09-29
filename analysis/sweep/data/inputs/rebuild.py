"""Rebuild every sweep input file (full/ is/ oos/ final/ x 8 TFs x 7 coins = 224 files) from the 7 committed
5m base series (<coin>usd-5m.csv.xz, = full/<coin>usd-5m.csv) and check each against MANIFEST.json sha256.
Same resample rules as ../tools/build.py.  usage: python3 rebuild.py [out_dir]   (default ../ i.e. analysis/sweep/data)
fixups.csv.xz restores the original text of 1,043 lines (62 files) whose volume differs from a fresh resample only in
the last floating-point digit (summation order); prices and timestamps are identical either way.
Then point the sweep at it (default location) or set SWEEP_DATA=<out_dir>."""
import os, sys, json, lzma, hashlib, io
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(HERE)
MAN = json.load(open(os.path.join(os.path.dirname(HERE), "MANIFEST.json")))
TF = {'5m': '5min', '15m': '15min', '30m': '30min', '1h': '1h', '2h': '2h', '4h': '4h', '1d': '1D', '1w': '7D'}
U = lambda s: pd.Timestamp(s, tz='UTC'); FIVE = pd.Timedelta(minutes=5)

def resample(x, tf, start, end):
    origin = U('1970-01-05') if tf == '1w' else 'epoch'
    r = x.resample(TF[tf], label='left', closed='left', origin=origin)
    o = pd.DataFrame({'open': r.open.first(), 'high': r.high.max(), 'low': r.low.min(),
                      'close': r.close.last(), 'volume': r.volume.sum(), 'n': r.close.count()})
    o = o[o.n > 0]
    return o[(o.index >= start) & (o.index + pd.Timedelta(TF[tf]) <= end)]

def write(o, path):
    w = o[['open', 'high', 'low', 'close', 'volume']].copy()
    w.insert(0, 'ts', o.index.strftime('%Y-%m-%dT%H:%M:%SZ'))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    w.to_csv(path, index=False)

import csv
FIX = {}
for r in csv.DictReader(lzma.open(os.path.join(HERE, "fixups.csv.xz"), "rt")):
    FIX.setdefault(r["file"], {})[int(r["line"])] = r["original"]

def fixup(rel, path):
    if rel in FIX:
        lines = open(path).read().split("\n")
        for i, t in FIX[rel].items():
            lines[i] = t
        open(path, "w").write("\n".join(lines))

ok = bad = 0
for coin, clean_from in MAN["clean_from"].items():
    raw = lzma.open(os.path.join(HERE, f"{coin}-5m.csv.xz"), "rt").read()
    d = pd.read_csv(io.StringIO(raw)); d.index = pd.to_datetime(d.pop("ts"), utc=True)
    end = d.index[-1] + FIVE
    WIN = {'full': (d.index[0], end), 'is': (U(clean_from), U('2024-07-01')),
           'oos': (U('2024-01-01'), U('2025-08-07')), 'final': (U('2025-02-01'), end)}
    for split, (a, b) in WIN.items():
        x = d[(d.index >= a) & (d.index < b)]
        for tf in TF:
            rel = f"{split}/{coin}-{tf}.csv"
            path = os.path.join(OUT, rel)
            if split == 'full' and tf == '5m':
                os.makedirs(os.path.dirname(path), exist_ok=True); open(path, "w").write(raw)
            else:
                write(x if tf == '5m' else resample(x, tf, a, b), path)
                fixup(rel, path)
            h = hashlib.sha256(open(path, "rb").read()).hexdigest()
            want = MAN["files"].get(rel, {}).get("sha256")
            if h == want: ok += 1
            else: bad += 1; print("MISMATCH", rel)
print(f"sha256 match {ok} / {ok + bad}")
