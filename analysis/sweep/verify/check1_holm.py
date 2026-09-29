# Independent recompute of family, Holm, survivors from the 7 raw Discover gate tables.
import glob, numpy as np, pandas as pd
from scipy.stats import norm
S = '/tmp/claude-0/-home-user-crypto-bot-research/e4f1f93f-891a-54cf-944d-5e95b2209f11/scratchpad/sweep'
files = sorted(glob.glob(S+'/discover_g5m/out/gate_is_5m_sub*.csv')) + \
        [S+f'/discover_g15_30/out/gate_is_{t}.csv' for t in ('15m','30m')] + \
        [S+f'/discover_g1h_4h_1d/out/gate_is_{t}.csv' for t in ('1h','4h','1d')]
d = pd.concat([pd.read_csv(f).assign(src=f.split('/')[-1]) for f in files], ignore_index=True)
print('files', len(files), 'rows', len(d), 'dups', d.duplicated(['strategy','tf','H']).sum())
print('strategies', d.strategy.nunique(), 'tfs', sorted(d.tf.unique()), 'H', sorted(d.H.unique()))
# my own p from z (check p=1-Phi(z))
pz = norm.sf(d.z); print('max |p - sf(z)|', np.nanmax(np.abs(pz - d.p)))
pzv = norm.sf(d.z_vn); print('max |p_vn - sf(z_vn)|', np.nanmax(np.abs(pzv - d.p_vn)))
# own hurdle recompute
tfm = {'5m':5,'15m':15,'30m':30,'1h':60,'4h':240,'1d':1440}
cost = 0.0014 + 0.0001*d.H*d.tf.map(tfm)/480
print('max |cost_H - mine|', np.abs(cost-d.cost_H).max())
mu = cost + 0.091*d.E_abs_r
print('max |mu* - mine|', np.abs(mu-d.mu_star).max())
fam = (d.n>=100) & np.isfinite(d.p) & np.isfinite(d.p_vn)
m = int(fam.sum()); print('family m', m, d[fam].groupby('tf').size().to_dict())
def holm_mine(p):
    p = np.asarray(p); m=len(p); o=np.argsort(p); sp=p[o]
    adj = np.minimum(1, np.maximum.accumulate((m-np.arange(m))*sp))
    out=np.empty(m); out[o]=adj; return out
d['ph']=np.nan; d['pvh']=np.nan
d.loc[fam,'ph']=holm_mine(d.loc[fam,'p']); d.loc[fam,'pvh']=holm_mine(d.loc[fam,'p_vn'])
# symbols rule
per = [c for c in ['BTCUSD','ETHUSD','SOLUSD','XRPUSD','DOGEUSD','LTCUSD','BCHUSD']]
n10 = sum((d[f'n_{c}']>=10).astype(int) for c in per)
sp = sum(((d[f'n_{c}']>=10)&(d[f'fwd_{c}']>0)).astype(int) for c in per)
print('symbols_pos mismatch', (sp!=d.symbols_pos).sum(), 'n10 mismatch', (n10!=d.n_coins_ge10).sum())
symok = (sp>=4) | ((n10>=1)&(sp>=0.6*n10))
c1 = d.ph<0.05; c2=d.pvh<0.05; c3=d.fwd>=mu; c5=d.n>=100
spec = fam & c1 & c3 & symok & c5
gp = spec & c2
print('gate_pass_spec', int(spec.sum()), 'gate_pass', int(gp.sum()))
print('c1', int((fam&c1).sum()), 'c2', int((fam&c2).sum()), 'c3', int((fam&c3).sum()), 'c4', int((fam&symok).sum()))
print('min p', d.loc[fam,'p'].min(), d.loc[fam].sort_values('p').iloc[0][['strategy','tf','H','n','z','p','ph','p_vn']].to_dict())
print('holm first step', 0.05/m, 'm needed for min p to pass', 0.05/d.loc[fam,'p'].min())
# Any cell that would pass even without Holm (raw p<0.05 & p_vn<0.05 & fwd>=mu & sym)?
raw = fam & (d.p<0.05)&(d.p_vn<0.05)&c3&symok
print('raw-level (no multiplicity) passes:', int(raw.sum()))
print(d[raw][['strategy','tf','H','n','fwd','mu_star','z','p','p_vn','symbols_pos','n_coins_ge10']].to_string())
# compare with combine
cb = pd.read_csv(S+'/combine/out/gate_all_is_applied.csv')
mm = d.merge(cb[['strategy','tf','H','p_holm','p_vn_holm','gate_pass','gate_pass_spec','fwd','z']], on=['strategy','tf','H'], suffixes=('','_cb'))
print('merge rows', len(mm), 'max|ph diff|', np.nanmax(np.abs(mm.ph-mm.p_holm)), 'max|pvh diff|', np.nanmax(np.abs(mm.pvh-mm.p_vn_holm)),
      'fwd diff', np.nanmax(np.abs(mm.fwd-mm.fwd_cb)), 'gp any', mm.gate_pass.any(), mm.gate_pass_spec.any())
# rank sensitivity: how many family cells have p below 0.05/k for k ~ small
for k in [1,10,37,62,100]:
    print(f'cells with p<0.05/{k}:', int((d.loc[fam,'p']<0.05/k).sum()))
d.to_csv('out/check1_is_recomputed.csv', index=False)
