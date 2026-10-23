"""Round 2 (PREREG2.md): every signal's outcome under the 512 exits = stop {1, 1.5, 2, 3 ATR} x profit side (8) x early
exit (16), for the signal's side and the other side (coin-flip twin). Entry books: 15m, 30m, 1h and 30mc (30m with the
next-bar confirmation entry).

    python3 -I vwbuild2.py 30m 15m 1h 30mc [--procs 3]      -> OUT2/<book>/<coin>.npz, <coin>_features.pkl, exits2.json

Early exits fill at a close: the reclaim exit at the close of the bar (of the book's timeframe) that closes back across
VWAP by the buffer; the BTC exit at the close of the first minute BTC's close is x against the trade (BTC's own price
for BTC trades); the no-progress exit at the close of minute T if the best price so far is short of k ATR. In one
minute: stop, then the profit side, then the early exit (it acts on the close)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from vwbuild import features, owners_lev, lock_house, lock_owners, first_true
from vwcommon import *
import warnings
from multiprocessing import Pool
warnings.filterwarnings("ignore", category=RuntimeWarning)

OUT2 = OUT + "_r2"
STOPS2 = (1.0, 1.5, 2.0, 3.0)
PROFITS = ("house", "owners", 0.5, 0.75, 1.0, 1.5, "trail", None)
RECL = (0.0, 0.1, 0.25)
BTCX = (0.003, 0.005, 0.0075)
NOPROG = ((30, 0.25), (30, 0.5), (60, 0.25), (60, 0.5), (120, 0.25), (120, 0.5))
EARLY = ([()] + [(("A", b),) for b in RECL] + [(("B", x),) for x in BTCX] + [(("C", T, k),) for T, k in NOPROG]
         + [(("A", 0.0), ("B", 0.005)), (("A", 0.0), ("C", 60, 0.25)), (("A", 0.0), ("B", 0.005), ("C", 60, 0.25))])
BOOK_TF = {"15m": "15m", "30m": "30m", "1h": "1h", "30mc": "30m"}


def exits2():
    ex = []
    for s in STOPS2:
        for p in PROFITS:
            for ev in EARLY:
                ex.append({"id": len(ex), "stop": s, "profit": p, "early": [list(x) for x in ev], "time": HOLD_BARS})
    return ex


EXITS2 = exits2()


def exit2_name(e):
    p = e["profit"]
    pk = {"house": "규칙봇 계단", "owners": "두 분 계단", "trail": "+1ATR 뒤 0.5ATR 따라가기", None: "익절 없음"}.get(
        p, f"익절 {p:g}ATR" if not isinstance(p, str) and p is not None else str(p))
    names = []
    for x in e["early"]:
        if x[0] == "A":
            names.append(f"VWAP 재돌파 청산(여유 {x[1]:g}ATR)")
        elif x[0] == "B":
            names.append(f"BTC 반대 {x[1] * 100:g}% 청산")
        else:
            names.append(f"{x[1]}분 안에 +{x[2]:g}ATR 못 가면 청산")
    return f"손절 {e['stop']:g}ATR · {pk}" + ("" if not names else " · " + " + ".join(names))


def tf_vwap(df):
    h, l, c, v = (df[k].to_numpy(float) for k in ("high", "low", "close", "volume"))
    day = df.ts.to_numpy(np.int64) // DAY
    pv = pd.Series((h + l + c) / 3 * v).groupby(day).cumsum().to_numpy()
    cv = pd.Series(v).groupby(day).cumsum().to_numpy()
    with np.errstate(all="ignore"):
        return np.where(cv > 0, pv / cv, np.nan), c


def confirm_entries(df, sg):
    """30mc: the bar after the signal closes further the trade's way than the signal bar and still on the trade's side of
    VWAP; the entry is that bar's close. i stays the signal bar (its features), j is the entry bar."""
    vw, c = tf_vwap(df)
    i = sg.i.to_numpy()
    s = sg.side.to_numpy()
    j = i + 1
    ok = j < len(c)
    j = np.minimum(j, len(c) - 1)
    ok &= ((c[j] - c[i]) * s > 0) & ((c[j] - vw[j]) * s > 0)
    out = sg[ok].copy()
    out["j"] = j[ok]
    out["bar_close"] = df.ts.to_numpy()[out.j.to_numpy()] + 30 * MIN
    return out.reset_index(drop=True)


def outcomes2(P, s, atrf, coin, tfmin, hmax, recl_t, btc_path):
    """P: H L C O F matrices from the entry minute; recl_t: {buffer: minute offset of the reclaim close (W+1 = none)} for
    side s; btc_path: BTC close / BTC entry open - 1 per minute (n x W)."""
    n, W = P["H"].shape
    s2 = s[:, None]
    UP = np.where(s2 > 0, P["H"], -P["L"])
    DN = np.where(s2 > 0, P["L"], -P["H"])
    CL, OP, FC = s2 * P["C"], s2 * P["O"], s2 * P["F"]
    col = np.arange(W)[None, :]
    valid = col < hmax[:, None]
    DN = np.where(valid, DN, np.inf)
    UP = np.where(valid, UP, -np.inf)
    RMU = np.maximum.accumulate(UP, axis=1)
    RMD = np.minimum.accumulate(DN, axis=1)
    RMUp = np.concatenate([np.zeros((n, 1)), RMU[:, :-1]], axis=1)
    rows = np.arange(n)
    big = W + 10
    tn = np.minimum(HOLD_BARS * tfmin, hmax) - 1
    a2 = atrf[:, None]
    # early-exit event minutes
    evt = {}
    for b in RECL:
        t = recl_t[b]
        evt[("A", b)] = np.where(t <= tn, t, big)
    bp = s2 * btc_path
    bp = np.where(valid, bp, np.inf)
    for x in BTCX:
        t = first_true(bp <= -x)
        evt[("B", x)] = np.where(t <= tn, t, big)
    for T, k in NOPROG:
        tc = np.minimum(T - 1, W - 1)
        hit = (RMU[:, tc] < k * atrf) & (tc <= tn)
        evt[("C", T, k)] = np.where(hit, tc, big)
    # stop / target times
    t_stop = {k: (RMD > -k * a2).sum(1) for k in STOPS2}
    t_tgt = {k: (RMU < k * a2).sum(1) for k in PROFITS if not isinstance(k, str) and k is not None}
    lev_h = 30.0
    lev_o = float(owners_lev(coin))
    lock_lv = {"house": lock_house(lev_h * (RMUp - COST_RT)), "owners": lock_owners(lev_o * (RMUp - COST_RT))}
    lp = {"house": np.where(np.isnan(lock_lv["house"]), -np.inf, lock_lv["house"] / lev_h + COST_RT),
          "owners": np.where(np.isnan(lock_lv["owners"]), -np.inf, lock_lv["owners"] / lev_o + COST_RT),
          "trail": np.where(RMUp >= 1.0 * a2, RMUp - 0.5 * a2, -np.inf)}
    lvl_hit = {}
    for p in ("house", "owners", "trail"):
        for k in STOPS2:
            level = np.maximum(lp[p], -k * a2)
            th = first_true(DN <= level)
            thc = np.minimum(th, W - 1)
            lvl_hit[(p, k)] = (th, np.minimum(level[rows, thc], OP[rows, thc]))
    ret = np.zeros((n, len(EXITS2)), np.float32)
    tt = np.zeros((n, len(EXITS2)), np.int32)
    ev_cache = {}
    for e in EXITS2:
        key = tuple(tuple(x) for x in e["early"])
        if key not in ev_cache:
            te = np.full(n, big)
            for x in key:
                te = np.minimum(te, evt[x])
            ev_cache[key] = te
        te = ev_cache[key]
        k, p = e["stop"], e["profit"]
        if isinstance(p, str):
            th, fill = lvl_hit[(p, k)]
            t = np.minimum(np.minimum(th, te), tn)
            is_l = (th <= te) & (th <= tn)
            is_e = ~is_l & (te <= tn)
            tc = np.minimum(t, W - 1)
            v = np.where(is_l, fill, CL[rows, tc])
        else:
            ts = t_stop[k]
            tg = t_tgt[p] if p is not None else np.full(n, big)
            t = np.minimum(np.minimum(np.minimum(ts, tg), te), tn)
            is_s = (ts <= tg) & (ts <= te) & (ts <= tn)
            is_t = ~is_s & (tg <= te) & (tg <= tn)
            tc = np.minimum(t, W - 1)
            v = np.where(is_s, np.minimum(-k * atrf, OP[rows, tc]), np.where(is_t, (p or 0.0) * atrf, CL[rows, tc]))
        ret[:, e["id"]] = v - COST_RT - FC[rows, tc]
        tt[:, e["id"]] = tc
    return ret, tt


def reclaim_times(c, vw, atr_sig, j0, s, tfmin, nb=HOLD_BARS):
    """Minute offset (from the entry minute) of the close of the first bar after the entry bar j0 that closes back across
    VWAP by b ATR, per buffer; W+10 when none."""
    n = len(j0)
    W = nb * tfmin
    k = np.arange(1, nb + 1)[None, :]
    jj = np.minimum(j0[:, None] + k, len(c) - 1)
    beyond = (j0[:, None] + k) >= len(c)
    d = (c[jj] - vw[jj]) * s[:, None]                     # > 0: still on the trade's side
    out = {}
    for b in RECL:
        cond = (d < -b * atr_sig[:, None]) & ~beyond & np.isfinite(d)
        f = first_true(cond)
        out[b] = np.where(f < nb, (f + 1) * tfmin - 1, W + 10)
    return out


def job(args):
    coin, book = args
    t0 = time.time()
    tf = BOOK_TF[book]
    k = TF_MIN[tf]
    g = grid(coin)
    gb = grid("BTCUSDT")
    df = bars(coin, tf)
    sg = signals(coin, tf, df)
    if book == "30mc":
        sg = confirm_entries(df, sg)
    sg = sg[(sg.bar_close.to_numpy(np.int64) - T0) // MIN < g["n"] - 1].reset_index(drop=True)
    j0 = (sg.j if book == "30mc" else sg.i).to_numpy()
    F = features(coin, tf, df, sg[["i", "side", "bar_close"]], g)
    vw, c = tf_vwap(df)
    W = HOLD_BARS * k
    e = ((F.bar_close.to_numpy(np.int64) - T0) // MIN).astype(np.int64)
    ep = F.entry_px.to_numpy()
    hmax = np.minimum(W, g["n"] - e).astype(np.int64)
    n = len(F)
    E = len(EXITS2)
    R = {"ret": np.zeros((n, E), np.float32), "t": np.zeros((n, E), np.int32),
         "ret_o": np.zeros((n, E), np.float32), "t_o": np.zeros((n, E), np.int32)}
    cumf = np.cumsum(g["fund"])
    atr_sig = F.atr.to_numpy()
    CH = max(150, int(2_000_000 // W))
    for a in range(0, n, CH):
        b = min(n, a + CH)
        idx = np.minimum(e[a:b, None] + np.arange(W)[None, :], g["n"] - 1)
        base = ep[a:b, None]
        P = {"H": g["h"][idx] / base - 1, "L": g["l"][idx] / base - 1, "C": g["c"][idx] / base - 1,
             "O": g["o"][idx] / base - 1, "F": cumf[idx] - cumf[e[a:b] - 1][:, None]}
        bi = np.minimum(idx, gb["n"] - 1)
        btc_path = gb["c"][bi] / gb["o"][e[a:b]][:, None] - 1
        s = F.side.to_numpy()[a:b]
        af = F.atrf.to_numpy()[a:b]
        hm = hmax[a:b]
        jb = j0[a:b]
        rt = reclaim_times(c, vw, atr_sig[a:b], jb, s, k)
        R["ret"][a:b], R["t"][a:b] = outcomes2(P, s, af, coin, k, hm, rt, btc_path)
        rto = reclaim_times(c, vw, atr_sig[a:b], jb, -s, k)
        R["ret_o"][a:b], R["t_o"][a:b] = outcomes2(P, -s, af, coin, k, hm, rto, btc_path)
    os.makedirs(os.path.join(OUT2, book), exist_ok=True)
    np.savez(os.path.join(OUT2, book, f"{coin}.npz"), **R)
    F.to_pickle(os.path.join(OUT2, book, f"{coin}_features.pkl"))
    return coin, book, n, round(time.time() - t0, 1)


if __name__ == "__main__":
    books = [a for a in sys.argv[1:] if a in BOOK_TF]
    procs = int(sys.argv[sys.argv.index("--procs") + 1]) if "--procs" in sys.argv else 3
    os.makedirs(OUT2, exist_ok=True)
    json.dump(EXITS2, open(os.path.join(OUT2, "exits2.json"), "w"))
    with Pool(procs) as pool:
        for r in pool.imap_unordered(job, [(c, bk) for bk in books for c in COINS]):
            print(*r, flush=True)
