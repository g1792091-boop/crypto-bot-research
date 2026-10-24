"""PREREG13.md: enter when, on the last closed 1h OR 4h bar, both EMA21 vs EMA52 and RSI26 vs 50 are on the 15m signal's side. F1 swaps
the 1h / 4h ROC9 confirmation for it, F2 keeps the ROC9 confirmation and adds it; both with PREREG12's trade (the four bigger-trend
conditions, 35x, the screen's -20 % stop, the ladder 12 -> 10 then 5 % steps, one position, the entry blocks, margin 40 %, the
TetherMax payback 90 %). PREREG12's E1 and B beside them; for reference the net -50 % stop and both without the four conditions.

    python3 -I frhtrend2.py       -> research/friendroc/results18.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frcore import _ind
from frloss import PER, FL
from frbracket import detail
from frtrend4 import trend_columns, conditions
from frladder35 import outcomes, exits
from frhtrend import raw15, STOPS
import hashlib


def add_rsi(A):
    """The side-signed RSI26 - 50 of the last closed 1h and 4h bars (the same bar raw15 reads its ROC9 and EMAs from)."""
    A = A.copy()
    for htf in ("1h", "4h"):
        col = np.full(len(A), np.nan)
        for ci, coin in enumerate(COINS):
            m = (A.coin == ci).to_numpy()
            t = A.t.to_numpy(np.int64)[m]
            s = A.side.to_numpy()[m]
            dh = bars(coin, htf)
            rsi = _ind(dh.close.to_numpy(float))["rsi"]
            hc = dh.ts.to_numpy(np.int64) + TF_MIN[htf] * MIN
            j = np.searchsorted(hc, t, side="right") - 1
            col[m] = np.where(j >= WARMH, s * (rsi[np.maximum(j, 1)] - 50), np.nan)
        A[f"rsi_{htf}"] = col
    return A


def main():
    want = open(os.path.join(RES_DIR, "PREREG13.md.sha256")).read().split()[0]
    sha = hashlib.sha256(open(os.path.join(RES_DIR, "PREREG13.md"), "rb").read()).hexdigest()
    assert sha == want, "PREREG13.md changed after it was frozen"
    A = pd.concat([raw15(c) for c in COINS], ignore_index=True)
    A = A.iloc[np.lexsort((A.coin.to_numpy(), A.t.to_numpy()))].reset_index(drop=True)
    A = add_rsi(A)
    A["block"] = [blocked(int(x)) for x in A.t.to_numpy()]
    R = trend_columns(A[(A.block == "").to_numpy()].reset_index(drop=True))
    with np.errstate(invalid="ignore"):
        roc_ok = (R.roc_1h.to_numpy() > 0) | (R.roc_4h.to_numpy() > 0)
        ema_ok = (R.ema_1h.to_numpy() > 0) | (R.ema_4h.to_numpy() > 0)
        er_ok = ((R.ema_1h.to_numpy() > 0) & (R.rsi_1h.to_numpy() > 0)) | ((R.ema_4h.to_numpy() > 0) & (R.rsi_4h.to_numpy() > 0))
    four = np.logical_and.reduce(list(conditions(R).values()))
    doge = (R.coin == COINS.index("DOGEUSDT")).to_numpy()
    arms = {"F1 바꾸기 (EMA + RSI) · 네 조건": er_ok & four, "F2 더하기 (EMA + RSI) · 네 조건": roc_ok & er_ok & four,
            "비교 E1 (EMA만 바꾸기) · 네 조건": ema_ok & four, "비교 B (지금 신호) · 네 조건": roc_ok & four,
            "F1 바꾸기 (EMA + RSI) · 조건 없음": er_ok, "F2 더하기 (EMA + RSI) · 조건 없음": roc_ok & er_ok}
    judged = ("F1 바꾸기 (EMA + RSI) · 네 조건", "F2 더하기 (EMA + RSI) · 네 조건")
    res = {"prereg13_sha256": sha, "signals_unblocked": {k: int(v.sum()) for k, v in arms.items()}, "runs": {}}
    for sn, net_stop in STOPS.items():
        O = outcomes(R, net_stop, FL)
        Oo = outcomes(R, net_stop, FL, flip=True)
        for an, use in arms.items():
            if sn != "손절 화면 −20" and ("조건 없음" in an or an.startswith("비교 B")):
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
    json.dump(res, open(os.path.join(RES_DIR, "results18.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
