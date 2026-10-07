import site, sys
sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path: sys.path.append(us)
import pandas as pd
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)
R = pd.read_csv(sys.argv[1])
cols = ["tf","variant","dR_v3b","dR_v4","dR_pooled","lo_pooled","hi_pooled","q_R_main","dR_flip","dR_res_v3b","dR_res_v4","dpe_v3b_pct","dpe_v4_pct"]
for tf in ["15m","30m","1h","4h"]:
    print(R[R.tf==tf][cols].round(3).to_string(index=False))
