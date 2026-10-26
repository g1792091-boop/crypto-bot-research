"""Owners 10/26: "혹시 커스텀값은 괜찮을까? 더 좋은 커스텀값 찾아줄수있어?" The range filter's two numbers (period, multiplier) under the
final structure (FINAL_KO.md, hunt.py's F1: the coin's and BTC's 1h V3.9 supertrend on the side, 0.2 ATR / 1 h pullback at market,
TP net +10 %, stop net -50 %, BTC 40x / others 30x, margin 40 %, NYSE open / macro +-30 min, weekend off, one signal at a time).
80 / 9.0 came from the league's five-year full grid (candleague/data/candidates.json), chosen before October: its October is a forward
read. Any other pair picked here is picked on October itself, so the grid is read for its shape (is 80 / 9.0 on a plateau or a
spike?) and against the 21 months 2025-01 .. 2026-09 as well as the two live windows.
Run: python3 numbers_grid.py --bars FIVE5M_DIR --work WORK_DIR"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import warnings

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402

import hunt as H  # noqa: E402
import pick as PK  # noqa: E402
import prep as P  # noqa: E402  (puts the repository on sys.path)

PERIODS = (30, 40, 50, 60, 70, 80, 90, 100, 120, 150, 200)
MULTS = (2.0, 3.0, 4.5, 6.0, 7.5, 9.0, 10.5, 12.0, 15.0)
F1 = dict(H.BASE, commit=True, btc=True, k=0.20, wait_h=1, sources=("1h_g",))


def heikin(W: H.World, work: str) -> dict:
    """{coin: (ha 1h, ha of the last closed 4h bar)} as ds_defs._f7_triple reads them."""
    from research.fullgrid import ds_defs as D
    out = {}
    for c in H.ST.COINS:
        z = np.load(os.path.join(work, "prep", f"{c}.npz"))
        b = {"ts": z["h1_ts"], "o": z["h1_o"], "h": z["h1_h"], "l": z["h1_l"], "c": z["h1_c"], "v": z["h1_v"]}
        df = P.frame(b)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ha = D.C.heikin_bull(b["o"], b["h"], b["l"], b["c"])
            hha = D.C.htf_value(df, "1h", lambda dh: D.C.heikin_bull(dh["open"].to_numpy(float), dh["high"].to_numpy(float),
                                                                      dh["low"].to_numpy(float), dh["close"].to_numpy(float)))
        out[c] = (ha, hha, b["c"])
    return out


def set_numbers(W: H.World, HA: dict, period: int, mult: float) -> None:
    from research.fullgrid import ds_defs as D
    for c, (ha, hha, close) in HA.items():
        rf = D.range_filter_dir(close, period, mult)
        up, dn = (rf == 1) & (ha == 1) & (hha == 1), (rf == -1) & (ha == 0) & (hha == 0)
        W.h[c]["1h_g_state"] = up.astype(np.int8) - dn.astype(np.int8)
        W.h[c]["1h_g_sig"] = D._first_event(up).astype(np.int8) - D._first_event(dn).astype(np.int8)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--work", required=True)
    a = ap.parse_args(argv)
    H.SOURCES["1h_g"] = ("1h", "g")
    W = H.World(a.bars, a.work)
    HA = heikin(W, a.work)
    set_numbers(W, HA, 80, 9.0)
    for c in H.ST.COINS:                                  # the grid's own build of 80 / 9.0 is the league's signal
        if not np.array_equal(W.h[c]["1h_g_sig"], W.h[c]["1h_c_sig"]):
            raise SystemExit(f"{c}: the grid's 80 / 9.0 differs from the prepared custom signal")
    a0, b0 = H.kst_month("2025-01")[0], H.kst_month("2026-09")[1]
    rows, t0 = [], time.time()
    for p in PERIODS:
        for m in MULTS:
            set_numbers(W, HA, p, m)
            r = {"period": p, "mult": m}
            for wn, (wa, wb) in list(PK.LIVE.items()) + [("oct", H.OCT)]:
                r[wn] = H.run(W, F1, wa, wb)[1]
            T, s = H.run(W, F1, a0, b0)
            mo = H.months_read(T)
            r["months"] = {k: mo[k] for k in ("x2", "up", "median", "geo", "best", "worst")}
            r["months"]["win"] = s["w"] / max(s["n"], 1)
            r["months"]["per_month"] = s["n"] / len(H.MONTHS)
            r["live"] = min(r["rulebot"]["x"], r["league"]["x"])
            rows.append(r)
            print(f"{p:4} / {m:4.1f} | RB {r['rulebot']['w']}-{r['rulebot']['l']} x{r['rulebot']['x']:.2f} | LG {r['league']['w']}-"
                  f"{r['league']['l']} x{r['league']['x']:.2f} | OCT {r['oct']['w']}-{r['oct']['l']} x{r['oct']['x']:.2f} | 21m win "
                  f"{r['months']['win'] * 100:.1f}% up {mo['up']} med {mo['median']:.2f} geo {mo['geo']:.2f} n/mo "
                  f"{r['months']['per_month']:.0f} | {time.time() - t0:.0f}s", flush=True)
    json.dump(rows, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "numbers_grid.json"), "w"), indent=0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
