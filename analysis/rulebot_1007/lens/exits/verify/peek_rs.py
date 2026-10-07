import site, sys
sys.dont_write_bytecode=True
sys.path.append(site.getusersitepackages())
import sys, pandas as pd
rs = pd.read_csv(sys.argv[1], low_memory=False)
print(rs.status.value_counts())
print(rs.groupby(['run','kind','status']).size())
u = rs[rs.status=='UNRESOLVED']
print(u[['entry_price','stop_initial','qty','leverage','mark_R','R']].describe())
print(rs[rs.status=='TRADED'][['entry_price','qty','leverage','R','funding']].describe())
