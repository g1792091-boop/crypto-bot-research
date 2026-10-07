import site, sys
sys.path.append(site.getusersitepackages())
import pandas as pd, numpy as np
pd.set_option('display.width', 250); pd.set_option('display.max_columns', 80); pd.set_option('display.max_rows', 500)
code = sys.argv[1]
args = sys.argv[2:]
exec(open(code).read())
