"""The owners' ask of 10/24 night: which reading of the friend's rule did better from 2026-01-01 to 10-22 (KST)? Three readings of the
higher-bar check after the friend's 15m signal (EMA21 vs EMA52, RSI26 vs 50, ROC9 crossing 0):
  ① the friend's first message: the last closed 1h OR 4h bar has RSI26 and ROC9 both on the side;
  ② the friend's correction (the bot's deploy rule): the last closed 1h OR 4h bar has ROC9 on the side;
  ③ the owners' chat line: the last closed 1h bar has RSI26 and ROC9 on the side (4h not read).
Same trade for all: 35x, net ROE -50 % stop, the ladder 12 -> 10 then 5 % steps, one position, the entry blocks, margin 40 %, with and
without the TetherMax payback 90 %. A read, not a test.

    python3 -I frytd.py           -> research/friendroc/results23.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frrun import take, rnd
from frloss import FL
from frmanual2 import LEV, REFUND
from frladder35 import outcomes
from frhtrend import raw15
from frhtrend2 import add_rsi

A0, Z0 = ms("2026-01-01") - KST, ms("2026-10-23") - KST          # 2026-01-01 00:00 .. 10-23 00:00 KST


def stats(roe):
    eq = np.cumprod(1 + np.maximum(0.4 * roe, -1.0))
    w, lo = roe[roe > 0], roe[roe <= 0]
    return {"n": int(len(roe)), "win": rnd(float((roe > 0).mean()), 4), "roe_pct": rnd(float(roe.mean() * 100), 2),
            "pf": rnd(float(w.sum() / -lo.sum()), 3) if len(lo) else None, "mult40": rnd(float(eq[-1]), 4),
            "maxdd40": rnd(float((eq / np.maximum.accumulate(np.r_[1.0, eq])[1:] - 1).min()), 3)}


def main():
    B = add_rsi(pd.concat([raw15(c) for c in COINS], ignore_index=True))
    B = B[B.t.to_numpy(np.int64) >= ms("2025-12-01") - KST]
    B = B.iloc[np.lexsort((B.coin.to_numpy(), B.t.to_numpy()))].reset_index(drop=True)
    B["block"] = [blocked(int(x)) for x in B.t.to_numpy()]
    B = B[B.block == ""].reset_index(drop=True)
    with np.errstate(invalid="ignore"):
        g = {k: B[k].to_numpy() > 0 for k in ("roc_1h", "roc_4h", "rsi_1h", "rsi_4h")}
    rules = {"① 처음 말 (1시간 또는 4시간, RSI + ROC)": (g["rsi_1h"] & g["roc_1h"]) | (g["rsi_4h"] & g["roc_4h"]),
             "② 수정한 말 (1시간 또는 4시간, ROC만) = 지금 봇": g["roc_1h"] | g["roc_4h"],
             "③ 채팅 (1시간만, RSI + ROC)": g["rsi_1h"] & g["roc_1h"]}
    O = outcomes(B, -0.50, FL)
    t = B.t.to_numpy(np.int64)
    mon = np.asarray(pd.to_datetime(t + KST, unit="ms").strftime("%Y-%m"))
    res = {}
    for nm, m in rules.items():
        idx = take(t, O["k"], m & (t >= A0) & (t < Z0))
        r = LEV * O["r"][idx]
        d = {"with_payback": stats(r + REFUND), "no_payback": stats(r), "months": {}}
        for q in pd.period_range("2026-01", "2026-10", freq="M").strftime("%Y-%m"):
            mi = take(t, O["k"], m & (mon == q) & (t >= A0) & (t < Z0))         # each month from a fresh start
            rr = LEV * O["r"][mi]
            d["months"][q] = {"n": int(len(mi)), "with": rnd(float(np.prod(1 + 0.4 * (rr + REFUND))), 3) if len(mi) else 1.0,
                              "without": rnd(float(np.prod(1 + 0.4 * rr)), 3) if len(mi) else 1.0}
        res[nm] = d
        a, b = d["with_payback"], d["no_payback"]
        print(f"== {nm}", flush=True)
        print(f"   with payback: n{a['n']} win {a['win']} roe/trade {a['roe_pct']}% PF {a['pf']} x40 {a['mult40']} maxdd {a['maxdd40']}", flush=True)
        print(f"   no payback  : win {b['win']} roe/trade {b['roe_pct']}% PF {b['pf']} x40 {b['mult40']} maxdd {b['maxdd40']}", flush=True)
        print("   months (with / without):", " ".join(f"{q[5:]}:{v['with']}/{v['without']}({v['n']})" for q, v in d["months"].items()), flush=True)
    json.dump(res, open(os.path.join(RES_DIR, "results23.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
