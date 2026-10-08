"""Build two example AI-trader screens from real v4 export data and estimate tokens.

Usage: python3 -I build_screens.py <export_current_dir> <work_dir>
Reads only. Writes example screens + token table into <work_dir>.
No tokenizer is available offline: token counts are heuristic estimates (see est()).
"""
import csv, sys, math, datetime as dt, os, re

E, W = sys.argv[1], sys.argv[2]
COINS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BCHUSDT', 'LTCUSDT', 'DOGEUSDT']
SHORT = {c: c.replace('USDT', '') for c in COINS}
COST_FRAC = 0.0014  # assumed round trip (taker fees + slippage) as fraction of notional

bars = {c: [] for c in COINS}
for r in csv.DictReader(open(os.path.join(E, 'live_bars.csv'))):
    if r['symbol'] in bars:
        bars[r['symbol']].append((int(r['ts']), float(r['open']), float(r['high']), float(r['low']),
                                  float(r['close']), float(r['volume'])))
for c in COINS:
    bars[c].sort()


def utc(ms):
    return dt.datetime.utcfromtimestamp(ms / 1000)


def fmt_t(ms):
    u = utc(ms); k = u + dt.timedelta(hours=9)
    return f"{u:%Y-%m-%d %H:%M} UTC / {k:%m-%d %H:%M} KST"


def agg(c, tf_min, T):
    """Closed bars of tf_min minutes with close time <= T (no look-ahead)."""
    out = {}
    step = tf_min * 60000
    for ts, o, h, l, cl, v in bars[c]:
        if ts + 60000 > T:
            break
        k = ts - ts % step
        b = out.get(k)
        if b is None:
            out[k] = [k, o, h, l, cl, v, 1]
        else:
            b[2] = max(b[2], h); b[3] = min(b[3], l); b[4] = cl; b[5] += v; b[6] += 1
    res = [b for k, b in sorted(out.items()) if k + step <= T and b[6] >= tf_min * 0.9]
    return res


def wilder(vals, n):
    if len(vals) < n:
        return sum(vals) / len(vals) if vals else float('nan')
    a = sum(vals[:n]) / n
    for x in vals[n:]:
        a = (a * (n - 1) + x) / n
    return a


def ind(b):
    o = [x[1] for x in b]; h = [x[2] for x in b]; l = [x[3] for x in b]; c = [x[4] for x in b]; v = [x[5] for x in b]
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(b))]
    atr = wilder(tr, 14)
    e = c[0]; k = 2 / 21
    for x in c[1:]:
        e = x * k + e * (1 - k)
    up = [max(c[i] - c[i - 1], 0) for i in range(1, len(c))]; dn = [max(c[i - 1] - c[i], 0) for i in range(1, len(c))]
    au, ad = wilder(up, 14), wilder(dn, 14)
    rsi = 100 - 100 / (1 + au / ad) if ad > 0 else 100.0
    pdm = [max(h[i] - h[i - 1], 0) if (h[i] - h[i - 1]) > (l[i - 1] - l[i]) else 0 for i in range(1, len(b))]
    mdm = [max(l[i - 1] - l[i], 0) if (l[i - 1] - l[i]) > (h[i] - h[i - 1]) else 0 for i in range(1, len(b))]
    tr1 = tr[1:]
    # running Wilder DI and ADX
    n = 14; dx = []; pdi = mdi = 0.0
    if len(tr1) >= n:
        st, sp, sm = sum(tr1[:n]), sum(pdm[:n]), sum(mdm[:n])
        for i in range(n, len(tr1) + 1):
            if i > n:
                st = st - st / n + tr1[i - 1]; sp = sp - sp / n + pdm[i - 1]; sm = sm - sm / n + mdm[i - 1]
            pdi = 100 * sp / st if st else 0; mdi = 100 * sm / st if st else 0
            dx.append(100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi else 0)
    adx = wilder(dx, 14) if dx else float('nan')
    m = min(20, len(c) - 1)
    er = abs(c[-1] - c[-1 - m]) / sum(abs(c[i] - c[i - 1]) for i in range(len(c) - m, len(c))) if m > 0 else 0
    w = min(24, len(b))
    hi, lo = max(h[-w:]), min(l[-w:])
    box = (c[-1] - lo) / (hi - lo) if hi > lo else 0.5
    vr = v[-1] / (sum(v[-21:-1]) / len(v[-21:-1])) if len(v) > 1 else 1.0
    chg = [100 * (c[i] / c[i - 1] - 1) for i in range(max(1, len(c) - 8), len(c))]
    rg = 'trend' if (er >= 0.3 and adx == adx and adx >= 25) else ('box' if (hi - lo) / c[-1] < 6 * atr / c[-1] else 'chop')
    return dict(c=c[-1], atr=100 * atr / c[-1], atr_abs=atr, chg=chg, vr=vr, e20=(c[-1] - e) / atr, rsi=rsi,
                adx=adx, pdi=pdi, mdi=mdi, box=box, er=er, rg=rg, n=len(b))


def px(c, x):
    d = 1 if x > 1000 else (2 if x > 10 else 5)
    return f"{x:,.{d}f}"


def row_en(coin, tf, d):
    chg = ' '.join(f"{x:+.2f}" for x in d['chg'])
    adx = 'na' if d['adx'] != d['adx'] else f"{d['adx']:.0f}({d['pdi']:.0f}/{d['mdi']:.0f})"
    note = '' if d['n'] >= 30 else f" n={d['n']}"
    return (f"{tf:>3} c={px(coin, d['c'])} atr={d['atr']:.2f}% chg=[{chg}] vr={d['vr']:.1f} e20={d['e20']:+.1f} "
            f"rsi={d['rsi']:.0f} adx={adx} box={d['box']:.2f} er={d['er']:.2f} rg={d['rg']}{note}")


def row_ko(coin, tf, d):
    chg = ' '.join(f"{x:+.2f}" for x in d['chg'])
    adx = '없음' if d['adx'] != d['adx'] else f"{d['adx']:.0f}"
    tfk = {'15m': '15분', '30m': '30분', '1h': '1시간', '4h': '4시간'}[tf]
    return (f"{tfk} 종가 {px(coin, d['c'])} · ATR {d['atr']:.2f}% · 8봉 변화% {chg} · 거래량비 {d['vr']:.1f} · "
            f"EMA20 거리 {d['e20']:+.1f}ATR · RSI {d['rsi']:.0f} · ADX {adx}(DI+ {d['pdi']:.0f}/DI- {d['mdi']:.0f}) · "
            f"박스 위치 {d['box']:.2f} · 효율비 {d['er']:.2f} · 장세 {d['rg']}")


# Placeholder lines (format only; the export has no daily history, funding or OI)
DAILY_EN = "1d ret20=-3.1% c/ema50=-1.2% c/ema200=-4.0% datr=2.9% pdh=+1.1A pdl=-0.6A wopen=-2.0% today/avg14=0.8 [PLACEHOLDER]"
DAILY_KO = "일봉 20일 변화 -3.1% · EMA50 대비 -1.2% · EMA200 대비 -4.0% · 일ATR 2.9% · 전일 고점 +1.1ATR / 저점 -0.6ATR · 주 시가 대비 -2.0% · 오늘 폭/14일 평균 0.8 [자리표시]"
FUND_EN = "fund=+0.0081%/8h next=2h41m oi1h=-0.4% oi24h=+2.1% [PLACEHOLDER]"
FUND_KO = "펀딩 +0.0081%/8시간 · 다음 정산 2시간 41분 뒤 · 미결제약정 1시간 -0.4% / 24시간 +2.1% [자리표시]"


def macro_line(T, ko):
    ev = [('2026-10-14T12:30:00Z', 'CPI'), ('2026-10-28T18:00:00Z', 'FOMC'), ('2026-10-29T12:30:00Z', 'PCE')]
    out = []
    for s, k in ev:
        t = dt.datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ')
        hrs = (t - utc(T)).total_seconds() / 3600
        if 0 < hrs < 24 * 10:
            out.append(f"{k} {hrs:.0f}h" if not ko else f"{k} {hrs:.0f}시간 뒤")
    return ("schedule: " + ', '.join(out) + " | shock=none") if not ko else ("일정: " + ', '.join(out) + " · 충격 표시 없음")


def market(T, ko):
    v15 = T - T % (15 * 60000)  # market version = last 15m close
    slow, fast = [], []
    hdr = f"[시장 묶음 판 {utc(v15):%m%d-%H%M}] 기준 {fmt_t(v15)}"
    slow.append(hdr + " · 느린 층(4시간·1시간·일봉·일정)")
    slow.append(macro_line(T, ko))
    fast.append("[빠른 층(30분·15분)]")
    for c in COINS:
        slow.append(f"# {SHORT[c]}")
        slow.append(DAILY_KO if ko else DAILY_EN)
        for tf, m in (('4h', 240), ('1h', 60)):
            d = ind(agg(c, m, v15)); slow.append(row_ko(c, tf, d) if ko else row_en(c, tf, d))
        slow.append(FUND_KO if ko else FUND_EN)
        fast.append(f"# {SHORT[c]}")
        for tf, m in (('30m', 30), ('15m', 15)):
            d = ind(agg(c, m, v15)); fast.append(row_ko(c, tf, d) if ko else row_en(c, tf, d))
    return '\n'.join(slow), '\n'.join(fast)


CARD_F16 = """[매매법 카드] F16_FIB382 · 피보나치 38.2% 되돌림 (DeepSeek 정의) · 카드 판 v1 (10/17 잠금)
진입 규칙: 하락 임펄스(스윙 고점->저점, 높이 3 ATR 이상, 30봉 이내)의 38.2% 되돌림 선에 처음 닿고 종가가 그 선 아래면 숏. 롱은 대칭. 그 전에 저점을 깨면 소멸.
이 트레이더의 진입 봉: 15분, 1시간 (30분·4시간은 5년 방향 부호가 마이너스라 제외. 미리 고정)
청산: 코드가 함. 처음 손절 2 ATR(진입 봉 ATR14). 잠금·보유 상한은 청산 명세대로. 너는 HOLD/EXIT/본전 이동만.
맞춤 값: 정의의 기본값, 12/31까지 고정.
5년 숫자 (2021-08~2026-09, 매 신호 단독, 켜기 전에 계산해 고정):
- 15분: 비용 전 방향 +0.026R/거래(다중 검정 보정 통과, q 0.006) · 비용 뒤 -0.11R[예시값] · 하루 신호 10.1개
- 1시간: 비용 전 +0.015R · 비용 뒤 -0.06R[예시값] · 하루 신호 2.7개
- 한 사람 트레이더(한 번에 하나) 5년: 하루 4.9거래 · 비용 뒤 -0.113R/거래
- 이긴 거래의 80%가 견딘 최대 불리 폭 0.6R[예시값] · 보유 봉 수 중앙값 15분 12봉[예시값]
- 반기별 비용 전 방향 부호(15분): + + - + +[예시값]
뜻: 작은 진짜 기울기가 있을 수 있지만 비용보다 작다. 고르기가 비용을 넘어야 한다."""

CARD_N10 = """[매매법 카드] N10_HA_PSAR · 하이킨아시 + PSAR 추세 · 카드 판 v1 (10/17 잠금)
진입 규칙: 숏 = 하이킨아시가 최근 2봉 안에 음봉으로 바뀌고 이번 HA 봉 위꼬리가 HA 범위의 2% 이하, PSAR(0.02, 0.02, 0.2) > 종가이고 하락 상태(또는 최근 2봉 안 하락 전환). 롱은 대칭.
이 트레이더의 진입 봉: 30분 중심 + 15분·1시간 (4시간 제외. 미리 고정)
청산: 코드가 함. 처음 손절 2 ATR(진입 봉 ATR14). 잠금·보유 상한은 청산 명세대로. 너는 HOLD/EXIT/본전 이동만.
맞춤 값: 기본값, 12/31까지 고정.
5년 숫자 (매 신호 단독, 켜기 전에 계산해 고정):
- 30분: 비용 전 방향 +0.012R/거래(t 1.79, 두 반기 모두 +, 보정 통과 못 함) · 비용 뒤 -0.15R[예시값] · 하루 신호 11.3개
- 15분: 비용 전 약 0 · 하루 신호 24.5개 / 1시간: 비용 전 약 0 · 하루 신호 5.5개
- 한 사람 트레이더 5년: 하루 6.3거래 · 비용 뒤 -0.124R/거래
- 이긴 거래의 80%가 견딘 최대 불리 폭 0.7R[예시값] · 보유 봉 수 중앙값 30분 6봉[예시값]
뜻: 방향 실력의 증거가 약하다. 고르기·보유 판단이 비용을 넘어야 한다."""

JOURNAL_F16 = """[최근 진입 판단 6개 (이 트레이더의 실제 판단만. 결과·손익은 넣지 않음)]
10-07 09:00 TAKE S1 1h ETH SHORT 확신3 trend "1h 신호, 손절 0.81%, 비용 0.17R로 15분보다 쌈"
10-07 04:45 SKIP 확신2 cost "15m LTC 손절 0.80%, 비용 0.18R, 방향 근거 없음"
10-07 04:15 SKIP 확신2 none "15m BCH 롱, 1h e20 -0.4, 근거 약함"
10-06 23:30 SKIP 확신2 cost "15m BTC 손절 0.55%, 비용 0.25R"
10-06 21:45 TAKE S1 15m SOL LONG 확신2 price_structure "15m box 0.21에서 반등, 비용 0.15R"
10-06 20:15 SKIP 확신1 none "두 신호 반대 방향, 고를 근거 없음"
"""

JOURNAL_N10 = """[최근 진입 판단 6개 (이 트레이더의 실제 판단만. 결과·손익은 넣지 않음)]
10-07 04:00 TAKE S2 30m ETH SHORT 확신3 trend "30m er 0.38·e20 -1.4, S1(1h SOL 롱)은 1h e20 +0.2로 근거 약함"
10-07 03:45 SKIP 확신2 cost "15m ETH 손절 0.48%, 비용 0.29R"
10-07 03:00 SKIP 확신2 none "1h DOGE 숏, 4h box 0.12로 바닥 근처"
10-07 02:30 SKIP 확신2 cost "15m BCH 손절 0.70%, 비용 0.20R"
10-07 02:00 SKIP 확신2 none "1h BTC 숏, 1h er 0.08 횡보"
10-07 01:00 SKIP 확신1 cost "15m ETH·SOL 숏 둘 다 비용 0.17R 이상"
"""


def sig_row(slot, s, T):
    side = 'SHORT' if int(s['side']) < 0 else 'LONG'
    atr = float(s['atr']); ref = float(s['ref_price'])
    stop_frac = 2 * atr / ref
    cost_r = COST_FRAC / stop_frac
    return (f"{slot} {s['timeframe']} {SHORT[s['symbol']]} {side} · 신호가 {px(s['symbol'], ref)} · ATR {atr:.6g} ({100*atr/ref:.2f}%) · "
            f"처음 손절 2ATR = {100*stop_frac:.2f}% · 왕복 비용 {cost_r:.2f}R · 조건 모두 충족(정의상)")


def entry_screen(T, sigs):
    w = [f"[이번 깨움] 진입 화면 · 봉 마감 {fmt_t(T)} · 포지션 없음",
         "신호 (줄 순서는 매번 무작위, 우선순위 아님):"]
    for i, s in enumerate(sigs):
        w.append(sig_row(f"S{i+1}", s, T))
    w.append("답: TAKE(slot S1/S2) 또는 SKIP(slot NONE). move_stop_to_breakeven=false.")
    return '\n'.join(w)


def hold_screen(Tw, tr, price, mfe_r, mae_r, cost_r, bars_held, be_px, wake_note):
    side = int(tr['side']); e = float(tr['entry_price']); st = float(tr['stop_initial'])
    rd = abs(e - st)
    r_now = side * (price - e) / rd - cost_r
    return '\n'.join([
        f"[이번 깨움] 보유 화면 · {fmt_t(Tw)} · 깨운 이유: {wake_note}",
        f"포지션: 30분 ETH {'숏' if side < 0 else '롱'} · 진입 10-07 04:00 KST(봉 마감) {e:,.2f} · 보유 {bars_held}봉(30분) · 지금가 {price:,.2f}",
        f"지금 R(비용 뺀, 지금 청산 가정) {r_now:+.2f}R · 최대 유리 {mfe_r:+.2f}R · 최대 불리 {mae_r:+.2f}R · 1R = {rd:.2f} ({100*rd/e:.2f}%)",
        f"코드 청산 상태: 손절 {st:,.2f} (-1.00R, 지금가에서 {abs(st-price)/(rd/2):.1f}ATR) · 잠금 미발동 · 안전 보유 상한까지 {48-bars_held}봉 [청산 명세 값으로 바뀜]",
        f"본전 이동 가능: 예 (최대 유리 +1R 넘음) · 본전가 {be_px:,.2f} (진입가 ± 왕복 비용 {cost_r:.2f}R)",
        "펀딩: 다음 정산 3시간 41분 뒤 · 예상 비용 0.01R [자리표시]",
        "들어갈 때 쓴 이유: \"30m er 0.38·e20 -1.4\" · 무효 조건: \"30분 종가가 2,701 위로 마감\"",
        "이 거래의 보유 판단: 30분 마감 점검 13번 모두 HOLD(확신 2~3) · 마지막 셋: 09:30 HOLD 3 \"무효 조건 미충족, +0.2R\", 10:00 HOLD 3 \"30m e20 -1.2 유지\", 10:30 HOLD 3 \"30m box 0.03, 무효 조건 멂\"",
        "답: HOLD 또는 EXIT (slot NONE). 본전 이동 원하면 move_stop_to_breakeven=true."])


HANGUL = re.compile(r'[가-힣]')


def est(text):
    """Return dict of token estimates. A = analyst rule (ASCII/3.2 + Hangul*0.95 + other*1.0).
    B = token-class rule (digit run ceil(len/3); ASCII letter run ceil(len/6) min 1; ASCII punctuation 1;
    newline 1; space 0; Hangul 0.7/1.0/1.3; other non-ASCII 1.5)."""
    ascii_n = sum(1 for ch in text if ord(ch) < 128)
    hang = len(HANGUL.findall(text))
    other = len(text) - ascii_n - hang
    A = ascii_n / 3.2 + hang * 0.95 + other * 1.0
    base = 0
    for m in re.finditer(r'\d+|[A-Za-z]+|\n|[ \t]+|[\x21-\x2f\x3a-\x40\x5b-\x60\x7b-\x7e]|.', text, re.S):
        s = m.group(0)
        if s.isdigit():
            base += math.ceil(len(s) / 3)
        elif s.isascii() and s.isalpha():
            base += max(1, math.ceil(len(s) / 6))
        elif s == '\n':
            base += 1
        elif s.strip() == '':
            base += 0
        elif s.isascii():
            base += 1
        elif HANGUL.match(s):
            pass
        else:
            base += 1.5
    return dict(chars=len(text), A=round(A), B_low=round(base + 0.7 * hang), B_mid=round(base + 1.0 * hang),
                B_high=round(base + 1.3 * hang))


sigs = {r['id']: r for r in csv.DictReader(open(os.path.join(E, 'signal_log.csv'))) if r['id'] in ('4025', '4026')}
T1 = int(sigs['4026']['bar_close'])
# order per setup B: same tf -> widest stop first
S = [sigs['4025'], sigs['4026']]  # randomized slot order (seed logged); rule pick under setup B = widest stop = DOGE

tr = next(t for t in csv.DictReader(open(os.path.join(E, 'trades.csv'))) if t['id'] == '940')
e, st, side = float(tr['entry_price']), float(tr['stop_initial']), int(tr['side'])
rd = abs(e - st); t0 = int(float(tr['entry_time']))
cost_r = COST_FRAC * e / rd
mfe = mae = 0.0; Tw = None; price = None
for ts, o, h, l, c, v in bars['ETHUSDT']:
    if ts < t0:
        continue
    fav = (e - l) / rd if side < 0 else (h - e) / rd
    adv = (e - h) / rd if side < 0 else (l - e) / rd
    mfe = max(mfe, fav); mae = min(mae, adv)
    if mfe >= 1.0:
        Tw = ts + 60000; price = c; break
bars_held = (Tw - t0) // (30 * 60000)
be_px = e * (1 - COST_FRAC) if side < 0 else e * (1 + COST_FRAC)

sysko = open(os.path.join(W, 'system_ko.txt'), encoding='utf-8').read()
outs = {}
for lang in ('ko', 'en'):
    s1, f1 = market(T1, lang == 'ko')
    s2, f2 = market(Tw, lang == 'ko')
    outs[lang] = dict(entry=[('system', sysko), ('market_slow', s1), ('market_fast', f1), ('card', CARD_F16),
                             ('journal', JOURNAL_F16), ('wake', entry_screen(T1, S))],
                      hold=[('system', sysko), ('market_slow', s2), ('market_fast', f2), ('card', CARD_N10),
                            ('journal', JOURNAL_N10),
                            ('wake', hold_screen(Tw, tr, price, mfe, mae, cost_r, bars_held, be_px,
                                                 '1.0R 유리한 움직임(쿨다운 15분)'))])

lines = ["screen,lang,part,chars,A,B_low,B_mid,B_high"]
for lang in outs:
    for scr, parts in outs[lang].items():
        tot = dict(chars=0, A=0, B_low=0, B_mid=0, B_high=0)
        for name, text in parts:
            x = est(text)
            lines.append(f"{scr},{lang},{name},{x['chars']},{x['A']},{x['B_low']},{x['B_mid']},{x['B_high']}")
            for k in tot:
                tot[k] += x[k]
        lines.append(f"{scr},{lang},TOTAL,{tot['chars']},{tot['A']},{tot['B_low']},{tot['B_mid']},{tot['B_high']}")
        if lang == 'en' or True:
            with open(os.path.join(W, f"screen_{scr}_{lang}.txt"), 'w', encoding='utf-8') as fh:
                for name, text in parts:
                    fh.write(f"===== {name} =====\n{text}\n")
open(os.path.join(W, 'tokens.csv'), 'w').write('\n'.join(lines) + '\n')
print('\n'.join(lines))
print('T1', fmt_t(T1), 'Tw', fmt_t(Tw), 'price', price, 'mfe', round(mfe, 2), 'mae', round(mae, 2), 'cost_r', round(cost_r, 3),
      'bars_held', bars_held, 'be_px', round(be_px, 2), 'rd', round(rd, 2))
for s in S:
    print(s['id'], s['symbol'], s['atr'], s['ref_price'], 'stop%', round(200 * float(s['atr']) / float(s['ref_price']), 3),
          'costR', round(COST_FRAC / (2 * float(s['atr']) / float(s['ref_price'])), 3))
