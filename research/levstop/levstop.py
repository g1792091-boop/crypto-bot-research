"""Five-year leverage and stop-width comparison (pre-registered in research/levstop/PREREG_LEVSTOP.md).

    python3 research/levstop/levstop.py run --signals DIR [--out research/levstop/out/levstop.json] [--procs 4]
        [--n-boot 2000] [--strategies A,B] [--tfs 5m,1h]

Read-only research: nothing here trades or touches a database. ``DIR`` is the lab's five-year signal cache
(``sig_<tf>_<COIN>.npz``, the files paperbot/agents/labdata.py builds and checks against labdata_reference.json).
The committed result (``out/levstop.json``) is what paperbot/agents/levstop.py gives the Friday risk meeting.

What (every number is code; the choices are fixed in the PREREG, before any result):
- 36 strategies x 5 timeframes (180 cells) x 24 arms: leverage mode ``tiers`` (the current rules' sizing with its
  fallback, rules_bt.SETTINGS, like the lab's stop_atr test) or a fixed 10 / 20 / 30 / 40 / 50x at the tier table's
  margin share (10x and 20x 20%, 30x 30%, 40x and 50x 40%), times the initial stop 1.5 / 2 / 2.5 / 3 ATR14.
- Per-signal outcomes (every signal alone, no position limit) from research/strategy_profiles/profiles.py ``_scan`` /
  ``_sizer`` in the passes of paperbot/agents/labtests.py ``signal_outcomes`` (next-bar entry + slippage, k x ATR14
  stop, the stepped lock, fees, slippage and funding as rules_bt). Fixed leverage: every signal enters at that
  leverage (no 15% stop-loss cap, no stop-inside-liquidation buffer); liquidation applies: where the stop lies at or
  beyond the liquidation price the exit level is the liquidation price and such an exit is a liquidation (ROE -100%),
  as is a bar that opens beyond it. ``rules_ok_share``: the share of those signals the rules' sizing checks would
  have let in at that single leverage.
- Per cell and arm: trades, mean ROE, mean P&L on equity (ROE x margin share), win rate, liquidation share, the mean
  per period (1: 2021-08-01 .. 2024-07-01, 2: 2024-07-01 .. 2026-09-30), the week-block bootstrap p of the mean
  P&L on equity vs zero (paperbot/agents/newlab.py ``boot_mean_p``, one-sided each way), its t-value, and one
  account per period ($5,000, one position at a time over the six coins, coin priority, compounding, bust < $10).
- Summary per arm: Benjamini-Hochberg FDR 10% over the 180 cells (each side), busts, pooled means; lines in Korean.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import sys
import time
from multiprocessing import Pool
from typing import Optional

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out", "levstop.json")
PREREG = os.path.join(HERE, "PREREG_LEVSTOP.md")
VERSION = 1
TFS = ("5m", "15m", "30m", "1h", "4h")
COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "LTCUSD", "BCHUSD")      # entry priority (rules_bt.COINS)
LEV_MODES = ("tiers", 10, 20, 30, 40, 50)
KS = (1.5, 2.0, 2.5, 3.0)
MARGIN_FRAC = {50: 0.40, 40: 0.40, 30: 0.30, 20: 0.20, 10: 0.20}
PERIODS = (("1", "2021-08-01", "2024-07-01"), ("2", "2024-07-01", "2026-09-30"))
N_BOOT = 2000
ALPHA = 0.05
FDR = 0.10
START = 5000.0
BUST_BELOW = 10.0
SIZE_EQUITY = 1000.0             # profiles.EQUITY: the sizing equity of the per-signal outcomes
CURRENT = "tiers|2.0"
COLUMNS = ["signals", "trades", "mean_roe", "mean_eq", "win_rate", "liq_share", "mean_eq_p1", "mean_eq_p2",
           "p_pos", "p_neg", "t", "bust_p1", "bust_p2", "mult_p1", "mult_p2", "rules_ok_share", "mean_eq_rules_ok"]


def arms() -> list[str]:
    return [f"{m}|{k}" for m in LEV_MODES for k in KS]


def _ns(day: str) -> int:
    return int(np.datetime64(day, "ns").astype(np.int64))


def _sha(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


# ---------------------------------------------------------------- machinery (read-only reuse)
def _lt():
    from paperbot.agents import labtests as LT
    return LT


def _profiles():
    return _lt().profiles_module()


def _fixed_settings(lev: int):
    from dataclasses import replace

    from paperbot.config import Tier
    RB = _profiles().RB
    s = RB.SETTINGS
    return replace(s, tiers=(Tier("best", MARGIN_FRAC[lev], (lev,)),), min_leverage=min(lev, s.min_leverage),
                   max_leverage=max(lev, s.max_leverage))


class FixedSizer:
    """Fixed leverage ``lev`` at its tier margin share on SIZE_EQUITY: the liquidation distance (fraction of the
    fill, exchange formula on the research brackets) per side, and whether the rules' sizing checks (15% stop-loss
    cap, stop inside liquidation by max(1 ATR, 0.2%), bracket) would pass at that single leverage."""

    def __init__(self, lev: int, k: float):
        from paperbot.margin import liquidation_price
        RB = _profiles().RB
        self.lev, self.k = lev, k
        self.settings = _fixed_settings(lev)
        slip = RB.SETTINGS.slippage_frac
        self.liq_frac = {}
        for side in (1, -1):
            fill = 100.0 * (1 + side * slip)
            margin = SIZE_EQUITY * MARGIN_FRAC[lev]
            qty = margin * lev / fill
            liq = liquidation_price(side, qty, fill, margin, RB.BRACKETS.for_notional(qty * fill))
            self.liq_frac[side] = side * (fill - liq) / fill
        self._ok: dict = {}

    def rules_ok(self, side: int, atr_frac: float) -> bool:
        from paperbot.sizing import size_position
        RB = _profiles().RB
        key = (side, float(f"{atr_frac:.4g}"))
        if key not in self._ok:
            raw = 100.0
            a = key[1] * raw
            fill = raw * (1 + side * RB.SETTINGS.slippage_frac)
            d = size_position(self.settings, SIZE_EQUITY, side, fill, raw - side * self.k * a, "best", RB.BRACKETS,
                              atr=a, min_notional=RB.MIN_NOTIONAL)
            self._ok[key] = bool(d.ok)
        return self._ok[key]


def outcomes(b: dict, idx: np.ndarray, side: np.ndarray, tf: str, mode, k: float) -> dict:
    """Per-signal outcomes of one arm for signals at bar ``idx`` (entry at idx + 1): the passes of
    labtests.signal_outcomes over profiles._scan, with a per-signal stop multiple (the stop clipped to the
    liquidation price for a fixed leverage). Returns lev, roe, reason (0 stop, 1 lock, 2 liquidation, 3 open),
    held, done, rules_ok."""
    from paperbot import sweepsig
    P = _profiles()
    RB = P.RB
    L = sweepsig.lib()
    n = len(b["ts"])
    f_bar = RB.FUNDING_8H * L.tf_minutes(tf) / 480.0
    m = len(idx)
    raw = b["o"][idx + 1]
    a = b["atr"][idx]
    af = a / raw
    kk = np.full(m, float(k))
    clipped = np.zeros(m, bool)
    if mode == "tiers":
        sizer = P._sizer(k)
        ll = np.array([sizer(int(s), float(x)) for s, x in zip(side, af)], float).reshape(-1, 2)
        lev, liq_frac = ll[:, 0], ll[:, 1]
        rules_ok = lev > 0
    else:
        fs = FixedSizer(int(mode), k)
        lev = np.full(m, float(mode))
        liq_frac = np.where(side > 0, fs.liq_frac[1], fs.liq_frac[-1])
        fill = raw * (1 + side * RB.SETTINGS.slippage_frac)
        liq = fill * (1 - side * liq_frac)
        cap = side * (raw - liq) / a                       # the stop multiple that sits on the liquidation price
        clipped = cap <= k
        kk = np.minimum(kk, cap)
        rules_ok = np.array([fs.rules_ok(int(s), float(x)) for s, x in zip(side, af)], bool)
    sized = lev > 0
    res = {x: np.full(m, np.nan) for x in ("held", "roe", "reason")}
    todo = np.nonzero(sized)[0]
    for H in (64, 512, 4096):
        if not len(todo):
            break
        nxt = []
        step = max(32, 256_000 // H)
        for c0 in range(0, len(todo), step):
            sel = todo[c0:c0 + step]
            r = P._scan(b, idx[sel], side[sel], lev[sel], liq_frac[sel], H, n, f_bar, k_stop=kk[sel])
            keep = r["done"] | (H == 4096) | (idx[sel] + H >= n - 1)
            for x in ("held", "roe", "reason"):
                res[x][sel[keep]] = r[x][keep]
            nxt.append(sel[~keep])
        todo = np.concatenate(nxt) if nxt else np.zeros(0, int)
    reason = res["reason"]
    reason = np.where(clipped & (reason == 0), 2.0, reason)      # the "stop" on the liquidation price
    roe = np.where(reason == 2, -1.0, res["roe"])
    done = sized & (reason < 3)
    return dict(lev=lev, roe=roe, reason=reason, held=res["held"], done=done, rules_ok=rules_ok)


# ---------------------------------------------------------------- statistics
def tvalue(x: np.ndarray) -> Optional[float]:
    """profiles._t: mean / (sd / sqrt n)."""
    x = x[np.isfinite(x)]
    if len(x) <= 2 or not x.std() > 0:
        return None
    return float(x.mean() / (x.std(ddof=1) / math.sqrt(len(x))))


def boot_p(week: np.ndarray, x: np.ndarray, n_boot: int, seed: int) -> Optional[float]:
    from paperbot.agents.newlab import boot_mean_p
    return boot_mean_p(week, x, n_boot, seed) if len(x) else None


def account(ts: np.ndarray, coin: np.ndarray, exit_ts: np.ndarray, g: np.ndarray) -> tuple[bool, float, int]:
    """One account: signals by time and coin priority, one position at a time (a signal before the open trade's exit
    bar is skipped), equity x (1 + g) per trade, bust below BUST_BELOW (nothing after). (bust, final / start, trades)."""
    if not len(ts):
        return False, 1.0, 0
    o = np.lexsort((coin, ts))
    ts, ex, g = ts[o], exit_ts[o], g[o]
    eq, i, n, free = START, 0, len(ts), None
    trades = 0
    while i < n:
        if free is not None and ts[i] < free:
            i = int(np.searchsorted(ts, free, side="left"))
            if i >= n:
                break
        eq *= 1.0 + float(g[i])
        trades += 1
        if eq < BUST_BELOW:
            return True, eq / START, trades
        free = ex[i]
        i += 1
    return False, eq / START, trades


def bh(pvals: list, q: float = FDR) -> list[bool]:
    """Benjamini-Hochberg step-up at FDR ``q`` (None p-values never pass and do not count)."""
    ix = [i for i, p in enumerate(pvals) if p is not None]
    m = len(ix)
    out = [False] * len(pvals)
    if not m:
        return out
    order = sorted(ix, key=lambda i: pvals[i])
    k = 0
    for r, i in enumerate(order, 1):
        if pvals[i] <= q * r / m:
            k = r
    for i in order[:k]:
        out[i] = True
    return out


def _r(x, n: int = 5):
    if x is None:
        return None
    x = float(x)
    if not math.isfinite(x):
        return None
    return float(f"{x:.{n}g}")


def _seed(*parts) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def cell_stats(per_coin: list[dict], strategy: str, tf: str, arm: str, mode, n_boot: int) -> list:
    """The COLUMNS row of one cell and arm from the per-coin outcomes (dicts with ts, coin, exit_ts, period and the
    ``outcomes`` arrays)."""
    cat = {x: np.concatenate([c[x] for c in per_coin]) if per_coin else np.zeros(0)
           for x in ("ts", "coin", "exit_ts", "period", "lev", "roe", "reason", "done", "rules_ok")}
    signals = int(len(cat["ts"]))
    d = cat["done"].astype(bool)
    roe = cat["roe"][d]
    lev = cat["lev"][d]
    mf = np.array([MARGIN_FRAC.get(int(round(x)), np.nan) for x in lev], float)
    eq = roe * mf
    per = cat["period"][d]
    ts = cat["ts"][d]
    n = int(len(roe))
    if not n:
        return [signals, 0] + [None] * (len(COLUMNS) - 2)
    LT = _lt()
    week = LT.week_of(ts)
    p_pos = boot_p(week, eq, n_boot, _seed(strategy, tf, arm, "pos"))
    p_neg = boot_p(week, -eq, n_boot, _seed(strategy, tf, arm, "neg"))
    acc = []
    for pid, _a, _b in PERIODS:
        s = per == int(pid)
        acc.append(account(ts[s], cat["coin"][d][s], cat["exit_ts"][d][s], eq[s]))
    ok = cat["rules_ok"][d].astype(bool)
    fixed = mode != "tiers"
    mp = [float(np.mean(eq[per == int(pid)])) if (per == int(pid)).any() else None for pid, _a, _b in PERIODS]
    return [signals, n, _r(np.mean(roe)), _r(np.mean(eq)), _r(np.mean(roe > 0), 4),
            _r(np.mean(cat["reason"][d] == 2), 4), _r(mp[0]), _r(mp[1]), _r(p_pos, 4), _r(p_neg, 4), _r(tvalue(eq), 4),
            int(acc[0][0]), int(acc[1][0]), _r(acc[0][1], 4), _r(acc[1][1], 4),
            _r(np.mean(ok), 4) if fixed else None,
            _r(np.mean(eq[ok])) if fixed and ok.any() else None]


# ---------------------------------------------------------------- one strategy x timeframe
_BARS: dict = {}


def _bars(sig_dir: str, tf: str) -> dict:
    """{coin: (bars dict, npz)} of one timeframe, one timeframe cached per process."""
    if tf not in _BARS:
        _BARS.clear()
        out = {}
        for c in COINS:
            p = os.path.join(sig_dir, f"sig_{tf}_{c}.npz")
            if not os.path.exists(p):
                continue
            z = np.load(p)
            out[c] = ({x: z[x] for x in ("ts", "o", "h", "l", "c", "atr")}, z)
        _BARS[tf] = out
    return _BARS[tf]


def job(args) -> tuple[str, str, dict, float]:
    """All arms of one strategy x timeframe: {arm: COLUMNS row}."""
    sig_dir, strategy, tf, n_boot = args
    t0 = time.time()
    from paperbot import sweepsig
    RB = _profiles().RB
    L = sweepsig.lib()
    p_edges = [(_ns(a), _ns(b)) for _p, a, b in PERIODS]
    coins = []
    for ci, c in enumerate(COINS):
        got = _bars(sig_dir, tf).get(c)
        if got is None or f"s__{strategy}" not in got[1].files:
            continue
        b, z = got
        sg = z[f"s__{strategy}"]
        n = len(b["ts"])
        lo = RB.window_bounds(L, b, tf, "is")[0]
        n_end = RB.window_bounds(L, b, tf, "cf")[1]
        idx = np.nonzero(sg[lo:max(lo, n_end - 1)])[0] + lo
        ok = np.isfinite(b["atr"][idx]) & (b["atr"][idx] > 0) & np.isfinite(b["o"][np.minimum(idx + 1, n - 1)])
        idx = idx[ok]
        ts = b["ts"][idx]
        period = np.zeros(len(idx), int)
        for k, (a, e) in enumerate(p_edges, 1):
            period[(ts >= a) & (ts < e)] = k
        keep = period > 0
        coins.append((ci, b, idx[keep], sg[idx[keep]].astype(int), ts[keep], period[keep]))
    rows = {}
    for mode in LEV_MODES:
        for k in KS:
            arm = f"{mode}|{k}"
            per_coin = []
            for ci, b, idx, side, ts, period in coins:
                o = outcomes(b, idx, side, tf, mode, k)
                held = np.nan_to_num(o["held"], nan=0).astype(int)
                ex = b["ts"][np.minimum(idx + held, len(b["ts"]) - 1)]
                per_coin.append(dict(ts=ts, coin=np.full(len(idx), ci), exit_ts=ex, period=period, **o))
            rows[arm] = cell_stats(per_coin, strategy, tf, arm, mode, n_boot)
    return strategy, tf, rows, time.time() - t0


# ---------------------------------------------------------------- summary
def summarize(cells: dict) -> dict:
    ci = {c: i for i, c in enumerate(COLUMNS)}
    by_arm, by_arm_tf = {}, {}
    keys = sorted(cells)
    for arm in arms():
        rows = [(key, cells[key].get(arm)) for key in keys if cells[key].get(arm)]
        rows = [(key, r) for key, r in rows if r[ci["trades"]]]
        pos_bh = bh([r[ci["p_pos"]] for _k, r in rows])
        neg_bh = bh([r[ci["p_neg"]] for _k, r in rows])
        tr = sum(r[ci["trades"]] for _k, r in rows)
        mults = [r[ci[x]] for _k, r in rows for x in ("mult_p1", "mult_p2") if r[ci[x]] is not None]
        means = [r[ci["mean_eq"]] for _k, r in rows]
        a = {"cells": len(rows), "trades": tr,
             "cells_mean_positive": sum(1 for x in means if x > 0),
             "sig_pos_raw": sum(1 for _k, r in rows if r[ci["p_pos"]] is not None and r[ci["p_pos"]] < ALPHA),
             "sig_neg_raw": sum(1 for _k, r in rows if r[ci["p_neg"]] is not None and r[ci["p_neg"]] < ALPHA),
             "sig_pos_bh": sum(pos_bh), "sig_neg_bh": sum(neg_bh),
             "sig_pos_bh_cells": [k for (k, _r_), f in zip(rows, pos_bh) if f],
             "median_cell_mean_eq": _r(np.median(means)) if means else None,
             "pooled_mean_eq": _r(sum(r[ci["mean_eq"]] * r[ci["trades"]] for _k, r in rows) / tr) if tr else None,
             "pooled_mean_roe": _r(sum(r[ci["mean_roe"]] * r[ci["trades"]] for _k, r in rows) / tr) if tr else None,
             "pooled_liq_share": _r(sum(r[ci["liq_share"]] * r[ci["trades"]] for _k, r in rows) / tr, 4) if tr else None,
             "busts": sum(r[ci["bust_p1"]] + r[ci["bust_p2"]] for _k, r in rows), "accounts": 2 * len(rows),
             "median_final_multiple": _r(np.median(mults), 4) if mults else None}
        if not arm.startswith("tiers"):
            a["pooled_rules_ok_share"] = _r(sum(r[ci["rules_ok_share"]] * r[ci["trades"]] for _k, r in rows) / tr, 4) \
                if tr else None
        by_arm[arm] = a
        t_out = {}
        for tf in TFS:
            sel = [(i, r) for i, (key, r) in enumerate(rows) if key.endswith("|" + tf)]
            if not sel:
                continue
            ttr = sum(r[ci["trades"]] for _i, r in sel)
            t_out[tf] = {"cells": len(sel), "sig_pos_bh": sum(1 for i, _r_ in sel if pos_bh[i]),
                         "sig_neg_bh": sum(1 for i, _r_ in sel if neg_bh[i]),
                         "pooled_mean_eq": _r(sum(r[ci["mean_eq"]] * r[ci["trades"]] for _i, r in sel) / ttr) if ttr else None,
                         "busts": sum(r[ci["bust_p1"]] + r[ci["bust_p2"]] for _i, r in sel)}
        by_arm_tf[arm] = t_out
    return {"by_arm": by_arm, "by_arm_tf": by_arm_tf, "lines_ko": lines_ko(by_arm)}


def _arm_ko(arm: str) -> str:
    m, k = arm.split("|")
    lev = "지금 단계(50→20배)" if m == "tiers" else f"{m}배 고정"
    return f"{lev}·손절 {float(k):g} ATR"


def lines_ko(by_arm: dict) -> list[str]:
    """Plain sentences written by code (no interpretation beyond the counts)."""
    out = []
    cur = by_arm.get(CURRENT) or {}
    if cur:
        out.append(f"지금 규칙({_arm_ko(CURRENT)}): {cur['cells']}칸 중 거래당 자금 대비 평균이 플러스 {cur['cells_mean_positive']}칸, "
                   f"여러 번 검정 보정(BH 10%) 뒤 유의하게 플러스 {cur['sig_pos_bh']}칸, 유의하게 마이너스 {cur['sig_neg_bh']}칸, "
                   f"계좌 파산 {cur['busts']}/{cur['accounts']}")
    total_pos = sum(a["sig_pos_bh"] for a in by_arm.values())
    if total_pos == 0:
        out.append("24가지 조합 모두에서, 보정 뒤 0보다 유의하게 큰 칸이 하나도 없음")
    else:
        best = sorted(by_arm.items(), key=lambda kv: -kv[1]["sig_pos_bh"])[:3]
        out.append("보정 뒤 유의하게 플러스인 칸이 있는 조합: " + ", ".join(
            f"{_arm_ko(k)} {v['sig_pos_bh']}칸" for k, v in best if v["sig_pos_bh"]) +
            f" (24가지 × 180칸을 함께 보면 일부는 우연일 수 있음, 전체 합 {total_pos}칸)")
    ranked = sorted(((k, v) for k, v in by_arm.items() if v.get("pooled_mean_eq") is not None),
                    key=lambda kv: -kv[1]["pooled_mean_eq"])
    if ranked:
        hi, lo = ranked[0], ranked[-1]
        out.append(f"모든 거래를 합친 거래당 자금 대비 평균: 가장 높은 조합 {_arm_ko(hi[0])} {hi[1]['pooled_mean_eq'] * 100:+.3f}%, "
                   f"가장 낮은 조합 {_arm_ko(lo[0])} {lo[1]['pooled_mean_eq'] * 100:+.3f}% "
                   f"(플러스인 조합 {sum(1 for _k, v in ranked if v['pooled_mean_eq'] > 0)}/{len(ranked)})")
    for m in LEV_MODES:
        if m == "tiers":
            continue
        b = [by_arm.get(f"{m}|{k}") for k in KS]
        b = [x for x in b if x]
        if b:
            out.append(f"{m}배 고정: 파산 계좌 " + ", ".join(f"손절 {k:g} ATR {x['busts']}/{x['accounts']}"
                                                         for k, x in zip(KS, b)))
    return out


def labdata_status(sig_dir: str) -> dict:
    """The lab cache check (labdata_manifest.json in the cache folder, written by ``labdata check``)."""
    try:
        with open(os.path.join(sig_dir, "labdata_manifest.json")) as fh:
            man = json.load(fh)
    except (OSError, ValueError):
        return {"checked": False}
    files = man.get("files") or {}
    main = [v for v in files.values() if v.get("source") == "main"]
    return {"checked": True, "checked_utc": man.get("checked_utc"), "main_files": len(main),
            "main_identical_to_research": bool(main) and all(v.get("status") == "identical" for v in main)}


def run(sig_dir: str, out: str = OUT, procs: int = 4, n_boot: int = N_BOOT, strategies: Optional[list] = None,
        tfs: tuple = TFS) -> dict:
    t0 = time.time()
    if strategies is None:
        z = np.load(os.path.join(sig_dir, f"sig_{tfs[0]}_{COINS[0]}.npz"))
        strategies = sorted(k[3:] for k in z.files if k.startswith("s__"))
    jobs = [(sig_dir, s, tf, n_boot) for tf in tfs for s in strategies]
    cells, secs = {}, []
    if procs > 1:
        with Pool(procs) as p:
            for s, tf, rows, sec in p.imap_unordered(job, jobs):
                cells[f"{s}|{tf}"] = rows
                secs.append(sec)
                print(f"{len(cells)}/{len(jobs)} {s} {tf} {sec:.0f}s", flush=True)
    else:
        for j in jobs:
            s, tf, rows, sec = job(j)
            cells[f"{s}|{tf}"] = rows
            secs.append(sec)
    full = len(strategies) == 36 and tuple(tfs) == TFS
    doc = {"version": VERSION, "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "prereg": {"file": "research/levstop/PREREG_LEVSTOP.md", "sha256": _sha(PREREG)},
           "script_sha256": _sha(os.path.abspath(__file__)),
           "data": {"source": "lab five-year signal cache (Binance USDT-M, paperbot/agents/labdata.py)",
                    **labdata_status(sig_dir)},
           "periods": {p: [a, b] for p, a, b in PERIODS}, "lev_modes": [str(m) for m in LEV_MODES], "stops_atr": list(KS),
           "margin_frac": {str(k): v for k, v in MARGIN_FRAC.items()}, "current_arm": CURRENT,
           "n_boot": n_boot, "alpha": ALPHA, "fdr": FDR, "start_equity": START, "bust_below": BUST_BELOW,
           "grid": "full (36 strategies x 5 timeframes x 24 arms)" if full else
                   f"subset: {len(strategies)} strategies x {list(tfs)}",
           "columns": COLUMNS, "cells": {k: cells[k] for k in sorted(cells)},
           "summary": summarize(cells),
           "runtime_s": {"total": round(time.time() - t0, 1), "job_sum": round(sum(secs), 1), "procs": procs},
           "notes": ["every signal alone for the means and p-values (no position limit), as the 5-year cards",
                     "fixed leverage: every signal enters; liquidation applies (stop clipped to the liquidation price)",
                     "accounts: one per cell, arm and period, $5,000, one position at a time, bust < $10",
                     "p_pos / p_neg: one-sided week-block bootstrap of the mean P&L on equity vs zero; "
                     "BH FDR 10% over the cells of one arm in the summary"]}
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w") as fh:
            json.dump(doc, fh, ensure_ascii=False, separators=(",", ":"))
    return doc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run"])
    ap.add_argument("--signals", required=True)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--n-boot", type=int, default=N_BOOT)
    ap.add_argument("--strategies")
    ap.add_argument("--tfs")
    a = ap.parse_args(argv)
    doc = run(a.signals, a.out, a.procs, a.n_boot, a.strategies.split(",") if a.strategies else None,
              tuple(a.tfs.split(",")) if a.tfs else TFS)
    print(json.dumps(doc["summary"]["lines_ko"], ensure_ascii=False, indent=1))
    print(f"runtime {doc['runtime_s']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
