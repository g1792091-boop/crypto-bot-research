"""Verify Holdout claims from the Holdout agent's derived gate tables (no bar reads)."""
import glob, numpy as np, pandas as pd
from scipy.stats import spearmanr, norm
S = '/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/sweep'
def raw(split):
    fs = sorted(glob.glob(f'{S}/holdout/out/gate_{split}_*.csv'))
    fs = [f for f in fs if 'applied' not in f]
    d = pd.concat([pd.read_csv(f) for f in fs], ignore_index=True)
    return d
def holm(p):
    p=np.asarray(p); m=len(p); o=np.argsort(p); a=np.minimum(1,np.maximum.accumulate((m-np.arange(m))*p[o])); r=np.empty(m); r[o]=a; return r
IS = pd.read_csv('out/check1_is_recomputed.csv')
for split in ['oos','final']:
    d = raw(split)
    print(f'== {split}: rows {len(d)} dups {d.duplicated(["strategy","tf","H"]).sum()} splitcol {d.split.unique()}')
    fam = (d.n>=100)&np.isfinite(d.p)&np.isfinite(d.p_vn)
    d['ph']=np.nan; d.loc[fam,'ph']=holm(d.loc[fam,'p']); d['pvh']=np.nan; d.loc[fam,'pvh']=holm(d.loc[fam,'p_vn'])
    f = d[fam]
    print(' family', len(f), ' z>2:', int((f.z>2).sum()), f'(exp {len(f)*norm.sf(2):.1f})', ' p<.05:', int((f.p<.05).sum()),
          ' fwd>=mu*:', int((f.fwd>=f.mu_star).sum()), ' fwd>=mu*&p<.05&p_vn<.05:', int(((f.fwd>=f.mu_star)&(f.p<.05)&(f.p_vn<.05)).sum()),
          f' z mean/sd {f.z.mean():.2f}/{f.z.std():.2f}')
    print(' own-family Holm significant (p_holm<.05):'); print(f[f.ph<0.05][['strategy','tf','H','n','fwd','mu_star','z','p','ph','p_vn','pvh']].to_string())
    print(' own-family Holm on p_vn significant count:', int((f.pvh<0.05).sum()), ' of which fwd>=mu*:', int(((f.pvh<0.05)&(f.fwd>=f.mu_star)).sum()))
    # windows sanity: n_min per tf/H, E_abs_r
    print(d.groupby(['tf']).n_min.agg(['min','max']).T.to_string())
    m = IS.merge(d, on=['strategy','tf','H'], suffixes=('_is','_x'))
    ok = np.isfinite(m.fwd_is - m.mu_star_is) & np.isfinite(m.fwd_x - m.mu_star_x)
    rho = spearmanr(m.fwd_is[ok]-m.mu_star_is[ok], m.fwd_x[ok]-m.mu_star_x[ok])
    ok2 = ok & (m.n_is>=100)&(m.n_x>=100)
    rhoz = spearmanr(m.z_is[ok2], m.z_x[ok2])
    print(f' Spearman IS vs {split} (fwd-mu*): {rho.correlation:.3f} (cells {int(ok.sum())});  z-Spearman n>=100 both: {rhoz.correlation:.3f} (cells {int(ok2.sum())})')
    # within (tf,H) z correlation
    w = [spearmanr(g.z_is, g.z_x).correlation for _, g in m[ok2].groupby(['tf','H']) if len(g)>5]
    print(f'  mean within-(tf,H) z Spearman {np.nanmean(w):.3f}, positive groups {sum(np.array(w)>0)}/{len(w)}')
    # consistency across windows: IS z>1.645 and split z>1.645 and fwd>=cost in both
    both = m[(m.n_is>=100)&(m.n_x>=100)&(m.z_is>1.645)&(m.z_x>1.645)&(m.fwd_is>m.cost_H_is)&(m.fwd_x>m.cost_H_x)]
    print(f'  cells with z>1.645 AND fwd>cost in BOTH IS and {split}:'); print(both[['strategy','tf','H','n_is','z_is','fwd_is','n_x','z_x','fwd_x','mu_star_x','p_vn_x']].to_string())
    d.to_csv(f'out/holdout_{split}_recheck.csv', index=False)
# three-window consistency
o = pd.read_csv('out/holdout_oos_recheck.csv'); fi = pd.read_csv('out/holdout_final_recheck.csv')
m = IS.merge(o, on=['strategy','tf','H'], suffixes=('','_o')).merge(fi, on=['strategy','tf','H'], suffixes=('','_f'))
all3 = m[(m.n>=100)&(m.z>0)&(m.z_o>0)&(m.z_f>0)&(m.fwd>m.cost_H)&(m.fwd_o>m.cost_H_o)&(m.fwd_f>m.cost_H_f)]
print('cells with z>0 and fwd>cost in ALL THREE windows:', len(all3))
print(all3[['strategy','tf','H','n','z','z_o','z_f','fwd','fwd_o','fwd_f','mu_star','mu_star_o','mu_star_f','prev_examined','approx']].round(4).to_string())
exp = 0
print('fraction of family cells with fwd>cost in IS/OOS/FINAL:', round(((m.n>=100)&(m.fwd>m.cost_H)).mean(),3), round(((m.n_o>=100)&(m.fwd_o>m.cost_H_o)).mean(),3), round(((m.n_f>=100)&(m.fwd_f>m.cost_H_f)).mean(),3))
