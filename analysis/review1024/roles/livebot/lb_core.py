"""추세판단 봇 재현 (livebot part of analysis/review1024/roles). Run from this folder without -I (pandas):

    python3 lb_core.py selftest

Everything is read-only over the shared data layer (../data, files under common.OUT). The trend bot's rules come from
paperbot/trendjudge.py, paperbot/trendbot.py, paperbot/combo.py and deploy/combo.trend.json (read, not imported, except
the indicator functions the data layer already vendors). Plan: PLAN.md (hashed before any variant result)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "data"))
import rolesdata as RD            # noqa: E402
from common import *              # noqa: E402,F401,F403
import numba                      # noqa: E402

LB = os.path.dirname(os.path.abspath(__file__))   # this folder (common.HERE is the data folder)

# ---------------------------------------------------------------- the bot's numbers (deploy/combo.trend.json, 10-22)
MEMBERS18 = [("N06_MACD_ORB", "30m"), ("S3_CMO_SANDWICH", "30m"), ("N05_PSAR_POC", "30m"), ("F16_FIB382", "30m"),
             ("V39_ALL", "1h"), ("F9_IFVG", "1h"), ("F16_FIB382", "1h"), ("F16_FIB500", "1h"), ("F6_VWAP_FAIL", "1h"),
             ("F3_BOS", "1h"), ("F15_ORB", "1h"), ("F15_ORB", "4h"), ("F10_OTE", "4h"), ("F16_FIB618", "4h"),
             ("F16_FIB764", "4h"), ("F9_IFVG", "4h"), ("F9_OB", "4h"), ("F7_RF_TRIPLE", "4h")]
BREAKOUT = ("F3_BOS", "F15_ORB", "N06_MACD_ORB")
HTF_OF = {"30m": "1h", "1h": "4h", "4h": "1d"}
HTF_UP = {"30m": "4h", "1h": "1d", "4h": "1d"}
HOLD = {"1h": 2, "4h": 1, "1d": 1}
LADDER2 = (0.10, 0.01, 0.05, 0.15, 0.03)          # first_lock, trigger_gap, step, next_trigger, next_gap
ROE_STOP = -0.50
MARGIN = 0.40
HOUR_MS = 3_600_000
P_SEL = (ms("2020-03-01"), ms("2024-01-01"))
P_CON = (ms("2024-01-01"), ms("2025-07-01"))
P_LATE = (ms("2025-07-01"), FWD[0])
P_FWD = FWD
P_OOS = (ms("2026-10-22 15:00"), FWD[1])         # the 10-22 design's own live period (10-23 00:00 KST on)
PERIODS4 = {"select": P_SEL, "confirm": P_CON, "late": P_LATE, "fwd": P_FWD}


def lev_of(coin):
    return np.where(np.asarray(coin) == 0, 40.0, 30.0)


def period_name(t):
    t = np.asarray(t, np.int64)
    out = np.full(len(t), "", dtype=object)
    for k, (a, b) in PERIODS4.items():
        out[(t >= a) & (t < b)] = k
    return out


# ---------------------------------------------------------------- the exit walk (paper engine rules)
@numba.njit(cache=True)
def _lock(best, fl, gap, step, nt, ng):
    ft = fl + gap
    if not best >= ft - 1e-12:
        return np.nan
    if nt <= 0.0:                                   # form 1 (paperbot/ladder.py)
        return fl + step * np.floor((best - ft) / step + 1e-9)
    if not best >= nt - 1e-12:                      # form 2 (paperbot/ladder2.py): +11 -> 10, +15 -> 12, +20 -> 17 ...
        return fl
    return nt - ng + step * np.floor((best - nt) / step + 1e-9)


@numba.njit(cache=True)
def walk(o, h, l, c, cumf, es, ss, levs, force, cost, fl, gap, step, nt, ng, roe_stop, n):
    """frdeep.walk3's order of checks (stop before lock arming, a lock armed from the next minute, stop fill at the level
    or the open if gapped through) with the two-part ladder and one forced exit minute per trade (force[q] >= 0): at the
    open of that minute, only before the first lock (the supervisor JUDGE exit / the own-reverse REV exit).
    why: 0 stop, 1 lock, 2 forced, 3 open at the data end."""
    m = len(es)
    ret = np.zeros(m)
    kk = np.zeros(m, np.int64)
    why = np.zeros(m, np.int8)
    for q in range(m):
        e = es[q]
        s = ss[q]
        lev = levs[q]
        fm = force[q]
        p0 = o[e]
        f0 = cumf[e - 1]
        best = -1e9
        lk = np.nan
        k = 0
        while True:
            i = e + k
            if i >= n:
                i = n - 1
                ret[q] = s * (c[i] / p0 - 1.0) - cost - s * (cumf[i] - f0)
                kk[q] = i - e
                why[q] = 3
                break
            Fp = s * (cumf[i - 1] - f0)
            F = s * (cumf[i] - f0)
            locked = not np.isnan(lk)
            op = s * (o[i] / p0 - 1.0)
            if k > 0 and (not locked) and fm >= 0 and i >= fm:
                ret[q] = op - cost - F
                kk[q] = k
                why[q] = 2
                break
            level = roe_stop / lev + cost + Fp
            rs = 0
            if locked:
                lv = lk / lev + cost + Fp
                if lv > level:
                    level = lv
                    rs = 1
            if s > 0:
                up = h[i] / p0 - 1.0
                dn = l[i] / p0 - 1.0
            else:
                up = 1.0 - l[i] / p0
                dn = 1.0 - h[i] / p0
            if dn <= level:
                fill = level if level < op else op
                ret[q] = fill - cost - F
                kk[q] = k
                why[q] = rs
                break
            r_up = lev * (up - cost - F)
            if r_up > best:
                best = r_up
                lk = _lock(best, fl, gap, step, nt, ng)
            k += 1
        if ret[q] < -1.0 / lev:
            ret[q] = -1.0 / lev
    return ret, kk, why


def run_walk(D, force_col="force", opp=False, ladder=LADDER2, payback=False):
    """r, k, why per row of D (coin, e, side, force); opp=True walks the opposite side with the same forced minute."""
    r = np.full(len(D), np.nan)
    k = np.full(len(D), -1, np.int64)
    w = np.full(len(D), -1, np.int8)
    fl, gap, step, nt, ng = ladder
    for ci, coin in enumerate(COINS):
        m = (D.coin.to_numpy() == ci)
        if not m.any():
            continue
        g = grid(coin)
        cumf = np.cumsum(g["fund"])
        o, h, l, c = (np.ascontiguousarray(g[x], dtype=np.float64) for x in ("o", "h", "l", "c"))
        es = D.e.to_numpy(np.int64)[m]
        ss = D.side.to_numpy(np.int64)[m] * (-1 if opp else 1)
        lv = lev_of(np.full(m.sum(), ci))
        fo = D[force_col].to_numpy(np.int64)[m] if force_col else np.full(m.sum(), -1, np.int64)
        a = walk(o, h, l, c, cumf, es, ss.astype(np.int64), lv, fo, COST, fl, gap, step, nt, ng, ROE_STOP, g["n"])
        r[m], k[m], w[m] = a
    if payback:
        r = r + PAYBACK
    return r, k, w


# ---------------------------------------------------------------- the judge of each row's higher bar
def judge(S, htf_map, kind="vote3"):
    """Columns j_dir, j_raw, j_adx, j_adxp, j_ema, j_atr, j_n4 (judges on the row's side), j_htf, j_i, j_na for the last
    CLOSED higher bar (htf per row from htf_map[tf]). kind: vote3 (the bot), vote4 (4 of 4), obv (OBV alone).
    dir = raw held on the last HOLD[htf] bars (TrendRules defaults = the 10-22 config)."""
    n = len(S)
    out = {k: np.full(n, np.nan) for k in ("j_dir", "j_raw", "j_adx", "j_adxp", "j_ema", "j_atr", "j_n4", "j_i")}
    hm = S.tf.map(htf_map).to_numpy()
    side = S.side.to_numpy()
    for h in HTFS:
        mh = hm == h
        if not mh.any():
            continue
        idx = RD.htf_index(S, h)
        for ci, coin in enumerate(COINS):
            m = mh & (S.coin.to_numpy() == ci) & (idx >= 1)
            if not m.any():
                continue
            Z = RD._states(coin, h)
            ii = idx[m]
            V = np.vstack([Z[f"j_{x}"] for x in ("V39", "S6", "OBV", "N12")]).astype(int)
            if kind == "vote3":
                raw = Z["j_raw3"].astype(int)
            elif kind == "vote4":
                raw = np.where((V == 1).all(0), 1, np.where((V == -1).all(0), -1, 0))
            elif kind == "obv":
                raw = Z["j_OBV"].astype(int)
            else:
                raise ValueError(kind)
            hold = HOLD[h]
            d = raw[ii].copy()
            if hold == 2:
                d = np.where(raw[ii - 1] == raw[ii], d, 0)
            ok = Z["nb"][ii] >= 120
            out["j_dir"][m] = np.where(ok, d, np.nan)
            out["j_raw"][m] = np.where(ok, raw[ii], np.nan)
            out["j_adx"][m] = np.where(ok, Z["j_adx"][ii], np.nan)
            out["j_adxp"][m] = np.where(ok, Z["j_adx"][ii - 1], np.nan)
            out["j_ema"][m] = np.where(ok, Z["j_ema20"][ii], np.nan)
            out["j_atr"][m] = np.where(ok, Z["j_atr"][ii], np.nan)
            out["j_n4"][m] = np.where(ok, (V[:, ii] == side[m]).sum(0), np.nan)
            out["j_i"][m] = ii
    S = S.copy()
    for k_, v in out.items():
        S[k_] = v
    S["j_htf"] = hm
    return S


def judge_exit_minute(S, htf_map, kind="vote3", side_col="side"):
    """First minute after the entry at which a higher bar (htf_map[tf]) CLOSES with raw == -side (the supervisor's
    JUDGE exit at that minute's open; trendbot._before_step: j.bar_close > entry and j.raw == -want); -1 = none."""
    out = np.full(len(S), -1, np.int64)
    hm = S.tf.map(htf_map).to_numpy()
    e = S.e.to_numpy(np.int64)
    side = S[side_col].to_numpy()
    for h in HTFS:
        for ci, coin in enumerate(COINS):
            m0 = (hm == h) & (S.coin.to_numpy() == ci)
            if not m0.any():
                continue
            Z = RD._states(coin, h)
            if kind == "vote3":
                raw = Z["j_raw3"].astype(int)
            elif kind == "vote4":
                V = np.vstack([Z[f"j_{x}"] for x in ("V39", "S6", "OBV", "N12")]).astype(int)
                raw = np.where((V == 1).all(0), 1, np.where((V == -1).all(0), -1, 0))
            else:
                raw = Z["j_OBV"].astype(int)
            closem = (Z["ts"].astype(np.int64) - T0) // MIN + TF_MIN[h]
            for sd in (1, -1):
                m = m0 & (side == sd)
                if not m.any():
                    continue
                cm = closem[raw == -sd]
                j = np.searchsorted(cm, e[m], side="right")
                out[np.flatnonzero(m)] = np.where(j < len(cm), cm[np.minimum(j, len(cm) - 1)], -1)
    return out


def rev_exit_minute(S):
    """First minute after the entry at which the same member (name, tf, coin) signals the other side (combo early_exit
    "own": its bar close > the entry; filtered signals count too); -1 = none."""
    out = np.full(len(S), -1, np.int64)
    e = S.e.to_numpy(np.int64)
    side = S.side.to_numpy()
    for (nm, tf), G in S.groupby(["name", "tf"]):
        for ci, coin in enumerate(COINS):
            idx = G.index[G.coin.to_numpy() == ci]
            if not len(idx):
                continue
            L, Sh, e0 = RD.signal_bits(nm, tf, coin)
            if L is None:
                continue
            tfm = TF_MIN[tf]
            mL = e0 + np.flatnonzero(L).astype(np.int64) * tfm
            mS = e0 + np.flatnonzero(Sh).astype(np.int64) * tfm
            pos = S.index.get_indexer(idx)
            for sd, opp in ((1, mS), (-1, mL)):
                q = pos[side[pos] == sd]
                if not len(q) or not len(opp):
                    continue
                j = np.searchsorted(opp, e[q], side="right")
                out[q] = np.where(j < len(opp), opp[np.minimum(j, len(opp) - 1)], -1)
    return out


# ---------------------------------------------------------------- the chase block (combo.chase_check)
_HL = {}


def _hourly(coin):
    if coin not in _HL:
        g = grid(coin)
        n = g["n"] // 60 * 60
        hh = np.nanmax(np.where(np.isfinite(g["h"][:n]), g["h"][:n], np.nan).reshape(-1, 60), axis=1)
        ll = np.nanmin(g["l"][:n].reshape(-1, 60), axis=1)
        H, L = pd.Series(hh), pd.Series(ll)
        _HL[coin] = {"h24": H.rolling(24, min_periods=20).max().to_numpy(), "l24": L.rolling(24, min_periods=20).min().to_numpy(),
                     "h7": H.rolling(168, min_periods=150).max().to_numpy(), "l7": L.rolling(168, min_periods=150).min().to_numpy()}
    return _HL[coin]


def chase(S, price_col="p0"):
    """1 = a chase (no entry), 0 = not, 2 = cannot tell (fewer than 20 of the 24 hours; the bot does not enter either).
    Windows end at the last hour closed before the signal bar's close; price = the entry minute's open (~ the bot's ref)."""
    out = np.zeros(len(S), np.int8)
    t = S.t.to_numpy(np.int64)
    side = S.side.to_numpy()
    px = S[price_col].to_numpy(float)
    for ci, coin in enumerate(COINS):
        m = S.coin.to_numpy() == ci
        if not m.any():
            continue
        Hh = _hourly(coin)
        k = (t[m] - T0) // HOUR_MS - 1                  # the window's last hour
        okk = (k >= 0) & (k < len(Hh["h24"]))
        kk = np.clip(k, 0, len(Hh["h24"]) - 1)
        h24, l24, h7, l7 = (Hh[x][kk] for x in ("h24", "l24", "h7", "l7"))
        with np.errstate(invalid="ignore", divide="ignore"):
            p24 = (px[m] - l24) / np.maximum(h24 - l24, 1e-12)
            p7 = (px[m] - l7) / np.maximum(h7 - l7, 1e-12)
        sd = side[m]
        c24 = np.where(sd > 0, p24 >= 0.9, p24 <= 0.1)
        c7 = np.isfinite(p7) & np.where(sd > 0, p7 >= 0.8, p7 <= 0.2)
        v = np.where(~okk | ~np.isfinite(p24), 2, np.where(c24 | c7, 1, 0))
        out[m] = v
    return out


# ---------------------------------------------------------------- candidates of a variant
def base_signals(pairs, period=(ms("2020-03-01"), FWD[1])):
    names = sorted({p[0] for p in pairs})
    tfs = sorted({p[1] for p in pairs}, key=lambda x: TFS.index(x))
    S = RD.signals(names=names, tfs=tfs, period=period)
    key = set(pairs)
    S = S[[(a, b) in key for a, b in zip(S.name, S.tf)]].reset_index(drop=True)
    return S


def add_entry_facts(S):
    """p0 (entry minute open), spot EMA20 / ATR14 / RSI14 of the signal bar, blk, chase."""
    S = S.copy()
    p0 = np.full(len(S), np.nan)
    for ci, coin in enumerate(COINS):
        m = S.coin.to_numpy() == ci
        if m.any():
            p0[m] = grid(coin)["o"][S.e.to_numpy(np.int64)[m]]
    S["p0"] = p0
    sp = RD.spot(S)
    for k_ in ("spot_ema20", "spot_atr", "spot_rsi", "spot_close"):
        S[k_] = sp[k_]
    S = RD.add_blocks(S)
    S["chase"] = chase(S)
    return S


def checks(S):
    """Each check on its own (bool = fails): the trendjudge.check list + the combo entry blocks."""
    side = S.side.to_numpy(float)
    d = S.j_dir.to_numpy(float)
    adx, adxp = S.j_adx.to_numpy(float), S.j_adxp.to_numpy(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        fh = side * (S.p0.to_numpy(float) - S.j_ema.to_numpy(float)) / S.j_atr.to_numpy(float)
        fe = (S.p0.to_numpy(float) - S.spot_ema20.to_numpy(float)) / S.spot_atr.to_numpy(float)
    rsi = S.spot_rsi.to_numpy(float)
    na = ~np.isfinite(d) | ~np.isfinite(adx) | ~np.isfinite(adxp) | ~np.isfinite(fh) | ~np.isfinite(fe) | ~np.isfinite(rsi)
    brk = S.name.isin(BREAKOUT).to_numpy()
    C = pd.DataFrame({
        "blk": S.blk.to_numpy() != 0,
        "chase": S.chase.to_numpy() != 0,
        "na": na,
        "hold": (d == 0),
        "against": (d != 0) & np.isfinite(d) & (d != side),
        "weak": ~(adx >= 20.0),
        "tired": (adx > 40.0) & (adx < adxp),
        "breakout": brk & ~((adx < 30.0) & (adx > adxp)),
        "far_htf": fh > 1.5,
        "far_etf": np.abs(fe) > 1.5,
        "rsi": ((side > 0) & (rsi >= 70.0)) | ((side < 0) & (rsi <= 30.0)),
    }, index=S.index)
    S = S.copy()
    S["far_htf_atr"], S["far_etf_atr"] = fh, fe
    return S, C


ORDER = ("blk", "chase", "na", "hold", "against", "weak", "tired", "breakout", "far_htf", "far_etf", "rsi")


def first_reason(C, use):
    why = np.full(len(C), "", dtype=object)
    for k_ in ORDER:
        if k_ in use:
            put = (why == "") & C[k_].to_numpy()
            why[put] = k_
    return why


VARIANTS_DEF = {
    "B0": dict(members="18", hold_ok=True, extra=True, judge="vote3", htf=HTF_OF, trend_side=False, exits=True),
    "B1": dict(members="18", hold_ok=False, extra=True, judge="vote3", htf=HTF_OF, trend_side=False, exits=True),
    "B2": dict(members="17", hold_ok=False, extra=True, judge="vote3", htf=HTF_OF, trend_side=False, exits=True),
    "B3": dict(members="17", hold_ok=False, extra=False, judge="vote3", htf=HTF_OF, trend_side=False, exits=True),
    "B4": dict(members="17", hold_ok=False, extra=False, judge="vote3", htf=HTF_OF, trend_side=True, exits=True),
    "B5": dict(members="17", hold_ok=False, extra=False, judge="vote4", htf=HTF_OF, trend_side=False, exits=True),
    "B6": dict(members="17", hold_ok=False, extra=False, judge="obv", htf=HTF_OF, trend_side=False, exits=True),
    "B7": dict(members="stoch", hold_ok=False, extra=False, judge="obv", htf=HTF_OF, trend_side=False, exits=True),
    "B8": dict(members="17", hold_ok=False, extra=False, judge="vote3", htf=HTF_OF, trend_side=False, exits=False),
    "B9": dict(members="roles", hold_ok=False, extra=False, judge="vote3", htf=HTF_OF, trend_side=False, exits=True),
    "B10": dict(members="17", hold_ok=False, extra=False, judge="vote3", htf=HTF_UP, trend_side=False, exits=True),
    # extra, NOT in PLAN.md (added after the 11 results; counted as trials): the trend-wait shadow's pullback entry
    "W0": dict(members="18", hold_ok=True, extra=True, judge="vote3", htf=HTF_OF, trend_side=False, exits=True, wait=True),
    "W3": dict(members="17", hold_ok=False, extra=False, judge="vote3", htf=HTF_OF, trend_side=False, exits=True, wait=True),
}
KO_VAR = {
    "B0": "지금 10/22 설계", "B1": "+ 보류면 안 함", "B2": "+ F7_RF_TRIPLE 빼기", "B3": "+ 추가 검사 빼기(추세 방향만)",
    "B4": "+ 방향은 추세가(멤버 방향 무시)", "B5": "+ 판단 4/4", "B6": "+ 판단 OBV 하나", "B7": "OBV 추세 + 스톡RSI 타점",
    "B8": "+ 감독·빠른 청산 빼기", "W0": "B0 + 되돌림 기다림(그림자 trend-wait)", "W3": "B3 + 되돌림 기다림", "B9": "+ 진입 = 역할 지도 눌림·자리·돌파 전부", "B10": "+ 상위 봉 한 단계 더 위",
}


def member_pairs(kind):
    if kind == "18":
        return list(MEMBERS18)
    if kind == "17":
        return [p for p in MEMBERS18 if p[0] != "F7_RF_TRIPLE"]
    if kind == "stoch":
        return [("O4_STOCHRSI_ZONE", tf) for tf in ("30m", "1h", "4h")]
    if kind == "roles":
        N = RD.names()
        nm = N[N.role.isin(["pullback", "range", "breakout"])].name.tolist()
        return [(a, tf) for a in nm for tf in ("30m", "1h", "4h")]
    raise ValueError(kind)


def candidates(vname, period=(ms("2020-03-01"), FWD[1]), keep_all=False):
    """All signals of a variant's members with their judge, checks, reason, outcomes (own and opposite side, the bot's
    exits) and the score priority. keep_all=True keeps the rows that fail a check (what-if tables)."""
    V = VARIANTS_DEF[vname]
    S = base_signals(member_pairs(V["members"]), period)
    S = judge(S, V["htf"], V["judge"])
    if V["trend_side"]:
        d = S.j_dir.to_numpy(float)
        S = S[np.isfinite(d) & (d != 0)].copy()
        S["side"] = S.j_dir.astype(np.int8)
        S = S.drop_duplicates(["coin", "e", "name", "tf"]).reset_index(drop=True)
        S = judge(S, V["htf"], V["judge"])           # j_n4 on the new side
    S = add_entry_facts(S)
    S, C = checks(S)
    use = ["blk", "na", "against"] + ([] if V["hold_ok"] else ["hold"])
    if V["extra"]:
        use += ["chase", "weak", "tired", "breakout", "far_htf", "far_etf", "rsi"]
    S["why"] = first_reason(C, use)
    for k_ in ORDER:
        S[f"f_{k_}"] = C[k_].to_numpy()
    if not keep_all:
        S = S[S.why == ""].reset_index(drop=True)
    if V.get("wait"):
        S = pullback(S)
    if V["exits"]:
        jm = judge_exit_minute(S, V["htf"], V["judge"])
        rm = rev_exit_minute(S)
        f = np.where(jm < 0, rm, np.where(rm < 0, jm, np.minimum(jm, rm)))
        S["force_judge"], S["force_rev"] = jm, rm
    else:
        f = np.full(len(S), -1, np.int64)
    S["force"] = f
    r, k_, w = run_walk(S, "force")
    ro, ko, wo = run_walk(S, "force", opp=True)
    lev = lev_of(S.coin.to_numpy())
    S["tb_r"], S["tb_k"], S["tb_why"], S["tb_roe"] = r, k_, w, lev * r
    S["tb_opp_r"], S["tb_opp_k"], S["tb_opp_why"], S["tb_opp_roe"] = ro, ko, wo, lev * ro
    strength = (S.j_n4.to_numpy(float) >= 4).astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        spot = np.maximum(0.0, 1.0 - np.abs(S.p0 - S.spot_ema20) / (1.5 * S.spot_atr)).fillna(0).to_numpy()
    S["prio"] = -(strength + spot)
    S["period"] = period_name(S.t)
    return S


def taken(S, side_col=""):
    A = S[(S.tb_k >= 0)].reset_index(drop=True)
    t = RD.one_position(A, "tb", side_col=side_col, priority="prio")
    return A[t].reset_index(drop=True)


# ---------------------------------------------------------------- the pullback wait (trend-wait shadow; NOT in PLAN.md)
@numba.njit(cache=True)
def _touch(l, h, es, ss, lv, last):
    """First minute i in (e, last] whose low (long) / high (short) reaches lv; -1 = none (trendbot._pullbacks)."""
    out = np.full(len(es), -1, np.int64)
    for q in range(len(es)):
        for i in range(es[q] + 1, last[q] + 1):
            if (ss[q] > 0 and l[i] <= lv[q]) or (ss[q] < 0 and h[i] >= lv[q]):
                out[q] = i
                break
    return out


def pullback(S, k=0.25, k_big=0.5, big_bar=2.0):
    """The trend-wait shadow's entry: wait from the signal minute + 1 to the entry bar's second-to-last minute for the
    price to come back k (k_big after a signal bar longer than big_bar ATR) entry-bar ATR from the reference price (p0);
    the entry is the next minute's open. Rows without a touch are dropped. Returns S with e / p0 moved (e_sig kept)."""
    S = S.copy()
    rng = np.full(len(S), np.nan)
    for ci, coin in enumerate(COINS):
        for tf in TFS:
            m = (S.coin.to_numpy() == ci) & (S.tf.to_numpy() == tf)
            if not m.any():
                continue
            df = bars(coin, tf)
            bc = close_ms(df, tf)
            i = np.clip(np.searchsorted(bc, S.t.to_numpy(np.int64)[m]), 0, len(bc) - 1)
            ok = bc[i] == S.t.to_numpy(np.int64)[m]
            rng[m] = np.where(ok, (df.high.to_numpy() - df.low.to_numpy())[i], np.nan)
    kk = np.where(rng > big_bar * S.spot_atr.to_numpy(), k_big, k)
    lvl = S.p0.to_numpy() - S.side.to_numpy() * kk * S.spot_atr.to_numpy()
    last = S.e.to_numpy(np.int64) + S.tf.map(TF_MIN).to_numpy(np.int64) - 2
    tm = np.full(len(S), -1, np.int64)
    for ci, coin in enumerate(COINS):
        m = S.coin.to_numpy() == ci
        if not m.any():
            continue
        g = grid(coin)
        tm[m] = _touch(g["l"], g["h"], S.e.to_numpy(np.int64)[m], S.side.to_numpy(np.int64)[m],
                       np.nan_to_num(lvl[m], nan=-1e18), np.minimum(last[m], g["n"] - 2))
    S["e_sig"] = S.e
    S["touch"] = tm
    S = S[tm >= 0].copy()
    S["e"] = S.touch + 1
    for ci, coin in enumerate(COINS):
        m = S.coin.to_numpy() == ci
        if m.any():
            S.loc[m, "p0"] = grid(coin)["o"][S.e.to_numpy(np.int64)[m]]
    return S.reset_index(drop=True)


# ---------------------------------------------------------------- self test
def selftest():
    import time
    t0 = time.time()
    # 1) the walk with form 1, no forced exit, 30x == the grid's w30 (all coins, random 15m-boundary rows)
    S = RD.signals(names=["F16_FIB382", "V39_ALL"], tfs=["30m", "1h"], period=(ms("2021-01-01"), FWD[1]))
    S = S.sample(4000, random_state=1).reset_index(drop=True)
    S = RD.add_outcomes(S, ["w30"])
    S["force"] = -1
    r = np.full(len(S), np.nan)
    k = np.full(len(S), -1)
    w = np.full(len(S), -1)
    for ci, coin in enumerate(COINS):
        m = S.coin.to_numpy() == ci
        g = grid(coin)
        cumf = np.cumsum(g["fund"])
        o, h, l, c = (np.ascontiguousarray(g[x], dtype=np.float64) for x in ("o", "h", "l", "c"))
        a = walk(o, h, l, c, cumf, S.e.to_numpy(np.int64)[m], S.side.to_numpy(np.int64)[m], np.full(m.sum(), 30.0),
                 np.full(m.sum(), -1, np.int64), COST, FL, GAP, STEP, 0.0, 0.0, -0.5, g["n"])
        r[m], k[m], w[m] = a
    ok = np.isfinite(S.w30_r)
    d = np.abs(r[ok] - S.w30_r.to_numpy()[ok])
    print("walk form1 vs grid w30: rows", ok.sum(), "max |dr|", d.max(), "k equal", (k[ok] == S.w30_k.to_numpy()[ok]).mean(),
          "why equal", (w[ok] == S.w30_why.to_numpy()[ok]).mean())
    assert d.max() < 2e-6 and (k[ok] == S.w30_k.to_numpy()[ok]).all()
    # 2) the two-part ladder == paperbot/ladder2.ComboLadder.lock_for on a dense grid
    sys.path.insert(0, REPO)
    from paperbot.ladder2 import ComboLadder
    spec = ComboLadder(first_lock=0.10, trigger_gap=0.01, step=0.05, next_trigger=0.15, next_gap=0.03)
    for b in np.linspace(-0.2, 1.5, 3401):
        a_ = _lock(b, *LADDER2)
        e_ = spec.lock_for(float(b))
        assert (e_ is None and np.isnan(a_)) or (e_ is not None and abs(a_ - e_) < 1e-9), (b, a_, e_)
    print("ladder2 == ComboLadder on 3,401 points")
    # 3) judge == the data layer's add_judge (tj_dir / tj_adx) on the bot's mapping
    S2 = RD.signals(names=["F9_IFVG", "F16_FIB382", "F15_ORB"], tfs=["30m", "1h", "4h"], period=(ms("2022-01-01"), FWD[1]))
    S2 = S2.sample(3000, random_state=2).reset_index(drop=True)
    A = judge(S2, HTF_OF, "vote3")
    B = RD.add_judge(S2, check=False)
    mm = np.isfinite(B.tj_dir) & np.isfinite(A.j_dir)
    print("judge vs add_judge: rows", mm.sum(), "dir equal", (A.j_dir[mm] == B.tj_dir[mm]).mean(),
          "adx max diff", np.nanmax(np.abs(A.j_adx[mm] - B.tj_adx[mm])))
    assert (A.j_dir[mm] == B.tj_dir[mm]).all()
    print("selftest ok", round(time.time() - t0, 1), "s")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        selftest()
