"""The friend's chart-mix indicators ("차트 믹스", owners 10-29) as the live bots read them (Pine semantics, closed bars).

Three parts of the friend's TradingView scripts (차트 믹스 · 차트 믹스 + OBV · 차트 믹스 + 스톡 RSI):

1. the trend, four votes on a closed bar, +1 up / -1 down / 0 sideways (owners 10-29: "같은 추세가 2개 이상 나와야 그 추세로
   인정 하지만 추세신호 2개 횡보신호 2개가 나오면 진입 금지", "찹존은 노란색만 횡보 슈퍼트랜드 노란색도 횡보 3번도 진입금지"):
     line   the sky / purple line: ROC 9 · RSI 26 · MOM 10 summed, above its EMA 9 signal = sky (up), else purple (down)
     ema    the EMA RSI band's middle-line colour: EMA RSI >= 50 green (up), else red (down); the default mode
            '가격 · EMA 거리' (EMA 21 / 52, normalised over 100 bars, EMA 3)
     chop   the chop zone 9 band: zones +1 .. +4 up, -1 .. -4 down, 0 (yellow) sideways
     st     the supertrend average (ATR 14, factors 6 and 3): both up / both down; mixed (yellow) sideways
   trend: two or more sideways -> 0 (no entry); else the side with two or more votes and more than the other; 2-2 -> 0.
2. the OBV pane (차트 아래, '누적 (OBV 형식)', the script's defaults): the line = the running sum of the averaged, normalised
   OBV flow and Klinger (21 / 34) volume force, its EMA 9 signal; the conditional state cs (+1 when the averaged RSI
   (RSI 26 · ROC 7 · MOM 7, EMA 3) says up and the line is above its signal, -1 the mirror, else kept); the histogram
   (line - the conditional signal) is dark when its size grew on this bar, light when it did not; green while cs is +1,
   red while -1. Owners 10-29: "연한색에서 진한색으로 변할때 진입" -> long on the bar where light green turns dark green
   (cs +1 on both bars), short on light red turning dark red.
3. the Stoch RSI pane (14 · 11 · 4 · 6, '노이즈 줄이기' 보통 = K through one more EMA 3, the cross confirmed past 2 points):
   golden ● when the confirmed state turns to K above D, dead ● when it turns to K below D. Owners 10-29: "스톡 rsi가
   50선 밑에서 롱신호가 나오면 진입 50선 위에서 숏 신호뜨면 진입" -> long on a golden ● with K under 50, short on a dead ●
   with K over 50 (the ● is drawn at K).

4. the OBV pane's 50 line ('OBV 50' script, owners 10-30): the same line drawn RSI-style, 50 + 50 tanh((line - EMA 52 of
   the line) / (stdev 100 of that gap x 2)); under 50 = the line under its EMA 52. Owners 10-30: "obv가 50선 밑에서 진한색으로
   변하면 롱진입 … obv 50선 위에서 롱진입 금지 50선 밑에서 숏 진입금지" -> the light -> dark turn of part 2, long only
   under 50, short only over 50.
5. the OBV ROC pane ('OBV ROC + EMA 21 · 52 (RSI 형식)', owners 10-30): ROC 12 of the close weighted by the volume
   direction (the same OBV · Klinger line's 12-bar move, tanh over its 100-bar stdev): roc x (1 + sign(roc) x vdir) / 2,
   drawn 0 ~ 100 (tanh over its 100-bar stdev x 2: the purple line), its EMA 21 and EMA 52, and the bar between them:
   green while EMA 21 >= EMA 52, red under; dark while their gap (its EMA 2) widens, light while it narrows. Owners 10-30
   ("봉이 진한거"): long on the bar where a light green bar turns dark green with the purple line under 50, short on light
   red turning dark red over 50.
6. WOO X Pro 2's trend (owners 10-30, 15m): the sky / purple line, the chop zone and the supertrend average (no EMA RSI):
   long needs the sky line with the chop zone and the supertrend each sideways or down and at least one sideways
   ("파란선 이여야 하고 찹존이나 슈퍼트랜드 두개중 하나가 횡보 … 같은 추세가 2개 이상이면 진입 금지 … 찹존이랑 슈퍼트랜드가
   같이 횡보면 진입 가능"; owners 10-30: chop sideways with the supertrend down is a long too); short the mirror.
7. '추세 3개 일치' (EMARSI_ALL.pine, owners 10-31, 15m): three trends, the EMA RSI line (green over 50 / red under, part 1's
   ema), the sky / purple line (part 1's line) and the supertrend average of ATR 14 with factors 3 and 5 (both up / both
   down / mixed = sideways); the histogram under it is the EMA RSI's distance from 50, green over / red under, dark while
   that distance (its EMA 2) grows, light while it shrinks. Owners 10-31 ("추세 지표중에 3개 이상 같은 추세 … 횡보 추세가
   2개 이상 나오면 진입 금지 상승 2개 하락1개 나와도 진입 금지 … 그 포지션에 맞는 진한 히스토그램이 나오면 진입", and their
   answer: the light -> dark bar): long on the bar where the three are up and a light green bar turns dark green; short
   the mirror. The script's other filters (overheat, overbought / oversold, its own exits) are not used (owners 10-31).
8. OBV MACD's AC histogram (OBV_MACD.pine, owners 10-31): part 2's OBV pane drawn MACD-style (the same line, the same
   conditional signal); its default histogram 'AC 오실레이터 (가속)' = (line - the conditional signal) - its SMA 5, green
   while it rose on this bar, red while it fell (grey: equal or not yet defined). Owners 10-31 (the 바이비트 봇 and the
   friend bot: "상승 추세에서 초록진한선이 뜨는데 히스토그램이 플러스 양봉이면 진입 … 플러스 음봉이면 진입 금지", the dark line =
   their answer: part 2's light -> dark turn, "50일선위 숏 아래 롱은 삭제"): long on a light -> dark green turn with the AC
   bar over 0 and green; short on a light -> dark red turn with the AC bar under 0 and red; no 50 line.
9. '추세 바' and 'ALL + OBV6 MACD' (추세 바만.pine, WOOX_pro2.pine, owners 10-31 night: "이 추세지표는 레인지봇,
   바이비트봇, woo x pro 2친구봇에 공통으로 쓰이는 추세지표"): the trend of all three bots is the trend bar's 종합 over six
   rows: ① 3개 점수 (sky / purple +-1, EMA RSI +-1, the supertrend average 14 · 3 / 14 · 5 +-1 or 0; +2 or more up, -2 or
   less down, else sideways), ② 6종 평균 (OBV - EMA 20, ROC 9, Klinger 34 / 55, MACD 12 / 26, AO 5 / 34, AC 5, each
   zsq over 100, x 100, EMA 3: >= 0 up, else down), ③ the sky / purple line (up / down, equal: sideways), ④ EMA RSI (> 50 up,
   < 50 down), ⑤ the supertrend average (both up / both down / mixed: sideways), ⑥ 4종 평균 (AO, AC, OBV, Klinger the same
   way). 종합: two or more sideways, or two or more up with two or more down -> 0 (노랑, no entry); else two or more up -> +1,
   two or more down -> -1. 'ALL + OBV6 MACD' (its defaults): A = 2 x (EMA RSI - 50), B = the mean of the OBV line's
   distance from its EMA 52 (zsq over 100, x 100) and ② 6종 평균; their mean through EMA 3 is the MACD line, its EMA 9 the
   signal, the histogram = line - signal. Owners 10-31 night (WOO X Pro 2 and the 레인지 봇: "15분봉 진입 추세 바를 통해서
   추세를 정하고 그리고 추세에 맞게 히스토 그램이 0선 돌파 할때 진입"): long on the bar where the histogram crosses above 0
   with 종합 up, short where it crosses below 0 with 종합 down (Pine's crossover / crossunder of 0).

Every series is computed over the whole bar history given (oldest first) and read on its last value: the recursive parts
(EMA, RMA, SAR, supertrend, the running sums, the kept states) settle long before the last of 1,000+ bars. The Pine
helpers come from paperbot/mixchop.py (EMA, RSI, population stdev, zsq, ROC, MOM, ATR, supertrend: the friend bot's,
matched to TradingView); the rest follows the scripts and TradingView's documented built-ins line by line. Pine's
zsq(na) is 0 (its `sd > 0` is false), so every zsq of an undefined value counts 0 here.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import mixchop as M

VOTES = ("line", "ema", "chop", "st")
VOTE_KO = {"line": "하늘·보라 선", "ema": "EMA RSI", "chop": "찹존", "st": "슈퍼트렌드"}
TREND_KO = {1: "상승", -1: "하락", 0: "진입 금지"}
STOCH = (14, 11, 4, 6)          # RSI, stochastic, K SMA, D SMA
STOCH_SMOOTH = 3                # '노이즈 줄이기' 보통: K through EMA 3
STOCH_GAP = 2.0                 # '교차 확인 폭': K - D past this to change the state


def _nz(x, d: float = 0.0) -> np.ndarray:
    x = np.asarray(x, float)
    return np.where(np.isfinite(x), x, d)


def _zsq0(x, n: int) -> np.ndarray:
    """Pine zsq(x, n): tanh(x / stdev) or 0 (also 0 where x is na)."""
    return _nz(M.zsq(x, n))


def _tanh(x) -> np.ndarray:
    """The scripts' tanh: exp of 2 x clamped to +-10 (na stays na)."""
    with np.errstate(invalid="ignore"):
        return np.tanh(np.clip(np.asarray(x, float), -10, 10))


def _clamp1(x) -> np.ndarray:
    return np.clip(_nz(x), -1.0, 1.0)


def highest(x, n: int) -> np.ndarray:
    return pd.Series(np.asarray(x, float)).rolling(n, min_periods=n).max().to_numpy()


def lowest(x, n: int) -> np.ndarray:
    return pd.Series(np.asarray(x, float)).rolling(n, min_periods=n).min().to_numpy()


def lag(x, k: int) -> np.ndarray:
    x = np.asarray(x, float)
    return np.r_[np.full(k, np.nan), x[:-k]] if k > 0 else x


def change(x) -> np.ndarray:
    """ta.change: x - x[1], na on the first bar."""
    x = np.asarray(x, float)
    return np.r_[np.nan, np.diff(x)]


def obv(close, volume) -> np.ndarray:
    """ta.obv = ta.cum(math.sign(ta.change(close)) * volume); the first bar adds nothing."""
    return np.cumsum(_nz(np.sign(change(close)) * np.asarray(volume, float)))


def sar(high, low, close, start: float = 0.02, inc: float = 0.02, mx: float = 0.2) -> np.ndarray:
    """ta.sar as TradingView documents it (the Pine reference implementation)."""
    h, l, c = (np.asarray(a, float) for a in (high, low, close))
    n = len(c)
    out = np.full(n, np.nan)
    result = max_min = acc = math.nan
    below = False
    for i in range(1, n):
        first = False
        if i == 1:
            if c[1] > c[0]:
                below, max_min, result = True, h[1], l[0]
            else:
                below, max_min, result = False, l[1], h[0]
            first, acc = True, start
        result = result + acc * (max_min - result)
        if below:
            if result > l[i]:
                first, below = True, False
                result, max_min, acc = max(h[i], max_min), l[i], start
        else:
            if result < h[i]:
                first, below = True, True
                result, max_min, acc = min(l[i], max_min), h[i], start
        if not first:
            if below:
                if h[i] > max_min:
                    max_min, acc = h[i], min(acc + inc, mx)
            else:
                if l[i] < max_min:
                    max_min, acc = l[i], min(acc + inc, mx)
        if below:
            result = min(result, l[i - 1])
            if i > 1:
                result = min(result, l[i - 2])
        else:
            result = max(result, h[i - 1])
            if i > 1:
                result = max(result, h[i - 2])
        out[i] = result
    return out


# ====================================================================== 1. the trend
def chop_zone(o, h, l, c, v) -> np.ndarray:
    """종합 찹존 9 (all nine on, sensitivity 1.0, smoothing 3): zones +4 .. -4, 0 = 횡보 (yellow)."""
    h, l, c, v = (np.asarray(a, float) for a in (h, l, c, v))
    atr = M.atr(h, l, c, 14)
    atr_ok = np.isfinite(atr) & (atr > 0)
    hlc3 = (h + l + c) / 3.0
    # 1. chop zone: the EMA 34 slope as an angle
    hh, ll = highest(h, 30), lowest(l, 30)
    with np.errstate(invalid="ignore", divide="ignore"):
        span = np.where(hh - ll > 0, 25.0 / (hh - ll) * ll, 0.0)
        e34 = M.ema(c, 34)
        prev = np.where(np.isfinite(lag(e34, 1)), lag(e34, 1), e34)
        y2 = np.where(hlc3 > 0, (prev - e34) / hlc3 * span, 0.0)
        ang1 = np.floor(180.0 * np.arccos(1.0 / np.sqrt(1.0 + y2 * y2)) / math.pi + 0.5)
        angle = np.where(y2 > 0, -ang1, ang1)
    s1 = _clamp1(angle / 5.0)
    # 2 · 3. AC / AO
    hl2 = (h + l) / 2.0
    ao = M.sma(hl2, 5) - M.sma(hl2, 34)
    ac = ao - M.sma(ao, 5)
    s2, s3 = _zsq0(ac, 100), _zsq0(ao, 100)
    # 4. RSI 14
    s4 = _clamp1((_nz(M.rsi(c, 14), 50.0) - 50.0) / 50.0)
    # 5. OBV against its EMA 20, only once some volume has traded (hasVol = ta.cum(volume) > 0)
    ob = obv(c, v)
    has_vol = np.cumsum(_nz(v)) > 0
    s5 = np.where(has_vol, _zsq0(ob - M.ema(ob, 20), 100), 0.0)
    # 6. EMA 21 / 52
    with np.errstate(invalid="ignore", divide="ignore"):
        s6 = np.where(atr_ok, _tanh((M.ema(c, 21) - M.ema(c, 52)) / (2.0 * atr)), 0.0)
    # 7. MACD 12 / 26 / 9: the line and the histogram
    ml = M.ema(c, 12) - M.ema(c, 26)
    mh = ml - M.ema(ml, 9)
    s7 = (_zsq0(ml, 100) + _zsq0(mh, 100)) / 2.0
    # 8. parabolic SAR
    with np.errstate(invalid="ignore", divide="ignore"):
        s8 = np.where(atr_ok, _tanh((c - sar(h, l, c)) / (2.0 * atr)), 0.0)

    # 9. Ichimoku 9 / 26 / 52, the cloud 26 bars on (the values 25 bars back)
    def don(n):
        return (highest(h, n) + lowest(l, n)) / 2.0
    conv, base, spb = don(9), don(26), don(52)
    spa = (conv + base) / 2.0
    a25, b25 = lag(spa, 25), lag(spb, 25)
    with np.errstate(invalid="ignore", divide="ignore"):
        both = np.isfinite(a25) & np.isfinite(b25)
        top = np.where(both, np.fmax(a25, b25), np.nan)
        bot = np.where(both, np.fmin(a25, b25), np.nan)
        cloud = np.where(c > top, _tanh((c - top) / (2.0 * atr)), np.where(c < bot, -_tanh((bot - c) / (2.0 * atr)), 0.0))
        tk = np.where(atr_ok, _tanh((conv - base) / atr), 0.0)
        s9 = np.where(atr_ok, 0.6 * _nz(cloud) + 0.4 * _nz(tk), 0.0)
    total = sum(_nz(s) for s in (s1, s2, s3, s4, s5, s6, s7, s8, s9))
    used = 8.0 + has_vol                                # the OBV term counts once volume has traded
    sc = M.ema(total / used, 3) * 1.0
    zone = np.zeros(len(c), np.int8)
    for lim, z in ((0.60, 4), (0.40, 3), (0.25, 2), (0.10, 1)):
        zone = np.where((zone == 0) & (sc >= lim), z, zone)
    for lim, z in ((-0.60, -4), (-0.40, -3), (-0.25, -2), (-0.10, -1)):
        zone = np.where((zone == 0) & (sc <= lim), z, zone)
    return zone.astype(np.int8)


def ema_rsi(c) -> np.ndarray:
    """EMA RSI ('가격 · EMA 거리' mode): EMA 3 of 50 + 50 x the mean of three zsq'd distances."""
    c = np.asarray(c, float)
    e1, e2 = M.ema(c, 21), M.ema(c, 52)
    sc = (_zsq0(c - e1, 100) + _zsq0(c - e2, 100) + _zsq0(e1 - e2, 100)) / 3.0
    return M.ema(50.0 + 50.0 * sc, 3)


def trend_of(line, ema, chop, st) -> np.ndarray:
    """The owners' rule on the four votes: 2+ sideways -> 0; else the side with 2+ votes and more than the other."""
    V = np.vstack([np.asarray(x) for x in (line, ema, chop, st)])
    nu, nd, ns = (V == 1).sum(0), (V == -1).sum(0), (V == 0).sum(0)
    return np.where(ns >= 2, 0, np.where((nu >= 2) & (nu > nd), 1,
                                         np.where((nd >= 2) & (nd > nu), -1, 0))).astype(np.int8)


def votes(o, h, l, c, v) -> dict:
    """The four votes and the trend per bar (each from that bar's close: read the last closed bar)."""
    line = np.where(M.line_gold(c), 1, -1).astype(np.int8)
    er = ema_rsi(c)
    ema = np.where(er >= 50, 1, -1).astype(np.int8)
    zone = chop_zone(o, h, l, c, v)
    chop = np.sign(zone).astype(np.int8)
    _, up6 = M.supertrend(h, l, c, 14, 6.0)
    _, up3 = M.supertrend(h, l, c, 14, 3.0)
    st = np.where(up6 & up3, 1, np.where(~up6 & ~up3, -1, 0)).astype(np.int8)
    return {"line": line, "ema": ema, "chop": chop, "st": st, "trend": trend_of(line, ema, chop, st), "ema_rsi": er,
            "chop_zone": zone}


def last_trend(o, h, l, c, v) -> dict:
    """The trend on the last bar: {"trend", "line", "ema", "chop", "st", "ema_rsi", "chop_zone"} (plain ints / floats)."""
    V = votes(o, h, l, c, v)
    er = float(V["ema_rsi"][-1])
    return {"trend": int(V["trend"][-1]), **{k: int(V[k][-1]) for k in VOTES},
            "ema_rsi": round(er, 2) if math.isfinite(er) else None, "chop_zone": int(V["chop_zone"][-1])}


def vote_words(t: dict) -> str:
    """'하늘·보라 선 상승 · EMA RSI 상승 · 찹존 횡보 · 슈퍼트렌드 상승' (a vote 0 = 횡보)."""
    ko = {1: "상승", -1: "하락", 0: "횡보"}
    return " · ".join(f"{VOTE_KO[k]} {ko.get(int(t.get(k, 0)), '?')}" for k in VOTES if k in t)


def trend_words(t: dict) -> str:
    """'상승 (하늘·보라 선 상승 · …)' / '진입 금지 (…)'."""
    return f"{TREND_KO.get(int(t.get('trend', 0)), '?')} ({vote_words(t)})"


# ====================================================================== 2. the OBV pane
def _nrm(x, n: int) -> np.ndarray:
    """nrm(x, len): x / sma(|x|, len), 0 where that average is na or 0."""
    x = np.asarray(x, float)
    a = M.sma(np.abs(x), n)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(np.isfinite(a) & (a > 0), x / np.where(a > 0, a, 1.0), 0.0)


def mix_line(h, l, c, v) -> np.ndarray:
    """The OBV · Klinger line both panes share (트렌드 믹스 통합 라인, '누적 (OBV 형식)'): the running sum of the averaged
    OBV flow and Klinger (21 / 34) volume force, each normalised over 50 bars."""
    h, l, c = (np.asarray(a, float) for a in (h, l, c))
    vol = _nz(v)
    chg = change(c)
    flow = np.where(chg > 0, vol, np.where(chg < 0, -vol, 0.0))
    sv = np.where(change((h + l + c) / 3.0) >= 0, vol, -vol)   # na >= 0 is false: the first bar counts -volume
    kvo = M.ema(sv, 21) - M.ema(sv, 34)
    return np.cumsum(_nz((_nrm(flow, 50) + _nrm(kvo, 50)) / 2.0))


def obv_pane(h, l, c, v) -> dict:
    """The OBV pane of '차트 믹스 + OBV' (its defaults): {"line", "sig", "cs", "dark"} per bar. cs: +1 green, -1 red, 0 grey
    (before the first state); dark: the histogram (line - the conditional signal) grew in size on this bar."""
    c = np.asarray(c, float)
    n = len(c)
    ar = M.avg_rsi(c)                                   # RSI 26 · ROC 7 · MOM 7, normalised over 100, EMA 3
    line = mix_line(h, l, c, v)
    sig = M.ema(line, 9)
    gold = np.where(np.isfinite(sig), line > sig, False)
    cs = np.zeros(n, np.int8)
    trend = 0
    state = 0
    for i in range(n):
        a = ar[i]
        if math.isfinite(a):
            trend = 1 if a > 50 else (-1 if a < 50 else trend)
        if trend == 1 and gold[i]:
            state = 1
        elif trend == -1 and not gold[i]:
            state = -1
        cs[i] = state
    eps = np.maximum(np.abs(line) * 1e-6, 1e-9)
    with np.errstate(invalid="ignore"):                 # math.min / math.max with na is na (np.minimum keeps NaN)
        cond = np.where(cs == 1, np.minimum(sig, line - eps), np.where(cs == -1, np.maximum(sig, line + eps), sig))
    hist = np.abs(line - cond)
    prev = lag(hist, 1)
    with np.errstate(invalid="ignore"):
        grew = np.where(np.isfinite(hist) & np.isfinite(prev), hist > prev, False)
    # A bar whose line sits on the wrong side of its signal while cs is kept is drawn eps high (a hairline): its size is
    # eps = |line| x 1e-6, so whether it "grew" depends on where the running sum started (the chart's first loaded bar),
    # not on the market. Such a bar counts as light; only a real bar (green: line over the signal, red: under) is dark.
    real = ((cs == 1) & gold) | ((cs == -1) & ~gold & np.isfinite(sig))
    return {"line": line, "sig": sig, "cs": cs, "dark": (grew & real).astype(bool), "real": real, "hist": line - cond}


def obv_state(h, l, c, v) -> dict:
    """On the last bar: {"turn": +1 light green -> dark green / -1 light red -> dark red / 0 (a hairline bar is light),
    "cs": the histogram's colour (+1 green, -1 red, 0 grey), "dark": is it dark}."""
    P = obv_pane(h, l, c, v)
    cs, dark = P["cs"], P["dark"]
    if len(cs) < 1:
        return {"turn": 0, "cs": 0, "dark": False}
    turn = int(cs[-1]) if len(cs) >= 2 and cs[-1] == cs[-2] and cs[-1] != 0 and dark[-1] and not dark[-2] else 0
    return {"turn": turn, "cs": int(cs[-1]), "dark": bool(dark[-1])}


def obv_turn(h, l, c, v) -> int:
    """On the last bar: +1 light green -> dark green, -1 light red -> dark red, else 0 (a hairline bar is light)."""
    return obv_state(h, l, c, v)["turn"]


# ====================================================================== 4. the OBV pane's 50 line (owners 10-30)
OBV50_BASE = 52                 # '50 기준선 = 통합 라인의 EMA'
OBV50_NORM = 100                # '크기 맞춤 기간'
OBV50_SENS = 2.0                # '민감도'


def to50(x, base, norm: int, sens: float) -> np.ndarray:
    """The scripts' RSI-style drawing: 50 + 50 tanh((x - base) / (stdev_norm(x - base) x sens)); 50 where that stdev is
    0 or na (Pine: oSd > 0 is false)."""
    d = np.asarray(x, float) - np.asarray(base, float)
    sd = M.stdev(d, norm)
    pos = np.isfinite(sd) & (sd > 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(pos, 50.0 + 50.0 * _tanh(d / (np.where(pos, sd, 1.0) * sens)), 50.0)


def obv50_state(h, l, c, v) -> dict:
    """On the last bar: the OBV turn of part 2 with the 50 line: {"turn", "cs", "dark", "d50": the line drawn 0 ~ 100,
    "side": +1 a light -> dark green turn under 50 / -1 light -> dark red over 50 / 0}."""
    P = obv_pane(h, l, c, v)
    cs, dark = P["cs"], P["dark"]
    d50 = to50(P["line"], M.ema(P["line"], OBV50_BASE), OBV50_NORM, OBV50_SENS)
    if len(cs) < 1:
        return {"turn": 0, "cs": 0, "dark": False, "d50": None, "side": 0}
    turn = int(cs[-1]) if len(cs) >= 2 and cs[-1] == cs[-2] and cs[-1] != 0 and dark[-1] and not dark[-2] else 0
    x = float(d50[-1])
    side = 1 if turn > 0 and x < 50 else (-1 if turn < 0 and x > 50 else 0)
    return {"turn": turn, "cs": int(cs[-1]), "dark": bool(dark[-1]), "d50": round(x, 2) if math.isfinite(x) else None,
            "side": side}


# ====================================================================== 8. OBV MACD's AC histogram (owners 10-31)
AC_LEN = 5                      # 'AC: SMA 기간'


def ac_pane(h, l, c, v) -> dict:
    """Part 2's OBV pane with OBV MACD's AC histogram per bar: "ac" = (line - the conditional signal) - its SMA 5,
    "ac_col" +1 green (rose on this bar) / -1 red (fell) / 0 grey (equal, or not defined yet)."""
    P = obv_pane(h, l, c, v)
    hraw = np.asarray(P["hist"], float)
    ac = hraw - M.sma(hraw, AC_LEN)
    prev = lag(ac, 1)
    with np.errstate(invalid="ignore"):
        ok = np.isfinite(ac) & np.isfinite(prev)
        col = np.where(ok, np.where(ac > prev, 1, np.where(ac < prev, -1, 0)), 0).astype(np.int8)
    return {**P, "ac": ac, "ac_col": col}


def ac_side(turn: int, ac: float, col: int) -> int:
    """The owners' 10-31 entry: a green turn with the AC bar plus and green (+1), a red turn with it minus and red (-1)."""
    if not math.isfinite(ac):
        return 0
    if turn > 0 and ac > 0 and col > 0:
        return 1
    if turn < 0 and ac < 0 and col < 0:
        return -1
    return 0


def ac_words(ac, col) -> str:
    """'플러스 양봉(0.42)' / '마이너스 음봉(-0.31)' / '플러스 음봉(0.12)' …"""
    try:
        a = float(ac)
    except (TypeError, ValueError):
        return "못 읽음"
    if not math.isfinite(a):
        return "못 읽음"
    sign = "플러스" if a > 0 else "마이너스" if a < 0 else "0"
    bar = "양봉" if col and int(col) > 0 else "음봉" if col and int(col) < 0 else "보합"
    return f"{sign} {bar}({a:.2f})"


def obvac_state(h, l, c, v) -> dict:
    """On the last bar: {"turn", "cs", "dark" (part 2), "ac", "ac_col", "side": ac_side}."""
    P = ac_pane(h, l, c, v)
    cs, dark = P["cs"], P["dark"]
    if len(cs) < 2:
        return {"turn": 0, "cs": 0, "dark": False, "ac": None, "ac_col": 0, "side": 0}
    turn = int(cs[-1]) if cs[-1] == cs[-2] and cs[-1] != 0 and dark[-1] and not dark[-2] else 0
    ac, col = float(P["ac"][-1]), int(P["ac_col"][-1])
    return {"turn": turn, "cs": int(cs[-1]), "dark": bool(dark[-1]),
            "ac": round(ac, 4) if math.isfinite(ac) else None, "ac_col": col, "side": ac_side(turn, ac, col)}


# ====================================================================== 5. the OBV ROC pane (owners 10-30)
ROC_LEN = 12                    # 'ROC 기간'
ROC_FAST, ROC_SLOW = 21, 52     # its EMAs
ROC_NORM = 100                  # '크기 맞춤 기간' (0 ~ 100)
ROC_SENS = 2.0                  # '민감도'
ROC_NORM_V = 100                # '거래량 방향 크기 맞춤 기간'
ROC_WEAK = 2                    # '힘 판단 평활 기간'


def roc_pane(h, l, c, v) -> dict:
    """The OBV ROC pane (its defaults) per bar: {"osc": the purple line 0 ~ 100, "ef", "es": its EMA 21 / 52, "cs": the
    bar's colour (+1 green: EMA 21 >= EMA 52, -1 red), "dark": the gap widening (its EMA 2 grew in size)}."""
    c = np.asarray(c, float)
    vol = _nz(v)
    line = mix_line(h, l, c, v)
    dmix = line - lag(line, ROC_LEN)
    dsd = M.stdev(dmix, ROC_NORM_V)
    pos = np.isfinite(dsd) & (dsd > 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        vdir = np.where(pos, _tanh(dmix / np.where(pos, dsd, 1.0)), 0.0)
        prev = lag(c, ROC_LEN)
        raw = 100.0 * (c - prev) / prev
    has_vol = np.cumsum(vol) > 0
    obv_roc = np.where(has_vol, raw * (1.0 + np.sign(raw) * vdir) / 2.0, raw)
    osc = to50(obv_roc, np.zeros(len(c)), ROC_NORM, ROC_SENS)
    ef, es = M.ema(osc, ROC_FAST), M.ema(osc, ROC_SLOW)
    with np.errstate(invalid="ignore"):
        gap = M.ema(ef - es, ROC_WEAK)
        weak = np.where(np.isfinite(gap) & np.isfinite(lag(gap, 1)), np.abs(gap) < np.abs(lag(gap, 1)), False)
        cs = np.where(ef >= es, 1, -1).astype(np.int8)          # na >= na is false: red
    return {"osc": osc, "ef": ef, "es": es, "cs": cs, "dark": ~weak}


def roc_state(h, l, c, v) -> dict:
    """On the last bar: {"turn": +1 light -> dark green bar / -1 light -> dark red / 0, "cs", "dark", "osc", "side": +1 a
    green turn with the purple line under 50 / -1 a red turn over 50 / 0}."""
    P = roc_pane(h, l, c, v)
    cs, dark, osc = P["cs"], P["dark"], P["osc"]
    if len(cs) < 2:
        return {"turn": 0, "cs": int(cs[-1]) if len(cs) else 0, "dark": bool(dark[-1]) if len(cs) else False,
                "osc": None, "side": 0}
    turn = int(cs[-1]) if cs[-1] == cs[-2] and dark[-1] and not dark[-2] else 0
    x = float(osc[-1])
    side = 1 if turn > 0 and x < 50 else (-1 if turn < 0 and x > 50 else 0)
    return {"turn": turn, "cs": int(cs[-1]), "dark": bool(dark[-1]), "osc": round(x, 2) if math.isfinite(x) else None,
            "side": side}


# ====================================================================== 6. WOO X Pro 2's trend (owners 10-30)
SWING_KO = {1: "롱 가능", -1: "숏 가능", 0: "진입 금지"}


def swing_side(t: dict) -> int:
    """+1 / -1 / 0 from the votes ``line``, ``chop``, ``st`` (part 6): the line's side, with the chop zone and the
    supertrend each sideways or against it, at least one sideways."""
    side, chop, st = int(t.get("line", 0)), int(t.get("chop", 0)), int(t.get("st", 0))
    if side == 0 or chop == side or st == side or (chop != 0 and st != 0):
        return 0
    return side


def swing_words(t: dict) -> str:
    """'롱 가능 (하늘·보라 선 상승 · 찹존 횡보 · 슈퍼트렌드 하락)'."""
    ko = {1: "상승", -1: "하락", 0: "횡보"}
    vs = " · ".join(f"{VOTE_KO[k]} {ko.get(int(t.get(k, 0)), '?')}" for k in ("line", "chop", "st") if k in t)
    return f"{SWING_KO.get(swing_side(t), '?')} ({vs})"


# ====================================================================== 7. 추세 3개 일치 (owners 10-31)
EMA3_ST = (3.0, 5.0)            # the supertrend average's two factors (ATR 14)
EMA3_WEAK = 2                   # '막대 진한색 / 연한색 판단 평활'
EMA3_VOTES = (("ema", "EMA RSI"), ("line", "하늘·보라 선"), ("st", "슈퍼트렌드"))


def ema3_pane(h, l, c) -> dict:
    """Per bar: {"ersi": the EMA RSI, "ema" +1 green / -1 red / 0, "line" +1 sky / -1 purple, "st" +1 both up / -1 both
    down / 0 mixed, "trend" +1 all three up / -1 all three down / 0, "cs" the histogram's colour (= ema), "dark"}."""
    c = np.asarray(c, float)
    er = ema_rsi(c)
    ema = np.where(er > 50, 1, np.where(er < 50, -1, 0)).astype(np.int8)
    line = np.where(M.line_gold(c), 1, -1).astype(np.int8)
    _, up_a = M.supertrend(h, l, c, 14, EMA3_ST[0])
    _, up_b = M.supertrend(h, l, c, 14, EMA3_ST[1])
    st = np.where(up_a & up_b, 1, np.where(~up_a & ~up_b, -1, 0)).astype(np.int8)
    trend = np.where((ema == 1) & (line == 1) & (st == 1), 1, np.where((ema == -1) & (line == -1) & (st == -1), -1, 0))
    dev = M.ema(np.abs(er - 50.0), EMA3_WEAK)
    with np.errstate(invalid="ignore"):
        dark = np.where(np.isfinite(dev) & np.isfinite(lag(dev, 1)), dev > lag(dev, 1), False)
    return {"ersi": er, "ema": ema, "line": line, "st": st, "trend": trend.astype(np.int8), "cs": ema, "dark": dark}


def ema3_state(h, l, c) -> dict:
    """On the last bar: {"trend", "votes", "ersi", "cs", "dark", "turn": +1 light -> dark green / -1 light -> dark red / 0,
    "side": the turn when the three trends are on its side, else 0}."""
    P = ema3_pane(h, l, c)
    cs, dark = P["cs"], P["dark"]
    n = len(cs)
    votes = {k: int(P[k][-1]) for k, _ko in EMA3_VOTES} if n else {k: 0 for k, _ko in EMA3_VOTES}
    if n < 2:
        return {"trend": 0, "votes": votes, "ersi": None, "cs": 0, "dark": False, "turn": 0, "side": 0}
    turn = int(cs[-1]) if cs[-1] == cs[-2] and cs[-1] != 0 and dark[-1] and not dark[-2] else 0
    tr = int(P["trend"][-1])
    x = float(P["ersi"][-1])
    return {"trend": tr, "votes": votes, "ersi": round(x, 2) if math.isfinite(x) else None, "cs": int(cs[-1]),
            "dark": bool(dark[-1]), "turn": turn, "side": turn if turn and tr == turn else 0}


def ema3_words(t: dict) -> str:
    """'3개 상승 (EMA RSI 초록 · 하늘·보라 선 하늘 · 슈퍼트렌드 상승)' / '진입 금지 (…)'."""
    v = t.get("votes") or {}
    tr = int(t.get("trend") or 0)
    head = {1: "3개 상승", -1: "3개 하락"}.get(tr, "진입 금지")
    ko = {"ema": {1: "초록", -1: "빨강", 0: "50"}, "line": {1: "하늘", -1: "보라"}, "st": {1: "상승", -1: "하락", 0: "횡보"}}
    return f"{head} ({' · '.join(f'{name} {ko[k].get(int(v.get(k, 0)), chr(63))}' for k, name in EMA3_VOTES)})"


# ====================================================================== 9. 추세 바 · ALL + OBV6 MACD (owners 10-31 night)
BAR_ROWS = (("score", "3개 점수"), ("six", "6종 평균"), ("line", "하늘·보라 선"), ("ema", "EMA RSI"), ("st", "슈퍼트렌드"),
            ("four", "4종 평균"))
BAR_ST = (5.0, 3.0)                     # the supertrend average's two factors (ATR 14), as part 7's
H6_SMOOTH, H6_SIG = 3, 9                # 'ALL + OBV6 MACD': its MACD line's EMA, its signal's EMA


def _z100(x) -> np.ndarray:
    """nz(zsq(x, 100)): 0 where undefined (the scripts' nz around every zsq)."""
    return _nz(M.zsq(x, 100))


def six_four(h, l, c, v) -> tuple[np.ndarray, np.ndarray]:
    """(② 6종 평균, ⑥ 4종 평균) per bar, the trend bar's (and 'ALL + OBV6 MACD''s v6 / v4): OBV - EMA 20, ROC 9, Klinger
    EMA 34 - EMA 55 of the volume force, MACD EMA 12 - EMA 26, AO SMA 5 - SMA 34 of hl2, AC AO - SMA 5; each zsq over 100,
    their mean x 100 through EMA 3."""
    h, l, c = (np.asarray(a, float) for a in (h, l, c))
    vol = _nz(v)
    ob = obv(c, vol)
    sv = np.where(change((h + l + c) / 3.0) >= 0, vol, -vol)   # na >= 0 is false: the first bar counts -volume
    hl2 = (h + l) / 2.0
    ao = M.sma(hl2, 5) - M.sma(hl2, 34)
    zO, zR, zK = _z100(ob - M.ema(ob, 20)), _z100(M.roc(c, 9)), _z100(M.ema(sv, 34) - M.ema(sv, 55))
    zM, zAo, zAc = _z100(M.ema(c, 12) - M.ema(c, 26)), _z100(ao), _z100(ao - M.sma(ao, 5))
    six = M.ema(100.0 * (zO + zR + zK + zM + zAo + zAc) / 6.0, 3)
    four = M.ema(100.0 * (zAo + zAc + zO + zK) / 4.0, 3)
    return six, four


def bar_pane(h, l, c, v) -> dict:
    """The trend bar per bar: each row (+1 / -1 / 0), the 3-score, the counts and 종합 ("trend")."""
    h, l, c = (np.asarray(a, float) for a in (h, l, c))
    er = ema_rsi(c)
    with np.errstate(invalid="ignore"):
        ema = np.where(er > 50, 1, np.where(er < 50, -1, 0))
    score_l = ((M._nz(M.rsi(c, 26), 50.0) - 50.0) / 50.0 + _z100(M.roc(c, 9)) + _z100(M.mom(c, 10))) / 3.0
    nline = np.cumsum(score_l)
    nsig = M.ema(nline, 9)
    with np.errstate(invalid="ignore"):
        line = np.where(nline > nsig, 1, np.where(nline < nsig, -1, 0))
    _, up_a = M.supertrend(h, l, c, 14, BAR_ST[0])
    _, up_b = M.supertrend(h, l, c, 14, BAR_ST[1])
    st = np.where(up_a & up_b, 1, np.where(~up_a & ~up_b, -1, 0))
    score = line + ema + st
    six, four = six_four(h, l, c, v)
    with np.errstate(invalid="ignore"):
        rows = {"score": np.where(score >= 2, 1, np.where(score <= -2, -1, 0)), "six": np.where(six >= 0, 1, -1),
                "line": line, "ema": ema, "st": st, "four": np.where(four >= 0, 1, -1)}
    up = sum((r == 1).astype(int) for r in rows.values())
    dn = sum((r == -1).astype(int) for r in rows.values())
    sd = len(rows) - up - dn
    trend = np.where((sd >= 2) | ((up >= 2) & (dn >= 2)), 0, np.where(up >= 2, 1, np.where(dn >= 2, -1, 0)))
    return {"rows": {k: r.astype(np.int8) for k, r in rows.items()}, "score": score.astype(np.int8), "up": up, "down": dn,
            "side": sd, "trend": trend.astype(np.int8), "ersi": er, "six": six, "four": four}


def bar_state(h, l, c, v) -> dict:
    """On the last bar: {"trend": 종합, "rows": {row: +1 / -1 / 0}, "n": [up, down, sideways], "score", "ersi"}."""
    P = bar_pane(h, l, c, v)
    if not len(P["trend"]):
        return {"trend": 0, "rows": {}, "n": [0, 0, 0], "score": 0, "ersi": None}
    er = float(P["ersi"][-1])
    return {"trend": int(P["trend"][-1]), "rows": {k: int(r[-1]) for k, r in P["rows"].items()},
            "n": [int(P["up"][-1]), int(P["down"][-1]), int(P["side"][-1])], "score": int(P["score"][-1]),
            "ersi": round(er, 2) if math.isfinite(er) else None}


ROW_KO = {"score": {1: "상승", -1: "하락", 0: "횡보"}, "six": {1: "상승", -1: "하락"}, "line": {1: "하늘", -1: "보라", 0: "같음"},
          "ema": {1: "초록", -1: "빨강", 0: "50"}, "st": {1: "상승", -1: "하락", 0: "횡보"}, "four": {1: "상승", -1: "하락"}}


def bar_words(t: dict) -> str:
    """'종합 상승 (상승 5 · 하락 1 · 횡보 0: 3개 점수 +3 · 6종 상승 · 하늘·보라 선 하늘 · EMA RSI 초록 · 슈퍼트렌드 상승 ·
    4종 하락)'; 종합 노랑: '종합 횡보(진입 금지) (…)'."""
    rows = t.get("rows") or {}
    n = t.get("n") or [None, None, None]
    head = {1: "종합 상승", -1: "종합 하락"}.get(int(t.get("trend") or 0), "종합 횡보(진입 금지)")
    parts = []
    for k, ko in BAR_ROWS:
        if k not in rows or rows[k] is None:
            continue
        if k == "score":
            sc = t.get("score")
            parts.append(f"{ko} {'+' if sc is not None and sc > 0 else ''}{sc}" if sc is not None else
                         f"{ko} {ROW_KO[k].get(int(rows[k]), '?')}")
        else:
            parts.append(f"{ko} {ROW_KO[k].get(int(rows[k]), '?')}")
    count = f"상승 {n[0]} · 하락 {n[1]} · 횡보 {n[2]}" if None not in n else ""
    inner = ": ".join(x for x in (count, " · ".join(parts)) if x)
    return f"{head} ({inner})" if inner else head


def h6_pane(h, l, c, v) -> dict:
    """'ALL + OBV6 MACD' per bar (its defaults): {"macd", "sig", "hist", "cross": +1 the histogram crossed above 0 on this
    bar / -1 below / 0}."""
    h, l, c = (np.asarray(a, float) for a in (h, l, c))
    a = 2.0 * (ema_rsi(c) - 50.0)
    ml = mix_line(h, l, c, v)
    vobv = 100.0 * _z100(ml - M.ema(ml, 52))
    six, _four = six_four(h, l, c, v)
    avg = (a + (vobv + six) / 2.0) / 2.0
    macd = M.ema(avg, H6_SMOOTH)
    sig = M.ema(macd, H6_SIG)
    hist = macd - sig
    prev = lag(hist, 1)
    with np.errstate(invalid="ignore"):
        ok = np.isfinite(hist) & np.isfinite(prev)
        cross = np.where(ok & (hist > 0) & (prev <= 0), 1, np.where(ok & (hist < 0) & (prev >= 0), -1, 0))
    return {"macd": macd, "sig": sig, "hist": hist, "cross": cross.astype(np.int8)}


def h0x_side(cross: int, trend: int) -> int:
    """The owners' entry: a cross of 0 on 종합's side (+1 / -1), else 0."""
    return int(cross) if cross and int(cross) == int(trend) else 0


def h0x_state(h, l, c, v) -> dict:
    """On the last bar: {"cross", "hist", "macd", "bar": bar_state, "side": h0x_side}."""
    H = h6_pane(h, l, c, v)
    B = bar_state(h, l, c, v)
    if not len(H["hist"]):
        return {"cross": 0, "hist": None, "macd": None, "bar": B, "side": 0}
    x, hv, mv = int(H["cross"][-1]), float(H["hist"][-1]), float(H["macd"][-1])
    return {"cross": x, "hist": round(hv, 4) if math.isfinite(hv) else None,
            "macd": round(mv, 3) if math.isfinite(mv) else None, "bar": B, "side": h0x_side(x, B["trend"])}


# ====================================================================== 10. 추세 MACD · OBV4 MACD · 3합 히스토그램 (owners 11-02)
TM_SMOOTH, TM_SIG = 3, 9                # 추세 MACD: its MACD line's EMA, its signal's EMA
O4_SMOOTH, O4_SIG, O4_AC = 3, 9, 5      # OBV4 MACD: the MACD line's EMA, the signal's EMA, the AC histogram's SMA
H3_SIG = 9                              # 3합 히스토그램: the signal's EMA (EMA, cSm 1 = the average itself)
TM_KO = {1: "상승", -1: "하락", 0: "0선"}


def _cross0(hist) -> np.ndarray:
    """Pine ta.crossover(hist, 0) / ta.crossunder(hist, 0) per bar: +1 / -1 / 0 (the bar before at or past 0)."""
    prev = lag(hist, 1)
    with np.errstate(invalid="ignore"):
        ok = np.isfinite(hist) & np.isfinite(prev)
        return np.where(ok & (hist > 0) & (prev <= 0), 1, np.where(ok & (hist < 0) & (prev >= 0), -1, 0)).astype(np.int8)


def tmacd_pane(h, l, c, v) -> dict:
    """'추세 지표 MACD' (추세 MACD.pine, its defaults) per bar: the trend bar's six rows as values -100 ~ +100 (③ sky /
    purple: 100 zsq(line - its EMA 9), ④ EMA RSI: 2 (EMA RSI - 50), ⑤ supertrend: 100 zsq(close - the average of the
    supertrend lines 14 · 5 and 14 · 3), ① 3개 점수: the mean of ③ ④ ⑤, ② 6종 and ⑥ 4종 as they are), their mean through
    EMA 3 = the MACD line, its EMA 9 the signal, the histogram = line - signal. Owners 11-02 ("30분봉 추세 … macd
    히스토그램으로 사용 0선 위에 있으면 상승 0선 아래에 있으면 하락", "노란 히스토그램이 나와도 0선 아래에 있으면 하락추세 … 0선
    위에 있으면 상승추세"): "trend" = the histogram's sign (+1 over 0, -1 under, 0 on it or undefined), whatever its colour;
    "yellow" = the trend bar's 종합 is 횡보 there (the script draws that bar yellow: said, not used)."""
    h, l, c = (np.asarray(a, float) for a in (h, l, c))
    er = ema_rsi(c)
    score_l = ((M._nz(M.rsi(c, 26), 50.0) - 50.0) / 50.0 + _z100(M.roc(c, 9)) + _z100(M.mom(c, 10))) / 3.0
    nline = np.cumsum(score_l)
    nsig = M.ema(nline, 9)
    st_a, _ = M.supertrend(h, l, c, 14, BAR_ST[0])
    st_b, _ = M.supertrend(h, l, c, 14, BAR_ST[1])
    su = (st_a + st_b) / 2.0
    v_n = 100.0 * _z100(nline - nsig)
    v_e = 2.0 * (er - 50.0)
    v_s = 100.0 * _z100(c - np.where(np.isfinite(su), su, c))
    v_1 = (v_n + v_e + v_s) / 3.0
    six, four = six_four(h, l, c, v)
    macd = M.ema((v_1 + six + v_n + v_e + v_s + four) / 6.0, TM_SMOOTH)
    sig = M.ema(macd, TM_SIG)
    hist = macd - sig
    with np.errstate(invalid="ignore"):
        trend = np.where(hist > 0, 1, np.where(hist < 0, -1, 0)).astype(np.int8)
    B = bar_pane(h, l, c, v)
    return {"macd": macd, "sig": sig, "hist": hist, "trend": trend, "yellow": B["trend"] == 0}


def tmacd_state(h, l, c, v) -> dict:
    """On the last bar: {"trend" +1 / -1 / 0, "hist", "macd", "yellow"}."""
    P = tmacd_pane(h, l, c, v)
    if not len(P["hist"]):
        return {"trend": 0, "hist": None, "macd": None, "yellow": False}
    hv, mv = float(P["hist"][-1]), float(P["macd"][-1])
    return {"trend": int(P["trend"][-1]), "hist": round(hv, 3) if math.isfinite(hv) else None,
            "macd": round(mv, 3) if math.isfinite(mv) else None, "yellow": bool(P["yellow"][-1])}


def tmacd_words(t: dict) -> str:
    """'히스토그램 0선 위 상승(+3.21)' / '히스토그램 0선 아래 하락(−1.40, 노란 막대)' / '히스토그램 0선(진입 안 함)'."""
    tr = int(t.get("trend") or 0)
    hv = t.get("hist")
    val = f"{hv:+.2f}" if isinstance(hv, (int, float)) and math.isfinite(hv) else "못 읽음"
    yl = ", 노란 막대" if t.get("yellow") else ""
    if tr > 0:
        return f"히스토그램 0선 위 상승({val}{yl})"
    if tr < 0:
        return f"히스토그램 0선 아래 하락({val}{yl})"
    return f"히스토그램 0선(진입 안 함, {val})"


def o4_pane(h, l, c, v) -> dict:
    """'OBV · AO · AC · MACD 합친 평균 MACD' (OBV4 MACD, its defaults: all four on, weight 1, the OBV line '누적') per bar:
    ① the OBV · Klinger line (21 / 34) - its EMA 52, ② AO SMA 5 - SMA 34 of hl2, ③ AC = AO - its SMA 5, ④ MACD EMA 12 -
    EMA 26; each zsq over 100, their mean x 100 through EMA 3 = the MACD line, its EMA 9 the signal; the histogram (the
    default 'AC 오실레이터 (가속)') = (line - signal) - its SMA 5, green while it rose on this bar, red while it fell.
    "col" +1 / -1 / 0 (equal or undefined); "turn" +1 = green now and not green on the bar before (the script's 'AC 초록
    전환'), -1 = red now and not red before. Owners 11-02 (the 바이비트 봇: "obv 선은 사용 안함 히스토그램으로 진입 … 15분봉
    obv 히스토그램이 0선 아래에서 양봉으로 바뀌면 롱진입 숏 진입은 반대 조건"): "side" +1 = a green turn under 0, -1 = a red
    turn over 0."""
    h, l, c = (np.asarray(a, float) for a in (h, l, c))
    ml = mix_line(h, l, c, v)
    hl2 = (h + l) / 2.0
    ao = M.sma(hl2, 5) - M.sma(hl2, 34)
    zs = (_z100(ml - M.ema(ml, 52)), _z100(ao), _z100(ao - M.sma(ao, 5)), _z100(M.ema(c, 12) - M.ema(c, 26)))
    macd = M.ema(100.0 * sum(zs) / 4.0, O4_SMOOTH)
    sig = M.ema(macd, O4_SIG)
    hraw = macd - sig
    ac = hraw - M.sma(hraw, O4_AC)
    prev = lag(ac, 1)
    with np.errstate(invalid="ignore"):
        ok = np.isfinite(ac) & np.isfinite(prev)
        col = np.where(ok, np.where(ac > prev, 1, np.where(ac < prev, -1, 0)), 0).astype(np.int8)
    pcol = np.r_[0, col[:-1]].astype(np.int8)
    turn = np.where((col == 1) & (pcol != 1), 1, np.where((col == -1) & (pcol != -1), -1, 0)).astype(np.int8)
    with np.errstate(invalid="ignore"):
        side = np.where((turn > 0) & (ac < 0), 1, np.where((turn < 0) & (ac > 0), -1, 0)).astype(np.int8)
    return {"macd": macd, "sig": sig, "ac": ac, "col": col, "turn": turn, "side": side}


def o4_state(h, l, c, v) -> dict:
    """On the last bar: {"ac", "col", "turn", "side", "macd"}."""
    P = o4_pane(h, l, c, v)
    if not len(P["ac"]):
        return {"ac": None, "col": 0, "turn": 0, "side": 0, "macd": None}
    a, mv = float(P["ac"][-1]), float(P["macd"][-1])
    return {"ac": round(a, 4) if math.isfinite(a) else None, "col": int(P["col"][-1]), "turn": int(P["turn"][-1]),
            "side": int(P["side"][-1]), "macd": round(mv, 3) if math.isfinite(mv) else None}


def o4_words(ac, turn) -> str:
    """'0선 아래 양봉 전환(−3.20)' / '0선 위 음봉 전환(2.10)' / '0선 위 양봉 전환(1.10)' / '전환 없음(0.40)'."""
    try:
        a = float(ac)
    except (TypeError, ValueError):
        a = math.nan
    val = f"{a:.2f}" if math.isfinite(a) else "못 읽음"
    t = int(turn or 0)
    if not t:
        return f"전환 없음({val})"
    where = "0선 아래" if math.isfinite(a) and a < 0 else "0선 위" if math.isfinite(a) and a > 0 else "0선"
    return f"{where} {'양봉' if t > 0 else '음봉'} 전환({val})"


def _qz(x) -> np.ndarray:
    """The 15종 MACD's qz(x): EMA 3 of nz(tanh(x / stdev_100(x))) (0 where that stdev is 0 or na)."""
    return M.ema(_nz(M.zsq(x, 100)), 3)


def _tsi(c, short: int, long: int) -> np.ndarray:
    """Pine ta.tsi(close, short, long): EMA short of EMA long of the change over the same of its size."""
    pc = change(c)
    num = M.ema(M.ema(pc, long), short)
    den = M.ema(M.ema(np.abs(pc), long), short)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(np.isfinite(den) & (den != 0), num / np.where(den != 0, den, 1.0), np.nan)


def _mfi(src, vol, n: int) -> np.ndarray:
    """Pine ta.mfi(src, n): 100 - 100 / (1 + upper / lower), the n-bar sums of the volume x src of the bars where src
    rose / fell (the first bar's na change counts on both sides, as Pine's na comparisons do); na where lower is 0."""
    src = np.asarray(src, float)
    ch = change(src)
    with np.errstate(invalid="ignore"):
        up = vol * np.where(ch <= 0.0, 0.0, src)
        dn = vol * np.where(ch >= 0.0, 0.0, src)
    upper = pd.Series(up).rolling(n, min_periods=n).sum().to_numpy()
    lower = pd.Series(dn).rolling(n, min_periods=n).sum().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(np.isfinite(lower) & (lower != 0), 100.0 - 100.0 / (1.0 + upper / np.where(lower != 0, lower, 1.0)),
                        np.nan)


def _poc(h, l, c, vol, n: int = 100, bins: int = 24) -> np.ndarray:
    """The 15종 MACD's VPVR point of control per bar (from bar n on): the last n bars' hlc3 binned in 24 rows between
    their lowest low and highest high, weighted by volume; the middle of the first fullest row; na before / when flat."""
    hlc3 = (h + l + c) / 3.0
    hi, lo = highest(h, n), lowest(l, n)
    out = np.full(len(c), np.nan)
    for t in range(n, len(c)):
        rg = hi[t] - lo[t]
        if not (math.isfinite(rg) and rg > 0):
            continue
        x = hlc3[t - n + 1:t + 1]
        k = np.clip(np.floor((x - lo[t]) / rg * bins), 0, bins - 1)
        k = np.where(np.isfinite(k), k, 0).astype(int)        # (an na hlc3: Pine's int(na) is na -> its clamp gives 0)
        w = np.bincount(k, weights=vol[t - n + 1:t + 1], minlength=bins)
        if w.max() > 0:
            out[t] = lo[t] + (int(np.argmax(w)) + 0.5) * rg / bins
    return out


Q15_KEYS = ("bb", "rsi", "mfi", "wpr", "mom", "vo", "uo", "ao", "ac", "smio", "poc", "vsma", "smma", "ma52", "macd")


def q15_parts(o, h, l, c, v) -> dict:
    """The 15종 MACD's fifteen inputs per bar (Q15_KEYS, its defaults), before their qz: ① BB %B (20, 2) - 0.5, ② RSI 14
    - 50, ③ MFI 14 of hlc3 - 50, ④ %R 14 + 50, ⑤ MOM 10, ⑥ the volume oscillator (EMA 5 / EMA 10) only on its plus side,
    signed by the 5-bar move (already its own EMA 3: no qz), ⑦ the ultimate oscillator (7 / 14 / 28) - 50, ⑧ AO, ⑨ AC,
    ⑩ SMIO (TSI 5 / 20 - its EMA 5), ⑪ the VPVR point of control's distance in ATR 14, ⑫ the signed volume over its SMA 20
    (EMA 3), ⑬ close - SMMA 21, ⑭ close - SMA 52, ⑮ MACD 12 / 26."""
    o, h, l, c = (np.asarray(a, float) for a in (o, h, l, c))
    vol = _nz(v)
    at = M.atr(h, l, c, 14)
    bm = M.sma(c, 20)
    dev = 2.0 * M.stdev(c, 20)
    with np.errstate(invalid="ignore", divide="ignore"):
        bw = 2.0 * dev                                          # upper - lower
        pb = np.where(bw > 0, (c - (bm - dev)) / np.where(bw > 0, bw, 1.0) - 0.5, 0.0)
        hh, ll = highest(h, 14), lowest(l, 14)
        wpr = np.where(hh - ll != 0, 100.0 * (c - hh) / np.where(hh - ll != 0, hh - ll, 1.0), np.nan)
    hl2 = (h + l) / 2.0
    ao = M.sma(hl2, 5) - M.sma(hl2, 34)
    vs = M.ema(vol, 10)
    with np.errstate(invalid="ignore", divide="ignore"):
        vo = np.where(vs > 0, 100.0 * (M.ema(vol, 5) - vs) / np.where(vs > 0, vs, 1.0), 0.0)
    vd = M.stdev(vo, 100)
    with np.errstate(invalid="ignore", divide="ignore"):
        vt = np.where(np.isfinite(vd) & (vd > 0), _tanh(vo / np.where(vd > 0, vd, 1.0)), 0.0)
    pc = np.where(np.isfinite(lag(c, 1)), lag(c, 1), c)
    bp = c - np.minimum(l, pc)
    tr = np.maximum(h, pc) - np.minimum(l, pc)

    def ssum(x, n):
        return pd.Series(x).rolling(n, min_periods=n).sum().to_numpy()

    def part(n):
        s = ssum(tr, n)
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.where(s > 0, ssum(bp, n) / np.where(s > 0, s, 1.0), 0.5)
    er = _tsi(c, 5, 20)
    poc = _poc(h, l, c, vol)
    with np.errstate(invalid="ignore", divide="ignore"):
        dpoc = np.where(np.isfinite(poc) & (at > 0), (c - poc) / np.where(at > 0, at, 1.0), 0.0)
        vm = M.sma(vol, 20)
        sv = np.where(c >= o, 1.0, -1.0) * np.where(vm > 0, vol / np.where(vm > 0, vm, 1.0), 0.0)
    return {"bb": pb, "rsi": _nz(M.rsi(c, 14), 50.0) - 50.0, "mfi": _nz(_mfi((h + l + c) / 3.0, vol, 14), 50.0) - 50.0,
            "wpr": _nz(wpr, -50.0) + 50.0, "mom": _nz(M.mom(c, 10)),
            "vo": M.ema(_nz(np.maximum(vt, 0.0) * np.sign(_nz(c - lag(c, 5)))), 3),
            "uo": 100.0 * (4.0 * part(7) + 2.0 * part(14) + part(28)) / 7.0 - 50.0, "ao": _nz(ao),
            "ac": _nz(ao - M.sma(ao, 5)), "smio": _nz(er - M.ema(er, 5)), "poc": dpoc, "vsma": M.ema(sv, 3),
            "smma": c - M.rma(c, 21), "ma52": c - M.sma(c, 52), "macd": _nz(M.ema(c, 12) - M.ema(c, 26))}


def q15_line(o, h, l, c, v) -> np.ndarray:
    """'15종 MACD''s line (its defaults, all fifteen on) per bar: the mean of the fifteen qz(input) (⑥ as it is) x 100
    through EMA 3."""
    P = q15_parts(o, h, l, c, v)
    qs = [P[k] if k == "vo" else _qz(P[k]) for k in Q15_KEYS]
    return M.ema(100.0 * sum(qs) / 15.0, 3)


def h3_pane(o, h, l, c, v) -> dict:
    """'3개 합친 평균 히스토그램' (3합 히스토그램, its defaults) per bar: ① WOOX pro2 = 'ALL + OBV6 MACD''s line (part 9),
    ② 레인지봇 = 2 (EMA RSI - 50), ③ 15종 MACD's line; their mean, its EMA 9 the signal, the histogram = mean - signal;
    "cross" +1 / -1 where it crossed above / below 0 on that bar. Owners 11-02 (WOO X Pro 1 · 2: "30분봉 추세 macd가 0선 위에
    있으면 상승 추세로 보고 15분봉 3합 히스토 그램이 0선을 상향 돌파 하면 롱진입 숏 진입은 반대 조건")."""
    h, l, c = (np.asarray(a, float) for a in (h, l, c))
    w = h6_pane(h, l, c, v)["macd"]
    r = 2.0 * (ema_rsi(c) - 50.0)
    q = q15_line(o, h, l, c, v)
    avg = (w + r + q) / 3.0
    sig = M.ema(avg, H3_SIG)
    hist = avg - sig
    return {"avg": avg, "sig": sig, "hist": hist, "cross": _cross0(hist), "w": w, "r": r, "q": q}


def h3_state(o, h, l, c, v) -> dict:
    """On the last bar: {"cross", "hist", "avg"}."""
    P = h3_pane(o, h, l, c, v)
    if not len(P["hist"]):
        return {"cross": 0, "hist": None, "avg": None}
    hv, av = float(P["hist"][-1]), float(P["avg"][-1])
    return {"cross": int(P["cross"][-1]), "hist": round(hv, 4) if math.isfinite(hv) else None,
            "avg": round(av, 3) if math.isfinite(av) else None}


# ====================================================================== 3. the Stoch RSI pane
def stoch_pane(c) -> dict:
    """The Stoch RSI pane of '차트 믹스 + 스톡 RSI' (14 · 11 · 4 · 6, noise 보통, gap 2): {"k", "d", "xs", "gold", "dead"}."""
    c = np.asarray(c, float)
    rl, sl, kl, dl = STOCH
    rx = M.rsi(c, rl)
    lo, hi = lowest(rx, sl), highest(rx, sl)
    with np.errstate(invalid="ignore", divide="ignore"):
        st = np.where(hi - lo != 0, 100.0 * (rx - lo) / (hi - lo), np.nan)   # x / 0 is na in Pine
    kr = _nz(M.sma(st, kl), 50.0)
    k = M.ema(kr, STOCH_SMOOTH)
    d = _nz(M.sma(k, dl), 50.0)
    n = len(c)
    xs = np.zeros(n, np.int8)
    state = 0
    for i in range(n):
        if math.isfinite(k[i]):
            if k[i] - d[i] > STOCH_GAP:
                state = 1
            elif d[i] - k[i] > STOCH_GAP:
                state = -1
        xs[i] = state
    prev = np.r_[0, xs[:-1]]
    return {"k": k, "d": d, "xs": xs, "gold": (xs == 1) & (prev != 1), "dead": (xs == -1) & (prev != -1)}


def stoch_signal(c) -> dict:
    """On the last bar: {"side": +1 golden ● with K < 50 / -1 dead ● with K > 50 / 0, "cross": "gold"/"dead"/"", "k", "d",
    "xs": the pane's state (+1 K over D by the gap, -1 under, 0 before the first)}."""
    P = stoch_pane(c)
    k, d = float(P["k"][-1]), float(P["d"][-1])
    cross = "gold" if P["gold"][-1] else ("dead" if P["dead"][-1] else "")
    side = 1 if cross == "gold" and k < 50 else (-1 if cross == "dead" and k > 50 else 0)
    rnd = (lambda x: round(x, 2) if math.isfinite(x) else None)
    return {"side": side, "cross": cross, "k": rnd(k), "d": rnd(d), "xs": int(P["xs"][-1])}
