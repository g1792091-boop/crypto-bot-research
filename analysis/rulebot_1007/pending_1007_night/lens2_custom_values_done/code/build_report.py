import sys, json, os
sys.path.insert(0,'/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens2/custom_values/code')
from show import *
import numpy as np
W='/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens2/custom_values'
os.chdir(W)
d=pd.read_csv('out_R2/cell_desc.csv'); one=pd.read_csv('out/one_position.csv'); ps=pd.read_csv('out_R2/persistence.csv')
cR=pd.read_csv('out/wf_cells.csv'); cM=pd.read_csv('out_R2/wf_cells.csv')
notes=[]
for _,r in d.iterrows():
    cell=r.cell
    a=cM[(cM.cell==cell)&(cM.method=='naive')&(cM.scheme=='s4_w26')].iloc[0]
    b=cM[(cM.cell==cell)&(cM.method=='naive')&(cM.scheme=='s4_w13')].iloc[0]
    e=cR[(cR.cell==cell)&(cR.method=='naive')&(cR.scheme=='s4_w26')].iloc[0]
    p=ps[ps.cell==cell].iloc[0]; o=one[one.cell==cell].iloc[0]
    strat,tf=cell.rsplit('_',1)
    grade='D'
    note=f"Default loses {r.default_mean_R:+.3f} R/trade over {int(r.default_n):,} all-signal trades (gross {r.default_gross_R:+.3f} R, cost {r.default_cost_R:.3f} R). Walk-forward search (26-wk window, monthly re-tune) in money units: {a.delta_R:+.4f} R2/trade vs default (p_one_sided {a.p_le0:.2f}, BH10 {'pass' if a.bh10 else 'fail'}); 13-wk: {b.delta_R:+.4f}. In stop-relative R units: {e.delta_R:+.4f} (mostly wide-stop artefact). Half A to half B persistence of the top-10 combos: {p.top10A_mean_dA:+.3f} -> {p.top10A_mean_dB:+.3f} R; Spearman {p.spearman_dA_dB:+.2f}. A one-position trader would get {o.one_pos_trades_per_week:.1f} trades/week (all-signal stream {o.all_signal_trades_per_week:.0f}/week)."
    if strat=='F5_BOX':
        grade='D (watch)'; note+=" F5_BOX is the only family whose search was positive in all three timeframes (money units +0.023/+0.064/+0.024 R2 at 15m/30m/1h) but none passes BH and trade counts are small (2,199-9,775); even +0.06 leaves it far below break-even."
    if strat=='N16_BBRSI': note+=" Search is worse than default at 30m/1h (negative cell deltas)."
    notes.append(dict(strategy=strat,timeframe=tf,grade=grade,numbers=dict(default_n=int(r.default_n),default_mean_R=r.default_mean_R,default_gross_R=r.default_gross_R,default_cost_R=r.default_cost_R,wf_naive_s4_w26_R2_delta=a.delta_R,wf_naive_s4_w26_p=a.p_le0,wf_naive_s4_w13_R2_delta=b.delta_R,wf_naive_s4_w26_R_delta=e.delta_R,top10A_dA=p.top10A_mean_dA,top10A_dB=p.top10A_mean_dB,spearman_AB=p.spearman_dA_dB,oracle_in_sample_delta=r.oracle_delta,combos_mean_positive_of_225=int(r.combos_mean_positive),weeks_to_confirm_0p10R_all_signal=r['weeks_needed_0.1'],one_position_trades_per_week=o.one_pos_trades_per_week),note=note))
json.dump(notes,open('out/strategy_notes.json','w'),indent=1)
print(len(notes))
