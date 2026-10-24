"""Loader of the role-combination data layer (analysis/review1024/roles/data; files under common.OUT). Import it from a
script in another folder with

    import sys; sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
    import rolesdata as RD

and run that script without -I (pandas). Everything here is read-only over the built files (MANIFEST_KO.md).

    S = RD.signals(names=["O4_STOCHRSI_ZONE"], tfs=["1h"], period="five")   # one row per signal
    S = RD.add_outcomes(S, ["w35"])            # w35_r, w35_roe, w35_k, w35_why + w35_opp_* (coin-flip twin side)
    S = RD.add_states(S, "4h", ["OBV_S", "V39_ALL"], kind="c")   # c4h_OBV_S, c4h_V39_ALL (last CLOSED 4h bar)
    S = RD.add_judge(S)                        # the trend bot's judge of each row's higher bar + tj_why_1022 / 1021
    took = RD.one_position(S, "w35")           # one position at a time over all rows (the bot's rule)
    acct = RD.account(S[took], "w35", margin=0.4)

Conventions: t = bar close (ms UTC) = the entry minute's open; e = minutes from T0 (2020-01-01); side +1 / -1;
r = net price return after the 0.124 % round-trip cost (taker 0.042 % + slippage 0.02 % each side), WITHOUT the
TetherMax payback (payback=True adds common.PAYBACK); roe = leverage x r. A trade with why == 3 was still open at the
data end (2026-10-24 14:12 UTC) and is marked at the last close: drop or flag it."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *          # noqa: E402,F401
import numba                  # noqa: E402

LEV = {k: v[1] for k, v in VARIANTS.items()}
PERIODS = {"five": FIVE, "fwd": FWD, "select": (ms("2020-03-01"), ms("2024-01-01")),
           "confirm": (ms("2024-01-01"), ms("2025-07-01")), "late": (ms("2025-07-01"), GRID_END)}
TJ_HTF = {"15m": "1h", "30m": "1h", "1h": "4h", "4h": "1d"}


# ====================================================================== names and roles
def names():
    """sid, set, name, role (trend / range / pullback / breakout / reversal / other / timing), dual (other roles)."""
    T = pd.read_csv(os.path.join(OUT, "signals", "names.csv"))
    R = roles()
    role, dual = {}, {}
    for it in R["items"]:
        r = it["role"]
        if r == "entry":
            r = next((k for k, v in R["roles"]["entry"].items() if it["id"] in v), "entry")
        role[it["id"]] = r
        dual[it["id"]] = ",".join(it.get("dual") or [])
    T["role"] = T.name.map(role).fillna("?")
    T["dual"] = T.name.map(dual).fillna("")
    return T


# ====================================================================== signals
_SIG = {}


def _sigfile(coin):
    if coin not in _SIG:
        _SIG[coin] = np.load(os.path.join(OUT, "signals", f"{coin}.npz"))
    return _SIG[coin]


def period_of(period):
    if period is None:
        return (T0, 2**62)
    if isinstance(period, str):
        return PERIODS[period]
    return tuple(int(x) for x in period)


def signal_bits(name, tf, coin):
    """(long, short) bool arrays over the coin's whole bars on tf (bar number nb), and e0 (entry minute of bar 0)."""
    N = globals()["names"]()
    sid = int(N.sid[N.name == name].iloc[0])
    z = _sigfile(coin)
    n = int(z[f"{tf}_n"])
    if f"{tf}_{sid}_L" not in z.files:
        return None, None, int(z[f"{tf}_e0"])
    return (np.unpackbits(z[f"{tf}_{sid}_L"])[:n].astype(bool), np.unpackbits(z[f"{tf}_{sid}_S"])[:n].astype(bool),
            int(z[f"{tf}_e0"]))


def signals(names=None, tfs=TFS, period="five", sets=None, roles_=None, coins=None, min_nb=300):
    """Signals as a DataFrame: name, set, role, tf, coin (index into COINS), symbol, side, t, e, nb.
    period: "five" (2020-03-01 .. 2026-10-23 00:00 UTC bar close), "fwd" (2026-10-05 15:00 .. 10-24 15:00 UTC =
    10-06 .. 10-24 KST), "select" / "confirm" / "late", (a, b) ms, or None. min_nb: drop the first bars of each coin
    on that timeframe (indicator warm-up; 300 = the live bot's window)."""
    N = globals()["names"]()
    keep = N
    if names is not None:
        keep = keep[keep.name.isin(list(names))]
    if sets is not None:
        keep = keep[keep.set.isin(list(sets))]
    if roles_ is not None:
        keep = keep[keep.role.isin(list(roles_))]
    a, b = period_of(period)
    cl = [COINS.index(c) if isinstance(c, str) else int(c) for c in coins] if coins is not None else range(len(COINS))
    out = []
    for ci in cl:
        z = _sigfile(COINS[ci])
        for tf in tfs:
            n = int(z[f"{tf}_n"])
            e0 = int(z[f"{tf}_e0"])
            tfm = TF_MIN[tf]
            step = tfm * MIN                      # bar nb closes at T0 + (e0 + nb * tfm) min; keep a <= t < b
            lo = max(min_nb, -(-(a - T0 - e0 * MIN) // step), 0)
            hi = min(n, -(-(b - T0 - e0 * MIN) // step))
            if hi <= lo:
                continue
            for sid in keep.sid.to_numpy():
                for lab, sd in (("L", 1), ("S", -1)):
                    key = f"{tf}_{sid}_{lab}"
                    if key not in z.files:
                        continue
                    nb = np.flatnonzero(np.unpackbits(z[key])[lo:hi]) + lo
                    if not len(nb):
                        continue
                    e = e0 + nb.astype(np.int64) * tfm
                    out.append(pd.DataFrame({"sid": np.int16(sid), "tf": tf, "coin": np.int8(ci), "side": np.int8(sd),
                                             "t": T0 + e * MIN, "e": e, "nb": nb.astype(np.int32)}))
    if not out:
        return pd.DataFrame(columns=["sid", "tf", "coin", "side", "t", "e", "nb", "set", "name", "role", "symbol"])
    D = pd.concat(out, ignore_index=True)
    D = D.merge(keep[["sid", "set", "name", "role"]], on="sid", how="left")
    D["symbol"] = np.asarray(COINS, dtype=object)[D.coin.to_numpy(int)]
    return D.sort_values(["t", "coin", "tf", "sid"]).reset_index(drop=True)


# ====================================================================== outcomes
_GR = {}


def _grid(coin):
    if coin not in _GR:
        z = np.load(os.path.join(OUT, "grid", f"{coin}.npz"))
        _GR[coin] = {k: z[k] for k in z.files}
    return _GR[coin]


def add_outcomes(S, variants=("w35",), opp=True, payback=False):
    """Columns <v>_r, <v>_roe (= leverage x r), <v>_k (minutes to the exit), <v>_why (0 stop, 1 lock, 3 open) for the
    row's side, and <v>_opp_* for the opposite side (the coin-flip twin on the same entry). a2 uses each row's own
    timeframe. Rows whose entry minute is not on the grid get NaN / -1."""
    S = S.copy()
    e = S.e.to_numpy(np.int64)
    side = S.side.to_numpy()
    tf = S.tf.to_numpy()
    n = len(S)
    for v in variants:
        sfx = [("", 1)] + ([("_opp", -1)] if opp else [])
        for s_, sg in sfx:
            r = np.full(n, np.nan)
            k = np.full(n, -1, np.int64)
            w = np.full(n, -1, np.int8)
            for ci, coin in enumerate(COINS):
                mc = S.coin.to_numpy() == ci
                if not mc.any():
                    continue
                G = _grid(coin)
                for t_ in (TFS if v == "a2" else ("15m",)):
                    mt = mc & ((tf == t_) if v == "a2" else True)
                    if not mt.any():
                        continue
                    tfm = TF_MIN[t_]
                    j = e // tfm - 1
                    pre = f"a2_{t_}" if v == "a2" else v
                    nb_ = len(G[f"{pre}_L_r"])
                    ok = mt & (e % tfm == 0) & (j >= 0) & (j < nb_)
                    for sd, lab in ((1, "L"), (-1, "S")):
                        q = ok & (side * sg == sd)
                        jj = j[q]
                        r[q] = G[f"{pre}_{lab}_r"][jj]
                        k[q] = G[f"{pre}_{lab}_k"][jj]
                        w[q] = G[f"{pre}_{lab}_why"][jj]
            if payback:
                r = r + PAYBACK
            S[f"{v}{s_}_r"] = r
            S[f"{v}{s_}_roe"] = LEV[v] * r
            S[f"{v}{s_}_k"] = k
            S[f"{v}{s_}_why"] = w
    return S


def add_blocks(S):
    """blk: frcore.blocked code of the entry minute (0 none, 1 KST weekend, 2 US macro +-30 min -- the events file starts
    2026-10, so 2 never occurs earlier --, 3 NYSE open +-30 min); -1 off the 15m grid."""
    S = S.copy()
    b = np.load(os.path.join(OUT, "grid", "blk15.npy"))
    e = S.e.to_numpy(np.int64)
    j = e // 15 - 1
    ok = (e % 15 == 0) & (j >= 0) & (j < len(b))
    S["blk"] = np.where(ok, b[np.clip(j, 0, len(b) - 1)], -1)
    return S


# ====================================================================== higher-timeframe states
_STATES = {}


def _states(coin, htf):
    key = (coin, htf)
    if key not in _STATES:
        z = np.load(os.path.join(OUT, "states", f"{coin}_{htf}.npz"))
        _STATES[key] = {k: z[k] for k in z.files}
    return _STATES[key]


def htf_index(S, htf):
    """Index of the last CLOSED htf bar (close <= the signal's bar close) per row; -1 = none."""
    idx = np.full(len(S), -1, np.int64)
    t = S.t.to_numpy(np.int64)
    for ci, coin in enumerate(COINS):
        m = S.coin.to_numpy() == ci
        if m.any():
            Z = _states(coin, htf)
            idx[m] = last_closed(Z["ts"] + TF_MIN[htf] * MIN, t[m])
    return idx


def add_states(S, htf, sources, kind="c", min_nb=300, prefix=None):
    """Columns <kind><htf>_<source> (int8 +1 / -1 / 0) of the last closed htf bar; kind "c" = condition state, "l" =
    latch (side of the source's last own signal on htf). htf "auto" = the trend bot's mapping per row (15m / 30m -> 1h,
    1h -> 4h, 4h -> 1d). States of higher bars with bar number < min_nb (indicator warm-up) are set to 0, and so are
    l_ states that do not exist (DeepSeek / FRIEND_ROC on 1d)."""
    S = S.copy()
    pre = prefix or f"{kind}{htf}"
    htfs = {htf: np.ones(len(S), bool)} if htf != "auto" else \
        {h: S.tf.map(TJ_HTF).to_numpy() == h for h in HTFS}
    cols = {src: np.zeros(len(S), np.int8) for src in sources}
    for h, mh in htfs.items():
        if not mh.any():
            continue
        idx = htf_index(S, h)
        for ci, coin in enumerate(COINS):
            m = mh & (S.coin.to_numpy() == ci) & (idx >= 0)
            if not m.any():
                continue
            Z = _states(coin, h)
            ii = idx[m]
            warm = Z["nb"][ii] >= min_nb
            for src in sources:
                arr = Z.get(f"{kind}_{src}")
                if arr is None:
                    continue
                cols[src][m] = np.where(warm, arr[ii], 0)
    for src in sources:
        S[f"{pre}_{src}"] = cols[src]
    return S


def add_judge(S, htf="auto", min_nb=120, check=True, price="close"):
    """The trend bot's judgment of each row's higher bar (htf "auto" = 15m / 30m -> 1h, 1h -> 4h, 4h -> 1d, or one htf
    for all rows): tj_V39 tj_S6 tj_OBV tj_N12, tj_raw3, tj_dir (held), tj_adx, tj_adx_prev, tj_ema20, tj_atr, tj_i;
    and with check=True the entry checks of paperbot/trendjudge.check on the row's own bar (spot EMA20 / ATR14 / RSI14,
    price = the signal bar's close, as the bot's reference price ~ the next minute's open): tj_why_1022 (the live config
    since 10-22: 보류 allowed) and tj_why_1021 ('' = pass; else hold / against / weak / tired / breakout / far_htf /
    far_etf / rsi / na). min_nb = the live MIN_BARS (fewer closed bars: not judged -> na)."""
    S = S.copy()
    n = len(S)
    hmap = S.tf.map(TJ_HTF).to_numpy() if htf == "auto" else np.full(n, htf, dtype=object)
    J = {k: np.full(n, np.nan) for k in ("V39", "S6", "OBV", "N12", "raw3", "dir", "adx", "adx_prev", "ema20", "atr", "i")}
    for h in HTFS:
        mh = hmap == h
        if not mh.any():
            continue
        idx = htf_index(S, h)
        for ci, coin in enumerate(COINS):
            m = mh & (S.coin.to_numpy() == ci) & (idx >= 1)
            if not m.any():
                continue
            Z = _states(coin, h)
            ii = idx[m]
            ok = Z["nb"][ii] >= min_nb
            for k in ("V39", "S6", "OBV", "N12", "raw3", "dir", "adx", "ema20", "atr"):
                J[k][m] = np.where(ok, Z[f"j_{k}"][ii], np.nan)
            J["adx_prev"][m] = np.where(ok, Z["j_adx"][ii - 1], np.nan)
            J["i"][m] = ii
    for k, v in J.items():
        S[f"tj_{k}"] = v
    S["tj_htf"] = hmap
    if check:
        from build_forward import tj_check
        sp = spot(S)
        side = S.side.to_numpy(float)
        px = sp["spot_close"]
        Jc = {k: J[k] for k in ("dir", "adx", "adx_prev", "ema20", "atr")}
        for nm, he in (("1022", True), ("1021", False)):
            w, fh, fe = tj_check(S.name.to_numpy() if "name" in S else S.strategy.to_numpy(), S.tf.to_numpy(), side, px,
                                 Jc, sp, hold_entry=he)
            S[f"tj_why_{nm}"] = w
        S["far_htf_atr"], S["far_etf_atr"], S["spot_rsi"] = fh, fe, sp["spot_rsi"]
    return S


_SPOT = {}


def spot(S):
    """The signal bar's close, EMA20, ATR14, RSI14 (fg, as trendjudge.spot_frame) per row (bars rebuilt from the grid)."""
    out = {k: np.full(len(S), np.nan) for k in ("spot_close", "spot_ema20", "spot_atr", "spot_rsi")}
    t = S.t.to_numpy(np.int64)
    fg = libs()["fg"]
    for ci, coin in enumerate(COINS):
        for tf in TFS:
            m = (S.coin.to_numpy() == ci) & (S.tf.to_numpy() == tf)
            if not m.any():
                continue
            key = (coin, tf)
            if key not in _SPOT:
                df = bars(coin, tf)
                _SPOT[key] = (close_ms(df, tf), df.close.to_numpy(float), fg.ema(df["close"], 20).to_numpy(float),
                              fg.atr(df, 14).to_numpy(float), fg.rsi(df["close"], 14).to_numpy(float))
            bc, c, e20, a14, r14 = _SPOT[key]
            i = np.clip(np.searchsorted(bc, t[m]), 0, len(bc) - 1)
            good = bc[i] == t[m]
            for k, arr in (("spot_close", c), ("spot_ema20", e20), ("spot_atr", a14), ("spot_rsi", r14)):
                out[k][m] = np.where(good, arr[i], np.nan)
        drop(coin)
    return out


# ====================================================================== the forward tables
def forward(which="rule"):
    """forward_rule / forward_trendbot / forward_ac / forward_league (MANIFEST_KO.md)."""
    return pd.read_csv(os.path.join(OUT, f"forward_{which}.csv.gz"), low_memory=False)


# ====================================================================== account math
@numba.njit
def _one_pos(e, k, order):
    took = np.zeros(len(e), np.bool_)
    busy = -1
    for q in order:
        if k[q] < 0:
            continue
        if e[q] > busy:
            took[q] = True
            busy = e[q] + k[q]
    return took


def one_position(S, variant="w35", side_col="", priority=None):
    """Rows taken by a bot that holds ONE position at a time over all rows of S (all coins): a row is taken when its
    entry minute is after the previous taken trade's exit minute. Ties (same entry minute): priority column (lower
    first), else COINS order then tf then name. variant picks the exit (k) column: f"{variant}{side_col}_k"."""
    k = S[f"{variant}{side_col}_k"].to_numpy(np.int64)
    keys = [S.e.to_numpy(np.int64)]
    if priority is not None:
        keys.append(S[priority].to_numpy())
    else:
        keys += [S.coin.to_numpy(), S.tf.map({t: i for i, t in enumerate(TFS)}).to_numpy()]
    order = np.lexsort(tuple(reversed(keys)))
    return _one_pos(S.e.to_numpy(np.int64), k, order.astype(np.int64))


def account(T, variant="w35", margin=0.40, side_col="", start=None, end=None):
    """Compounded account over taken trades T (time order): equity *= 1 + margin x roe (margin = share of equity put
    up per trade; roe = leverage x r, floored at -100 %). Returns dict n, days, per_day, mean_roe, win, final_x,
    max_dd, worst_roe, open_at_end."""
    T = T.sort_values("t")
    roe = np.maximum(T[f"{variant}{side_col}_roe"].to_numpy(float), -1.0)
    eq = np.cumprod(1.0 + margin * roe)
    peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    dd = 1.0 - eq / peak
    a = start if start is not None else int(T.t.min()) if len(T) else 0
    b = end if end is not None else int(T.t.max()) if len(T) else 0
    days = max((b - a) / DAY, 1e-9)
    return {"n": len(T), "days": round(days, 2), "per_day": round(len(T) / days, 3),
            "mean_roe": float(np.mean(roe)) if len(T) else np.nan, "win": float(np.mean(roe > 0)) if len(T) else np.nan,
            "final_x": float(eq[-1]) if len(T) else 1.0, "max_dd": float(dd.max()) if len(T) else 0.0,
            "worst_roe": float(roe.min()) if len(T) else np.nan,
            "open_at_end": int((T[f"{variant}{side_col}_why"] == 3).sum())}


def goal_bootstrap(T, variant="w35", margin=0.40, days=None, horizon=30, n_boot=20000, seed=20261024, side_col="",
                   target=6.0):
    """Day-block bootstrap of a 30-day path: the taken trades grouped by UTC day (days without trades kept), `horizon`
    days drawn with replacement, trades in order, equity *= 1 + margin x roe. Returns P(reach target x first ... any
    time within the horizon), P(lose 50 % before reaching the target), P(lose 90 % before), median final multiple.
    days = (start ms, end ms) of the period the trades come from (default: their first .. last day)."""
    T = T.sort_values("t")
    roe = np.maximum(T[f"{variant}{side_col}_roe"].to_numpy(float), -1.0)
    d = (T.t.to_numpy(np.int64) // DAY)
    lo, hi = (d.min(), d.max()) if days is None else (days[0] // DAY, (days[1] - 1) // DAY)
    nd = int(hi - lo + 1)
    by = [roe[d == lo + i] for i in range(nd)]
    rng = np.random.default_rng(seed)
    hit = l50 = l90 = 0
    finals = np.empty(n_boot)
    for b in range(n_boot):
        eq, half_lost, done = 1.0, False, False       # done: the target was reached or 90 % was lost (path settled)
        for di in rng.integers(0, nd, horizon):
            for x in by[di]:
                eq *= 1.0 + margin * x
                if not done:
                    if eq >= target:
                        hit += 1
                        done = True
                    else:
                        if eq <= 0.5 and not half_lost:
                            l50 += 1
                            half_lost = True
                        if eq <= 0.1:
                            l90 += 1
                            done = True
        finals[b] = eq
    return {"p_target": hit / n_boot, "p_lose50_first": l50 / n_boot, "p_lose90_first": l90 / n_boot,
            "median_final_x": float(np.median(finals)), "days_in_sample": nd, "trades_in_sample": len(roe)}
