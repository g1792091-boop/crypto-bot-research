"""Round 3 (PREREG3.md): every signal of the 189 strategy labels in research/newlive's signals (read as they are) under
the 24 exits, for the signal's side and the other side (coin-flip twin). Same fills and costs as vwbuild.py.

    python3 -I vwbuild3.py [--procs 3] [--only LABEL,...]     -> OUT3/<label>.npz

A file: t (entry = bar close, ms), coin (index into COINS), side, atrf (signal ATR / entry price), ret, tx (exit minute
offset), ret_o, tx_o (the other side). ret float32, tx int16, one column per exit (exits3.json)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from vwbuild import owners_lev, lock_house, lock_owners, first_true
from vwcommon import *
import glob, warnings
from multiprocessing import Pool
warnings.filterwarnings("ignore", category=RuntimeWarning)

OUT3 = OUT + "_r3"
SIG = os.path.join(NL.NL, "signals")


def exits3():
    ex = []
    for s in (1.0, 1.5, 2.0, 3.0):
        ex += [{"kind": "house", "stop": s, "lev": 30},
               {"kind": "grid", "stop": s, "target": 1.0, "be": None},
               {"kind": "grid", "stop": s, "target": 2.0, "be": None},
               {"kind": "grid", "stop": s, "target": None, "be": 1.0},
               {"kind": "trail", "stop": s, "act": 1.0, "dist": 0.5}]
    ex += [{"kind": "grid", "stop": 2.0, "target": None, "be": None},
           {"kind": "grid", "stop": 3.0, "target": None, "be": None},
           {"kind": "grid", "stop": 0.75, "target": None, "be": 1.0},
           {"kind": "owners"}]
    for i, e in enumerate(ex):
        e["id"] = i
        e["time"] = HOLD_BARS
    return ex


EXITS3 = exits3()


def exit3_name(e):
    if e["kind"] == "owners":
        return "두 분 방식(순ROE −50% + 두 분 계단)"
    if e["kind"] == "house":
        return f"손절 {e['stop']:g}ATR · 규칙봇 계단"
    if e["kind"] == "trail":
        return f"손절 {e['stop']:g}ATR · +1ATR 뒤 0.5ATR 따라가기"
    t = "익절 없음" if e["target"] is None else f"익절 {e['target']:g}ATR"
    return f"손절 {e['stop']:g}ATR · {t}" + (" · +1ATR 뒤 본전" if e["be"] else "")


def outcomes3(P, s, atrf, coin, tfmin, hmax):
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
    a2 = atrf[:, None]
    tn = np.minimum(HOLD_BARS * tfmin, hmax) - 1
    ret = np.zeros((n, len(EXITS3)), np.float32)
    tt = np.zeros((n, len(EXITS3)), np.int16)
    t_stop, t_tgt = {}, {}
    t_act = (RMU < 1.0 * a2).sum(1)
    t_be = first_true((DN <= 0) & (col > t_act[:, None]))
    lp_h = lock_house(30.0 * (RMUp - COST_RT))
    lp_h = np.where(np.isnan(lp_h), -np.inf, lp_h / 30.0 + COST_RT)
    for e in EXITS3:
        j = e["id"]
        if e["kind"] == "grid":
            k = e["stop"]
            if k not in t_stop:
                t_stop[k] = (RMD > -k * a2).sum(1)
            ts = t_stop[k].copy()
            lvl = -k * atrf
            if e["be"] is not None:
                use = t_act < ts
                lvl = np.where(use & (t_be <= ts), 0.0, lvl)
                ts = np.where(use, np.minimum(t_be, ts), ts)
            if e["target"] is not None:
                if e["target"] not in t_tgt:
                    t_tgt[e["target"]] = (RMU < e["target"] * a2).sum(1)
                tg = t_tgt[e["target"]]
            else:
                tg = np.full(n, W + 1)
            tgl = (e["target"] or 0.0) * atrf
            t = np.minimum(np.minimum(ts, tg), tn)
            is_stop = (ts <= tg) & (ts <= tn)
            is_tgt = ~is_stop & (tg <= tn)
            tc = np.minimum(t, W - 1)
            v = np.where(is_stop, np.minimum(lvl, OP[rows, tc]), np.where(is_tgt, tgl, CL[rows, tc]))
        else:
            if e["kind"] == "trail":
                level = np.where(RMUp >= e["act"] * a2, RMUp - e["dist"] * a2, -np.inf)
                level = np.maximum(level, -e["stop"] * a2)
            elif e["kind"] == "house":
                level = np.maximum(lp_h, -e["stop"] * a2)
            else:
                lev = float(owners_lev(coin))
                lk = lock_owners(lev * (RMUp - COST_RT))
                level = np.maximum(np.where(np.isnan(lk), -np.inf, lk / lev + COST_RT), -(0.5 / lev - COST_RT))
            th = first_true(DN <= level)
            t = np.minimum(th, tn)
            hit = th <= tn
            tc = np.minimum(t, W - 1)
            v = np.where(hit, np.minimum(level[rows, tc], OP[rows, tc]), CL[rows, tc])
        tc = np.minimum(t, W - 1)
        ret[:, j] = v - COST_RT - FC[rows, tc]
        tt[:, j] = tc
    return ret, tt


def job(path):
    t0 = time.time()
    label = os.path.basename(path)[:-4]
    Z = np.load(path)
    tf = "30m" if "_at_30m" in label else "1h"
    k = TF_MIN[tf]
    W = HOLD_BARS * k
    out = {q: [] for q in ("t", "coin", "side", "atrf", "ret", "tx", "ret_o", "tx_o")}
    for ci, coin in enumerate(COINS):
        m = Z["coin"] == ci
        if not m.any():
            continue
        g = grid(coin)
        t_ = Z["t"][m].astype(np.int64)
        side = Z["side"][m].astype(int)
        atr = Z["atr"][m].astype(float)
        e = (t_ - T0) // MIN
        ok = (e < g["n"] - 1) & (e >= 1) & np.isfinite(atr) & (atr > 0)
        t_, side, atr, e = t_[ok], side[ok], atr[ok], e[ok]
        ep = g["o"][e]
        ok = np.isfinite(ep) & (ep > 0)
        t_, side, atr, e, ep = t_[ok], side[ok], atr[ok], e[ok], ep[ok]
        n = len(t_)
        if not n:
            continue
        hmax = np.minimum(W, g["n"] - e).astype(np.int64)
        cumf = np.cumsum(g["fund"])
        R = {q: np.zeros((n, len(EXITS3)), np.float32 if q.startswith("ret") else np.int16) for q in ("ret", "tx", "ret_o", "tx_o")}
        CH = max(100, int(1_500_000 // W))
        for a in range(0, n, CH):
            b = min(n, a + CH)
            idx = np.minimum(e[a:b, None] + np.arange(W)[None, :], g["n"] - 1)
            base = ep[a:b, None]
            P = {"H": g["h"][idx] / base - 1, "L": g["l"][idx] / base - 1, "C": g["c"][idx] / base - 1,
                 "O": g["o"][idx] / base - 1, "F": cumf[idx] - cumf[e[a:b] - 1][:, None]}
            af = atr[a:b] / ep[a:b]
            R["ret"][a:b], R["tx"][a:b] = outcomes3(P, side[a:b], af, coin, k, hmax[a:b])
            R["ret_o"][a:b], R["tx_o"][a:b] = outcomes3(P, -side[a:b], af, coin, k, hmax[a:b])
        out["t"].append(t_)
        out["coin"].append(np.full(n, ci, np.int8))
        out["side"].append(side.astype(np.int8))
        out["atrf"].append((atr / ep).astype(np.float32))
        for q in R:
            out[q].append(R[q])
    if not out["t"]:
        return label, 0, 0.0
    res = {q: np.concatenate(v) for q, v in out.items()}
    np.savez(os.path.join(OUT3, f"{label}.npz"), **res)
    return label, len(res["t"]), round(time.time() - t0, 1)


if __name__ == "__main__":
    procs = int(sys.argv[sys.argv.index("--procs") + 1]) if "--procs" in sys.argv else 3
    files = sorted(glob.glob(os.path.join(SIG, "*.npz")))
    if "--only" in sys.argv:
        want = set(sys.argv[sys.argv.index("--only") + 1].split(","))
        files = [f for f in files if os.path.basename(f)[:-4] in want]
    os.makedirs(OUT3, exist_ok=True)
    json.dump(EXITS3, open(os.path.join(OUT3, "exits3.json"), "w"))
    done = {os.path.basename(f)[:-4] for f in glob.glob(os.path.join(OUT3, "*.npz"))} if "--resume" in sys.argv else set()
    files = [f for f in files if os.path.basename(f)[:-4] not in done]
    # big files first so the pool ends evenly
    files.sort(key=lambda f: -os.path.getsize(f))
    t0 = time.time()
    with Pool(procs, maxtasksperchild=8) as pool:
        for i, r in enumerate(pool.imap_unordered(job, files)):
            print(i + 1, len(files), *r, round(time.time() - t0), flush=True)
