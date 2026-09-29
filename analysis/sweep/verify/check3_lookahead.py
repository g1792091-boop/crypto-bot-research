"""Look-ahead checks (IS data only).
A) truncation: signals of the HARNESS registry fn on df0[:t+1] must equal the full-series signals on bars <= t
   for V45_AMB at 15m (HTF 1h) and 1h (HTF 4h), N13_3OUTSIDE and S2_ST_ROC/N11 at 4h, DOGE_L at 1h.
B) HTF mapping: for V45 the HTF bar used on chart bar t must have close <= open(t); verify with own code
   that swapping in the 'current' (containing) HTF bar changes signals (i.e. the test has teeth).
C) resampler: 1h/4h/1d IS files == own aggregation of 5m bars with ts in [T, T+len); harness resample_ohlcv
   (used for V45 HTF) == own aggregation for 1h,2h,4h,1d,1w (Monday-start) from the chart bars."""
import sys, time, numpy as np, pandas as pd, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, '.'); sys.path.insert(0, './lib')
import indep as I
import sweep_lib as SL   # verifier's byte-identical copy (for testing the harness fn itself)
rng = np.random.default_rng(99)
rows = []
def trunc_test(name, tf, sym, a, b, npts=40):
    df_full = I.myload(sym, tf)
    df0 = df_full.iloc[a:b].reset_index(drop=True)
    df0.attrs['tf'] = tf
    fn = SL.REGISTRY[name]
    L, Sh = fn(df0, None); L, Sh = SL._clean(L, Sh, len(df0)); full = L.astype(int) - Sh.astype(int)
    sig_idx = np.flatnonzero(full)
    late = np.arange(len(df0)//2, len(df0))
    cand = np.concatenate([rng.choice(late, npts//2, replace=False),
                           rng.choice(sig_idx[sig_idx >= len(df0)//2], min(npts//2, (sig_idx >= len(df0)//2).sum()), replace=False)])
    # also bars just after an HTF boundary (first chart bar of an HTF bin) -> most sensitive for V45
    fails = 0; checked = 0
    for t in np.unique(cand):
        d = df0.iloc[:t+1].copy(); d.attrs['tf'] = tf
        l2, s2 = fn(d, None); l2, s2 = SL._clean(l2, s2, len(d)); tr = l2.astype(int) - s2.astype(int)
        ok = np.array_equal(tr, full[:t+1]); checked += 1; fails += (not ok)
    rows.append(dict(test='truncation', name=name, tf=tf, sym=sym, bars=len(df0), n_signals=len(sig_idx), checked=checked, fails=fails))
    print(rows[-1], flush=True)

t0 = time.time()
trunc_test('V45_AMB', '15m', 'BTCUSD', 60000, 66000)
trunc_test('V45_AMB', '15m', 'SOLUSD', 80000, 86000)
trunc_test('V45_AMB', '1h', 'ETHUSD', 10000, 16000)
trunc_test('V45_AMB', '1h', 'DOGEUSD', 18000, 24000)
trunc_test('N13_3OUTSIDE', '4h', 'BTCUSD', 0, 6000)
trunc_test('N13_3OUTSIDE', '4h', 'BCHUSD', 0, 6000)
trunc_test('S2_ST_ROC', '4h', 'ETHUSD', 0, 6000)
trunc_test('N11_BREAKAWAY', '4h', 'SOLUSD', 0, 5000)
trunc_test('DOGE_L', '1h', 'XRPUSD', 10000, 16000)
trunc_test('N23_HA_ST', '1d', 'SOLUSD', 0, 1000)
print('trunc time', time.time()-t0, flush=True)

# B) mapping teeth + mapping rule check with own code
for tf, sym in [('15m','BTCUSD'), ('1h','ETHUSD'), ('4h','SOLUSD'), ('1d','BTCUSD')]:
    df = I.myload(sym, tf); df.attrs['tf'] = tf
    htf = SL.HTF_OF[tf]
    dfh = SL.resample_ohlcv(df, htf)
    dcl, _ = SL.v45_htf_components(df, dfh, htf, 'closed')
    dcu, _ = SL.v45_htf_components(df, dfh, htf, 'current')
    # own mapping: HTF bin containing chart bar = floor; bin used must be the PREVIOUS complete bin
    ts = df.ts
    if htf == '1w':
        day = ts.dt.floor('1D'); cont = day - pd.to_timedelta(day.dt.weekday, unit='D')
    else:
        cont = ts.dt.floor(f"{I.TFM[htf]}min")
    hts = pd.to_datetime(dfh.ts, utc=True)
    # position of containing bin in dfh
    pos_cont = np.searchsorted(hts.values, cont.values)
    assert np.all(hts.values[np.clip(pos_cont,0,len(hts)-1)] == cont.values), 'containing bin missing'
    # closed mapping index according to harness
    key = (hts + pd.Timedelta(minutes=I.TFM[htf])).values
    idx = np.searchsorted(key, ts.values, side='right') - 1
    viol = int((idx >= pos_cont).sum())          # would mean using the containing (unfinished) bin
    lag_bins = pos_cont - idx
    L1, S1 = SL.v45_amb(df, None, 'closed'); L2, S2 = SL.v45_amb(df, None, 'current')
    diff_sig = int(((L1 != L2) | (S1 != S2)).sum())
    rows.append(dict(test='htf_mapping', name='V45_AMB', tf=tf, sym=sym, bars=len(df), htf=htf,
                     mapped_to_containing_or_later=viol, lag_bins_min=int(lag_bins.min()), lag_bins_max=int(lag_bins.max()),
                     frac_lag1=float((lag_bins == 1).mean()), sig_diff_closed_vs_current=diff_sig,
                     htf_labels_monday=(bool((hts.dt.weekday == 0).all()) if htf == '1w' else None)))
    print(rows[-1], flush=True)

# C) resampler
def own_agg(d5, minutes=None, weekly=False):
    ts = d5.ts
    if weekly:
        day = ts.dt.floor('1D'); key = day - pd.to_timedelta(day.dt.weekday, unit='D')
    else:
        key = ts.dt.floor(f'{minutes}min')
    g = d5.groupby(key.values)
    o = pd.DataFrame({'open': g.open.first(), 'high': g.high.max(), 'low': g.low.min(), 'close': g.close.last(),
                      'volume': g.volume.sum(), 'n5': g.size(), 'first5': g.ts.min(), 'last5': g.ts.max()})
    o.index = pd.to_datetime(o.index, utc=True); return o
for sym in I.COINS:
    d5 = I.myload(sym, '5m')
    for tf, mins in [('15m',15),('30m',30),('1h',60),('4h',240),('1d',1440)]:
        f = I.myload(sym, tf).set_index('ts')
        o = own_agg(d5, mins)
        o = o[o.index.isin(f.index)]
        # containment: every 5m bar assigned to bin T lies in [T, T+len)
        contain_bad = int(((o.first5 < o.index) | (o.last5 >= o.index + pd.Timedelta(minutes=mins))).sum())
        m = f.join(o, rsuffix='_own', how='outer')
        missing_in_file = int(m.open.isna().sum()); missing_in_own = int(m.open_own.isna().sum())
        mm = m.dropna(subset=['open','open_own'])
        dif = max(float(np.abs(mm[c]-mm[c+'_own']).max()) for c in ['open','high','low','close'])
        vdif = float((np.abs(mm.volume-mm.volume_own)/mm.volume_own.clip(lower=1e-12)).max())
        partial = int((mm.n5 < mins//5).sum())
        rows.append(dict(test='resample_file', sym=sym, tf=tf, bars=len(f), contain_bad=contain_bad, missing_in_file=missing_in_file,
                         missing_in_own=missing_in_own, max_abs_ohlc_diff=dif, max_rel_vol_diff=vdif, partial_bins=partial))
    # harness resampler (V45 HTF path) vs own, from chart bars
    for tfc, htf in [('15m','1h'),('30m','2h'),('1h','4h'),('4h','1d'),('1d','1w')]:
        dc = I.myload(sym, tfc)
        h = SL.resample_ohlcv(dc, htf).set_index('ts')
        mins = I.TFM[htf]
        o = own_agg(dc, None if htf=='1w' else mins, weekly=(htf=='1w'))
        m = h.join(o, rsuffix='_own', how='outer')
        dif = max(float(np.abs(m[c]-m[c+'_own']).max()) for c in ['open','high','low','close'])
        rows.append(dict(test='resample_harness_htf', sym=sym, tf=tfc, htf=htf, bars=len(h), n_own=len(o),
                         label_mismatch=int(m.open.isna().sum()+m.open_own.isna().sum()), max_abs_ohlc_diff=dif,
                         weekly_monday=(bool((h.index.weekday==0).all()) if htf=='1w' else None)))
    print(sym, 'resample done', flush=True)
out = pd.DataFrame(rows); out.to_csv('out/check3_lookahead.csv', index=False)
with pd.option_context('display.width', 250, 'display.max_columns', 30):
    print(out.to_string())
