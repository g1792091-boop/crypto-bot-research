"""PREREG2_AMEND1.md: P30 = the rules of P (PREREG_AMEND1) on closed 30-minute signal bars (EMA21 > EMA52, RSI26 > 50, ROC9
crossing 0 up, ROC9 > 0 on the last closed 1h or 4h bar; shorts mirrored; warm-up 200 30m bars and 60 1h / 4h bars), entry at
the next 1m open, the same entry blocks, 30x, net ROE -50 % stop, the same ladder, one position over the six coins, cost
0.124 % round trip, margin 40 %. Reported next to P (15m) on October, the last 19 days, 2020-03 .. 2024-12 and 2025-01 ..
2026-09, with the coin-flip twin of the first study (2,000 draws, seed 20261024) and stops at net ROE -30 / -40 / -50 / -60 %.

    python3 -I frrun.py build     (once: OUT/rows.pkl, for P)
    python3 -I frp30.py           -> the "P30" part of research/friendroc/results2.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frcore import _ind
from frrun import ROWS, MARGIN, take, rnd, coin_flip
from frloss import walk2, acct, PER, LEV, COST, FL, STEP, GAP
import hashlib
from types import SimpleNamespace

TFK = {"15m": 15, "30m": 30}
STOPS30 = (-0.30, -0.40, -0.50, -0.60)


def p_signals(coin, tf):
    """P's signal rows on the coin's tf bars (frcore.coin_signals' P on 15m): t (bar close = entry minute), coin, side, e."""
    k = TFK[tf]
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
    H = {}
    for htf, kh in (("1h", 60), ("4h", 240)):
        dh = bars(coin, htf)
        r = _ind(dh.close.to_numpy(float))["roc"]
        hc = dh.ts.to_numpy(np.int64) + kh * MIN
        j = np.searchsorted(hc, bc, side="right") - 1                # the last one closed at (or before) the bar close
        H[htf] = np.where(j >= WARMH, r[np.maximum(j, 1)], np.nan)
    with np.errstate(invalid="ignore"):
        L = warm & up & ((H["1h"] > 0) | (H["4h"] > 0))
        S = warm & dn & ((H["1h"] < 0) | (H["4h"] < 0))
    g = grid(coin)
    e = (bc - T0) // MIN
    i = np.flatnonzero((L | S) & (e < g["n"]))
    return pd.DataFrame({"t": bc[i], "coin": COINS.index(coin), "side": np.where(L[i], 1, -1), "e": e[i]})


def outcomes(R, roe_stop, sides=("own",)):
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
                    es = R.e.to_numpy(np.int64)[m]
                    a = walk2(o, h, l, c, cumf, es, side, LEV, COST, FL, STEP, GAP, np.full(m.sum(), np.inf), roe_stop, g["n"])
                    r[m], k[m], w[m] = a[0], a[1], a[2]
        out[sn] = {"r": r, "k": k, "why": w}
    return out


def weekdays(a, z):
    d = pd.date_range(pd.Timestamp(a + KST, unit="ms").normalize(), pd.Timestamp(z - 1 + KST, unit="ms").normalize())
    return int((d.dayofweek < 5).sum())


def report(R, O, twin=True):
    t = R.t.to_numpy(np.int64)
    every = np.ones(len(R), bool)
    out = {}
    for pn, (a, z) in PER.items():
        x = acct(t, O["own"]["k"], O["own"]["r"], O["own"]["why"], every, a, z, keep=True)
        idx = x.pop("_idx")
        x["per_weekday"] = rnd(x["n"] / weekdays(a, z), 2)
        if twin and x["n"]:
            m = (t >= a) & (t < z)
            roe = LEV * O["own"]["r"][idx]
            growth = rnd(np.log1p(np.maximum(MARGIN * roe, -1 + 1e-12)).sum(), 3)
            tw = coin_flip(SimpleNamespace(t=t), m, O["own"], O["opp"], LEV, roe.mean(), growth)
            x["twin_pct_below"] = tw["pct_below"]
            x["twin_roe_pct_median"] = tw["roe_pct_median"]
        out[pn] = x
    return out


def main():
    for f in ("PREREG2.md", "PREREG2_AMEND1.md"):
        want = open(os.path.join(RES_DIR, f + ".sha256")).read().split()[0]
        assert hashlib.sha256(open(os.path.join(RES_DIR, f), "rb").read()).hexdigest() == want, f"{f} changed after it was frozen"
    A = pd.read_pickle(ROWS)
    # the signal code against the study's own P rows (15m), before using it on 30m
    P15 = pd.concat([p_signals(c, "15m") for c in COINS], ignore_index=True)
    P15 = P15.iloc[np.lexsort((P15.coin.to_numpy(), P15.t.to_numpy()))].reset_index(drop=True)
    ref = A[A.P].reset_index(drop=True)
    assert len(P15) == len(ref) and (P15.t.to_numpy() == ref.t.to_numpy()).all() and (P15.side.to_numpy() == ref.side.to_numpy()).all()
    # P30
    R = pd.concat([p_signals(c, "30m") for c in COINS], ignore_index=True)
    R = R.iloc[np.lexsort((R.coin.to_numpy(), R.t.to_numpy()))].reset_index(drop=True)
    R["block"] = [blocked(int(x)) for x in R.t.to_numpy()]
    print("P30 signal rows", len(R), R.block.value_counts().to_dict(), flush=True)
    R = R[R.block == ""].reset_index(drop=True)
    O = outcomes(R, -0.5, ("own", "opp"))
    res = {"amend1_sha256": open(os.path.join(RES_DIR, "PREREG2_AMEND1.md.sha256")).read().split()[0],
           "signal_rows_free": int(len(R)), "P30": report(R, O)}
    # P (15m) with the same columns (its twin from results.json)
    Af = A[A.P & (A.block == "")].reset_index(drop=True)
    OP = {"own": {q: Af[f"L30_c042_own_{q}"].to_numpy() for q in ("r", "k", "why")},
          "opp": {q: Af[f"L30_c042_opp_{q}"].to_numpy() for q in ("r", "k", "why")}}
    old = json.load(open(os.path.join(RES_DIR, "results.json")))["variants"]["P"]["c042"]
    rp = report(Af, OP, twin=False)
    for pn in PER:
        rp[pn]["twin_pct_below"] = old[pn]["twin"]["pct_below"]
        rp[pn]["twin_roe_pct_median"] = old[pn]["twin"]["roe_pct_median"]
        assert rp[pn]["n"] == old[pn]["n"]
    res["P"] = rp
    # October trades of P30
    a, z = PER["oct2026"]
    t = R.t.to_numpy(np.int64)
    idx = take(t, O["own"]["k"], (t >= a) & (t < z))
    res["oct_trades"] = [{"entry_kst": str(pd.Timestamp(int(R.t.iat[i]) + KST, unit="ms"))[:16], "coin": COINS[int(R.coin.iat[i])][:-4],
                          "side": "롱" if R.side.iat[i] > 0 else "숏", "roe_pct": rnd(LEV * O["own"]["r"][i] * 100, 1),
                          "exit": REASONS[int(O["own"]["why"][i])], "minutes": int(O["own"]["k"][i]) + 1} for i in idx]
    # stops
    res["stops"] = {}
    for rs in STOPS30:
        Os = O if rs == -0.5 else outcomes(R, rs)
        row = report(R, Os, twin=False)
        res["stops"][f"ROE {int(round(rs * 100))}%"] = row
    base = res["stops"]["ROE -50%"]
    for nm, row in res["stops"].items():
        row["better_both_halves"] = bool(row["select"]["roe_pct"] > base["select"]["roe_pct"] and row["confirm"]["roe_pct"] > base["confirm"]["roe_pct"])
    p30 = res["P30"]
    res["verdict"] = {"both_halves_positive": bool(p30["select"]["roe_pct"] > 0 and p30["confirm"]["roe_pct"] > 0),
                      "confirm_twin_975": bool(p30["confirm"]["twin_pct_below"] >= 0.975)}
    for nm, d in (("P", res["P"]), ("P30", p30), *res["stops"].items()):
        print(nm, " | ".join(f"{pn[:4]} n{v['n']} {v['per_weekday']}/d {v.get('wins')}W{v.get('losses')}L w{v.get('win')} "
                             f"aw{v.get('avg_win_pct')}/al{v.get('avg_loss_pct')} be{v.get('breakeven_win')} roe{v.get('roe_pct')} "
                             f"x{v.get('mult40')} tw{v.get('twin_pct_below')}" for pn, v in d.items() if isinstance(v, dict)), flush=True)
    print(res["verdict"], flush=True)
    for x in res["oct_trades"]:
        if x["roe_pct"] <= 0:
            print(x)
    path = os.path.join(RES_DIR, "results2.json")
    out = json.load(open(path))
    out["P30"] = res
    json.dump(out, open(path, "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
