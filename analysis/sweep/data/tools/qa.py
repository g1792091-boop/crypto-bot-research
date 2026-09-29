"""Bar-level QA of a stitched OHLCV csv. usage: qa.py <csv> <freq_min> [period=Q]"""
import sys, pandas as pd, numpy as np, json
f, fm = sys.argv[1], int(sys.argv[2]); per = sys.argv[3] if len(sys.argv) > 3 else 'Q'
d = pd.read_csv(f); d['ts'] = pd.to_datetime(d.timestamp, utc=True)
d = d.set_index('ts')
step = pd.Timedelta(minutes=fm)
dt = d.index.to_series().diff()
gaps = dt[dt > step]
print('rows', len(d), 'first', d.index[0], 'last', d.index[-1])
print('duplicates', int(d.index.duplicated().sum()), 'non-monotonic', int((dt < pd.Timedelta(0)).sum()))
exp = int((d.index[-1]-d.index[0])/step)+1
print('expected slots', exp, 'missing slots', exp-len(d), f'({(exp-len(d))/exp*100:.3f}%)')
print('gap events', len(gaps), 'max gap', gaps.max() if len(gaps) else None)
big = gaps[gaps >= pd.Timedelta(hours=1)]
print('gaps >=1h:', len(big))
for t, g in big.sort_values(ascending=False).head(25).items():
    print('   gap ending', t, 'len', g)
o, h, l, c, v = d.open, d.high, d.low, d.close, d.volume
bad_ohlc = (h < np.maximum(o, c) - 1e-12) | (l > np.minimum(o, c) + 1e-12) | (l <= 0) | (h < l)
print('OHLC inconsistent rows', int(bad_ohlc.sum()), ' nonpositive', int((d[['open','high','low','close']] <= 0).any(axis=1).sum()),
      ' NaN', int(d[['open','high','low','close','volume']].isna().any(axis=1).sum()), ' vol<=0', int((v <= 0).sum()))
pc = c.shift(1)
contig = (dt == step)
jump = (o / pc - 1).abs().where(contig)
upw = (h - np.maximum(o, c)) / c
dnw = (np.minimum(o, c) - l) / c
rng = (h - l) / c
# rolling median range as a local vol scale (288 bars ~ 1 day for 5m)
win = max(12, int(1440 / fm))
medr = rng.rolling(win, min_periods=win//4).median()
wick_x = (np.maximum(upw, dnw) / medr.replace(0, np.nan))
# robust spike: close deviates from both neighbours' closes by > X and reverts
r1 = np.log(c / pc); r2 = np.log(c.shift(-1) / c)
spike = ((r1.abs() > 0.03) & (r2.abs() > 0.03) & (np.sign(r1) != np.sign(r2)))
q = pd.DataFrame(dict(bars=o, jump=jump, jump_gt_05=(jump > 0.005), jump_gt_2=(jump > 0.02), jump_nonzero=(jump > 1e-9),
                      wick_gt_3=(np.maximum(upw, dnw) > 0.03), wick_x20=(wick_x > 20), rng=rng, flat=(h == l), spike=spike,
                      vol0=(v <= 0)))
g = q.groupby(q.index.to_period(per))
def dec_places(x):
    s = x.astype(str)
    return s.str.split('.').str[1].str.len().fillna(0)
tick = d.close.groupby(d.index.to_period(per)).apply(lambda x: float(np.median(dec_places(x.sample(min(len(x), 3000), random_state=0)))))
mx_dec = d.close.groupby(d.index.to_period(per)).apply(lambda x: int(dec_places(x.sample(min(len(x), 3000), random_state=0)).max()))
slots = g.bars.count()
per_len = pd.Series({p: int(((p.end_time.tz_localize('UTC') if p.end_time.tzinfo is None else p.end_time) - (p.start_time.tz_localize('UTC') if p.start_time.tzinfo is None else p.start_time)).total_seconds()//(fm*60))+1 for p in slots.index})
tab = pd.DataFrame({
  'bars': slots,
  'miss%': (1 - slots / per_len) * 100,
  'open!=prevC%': g.jump_nonzero.mean() * 100,
  'jump>0.5%': g.jump_gt_05.sum(),
  'jump>2%': g.jump_gt_2.sum(),
  'p99jump%': g.jump.quantile(0.99) * 100,
  'wick>3%': g.wick_gt_3.sum(),
  'wick>20xMedR': g.wick_x20.sum(),
  'spikes3%': g.spike.sum(),
  'medRng%': g.rng.median() * 100,
  'flat%': g.flat.mean() * 100,
  'dec_med': tick, 'dec_max': mx_dec,
})
pd.set_option('display.width', 250); pd.set_option('display.max_rows', 200)
print(tab.round(3).to_string())
if len(sys.argv) > 4:
    tab.to_csv(sys.argv[4])
