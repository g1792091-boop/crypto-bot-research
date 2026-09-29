"""per-month gap events, missing slots, flat bars, median USD volume per 5m bar. usage: monthly_liq.py coin"""
import sys, pandas as pd, numpy as np
c = sys.argv[1]
d = pd.read_csv(f'work/{c}usd-5m-stitched-raw.csv'); d['ts'] = pd.to_datetime(d.timestamp, utc=True); d = d.set_index('ts')
step = pd.Timedelta(minutes=5)
dt = d.index.to_series().diff()
gapmask = dt > step
miss = (dt / step - 1).where(gapmask, 0)
usd = d.volume * d.close
flat = (d.high == d.low)
m = d.index.tz_localize(None).to_period('M')
t = pd.DataFrame({'gap_ev': gapmask.groupby(m).sum(), 'miss_slots': miss.groupby(m).sum(),
                  'flat_bars': flat.groupby(m).sum(), 'med_usd_vol': usd.groupby(m).median().round(0),
                  'p10_usd_vol': usd.groupby(m).quantile(0.1).round(0)})
t.to_csv(f'qa/liq_{c}_monthly.csv')
pd.set_option('display.max_rows', 200)
print(c); print(t.astype({'gap_ev': int, 'miss_slots': int, 'flat_bars': int}).to_string())
