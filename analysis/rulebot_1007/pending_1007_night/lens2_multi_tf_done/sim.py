"""One-position trader accounts per strategy over several timeframes (rule proxies of the AI's choices).

    python3 -I -B sim.py <core_sig_dir> <outc_dir> <res_dir> [procs]

Signals: every signal of one strategy (core 36 or DeepSeek 44) on the timeframes of a scope, six coins,
2021-08-01..2026-09-30, each with its precomputed ALONE house-exit outcome (precompute.py). Decision time = the
signal bar's close = the entry 15m bar e. A position entered at e and exiting inside 15m bar x frees the trader for
signals with e' > x.

Scopes: A = 15m+30m, ALL = 15m+30m+1h+4h, HI = 1h+4h (D's second trader), single tfs (rule accounts), and ALLINF =
all four including signals neither 30x nor 20x can size (ladder at 20x; leverage below the owners' range in reality).
Feasible-only scopes drop infeasible signals (house: REJECTED, never a position).

Rules (proxies for the AI's choice):
  FC   first-come; same-moment ties: coin priority (BTC, ETH, SOL, DOGE, LTC, BCH), then shorter tf
  LTF  first-come; same-moment ties: longer tf first, then coin priority
  SW   switch to any new signal (close the held position at the new entry bar's open, open the new one);
       a new signal on the held coin and side = hold
  SWH  switch only when the new signal's tf is longer than the held position's tf
"""
import os
import sys
import time

sys.path[:0] = ['/root/.local/lib/python3.11/site-packages', '/home/user/crypto-bot-research']
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from multiprocessing import Pool  # noqa: E402

COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")
TFS = ("15m", "30m", "1h", "4h")
TF_MIN = (15, 30, 60, 240)
FEE, SLIP = 0.0005, 0.0002
F_BAR15 = 0.0001 * 15 / 480.0
SCOPES = {
    "A": ((0, 1), True, ("FC", "LTF", "SW", "SWH")),
    "ALL": ((0, 1, 2, 3), True, ("FC", "LTF", "SW", "SWH")),
    "HI": ((2, 3), True, ("FC", "LTF", "SW", "SWH")),
    "ALLINF": ((0, 1, 2, 3), False, ("FC", "SWH")),
    "T15": ((0,), True, ("FC",)), "T30": ((1,), True, ("FC",)), "T1h": ((2,), True, ("FC",)), "T4h": ((3,), True, ("FC",)),
}
_G = {}


def load(core_dir, outc_dir):
    ts15 = np.load(os.path.join(core_dir, "sig_15m_BTCUSD.npz"))["ts"]
    o15 = [np.load(os.path.join(core_dir, f"sig_15m_{c}.npz"))["o"] for c in COINS]
    tabs, names = {}, set()
    for ti, tf in enumerate(TFS):
        for ci, c in enumerate(COINS):
            z = np.load(os.path.join(outc_dir, f"out_{tf}_{c}.npz"))
            d = {k: z[k] for k in z.files}
            tabs[(ti, ci)] = d
            names |= {k[3:] for k in d if k.startswith("m__")}
    _G.update(ts15=ts15, o15=o15, tabs=tabs, names=sorted(names))


def strategy_table(name):
    parts = []
    for (ti, ci), d in _G["tabs"].items():
        k = "m__" + name
        if k not in d:
            continue
        p = d[k]
        parts.append(pd.DataFrame({
            "e": d["e"][p], "tf": ti, "coin": ci, "side": d["side"][p], "R": d["R"][p], "gross": d["gross"][p],
            "x": d["x"][p], "feas": d["feasible"][p], "lev": np.where(d["lev"][p] > 0, d["lev"][p], 20),
            "fill": d["fill"][p], "risk": d["risk"][p], "reason": d["reason"][p]}))
    t = pd.concat(parts, ignore_index=True)
    return t


def run_account(t, rule):
    """t: DataFrame of the scope's signals. Returns (trades dict of lists, blocked dict of lists, counters)."""
    if rule in ("FC", "SW"):
        t = t.sort_values(["e", "coin", "tf"], kind="mergesort")
    else:
        t = t.assign(ntf=-t["tf"]).sort_values(["e", "ntf", "coin"], kind="mergesort")
    E, TF, CO, SD, R, X = (t[c].tolist() for c in ("e", "tf", "coin", "side", "R", "x"))
    G, LV, FI, RI = (t[c].tolist() for c in ("gross", "lev", "fill", "risk"))
    ts15, o15 = _G["ts15"], _G["o15"]
    tr = {k: [] for k in ("e", "xe", "R", "gross", "tf", "coin", "switched_out", "alone_R", "nblk_low", "nblk_all",
                          "hold_min")}
    bl = {k: [] for k in ("e", "tf", "R", "held_tf", "tie")}
    n_switch = n_confirm = 0
    h = None   # held: [idx, e, x, tf, coin, side, nblk_low, nblk_all]

    def close_alone(hh):
        j = hh[0]
        tr["e"].append(hh[1]); tr["xe"].append(hh[2]); tr["R"].append(R[j]); tr["gross"].append(G[j])
        tr["tf"].append(hh[3]); tr["coin"].append(hh[4]); tr["switched_out"].append(False); tr["alone_R"].append(R[j])
        tr["nblk_low"].append(hh[6]); tr["nblk_all"].append(hh[7])
        tr["hold_min"].append((ts15[hh[2]] - ts15[hh[1]]) / 6e10 + 15.0)

    def close_at(hh, k):
        j = hh[0]
        side, fill, lev = hh[5], FI[j], LV[j]
        raw = o15[hh[4]][k]
        px = raw * (1 - side * SLIP)
        roe = lev * (side * (px / fill - 1) - FEE * (1 + px / fill) - F_BAR15 * (k - hh[1]))
        roe = max(roe, -1.0)
        r_ = roe * fill / (lev * RI[j])
        raw0 = fill / (1 + side * SLIP)
        tr["e"].append(hh[1]); tr["xe"].append(k - 1); tr["R"].append(r_); tr["gross"].append(side * (raw - raw0) / RI[j])
        tr["tf"].append(hh[3]); tr["coin"].append(hh[4]); tr["switched_out"].append(True); tr["alone_R"].append(R[j])
        tr["nblk_low"].append(hh[6]); tr["nblk_all"].append(hh[7])
        tr["hold_min"].append((ts15[k] - ts15[hh[1]]) / 6e10)

    for j in range(len(E)):
        e = E[j]
        if h is not None and e > h[2]:
            close_alone(h)
            h = None
        if h is None:
            h = [j, e, X[j], TF[j], CO[j], SD[j], 0, 0]
            continue
        # busy
        tie = e == h[1]
        sw = False
        if not tie:
            same = CO[j] == h[4] and SD[j] == h[5]
            if rule == "SW" and not same:
                sw = True
            elif rule == "SWH" and TF[j] > h[3] and not same:
                sw = True
            elif same and rule in ("SW", "SWH"):
                n_confirm += 1
        if sw:
            close_at(h, e)
            n_switch += 1
            h = [j, e, X[j], TF[j], CO[j], SD[j], 0, 0]
            continue
        bl["e"].append(e); bl["tf"].append(TF[j]); bl["R"].append(R[j]); bl["held_tf"].append(h[3]); bl["tie"].append(tie)
        h[7] += 1
        if TF[j] <= 1:
            h[6] += 1
    if h is not None:
        close_alone(h)
    return tr, bl, dict(n_switch=n_switch, n_confirm=n_confirm)


def job(name):
    t_all = strategy_table(name)
    out = {}
    for sc, (tfs, feas_only, rules) in SCOPES.items():
        t = t_all[t_all["tf"].isin(tfs)]
        n_infeas = int((~t["feas"]).sum())
        if feas_only:
            t = t[t["feas"]]
        if not len(t):
            continue
        for rule in rules:
            tr, bl, cnt = run_account(t, rule)
            key = f"{sc}|{rule}"
            for k, v in tr.items():
                out[f"{key}|tr|{k}"] = np.asarray(v)
            for k, v in bl.items():
                out[f"{key}|bl|{k}"] = np.asarray(v)
            out[f"{key}|cnt"] = np.array([len(t), n_infeas, cnt["n_switch"], cnt["n_confirm"]]
                                         + [int((t["tf"] == k).sum()) for k in range(4)])
    return name, out


def init(core_dir, outc_dir):
    load(core_dir, outc_dir)


if __name__ == "__main__":
    core_dir, outc_dir, res_dir = sys.argv[1:4]
    procs = int(sys.argv[4]) if len(sys.argv) > 4 else 4
    only = sys.argv[5].split(",") if len(sys.argv) > 5 else None
    os.makedirs(res_dir, exist_ok=True)
    load(core_dir, outc_dir)
    names = [n for n in _G["names"] if only is None or n in only]
    t0 = time.time()
    with Pool(procs, initializer=init, initargs=(core_dir, outc_dir)) as p:
        for name, out in p.imap_unordered(job, names):
            np.savez_compressed(os.path.join(res_dir, name.replace(":", "__") + ".npz"), **out)
            print(name, f"{time.time() - t0:.0f}s", flush=True)
