"""New method 4 (10/25 night): pick the bot WITH the executor's signal light on (20 trades / 90 %) and its sizing,
from every coded strategy, instead of picking without it and adding the light after.

Members a config can run tomorrow: 484 cells (121 strategies x 15m/30m/1h/4h) x exits {ladder 12->10/5 with stop
1 ATR, 2 ATR, ROE -50 %, ROE -75 %} x side {both, short only, long only} x BTC 4h regime {all, up, down, range}.
Score (picked on 2020-03 .. 2025-12 only): from a start every 3 days, 30 days with the light 20/0.9 and the executor's
sizing (paper qty x a scale fixed at the start), J1 = share of starts reaching x5 before -30 %, J2 = J1 - 0.25 x share
reaching -30 % first. Each member alone (one position, at least 60 trades in 2020-25), the best 150 by each score,
then greedy: add the member that raises the merged bot's score most, up to 6 members, while it rises.
Read on 2026 Jan-Sep (never used), the forward 19 days, KST months. Coin flip: the whole pipeline again on seeded
random directions (seed 21), walked again."""
import os, sys, json, time
import numpy as np, pandas as pd
import numba as nb
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
exec(open(os.path.join(HERE, "s4_combo.py")).read().split("res = {}")[0])
T00 = time.time()
DAY = 86_400_000
SEED = None if len(sys.argv) < 2 else int(sys.argv[1])
XS = [0, 2, 5, 6]                    # ladder 12->10/5 with stop 1 ATR, 2 ATR, ROE -50 %, ROE -75 %
MODES = ("B", "S", "L")
GATES = (None, 0, 1, 2)
S0, S1 = ms("2020-03-01"), ms("2025-12-02")
STARTS = np.arange(S0, S1, 3 * DAY, dtype=np.int64)
STARTS26 = np.arange(ms("2026-01-01"), ms("2026-09-25"), DAY, dtype=np.int64)


def log(*a):
    print(f"[{time.time() - T00:7.0f}s]", *a, flush=True)


@nb.njit(cache=False)
def one_pos(t, k):
    keep = np.zeros(len(t), np.bool_); free = -1
    for i in range(len(t)):
        if t[i] >= free:
            keep[i] = True; free = t[i] + k[i] * 60000
    return keep


@nb.njit(cache=False)
def light(w, n, q):
    lv = np.ones(len(w), np.bool_)
    for i in range(n, len(w)):
        c = 0
        for j in range(i - n, i):
            if w[j] > 0:
                c += 1
        lv[i] = c >= q * n - 1e-9
    return lv


@nb.njit(cache=False)
def roll(t, w, lv, starts, horizon, floor, goal):
    hit = 0; bust = 0
    for s in starts:
        i = np.searchsorted(t, s); P = 1.0; E = 1.0
        while i < len(t) and t[i] < s + horizon:
            if lv[i]:
                r = P / E
                if r > 1.0:
                    r = 1.0
                E *= 1 + r * w[i]
                if E >= goal:
                    hit += 1; break
                if E <= floor:
                    bust += 1; break
            P *= 1 + w[i]; i += 1
    return hit / len(starts), bust / len(starts)


def merged(parts):
    """parts: list of (t, w, k, tfo) arrays of members -> one-position bot (sorted by t, longer bar first)."""
    t = np.concatenate([p[0] for p in parts]); w = np.concatenate([p[1] for p in parts])
    k = np.concatenate([p[2] for p in parts]); tf = np.concatenate([p[3] for p in parts])
    o = np.lexsort((-tf, t)); t, w, k = t[o], w[o], k[o]
    keep = one_pos(t, k)
    return t[keep], w[keep]


def score(t, w):
    lv = light(w, 20, 0.9)
    h, b = roll(t, w, lv, STARTS, 30 * DAY, 0.7, 5.0)
    return h, b, h - 0.25 * b


def read26(t, w):
    lv = light(w, 20, 0.9)
    h, b = roll(t, w, lv, STARTS26, 30 * DAY, 0.7, 5.0)
    f = (t >= SM.FWD_A) & (t < SM.Z)
    # forward 19 days: the executor's sizing from a start at FWD_A, no goal, no floor
    i0 = np.searchsorted(t, SM.FWD_A); P = E = 1.0
    for i in range(i0, len(t)):
        if t[i] >= SM.Z:
            break
        if lv[i]:
            E *= 1 + min(P / E, 1.0) * w[i]
        P *= 1 + w[i]
    y = pd.to_datetime(t + 9 * 3600 * 1000, unit="ms").year.to_numpy()
    per = {str(yy): round(float(w[(y == yy) & (t < SM.FWD_A)].mean()), 4) for yy in range(2020, 2027)
           if ((y == yy) & (t < SM.FWD_A)).any()}
    return {"2026 30일 x5/-30%": [round(h, 3), round(b, 3)], "10월19일": round(E, 2), "10월 거래": int(f.sum()),
            "실거래 비율": round(float(lv.mean()), 3), "거래당": per}


cells = [str(c) for c in np.load(os.path.join(OUTD, "meta.npz"), allow_pickle=True)["cells"]]
STORE = {}
for n, cell in enumerate(cells):
    for x in XS:
        try:
            T = SM.trades(cell, "none", "양방향", x, flip_seed=SEED)
        except IndexError:                 # a cell with no signal in the period
            break
        if not len(T):
            continue
        t = T.t.to_numpy(np.int64)
        STORE[(cell, x)] = (t, T.w.to_numpy(np.float64), T.k.to_numpy(np.int64), T.side.to_numpy(np.int8),
                            reg_at(t).astype(np.int8), int(T.tfo.iloc[0]))
    SM._S.pop(cell, None)
    if n % 50 == 0:
        log("walked", n, "/", len(cells))
log("walks done", len(STORE))


def member(key):
    cell, x, mode, gate = key
    t, w, k, side, reg, tfo = STORE[(cell, x)]
    m = np.ones(len(t), bool)
    if mode == "S":
        m &= side < 0
    elif mode == "L":
        m &= side > 0
    if gate is not None:
        m &= reg == gate
    o = np.argsort(t[m], kind="stable")
    tt, ww, kk = t[m][o], w[m][o], k[m][o]
    keep = one_pos(tt, kk)
    return tt[keep], ww[keep], kk[keep], np.full(int(keep.sum()), tfo)


rows = []
for (cell, x) in STORE:
    for mode in MODES:
        for gate in GATES:
            key = (cell, x, mode, gate)
            tt, ww, kk, tf = member(key)
            sel = (tt >= S0) & (tt < ms("2026-01-01"))
            if sel.sum() < 60:
                continue
            h, b, j2 = score(tt, ww)
            rows.append((key, h, b, j2))
log("members scored", len(rows))
res = {"members": len(rows)}
for jname, ji in (("J1", 1), ("J2", 3)):
    top = sorted(rows, key=lambda r: -r[ji])[:150]
    parts = {r[0]: member(r[0]) for r in top}
    chosen = []; best = -9.0; path = []
    for step in range(6):
        cand = None
        for r in top:
            key = r[0]
            if key in chosen or any(c[0] == key[0] and c[2] == key[2] for c in chosen):
                continue
            t, w = merged([parts[c] for c in chosen + [key]])
            s = score(t, w)[ji - 1 if ji == 1 else 2]
            if s > best + 1e-9 and (cand is None or s > cand[1]):
                cand = (key, s)
        if cand is None:
            break
        chosen.append(cand[0]); best = cand[1]
        t, w = merged([parts[c] for c in chosen])
        h, b, j2 = score(t, w)
        path.append({"추가": list(map(str, cand[0])), "2020~25 x5/-30%": [round(h, 3), round(b, 3)], "J": round(best, 4),
                     **read26(t, w)})
        log(jname, "step", step, path[-1])
    res[jname] = {"top5 단독": [{"멤버": list(map(str, r[0])), "x5": round(r[1], 3), "-30%": round(r[2], 3)} for r in top[:5]],
                  "탐욕 경로": path}
lab = "real" if SEED is None else f"flip{SEED}"
json.dump(res, open(os.path.join(OUTD, f"lightpick15_{lab}.json"), "w"), ensure_ascii=False, indent=1, default=float)
log("done")
