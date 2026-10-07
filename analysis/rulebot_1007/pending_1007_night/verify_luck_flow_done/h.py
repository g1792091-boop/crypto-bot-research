import site, sys
sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np, pandas as pd
E='/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/export_1007'
RUNS={'v3a':'run-20261005T014624Z','v3b':'run-20261005T183457Z','v4':'current'}
def rd(run,f,**k): return pd.read_csv(f'{E}/{RUNS[run]}/{f}',**k)
