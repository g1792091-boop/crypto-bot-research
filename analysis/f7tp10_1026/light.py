"""Owners 10/26 ("정말 성공하고 싶어 ... 제대로 알아봐줘"): final.py showed every variant losing hard in 2026-06 .. 09 and winning in
October. A signal light on the set-up's own shadow (the same rules, every trade, no money): a real trade only while the shadow's
last K closed trades won at least W (the trade itself is the shadow's own). Continuous 2026-06-01 .. data end, margin 40 %,
read by KST month and on the two live windows.
Run: python3 light.py --bars FIVE5M_DIR --work WORK_DIR"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import final as FN  # noqa: E402
import pick as PK  # noqa: E402
import structure as SR  # noqa: E402
import study as ST  # noqa: E402
import timing as TM  # noqa: E402

KST = 9 * 3_600_000
LIGHTS = {"신호등 없음": None, "최근 5번 다 승": (5, 5), "최근 8번 중 7승": (8, 7), "최근 10번 중 9승": (10, 9),
          "최근 10번 중 8승": (10, 8), "최근 20번 중 17승": (20, 17)}


def lit(T: pd.DataFrame, light) -> np.ndarray:
    if light is None:
        return np.ones(len(T), bool)
    k, w = light
    win = (T.roe > 0).to_numpy()
    ex = (T.t + (T.wait_h + T.hold_h) * 3_600_000).to_numpy()
    out = np.zeros(len(T), bool)
    for i in range(len(T)):
        done = np.flatnonzero(ex[:i] <= T.t.iloc[i])
        last = done[-k:]
        out[i] = len(last) == k and win[last].sum() >= w
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--work", required=True)
    a = ap.parse_args(argv)
    W = ST.World(a.bars, a.work)
    cand = SR.add_trend(W, pd.read_pickle(os.path.join(a.work, "cand.pkl")), a.work)
    setups = {"L2 1시간 슈퍼트렌드 · 주말 쉼": FN.setup_kw(0.25, 2, 0.10, 0.50, True, True),
              "L1 1시간 슈퍼트렌드 · 주말 포함": FN.setup_kw(0.25, 2, 0.10, 0.50, True, False),
              "L4 추세 없음 · 주말 쉼": FN.setup_kw(0.25, 2, 0.10, 0.50, False, True)}
    start = int(pd.Timestamp("2026-05-01 00:00", tz="Asia/Seoul").value // 1_000_000)   # a month of history for the light
    out = {}
    for sn, kw in setups.items():
        T, _ = TM.run(W, cand, a=start, b=PK.END, **kw)
        T["month"] = pd.to_datetime(T.t + KST, unit="ms").dt.strftime("%Y-%m")
        for ln, light in LIGHTS.items():
            take = lit(T, light)
            r = {}
            for m in ("2026-06", "2026-07", "2026-08", "2026-09", "2026-10"):
                g = T[take & (T.month == m)]
                r[m] = {"n": int(len(g)), "w": int((g.roe > 0).sum()), "l": int((g.roe <= 0).sum()),
                        "x": float(np.prod(1 + 0.40 * np.maximum(g.roe.to_numpy(), -1)))}
            g = T[take & (T.t >= ST.ms("2026-06-01"))]
            r["jun_oct"] = float(np.prod(1 + 0.40 * np.maximum(g.roe.to_numpy(), -1)))
            for wn, (wa, wb) in PK.LIVE.items():
                g = T[take & (T.t >= wa) & (T.t < wb)]
                r[wn] = {"n": int(len(g)), "w": int((g.roe > 0).sum()), "l": int((g.roe <= 0).sum()),
                         "x": float(np.prod(1 + 0.40 * np.maximum(g.roe.to_numpy(), -1)))}
            out[f"{sn}|{ln}"] = r
            print(sn, ln, json.dumps(r, ensure_ascii=False), flush=True)
    json.dump(out, open(os.path.join(a.work, "light.json"), "w"), indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
