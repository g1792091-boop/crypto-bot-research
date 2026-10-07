import site, sys
sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path: sys.path.append(us)
import numpy as np, pandas as pd, json
E = "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/export_1007"
RUNS = {"v3a": "run-20261005T014624Z", "v3b": "run-20261005T183457Z", "v4": "current"}
def kst(ms): return pd.to_datetime(ms, unit="ms") + pd.Timedelta(hours=9)
def load(lab, f): return pd.read_csv(f"{E}/{RUNS[lab]}/{f}.csv", low_memory=False)
