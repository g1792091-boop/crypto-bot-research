import site, sys
sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np, pandas as pd
E, ESF = sys.argv[1:3]
sh = pd.read_csv(E + "/run-20261005T014624Z/d3_shadows.csv")
sh = sh[sh.kind == "skipped"].copy()
k = sh.key.str.split("|", expand=True)
sh["aid"] = k[1]; sh["bc"] = k[3].astype(np.int64)
sh["tf"] = sh.aid.str.split("@").str[1]; sh["strategy"] = sh.aid.str.split("@").str[0]
ES = pd.read_csv(ESF)
x = ES[(ES.run == "run-20261005T014624Z") & (ES.src == "shadow") & (ES.status == "TRADED") & ES.R.isna()]
print("v3a resolved shadows with no reconstructable leverage, by tf:", x.groupby("tf").size().to_dict())
m = x.merge(sh[["strategy", "tf", "symbol", "bc", "roe", "exit_reason", "data"]], on=["strategy", "tf", "symbol", "bc"])
print(m.groupby(["tf", "symbol"]).roe.agg(["size", "mean"]).round(3).to_string())
print(m.groupby("tf").exit_reason.value_counts().to_string())
print(m[m.tf == "4h"][["strategy", "symbol", "roe", "exit_reason"]].to_string())
