import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import *
E, O = sys.argv[1], sys.argv[2]
for r in RUNS:
    s = pd.read_csv(os.path.join(E, r, "signal_log.csv"))
    print(r, s.shape, s["status"].value_counts().to_dict())
    print(pd.crosstab(s["timeframe"], s["status"]))
    a = pd.read_csv(os.path.join(E, r, "accounts.csv"))
    print(a.columns.tolist()); print(a.head(2).to_string())
    print(a["kind"].value_counts().to_dict())
