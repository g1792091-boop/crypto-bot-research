"""Owners 10/26: "짧게 먹고 나오는 전략인가? ... 익절 손절 구조를 내 목표 1달 수익률에 가능성이 있는 최대 좋은 구조로 ... 주말장은? ...
진입타점 부분도 괜찮나? 추세전략을 넣어야하나? v3.9 매매법을 추세판단용으로 사용하고 진입 매매법을 레인지로 사용했을때 성과는?"
All with the custom numbers (80 / 9.0), BTC 40x / others 30x, margin 40 %, no entry 30 min around the NYSE open and macro releases.
  (1) what a trade does: the best net ROE it reaches before a -50 % stop (no take-profit), five years and October;
  (2) take-profits (fixed 10 / 15 / 20 / 30 / 50 %, steps 12 -> 10, 22 -> 20, 32 -> 30, 52 -> 50, each +5 then -2) with a -50 % stop,
      weekend on / off, and a trend side check: none, the V3.9 1h strategy's last signal, the V3.9 supertrend (10, 3) on the 1h
      bar, or on the last closed 4h bar (trendjudge's V39 vote);
  (3) each read on the two live windows, every start day in October (10/01 .. 10/18 to the data's end) and five years by KST
      month (a fresh wallet each month).
Run: python3 structure.py --bars FIVE5M_DIR --work WORK_DIR"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import pick as PK  # noqa: E402
import study as ST  # noqa: E402

KST = 9 * 3_600_000
EXITS = {"고정 +10%": dict(exit="tp10", tp_roe=0.10), "고정 +15%": dict(exit="tp10", tp_roe=0.15),
         "고정 +20%": dict(exit="tp10", tp_roe=0.20), "고정 +30%": dict(exit="tp10", tp_roe=0.30),
         "고정 +50%": dict(exit="tp10", tp_roe=0.50),
         "계단 12→10": dict(exit="lad", lad=(0.12, 0.10, 0.05, 0.02)), "계단 22→20": dict(exit="lad", lad=(0.22, 0.20, 0.05, 0.02)),
         "계단 32→30": dict(exit="lad", lad=(0.32, 0.30, 0.05, 0.02)), "계단 52→50": dict(exit="lad", lad=(0.52, 0.50, 0.05, 0.02))}
TRENDS = {"추세 없음": None, "V3.9 마지막 신호 방향": "v39_latch", "V3.9 슈퍼트렌드 1시간": "st1h", "V3.9 슈퍼트렌드 4시간": "st4h"}
STARTS = [f"2026-10-{d:02d} 09:00" for d in range(1, 19)]


def add_trend(W, cand: pd.DataFrame, work: str) -> pd.DataFrame:
    names = ("v39_latch", "st1h", "st4h", "j1_V39", "j1_S6", "j1_OBV", "j1_N12", "j1_raw3", "ema200",
             "j4_S6", "j4_OBV", "j4_N12", "j4_raw3")
    cols = {k: np.zeros(len(cand), np.int8) for k in names}
    for c in ST.COINS:
        m = (cand.coin == c).to_numpy()
        y = np.load(os.path.join(work, "prep", f"{c}_trend.npz"))
        i1 = cand.loc[m, "i1"].to_numpy()
        k4 = cand.loc[m, "j4k"].to_numpy()
        cols["v39_latch"][m] = y["v39_latch"][i1]
        cols["st1h"][m] = y["st1h"][i1]
        cols["st4h"][m] = W.p[c]["j4_V39"][k4]
        for k in ("j1_V39", "j1_S6", "j1_OBV", "j1_N12", "j1_raw3", "ema200"):
            if k in y.files:
                cols[k][m] = y[k][i1]
        for k in ("j4_S6", "j4_OBV", "j4_N12", "j4_raw3"):
            cols[k][m] = W.p[c][k][k4]
    return cand.assign(**cols)


def arm_of(ex: dict, wk: str, trend):
    f = [PK.FIXED] + ([PK.NOWK] if wk == "주말 쉼" else [])
    if trend:
        f.append(lambda g, col=trend: g[col] == g.side)
    return {**PK.SIZE, **ex, "stop_roe": 0.50, "filters": tuple(f)}


def months(W, cand, arm) -> dict:
    S5 = ST.run_arm(W, cand, dict(arm, margin=lambda c: 1e-9), ST.ms("2021-01-01"), ST.ms("2026-10-01"))
    S5["month"] = pd.to_datetime(S5.t + KST, unit="ms").dt.strftime("%Y-%m")
    mo = {}
    for m, g in S5.groupby("month"):
        eq = 1.0
        for x in g.roe.to_numpy():
            eq *= 1 + 0.40 * max(x, -1.0)
            if eq < 0.01:
                break
        mo[m] = eq
    s = pd.Series(mo).reindex(pd.period_range("2021-01", "2026-09", freq="M").strftime("%Y-%m")).fillna(1.0)
    return {"x6": int((s >= 6).sum()), "x3": int((s >= 3).sum()), "x2": int((s >= 2).sum()), "up": int((s > 1).sum()),
            "half": int((s <= 0.5).sum()), "median": float(s.median()), "best": float(s.max()), "n": int(len(S5)),
            "win": float((S5.roe > 0).mean()) if len(S5) else 0.0, "mean_roe": float(S5.roe.mean()) if len(S5) else 0.0}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--live-only", action="store_true",
                    help="owners 10/26 '5년치 말고 이번 규칙봇 돌린기간이랑 커스텀값 봇 돌린기간만': the two live windows only")
    a = ap.parse_args(argv)
    W = ST.World(a.bars, a.work)
    cand = add_trend(W, pd.read_pickle(os.path.join(a.work, "cand.pkl")), a.work)
    out = {"mfe": {}, "rows": []}
    if a.live_only:
        for en, ex in EXITS.items():
            for wk in ("주말 포함", "주말 쉼"):
                for tn, tc in TRENDS.items():
                    arm = arm_of(ex, wk, tc)
                    r = {"exit": en, "weekend": wk, "trend": tn}
                    for wn, (wa, wb) in PK.LIVE.items():
                        r[wn] = PK.read(ST.run_arm(W, cand, arm, wa, wb))
                    r["score"] = min(r["rulebot"]["x"], r["league"]["x"])
                    out["rows"].append(r)
                    print(json.dumps(r, ensure_ascii=False), flush=True)
        json.dump(out, open(os.path.join(a.work, "structure_live.json"), "w"), indent=1, ensure_ascii=False)
        return 0
    # (1) best net ROE before a -50 % stop, no take-profit (every signal the rules allow, one position)
    probe = {**PK.SIZE, "exit": "tp10", "tp_roe": 50.0, "stop_roe": 0.50, "filters": (PK.FIXED,)}
    for wn, (wa, wb) in (("2021-2026.09", (ST.ms("2021-01-01"), ST.ms("2026-10-01"))), ("2026-10", (ST.ms("2026-10-01"), PK.END))):
        T = ST.run_arm(W, cand, dict(probe, margin=lambda c: 1e-9), wa, wb)
        mfe = T.mfe.to_numpy()
        out["mfe"][wn] = {"n": int(len(T)), **{f">={k}%": float((mfe >= k / 100).mean()) for k in (5, 10, 15, 20, 30, 50, 100)},
                          "median_mfe": float(np.median(mfe)), "median_hours_to_stop": float(np.median((T.exit_t - T.t) / 3.6e6))}
        print("mfe", wn, json.dumps(out["mfe"][wn]), flush=True)
    for en, ex in EXITS.items():
        for wk in ("주말 포함", "주말 쉼"):
            for tn, tc in TRENDS.items():
                arm = arm_of(ex, wk, tc)
                r = {"exit": en, "weekend": wk, "trend": tn}
                for wn, (wa, wb) in PK.LIVE.items():
                    r[wn] = PK.read(ST.run_arm(W, cand, arm, wa, wb))
                xs = [PK.read(ST.run_arm(W, cand, arm, int(pd.Timestamp(s, tz="Asia/Seoul").value // 1_000_000), PK.END))["x"]
                      for s in STARTS]
                r["oct_start"] = {"median": float(np.median(xs)), "worst": float(min(xs)), "best": float(max(xs)),
                                  "losing": int(sum(x < 1 for x in xs))}
                r["five_year"] = months(W, cand, arm)
                out["rows"].append(r)
                print(json.dumps(r, ensure_ascii=False), flush=True)
    json.dump(out, open(os.path.join(a.work, "structure.json"), "w"), indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
