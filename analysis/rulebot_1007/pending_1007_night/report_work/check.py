"""Self-check: recompute report numbers from the CSV tables. usage: python3 -I check.py <scratchpad>"""
import csv, sys, os, collections
S = sys.argv[1]
O = os.path.join(S, 'rb_analyze/out_real')
rd = lambda p: list(csv.DictReader(open(p)))
fl = lambda v: float(v) if v not in ('', None) else None

pool = rd(os.path.join(O, 'strategy_tf_pooled.csv'))
def kt(kind, tf, col='mean_R'):
    xs = [x for x in pool if x['kind'] == kind and x['timeframe'] == tf and fl(x[col]) is not None]
    n = sum(int(x['n']) - int(x['n_R_missing'] or 0) for x in xs)
    return n, sum(fl(x[col]) * (int(x['n']) - int(x['n_R_missing'] or 0)) for x in xs) / n
for tf in ['5m', '15m', '30m', '1h', '4h']:
    n, m = kt('strategy', tf); _, c = kt('strategy', tf, 'mean_cost_all_R')
    print(f'[1] core live trades {tf}: n {n} mean R {m:+.3f} cost_all_R {c:.3f}')
for tf in ['15m', '30m', '1h', '4h']:
    n, m = kt('ds200', tf); print(f'[2] ds live trades {tf}: n {n} mean R {m:+.3f}')
n, m = kt('random', '15m'); print(f'[3] coin-flip accounts 15m n {n} mean R {m:+.3f}')
print('[4] total trades all kinds', sum(int(x['n']) for x in pool))

sf = rd(os.path.join(O, 'coinflip_sideflip.csv'))
for x in sf:
    if x['level'] == 'kind' and x['kind'] in ('strategy', 'ds200'):
        print(f"[5] side-flip {x['kind']}: pairs {x['n_pairs']} excess {float(x['excess_R']):+.4f} p {float(x['p_better']):.3f}")
cells = [x for x in sf if x['level'] == 'strategy_tf' and x['kind'] in ('strategy', 'ds200')]
print('[6] side-flip cells BH-better', sum(x['bh_reject_better_0.05'] == 'True' for x in cells), 'BH-worse', sum(x['bh_reject_worse_0.05'] == 'True' for x in cells), 'of', len(cells), 'tested', sum(x['p_better'] != '' for x in cells))

agg = rd(os.path.join(S, 'lens/fiveyear/verify3/agg_cells.csv'))
A = {(x['kind'], x['strategy'], x['tf']): x for x in agg}
for k in [('ds', 'F16_FIB382', '15m'), ('ds', 'F16_FIB500', '15m'), ('core', 'N23_HA_ST', '4h'), ('core', 'N17_KC_RSI', '1h'), ('ds', 'F15_ORB', '15m')]:
    a = A[k]; print(f"[7] 5y {k[1]}@{k[2]} gross {float(a['grossR']):+.4f} t {float(a['gross_t']):+.2f} IS {float(a['g_is']):+.4f} CF {float(a['g_cf']):+.4f} net {float(a['netR']):+.4f} n {a['n']}")
fy = rd(os.path.join(S, 'lens/fiveyear/out/fy_cells_is_cf.csv'))
F = {(x['strategy'], x['tf']): x for x in fy}
for k in [('F16_FIB382', '15m'), ('N23_HA_ST', '4h')]:
    x = F[k]; print(f"[8] fy_cells_is_cf {k}: gross {float(x['gross_R']):+.4f} t {float(x['gross_t']):+.2f} n {x['n']}")

z = rd(os.path.join(O, 'zero_trade_causes.csv'))
zz = collections.Counter()
for x in z:
    zz[(x['run'], x['kind'])] += int(x['accounts'])
print('[9] zero-trade accounts', dict(zz))

flow = rd(os.path.join(O, 'signal_flow.csv'))
for run in ['run-20261005T014624Z', 'run-20261005T183457Z', 'current']:
    xs = [x for x in flow if x['run'] == run and x['kind'] == 'strategy' and x['timeframe'] == '15m']
    out = sum(int(x['outcomes']) for x in xs)
    print(f"[10] flow {run} core 15m: entered {sum(int(x['out_ENTERED:ok']) for x in xs)/out:.1%} in-position {sum(int(x['out_SKIPPED:in position']) for x in xs)/out:.1%} submitted {sum(int(x['sig_SUBMITTED']) for x in xs)}")
print('[11] total SUBMITTED signals all runs/kinds', sum(int(x['sig_SUBMITTED']) for x in flow))
for run in ['run-20261005T014624Z', 'run-20261005T183457Z', 'current']:
    print('     ', run, sum(int(x['sig_SUBMITTED']) for x in flow if x['run'] == run))

rp = rd(os.path.join(O, 'replay_stats.csv'))
for k, s, tf in [('strategy', 'N10_HA_PSAR', '30m'), ('strategy', 'S4_BB_BBP', '15m'), ('ds200', 'F4_PULL', '15m')]:
    x = [r for r in rp if r['run'] == 'ALL' and r['kind'] == k and r['strategy'] == s and r['timeframe'] == tf][0]
    print(f"[12] replay v3b+v4 {s}@{tf}: traded {x['n_traded']} mean R {float(x['mean_R']):+.3f}")
tr = [r for r in rp if r['run'] == 'ALL' and r['kind'] in ('strategy', 'ds200', 'random', 'reel')]
print('[13] replay traded signals total', sum(int(r['n_traded']) for r in tr), 'submitted', sum(int(r['n_submitted']) for r in tr))

ps = [x for x in rd(os.path.join(S, 'lens2/multi_tf/summ/per_strategy.csv')) if x['period'] == 'all']
for s in ['C:N10_HA_PSAR', 'D:F16_FIB382']:
    for combo in ['A|FC', 'ALL|LTF', 'HI|FC']:
        x = [r for r in ps if r['strategy'] == s and r['combo'] == combo]
        if x:
            x = x[0]; print(f"[14] setup {s} {combo}: trades/day {float(x['trades_per_day']):.2f} netR {float(x['meanR']):+.3f}")
