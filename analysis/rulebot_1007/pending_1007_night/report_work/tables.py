"""Build per-strategy tables for the Korean report (read-only inputs; prints markdown).
usage: python3 -I tables.py <scratchpad_dir> <out_dir>
"""
import csv, sys, os, collections

S, OUT = sys.argv[1], sys.argv[2]
AGG = os.path.join(S, 'lens/fiveyear/verify3/agg_cells.csv')
RPS = os.path.join(S, 'rb_analyze/out_real/replay_stats.csv')
SFL = os.path.join(S, 'rb_analyze/out_real/coinflip_sideflip.csv')
PST = os.path.join(S, 'lens2/multi_tf/summ/per_strategy.csv')
TFS = ['15m', '30m', '1h', '4h']

agg = list(csv.DictReader(open(AGG)))
# BH over cells with sized n>=200 (two-sided gross p), as in the verifier
big = [x for x in agg if float(x['n']) >= 200]
ps = sorted((float(x['gross_p']), i) for i, x in enumerate(big))
m = len(ps); q = {}
prev = 1.0
for rank in range(m, 0, -1):
    p, i = ps[rank - 1]
    prev = min(prev, p * m / rank)
    q[i] = prev
Q = {}
for i, x in enumerate(big):
    Q[(x['kind'], x['strategy'], x['tf'])] = q[i]
A = {(x['kind'], x['strategy'], x['tf']): x for x in agg}

rps = [x for x in csv.DictReader(open(RPS)) if x['run'] == 'ALL']
R = {(('core' if x['kind'] == 'strategy' else 'ds'), x['strategy'], x['timeframe']): x for x in rps if x['kind'] in ('strategy', 'ds200')}

sfl = list(csv.DictReader(open(SFL)))
F = {(('core' if x['kind'] == 'strategy' else 'ds'), x['strategy'], x['timeframe']): x for x in sfl if x['level'] == 'strategy_tf' and x['kind'] in ('strategy', 'ds200')}

pst = [x for x in csv.DictReader(open(PST)) if x['period'] == 'all']
P = collections.defaultdict(dict)
for x in pst:
    P[x['strategy'].split(':', 1)[1]][x['combo']] = x

DAYS = {'core': 0.697 + 1.503, 'ds': 1.503}  # v3b+v4 / v4 (luck_flow LF10)

def f(v, d=3, sign=True):
    if v in (None, ''):
        return '-'
    v = float(v)
    s = f'{v:+.{d}f}' if sign else f'{v:.{d}f}'
    return s.replace('+0.000', '0.000').replace('-0.000', '0.000') if abs(v) < 0.5 * 10 ** -d else s

def label(kind, s, tf):
    a = A.get((kind, s, tf))
    if a is None:
        return '신호 없음', None
    n = float(a['n'])
    if n < 200:
        return '거래 너무 적음', None
    qq = Q[(kind, s, tf)]
    g = float(a['grossR'])
    if qq < 0.05:
        return ('방향 증거 + (보정 통과)' if g > 0 else '방향 증거 − (보정 통과)'), qq
    t = float(a['gross_t']); gi = float(a['g_is']); gc = float(a['g_cf'])
    if abs(t) >= 2 and gi * gc > 0:
        return ('중립 (t≥2·양쪽 반 +, 보정 실패)' if g > 0 else '중립 (t≤−2·양쪽 반 −, 보정 실패)'), qq
    return '중립', qq

def tt(a):
    return ('%+.2f' % float(a['gross_t'])) if a['gross_t'] else '-'

def halves(a):
    if not a['g_is'] or not a['g_cf']:
        return '-'
    gi = float(a['g_is']); gc = float(a['g_cf'])
    sg = lambda v: '+' if v > 0 else ('−' if v < 0 else '0')
    return f'{sg(gi)}/{sg(gc)}'

def table(kind, strategies, dupmark=None):
    rows = []
    hdr = ('| 매매법 | 봉 | 5년 신호/일 (진입 가능) | 5년 방향 R (비용 전) | t | 앞/뒤 반 | 5년 순R | 실시간 재생 n | 실시간 평균R (잡음 수준) | 라벨 |\n'
           '|---|---|---|---|---|---|---|---|---|---|')
    rows.append(hdr)
    counts = collections.Counter()
    for s in strategies:
        first = True
        for tf in TFS:
            a = A.get((kind, s, tf))
            lab, qq = label(kind, s, tf)
            counts[lab.split(' (t')[0] if lab.startswith('중립') else lab] += 1
            r = R.get((kind, s, tf))
            name = s + (f' {dupmark[s]}' if dupmark and s in dupmark and first else '')
            if a is None:
                rows.append(f'| {name if first else ""} | {tf} | 0 | - | - | - | - | {r["n_traded"] if r else 0} | {f(r["mean_R"],2) if r and r["n_traded"]!="0" else "-"} | 신호 없음 |')
            else:
                rn = r['n_traded'] if r else '0'
                rm = f(r['mean_R'], 2) if r and r['mean_R'] not in ('', None) and int(rn) > 0 else '-'
                rows.append(f'| {name if first else ""} | {tf} | {float(a["per_day"]):.1f} ({float(a["per_day_sized"]):.1f}) | {f(a["grossR"])} | {tt(a)} | {halves(a)} | {f(a["netR"])} | {rn} | {rm} | {lab} |')
            first = False
    return '\n'.join(rows), counts

core = sorted({x['strategy'] for x in agg if x['kind'] == 'core'} | {'N21_ST_RSI_ADX'})
import re
nk = lambda v: [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', v)]
ds = sorted({x['strategy'] for x in agg if x['kind'] == 'ds'}, key=nk)
DUP = {  # DS6 / LF14 merges (child -> parent)
    'F5_BOX_HTF': '(=F5_BOX 중복)', 'F13_RAID_PD': '(⊂F11_RAID 중복)', 'F11_TSOUP': '(≈F11_RAID, 15m 거래 동일)',
    'F17_Z_HL': '(⊂F17_Z 중복)', 'F12_MSS_DISP': '(⊂F12_MSS)', 'F13_FVG_PD': '(⊂F9_FVG)', 'F10_M2022': '(⊂F9_FVG)',
    'F16_FIB618': '(⊂F10_OTE)', 'F7_RF_ONLY': '(75%가 F7_RF_TRIPLE)', 'F15_OPEN0000': '(15m/30m/1h 같은 신호)',
    'F15_OPEN0930': '(15m=30m 같은 신호)',
}
tc, cc = table('core', core)
td, cd = table('ds', ds, DUP)
open(os.path.join(OUT, 'tab_core.md'), 'w').write(tc + '\n')
open(os.path.join(OUT, 'tab_ds.md'), 'w').write(td + '\n')
print('core strategies', len(core), 'ds', len(ds), 'BH family', m)
print('core label counts', dict(cc)); print('ds label counts', dict(cd))

# 5m summary (core)
r5 = [x for x in agg if x['tf'] == '5m']
print('5m cells', len(r5), 'mean netR', sum(float(x['netR']) for x in r5) / len(r5))

# setup-B per strategy (ALL|LTF) and A, HI
with open(os.path.join(OUT, 'setup.txt'), 'w') as fo:
    for s in core + ds:
        p = P.get(s, {})
        if 'ALL|LTF' in p:
            b = p['ALL|LTF']; a = p.get('A|FC'); h = p.get('HI|FC')
            fo.write(f"{s}\tB tpd {float(b['trades_per_day']):.2f} netR {float(b['meanR']):+.3f} gross {float(b['mean_gross']):+.3f}\tA tpd {float(a['trades_per_day']):.2f} netR {float(a['meanR']):+.3f}\tHI tpd {float(h['trades_per_day']):.2f} netR {float(h['meanR']):+.3f}\n")

# DS family pooled 5y gross (trade weighted) per tf
for tf in TFS:
    xs = [x for x in agg if x['kind'] == 'ds' and x['tf'] == tf and x['grossR'] and x['netR']]
    n = sum(float(x['n']) for x in xs)
    print('ds pooled', tf, 'gross', sum(float(x['grossR']) * float(x['n']) for x in xs) / n, 'net', sum(float(x['netR']) * float(x['n']) for x in xs) / n)
for tf in TFS + ['5m']:
    xs = [x for x in agg if x['kind'] == 'core' and x['tf'] == tf and x['grossR'] and x['netR']]
    n = sum(float(x['n']) for x in xs)
    print('core pooled', tf, 'gross', sum(float(x['grossR']) * float(x['n']) for x in xs) / n, 'net', sum(float(x['netR']) * float(x['n']) for x in xs) / n, 'n', n)
