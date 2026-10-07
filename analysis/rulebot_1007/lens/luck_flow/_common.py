import site, sys
sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path:
    sys.path.append(us)
import numpy as np, pandas as pd
MIN, HOUR, DAY = 60_000, 3_600_000, 86_400_000
TF_MIN = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
RUNS = ["run-20261005T014624Z", "run-20261005T183457Z", "current"]
RUN_LABEL = {"run-20261005T014624Z": "v3a", "run-20261005T183457Z": "v3b", "current": "v4"}
