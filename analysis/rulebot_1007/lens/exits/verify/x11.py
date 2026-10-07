import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
X = pd.read_pickle("xl.pkl")
b = X[(X.flip==0)&(X.variant=="base")].copy()
b["sf"] = b.dist/b.b_entry
# loss at the stop as share of equity, margin = L% of equity: notional = L^2/100 * equity
# loss/notional = sf + slip at stop exit (~0.0002) + taker fees on both sides (~0.001)
lossn = b.sf + 0.0002 + 0.001
for tf in ["15m","30m","1h"]:
    s = lossn[b.timeframe==tf]
    print(tf, "median stop", round(b[b.timeframe==tf].sf.median()*100,3), "% |", " ".join(f"{L}x {100*np.median(s*L*L/100):.1f}%" for L in (20,30,40,50)),
          "| 7 losses:", " ".join(f"{L}x {100*(1-(1-np.median(s*L*L/100))**7):.0f}%" for L in (20,30,40)))
