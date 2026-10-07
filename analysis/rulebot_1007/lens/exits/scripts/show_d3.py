import site, sys
sys.dont_write_bytecode = True
us = site.getusersitepackages()
if us not in sys.path: sys.path.append(us)
import pandas as pd
pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)
D = pd.read_csv(sys.argv[1])
keep = ["lev10","lev20","lock15","lock20","lock30","timestop","tp1R","tp1.5R","tp2R","tp3R","stopw1.5","stopw3","ladder_cap2R","lev40m40","lev50"]
for grp in ["core36","house_all"]:
    d = D[(D.group==grp)&D.variant.isin(keep)]
    print(grp)
    print(d[["run","tf","variant","n_pairs","n_unres","mean_bR_dropped","diff_R","lo_R","hi_R","lo_R_4h","hi_R_4h","diff_pe","diff_pe_ne0","G1h"]].sort_values(["variant","run","tf"]).round(3).to_string(index=False))
