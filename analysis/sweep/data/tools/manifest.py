"""Build MANIFEST.json for the final data files (computes every number from the files themselves)."""
import json, hashlib, os, pandas as pd

D = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = os.path.join(D, 'raw')
WIN = (pd.Timestamp('2026-09-13T00:00Z'), pd.Timestamp('2026-09-28T23:59Z'))  # friend's backtest window


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def stats(path, fm):
    d = pd.read_csv(path)
    t = pd.to_datetime(d.timestamp, utc=True)
    step = pd.Timedelta(minutes=fm)
    dt = t.diff()
    g = dt[dt > step]
    exp = int((t.iloc[-1] - t.iloc[0]) / step) + 1
    big = [(str(t[i] - dt[i] + step), str(t[i] - step), int(dt[i] / step) - 1)
           for i in g.index if dt[i] >= pd.Timedelta(hours=1)]
    w = t[(t >= WIN[0]) & (t <= WIN[1])]
    wexp = len(pd.date_range(WIN[0], WIN[1].floor(f'{fm}min'), freq=f'{fm}min'))
    o, h, l, c = d.open, d.high, d.low, d.close
    bad = int(((h < o.combine(c, max) - 1e-12) | (l > o.combine(c, min) + 1e-12) | (h < l)).sum())
    return dict(rows=len(d), first_ts=d.timestamp.iloc[0], last_ts=d.timestamp.iloc[-1],
                timeframe=f'{fm}m' if fm < 60 else f'{fm // 60}h',
                expected_slots=exp, missing_slots=exp - len(d), missing_pct=round((exp - len(d)) / exp * 100, 4),
                gap_events=len(g), max_gap=str(g.max()) if len(g) else None,
                gaps_ge_1h_missing_ranges=[dict(first_missing=a, last_missing=b, bars=n) for a, b, n in big],
                duplicates=int(t.duplicated().sum()), ohlc_inconsistent=bad,
                nan_rows=int(d.isna().any(axis=1).sum()), vol_le_0=int((d.volume <= 0).sum()),
                strategy_window_2026_09_13_to_28=dict(rows=len(w), expected=wexp, missing=wexp - len(w)),
                bytes=os.path.getsize(path), sha256=sha(path))


def attribute(final, sources):
    """count final rows by first source (priority order) that contains the timestamp with identical OHLCV"""
    f = pd.read_csv(final).set_index('timestamp')
    left = f.index
    out = {}
    for name in sources:
        s = pd.read_csv(os.path.join(R, name)).drop_duplicates('timestamp').set_index('timestamp')
        common = left.intersection(s.index)
        a, b = f.loc[common].values, s.loc[common, f.columns].values
        # 1e-12 relative tolerance: pandas' default float parser can differ in the last ulp on long volumes
        same = (abs(a - b) <= 1e-12 * abs(b)).all(axis=1)
        out[name] = int(same.sum())
        left = left.difference(common[same])
    out['unattributed'] = len(left)
    return out


files = {}
doge_notes = {
    'dogeusd-5m-ohlcv.csv': dict(
        fm=5, clean_from='2021-08-01',
        clean_from_tick_sensitive='2022-06-01',
        sources='raw/doge5m_p01..p16 (16 chained astral_price_get pulls, limit=40000, end-chained; p16 limit=3700); trimmed to >=2021-01-01',
        notes=[
            '2021-01..2021-06-02 corrupted by cross-venue mixing (2021Q2 median bar range 26.3%, 5,113 open-vs-prev-close jumps >2%, 3,129 3%-spikes); isolated bad wicks persist through 2021-07-31 (June 267, July 10, August 0).',
            'Until 2022-05-31 ~87% of closes have <=4 decimals (0.0001 tick = 0.03-0.17% of price), comparable to the strategy trail distances 0.20-0.35%; use 2022-06-01+ for tick-sensitive trailing-stop work.',
            'Whole day 2026-04-22 missing (288 bars) - present in every Astral crypto series checked.',
            '2026-09-29 06:00-07:05 missing (14 bars) in 5m; still missing in a 09:40 re-pull; present in 1m and direct 15m.',
            'Single-bar bad lows inside clean range: 2021-10-21 11:30/11:35 (0.176 / 0.150 vs ~0.25), 2026-05-17 23:40 (0.081 vs ~0.109).',
            'Re-pull at 09:40 UTC of 2026-09-27 06:30..09-29 09:35: 596 common bars byte-identical in OHLC (volume 99.66% exact).',
        ]),
    'dogeusd-15m-ohlcv.csv': dict(
        fm=15, clean_from='2021-08-01', sources='resampled from dogeusd-5m-ohlcv.csv (tools/resample.py, open-labelled, left-closed, partial bins kept, trailing incomplete bin dropped)',
        notes=['68 bins built from <3 5m bars (partial).',
               'Spot-check vs direct 15m pull (raw/doge15m_p01.csv, last 40,000 bars): close exact on all common bins; O/H/L >=99.99% exact; differences only at 5m-missing bins (2026-09-29 06:00-07:00) and 2 isolated bins (2026-05-13 11:45 low, 2026-07-21 22:30 open/high); 21 volume mismatches.']),
    'dogeusd-1h-ohlcv.csv': dict(
        fm=60, clean_from='2021-08-01', sources='resampled from dogeusd-5m-ohlcv.csv (same method as 15m)',
        notes=['62 bins built from <12 5m bars (partial).']),
    'dogeusd-1m-ohlcv.csv': dict(
        fm=1, clean_from='file start (2026-09-01T14:24)', sources='raw/doge1m_p01.csv (last 40,000 1m bars, one pull)',
        notes=['1m->5m vs 5m file: close exact 99.862%, 9 bins >1bp (max 0.063%), 50 volume mismatches - 1m and 5m are close but not identical; intrabar replays from 1m will not exactly match 5m OHLC.',
               'Missing 1m bars are no-trade minutes (sporadic single minutes).']),
}
coin_src = {
    'btcusd-5m-ohlcv.csv': ['btc5m_recheck.csv', 'btc5m_fresh.csv', 'btc5m_stage1.csv', 'btc5m_bridge.csv', 'btc5m_ext.csv', 'btc5m_head.csv'],
    'ethusd-5m-ohlcv.csv': ['eth5m_bridge2.csv', 'eth5m_fresh.csv', 'eth5m_stage1.csv', 'eth5m_bridge.csv', 'eth5m_ext.csv', 'eth5m_head.csv'],
    'solusd-5m-ohlcv.csv': ['sol5m_fresh.csv', 'sol5m_stage1.csv', 'sol5m_bridge.csv', 'sol5m_ext.csv', 'sol5m_head.csv'],
    'xrpusd-5m-ohlcv.csv': ['xrp5m_p01.csv', 'xrp5m_p02.csv', 'xrp5m_p03.csv', 'xrp5m_p04.csv', 'xrp5m_head.csv'],
    'ltcusd-5m-ohlcv.csv': ['ltc5m_p01.csv', 'ltc5m_p02.csv', 'ltc5m_p03.csv', 'ltc5m_p04.csv', 'ltc5m_head.csv'],
    'bchusd-5m-ohlcv.csv': ['bch5m_p01.csv', 'bch5m_p02.csv', 'bch5m_p03.csv', 'bch5m_p04.csv', 'bch5m_head.csv'],
}
coin_notes = {
    'btcusd-5m-ohlcv.csv': ['fresh/ and data/ copies = verbatim repo files (sha256 matched expected_sha256.txt / sha256_uncompressed.txt); bridge = Astral pull 2026-05-06T13:20..05-13T11:55 closing the 05-12/05-13 seam; ext/recheck = latest tail pulls; head = 2025-03-19 prefix.',
                            'Tail 2026-09-28T23:40..09-29T09:35 taken from the 09:40 re-pull (latest wins): vs the ~09:25 pull, 14 previously-missing bars appeared (09-29 05:05-05:25, 07:05-07:45) plus 2 new tail bars, close exact on only 67.3% of 104 common bars (max 0.13%), volume exact 54.8%.'],
    'ethusd-5m-ohlcv.csv': ['Repo stage-1 ETH file (pulled ~03:57 UTC) has a hole 2026-09-27 20:30..09-28 15:40 (inside the backtest window); filled by raw/eth5m_bridge2.csv (09:40 pull) which also replaced 49 overlapping stage-1 bars: close exact on only 36.7% of them (max 0.063%), volume 2% exact - ETH bars ~36h old were still being revised.',
                            'head = 2025-03-19 prefix.'],
    'solusd-5m-ohlcv.csv': ['2025-03-25 whole day missing (also in repo fresh file, XRP and LTC).'],
    'xrpusd-5m-ohlcv.csv': ['2025-03-25 whole day missing.'],
    'ltcusd-5m-ohlcv.csv': ['2025-03-25 whole day missing.'],
    'bchusd-5m-ohlcv.csv': ['Illiquid: 173 gap events (sporadic no-trade 5m slots), flat bars up to 0.45%/quarter; open!=prev close ~91-93%.'],
}
for fn, meta in doge_notes.items():
    s = stats(os.path.join(D, fn), meta['fm'])
    files[fn] = dict(path=os.path.join(D, fn), **s, clean_from=meta['clean_from'], sources=meta['sources'], notes=meta['notes'])
    if 'clean_from_tick_sensitive' in meta:
        files[fn]['clean_from_tick_sensitive'] = meta['clean_from_tick_sensitive']
for fn, srcs in coin_src.items():
    s = stats(os.path.join(D, fn), 5)
    files[fn] = dict(path=os.path.join(D, fn), **s,
                     clean_from='2025-03-19 (whole file; no corruption signature in quarterly QA)' if fn not in ('solusd-5m-ohlcv.csv', 'xrpusd-5m-ohlcv.csv', 'ltcusd-5m-ohlcv.csv') else '2025-03-26 if continuous data needed (2025-03-25 missing); otherwise 2025-03-19',
                     rows_by_source_priority_order=attribute(os.path.join(D, fn), srcs),
                     merge_policy='first-listed source wins on duplicate timestamps (order = rows_by_source keys)',
                     notes=['All series: 2026-04-22 whole day missing (vendor-wide).'] + coin_notes[fn])

raw = []
for line in open(os.path.join(R, 'sha256_verified.txt')):
    n, h = line.split()
    p = os.path.join(R, n)
    raw.append(dict(file='raw/' + n, sha256=h, verified_now=(sha(p) == h) if os.path.exists(p) else None))

m = dict(
    generated_utc=pd.Timestamp.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
    data_dir=D,
    astral_calls=dict(total=46, symbol_resolve=1, price_get=45, backtests=0,
                      note='every price_get used delivery=download; every artifact sha256-verified (raw_pulls). Never used start+end together.'),
    timestamp_convention='UTC bar-open, ISO like 2026-05-13T05:10:00+0000',
    strategy_window='2026-09-13T00:00Z..2026-09-28T23:55Z',
    files=files,
    raw_pulls=raw,
)
with open(os.path.join(D, 'MANIFEST.json'), 'w') as f:
    json.dump(m, f, indent=1)
print(json.dumps({k: {kk: v[kk] for kk in ('rows', 'first_ts', 'last_ts', 'missing_slots', 'gap_events', 'max_gap', 'strategy_window_2026_09_13_to_28', 'ohlc_inconsistent', 'duplicates')} | ({'src': v['rows_by_source_priority_order']} if 'rows_by_source_priority_order' in v else {}) for k, v in files.items()}, indent=1))
print('raw verified:', sum(r['verified_now'] is True for r in raw), '/', len(raw))
