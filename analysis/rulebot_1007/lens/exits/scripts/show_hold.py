import site, sys
sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path: sys.path.append(us)
import pandas as pd
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)
P = pd.read_csv(sys.argv[1])
M = P[(P.group=='house_all')&(P.set=='ALL')&(P.flip==0)&(P.run=='pooled')&P.tf.isin(['15m','30m'])]
print(M[['tf','variant','n_paired','R_var','grossR_var','win_var','avgwin_var','avgloss_var','payoff_var','hold_base_med','hold_var_med','open_end_var','exit_mix']].round(3).to_string(index=False))
