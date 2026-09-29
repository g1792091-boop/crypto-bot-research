"""lag-1 autocorrelation of contiguous 5m log returns per quarter, all coins. writes qa/ac1_quarterly.csv"""
import pandas as pd, numpy as np
out = {}
for c in ['btc','eth','sol','xrp','ltc','bch','doge']:
    d = pd.read_csv(f'work/{c}usd-5m-stitched-raw.csv'); d['ts'] = pd.to_datetime(d.timestamp, utc=True); d = d.set_index('ts')
    d = d[d.index >= '2021-06-01']
    r = np.log(d.close).diff()
    ok = d.index.to_series().diff() == pd.Timedelta(minutes=5)
    r = r.where(ok)
    rl = r.shift(1).where(ok.shift(1, fill_value=False))
    q = d.index.tz_localize(None).to_period('Q')
    df = pd.DataFrame({'r': r, 'rl': rl, 'q': q}).dropna()
    out[c] = df.groupby('q').apply(lambda x: x.r.corr(x.rl)).round(3)
t = pd.DataFrame(out)
t.to_csv('qa/ac1_quarterly.csv')
print(t.to_string())
