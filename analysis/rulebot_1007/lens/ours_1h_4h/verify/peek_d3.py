import site, sys
sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import pandas as pd
E = sys.argv[1]
d = pd.read_csv(E + '/run-20261005T014624Z/d3_shadows.csv')
print(d.kind.value_counts().head(40))
s = d[d.kind == 'skipped']
print(s.head(3).to_string())
print(s.data.iloc[0][:1500])
print(s.resolved.value_counts(), s.roe.isna().sum(), s.day.value_counts())
