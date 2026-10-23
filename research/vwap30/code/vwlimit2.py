"""PREREG10.md: limit entry k ATR better than the signal price, good for M minutes, conservative fills (the low must trade
0.02 % through the limit; the fill minute's earlier high is not used), maker entry + taker exit (round trip 0.09 %), against
the market entry (0.14 %). Two targets, both with the rule bot's exit (2 ATR + its ladder): V = VWAP fail 30m, M = round
9's ML pick A. The slot is held while the order waits; an unfilled order is no trade.

    python3 -I vwlimit2.py build [--procs 3]   -> OUT10/{V,M}_{variant}_{s,o}.npz (+ OUT10/m_cands.npz)
    python3 -I vwlimit2.py select              -> research/vwap30/finalists10.json (+ sha256)
    python3 -I vwlimit2.py confirm             -> research/vwap30/results10.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
import vwbuild3 as B
from vwcommon import *
from vwacct import metrics, _take
from vwstages3 import wd_mask
from vwconfirm import pick
import hashlib, glob, warnings
from multiprocessing import Pool
warnings.filterwarnings("ignore", category=RuntimeWarning)

OUT10 = OUT + "_r10"
RES_DIR = os.path.abspath(os.path.join(HERE, ".."))
COST_MKT, COST_LMT = 2 * (0.0005 + 0.0002), 0.0002 + 0.0005 + 0.0002
THRU = 0.0002
EX_H2 = next(e for e in B.EXITS3 if e["kind"] == "house" and e["stop"] == 2.0)
VARIANTS = [("mkt", None, 0)] + [(f"k{k:g}_m{M}", k, M) for k in (0.0, 0.1, 0.25, 0.5) for M in (5, 15, 30, 60)]
VALID = (ms("2023-07-01"), ms("2025-01-01"))
SEED10 = 20261103
VSIG = os.path.join(B.SIG, "F6_VWAP_FAIL_at_30m.npz")


def limit_out(coin, e, s, atr, tfm, k, M, cost):
    """(ret, minutes from the signal to the exit, filled) for the rule bot's exit, entries from minute e."""
    B.COST_RT = cost
    B.EXITS3 = [dict(EX_H2, id=0)]
    g = grid(coin)
    n = len(e)
    ref = g["o"][e]
    if k is None:
        f, px, filled = e.copy(), ref.copy(), np.ones(n, bool)
    else:
        Lp = ref - s * k * atr
        thr = Lp * (1 - s * THRU)
        idx = np.minimum(e[:, None] + np.arange(M)[None, :], g["n"] - 1)
        touch = np.where(s[:, None] > 0, g["l"][idx] <= thr[:, None], g["h"][idx] >= thr[:, None])
        filled = touch.any(1)
        f = e + touch.argmax(1)
        o_f = g["o"][f]
        px = np.where(s > 0, np.minimum(Lp, o_f), np.maximum(Lp, o_f))
    ret = np.full(n, np.nan)
    tt = np.full(n, max(M - 1, 0), np.int64)
    cumf = np.cumsum(g["fund"])
    for tf in np.unique(tfm):
        fi = np.flatnonzero(filled & (tfm == tf))
        W = int(96 * tf)
        for a in range(0, len(fi), 600):
            q = fi[a:a + 600]
            ff = f[q]
            idx = np.minimum(ff[:, None] + np.arange(W)[None, :], g["n"] - 1)
            base = px[q][:, None]
            P = {"H": g["h"][idx] / base - 1, "L": g["l"][idx] / base - 1, "C": g["c"][idx] / base - 1,
                 "O": g["o"][idx] / base - 1, "F": cumf[idx] - cumf[ff - 1][:, None]}
            if k is not None:                                  # the fill minute: nothing from before the fill
                sq = s[q]
                c0 = g["c"][ff] / px[q] - 1
                P["H"][:, 0] = np.where(sq > 0, np.maximum(c0, 0.0), P["H"][:, 0])
                P["L"][:, 0] = np.where(sq < 0, np.minimum(c0, 0.0), P["L"][:, 0])
                P["O"][:, 0] = 0.0
            hmax = np.minimum(W, g["n"] - ff).astype(np.int64)
            r, x = B.outcomes3(P, s[q], atr[q] / px[q], coin, int(tf), hmax)
            ret[q] = r[:, 0]
            tt[q] = x[:, 0].astype(np.int64) + (ff - e[q])
    return ret, tt, filled


def targets():
    """The two targets' signals: entry ms, coin, side, atr, timeframe minutes, priority (lower first among ties)."""
    Z = np.load(VSIG)
    ok = np.zeros(len(Z["t"]), bool)
    for ci, coin in enumerate(COINS):
        m = np.flatnonzero(Z["coin"] == ci)
        g = grid(coin)
        e = (Z["t"][m].astype(np.int64) - T0) // MIN
        good = (e >= 1) & (e < g["n"] - 2) & np.isfinite(Z["atr"][m]) & (Z["atr"][m] > 0)
        ep = g["o"][np.clip(e, 0, g["n"] - 1)]
        ok[m] = good & np.isfinite(ep) & (ep > 0)
        _GRID_clear()
    V = {"t": Z["t"][ok].astype(np.int64), "coin": Z["coin"][ok].astype(np.int64), "side": Z["side"][ok].astype(np.int64),
         "atr": Z["atr"][ok].astype(float), "tfm": np.full(ok.sum(), 30), "prio": np.zeros(ok.sum())}
    fp = os.path.join(OUT10, "m_cands.npz")
    if not os.path.exists(fp):
        import vwml as ML
        F = ML.load_feat()
        P = dict(np.load(os.path.join(ML.OUT9, "pred.npz")))
        f = json.load(open(os.path.join(RES_DIR, "finalists9.json")))["finalists"][0]
        rows = P["rows"]
        parts = []
        for o in (0, 1):
            p = P[f"p{f['exit']}_{o}"]
            k = p > f["theta"]
            r = rows[k]
            parts.append(dict(t=F["entry"][r], coin=F["coin"][r].astype(np.int64),
                              side=F["side"][r].astype(np.int64) * (-1 if o else 1), atrf=F["num"][r, 0].astype(float),
                              tfm=np.where(F["tf"][r] == 0, 30, 60), prio=-p[k].astype(float)))
        D = {q: np.concatenate([x[q] for x in parts]) for q in parts[0]}
        np.savez(fp, **D)
    D = dict(np.load(fp))
    atr = np.empty(len(D["t"]))
    for ci, coin in enumerate(COINS):
        m = D["coin"] == ci
        atr[m] = D["atrf"][m] * grid(coin)["o"][(D["t"][m] - T0) // MIN]
        _GRID_clear()
    Mx = {"t": D["t"], "coin": D["coin"], "side": D["side"], "atr": atr, "tfm": D["tfm"], "prio": D["prio"]}
    return {"V": V, "M": Mx}


def _GRID_clear():
    from vwcommon import _GRID
    _GRID.clear()


_TG = {}


def job(args):
    tg, name, k, M, flip = args
    fp = os.path.join(OUT10, f"{tg}_{name}_{'o' if flip else 's'}.npz")
    if os.path.exists(fp):
        return tg, name, flip, None
    S = _TG[tg]
    cost = COST_MKT if k is None else COST_LMT
    n = len(S["t"])
    ret, tt, fl = np.full(n, np.nan), np.zeros(n, np.int64), np.zeros(n, bool)
    for ci, coin in enumerate(COINS):
        m = np.flatnonzero(S["coin"] == ci)
        if not len(m):
            continue
        e = (S["t"][m] - T0) // MIN
        s = S["side"][m] * (-1 if flip else 1)
        r, x, f = limit_out(coin, e, s, S["atr"][m], S["tfm"][m], k, M, cost)
        ret[m], tt[m], fl[m] = r, x, f
        _GRID_clear()
    np.savez(fp, ret=ret, tt=tt, filled=fl)
    return tg, name, flip, round(float(fl.mean()), 3)


def build(procs):
    os.makedirs(OUT10, exist_ok=True)
    _TG.update(targets())
    jobs = [(tg, nm, k, M, fl) for tg in ("V", "M") for nm, k, M in VARIANTS for fl in (False, True)]
    with Pool(procs) as pool:
        for r in pool.imap_unordered(job, jobs):
            print("built", *r, flush=True)


class LBook:
    """One target under one variant, in (entry, priority, coin) order; flip columns = the other side."""

    def __init__(self, tg, name, T):
        S = np.load(os.path.join(OUT10, f"{tg}_{name}_s.npz"))
        O = np.load(os.path.join(OUT10, f"{tg}_{name}_o.npz"))
        o = np.lexsort((T["coin"], T["prio"], T["t"]))
        self.entry, self.coin = T["t"][o], T["coin"][o]
        self.ret, self.t = S["ret"][o][:, None], S["tt"][o][:, None]
        self.ret_o, self.t_o = O["ret"][o][:, None], O["tt"][o][:, None]
        self.fill, self.fill_o = S["filled"][o], O["filled"][o]
        ref_cost = COST_MKT if name == "mkt" else COST_LMT
        self.D = 2.0 * T["atrf"][o] + ref_cost
        kst = pd.to_datetime(self.entry + KST, unit="ms")
        self.wd = np.asarray(kst.dayofweek < 5)
        self.lev_owner = np.where(self.coin == 0, 40.0, 30.0)

    def risk_dist(self, j):
        return self.D


def take_f(book, m, j, flip=None):
    """The one-position pass with the slot held while an order waits; unfilled orders are not trades."""
    ret, t, fl = book.ret[:, 0], book.t[:, 0], book.fill
    if flip is not None:
        ret = np.where(flip, book.ret_o[:, 0], ret)
        t = np.where(flip, book.t_o[:, 0], t)
        fl = np.where(flip, book.fill_o, fl)
    ext = book.entry + (t.astype(np.int64) + 1) * MIN
    idx = _take(book.entry, ext, m)
    idx = idx[fl[idx]]
    return idx, ret[idx].astype(float), ext[idx], book.D[idx]


def with_atrf(T):
    T = dict(T)
    ref = np.empty(len(T["t"]))
    for ci, coin in enumerate(COINS):
        m = T["coin"] == ci
        ref[m] = grid(coin)["o"][(T["t"][m] - T0) // MIN]
        _GRID_clear()
    T["atrf"] = T["atr"] / ref
    return T


def run_metrics(book, per, flip=None, full=True):
    return metrics(book, wd_mask(book), 0, per, flip=flip, full=full, take=take_f)


def fill_rate(book, per):
    a, z = PERIODS[per]
    m = book.wd & (book.entry >= a) & (book.entry < z)
    return round(float(book.fill[m].mean()), 4)


def select():
    PERIODS["valid"] = VALID
    T = {k: with_atrf(v) for k, v in targets().items()}
    rows, fin = [], []
    for tg, per in (("V", "select"), ("M", "valid")):
        rr = []
        for nm, k, M in VARIANTS:
            b = LBook(tg, nm, T[tg])
            x = run_metrics(b, per)
            r = {"target": tg, "variant": nm, "k": k, "M": M, "fill": fill_rate(b, per), **pick(x)}
            rr.append(r)
            print(tg, per, nm, "fill", r["fill"], "n", x["n"], "wd", round(x["per_weekday"], 2), "win", round(x["win"], 3),
                  "R", round(x["avgR"], 3), "growth", round(x["growth"], 2), flush=True)
        ok = [r for r in rr if r["per_weekday"] >= 3.0]
        tag = ""
        if not ok:
            ok, tag = [r for r in rr if r["per_weekday"] >= 1.0], " (평일 3번 못 채움)"
        best = max(ok, key=lambda r: r["growth"])
        fin.append({"name": f"{tg}{tag}", "target": tg, "variant": best["variant"]})
        rows += rr
    fp = os.path.join(RES_DIR, "finalists10.json")
    json.dump({"made": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + "Z", "finalists": fin, "select_rows": rows},
              open(fp, "w"), ensure_ascii=False, indent=1, default=float)
    open(fp + ".sha256", "w").write(hashlib.sha256(open(fp, "rb").read()).hexdigest() + "  finalists10.json\n")
    for f in fin:
        print("finalist", f, flush=True)


def month_odds_t(book, a, z):
    m = wd_mask(book) & (book.entry >= a) & (book.entry < z)
    idx, net, ext, D = take_f(book, m, 0)
    kd = (book.entry[idx] + KST) // DAY
    d0, d1 = (a + KST) // DAY, (z + KST) // DAY
    out = {}
    for E in (9, 15, 20, 30):
        x = np.log1p(np.maximum(E * net, -1 + 1e-12))
        per = np.zeros(d1 - d0 + 1)
        np.add.at(per, kd - d0, x)
        cs = np.r_[0, np.cumsum(per)]
        mm = np.exp(cs[30:] - cs[:-30])
        out[str(E)] = {"x2": round(float((mm >= 2).mean()), 4), "x5": round(float((mm >= 5).mean()), 4),
                       "x10": round(float((mm >= 10).mean()), 4), "x20": round(float((mm >= 20).mean()), 4),
                       "lose90": round(float((mm <= 0.1).mean()), 4), "median": round(float(np.median(mm)), 4)}
    return out


def confirm():
    fp = os.path.join(RES_DIR, "finalists10.json")
    want = open(fp + ".sha256").read().split()[0]
    got = hashlib.sha256(open(fp, "rb").read()).hexdigest()
    assert want == got, "finalists10.json changed after it was frozen"
    PERIODS["valid"] = VALID
    PERIODS["c2025"] = (ms("2025-01-01"), ms("2026-01-01"))
    PERIODS["c2026"] = (ms("2026-01-01"), ms("2026-10-01"))
    T = {k: with_atrf(v) for k, v in targets().items()}
    rng = np.random.default_rng(SEED10)
    res = []
    for f in json.load(open(fp))["finalists"]:
        b = LBook(f["target"], f["variant"], T[f["target"]])
        mk = LBook(f["target"], "mkt", T[f["target"]])
        row = dict(f)
        for per in ("confirm", "c2025", "c2026", "live"):
            row[per] = {"fill": fill_rate(b, per), **pick(run_metrics(b, per))}
            row[f"{per}_market"] = pick(run_metrics(mk, per))
        tw = np.array([run_metrics(b, "confirm", flip=rng.random(len(b.entry)) < 0.5, full=False)["growth"]
                       for _ in range(2000)])
        q95 = float(np.percentile(tw, 95))
        g = row["confirm"]["growth"]
        row["twin"] = {"p50": round(float(np.median(tw)), 3), "p90": round(float(np.percentile(tw, 90)), 3),
                       "p95": round(q95, 3), "share_below": round(float((tw < g).mean()), 4)}
        row["verdict"] = "통함" if (row["confirm"]["avgR"] > 0 and g > q95) else "통하지 않음"
        a0 = SEL[0] if f["target"] == "V" else VALID[0]
        row["month_odds"] = month_odds_t(b, a0, CONF[1])
        row["month_odds_market"] = month_odds_t(mk, a0, CONF[1])
        res.append(row)
        c, cm = row["confirm"], row["confirm_market"]
        print(f["name"], f["variant"], "| confirm fill", c["fill"], "n", c["n"], "wd", round(c["per_weekday"], 2), "win", c["win"],
              "R", c["avgR"], "g", g, "p95", round(q95, 2), "->", row["verdict"], "| market n", cm["n"], "R", cm["avgR"], "g",
              cm["growth"], "| live n", row["live"]["n"], "R", row["live"]["avgR"], flush=True)
    json.dump({"made": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + "Z", "finalists_sha256": got, "finalists": res},
              open(os.path.join(RES_DIR, "results10.json"), "w"), ensure_ascii=False, indent=1, default=float)
    print("written results10.json")


def check():
    """The market variant of V against round 3's VWAP 30m outcomes (rule bot exit): must match."""
    S = np.load(os.path.join(OUT10, "V_mkt_s.npz"))
    T = targets()["V"]
    Z = np.load(os.path.join(B.OUT3, "F6_VWAP_FAIL_at_30m.npz"))
    a = pd.DataFrame({"t": T["t"], "coin": T["coin"], "r": S["ret"], "x": S["tt"]})
    b = pd.DataFrame({"t": Z["t"], "coin": Z["coin"].astype(np.int64), "r3": Z["ret"][:, EX_H2["id"]], "x3": Z["tx"][:, EX_H2["id"]]})
    j = a.merge(b, on=["t", "coin"])
    bad = (~np.isclose(j.r, j.r3, atol=1e-5)) | (j.x != j.x3)
    print("parity rows", len(j), "of", len(a), "bad", int(bad.sum()))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "build":
        build(int(sys.argv[sys.argv.index("--procs") + 1]) if "--procs" in sys.argv else 3)
    else:
        {"select": select, "confirm": confirm, "check": check}[cmd]()
