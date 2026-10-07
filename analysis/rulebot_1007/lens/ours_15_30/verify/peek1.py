import os,sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import vlib
import sys, pandas as pd, json
E=sys.argv[1]
d=pd.read_csv(E+'/run-20261005T014624Z/d3_shadows.csv')
print(d.kind.value_counts().head(40))
print(d.day.value_counts())
for k in ['skipped','base','lev10','quality']:
    x=d[d.kind==k]
    print(k, len(x)); print(x.head(3).to_string())
sk=d[d.kind=='skipped']
print(sk.resolved.value_counts(), sk.filled.value_counts())
print(sk.data.str.slice(0,300).head(5).tolist())
