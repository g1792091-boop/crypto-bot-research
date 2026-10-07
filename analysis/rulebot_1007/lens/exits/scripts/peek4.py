import site, sys
sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path: sys.path.append(us)
import pandas as pd, numpy as np
X = pd.read_csv(sys.argv[1])
for v in ['tp1R','tp2R','tp3R','be1_tp2','tp1.5R']:
    g = X[X.variant==v]
    print(v, g.exit_reason.value_counts().to_dict(), g.groupby('flip').exit_reason.value_counts().to_dict())
