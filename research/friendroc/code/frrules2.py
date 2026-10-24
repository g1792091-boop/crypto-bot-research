"""PREREG14.md: the owners' two rules as they gave them on 10/24 night.
R1: 15m EMA21 > EMA52, RSI26 > 50, ROC9 crossing 0 upward, and on the last closed 1h bar EMA21 > EMA52 and RSI26 > 50 (shorts mirrored).
R2: 15m EMA21 crossing EMA52 upward (golden cross) with RSI26 > 50, and on the last closed 1h bar EMA21 > EMA52 (shorts mirrored).
35x, the screen's -20 % stop, the ladder 12 -> 10 then 5 % steps, one position, the entry blocks, margin 40 %, the TetherMax payback
90 %; nothing else. For reference: a fixed +10 % take-profit, and the four bigger-trend conditions added.

    python3 -I frrules2.py        -> research/friendroc/results19.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frcore import _ind
from frrun import rnd
from frloss import PER, FL
from frbracket import detail, run as run_fixed
from frtrend4 import trend_columns, conditions
from frladder35 import outcomes, exits, FEE_ROE
from frhtrend import raw15
from frhtrend2 import add_rsi
import hashlib

STOP = -0.20 - FEE_ROE                                     # the screen's -20 % as net ROE


def coin_rules(coin):
    """Both rules' signal rows of one coin: {rule: DataFrame t, coin, side, e, adx4h}."""
    df = bars(coin, "15m")
    c = df.close.to_numpy(float)
    I = _ind(c)
    bc = df.ts.to_numpy(np.int64) + 15 * MIN
    e21, e52, rsi, roc = I["e21"], I["e52"], I["rsi"], I["roc"]
    e21p, e52p, rocp = prev(e21), prev(e52), prev(roc)
    dh = bars(coin, "1h")
    Ih = _ind(dh.close.to_numpy(float))
    hc = dh.ts.to_numpy(np.int64) + 60 * MIN
    j = np.searchsorted(hc, bc, side="right") - 1                    # the last 1h bar closed at (or before) the 15m close
    ok = j >= WARMH
    jj = np.maximum(j, 1)
    h_ema = np.where(ok, Ih["e21"][jj] - Ih["e52"][jj], np.nan)
    h_rsi = np.where(ok, Ih["rsi"][jj] - 50, np.nan)
    warm = np.arange(len(c)) >= WARM15
    with np.errstate(invalid="ignore"):
        L = {"R1": (e21 > e52) & (rsi > 50) & (rocp <= 0) & (roc > 0) & (h_ema > 0) & (h_rsi > 0),
             "R2": (e21p <= e52p) & (e21 > e52) & (rsi > 50) & (h_ema > 0)}
        S = {"R1": (e21 < e52) & (rsi < 50) & (rocp >= 0) & (roc < 0) & (h_ema < 0) & (h_rsi < 0),
             "R2": (e21p >= e52p) & (e21 < e52) & (rsi < 50) & (h_ema < 0)}
    g = grid(coin)
    e = (bc - T0) // MIN
    Z = np.load(os.path.join(NL.JUDGE, f"{coin}.npz"))
    tc = Z["4h_tclose"]
    out = {}
    for rn in ("R1", "R2"):
        i = np.flatnonzero(warm & (L[rn] | S[rn]) & (e < g["n"]))
        t = bc[i]
        jx = np.searchsorted(tc, t, side="right") - 1
        okx = (jx >= 0) & (t - tc[np.maximum(jx, 0)] < 2 * 240 * MIN)
        out[rn] = pd.DataFrame({"t": t, "coin": COINS.index(coin), "side": np.where(L[rn][i], 1, -1), "e": e[i],
                                "adx4h": np.where(okx, Z["4h_adx"].astype(float)[np.maximum(jx, 0)], np.nan)})
    return out


def main():
    want = open(os.path.join(RES_DIR, "PREREG14.md.sha256")).read().split()[0]
    sha = hashlib.sha256(open(os.path.join(RES_DIR, "PREREG14.md"), "rb").read()).hexdigest()
    assert sha == want, "PREREG14.md changed after it was frozen"
    per_coin = [coin_rules(c) for c in COINS]
    res = {"prereg14_sha256": sha, "rules": {}}
    # check: R1 is the friend's 15m signal (frhtrend.raw15) with 1h EMA and RSI26 on its side
    A = add_rsi(pd.concat([raw15(c) for c in COINS], ignore_index=True))
    with np.errstate(invalid="ignore"):
        A = A[(A.ema_1h.to_numpy() > 0) & (A.rsi_1h.to_numpy() > 0)]
    A = A.iloc[np.lexsort((A.coin.to_numpy(), A.t.to_numpy()))]
    for rn in ("R1", "R2"):
        R = pd.concat([pc[rn] for pc in per_coin], ignore_index=True)
        R = R.iloc[np.lexsort((R.coin.to_numpy(), R.t.to_numpy()))].reset_index(drop=True)
        if rn == "R1":
            same = len(R) == len(A) and (R.t.to_numpy() == A.t.to_numpy()).all() and (R.side.to_numpy() == A.side.to_numpy()).all()
            print("R1 == raw15 with 1h EMA and RSI26:", same, len(R), len(A), flush=True)
            assert same
        R["block"] = [blocked(int(x)) for x in R.t.to_numpy()]
        n_all = len(R)
        R = trend_columns(R[R.block == ""].reset_index(drop=True))
        every = np.ones(len(R), bool)
        four = np.logical_and.reduce(list(conditions(R).values()))
        doge = (R.coin == COINS.index("DOGEUSDT")).to_numpy()
        O = outcomes(R, STOP, FL)
        Oo = outcomes(R, STOP, FL, flip=True)
        OF = run_fixed(R, 0.10, -0.20)
        OFo = run_fixed(R, 0.10, -0.20, flip=True)
        rr = {"signals_all": n_all, "signals_unblocked": len(R), "four_pass": rnd(float(four.mean()), 4), "runs": {}}
        for an, OO, OOo, use in (("계단 · 손절 −20", O, Oo, every), ("고정 +10 · 손절 −20", OF, OFo, every),
                                 ("계단 · 손절 −20 + 네 조건", O, Oo, four)):
            d = detail(R, OO, use, OOo)
            if "why" in OO:
                d["exits"] = exits(R, OO, use)
            d["doge"] = detail(R, OO, use & doge)
            if an == "계단 · 손절 −20":
                v = {"select_positive": bool(d["select"]["roe_pct"] > 0), "confirm_positive": bool(d["confirm"]["roe_pct"] > 0),
                     "confirm_twin_975": bool(d["confirm"].get("twin") is not None and d["confirm"]["twin"] >= 0.975)}
                v["earns"] = all(v.values())
                d["verdict"] = v | {"text": "과거 기록상 버는 구조" if v["earns"] else "아님"}
            rr["runs"][an] = d
            print(f"== {rn} · {an} (signals {len(R)}, four pass {rr['four_pass']})", flush=True)
            for p in PER:
                x = d[p]
                print(f"  {p:8s} n{x['n']} {x['per_weekday']}/d w{x['win']} be{x['breakeven_win']} aw{x['avg_win_pct']} al{x['avg_loss_pct']} "
                      f"roe{x['roe_pct']} (no pb {x['roe_pct_no_payback']}) x40 {x['mult40']} dd{x['maxdd40']} twin {x.get('twin')} | {d.get('exits', {}).get(p)}",
                      flush=True)
            print("  months", d["months"], "goal90", d["goal90"], flush=True)
            print("  doge", {p: (d["doge"][p]["n"], d["doge"][p]["win"], d["doge"][p]["roe_pct"], d["doge"][p]["mult40"]) for p in PER}, flush=True)
            if "verdict" in d:
                print("  verdict", d["verdict"], flush=True)
        res["rules"][rn] = rr
    json.dump(res, open(os.path.join(RES_DIR, "results19.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
