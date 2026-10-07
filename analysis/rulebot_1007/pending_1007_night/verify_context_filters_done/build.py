# verify3 independent build: one row per SUBMITTED signal with ctx + outcome R.
# usage: python3 -I build.py <scratchpad> <repo>
import sys, site, json
sys.path.append(site.getusersitepackages()); sys.dont_write_bytecode = True
import numpy as np, pandas as pd
SC, REPO = sys.argv[1:3]
sys.path.append(REPO)
E = SC + '/export_1007/'; O = SC + '/rb_analyze/out_real/'; V = SC + '/lens/context_filters/verify3/'
RUNS = {'run-20261005T014624Z': 'v3a', 'run-20261005T183457Z': 'v3b', 'current': 'v4'}
TE = pd.read_csv(O + 'trades_enriched.csv', low_memory=False)
RP = pd.read_csv(O + 'replay_signals.csv', low_memory=False)
from paperbot.config import v3_settings, DEFAULT_TIERS
from paperbot.sizing import size_position
from paperbot.levrule import quality_score
sys.path.insert(0, SC + '/rb_analyze')
import analyze as A   # only for bracket table loader
br, _ = A.make_brackets(None)
SW = v3_settings(leverage_rule='tier_walk', tiers=DEFAULT_TIERS, max_margin_frac=0.40, taker_fee=0.0005)
out = []
for run, tag in RUNS.items():
    d = E + run + '/'
    s = pd.read_csv(d + 'signal_log.csv'); s = s[s.status == 'SUBMITTED'].rename(columns={'id': 'sig_id'}).drop(columns='status')
    rows = []
    for line in open(d + 'signal_ctx.jsonl'):
        j = json.loads(line); c = j.get('ctx') or {}; sr = c.get('sr') if isinstance(c.get('sr'), dict) else {}
        r = {'sig_id': int(j['id'])}
        for k in ['regime', 'htf_regime', 'er', 'box_pos', 'htf_box_pos', 'ema20_dist_atr', 'trend_age', 'range_pct', 'adx', 'di_plus', 'di_minus']:
            r[k] = c.get(k)
        for k in ['room', 'floor', 'level_before_lock', 'support_before_stop']:
            r['sr_' + k] = sr.get(k)
        r['strength'] = json.dumps(c.get('strength')) if isinstance(c.get('strength'), dict) else None
        rows.append(r)
    s = s.merge(pd.DataFrame(rows), on='sig_id', how='left')
    acc = pd.read_csv(d + 'accounts.csv')[['account_id', 'kind']]
    s['account_id'] = s.strategy + '@' + s.timeframe
    s = s.merge(acc, on='account_id', how='left')
    s['qtier'] = [quality_score(json.loads(x), a, b).get('tier') if isinstance(x, str) else None for x, a, b in zip(s.strength, s.strategy, s.timeframe)]
    s = s.drop(columns='strength'); s['run'] = tag
    if tag == 'v3a':
        oc = pd.read_csv(d + 'outcomes.csv', low_memory=False)[['account_id', 'sig_ts', 'symbol', 'status', 'sig_tier']]
        oc = oc.drop_duplicates(['account_id', 'sig_ts', 'symbol']); oc['bar_close'] = oc.sig_ts + 1
        s = s.merge(oc.drop(columns='sig_ts'), on=['account_id', 'bar_close', 'symbol'], how='left')
        t = TE[TE.run == run][['account_id', 'signal_ts', 'symbol', 'R', 'leverage']].drop_duplicates(['account_id', 'signal_ts', 'symbol'])
        t['bar_close'] = t.signal_ts + 1
        s = s.merge(t.drop(columns='signal_ts').rename(columns={'R': 'tR', 'leverage': 'tlev'}), on=['account_id', 'bar_close', 'symbol'], how='left')
        sh = pd.read_csv(d + 'd3_shadows.csv', low_memory=False); sh = sh[(sh.kind == 'skipped') & (sh.resolved == 1)].drop_duplicates('key')
        p = sh.key.str.split('|', expand=True)
        sh = pd.DataFrame({'account_id': p[1], 'symbol': p[2], 'bar_close': p[3].astype('int64'), 'shroe': sh.roe.values})
        s = s.merge(sh, on=['account_id', 'symbol', 'bar_close'], how='left')
        lev = []
        for r in s.itertuples():
            L = np.nan
            if r.status == 'SKIPPED' and r.shroe == r.shroe and r.symbol in br:
                fill = r.ref_price * (1 + r.side * SW.slippage_frac); stop = fill - r.side * 2 * r.atr
                dd = size_position(SW, 5000.0, int(r.side), fill, stop, r.sig_tier if isinstance(r.sig_tier, str) else 'normal', br[r.symbol], atr=r.atr)
                if dd.ok: L = dd.leverage
            lev.append(L)
        s['shlev'] = lev
        sf = 2 * s.atr / s.ref_price
        s['R'] = np.where(s.status == 'ENTERED', s.tR, np.where(s.status == 'SKIPPED', s.shroe / (s.shlev * sf), np.nan))
        s['lev'] = np.where(s.status == 'ENTERED', s.tlev, s.shlev); s['flipR'] = np.nan
        s['src'] = s.status
    else:
        rp = RP[RP.run == run][['sig_id', 'status', 'R', 'flip_status', 'flip_R', 'leverage']]
        s = s.merge(rp, on='sig_id', how='left')
        s['R'] = np.where(s.status == 'TRADED', s.R, np.nan)
        s['flipR'] = np.where(s.flip_status == 'TRADED', s.flip_R, np.nan); s['lev'] = s.leverage; s['src'] = 'replay'
    out.append(s[['run', 'sig_id', 'bar_close', 'timeframe', 'strategy', 'symbol', 'side', 'atr', 'ref_price', 'kind', 'qtier', 'R', 'flipR', 'lev', 'src',
                  'regime', 'htf_regime', 'er', 'box_pos', 'htf_box_pos', 'ema20_dist_atr', 'trend_age', 'range_pct', 'adx', 'di_plus', 'di_minus',
                  'sr_room', 'sr_floor', 'sr_level_before_lock', 'sr_support_before_stop']])
D = pd.concat(out, ignore_index=True)
D['stop_pct'] = 200 * D.atr / D.ref_price
D['kst_hour'] = ((D.bar_close // 3600000 + 9) % 24).astype(int)
D['kst_day'] = ((D.bar_close + 9 * 3600000) // 86400000).astype(int)
D.to_pickle(V + 'sig.pkl')
x = D[D.timeframe.isin(['15m', '30m'])]
print(x.groupby(['run', 'kind', 'timeframe']).agg(n=('sig_id', 'size'), nR=('R', 'count'), mR=('R', 'mean')).round(3).to_string())
print(D[D.run == 'v3a'].groupby('src').lev.value_counts().unstack().fillna(0).astype(int).to_string())
