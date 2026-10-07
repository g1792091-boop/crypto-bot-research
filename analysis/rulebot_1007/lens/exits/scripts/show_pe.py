import site, sys
sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path: sys.path.append(us)
import pandas as pd
pd.set_option("display.width", 250)
P = pd.read_csv(sys.argv[1])
M = P[(P.group=='house_all')&(P.set=='ALL')&(P.flip==0)&P.variant.isin(['lev10','lev20m20','lev30m30','lev40m40','lev50m50','geo10','geo20'])&P.tf.isin(['15m','30m','1h'])]
print(M[['tf','run','variant','n_signals','not_entered','R_base','R_var','pe_base_pct','pe_var_pct','diff_pe_pct','lo_pe_pct','hi_pe_pct']].round(3).to_string(index=False))
