"""Five-year exit-style comparison: stepped lock ("ladder") vs fixed take-profit (pre-registered in
research/exitstyle/PREREG_EXITSTYLE.md, written and hashed before this script ran).

    python3 research/exitstyle/exitstyle.py run --signals DIR [--out research/exitstyle/out/exitstyle.json]
        [--procs 4] [--n-boot 2000] [--strategies A,B] [--tfs 15m,1h]

Read-only research: reuses research/levstop/levstop.py (signal windows, sizing, account, BH, bootstrap) and
research/strategy_profiles/profiles.py (``_sizer``, the bar path of ``_scan``) without modifying them.

Arms (same signals, same entries, same sizes: the current tiers sizing with a 2 x ATR14 stop; only the exit differs):
  ladder        the current stepped lock (== levstop ``tiers|2.0``, checked cell by cell against levstop.json)
  tp1R..tp3R    stop stays at 2 ATR, no lock, take-profit at raw entry + side x R x (2 x ATR14)
  ladder_tp2R   the lock plus a 2R take-profit cap
TP fill: at the TP price with the taker fee and slippage (no favourable-gap credit). A bar that touches both the
stop / lock / liquidation and the TP counts as a stop (conservative). Reason codes: 0 stop, 1 lock, 2 liquidation,
3 open, 4 take-profit.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
import time
from multiprocessing import Pool
from typing import Optional

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research", "levstop"))
import levstop as LV  # noqa: E402

OUT = os.path.join(HERE, "out", "exitstyle.json")
SUMMARY = os.path.join(HERE, "out", "SUMMARY_KO.md")
PREREG = os.path.join(HERE, "PREREG_EXITSTYLE.md")
LEVSTOP_JSON = os.path.join(ROOT, "research", "levstop", "out", "levstop.json")
VERSION = 1
K = 2.0
BASE = "ladder"
ARMS = {"ladder": (True, None), "tp1R": (False, 1.0), "tp1.5R": (False, 1.5), "tp2R": (False, 2.0),
        "tp3R": (False, 3.0), "ladder_tp2R": (True, 2.0)}
CANDIDATES = ("tp1R", "tp1.5R", "tp2R", "tp3R", "ladder_tp2R")
TFS = LV.TFS
PRIMARY = ("15m", "30m", "1h", "4h")
CONTEXT = ("5m",)
MIN_PAIRED = 30
COLUMNS = ["trades", "mean_roe", "mean_eq", "mean_eq_p1", "mean_eq_p2", "win_rate", "tp_share", "lock_share",
           "liq_share", "mean_held", "bust_p1", "bust_p2", "mult_p1", "mult_p2",
           "paired_n", "paired_n_p1", "paired_n_p2", "diff", "diff_p1", "diff_p2", "p_better", "p_worse"]


# ---------------------------------------------------------------- exits
def scan(b, idx, side, lev, liq_frac, H, n, f_bar, k_stop=K, tp_r=None, ladder=True):
    """profiles._scan with an optional fixed take-profit and an optional ladder. With ``ladder=True, tp_r=None``
    it is the same computation as profiles._scan (checked bit for bit in the run and the tests)."""
    RB = LV._profiles().RB
    lad = RB.LADDER
    rt, fee, slip = RB.SETTINGS.round_trip_cost, RB.SETTINGS.taker_fee, RB.SETTINGS.slippage_frac
    m = len(idx)
    off = np.arange(1, H + 1)
    J = idx[:, None] + off[None, :]
    valid = J < n
    Jc = np.minimum(J, n - 1)
    o, h, lo, c = b["o"][Jc], b["h"][Jc], b["l"][Jc], b["c"][Jc]
    raw = b["o"][idx + 1]
    a = b["atr"][idx]
    fill = raw * (1 + side * slip)
    stop0 = raw - side * k_stop * a
    liq = fill * (1 - side * liq_frac)
    s = side[:, None]
    fav = np.where(s == 1, h, -lo)                        # favourable extreme, sign-adjusted
    if ladder:
        fund = f_bar * off[None, :]
        best_px = s * np.maximum.accumulate(np.concatenate([(side * fill)[:, None], fav], axis=1), axis=1)[:, 1:]
        roe_best = lev[:, None] * (s * (best_px / fill[:, None] - 1) - rt - fund)
        first = lad.first_lock + lad.trigger_gap
        nstep = np.floor((roe_best - first) / lad.step + 1e-9)
        lock_roe = np.where(roe_best >= first - 1e-12, lad.first_lock + lad.step * nstep, np.nan)
        lock_px = fill[:, None] * (1 + s * (lock_roe / lev[:, None] + rt + fund))
        lp = np.where(np.isnan(lock_px), -np.inf, s * lock_px)
        lock_cum = np.maximum.accumulate(np.concatenate([np.full((m, 1), -np.inf), lp], axis=1), axis=1)[:, :-1]
        stop_eff = np.maximum((side * stop0)[:, None], lock_cum)
    else:
        stop_eff = np.broadcast_to((side * stop0)[:, None], (m, H))
    adverse = np.where(s == 1, lo, -h)
    hit_s = (adverse <= stop_eff) & valid
    if tp_r is None:
        tp = np.full(m, np.nan)
        hit_t = np.zeros_like(hit_s)
    else:
        tp = raw + side * float(tp_r) * k_stop * a
        hit_t = (fav >= (side * tp)[:, None]) & valid & ~hit_s       # same bar: the stop comes first
    hit = hit_s | hit_t
    done = hit.any(axis=1)
    q = np.where(done, hit.argmax(axis=1), np.minimum(H, np.maximum(valid.sum(axis=1), 1)) - 1)
    r = np.arange(m)
    is_tp = done & hit_t[r, q]
    st = side * stop_eff[r, q]
    oq = o[r, q]
    gap = (side * oq) <= (side * st)
    liq_gap = done & ~is_tp & gap & ((side * oq) <= (side * liq))
    exit_raw = np.where(done, np.where(is_tp, tp, np.where(gap, oq, st)), c[r, q])
    exit_px = np.where(liq_gap, liq, exit_raw * (1 - side * slip))
    held = q + 1
    roe = lev * (side * (exit_px / fill - 1) - fee * (1 + exit_px / fill) - f_bar * held)
    roe = np.where(liq_gap, -1.0, np.maximum(roe, -1.0))
    is_lock = done & ~is_tp & ~liq_gap & (side * st > side * stop0 + 1e-12)
    reason = np.where(~done, 3, np.where(liq_gap, 2, np.where(is_tp, 4, np.where(is_lock, 1, 0))))
    return dict(done=done, held=held, roe=roe, reason=reason)


def sizing(idx, side, b, k=K):
    """The current tiers sizing (profiles._sizer(k)) of the signals: (lev, liq_frac)."""
    raw = b["o"][idx + 1]
    sizer = LV._profiles()._sizer(k)
    ll = np.array([sizer(int(s), float(x)) for s, x in zip(side, b["atr"][idx] / raw)], float).reshape(-1, 2)
    return ll[:, 0], ll[:, 1]


def outcomes(b, idx, side, tf, arm, lev=None, liq_frac=None) -> dict:
    """Per-signal outcomes of one arm in the look-ahead passes of levstop.outcomes (64, 512, 4096 bars)."""
    from paperbot import sweepsig
    RB = LV._profiles().RB
    ladder, tp_r = ARMS[arm]
    n = len(b["ts"])
    f_bar = RB.FUNDING_8H * sweepsig.lib().tf_minutes(tf) / 480.0
    m = len(idx)
    if lev is None:
        lev, liq_frac = sizing(idx, side, b)
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
            r = scan(b, idx[sel], side[sel], lev[sel], liq_frac[sel], H, n, f_bar, K, tp_r=tp_r, ladder=ladder)
            keep = r["done"] | (H == 4096) | (idx[sel] + H >= n - 1)
            for x in ("held", "roe", "reason"):
                res[x][sel[keep]] = r[x][keep]
            nxt.append(sel[~keep])
        todo = np.concatenate(nxt) if nxt else np.zeros(0, int)
    reason = res["reason"]
    done = sized & np.isfinite(reason) & (reason != 3)
    return dict(lev=lev, roe=res["roe"], reason=reason, held=res["held"], done=done)


def same_arrays(o1: dict, o2: dict) -> bool:
    """Bit-for-bit equality of the outcome arrays (NaN equal to NaN)."""
    return all(np.array_equal(np.asarray(o1[x], float), np.asarray(o2[x], float), equal_nan=True)
               for x in ("lev", "roe", "reason", "held", "done"))


# ---------------------------------------------------------------- one strategy x timeframe
def signals(sig_dir: str, strategy: str, tf: str) -> list:
    """The signals of levstop.job: [(coin index, bars, idx, side, ts, period)]."""
    from paperbot import sweepsig
    RB = LV._profiles().RB
    L = sweepsig.lib()
    p_edges = [(LV._ns(a), LV._ns(e)) for _p, a, e in LV.PERIODS]
    coins = []
    for ci, c in enumerate(LV.COINS):
        got = LV._bars(sig_dir, tf).get(c)
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
    return coins


def _cat(per_coin: list) -> dict:
    keys = ("ts", "coin", "exit_ts", "period", "lev", "roe", "reason", "done", "held")
    return {x: np.concatenate([c[x] for c in per_coin]) if per_coin else np.zeros(0) for x in keys}


def arm_row(cat: dict, base: dict, strategy: str, tf: str, arm: str, n_boot: int) -> tuple[list, dict]:
    """The COLUMNS row of one arm and the unrounded sums the pooled summary needs."""
    from paperbot.agents.labtests import week_of
    d = cat["done"].astype(bool)
    mf = np.array([LV.MARGIN_FRAC.get(int(round(x)), np.nan) if x > 0 else np.nan for x in cat["lev"]], float)
    eq_all = cat["roe"] * mf
    eq_b_all = base["roe"] * mf
    per_all = cat["period"].astype(int)
    eq, per, ts = eq_all[d], per_all[d], cat["ts"][d]
    n = int(d.sum())
    sums = {"n": n, "s": float(eq.sum()) if n else 0.0}
    if not n:
        return [0] + [None] * (len(COLUMNS) - 1), sums
    acc = []
    for pid, _a, _b in LV.PERIODS:
        s = per == int(pid)
        acc.append(LV.account(ts[s], cat["coin"][d][s], cat["exit_ts"][d][s], eq[s]))
    rs = cat["reason"][d]
    mp = [float(np.mean(eq[per == int(p)])) if (per == int(p)).any() else None for p, _a, _b in LV.PERIODS]
    # paired with the ladder on the same signals (both closed)
    pd_ = d & base["done"].astype(bool)
    diff = eq_all[pd_] - eq_b_all[pd_]
    pper = per_all[pd_]
    np_ = int(pd_.sum())
    sums.update(pn=np_)
    for p, _a, _b in LV.PERIODS:
        sel = pper == int(p)
        sums[f"pn{p}"] = int(sel.sum())
        sums[f"pa{p}"] = float(eq_all[pd_][sel].sum())
        sums[f"pb{p}"] = float(eq_b_all[pd_][sel].sum())
    dm = [float(np.mean(diff[pper == int(p)])) if (pper == int(p)).any() else None for p, _a, _b in LV.PERIODS]
    p_b = p_w = None
    if arm != BASE and np_:
        week = week_of(cat["ts"][pd_])
        p_b = LV.boot_p(week, diff, n_boot, LV._seed(strategy, tf, arm, "better"))
        p_w = LV.boot_p(week, -diff, n_boot, LV._seed(strategy, tf, arm, "worse"))
    r = LV._r
    row = [n, r(np.mean(cat["roe"][d]), 6), r(np.mean(eq), 6), r(mp[0], 6), r(mp[1], 6), r(np.mean(cat["roe"][d] > 0), 4),
           r(np.mean(rs == 4), 4), r(np.mean(rs == 1), 4), r(np.mean(rs == 2), 4), r(np.mean(cat["held"][d]), 4),
           int(acc[0][0]), int(acc[1][0]), r(acc[0][1], 4), r(acc[1][1], 4),
           np_, sums["pn1"], sums["pn2"], r(np.mean(diff), 6) if np_ else None, r(dm[0], 6), r(dm[1], 6),
           r(p_b, 4), r(p_w, 4)]
    return row, sums


def job(args) -> tuple:
    """All arms of one strategy x timeframe: ({arm: row}, {arm: sums}, levstop tiers|2.0 row, check, seconds)."""
    sig_dir, strategy, tf, n_boot = args
    t0 = time.time()
    coins = signals(sig_dir, strategy, tf)
    per_arm = {a: [] for a in ARMS}
    lad_check = True
    for ci, b, idx, side, ts, period in coins:
        lev, liq_frac = sizing(idx, side, b)
        ref = LV.outcomes(b, idx, side, tf, "tiers", K)                 # levstop's own ladder, unmodified
        for arm in ARMS:
            o = outcomes(b, idx, side, tf, arm, lev, liq_frac)
            if arm == BASE:
                ok = same_arrays(o, {**ref, "lev": ref["lev"]})
                lad_check = lad_check and ok
                o = {x: ref[x] for x in ("lev", "roe", "reason", "held", "done")}
            held = np.nan_to_num(o["held"], nan=0).astype(int)
            ex = b["ts"][np.minimum(idx + held, len(b["ts"]) - 1)]
            per_arm[arm].append(dict(ts=ts, coin=np.full(len(idx), ci), exit_ts=ex, period=period, **o,
                                     rules_ok=o["lev"] > 0))
    lv_row = LV.cell_stats(per_arm[BASE], strategy, tf, LV.CURRENT, "tiers", n_boot)
    base = _cat(per_arm[BASE])
    rows, sums = {}, {}
    for arm in ARMS:
        rows[arm], sums[arm] = arm_row(_cat(per_arm[arm]), base, strategy, tf, arm, n_boot)
    return strategy, tf, rows, sums, lv_row, lad_check, time.time() - t0


# ---------------------------------------------------------------- summary
def _pool(keys: list, sums: dict, arm: str) -> dict:
    tot = {x: 0.0 for x in ("n", "s", "pn", "pn1", "pn2", "pa1", "pb1", "pa2", "pb2")}
    for k in keys:
        for x in tot:
            tot[x] += sums[k][arm].get(x, 0.0)
    out = {"trades": int(tot["n"]), "pooled_mean_eq": LV._r(tot["s"] / tot["n"], 6) if tot["n"] else None,
           "paired_trades": int(tot["pn"])}
    for p in ("1", "2"):
        n = tot[f"pn{p}"]
        a = tot[f"pa{p}"] / n if n else None
        bb = tot[f"pb{p}"] / n if n else None
        out[f"paired_p{p}"] = {"n": int(n), "arm": LV._r(a, 6), "ladder": LV._r(bb, 6),
                               "diff": LV._r(a - bb, 6) if n else None}
    n = tot["pn1"] + tot["pn2"]
    out["paired_all"] = {"n": int(n), "arm": LV._r((tot["pa1"] + tot["pa2"]) / n, 6) if n else None,
                         "ladder": LV._r((tot["pb1"] + tot["pb2"]) / n, 6) if n else None,
                         "diff": LV._r((tot["pa1"] + tot["pa2"] - tot["pb1"] - tot["pb2"]) / n, 6) if n else None}
    return out


def scope_summary(cells: dict, sums: dict, tfs: tuple) -> dict:
    ci = {c: i for i, c in enumerate(COLUMNS)}
    keys = sorted(k for k in cells if k.split("|")[1] in tfs)
    out = {}
    for arm in ARMS:
        rows = [(k, cells[k][arm]) for k in keys if cells[k][arm][ci["trades"]]]
        a = {"cells": len(rows), **_pool([k for k, _r in rows], sums, arm),
             "cells_mean_positive": sum(1 for _k, r in rows if r[ci["mean_eq"]] > 0),
             "busts": sum(r[ci["bust_p1"]] + r[ci["bust_p2"]] for _k, r in rows), "accounts": 2 * len(rows),
             "mean_held": LV._r(sum(r[ci["mean_held"]] * r[ci["trades"]] for _k, r in rows) /
                                max(1, sum(r[ci["trades"]] for _k, r in rows)), 4),
             "tp_share": LV._r(sum(r[ci["tp_share"]] * r[ci["trades"]] for _k, r in rows) /
                               max(1, sum(r[ci["trades"]] for _k, r in rows)), 4),
             "win_rate": LV._r(sum(r[ci["win_rate"]] * r[ci["trades"]] for _k, r in rows) /
                               max(1, sum(r[ci["trades"]] for _k, r in rows)), 4)}
        if arm != BASE:
            big = [(k, r) for k, r in rows if r[ci["paired_n"]] >= MIN_PAIRED]
            better = LV.bh([r[ci["p_better"]] for _k, r in big])
            worse = LV.bh([r[ci["p_worse"]] for _k, r in big])
            a.update(cells_ge30=len(big), sig_better_bh=sum(better), sig_worse_bh=sum(worse),
                     sig_better_cells=[k for (k, _r), f in zip(big, better) if f],
                     cells_diff_positive=sum(1 for _k, r in big if r[ci["diff"]] is not None and r[ci["diff"]] > 0))
            t_out = {}
            for tf in tfs:
                sel = [i for i, (k, _r) in enumerate(big) if k.endswith("|" + tf)]
                tk = [k for k, _r in rows if k.endswith("|" + tf)]
                pool = _pool(tk, sums, arm)
                t_out[tf] = {"cells_ge30": len(sel), "sig_better_bh": sum(1 for i in sel if better[i]),
                             "sig_worse_bh": sum(1 for i in sel if worse[i]),
                             "paired_diff": pool["paired_all"]["diff"], "pooled_mean_eq": pool["pooled_mean_eq"],
                             "busts": sum(r[ci["bust_p1"]] + r[ci["bust_p2"]] for k, r in rows if k.endswith("|" + tf))}
            a["by_tf"] = t_out
        out[arm] = a
    return out


def decide(primary: dict) -> dict:
    """The pre-registered rule (PREREG_EXITSTYLE.md section 5)."""
    base = primary[BASE]
    res = {}
    for arm in CANDIDATES:
        a = primary[arm]
        d1, d2 = a["paired_p1"]["diff"], a["paired_p2"]["diff"]
        ca = d1 is not None and d2 is not None and d1 > 0 and d2 > 0
        cb = a["cells_ge30"] > 0 and a["sig_better_bh"] >= a["cells_ge30"] / 2.0
        cc = a["busts"] <= base["busts"]
        res[arm] = {"a_both_periods": ca, "b_half_cells_sig": cb, "c_no_more_busts": cc, "pass": ca and cb and cc}
    passing = [k for k, v in res.items() if v["pass"]]
    pick = max(passing, key=lambda k: primary[k]["paired_all"]["diff"]) if passing else None
    return {"arms": res, "passing": passing, "recommend": pick or BASE,
            "recommendation": f"switch to {pick}" if pick else "keep the ladder"}


# ---------------------------------------------------------------- Korean summary
ARM_KO = {"ladder": "계단 잠금 (지금)", "tp1R": "고정 익절 1R", "tp1.5R": "고정 익절 1.5R", "tp2R": "고정 익절 2R",
          "tp3R": "고정 익절 3R", "ladder_tp2R": "계단 잠금 + 2R 상한"}


def _pct(x, d=3):
    return "–" if x is None else f"{x * 100:+.{d}f}%"


def summary_ko(doc: dict) -> str:
    P, C, dec = doc["summary"]["primary"], doc["summary"]["context_5m"], doc["summary"]["decision"]
    lines = ["# 익절 방식 5년 비교: 계단 잠금 vs 고정 익절", "",
             f"만든 날: {doc['generated'][:10]} · 사전 등록: `research/exitstyle/PREREG_EXITSTYLE.md` "
             f"(해시 `{(doc['prereg']['sha256'] or '')[:12]}…`, 결과 보기 전에 고정) · 이 파일은 코드가 썼습니다.", "",
             "## 한 줄 결론", ""]
    if dec["recommend"] == BASE:
        lines.append("**계단 잠금을 유지하세요.** 미리 정한 세 조건을 모두 만족한 고정 익절 방식이 없습니다.")
    else:
        lines.append(f"**미리 정한 규칙상 '{ARM_KO[dec['recommend']]}'로 바꾸는 것을 권합니다.** "
                     "(여러 방식을 본 데서 오는 선택 편향이 있을 수 있음)")
    base = P[BASE]
    lines += ["", f"- 지금 방식의 5년 거래당 평균(자금 대비): **{_pct(base['pooled_mean_eq'])}** "
              f"({base['trades']:,}건, 15분·30분·1시간·4시간 {base['cells']}칸). "
              f"평균이 플러스인 칸 {base['cells_mean_positive']}/{base['cells']}, 계좌 파산 {base['busts']}/{base['accounts']}.",
              "- 익절 방식은 결과의 모양만 바꿉니다. 마이너스 매매법이 플러스가 되는 것은 처음부터 기대하지 않았습니다.", "",
              "## 방식별 표 (주 대상: 15분·30분·1시간·4시간)", "",
              "숫자는 거래 한 번에 자금의 몇 %를 벌거나 잃었는지의 평균입니다. '같은 신호 비교'는 두 방식 모두 끝난 같은 신호들에서 잰 것입니다.", "",
              "| 방식 | 거래당 평균 | 같은 신호, 1기 (방식 / 지금) | 같은 신호, 2기 (방식 / 지금) | 평균 플러스 칸 | 지금보다 유의하게 나음 / 나쁨 (30건 이상 칸) | 익절로 끝난 비율 | 승률 | 파산 계좌 |",
              "|---|---|---|---|---|---|---|---|---|"]
    for arm in ARMS:
        a = P[arm]
        p1, p2 = a["paired_p1"], a["paired_p2"]
        sig = "기준" if arm == BASE else f"{a['sig_better_bh']} / {a['sig_worse_bh']} (총 {a['cells_ge30']}칸)"
        lines.append(f"| {ARM_KO[arm]} | {_pct(a['pooled_mean_eq'])} | {_pct(p1['arm'])} / {_pct(p1['ladder'])} | "
                     f"{_pct(p2['arm'])} / {_pct(p2['ladder'])} | {a['cells_mean_positive']}/{a['cells']} | {sig} | "
                     f"{a['tp_share'] * 100:.0f}% | {a['win_rate'] * 100:.0f}% | {a['busts']}/{a['accounts']} |")
    lines += ["", "## 미리 정한 판정 규칙에 따른 결과", "",
              "바꾸라고 권하려면 셋 다 만족해야 합니다: (a) 같은 신호 평균이 1기·2기 모두 지금보다 높음, "
              "(b) 보정(BH 10%) 뒤 유의하게 나은 칸이 30건 이상 칸의 절반 이상, (c) 파산 계좌가 지금보다 많지 않음.", "",
              "| 방식 | (a) 두 기간 모두 높음 | (b) 절반 이상 칸 유의 | (c) 파산 안 늘어남 | 통과 |", "|---|---|---|---|---|"]
    yn = {True: "예", False: "아니오"}
    for arm in CANDIDATES:
        r = dec["arms"][arm]
        a = P[arm]
        lines.append(f"| {ARM_KO[arm]} | {yn[r['a_both_periods']]} ({_pct(a['paired_p1']['diff'])}, {_pct(a['paired_p2']['diff'])}) | "
                     f"{yn[r['b_half_cells_sig']]} ({a['sig_better_bh']}/{a['cells_ge30']}) | "
                     f"{yn[r['c_no_more_busts']]} ({a['busts']} vs {base['busts']}) | **{yn[r['pass']]}** |")
    lines += ["", "## 시간봉별 (같은 신호에서 지금 방식과의 차이, 거래당 자금 대비)", "",
              "| 방식 | " + " | ".join(PRIMARY) + " |", "|---|" + "---|" * len(PRIMARY)]
    for arm in CANDIDATES:
        t = P[arm]["by_tf"]
        lines.append(f"| {ARM_KO[arm]} | " + " | ".join(
            f"{_pct(t[tf]['paired_diff'])} (나음 {t[tf]['sig_better_bh']}, 나쁨 {t[tf]['sig_worse_bh']} / {t[tf]['cells_ge30']}칸)"
            if tf in t else "–" for tf in PRIMARY) + " |")
    if C.get(BASE, {}).get("cells"):
        lines += ["", "## 참고: 5분봉 (v3에서 빠짐, 판정에 넣지 않음)", "",
                  "| 방식 | 거래당 평균 | 같은 신호 차이 (1기 / 2기) | 유의하게 나음 / 나쁨 | 파산 |", "|---|---|---|---|---|"]
        for arm in ARMS:
            a = C[arm]
            sig = "기준" if arm == BASE else f"{a['sig_better_bh']} / {a['sig_worse_bh']} ({a['cells_ge30']}칸)"
            dd = "–" if arm == BASE else f"{_pct(a['paired_p1']['diff'])} / {_pct(a['paired_p2']['diff'])}"
            lines.append(f"| {ARM_KO[arm]} | {_pct(a['pooled_mean_eq'])} | {dd} | {sig} | {a['busts']}/{a['accounts']} |")
    chk = doc["self_test"]
    lines += ["", "## 읽을 때 주의", "",
              f"- 기준(계단 잠금) 숫자는 앞 연구(levstop `tiers|2.0`)와 칸마다 똑같이 나오는지 확인했습니다: "
              f"{chk['levstop_rows_identical']}/{chk['levstop_rows_compared']}칸 동일, 계산 경로 동일 {chk['scan_identical']}.",
              "- 봉 안에서 손절과 익절이 둘 다 닿으면 손절이 먼저라고 봤습니다(고정 익절에 불리한 쪽). 익절도 수수료·슬리피지를 냈습니다"
              "(지정가 익절이면 조금 더 싸질 수 있음). 그래서 고정 익절 쪽 숫자는 약간 보수적입니다.",
              "- 신호마다 따로 계산한 평균입니다(포지션 제한 없음). 파산은 한 번에 한 포지션 계좌로 따로 봤습니다.",
              "- 5년 결과는 실거래 30일 실험의 판정과 별개입니다. 규칙을 바꾸려면 두 분 결정과 규칙 버전 올림이 필요합니다.",
              f"- 계산 시간 {doc['runtime_s']['total'] / 60:.1f}분, 부트스트랩 {doc['n_boot']}번."]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- run
def _levstop_rows() -> Optional[dict]:
    try:
        with open(LEVSTOP_JSON) as fh:
            d = json.load(fh)
        return {"n_boot": d["n_boot"], "rows": {k: v.get(LV.CURRENT) for k, v in d["cells"].items()}}
    except (OSError, ValueError, KeyError):
        return None


def run(sig_dir: str, out: str = OUT, procs: int = 4, n_boot: int = LV.N_BOOT, strategies: Optional[list] = None,
        tfs: tuple = TFS, summary_path: Optional[str] = SUMMARY) -> dict:
    t0 = time.time()
    if strategies is None:
        z = np.load(os.path.join(sig_dir, f"sig_{tfs[0]}_{LV.COINS[0]}.npz"))
        strategies = sorted(k[3:] for k in z.files if k.startswith("s__"))
    jobs = [(sig_dir, s, tf, n_boot) for tf in tfs for s in strategies]
    cells, sums, lv_rows, checks, secs = {}, {}, {}, {}, []

    def take(res):
        s, tf, rows, sm, lv_row, ok, sec = res
        key = f"{s}|{tf}"
        cells[key], sums[key], lv_rows[key], checks[key] = rows, sm, lv_row, ok
        secs.append(sec)
        print(f"{len(cells)}/{len(jobs)} {s} {tf} {sec:.0f}s", flush=True)

    if procs > 1:
        with Pool(procs) as p:
            for res in p.imap_unordered(job, jobs):
                take(res)
    else:
        for j in jobs:
            take(job(j))
    ref = _levstop_rows()
    compared = identical = 0
    mism = []
    if ref is not None:
        for key, row in lv_rows.items():
            want = ref["rows"].get(key)
            if want is None:
                continue
            got = json.loads(json.dumps(row))
            if ref["n_boot"] != n_boot:          # p-values depend on the resample count: compare the rest
                skip = {LV.COLUMNS.index("p_pos"), LV.COLUMNS.index("p_neg")}
                got = [x for i, x in enumerate(got) if i not in skip]
                want = [x for i, x in enumerate(want) if i not in skip]
            compared += 1
            if got == want:
                identical += 1
            else:
                mism.append(key)
    self_test = {"scan_identical": f"{sum(checks.values())}/{len(checks)}", "scan_all_identical": all(checks.values()),
                 "levstop_rows_compared": compared, "levstop_rows_identical": identical, "levstop_mismatch": mism,
                 "levstop_n_boot": ref["n_boot"] if ref else None}
    if not all(checks.values()) or mism:
        raise RuntimeError(f"ladder arm does not reproduce levstop tiers|2.0: {self_test}")
    prim = tuple(t for t in tfs if t in PRIMARY)
    ctx = tuple(t for t in tfs if t in CONTEXT)
    primary = scope_summary(cells, sums, prim)
    summary = {"primary": primary, "context_5m": scope_summary(cells, sums, ctx) if ctx else {},
               "decision": decide(primary) if prim else None}
    full = len(strategies) == 36 and tuple(tfs) == TFS
    doc = {"version": VERSION, "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "prereg": {"file": "research/exitstyle/PREREG_EXITSTYLE.md", "sha256": LV._sha(PREREG)},
           "script_sha256": LV._sha(os.path.abspath(__file__)), "levstop_script_sha256": LV._sha(LV.__file__),
           "data": {"source": "lab five-year signal cache (Binance USDT-M, paperbot/agents/labdata.py)",
                    **LV.labdata_status(sig_dir)},
           "periods": {p: [a, b] for p, a, b in LV.PERIODS}, "arms": {k: {"ladder": v[0], "tp_r": v[1]} for k, v in ARMS.items()},
           "stop_atr": K, "baseline": BASE, "primary_tfs": list(PRIMARY), "context_tfs": list(CONTEXT),
           "n_boot": n_boot, "fdr": LV.FDR, "min_paired": MIN_PAIRED, "start_equity": LV.START, "bust_below": LV.BUST_BELOW,
           "grid": "full (36 strategies x 5 timeframes x 6 arms)" if full else f"subset: {len(strategies)} strategies x {list(tfs)}",
           "self_test": self_test, "columns": COLUMNS, "cells": {k: cells[k] for k in sorted(cells)},
           "summary": summary,
           "runtime_s": {"total": round(time.time() - t0, 1), "job_sum": round(sum(secs), 1), "procs": procs},
           "notes": ["every signal alone for the means and p-values (no position limit), as levstop",
                     "paired: arm minus ladder P&L on equity on the same signals, both closed",
                     "p_better / p_worse: one-sided week-block bootstrap of the mean paired difference; BH FDR 10% per arm "
                     "over primary cells with >= 30 paired trades",
                     "TP filled at the TP price with taker fee and slippage; a bar touching both stop and TP is a stop",
                     "accounts: one per cell, arm and period, $5,000, one position at a time, bust < $10"]}
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w") as fh:
            json.dump(doc, fh, ensure_ascii=False, separators=(",", ":"))
    if summary_path and prim:
        os.makedirs(os.path.dirname(os.path.abspath(summary_path)), exist_ok=True)
        with open(summary_path, "w") as fh:
            fh.write(summary_ko(doc))
    return doc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run"])
    ap.add_argument("--signals", required=True)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--summary", default=SUMMARY)
    ap.add_argument("--procs", type=int, default=4)
    ap.add_argument("--n-boot", type=int, default=LV.N_BOOT)
    ap.add_argument("--strategies")
    ap.add_argument("--tfs")
    a = ap.parse_args(argv)
    doc = run(a.signals, a.out, a.procs, a.n_boot, a.strategies.split(",") if a.strategies else None,
              tuple(a.tfs.split(",")) if a.tfs else TFS, a.summary)
    print(json.dumps(doc["summary"]["decision"], ensure_ascii=False, indent=1))
    print(json.dumps(doc["self_test"], ensure_ascii=False))
    print(f"runtime {doc['runtime_s']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
