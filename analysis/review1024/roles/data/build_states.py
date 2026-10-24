"""Higher-timeframe trend STATES per coin on 1h, 4h and 1d bars of the extended grid (one value per closed bar):

  j_V39 j_S6 j_OBV j_N12   the live trend bot's four judges (paperbot/trendjudge.vote_arrays, called as is)
  j_raw3                   +1 / -1 when 3 of the 4 agree, else 0 (trendjudge.raw_votes(arr, 3))
  j_dir                    j_raw3 held on the last `hold` closed bars (1h: 2, 4h: 1, 1d: 1 = TrendRules defaults), else 0
  j_adx j_ema20 j_atr j_close   ADX(14, 14), EMA20, ATR14, close of the bar (for the strength / 끝물 / spot checks)
  c_<source>               the CONDITION state of every trend source of the role map (roles.json trend_incl_dual, 52):
                           +1 / -1 / 0 from the indicator the strategy's own code reads, with its own numbers
                           (definitions in STATE_KO below and in MANIFEST_KO.md); 0 = neither side or not computable
  l_<source>               the LATCH state: the side of that strategy's most recent own signal on this timeframe, held
                           until the opposite signal (0 before the first); from OUT/signals/<coin>.npz (1h, 4h: all 52;
                           1d: the core and library sources only -- DeepSeek and FRIEND_ROC are not defined on 1d)
  ts, nb                   bar open (ms) and bar number of the coin (0 = first whole bar: warm-up filter)

A signal at bar close t reads the bar with the largest close <= t (common.last_closed): a higher bar that closed at the
same minute counts (the live bot reads it ~8-20 s after the close), a later one never does.

Output OUT/states/<coin>_<htf>.npz.    python3 build_states.py [procs]"""
from common import *

STATE_KO = {
    "S1_EMA_RSI_CHOP": "EMA5 > EMA20 그리고 초피존(34, 1, 5, 14) > 0 / 반대",
    "S2_ST_ROC": "슈퍼트렌드(10, 6) 방향 그리고 ROC9 부호 같음",
    "S5_DONCHIAN_MFI": "래치: 종가가 직전 20봉 고가 위로 → +1, 직전 20봉 저가 아래로 → -1 (돈치안 돌파 방향)",
    "S6_EMA_DMI_ADX": "종가 > EMA20 그리고 +DI > -DI (추세판단 봇 S6과 같음)",
    "N01_ST_EMA": "슈퍼트렌드(10, 6) 방향 그리고 EMA5 vs EMA20 같은 쪽",
    "N02_ST_KST": "슈퍼트렌드(10, 6) 방향 그리고 KST vs 신호선 같은 쪽",
    "N03_ADX_GC": "EMA50 vs EMA200 방향, ADX ≥ 25일 때만 (아니면 0)",
    "N04_ST_KLINGER": "슈퍼트렌드(10, 6) 방향 그리고 클링거(34, 55, 13) vs 신호선 같은 쪽",
    "N07_ICHI_CMO": "전환선 vs 기준선, 구름 색(선행A vs 선행B), CMO14 부호 모두 같은 쪽",
    "N08_ICHI_WR": "전환선 vs 기준선 그리고 구름 색 같은 쪽",
    "N09_ALLIG_AROON": "SMA5가 SMA8·SMA13 둘 다 위(아래) 그리고 아룬(25) 위 ≥ 아래(아래 ≥ 위)",
    "N10_HA_PSAR": "하이킨아시 색 그리고 종가 vs PSAR(0.02, 0.02, 0.2) 같은 쪽",
    "N12_ICHI_AO": "종가가 구름 전체 위(아래) 그리고 AO(5, 34) > 0 (< 0) (추세판단 봇 N12와 같음)",
    "N18_VWMA_MACD": "MACD(12, 26) 선 부호 그리고 종가 vs VWMA20 같은 쪽",
    "N22_VORTEX_PSAR": "+VI vs -VI(14) 그리고 종가 vs PSAR 같은 쪽",
    "N23_HA_ST": "슈퍼트렌드(10, 6) 방향 그리고 하이킨아시 색 같은 쪽",
    "N24_DMI": "+DI vs -DI(14) 부호",
    "V39_ALL": "슈퍼트렌드(10, 3) 방향 (pi.exchange_supertrend, 추세판단 봇 V39와 같음)",
    "OBV_S": "OBV vs OBV 30봉 평균 (추세판단 봇 OBV와 같음)",
    "F3_HHHL": "확인된 스윙(3) 저점·고점이 둘 다 직전보다 높음 → +1, 둘 다 낮음 → -1",
    "F4_FAN": "EMA 8 > 13 > 21 > 34 > 55 정배열 → +1, 역배열 → -1",
    "F6_VWAP_CROSS": "종가 vs 그날(UTC) VWAP (1h·4h만; 1d는 정의 안 됨 = 0)",
    "F7_RF_TRIPLE": "레인지 필터(100, 3) 방향, 하이킨아시 색, 한 단계 위 봉(1h→4h, 4h→1d) 하이킨아시 색 모두 같은 쪽 (1d는 위 봉 없이 둘만)",
    "F7_RF_ONLY": "레인지 필터(100, 3) 방향",
    "F15_OPEN0930": "그날(뉴욕 시간) 09:30이 든 봉의 시가 대비 종가 위/아래, 그 봉부터 그날 끝까지 (1h·4h만)",
    "F15_OPEN0000": "그날(뉴욕 시간) 00:00이 든 봉의 시가 대비 종가 위/아래, 그 봉부터 그날 끝까지 (1h·4h만)",
    "T1_EMA9_21": "EMA9 vs EMA21", "T1_EMA20_50": "EMA20 vs EMA50", "T1_EMA50_200": "EMA50 vs EMA200",
    "T2_SMA10_30": "SMA10 vs SMA30", "T2_SMA50_200": "SMA50 vs SMA200",
    "T3_MACD12_26_9": "MACD(12, 26) vs 신호선(9)", "T3_MACD8_21_5": "MACD(8, 21) vs 신호선(5)",
    "T4_MACDHIST0": "MACD(12, 26, 9) 히스토그램 부호",
    "T5_ST10_2": "슈퍼트렌드(10, 2) 방향", "T5_ST10_3": "슈퍼트렌드(10, 3) 방향", "T5_ST14_4": "슈퍼트렌드(14, 4) 방향",
    "T6_DON20": "래치: 종가가 직전 20봉 고가 위로 → +1, 저가 아래로 → -1",
    "T6_DON55": "래치: 종가가 직전 55봉 고가 위로 → +1, 저가 아래로 → -1",
    "T8_PSAR": "PSAR 방향", "T9_DMI14_ADX25": "+DI vs -DI, ADX > 25일 때만 (아니면 0)",
    "T10_ICHI_TK": "전환선 vs 기준선", "T11_AROON25": "아룬(25) 위 vs 아래", "T12_HMA21": "HMA21 기울기 부호",
    "T12_HMA55": "HMA55 기울기 부호", "O2_RSI14_X50": "RSI14 vs 50", "O8_ROC9": "ROC9 부호", "O8_ROC21": "ROC21 부호",
    "O9_CMO14": "CMO14 부호", "VO1_OBV_X_MA20": "OBV vs OBV 20봉 평균",
    "C4_THREE_SAME": "래치: 마지막 '같은 색 3봉 연속'의 방향",
    "FRIEND_ROC": "EMA21 > EMA52 그리고 RSI26 > 50 → +1, 둘 다 반대 → -1",
}
HOLD = {"1h": 2, "4h": 1, "1d": 1}
NEXT_HTF = {"1h": "4h", "4h": "1d", "1d": None}


def sgn(up, dn):
    up = np.nan_to_num(np.asarray(up, float)) != 0
    dn = np.nan_to_num(np.asarray(dn, float)) != 0
    return np.where(up & ~dn, 1, np.where(dn & ~up, -1, 0)).astype(np.int8)


def sign_of(x):
    x = np.asarray(x, float)
    with np.errstate(invalid="ignore"):
        return sgn(x > 0, x < 0)


def latch_of(up, dn):
    """+1 / -1 held from the last up / down event (0 before the first)."""
    ev = sgn(up, dn).astype(float)
    ev[ev == 0] = np.nan
    return np.nan_to_num(pd.Series(ev).ffill().to_numpy(), nan=0).astype(np.int8)


def _fast():
    libs()
    try:
        import fg_fast
    except ImportError:
        sys.path.insert(0, os.path.join(REPO, "third_party", "sweep", "harness", "vendor"))
        import fg_fast
    return fg_fast


def judge_arrays(df, htf):
    E = libs()
    TJ = E["TJ"]
    arr = TJ.vote_arrays(df, E["fg"], E["pi"])
    raw = TJ.raw_votes(arr, 3).astype(np.int8)
    h = HOLD[htf]
    d = raw.copy()
    for k in range(1, h):
        prev = np.r_[np.zeros(k, np.int8), raw[:-k]]
        d = np.where(prev == raw, d, 0).astype(np.int8)
    out = {f"j_{k}": np.asarray(arr[k], np.int8) for k in TJ.JUDGES}
    out.update(j_raw3=raw, j_dir=d)
    for k, src in (("adx", "adx"), ("ema20", "ema20"), ("atr", "atr"), ("close", "close")):
        out[f"j_{k}"] = np.asarray(arr[src], float)
    return out


def ha_color(df):
    """Heikin-Ashi colour as lib_c.heikin_bull: 1 up, 0 down, 0.5 flat -> +1 / -1 / 0."""
    from ds_defs import C
    b = C.heikin_bull(df.open.to_numpy(float), df.high.to_numpy(float), df.low.to_numpy(float), df.close.to_numpy(float))
    return np.where(b == 1.0, 1, np.where(b == 0.0, -1, 0)).astype(np.int8)


def open_bias(df, tref):
    """F15_OPEN state: sign(close - open of the bar containing ET wall time tref) from that bar to the ET day's end."""
    from ds_defs import C
    ts = pd.to_datetime(df.ts.to_numpy(np.int64), unit="ms").to_numpy().astype("datetime64[ns]")
    day, mins = C.et_wall(ts)
    tfm = int((df.ts.iloc[1] - df.ts.iloc[0]) // MIN)
    o, c = df.open.to_numpy(float), df.close.to_numpy(float)
    out = np.zeros(len(df), np.int8)
    for d, a, b in C._blocks(day):
        m = mins[a:b]
        r = np.flatnonzero((m <= tref) & (tref < m + tfm))
        if not len(r):
            continue
        r0 = a + int(r[0])
        out[r0:b] = sign_of(c[r0:b] - o[r0])
    return out


def cond_states(df, htf, nxt):
    """{source: int8 state per bar} on the bar frame df (ts ms, ohlcv); nxt = the next higher frame (F7_RF_TRIPLE)."""
    E = libs()
    fg, pi = E["fg"], E["pi"]
    ff = _fast()
    import ds_defs as D
    ch = as_chart(df, htf)
    o, h, l, c, v = (df[k].to_numpy(float) for k in ("open", "high", "low", "close", "volume"))
    cs = df["close"].astype(float).reset_index(drop=True)
    S = {}
    with np.errstate(invalid="ignore", divide="ignore"):
        e5, e20 = fg.ema(cs, 5).to_numpy(float), fg.ema(cs, 20).to_numpy(float)
        st6 = np.asarray(ff.supertrend(ch, 10, 6.0)[1], float)
        _cz = np.asarray(fg.chop_zone_proxy(ch, 34, 1.0, 5.0, 14)[1], float)
        S["S1_EMA_RSI_CHOP"] = sgn((e5 > e20) & (_cz > 0), (e5 < e20) & (_cz < 0))
        r9 = fg.roc(cs, 9).to_numpy(float)
        S["S2_ST_ROC"] = sgn((st6 > 0) & (r9 > 0), (st6 < 0) & (r9 < 0))
        up20, _m, lo20 = fg.donchian_channel(ch, 20, shift_previous=True)
        S["S5_DONCHIAN_MFI"] = latch_of(c > up20.to_numpy(float), c < lo20.to_numpy(float))
        plus, minus, adx = (np.asarray(x, float) for x in fg.dmi_adx(ch, 14, 14))
        S["S6_EMA_DMI_ADX"] = sgn((c > e20) & (plus > minus), (c < e20) & (minus > plus))
        S["N01_ST_EMA"] = sgn((st6 > 0) & (e5 > e20), (st6 < 0) & (e5 < e20))
        kl, ks = (np.asarray(x, float) for x in fg.kst(cs, (10, 15, 20, 30), (10, 10, 10, 15), 9))
        S["N02_ST_KST"] = sgn((st6 > 0) & (kl > ks), (st6 < 0) & (kl < ks))
        e50, e200 = fg.ema(cs, 50).to_numpy(float), fg.ema(cs, 200).to_numpy(float)
        S["N03_ADX_GC"] = sgn((e50 > e200) & (adx >= 25), (e50 < e200) & (adx >= 25))
        k1, k2 = (np.asarray(x, float) for x in fg.klinger_oscillator(ch, 34, 55, 13))
        S["N04_ST_KLINGER"] = sgn((st6 > 0) & (k1 > k2), (st6 < 0) & (k1 < k2))
        ten, kij, sa, sb = (np.asarray(x, float) for x in fg.ichimoku(ch, 9, 26, 52, 26))
        cmo = fg.cmo(cs, 14).to_numpy(float)
        S["N07_ICHI_CMO"] = sgn((ten > kij) & (sa > sb) & (cmo > 0), (ten < kij) & (sa < sb) & (cmo < 0))
        S["N08_ICHI_WR"] = sgn((ten > kij) & (sa > sb), (ten < kij) & (sa < sb))
        lips, teeth, jaw = (fg.sma(cs, k).to_numpy(float) for k in (5, 8, 13))
        au, ad = (np.asarray(x, float) for x in ff.aroon(ch, 25))
        S["N09_ALLIG_AROON"] = sgn((lips > teeth) & (lips > jaw) & (au - ad >= 0), (lips < teeth) & (lips < jaw) & (ad - au >= 0))
        ha = ff.heikin_ashi(ch)
        hc, ho = ha["ha_close"].to_numpy(float), ha["ha_open"].to_numpy(float)
        psar = np.asarray(ff.parabolic_sar(ch, 0.02, 0.02, 0.2)[0], float)
        S["N10_HA_PSAR"] = sgn((hc > ho) & (c > psar), (hc < ho) & (c < psar))
        top, bot = np.fmax(sa, sb), np.fmin(sa, sb)
        ao = np.asarray(fg.awesome_oscillator(ch, 5, 34), float)
        S["N12_ICHI_AO"] = sgn((c > top) & (ao > 0), (c < bot) & (ao < 0))
        vw = np.asarray(fg.vwma(ch, 20), float)
        ml = np.asarray(fg.macd(cs, 12, 26, 9)[0], float)
        S["N18_VWMA_MACD"] = sgn((ml > 0) & (c > vw), (ml < 0) & (c < vw))
        vp, vm = (np.asarray(x, float) for x in fg.vortex_indicator(ch, 14))
        S["N22_VORTEX_PSAR"] = sgn((vp > vm) & (c > psar), (vp < vm) & (c < psar))
        S["N23_HA_ST"] = sgn((st6 > 0) & (hc > ho), ~(st6 > 0) & (hc < ho))
        _adl, pl2, mi2 = (np.asarray(x, float) for x in fg.adx_dmi(ch, 14))
        S["N24_DMI"] = sgn(pl2 > mi2, mi2 > pl2)
        _line, d3 = pi.exchange_supertrend(h, l, c, 10, 3.0)
        S["V39_ALL"] = sgn(np.asarray(d3) == 1, np.asarray(d3) == -1)
        ob = np.asarray(pi.obv(c, v), float)
        S["OBV_S"] = sign_of(ob - np.asarray(pi.pine_sma(ob, 30), float))
        St = D.structure(o, h, l, c, 3)
        S["F3_HHHL"] = sgn((St["lo"] > St["prev_lo"]) & (St["hi"] > St["prev_hi"]),
                           (St["hi"] < St["prev_hi"]) & (St["lo"] < St["prev_lo"]))
        fan = [pi.pine_ema(c, k) for k in (8, 13, 21, 34, 55)]
        fu = np.logical_and.reduce([a > b for a, b in zip(fan[:-1], fan[1:])])
        fd = np.logical_and.reduce([a < b for a, b in zip(fan[:-1], fan[1:])])
        S["F4_FAN"] = sgn(fu, fd)
        if htf != "1d":
            ts = pd.to_datetime(df.ts.to_numpy(np.int64), unit="ms").to_numpy().astype("datetime64[ns]")
            vwap, _day = D.C.daily_vwap(ts, h, l, c, v)
            S["F6_VWAP_CROSS"] = sign_of(c - vwap)
            S["F15_OPEN0930"] = open_bias(df, 9 * 60 + 30)
            S["F15_OPEN0000"] = open_bias(df, 0)
        else:
            for k in ("F6_VWAP_CROSS", "F15_OPEN0930", "F15_OPEN0000"):
                S[k] = np.zeros(len(df), np.int8)
        rf = D.range_filter_dir(c, 100, 3.0)
        S["F7_RF_ONLY"] = sign_of(rf)
        hac = ha_color(df)
        if nxt is not None:
            nh, ndf = nxt
            hn = ha_color(ndf)
            j = last_closed(close_ms(ndf, nh), close_ms(df, htf))
            hnx = np.where(j >= 0, hn[np.maximum(j, 0)], 0)
        else:
            hnx = hac
        S["F7_RF_TRIPLE"] = sgn((rf == 1) & (hac == 1) & (hnx == 1), (rf == -1) & (hac == -1) & (hnx == -1))
        for f, s_ in ((9, 21), (20, 50), (50, 200)):
            S[f"T1_EMA{f}_{s_}"] = sign_of(pi.pine_ema(c, f) - pi.pine_ema(c, s_))
        for f, s_ in ((10, 30), (50, 200)):
            S[f"T2_SMA{f}_{s_}"] = sign_of(pi.pine_sma(c, f) - pi.pine_sma(c, s_))
        for f, s_, g_ in ((12, 26, 9), (8, 21, 5)):
            m_, sg_, hist = pi.pine_macd(c, f, s_, g_)
            S[f"T3_MACD{f}_{s_}_{g_}"] = sign_of(np.asarray(m_, float) - np.asarray(sg_, float))
        S["T4_MACDHIST0"] = sign_of(pi.pine_macd(c, 12, 26, 9)[2])
        for n_, mult in ((10, 2.0), (10, 3.0), (14, 4.0)):
            _l, d_ = pi.exchange_supertrend(h, l, c, n_, mult)
            S[f"T5_ST{n_}_{mult:g}"] = sgn(np.asarray(d_) == 1, np.asarray(d_) == -1)
        for n_ in (20, 55):
            hh, ll = pi.shift1(pi.pine_highest(h, n_)), pi.shift1(pi.pine_lowest(l, n_))
            S[f"T6_DON{n_}"] = latch_of(c > hh, c < ll)
        _sar, sd = fg.parabolic_sar(ch)
        S["T8_PSAR"] = sign_of(np.asarray(sd, float))
        S["T9_DMI14_ADX25"] = sgn((plus > minus) & (adx > 25), (minus > plus) & (adx > 25))
        t2, k2_, _a, _b = (np.asarray(x, float) for x in fg.ichimoku(ch))
        S["T10_ICHI_TK"] = sign_of(t2 - k2_)
        au2, ad2 = (np.asarray(x, float) for x in fg.aroon(ch, 25))
        S["T11_AROON25"] = sign_of(au2 - ad2)
        lib = E["lib"]
        for n_ in (21, 55):
            hm = lib._hma(cs, n_).to_numpy(float)
            S[f"T12_HMA{n_}"] = sign_of(np.r_[np.nan, np.diff(hm)])
        S["O2_RSI14_X50"] = sign_of(pi.pine_rsi(c, 14) - 50.0)
        for n_ in (9, 21):
            S[f"O8_ROC{n_}"] = sign_of(fg.roc(cs, n_).to_numpy(float))
        S["O9_CMO14"] = sign_of(cmo)
        obl = np.asarray(pi.obv(c, v), float)
        S["VO1_OBV_X_MA20"] = sign_of(obl - np.asarray(pi.pine_sma(obl, 20), float))
        up3 = pd.Series(c > o).rolling(3).sum().to_numpy() == 3
        dn3 = pd.Series(c < o).rolling(3).sum().to_numpy() == 3
        S["C4_THREE_SAME"] = latch_of(up3, dn3)
        e21, e52 = fg.ema(cs, 21).to_numpy(float), fg.ema(cs, 52).to_numpy(float)
        r26 = fg.rsi(cs, 26).to_numpy(float)
        S["FRIEND_ROC"] = sgn((e21 > e52) & (r26 > 50), (e21 < e52) & (r26 < 50))
    return S


def latch_states(coin, htf, df, names):
    """{source: latch} from the strategy's own signals on htf (OUT/signals/<coin>.npz bitmaps)."""
    T = pd.read_csv(os.path.join(OUT, "signals", "names.csv"))
    sid = dict(zip(T.name, T.sid))
    sset = dict(zip(T.name, T.set))
    z = np.load(os.path.join(OUT, "signals", f"{coin}.npz"))
    n = int(z[f"{htf}_n"])
    e0 = int(z[f"{htf}_e0"])
    assert n == len(df) and e0 == (close_ms(df, htf)[0] - T0) // MIN, (coin, htf, n, len(df))
    out = {}
    for name in names:
        kl, ks = f"{htf}_{sid[name]}_L", f"{htf}_{sid[name]}_S"
        if kl not in z.files:
            if htf == "1d" and sset[name] in ("ds", "friend"):
                continue                       # not defined on 1d: no latch state
            out[name] = np.zeros(n, np.int8)
            continue
        lg = np.unpackbits(z[kl])[:n].astype(bool)
        sh = np.unpackbits(z[ks])[:n].astype(bool)
        out[name] = latch_of(lg, sh)
    return out


def work(coin):
    t0 = time.time()
    B = {htf: bars(coin, htf) for htf in HTFS}
    drop(coin)
    names = roles()["roles"]["trend_incl_dual"]
    assert set(names) <= set(STATE_KO), set(names) - set(STATE_KO)
    for htf in HTFS:
        df = B[htf]
        nx = NEXT_HTF[htf]
        out = {"ts": df.ts.to_numpy(np.int64), "nb": np.arange(len(df), dtype=np.int32)}
        out.update(judge_arrays(df, htf))
        S = cond_states(df, htf, None if nx is None else (nx, B[nx]))
        missing = set(names) - set(S)
        assert not missing, missing
        for k in names:
            out[f"c_{k}"] = S[k]
        for k, v in latch_states(coin, htf, df, names).items():
            out[f"l_{k}"] = v
        save_npz(os.path.join(OUT, "states", f"{coin}_{htf}.npz"), **out)
        log(coin, htf, len(df), "bars", f"{time.time() - t0:.0f}s")
    return coin


if __name__ == "__main__":
    from multiprocessing import get_context
    os.makedirs(os.path.join(OUT, "states"), exist_ok=True)
    procs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    with get_context("fork").Pool(procs) as pool:
        for c in pool.imap_unordered(work, COINS):
            log("done", c)
    json.dump(STATE_KO, open(os.path.join(OUT, "states", "state_defs_ko.json"), "w"), ensure_ascii=False, indent=1)
