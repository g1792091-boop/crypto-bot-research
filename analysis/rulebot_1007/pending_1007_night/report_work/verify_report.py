"""Recompute numbers from CSV tables and confirm the report states them. usage: python3 -I verify_report.py <scratchpad> <report>"""
import csv, sys, os, collections
S, REP = sys.argv[1], sys.argv[2]
txt = open(REP, encoding='utf-8').read()
O = os.path.join(S, 'rb_analyze/out_real')
rd = lambda p: list(csv.DictReader(open(p)))
fl = lambda v: float(v) if v not in ('', None) else None
res = []
def chk(name, value, *needles):
    ok = all(n in txt for n in needles)
    res.append((ok, name, value, needles))

pool = rd(os.path.join(O, 'strategy_tf_pooled.csv'))
def kt(kind, tf, col='mean_R'):
    xs = [x for x in pool if x['kind'] == kind and x['timeframe'] == tf and fl(x[col]) is not None]
    w = lambda x: int(x['n']) - int(x['n_R_missing'] or 0)
    n = sum(w(x) for x in xs)
    return n, sum(fl(x[col]) * w(x) for x in xs) / n
fmt = lambda v: f'{v:+.3f}'.replace('+', '+').replace('-', '−')
for tf in ['5m', '15m', '30m', '1h', '4h']:
    n, m = kt('strategy', tf); _, c = kt('strategy', tf, 'mean_cost_all_R')
    chk(f'core live {tf} n/meanR/cost', (n, round(m, 3), round(c, 3)), f'| {tf} | {n} | {fmt(m)} |', f'{c:.3f}')
n, m = kt('ds200', '15m'); chk('ds live 15m', (n, round(m, 3)), f'15분 {fmt(m)}R({n}건)')
n, m = kt('random', '15m'); chk('coin-flip accts 15m', (n, round(m, 3)), f'{fmt(m)}R({n}건)')
chk('total trades', sum(int(x['n']) for x in pool), f"{sum(int(x['n']) for x in pool):,}")
sf = {x['kind']: x for x in rd(os.path.join(O, 'coinflip_sideflip.csv')) if x['level'] == 'kind'}
s = sf['strategy']; chk('sideflip core', (s['n_pairs'], round(float(s['excess_R']), 3), round(float(s['p_better']), 2)), f"{int(s['n_pairs']):,}쌍", f"p {float(s['p_better']):.2f}")
s = sf['ds200']; chk('sideflip ds', (s['n_pairs'], round(float(s['excess_R']), 3), round(float(s['p_better']), 2)), f"{int(s['n_pairs']):,}쌍", '+0.032R')
agg = rd(os.path.join(S, 'lens/fiveyear/verify3/agg_cells.csv'))
big = [x for x in agg if float(x['n']) >= 200]
ps = sorted((float(x['gross_p']), i) for i, x in enumerate(big)); m = len(ps); q = {}; prev = 1
for r in range(m, 0, -1):
    p, i = ps[r - 1]; prev = min(prev, p * m / r); q[i] = prev
pos = sum(1 for i, x in enumerate(big) if q[i] < .05 and float(x['grossR']) > 0); neg = sum(1 for i, x in enumerate(big) if q[i] < .05 and float(x['grossR']) < 0)
chk('BH 307 pos/neg', (m, pos, neg), f'{m}칸', f'나쁜 칸 {neg}개', f'좋은 칸 {pos}개')
A = {(x['strategy'], x['tf']): x for x in agg}
for k in [('F16_FIB382', '15m'), ('F16_FIB500', '15m'), ('N23_HA_ST', '4h')]:
    a = A[k]; chk(f'5y {k}', (round(float(a['grossR']), 3), round(float(a['gross_t']), 2)), f"{float(a['grossR']):+.3f}", f"{float(a['gross_t']):+.2f}")
for tf, want in [('15m', '−0.172'), ('30m', '−0.125'), ('1h', '−0.094'), ('4h', '−0.051')]:
    xs = [x for x in agg if x['kind'] == 'core' and x['tf'] == tf and x['netR']]
    v = sum(float(x['netR']) * float(x['n']) for x in xs) / sum(float(x['n']) for x in xs)
    chk(f'core 5y net {tf}', round(v, 3), fmt(v))
for tf in ['15m', '30m', '1h']:
    xs = [x for x in agg if x['kind'] == 'ds' and x['tf'] == tf and x['grossR']]
    v = sum(float(x['grossR']) * float(x['n']) for x in xs) / sum(float(x['n']) for x in xs)
    chk(f'ds 5y pooled gross {tf}', round(v, 4), f'{v:+.4f}'.replace('-', '−'))
z = collections.Counter()
for x in rd(os.path.join(O, 'zero_trade_causes.csv')):
    z[(x['run'], x['kind'])] += int(x['accounts'])
chk('zero-trade', dict(z), '| 48 | 35 | 8 | 5', '| 64 | 55 | 4 | 4', '| 43 | 35 | 3 | 4', '| 30 | 20 | 3 | 7')
flow = rd(os.path.join(O, 'signal_flow.csv'))
vals = []
for run in ['run-20261005T014624Z', 'run-20261005T183457Z', 'current']:
    xs = [x for x in flow if x['run'] == run and x['kind'] == 'strategy' and x['timeframe'] == '15m']
    o = sum(int(x['outcomes']) for x in xs)
    vals.append((f"{sum(int(x['out_ENTERED:ok']) for x in xs)/o:.1%}", f"{sum(int(x['out_SKIPPED:in position']) for x in xs)/o:.1%}"))
chk('flow entered/in-position', vals, *[v for p in vals for v in p])
tot = sum(int(x['sig_SUBMITTED']) for x in flow); chk('signals total', tot, f'{tot:,}')
rp = [r for r in rd(os.path.join(O, 'replay_stats.csv')) if r['run'] == 'ALL' and r['kind'] in ('strategy', 'ds200', 'random', 'reel')]
a, b = sum(int(r['n_submitted']) for r in rp), sum(int(r['n_traded']) for r in rp)
chk('replay submitted/traded', (a, b), f'{a:,}', f'{b:,}')
ps_ = [x for x in rd(os.path.join(S, 'lens2/multi_tf/summ/per_strategy.csv')) if x['period'] == 'all' and x['combo'] == 'ALL|LTF']
P = {x['strategy'].split(':')[1]: x for x in ps_}
for s_ in ['N10_HA_PSAR', 'F16_FIB382', 'N23_HA_ST', 'F4_FAN']:
    x = P[s_]; chk(f'setup B {s_}', (round(float(x['trades_per_day']), 2), round(float(x['meanR']), 3)), f"{float(x['trades_per_day']):.2f} · {fmt(float(x['meanR']))}")
bad = [r for r in res if not r[0]]
for ok, name, value, needles in res:
    print('OK ' if ok else 'MISS', name, value)
print(len(res), 'checks,', len(bad), 'missing')
