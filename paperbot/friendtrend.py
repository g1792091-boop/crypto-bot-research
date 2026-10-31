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
