"""Sweep 3 (10/25, the owners' idea): a regime-switching bot. Regime = the combined bot's own `reg` (paperbot/rmember:
the last closed BTC 4h bar, ADX14 < 20 range, else close above EMA50 up, below down). For each regime, members are
picked on 2020-03 .. 2025-12 only (per-trade wallet result inside that regime, positive in 2020-22 and in 2023-25),
then the bot (each member trades only in its regime, one position) is read on 2026 Jan-Sep and the forward 19 days,
which the pick never saw. Same sizing / costs / exits as sweep 2; coin-flip directions for the luck count."""
import os, sys, json, time
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); OUTD = os.path.join(HERE, "out")
src = open(os.path.join(HERE, "s2.py")).read()
_pre = src.split("# ------------------------------------------------------------------ months and forward flags")[0]
_a, _b = _pre.split("# ------------------------------------------------------------------ trend-judge bits")
_pre = _a + "# walks" + _b.split("# ------------------------------------------------------------------ walks")[1]
exec(_pre.replace("cache=True", "cache=False"))
sys.path.insert(0, "/home/user/crypto-bot-research")
from paperbot.rmember import regimes                    # noqa: E402
from common import bars                                  # noqa: E402

b4 = bars("BTCUSDT", "4h")
reg_bar, _ = regimes(b4.high.to_numpy(), b4.low.to_numpy(), b4.close.to_numpy())
close_t = b4.ts.to_numpy(np.int64) + 4 * 3600 * 1000
j = np.searchsorted(close_t, t, side="right") - 1
reg = np.where(j >= 0, reg_bar[np.clip(j, 0, None)], 2).astype(np.int8)
REG_KO = ["상승장", "하락장", "횡보장"]
dk = pd.to_datetime(t + KST, unit="ms")
ym = (dk.year * 100 + dk.month).to_numpy()
per = np.full(len(t), -1, np.int8)                      # 0: 2020-03..2022-12, 1: 2023..2025, 2: 2026-01..09, 3: forward
per[(ym >= 202003) & (ym <= 202212)] = 0
per[(ym >= 202301) & (ym <= 202512)] = 1
per[(ym >= 202601) & (ym <= 202609)] = 2
per[t >= FWD_A] = 3
log("regimes", {REG_KO[r]: round(float((reg == r).mean()), 3) for r in range(3)})

NCELL = 121 * 4
NX = W.shape[1]
cptr = np.searchsorted(cell, np.arange(NCELL + 1)).astype(np.int64)
CELLS_ = [f"{NM.name[NM.sid == q // 4].iloc[0]}@{TFS[q % 4]}" if (NM.sid == q // 4).any() else f"{q // 4}@{TFS[q % 4]}"
          for q in range(NCELL)]


def table(Wm, flipside):
    """Per (cell, mode, exit, regime, period): trades, sum of wallet results, wins (every signal, no position limit)."""
    out = np.zeros((NCELL, 3, NX, NR, 4, 3))
    sd = flipside
    for mode in range(3):
        mm = good.copy()
        if mode == 1:
            mm &= sd < 0
        elif mode == 2:
            mm &= sd > 0
        for p in range(4):
            mp = mm & (per == p)
            key = cell[mp].astype(np.int64) * NR + reg[mp]
            for x in range(NX):
                w = Wm[mp, x].astype(np.float64)
                out[:, mode, x, :, p, 0] = np.bincount(key, minlength=NCELL * NR).reshape(NCELL, NR)
                out[:, mode, x, :, p, 1] = np.bincount(key, weights=w, minlength=NCELL * NR).reshape(NCELL, NR)
                out[:, mode, x, :, p, 2] = np.bincount(key, weights=(w > 0), minlength=NCELL * NR).reshape(NCELL, NR)
    return out


def picks(Tb, K, min_n=300, cellmask=None):
    """Per regime, the top K distinct cells by mean wallet result in 2020-25 inside the regime (positive in 2020-22 and in
    2023-25, >= min_n trades)."""
    n = Tb[..., 0]; s = Tb[..., 1]
    nsel = n[..., 0] + n[..., 1]; msel = (s[..., 0] + s[..., 1]) / np.maximum(nsel, 1)
    m0 = s[..., 0] / np.maximum(n[..., 0], 1); m1 = s[..., 1] / np.maximum(n[..., 1], 1)
    ok = (nsel >= min_n) & (n[..., 0] >= min_n / 4) & (n[..., 1] >= min_n / 4) & (m0 > 0) & (m1 > 0)
    if cellmask is not None:
        ok &= cellmask[:, None, None, None]
    out = {}
    for r in range(NR):
        sc = np.where(ok[:, :, :, r], msel[:, :, :, r], -9)
        o = np.argsort(-sc.ravel()); sel = []; seen = set()
        for q in o:
            if sc.ravel()[q] <= 0:
                break
            c, m, x = np.unravel_index(q, sc.shape)
            if c in seen:
                continue
            seen.add(c); sel.append((int(c), int(m), int(x), float(sc.ravel()[q])))
            if len(sel) >= K:
                break
        out[r] = sel
    return out, int(ok.sum())


TFO = tfi.astype(np.int64)


def bot(sel, Wm, Km, sd):
    """One position over the members (each only in its regime); returns trades (t, w) in time order."""
    rows = []
    for r, mems in sel.items():
        for c, m, x, _ in mems:
            ii = np.arange(cptr[c], cptr[c + 1]); ii = ii[good[ii] & (reg[ii] == r)]
            if m == 1:
                ii = ii[sd[ii] < 0]
            elif m == 2:
                ii = ii[sd[ii] > 0]
            rows.append(np.c_[t[ii], -TFO[ii], Wm[ii, x], Km[ii, x]])
    if not rows:
        return np.zeros((0, 2))
    A_ = np.concatenate(rows); A_ = A_[np.lexsort((A_[:, 1], A_[:, 0]))]
    keep = []; free = -1
    for row in A_:
        if row[0] >= free:
            keep.append((row[0], row[2])); free = row[0] + row[3] * 60000
    return np.array(keep)


def read(T):
    tt, w = T[:, 0].astype(np.int64), T[:, 1]
    out = {}
    d = pd.to_datetime(tt + KST, unit="ms"); k = (d.year * 100 + d.month).to_numpy()
    for lab, (a, b) in {"2020~25": (202003, 202512), "2026 1~9월": (202601, 202609)}.items():
        hit = pos = act = 0
        for mth in np.unique(k[(k >= a) & (k <= b)]):
            eq = np.cumprod(1 + w[k == mth]); act += 1; pos += eq[-1] >= 1
            for v in eq:
                if v >= 5:
                    hit += 1; break
                if v <= 0.5:
                    break
        out[lab] = {"x5달": hit, "플러스달": pos, "달": act}
    f = tt >= FWD_A
    out["19일"] = {"x": round(float(np.prod(1 + w[f])), 2), "앞": round(float(np.prod(1 + w[f & (tt < MID)])), 2),
                  "뒤": round(float(np.prod(1 + w[f & (tt >= MID)])), 2), "n": int(f.sum()),
                  "승률": round(float((w[f] > 0).mean()), 3) if f.any() else None}
    for lab, (a, b) in {"2026 시작": (ms("2026-01-01"), ms("2026-09-25")), "2020~25 시작": (ms("2020-03-01"), ms("2025-12-02"))}.items():
        res = []
        for s0 in range(a, b, 86_400_000):
            i = np.searchsorted(tt, s0); eq = 1.0; rr = 0
            while i < len(tt) and tt[i] < s0 + 30 * 86_400_000:
                eq *= 1 + w[i]; i += 1
                if eq >= 5:
                    rr = 1; break
                if eq <= 0.5:
                    rr = -1; break
            res.append(rr)
        res = np.array(res); out[lab + " 30일 x5/-50%"] = [round(float((res == 1).mean()), 3), round(float((res == -1).mean()), 3)]
    for g in (10.0, 15.0):
        res = []
        for s0 in range(ms("2026-01-01"), ms("2026-09-25"), 86_400_000):
            i = np.searchsorted(tt, s0); eq = 1.0; rr = 0
            while i < len(tt) and tt[i] < s0 + 30 * 86_400_000:
                eq *= 1 + w[i]; i += 1
                if eq >= g:
                    rr = 1; break
                if eq <= 0.5:
                    rr = -1; break
            res.append(rr)
        res = np.array(res); out[f"2026 시작 30일 x{g:g}/-50%"] = [round(float((res == 1).mean()), 3), round(float((res == -1).mean()), 3)]
    m26 = (k >= 202601) & (k <= 202609)
    out["2026 월별"] = {int(q): [round(float(np.prod(1 + w[k == q])), 2), int((k == q).sum())] for q in np.unique(k[m26])}
    out["거래당 지갑(2026 1~9월)"] = round(float(w[(tt >= ms("2026-01-01")) & (tt < FWD_A)].mean()), 4) if len(w) else None
    return out


RUNNABLE = np.array([NM.set[NM.sid == q // 4].iloc[0] in ("core", "ds", "friend") if (NM.sid == q // 4).any() else False
                     for q in range(NCELL)])
from paperbot.rmember import vol_rank                   # noqa: E402
REG3 = reg.copy()
_, reg5_bar = regimes(b4.high.to_numpy(), b4.low.to_numpy(), b4.close.to_numpy())
REG5 = np.where(j >= 0, reg5_bar[np.clip(j, 0, None)], 4).astype(np.int8)
VOL = np.ones(len(t), np.int8)
for ci, c_ in enumerate(COINS):
    b1 = bars(c_, "1h"); rk = vol_rank(b1.high.to_numpy(), b1.low.to_numpy(), b1.close.to_numpy())
    v3 = np.where(np.isnan(rk), 1, np.where(rk < 1 / 3, 0, np.where(rk < 2 / 3, 1, 2))).astype(np.int8)
    m = coin == ci; jj = np.searchsorted(b1.ts.to_numpy(np.int64) + 3600 * 1000, t[m], side="right") - 1
    VOL[m] = np.where(jj >= 0, v3[np.clip(jj, 0, None)], 1)
log("vol3 shares", [round(float((VOL == v).mean()), 3) for v in range(3)])
DEFS = {"추세세기5": (REG5, ["강한상승", "약한상승", "강한하락", "약한하락", "횡보"]),
        "장세x변동성9": ((REG3 * 3 + VOL).astype(np.int8), [f"{a}·{b}" for a in ("상승", "하락", "횡보") for b in ("변동성낮음", "보통", "높음")]),
        "장세3(비교)": (REG3, ["상승장", "하락장", "횡보장"])}
res = {}
for dname, (reg_arr, names) in DEFS.items():
    reg = reg_arr; NR = len(names); REG_KO = names
    for run, seed in (("real", None), ("flip", 7), ("flip2", 8)):
        if seed is None:
            Wm, Km, sd = W, K, side
        else:
            fl = np.random.default_rng(seed).random(len(t)) < 0.5
            Wm = np.where(fl[:, None], W2, W); Km = np.where(fl[:, None], K2, K); sd = np.where(fl, -side, side).astype(np.int8)
        Tb = table(Wm, sd)
        n = Tb[..., 0]; s = Tb[..., 1]
        for K_ in (1, 2, 3):
            mn = 300 if NR == 3 else 200
            sel, nok = picks(Tb, K_, min_n=mn, cellmask=RUNNABLE)
            r = {"members": {REG_KO[rg]: [f"{CELLS_[c]} {['양방향', '숏만', '롱만'][m]} · {XN[x]} (2020-25 거래당 {sc:+.4f})"
                                          for c, m, x, sc in v] for rg, v in sel.items()}, "통과 수": nok}
            for lab, p in (("2026 1~9월", 2), ("19일", 3)):
                nn = sum(n[c, m, x, rg, p] for rg, v in sel.items() for c, m, x, _ in v)
                ss = sum(s[c, m, x, rg, p] for rg, v in sel.items() for c, m, x, _ in v)
                r[f"{lab} 거래당(제한 없이)"] = round(ss / max(nn, 1), 4); r[f"{lab} 거래 수"] = int(nn)
            T_ = bot(sel, Wm, Km, sd); r["봇"] = read(T_)
            res[f"{dname}/{run}/top{K_}"] = r
            b_ = r["봇"]
            print(dname, run, K_, "통과", nok, "| 2026 거래당", r["2026 1~9월 거래당(제한 없이)"], f"({r['2026 1~9월 거래 수']})",
                  "| 19일 거래당", r["19일 거래당(제한 없이)"], "| 봇 2026 x5/-50%", b_["2026 시작 30일 x5/-50%"],
                  "x10", b_["2026 시작 30일 x10/-50%"], "| 19일", b_["19일"]["x"], f"({b_['19일']['n']})",
                  "| 2026 봇 거래당", b_["거래당 지갑(2026 1~9월)"], flush=True)
            if run == "real":
                for rg, v in r["members"].items():
                    print("     ", rg, v, flush=True)
        del Tb
json.dump(res, open(os.path.join(OUTD, "regime3.json"), "w"), ensure_ascii=False, indent=1, default=float)
log("done")
