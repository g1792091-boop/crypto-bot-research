import sys, site
sys.path.append(site.getusersitepackages())
sys.dont_write_bytecode=True
import pandas as pd, numpy as np
pd.set_option('display.width',250); pd.set_option('display.max_columns',40)
code=open(sys.argv[1]).read()
exec(code)
