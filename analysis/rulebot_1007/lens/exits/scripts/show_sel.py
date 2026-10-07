import site, sys
sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path: sys.path.append(us)
import pandas as pd
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)
P = pd.read_csv(sys.argv[1])
vs = sys.argv[2].split(',')
tfs = sys.argv[3].split(',')
M = P[(P.group=='house_all')&(P.set=='ALL')&(P.flip==0)&P.variant.isin(vs)&P.tf.isin(tfs)]
print(M[['tf','variant','run','n_paired','G1h','R_base','R_var','diff_R','lo_R','hi_R','lo_R_4h','hi_R_4h','p_R','diff_pe_pct','lo_pe_pct','hi_pe_pct','share_better']].sort_values(['tf','variant','run']).round(3).to_string(index=False))
