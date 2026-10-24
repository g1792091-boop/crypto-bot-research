"""The owners' ask of 10/24 night: "19일치는 분석해 줄 수 있잖아, 현재 장이니까 그 기준으로 가자." Every entry rule tried today x with or
without the four bigger-trend conditions x four exits, on the last 19 days only (10/04 09:00 .. 10/23 09:00 KST), 35x, one position,
the entry blocks, margin 40 %, the TetherMax payback 90 % per trade; split in two halves (10/04 .. 10/13 21:00, 10/13 21:00 .. 10/23) to
see whether the first half's best holds in the second. A read, not a test.

    python3 -I frlast19.py        -> research/friendroc/results21.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from frcore import *
from frrun import take, rnd
from frloss import PER, FL
from frbracket import run as run_fixed
from frmanual2 import LEV, REFUND
from frtrend4 import trend_columns, conditions
from frladder35 import outcomes, FEE_ROE
from frhtrend import raw15
from frhtrend2 import add_rsi
from frrules2 import coin_rules

A19, Z19 = PER["last19"]
MID = A19 + (Z19 - A19) // 2
WIN = {"19일": (A19, Z19), "앞 절반": (A19, MID), "뒤 절반": (MID, Z19)}
LEAD = ms("2026-09-01") - KST                               # rows from here (the walk runs to the data end)
EXITS = {"계단 · 손절 −20": ("L", -0.20 - FEE_ROE), "계단 · 손절 −30": ("L", -0.30 - FEE_ROE),
         "계단 · 손절 순 −50": ("L", -0.50), "고정 +10 · 손절 −20": ("T", None)}


def frame(R):
    R = R[R.t.to_numpy(np.int64) >= LEAD].reset_index(drop=True)
    R["block"] = [blocked(int(x)) for x in R.t.to_numpy()]
    return trend_columns(R[R.block == ""].reset_index(drop=True))


def read(R, O, use):
    t = R.t.to_numpy(np.int64)
    out = {}
    for wn, (a, z) in WIN.items():
        idx = take(t, O["k"], use & (t >= a) & (t < z))
        roe = LEV * O["r"][idx] + REFUND
        x = np.maximum(0.4 * roe, -1.0)
        eq = np.cumprod(1 + x) if len(x) else np.ones(1)
        out[wn] = {"n": int(len(idx)), "win": rnd(float((roe > 0).mean()), 4) if len(idx) else None,
                   "roe_pct": rnd(float(roe.mean() * 100), 2) if len(idx) else None, "mult40": rnd(float(eq[-1]), 3),
                   "maxdd40": rnd(float((eq / np.maximum.accumulate(np.r_[1.0, eq])[1:] - 1).min()), 3) if len(idx) else 0.0}
    return out


def coin_split(R, O, use):
    t = R.t.to_numpy(np.int64)
    idx = take(t, O["k"], use & (t >= A19) & (t < Z19))
    roe = LEV * O["r"][idx] + REFUND
    co, sd = R.coin.to_numpy()[idx], R.side.to_numpy()[idx]
    out = {}
    for ci, c in enumerate(COINS):
        m = co == ci
        out[c] = {"n": int(m.sum()), "win": int((roe[m] > 0).sum()), "sum_roe_pct": rnd(float(roe[m].sum() * 100), 1)}
    for s, nm in ((1, "롱"), (-1, "숏")):
        m = sd == s
        out[nm] = {"n": int(m.sum()), "win": int((roe[m] > 0).sum()), "sum_roe_pct": rnd(float(roe[m].sum() * 100), 1)}
    return out


def main():
    B = add_rsi(pd.concat([raw15(c) for c in COINS], ignore_index=True))
    B = B.iloc[np.lexsort((B.coin.to_numpy(), B.t.to_numpy()))].reset_index(drop=True)
    B = frame(B)
    with np.errstate(invalid="ignore"):
        g = {k: B[k].to_numpy() > 0 for k in ("roc_1h", "roc_4h", "rsi_1h", "rsi_4h", "ema_1h", "ema_4h")}
    entries = {"실거래로 정한 규칙 (1시간 RSI + ROC)": g["roc_1h"] & g["rsi_1h"],
               "처음 친구 신호 (1시간 또는 4시간 ROC)": g["roc_1h"] | g["roc_4h"],
               "친구 정확한 규칙 (1·4시간 둘 다 RSI + ROC)": g["roc_1h"] & g["rsi_1h"] & g["roc_4h"] & g["rsi_4h"],
               "규칙 1 (1시간 EMA + RSI)": g["ema_1h"] & g["rsi_1h"],
               "EMA 추세 바꾸기 (1시간 또는 4시간 EMA)": g["ema_1h"] | g["ema_4h"]}
    four = np.logical_and.reduce(list(conditions(B).values()))
    R2 = pd.concat([coin_rules(c)["R2"] for c in COINS], ignore_index=True)
    R2 = frame(R2.iloc[np.lexsort((R2.coin.to_numpy(), R2.t.to_numpy()))].reset_index(drop=True))
    four2 = np.logical_and.reduce(list(conditions(R2).values()))
    frames = {"B": B, "R2": R2}
    O = {}
    for fn, R in frames.items():
        for en, (kind, stop) in EXITS.items():
            O[(fn, en)] = outcomes(R, stop, FL) if kind == "L" else run_fixed(R, 0.10, -0.20)
    arms = [(nm, "B", m) for nm, m in entries.items()] + [("규칙 2 (골든크로스)", "R2", np.ones(len(R2), bool))]
    rows = []
    for nm, fn, m in arms:
        R = frames[fn]
        f4 = four if fn == "B" else four2
        for cn, use in (("조건 없음", m), ("+ 네 조건", m & f4)):
            for en in EXITS:
                d = read(R, O[(fn, en)], use)
                rows.append({"entry": nm, "cond": cn, "exit": en, **d})
    rows.sort(key=lambda r: -r["19일"]["mult40"])
    for r in rows:
        print(f"{r['entry']:34s} {r['cond']:6s} {r['exit']:14s} | " + " | ".join(
            f"{w} n{r[w]['n']} w{r[w]['win']} roe{r[w]['roe_pct']} x{r[w]['mult40']} dd{r[w]['maxdd40']}" for w in WIN), flush=True)
    best19 = rows[0]
    bestA = max(rows, key=lambda r: r["앞 절반"]["mult40"])
    rankB = sorted(rows, key=lambda r: -r["뒤 절반"]["mult40"])
    res = {"window_kst": [str(pd.Timestamp(x + KST, unit="ms")) for x in (A19, MID, Z19)], "rows": rows,
           "best_19": {k: best19[k] for k in ("entry", "cond", "exit")},
           "best_first_half": {k: bestA[k] for k in ("entry", "cond", "exit")} | {"second_half": bestA["뒤 절반"],
                                "second_half_rank": 1 + rankB.index(bestA), "of": len(rows)},
           "up_19": sum(r["19일"]["mult40"] > 1 for r in rows), "up_both_halves": sum(r["앞 절반"]["mult40"] > 1 and r["뒤 절반"]["mult40"] > 1 for r in rows)}
    for key, r in (("best_19", best19), ("chosen", next(x for x in rows if x["entry"].startswith("실거래") and x["cond"] == "조건 없음"
                                                                        and x["exit"] == "계단 · 손절 −20"))):
        fn = "R2" if r["entry"].startswith("규칙 2") else "B"
        R = frames[fn]
        m = np.ones(len(R2), bool) if fn == "R2" else entries[r["entry"]]
        if r["cond"] == "+ 네 조건":
            m = m & (four2 if fn == "R2" else four)
        res[f"{key}_split"] = coin_split(R, O[(fn, r["exit"])], m)
        print(key, r["entry"], r["cond"], r["exit"], res[f"{key}_split"], flush=True)
    print("best first half", res["best_first_half"], flush=True)
    print("up over 19 days", res["up_19"], "of", len(rows), "| up in both halves", res["up_both_halves"], flush=True)
    json.dump(res, open(os.path.join(RES_DIR, "results21.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
