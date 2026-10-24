"""Verifier (costs / overlap lens) of the obvstoch claim: friend family (OBV trend x Stoch RSI) with-trend minus
against-trend per trade, family mean, coin-flip twin, trend-only, at cost x1 / x2 / x0 and funding off, per signal
(as the study) and ONE POSITION AT A TIME (6 coins pooled, per cell; also one position per coin).
Reads /dev/shm/claude_verify_cost (vwalk.py). Writes vcost_cells.csv.gz and vcost_summary.json here."""
import os, sys, json
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/obvstoch")
import numba
import oscore as O
from oscore import *
VC = "/dev/shm/claude_verify_cost"
HERE = os.path.dirname(os.path.abspath(__file__))
LEV = {"w35": 35.0, "a2": 30.0}
VARS = {"w35": ("x1", "x2", "xw"), "a2": ("x1", "x2", "xw")} if (len(sys.argv) > 1 and sys.argv[1] == "all") else {"w35": ("x1", "x2", "x0", "nf", "xw"), "a2": ("x1", "x2", "x0", "xw")}
PERS = ("PRE", "SEL", "CONF", "FIVE", "FWD")


def load_coin(coin):
    Z = np.load(os.path.join(VC, f"{coin}.npz")); W = np.load(os.path.join(VC, f"walk_{coin}.npz"))
    D = {}
    for tf in O.ENTRY_TFS:
        pre = f"{tf}_"
        e = Z[pre + "e"]; tfm = TF_MIN[tf]
        d = {"e": e, "t": T0 + e * MIN, "day": Z[pre + "day"]}
        for nm in O.TIMINGS:
            d["sig_" + nm] = Z[pre + "sig_" + nm]
        for htf in O.HTF_OF[tf]:
            for T in O.TRENDS:
                d[f"st_{htf}_{T}"] = Z[f"{pre}st_{htf}_{T}"]
        j15 = e // 15 - 1
        ok15 = (j15 >= 0) & (j15 < len(W["valid15"]))
        jc = np.clip(j15, 0, len(W["valid15"]) - 1)
        for v in VARS["w35"]:
            for lab in ("L", "S"):
                d[f"w35{v}_{lab}_r"] = np.where(ok15, W[f"w35{v}_{lab}_r"][jc], np.nan)
                d[f"w35{v}_{lab}_k"] = np.where(ok15, W[f"w35{v}_{lab}_k"][jc], -1)
                d[f"w35{v}_{lab}_w"] = np.where(ok15, W[f"w35{v}_{lab}_w"][jc], -1)
        # check: the study cache's w35 equals my x1
        for lab in ("L", "S"):
            a, b = Z[f"{pre}w35_{lab}_r"], d[f"w35x1_{lab}_r"].astype(np.float32)
            m = np.isfinite(a)
            assert np.allclose(a[m], b[m], atol=1e-7) and (np.isfinite(b) == m).all(), (coin, tf, lab)
        for v in VARS["a2"]:
            for lab in ("L", "S"):
                ref = W[f"a2{v}_{tf}_{lab}_r"]
                jt = e // tfm - 1
                okt = (jt >= 0) & (jt < len(ref))
                jt = np.clip(jt, 0, len(ref) - 1)
                d[f"a2{v}_{lab}_r"] = np.where(okt, ref[jt], np.nan)
                d[f"a2{v}_{lab}_k"] = np.where(okt, W[f"a2{v}_{tf}_{lab}_k"][jt], -1)
                d[f"a2{v}_{lab}_w"] = np.where(okt, W[f"a2{v}_{tf}_{lab}_w"][jt], -1)
        for lab in ("L", "S"):
            a, b = Z[f"{pre}a2_{lab}_r"], d[f"a2x1_{lab}_r"].astype(np.float32)
            m = np.isfinite(a)
            assert np.allclose(a[m], b[m], atol=1e-7, equal_nan=True), (coin, tf, lab, "a2")
        D[tf] = d
    return D


@numba.njit
def greedy(e, k, order):
    took = np.zeros(len(e), np.bool_)
    busy = -1
    for q in order:
        if k[q] < 0:
            continue
        if e[q] > busy:
            took[q] = True
            busy = e[q] + k[q]
    return took


def cell_rows(DD, tf, htf, T, Ot, X, v, per, mode):
    """mode: 'with' / 'against' / 'trend' (every bar in the trend direction). Returns e, coin, roe, opp, k, day."""
    a, b = O.P[per]
    acc = {q: [] for q in ("e", "coin", "roe", "opp", "k", "day")}
    lev = LEV[X]
    for ci, coin in enumerate(COINS):
        d = DD[coin][tf]
        mt = (d["t"] >= a) & (d["t"] < b)
        st = d[f"st_{htf}_{T}"]
        if mode == "trend":
            side = st; m = mt & (st != 0)
        else:
            sig = d["sig_" + Ot]; side = sig
            m = mt & (sig != 0) & ((st == sig) if mode == "with" else (st == -sig))
        sd = side[m]
        rL, rS = d[f"{X}{v}_L_r"][m], d[f"{X}{v}_S_r"][m]
        kL, kS = d[f"{X}{v}_L_k"][m], d[f"{X}{v}_S_k"][m]
        wL, wS = d[f"{X}{v}_L_w"][m], d[f"{X}{v}_S_w"][m]
        r = np.where(sd > 0, rL, rS); ro = np.where(sd > 0, rS, rL)
        k = np.where(sd > 0, kL, kS)
        w = np.where(sd > 0, wL, wS); wo = np.where(sd > 0, wS, wL)
        keep = np.isfinite(r) & np.isfinite(ro) & (w != 3) & (wo != 3)
        acc["e"].append(d["e"][m][keep]); acc["coin"].append(np.full(int(keep.sum()), ci))
        acc["roe"].append(lev * r[keep]); acc["opp"].append(lev * ro[keep]); acc["k"].append(k[keep])
        acc["day"].append(d["day"][m][keep])
    return {q: np.concatenate(z) for q, z in acc.items()}


def onepos(R, per_coin=False):
    if not len(R["e"]):
        return np.zeros(0, bool)
    if per_coin:
        took = np.zeros(len(R["e"]), bool)
        for ci in range(len(COINS)):
            ix = np.where(R["coin"] == ci)[0]
            o = ix[np.argsort(R["e"][ix], kind="stable")]
            took |= greedy(R["e"].astype(np.int64), R["k"].astype(np.int64), o.astype(np.int64))
        return took
    o = np.lexsort((R["coin"], R["e"]))
    return greedy(R["e"].astype(np.int64), R["k"].astype(np.int64), o.astype(np.int64))


if __name__ == "__main__":
    DD = {c: load_coin(c) for c in COINS}
    print("loaded; study cache w35/a2 == my x1 walks (asserted)", flush=True)
    which = sys.argv[1] if len(sys.argv) > 1 else "famA"
    trends = O.OBV_TRENDS if which == "famA" else ("ST", "EMA21_52", "ICHI", "J3", "J3A")
    recs = []
    to_cache = {}
    for (tf, htf) in O.MAPS:
        for T in trends:
            for X in ("w35", "a2"):
                for v in VARS[X]:
                    for per in PERS:
                        a, b = O.P[per]
                        nd = (min(b, ext_end()) - a) / DAY
                        key = (tf, htf, T, X, v, per)
                        Rt = cell_rows(DD, tf, htf, T, None, X, v, per, "trend")
                        tk = onepos(Rt); tkc = onepos(Rt, True)
                        to_cache[key] = (Rt["roe"].mean() if len(Rt["roe"]) else np.nan,
                                         Rt["roe"][tk].mean() if tk.any() else np.nan, int(tk.sum()) / nd,
                                         Rt["roe"][tkc].mean() if tkc.any() else np.nan)
                        for Ot in O.SRSI:
                            Rw = cell_rows(DD, tf, htf, T, Ot, X, v, per, "with")
                            Ra = cell_rows(DD, tf, htf, T, Ot, X, v, per, "against")
                            tw, ta = onepos(Rw), onepos(Ra)
                            twc, tac = onepos(Rw, True), onepos(Ra, True)
                            mean = lambda x: float(x.mean()) if len(x) else np.nan
                            recs.append(dict(tf=tf, htf=htf, trend=T, timing=Ot, exit=X, var=v, period=per,
                                n_with=len(Rw["roe"]), with_=mean(Rw["roe"]), coin=mean(Rw["opp"]),
                                n_against=len(Ra["roe"]), against=mean(Ra["roe"]),
                                trend_only=to_cache[key][0],
                                op_n_with=int(tw.sum()), op_with=mean(Rw["roe"][tw]), op_coin=mean(Rw["opp"][tw]),
                                op_n_against=int(ta.sum()), op_against=mean(Ra["roe"][ta]),
                                op_trend_only=to_cache[key][1], op_trend_per_day=to_cache[key][2],
                                op_with_per_day=int(tw.sum()) / nd,
                                opc_with=mean(Rw["roe"][twc]), opc_against=mean(Ra["roe"][tac]),
                                opc_trend_only=to_cache[key][3], opc_n_with=int(twc.sum())))
            print(tf, htf, T, flush=True)
    C = pd.DataFrame(recs)
    C.to_csv(os.path.join(HERE, f"vcost_{which}.csv.gz"), index=False, float_format="%.6g")
    print(len(C))
