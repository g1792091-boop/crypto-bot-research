import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
D = pd.read_csv(sys.argv[1], low_memory=False)
print(D.kind.value_counts().to_string())
print(D.groupby(["kind","resolved"]).size().unstack().fillna(0).astype(int).to_string())
for k in ["base","lev10","lock30","skipped"]:
    r = D[D.kind==k].head(2)
    for x in r.itertuples(): print(k, x.key, x.data[:600])
