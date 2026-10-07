import sys, site
sys.path.append(site.getusersitepackages())
import pandas as pd
t = pd.read_csv(sys.argv[1], low_memory=False)
print(t.groupby(['kind'])['strategy_style'].value_counts(dropna=False).to_string())
print(t[t.kind.isin(['strategy','ds200'])].groupby('strategy')['strategy_style'].first().to_string())
