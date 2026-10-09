"""Development tool (not run on the server): builds demobot/data/past5y_<S>_<tf>.npz, the "5년 성적" columns of the
ranking (CONTRACT section 4).

* periods 2020 / 2021-23 / 2024-26: the 5-year study's own totals (research/st_custom stage 2, every setting, every
  coin, variants main + 12 TP/stop pairs), from the study's work folder.
* crash months 2020-03 (COVID), 2022-05 (LUNA), 2022-11 (FTX): recomputed with the demo bot's own history path
  (engine.warm on the replay market), which reproduces the study's crash-window rows exactly (checked: S2 15m
  default 2022-05 all coins n=1688, net -0.089699).

    python3 -m demobot.tools.build_past5y <study_work_dir> <scratch_db_dir>
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np
import pandas as pd

from .. import engine as EN
from .. import grid as G
from .. import store as ST
from ..data import Market
from . import replay_market as RM

PERIODS = ("2020", "2021-23", "2024-26", "2020-03", "2022-05", "2022-11")
STUDY_PER = {"2020": "EXTRA", "2021-23": "SEARCH", "2024-26": "TEST"}
CRASH = {"2020-03": ("2020-03-01", "2020-04-01"), "2022-05": ("2022-05-01", "2022-06-01"),
         "2022-11": ("2022-11-01", "2022-12-01")}
VARIANT_OF_EXIT = [0] + [5 + j for j in range(12)]       # study s2 VARIANTS: main, maker, htf, chop, stflip, tpsl..
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ms(s: str) -> int:
    return int(pd.Timestamp(s, tz="UTC").value // 10**6)


def study_block(work: str, strat: str, tf: str, per: str) -> np.ndarray:
    """(E, S, C, 3) n / win_rate / mean_R from the study totals."""
    nc = G.NCOMBO[strat]
    out = np.full((G.NEXIT, len(G.SCOPES), nc, 3), np.nan, np.float32)
    tot_all = np.zeros((G.NEXIT, nc, 3))
    for ci, coin in enumerate(G.COINS):
        z = np.load(os.path.join(work, "totals", f"{coin}_{tf}_{per}.npz"))
        T = z[f"{strat}__tot"]                         # (NV, nc, [n, wins, sumR, sumG, sumR2, nsig])
        for e, v in enumerate(VARIANT_OF_EXIT):          # exit 13 (half/break-even) was not in the study: NaN
            n, w, s = T[v, :, 0], T[v, :, 1], T[v, :, 2]
            with np.errstate(invalid="ignore", divide="ignore"):
                out[e, ci + 1] = np.stack([n, w / n, s / n], 1)
            tot_all[e] += np.stack([n, w, s], 1)
    n, w, s = tot_all[..., 0], tot_all[..., 1], tot_all[..., 2]
    with np.errstate(invalid="ignore", divide="ignore"):
        out[:, 0] = np.stack([n, w / n, s / n], -1)
    out[len(VARIANT_OF_EXIT):] = np.nan
    return out


def crash_blocks(db_dir: str) -> dict:
    """{(strat, tf, period): (E, S, C, 3)} for the three crash months, via the demo bot's history path."""
    out = {}
    for per, (a, b) in CRASH.items():
        a0, a1 = ms(a), ms(b)
        end = a1 + 45 * 86400 * 1000
        weeks = int((end - a0) / (7 * 86400 * 1000)) + 2
        clock = [end]
        bars = RM.load(a0 - (weeks * 7 + 40) * 86400 * 1000, end)
        rest = RM.FakeREST(bars, RM.load_funding(), lambda: clock[0])
        mkt = Market(rest=rest, clock_ms=lambda: clock[0], pause=lambda s: None)
        dbp = os.path.join(db_dir, f"past_{per}.db")
        for suf in ("", "-wal", "-shm"):
            if os.path.exists(dbp + suf):
                os.remove(dbp + suf)
        conn = ST.connect(dbp)
        eng = EN.Engine(conn, market=mkt, clock_ms=lambda: clock[0], log=lambda *x: None)
        t0 = time.time()
        eng.warm(weeks=weeks, end_ms=end)
        print(per, "warm", round(time.time() - t0), "s", flush=True)
        for strat in G.STRATS:
            nc = G.NCOMBO[strat]
            for tf in G.TFS:
                blk = np.full((G.NEXIT, len(G.SCOPES), nc, 3), np.nan, np.float32)
                acc = np.zeros((G.NEXIT, len(G.SCOPES), nc, 3))
                for ci, coin in enumerate(G.COINS):
                    ts, cb, sd = eng.sigs[(coin, tf, strat)].arrays()
                    m = (ts >= a0) & (ts < a1)
                    ts, cb, sd = ts[m], cb[m].astype(np.int64), sd[m]
                    book = eng.books[(coin, tf)]
                    k = book.index(ts)
                    ok = k >= 0
                    cb, k, s = cb[ok], k[ok], np.where(sd[ok] > 0, 0, 1)
                    for e in range(G.NEXIT):
                        if e == 0:
                            R = book.F[k, s, ST.F_MAIN_R].astype(float)
                            d = book.F[k, s, ST.F_MAIN_REASON] != 3
                        elif e == G.HALFBE:
                            R = book.F[k, s, ST.F_HB_R].astype(float)
                            d = np.isfinite(R)
                        else:
                            R = book.F[k, s, ST.F_TP_R + e - 1].astype(float)
                            d = np.isfinite(R)
                        n = np.bincount(cb[d], minlength=nc)
                        w = np.bincount(cb[d & (R > 0)], minlength=nc)
                        sm = np.bincount(cb[d], weights=R[d], minlength=nc)
                        acc[e, ci + 1] = np.stack([n, w, sm], 1)
                        acc[e, 0] += np.stack([n, w, sm], 1)
                n, w, sm = acc[..., 0], acc[..., 1], acc[..., 2]
                with np.errstate(invalid="ignore", divide="ignore"):
                    blk[...] = np.stack([n, w / n, sm / n], -1)
                out[(strat, tf, per)] = blk
        conn.close()
        for suf in ("", "-wal", "-shm"):
            if os.path.exists(dbp + suf):
                os.remove(dbp + suf)
    return out


def main(work: str, db_dir: str) -> None:
    os.makedirs(db_dir, exist_ok=True)
    crash = crash_blocks(db_dir)
    for strat in G.STRATS:
        for tf in G.TFS:
            nc = G.NCOMBO[strat]
            st = np.full((len(PERIODS), G.NEXIT, len(G.SCOPES), nc, 3), np.nan, np.float32)
            for pi, per in enumerate(PERIODS):
                if per in STUDY_PER:
                    st[pi] = study_block(work, strat, tf, STUDY_PER[per])
                else:
                    st[pi] = crash[(strat, tf, per)]
            path = os.path.join(HERE, "data", f"past5y_{G.SHORT[strat]}_{tf}.npz")
            ST.write_npz(path, stats=st, periods=np.array(PERIODS), exits=np.array(G.EXITS),
                         scopes=np.array(G.SCOPES))
            print("wrote", path, flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
