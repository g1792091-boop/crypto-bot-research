import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import *
E, O = sys.argv[1], sys.argv[2]
f = pd.read_csv(os.path.join(O, "fiveyear_ref.csv"))
print(f.groupby(["source","variant"]).size())
print(f[f.source!="profiles_binance"][["source","strategy","timeframe","variant","n_signals","per_day","ds_is_n","ds_cf_n","ds_pre_n","hold_bars_is"]].head(12).to_string())
for r in RUNS:
    s = pd.read_csv(os.path.join(E, r, "signal_log.csv"))
    print(r, s[s.status=="RECORD"].groupby(["symbol"]).size().to_dict(), s[s.status=="SUBMITTED"].groupby("symbol").size().to_dict())
sf = pd.read_csv(os.path.join(O, "signal_flow.csv"))
print(sf.columns.tolist())
print(sf.groupby(["run","kind"])["zero_trade_cause"].value_counts())
