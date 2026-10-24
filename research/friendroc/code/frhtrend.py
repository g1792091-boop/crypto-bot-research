"""PREREG12.md: enter when the 15m trend and the 1h OR 4h trend agree (EMA21 vs EMA52 on the last closed higher bar). E1 swaps the
1h / 4h ROC9 confirmation of the friend's 15m signal for that trend agreement; E2 keeps the ROC9 confirmation and adds it. Both with
PREREG11's B: the four bigger-trend conditions, 35x, the screen's -20 % stop, the ladder 12 -> 10 then 5 % steps, one position, the
entry blocks, margin 40 %, the TetherMax payback 90 %. For reference: the net -50 % stop, and both without the four conditions.

    python3 -I frhtrend.py        -> research/friendroc/results17.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frcore import _ind
from frrun import rnd
from frloss import PER, FL
from frfamily import signals
from frbracket import detail
from frtrend4 import trend_columns, conditions
from frladder35 import outcomes, exits, FEE_ROE
import hashlib

STOPS = {"손절 화면 −20": -0.20 - FEE_ROE, "손절 순ROE −50": -0.50}


def raw15(coin):
    """Every 15m friend signal bar before the higher-bar check (frfamily.tf_signals without its last filter), with the side-signed
    ROC9 and EMA21 - EMA52 of the last closed 1h and 4h bars, and the 4h ADX14 of the trend judge files."""
    df = bars(coin, "15m")
    c = df.close.to_numpy(float)
    I = _ind(c)
    bc = df.ts.to_numpy(np.int64) + 15 * MIN
    with np.errstate(invalid="ignore"):
        e21, e52, rsi, roc = I["e21"], I["e52"], I["rsi"], I["roc"]
        rocp = prev(roc)
        up = (e21 > e52) & (rsi > 50) & (rocp <= 0) & (roc > 0)
        dn = (e21 < e52) & (rsi < 50) & (rocp >= 0) & (roc < 0)
    warm = np.arange(len(c)) >= WARM15
    g = grid(coin)
    e = (bc - T0) // MIN
    i = np.flatnonzero(warm & (up | dn) & (e < g["n"]))
    side = np.where(up[i], 1, -1)
    t = bc[i]
    R = pd.DataFrame({"t": t, "coin": COINS.index(coin), "side": side, "e": e[i]})
    for htf in ("1h", "4h"):
        dh = bars(coin, htf)
        Ih = _ind(dh.close.to_numpy(float))
        hc = dh.ts.to_numpy(np.int64) + TF_MIN[htf] * MIN
        j = np.searchsorted(hc, t, side="right") - 1                 # the last one closed at (or before) the bar close
        ok = j >= WARMH
        jj = np.maximum(j, 1)
        R[f"roc_{htf}"] = np.where(ok, side * Ih["roc"][jj], np.nan)
        R[f"ema_{htf}"] = np.where(ok, side * (Ih["e21"][jj] - Ih["e52"][jj]), np.nan)
    Z = np.load(os.path.join(NL.JUDGE, f"{coin}.npz"))
    tc = Z["4h_tclose"]
    jx = np.searchsorted(tc, t, side="right") - 1
    ok = (jx >= 0) & (t - tc[np.maximum(jx, 0)] < 2 * 240 * MIN)
    R["adx4h"] = np.where(ok, Z["4h_adx"].astype(float)[np.maximum(jx, 0)], np.nan)
    return R


def main():
    want = open(os.path.join(RES_DIR, "PREREG12.md.sha256")).read().split()[0]
    sha = hashlib.sha256(open(os.path.join(RES_DIR, "PREREG12.md"), "rb").read()).hexdigest()
    assert sha == want, "PREREG12.md changed after it was frozen"
    A = pd.concat([raw15(c) for c in COINS], ignore_index=True)
    A = A.iloc[np.lexsort((A.coin.to_numpy(), A.t.to_numpy()))].reset_index(drop=True)
    with np.errstate(invalid="ignore"):
        roc_ok = (A.roc_1h.to_numpy() > 0) | (A.roc_4h.to_numpy() > 0)
        ema_ok = (A.ema_1h.to_numpy() > 0) | (A.ema_4h.to_numpy() > 0)
    # check: the rebuilt current signal (1h OR 4h ROC9) is frfamily.signals("15m") row for row
    P = signals("15m")
    mine = A[roc_ok]
    same = (len(mine) == len(P) and (mine.t.to_numpy() == P.t.to_numpy()).all() and (mine.coin.to_numpy() == P.coin.to_numpy()).all()
            and (mine.side.to_numpy() == P.side.to_numpy()).all() and np.allclose(mine.adx4h.to_numpy(), P.adx4h.to_numpy(), equal_nan=True))
    print("rebuilt P == frfamily.signals('15m'):", same, len(mine), len(P), flush=True)
    assert same
    A["block"] = [blocked(int(x)) for x in A.t.to_numpy()]
    keep = (A.block == "").to_numpy()
    R = trend_columns(A[keep].reset_index(drop=True))
    roc_ok, ema_ok = roc_ok[keep], ema_ok[keep]
    four = np.logical_and.reduce(list(conditions(R).values()))
    doge = (R.coin == COINS.index("DOGEUSDT")).to_numpy()
    arms = {"E1 바꾸기 · 네 조건": ema_ok & four, "E2 더하기 · 네 조건": roc_ok & ema_ok & four,
            "비교 B (지금 신호 · 네 조건)": roc_ok & four,
            "E1 바꾸기 · 조건 없음": ema_ok, "E2 더하기 · 조건 없음": roc_ok & ema_ok}
    judged = ("E1 바꾸기 · 네 조건", "E2 더하기 · 네 조건")
    res = {"prereg12_sha256": sha, "rebuilt_p_matches": bool(same),
           "signals_unblocked": {k: int(v.sum()) for k, v in arms.items()}, "runs": {}}
    for sn, net_stop in STOPS.items():
        O = outcomes(R, net_stop, FL)
        Oo = outcomes(R, net_stop, FL, flip=True)
        for an, use in arms.items():
            if sn != "손절 화면 −20" and "조건 없음" in an:
                continue
            key = f"{an} · {sn}"
            d = detail(R, O, use, Oo)
            d["exits"] = exits(R, O, use)
            d["doge"] = detail(R, O, use & doge)
            if sn == "손절 화면 −20" and an in judged:
                v = {"select_positive": bool(d["select"]["roe_pct"] > 0), "confirm_positive": bool(d["confirm"]["roe_pct"] > 0),
                     "confirm_twin_975": bool(d["confirm"].get("twin") is not None and d["confirm"]["twin"] >= 0.975)}
                v["earns"] = all(v.values())
                d["verdict"] = v | {"text": "과거 기록상 버는 구조" if v["earns"] else "아님"}
            res["runs"][key] = d
            print(f"== {key} (signals {res['signals_unblocked'][an]})", flush=True)
            for p in PER:
                x = d[p]
                print(f"  {p:8s} n{x['n']} {x['per_weekday']}/d w{x['win']} be{x['breakeven_win']} aw{x['avg_win_pct']} al{x['avg_loss_pct']} "
                      f"roe{x['roe_pct']} (no pb {x['roe_pct_no_payback']}) x40 {x['mult40']} dd{x['maxdd40']} twin {x.get('twin')} | {d['exits'][p]}",
                      flush=True)
            print("  months", d["months"], "goal90", d["goal90"], flush=True)
            print("  doge", {p: (d["doge"][p]["n"], d["doge"][p]["win"], d["doge"][p]["roe_pct"], d["doge"][p]["mult40"]) for p in PER}, flush=True)
            if "verdict" in d:
                print("  verdict", d["verdict"], flush=True)
    json.dump(res, open(os.path.join(RES_DIR, "results17.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
