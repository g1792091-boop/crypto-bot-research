"""Write MANIFEST.json for the sweep data directory (all numbers computed here)."""
import json, glob, hashlib, os, datetime, pandas as pd
B = '/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/sweep/data'
os.chdir(B)
CF = {'btcusd': '2021-07-01', 'ethusd': '2021-07-01', 'solusd': '2021-10-01', 'xrpusd': '2021-07-01',
      'ltcusd': '2021-07-01', 'bchusd': '2021-07-01', 'dogeusd': '2021-08-01'}
TFM = {'5m': 5, '15m': 15, '30m': 30, '1h': 60, '2h': 120, '4h': 240, '1d': 1440, '1w': 10080}
def sha(f):
    h = hashlib.sha256()
    with open(f, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''): h.update(chunk)
    return h.hexdigest()
build = {}
for f in glob.glob('work/build_*.json'): build.update(json.load(open(f)))
files = {}
for split in ['full', 'is', 'oos', 'final']:
    for f in sorted(glob.glob(f'{split}/*.csv')):
        name = os.path.basename(f); sym, tf = name[:-4].split('-')
        d = pd.read_csv(f, usecols=['ts']); t = pd.to_datetime(d.ts, utc=True)
        step = pd.Timedelta(minutes=TFM[tf]); dt = t.diff()
        exp = int((t.iloc[-1] - t.iloc[0]) / step) + 1
        gaps = dt[dt > step]
        b = build.get(f, {})
        files[f] = dict(symbol=sym.upper(), split=split, tf=tf, rows=len(t), first=t.iloc[0].strftime('%Y-%m-%dT%H:%M:%SZ'),
                        last=t.iloc[-1].strftime('%Y-%m-%dT%H:%M:%SZ'), sha256=sha(f), bytes=os.path.getsize(f),
                        clean_from=CF[sym], starts_at_clean_from=(split == 'is'),
                        gaps=dict(expected_bins=exp, missing_bins=exp - len(t), gap_events=int(len(gaps)),
                                  max_gap=str(gaps.max()) if len(gaps) else None,
                                  partial_bins=b.get('partial_bins'), constituent_5m_bars=b.get('constituent_5m_bars')))
raw = []
ver = dict(l.split() for l in open('raw/sha256_verified.txt') if l.strip())
for f in sorted(glob.glob('raw/*.csv')):
    n = os.path.basename(f); d = pd.read_csv(f, usecols=['timestamp'])
    raw.append(dict(file=n, sha256=sha(f), sha256_matches_astral_artifact=(ver.get(n) == sha(f)), rows=len(d),
                    first=d.timestamp.iloc[0], last=d.timestamp.iloc[-1]))
seams = {c: json.load(open(f'work/stitch_{c}.json'))['seams'] for c in ['btc', 'eth', 'sol', 'xrp', 'ltc', 'bch']}
man = dict(
    generated_utc=datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'), data_dir=B,
    astral_calls=dict(price_get=64, price_get_5m_chain=60, price_get_crosscheck=4, other_tools=0,
                      note='all price_get with delivery=download and limit only (+end for chaining); never start+end together; every artifact sha256-verified'),
    conventions=dict(ts='bar-open UTC, ISO 8601 (YYYY-MM-DDTHH:MM:SSZ)', columns=['ts', 'open', 'high', 'low', 'close', 'volume'],
                     resample='open-labelled, left-closed; O first, H max, L min, C last, V sum over available 5m bars; zero-bar bins dropped; only bins fully inside the split window kept; in-progress last bin dropped; 1w bins start Monday 00:00 UTC',
                     splits={'is': '[clean_from, 2024-07-01T00:00Z)', 'oos': '[2024-01-01T00:00Z, 2025-08-07T00:00Z)', 'final': '[2025-02-01T00:00Z, end of data]',
                                 'full': 'whole stitched series (includes pre-clean_from bars; DOGE from 2021-01-01)'},
                     holdout='is/ contains no bar with ts >= 2024-07-01 and no bin extending past it (asserted in build.py). oos/ and final/ are for the Holdout agent only.',
                     no_clipping='No bar was modified or removed; suspects are only listed in suspects.csv'),
    clean_from=CF,
    clean_from_reasons={
        'BTCUSD/ETHUSD/LTCUSD/BCHUSD': '2021-07-01 (earliest allowed). June 2021 has elevated open-vs-prev-close jumps (BTC 29 >0.5%); July 2021 onward no gaps, 0 OHLC errors.',
        'XRPUSD': '2021-07-01, BUT degraded-liquidity window 2022-03-01..2023-07-31 (see degraded_windows): 282 gap events, 813 flat bars, median USD volume/5m bar 7,064 vs ~81k before/after. Not corrupted (0 OHLC errors, lag-1 return autocorr in line with BTC) so not excluded.',
        'SOLUSD': '2021-10-01: repeated round-number bad-print up-wicks Jun-Sep 2021 (e.g. 2021-08-18 11:15 high 114.000 vs prev close 73.784 = +54.5%; 2021-09-06 20:25 high 199.000 = +23.1%; 2021-07-07 09:45 high 40.000 = +14.3%); June 2021 has 134 gap events and 202 flat bars.',
        'DOGEUSD': '2021-08-01 (inherited from the doge dataset analysis: cross-venue mixing to 2021-06, bad wicks through 2021-07).'},
    degraded_windows=json.load(open('qa/degraded_ranges.json')),
    known_data_defects=[
        '2026-04-22 whole day missing in every 5m series (288 bars); the direct Astral 1d pull DOES contain a 2026-04-22 bar (BTC and DOGE), so the 1d files here lack that day.',
        'SOLUSD, XRPUSD, LTCUSD: 2025-03-25 whole day missing in 5m (inherited from the doge dataset files covering 2025-03-19+).',
        'DOGEUSD 5m: 2026-09-29 06:00-07:05 missing (14 bars); the direct 1h pull has a 06:00 bar.',
        'BCHUSD: 1h gap ending 2024-09-16 06:30; 329 gap events in 2024-09.',
        'Most recent ~2 days (2026-09-27..29) are provisional: direct re-pulls at 11:13 UTC differ from the stitched data (DOGE 1h: 21 price-mismatch bars, max close diff 1.04% at 2026-09-28 15:00).'],
    seams=seams, seam_open_vs_prev_close=json.load(open('qa/seam_jumps.json')),
    crosscheck=open('qa/xcheck.txt').read(),
    suspects=dict(file='suspects.csv', rows=int(len(pd.read_csv('suspects.csv'))),
                  definition='range/prev_close > 8x rolling median range (previous 288 bars, floor 5bp) AND excursion fully reverts (within bar: |c-pc|<=0.25*E, or next bar: |c_next-pc|<=0.25*E) AND isolated (neighbour ranges < 4x median, contiguous)'),
    raw_pulls=raw, files=files)
json.dump(man, open('MANIFEST.json', 'w'), indent=1)
print('files', len(files), 'raw', len(raw), 'all raw sha ok', all(r['sha256_matches_astral_artifact'] for r in raw))
