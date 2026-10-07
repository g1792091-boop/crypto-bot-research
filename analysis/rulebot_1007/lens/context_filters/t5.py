import sys, time, os, site
sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
lens = sys.argv[4]
sys.argv = sys.argv[:4] + ["1"]
sys.path.insert(0, lens)
import fiveyear_ctx as FY
t = time.time()
X = FY.job(("30m", "BTCUSD"))
print(time.time() - t, len(X))
print(X.describe().T.round(3).to_string())
print(X.groupby('strategy').R.agg(['size','mean']).head(40).to_string())
