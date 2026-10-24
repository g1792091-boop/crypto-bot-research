"""PREREG4.md: the friend's rules on 15m / 30m / 1h / 4h signal bars (higher bars 1h|4h, 1h|4h, 4h|1d, 1d|3d), 30x, net ROE
stops -50 / -75 / -90 %, ladders L10 (10 / 5), L20 (20 / 10), L30 (30 / 10), L50 (50 / 25) with the trigger 2 % above each lock,
filters none / F4 (4h ADX14 < 20 skipped) / V (signal-bar volume above 0.64 x the previous 20 bars' mean skipped): 144 settings,
one position over the six coins, the entry blocks, cost 0.124 % round trip, margin 40 %. The setting with the best per-trade net ROE
on 2020-03 .. 2024-12 (600 trades or more) is read once on 2025-01 .. 2026-09 with the coin-flip twin; the owners' goal numbers
(win rate, net ROE per trade, entries per weekday, months from 1 at margin 40 %) for it and for P.

    python3 -I frrun.py build     (once: OUT/rows.pkl, for the P check)
    python3 -I frfamily.py        -> research/friendroc/results4.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frcore import _ind
from frrun import ROWS, MARGIN, take, rnd, coin_flip
from frloss import table, PER, LEV, COST, warnings_off
from frdeep import walk3, per_stats
from frp30 import p_signals, weekdays
import hashlib
from types import SimpleNamespace

TF_MIN.setdefault("1d", 1440)
TF_MIN.setdefault("3d", 4320)
TFS = {"15m": ("1h", "4h"), "30m": ("1h", "4h"), "1h": ("4h", "1d"), "4h": ("1d", "3d")}
STOPS = (-0.50, -0.75, -0.90)
LADDERS = {"L10": (0.10, 0.05), "L20": (0.20, 0.10), "L30": (0.30, 0.10), "L50": (0.50, 0.25)}
FILTERS = ("none", "F4", "V")
GAP = 0.02
MIN_SELECT_N = 600
VCUT = 0.64
COST060 = COSTS["c060"]
FIRST_MONTH = "2020-03"


def tf_signals(coin, tf):
    """The friend's rules on the coin's tf bars with TFS[tf] as the higher bars: t (bar close = entry minute), coin, side, e,
    the signal bar's volume over the previous 20 bars' mean (vr) and the last closed 4h ADX14 of the trend judge files."""
    k = TF_MIN[tf]
    df = bars(coin, tf)
    c = df.close.to_numpy(float)
    I = _ind(c)
    bc = df.ts.to_numpy(np.int64) + k * MIN
    with np.errstate(invalid="ignore"):
        e21, e52, rsi, roc = I["e21"], I["e52"], I["rsi"], I["roc"]
        rocp = prev(roc)
        up = (e21 > e52) & (rsi > 50) & (rocp <= 0) & (roc > 0)
        dn = (e21 < e52) & (rsi < 50) & (rocp >= 0) & (roc < 0)
    warm = np.arange(len(c)) >= WARM15
    H = []
    for htf in TFS[tf]:
        dh = bars(coin, htf)
        r = _ind(dh.close.to_numpy(float))["roc"]
        hc = dh.ts.to_numpy(np.int64) + TF_MIN[htf] * MIN
        j = np.searchsorted(hc, bc, side="right") - 1                # the last one closed at (or before) the bar close
        H.append(np.where(j >= WARMH, r[np.maximum(j, 1)], np.nan))
    with np.errstate(invalid="ignore"):
        L = warm & up & ((H[0] > 0) | (H[1] > 0))
        S = warm & dn & ((H[0] < 0) | (H[1] < 0))
    v = df.volume.to_numpy(float)
    vm = pd.Series(v).rolling(20).mean().shift(1).to_numpy()
    g = grid(coin)
    e = (bc - T0) // MIN
    i = np.flatnonzero((L | S) & (e < g["n"]))
    t = bc[i]
    Z = np.load(os.path.join(NL.JUDGE, f"{coin}.npz"))
    tc = Z["4h_tclose"]
    jx = np.searchsorted(tc, t, side="right") - 1
    ok = (jx >= 0) & (t - tc[np.maximum(jx, 0)] < 2 * 240 * MIN)
    with np.errstate(all="ignore"):
        vr = v[i] / vm[i]
    return pd.DataFrame({"t": t, "coin": COINS.index(coin), "side": np.where(L[i], 1, -1), "e": e[i], "vr": vr,
                         "adx4h": np.where(ok, Z["4h_adx"].astype(float)[np.maximum(jx, 0)], np.nan)})


def signals(tf):
    R = pd.concat([tf_signals(c, tf) for c in COINS], ignore_index=True)
    R = R.iloc[np.lexsort((R.coin.to_numpy(), R.t.to_numpy()))].reset_index(drop=True)
    R["block"] = [blocked(int(x)) for x in R.t.to_numpy()]
    return R


def outcomes(R, stop, fl, step, cost=COST, sides=("own",)):
    bt = grid("BTCUSDT")
    bc_, bo_ = (np.ascontiguousarray(bt[x], dtype=np.float64) for x in ("c", "o"))
    out = {}
    for sn in sides:
        r = np.zeros(len(R)); k = np.zeros(len(R), np.int64); w = np.zeros(len(R), np.int8)
        for ci in range(6):
            g = grid(COINS[ci])
            cumf = np.cumsum(g["fund"])
            o, h, l, c = (np.ascontiguousarray(g[x], dtype=np.float64) for x in ("o", "h", "l", "c"))
            for side in (1, -1):
                m = ((R.coin == ci) & (R.side * (1 if sn == "own" else -1) == side)).to_numpy()
                if m.any():
                    a = walk3(o, h, l, c, cumf, R.e.to_numpy(np.int64)[m], side, LEV, cost, fl, step, GAP, stop, 9.0, 0.0, 0,
                              np.zeros(1, bool), False, bc_, bo_, 0.0, g["n"])
                    r[m], k[m], w[m] = a
        out[sn] = {"r": r, "k": k, "why": w}
    return out


def filt(R, f):
    if f == "F4":
        return ~(R.adx4h.to_numpy() < 20)
    if f == "V":
        return ~(R.vr.to_numpy() > VCUT)
    return np.ones(len(R), bool)


def goal_numbers(R, O, use):
    """The owners' goal numbers: per period entries per weekday and the median hold; months from 1 at margin 40 %."""
    t = R.t.to_numpy(np.int64)
    out = table(t, O["k"], O["r"], O["why"], use)
    for pn, (a, z) in PER.items():
        idx = take(t, O["k"], use & (t >= a) & (t < z))
        out[pn]["per_weekday"] = rnd(len(idx) / weekdays(a, z), 2)
        out[pn]["hold_min_median"] = int(np.median(O["k"][idx] + 1)) if len(idx) else None
    idx = take(t, O["k"], use & (t >= ms(FIRST_MONTH + "-01")))
    x = np.maximum(MARGIN * LEV * O["r"][idx], -1.0)
    mon = np.asarray(pd.to_datetime(t[idx] + KST, unit="ms").strftime("%Y-%m"))
    mult = {}
    for q in pd.period_range(FIRST_MONTH, "2026-10", freq="M").strftime("%Y-%m"):
        mult[q] = float(np.prod(1 + x[mon == q])) if (mon == q).any() else 1.0
    full = np.array([v for q, v in mult.items() if q <= "2026-09"])
    out["months"] = {"n": int(len(full)), "median": rnd(np.median(full), 3), "share_above_1": rnd((full > 1).mean(), 3),
                     "x4_or_more": int((full >= 4).sum()), "worst": rnd(full.min(), 3), "best": rnd(full.max(), 3),
                     "oct2026": rnd(mult["2026-10"], 3)}
    return out


def main():
    want = open(os.path.join(RES_DIR, "PREREG4.md.sha256")).read().split()[0]
    sha = hashlib.sha256(open(os.path.join(RES_DIR, "PREREG4.md"), "rb").read()).hexdigest()
    assert sha == want, "PREREG4.md changed after it was frozen"
    res = {"prereg4_sha256": sha, "data_end_utc": str(pd.Timestamp(DATA_END, unit="ms"))}
    SIG, OUTS = {}, {}
    for tf in TFS:
        R = signals(tf)
        if tf in ("15m", "30m"):                                     # the same rows as P / P30 (frp30.p_signals)
            ref = pd.concat([p_signals(c, tf) for c in COINS], ignore_index=True)
            ref = ref.iloc[np.lexsort((ref.coin.to_numpy(), ref.t.to_numpy()))].reset_index(drop=True)
            assert len(ref) == len(R) and (ref.t.to_numpy() == R.t.to_numpy()).all() and (ref.side.to_numpy() == R.side.to_numpy()).all(), tf
        R = R[R.block == ""].reset_index(drop=True)
        SIG[tf] = R
        for st in STOPS:
            for ln, (fl, step) in LADDERS.items():
                OUTS[(tf, st, ln)] = outcomes(R, st, fl, step)["own"]
        print("tf", tf, "free signals", len(R), flush=True)
    # P exactly as the first study (results.json)
    A = pd.read_pickle(ROWS)
    A = A[A.P & (A.block == "")].reset_index(drop=True)
    O = OUTS[("15m", -0.50, "L10")]
    assert np.array_equal(O["k"], A["L30_c042_own_k"].to_numpy()) and np.allclose(O["r"], A["L30_c042_own_r"].to_numpy(), atol=1e-15)
    bnd = np.array([PER[pn] for pn in PER], np.int64)
    keys = list(PER)
    isel, icf = keys.index("select"), keys.index("confirm")
    rows = []
    for (tf, st, ln), O in OUTS.items():
        R = SIG[tf]
        t = R.t.to_numpy(np.int64)
        ext = t + (O["k"].astype(np.int64) + 1) * MIN
        roe = LEV * O["r"]
        for f in FILTERS:
            S = per_stats(t, ext, roe, filt(R, f), bnd)
            row = {"tf": tf, "stop": st, "ladder": ln, "filter": f}
            for j, pn in enumerate(keys):
                n, w, sm, gr = S[j]
                row[pn] = {"n": int(n), "wins": int(w), "win": rnd(w / n, 4) if n else None, "roe_pct": rnd(sm / n * 100, 3) if n else None,
                           "mult40": rnd(np.exp(gr), 3)}
            rows.append(row)
    ok = [r for r in rows if r["select"]["n"] >= MIN_SELECT_N]
    ok.sort(key=lambda r: -r["select"]["roe_pct"])
    pick = ok[0]
    res["settings"] = len(rows)
    res["eligible"] = len(ok)
    res["both_halves_positive"] = [r for r in rows if (r["select"]["roe_pct"] or -1) > 0 and (r["confirm"]["roe_pct"] or -1) > 0]
    res["top10_select"] = ok[:10]
    res["best_per_tf"] = {tf: max((r for r in ok if r["tf"] == tf), key=lambda r: r["select"]["roe_pct"]) for tf in TFS if any(r["tf"] == tf for r in ok)}
    res["all"] = rows
    print("eligible", len(ok), "both halves positive", len(res["both_halves_positive"]), flush=True)
    for r in ok[:10]:
        print(" ", r["tf"], r["stop"], r["ladder"], r["filter"], {pn: (r[pn]["n"], r[pn]["win"], r[pn]["roe_pct"], r[pn]["mult40"]) for pn in keys}, flush=True)
    for tf, r in res["best_per_tf"].items():
        print(" best", tf, r["stop"], r["ladder"], r["filter"], {pn: (r[pn]["n"], r[pn]["win"], r[pn]["roe_pct"]) for pn in keys}, flush=True)

    # the pick: full numbers, twin, the 0.16 % cost, goal numbers; P next to it
    tf, st, ln, f = pick["tf"], pick["stop"], pick["ladder"], pick["filter"]
    R = SIG[tf]
    t = R.t.to_numpy(np.int64)
    fl, step = LADDERS[ln]
    O2 = outcomes(R, st, fl, step, sides=("own", "opp"))
    use = filt(R, f)
    det = goal_numbers(R, O2["own"], use)
    for pn in ("select", "confirm", "oct2026"):
        a, z = PER[pn]
        m = use & (t >= a) & (t < z)
        idx = take(t, O2["own"]["k"], m)
        roe = LEV * O2["own"]["r"][idx]
        growth = np.log1p(np.maximum(MARGIN * roe, -1 + 1e-12)).sum()
        det[pn]["twin"] = coin_flip(SimpleNamespace(t=t), m, O2["own"], O2["opp"], LEV, roe.mean(), growth)
    O6 = outcomes(R, st, fl, step, cost=COST060)["own"]
    c6 = table(t, O6["k"], O6["r"], O6["why"], use)
    det["cost016"] = {pn: {"n": v["n"], "roe_pct": v.get("roe_pct")} for pn, v in c6.items()}
    det["verdict"] = {"select_positive": bool(det["select"]["roe_pct"] > 0), "confirm_positive": bool(det["confirm"]["roe_pct"] > 0),
                      "confirm_twin_975": bool(det["confirm"]["twin"]["pct_below"] >= 0.975)}
    det["verdict"]["edge"] = all(det["verdict"].values())
    det["verdict"]["cost016_both_positive"] = bool((c6["select"]["roe_pct"] or -1) > 0 and (c6["confirm"]["roe_pct"] or -1) > 0)
    det["setting"] = {"tf": tf, "higher": TFS[tf], "stop": st, "ladder": ln, "first_lock": fl, "step": step, "filter": f}
    res["pick"] = det
    RP = SIG["15m"]
    res["P_goal"] = goal_numbers(RP, OUTS[("15m", -0.50, "L10")], np.ones(len(RP), bool))
    print("PICK", det["setting"], {pn: (det[pn]["n"], det[pn].get("win"), det[pn].get("roe_pct"), det[pn].get("avg_win_pct"), det[pn].get("avg_loss_pct"), det[pn].get("mult40"), det[pn].get("per_weekday")) for pn in PER}, flush=True)
    print("PICK twin", {pn: det[pn]["twin"]["pct_below"] for pn in ("select", "confirm", "oct2026")}, "cost016", det["cost016"], flush=True)
    print("PICK months", det["months"], "verdict", det["verdict"], flush=True)
    print("P months", res["P_goal"]["months"], flush=True)
    json.dump(res, open(os.path.join(RES_DIR, "results4.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
