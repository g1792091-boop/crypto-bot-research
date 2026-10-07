"""Z7 independent crash check from fy36 (v4n nominal outcomes) + own pessimistic 5m fills.
python3 -I -B v4_crash.py <fy36_dir> <bars_dir>"""
import os
import sys

sys.dont_write_bytecode = True
sys.path.append('/root/.local/lib/python3.11/site-packages')
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

FY, BARS = sys.argv[1:3]
TAKER, SLIP = 0.0005, 0.0002
TFM = {"15m": 15, "30m": 30}
DAYS = ["2022-06-13", "2022-11-08", "2024-08-05", "2025-10-10"]
NS = 60 * 10**9
b5 = {c: dict(np.load(os.path.join(BARS, f"sig_5m_{c}USD.npz"))) for c in ("BTC", "ETH", "SOL", "DOGE", "LTC", "BCH")}


def lpn(d):
    st = 1 - d
    ex = st * (1 - SLIP)
    return d + (st - ex) + TAKER + ex * TAKER


for tf in ("15m", "30m"):
    D = pd.read_pickle(os.path.join(FY, f"fy36_{tf}.pkl.gz"))
    D = D[(D.v4n_lev > 0) & D.v4n_done]
    D = D.assign(coin=D.coin.astype(str).str.replace("USD", ""), strategy=D.strategy.astype(str))
    tm = TFM[tf] * NS
    for day in DAYS:
        t0 = pd.Timestamp(day).value
        s = D[(D.ts + tm >= t0 - 86400 * 10**9) & (D.ts + tm < t0 + 86400 * 10**9)].copy()
        d = s.stop_frac.values.astype(float)
        R = s.v4n_R.values.astype(float)
        pR = R.copy()
        for k, (coin, ts, side, held, reason) in enumerate(zip(s.coin, s.ts, s.side, s.v4n_held, s.v4n_reason)):
            if reason != 0:
                continue
            b = b5[coin]
            i = np.searchsorted(b["ts"], ts + tm)
            raw = b["o"][i]
            fill = raw * (1 + side * SLIP)
            stop0 = fill * (1 - side * d[k])
            xb = ts + int(held) * tm
            i0, i1 = np.searchsorted(b["ts"], [xb, xb + tm])
            lo, hi = b["l"][i0:i1], b["h"][i0:i1]
            hit = np.nonzero(lo <= stop0)[0] if side == 1 else np.nonzero(hi >= stop0)[0]
            px = (lo[hit[0]] if side == 1 else hi[hit[0]]) if len(hit) else stop0
            ex = px * (1 - side * SLIP)
            ret = side * (ex / fill - 1) - TAKER * (1 + ex / fill)
            pR[k] = min(R[k], max(ret, -1 / 30) / d[k])
        s["R"], s["pR"] = R, pR
        s["k2"] = 0.02 * R * d / lpn(d)
        s["k2p"] = 0.02 * pR * d / lpn(d)
        s["m30"] = np.maximum(9 * R * d, -0.3)
        s["m30p"] = np.maximum(9 * pR * d, -0.3)
        m30ok = s.v4n_lev == 30
        # one-position traders, greedy (random tie-break), compounded and summed
        rng = np.random.default_rng(1)
        rows = []
        for st, g in s.assign(tb=rng.random(len(s))).sort_values(["ts", "tb"]).groupby("strategy"):
            free, cK, cKp, cM, cMp, sM, sMp = -1, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0
            for r in g.itertuples():
                if r.ts + tm < free:
                    continue
                free = r.ts + (int(r.v4n_held) + 1) * tm
                cK *= 1 + r.k2; cKp *= 1 + r.k2p
            free = -1
            for r in g[g.v4n_lev == 30].itertuples():   # margin 30x trader: only 30x-executable signals occupy the slot
                if r.ts + tm < free:
                    continue
                free = r.ts + (int(r.v4n_held) + 1) * tm
                cM *= 1 + r.m30; cMp *= 1 + r.m30p; sM += r.m30; sMp += r.m30p
            rows.append((st, cK - 1, cKp - 1, cM - 1, cMp - 1, sM, sMp))
        tr = pd.DataFrame(rows, columns=["s", "K2", "K2p", "M30", "M30p", "M30sum", "M30psum"])
        print(f"{day} {tf} n={len(s)} SL={int((s.v4n_reason == 0).sum())} worstR {R.min():.2f} pess {pR.min():.2f} | "
              f"worst trade K2 {s.k2.min()*100:.1f}/{s.k2p.min()*100:.1f}% M30 {s.m30[m30ok].min()*100:.1f}/"
              f"{s.m30p[m30ok].min()*100:.1f}% | traders {len(tr)} worst K2 {tr.K2.min()*100:.1f}/{tr.K2p.min()*100:.1f}% "
              f"M30 compounded {tr.M30.min()*100:.1f}/{tr.M30p.min()*100:.1f}% summed {tr.M30sum.min()*100:.1f}/"
              f"{tr.M30psum.min()*100:.1f}% share M30p<=-25% {(tr.M30p <= -0.25).mean()*100:.0f}% (summed "
              f"{(tr.M30psum <= -0.25).mean()*100:.0f}%)")
