import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
X = pd.read_pickle("xl.pkl")
X = X[(X.flip==0)&X.variant.isin(["base","geo10","lev10"])]
X["pe"] = np.where(X.status.isin(["CLOSED","OPEN_END"]), X.pnl/5000*100, 0.0)
T = X.groupby(["timeframe","runl","variant"]).pe.mean().unstack("variant")
T["exit_part"] = T.geo10 - T.base; T["size_part"] = T.lev10 - T.geo10
print(T.round(3).to_string())
