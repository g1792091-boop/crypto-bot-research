"""Bet size: how fast each candidate grows, and how often it is ruined, at several sizes (owners 2026-10-10: the goal is
fast growth; the size is what decides both the speed and the ruin).

    python research/fullgrid/sizing.py --results DIR --data DIR --work DIR --exchange FILE [--all-picks]

Rules fixed on 2026-10-10 before any full-grid result was seen:
- Sizes: the live rule (quality_v1: best spot 50% margin at 50x, else 40% at 40x; normal spot 30% at 30x, else 20% at
  20x) with every margin fraction times 1/4, 1/2, 1 (the live rule), 1.5 or 2 (at most 98% of the wallet); the
  leverages stay, so the liquidation distance stays and only the size changes.
- Accounts: run.py's account (kernel.account): $5,000, one position at a time over the six coins, compounding, the
  real brackets, liquidation, bust below $10; the select period (2021-01 .. 2023-12) and the test period (2024-01 ..
  2026-09) each from $5,000.
- A month: four weeks drawn at random (with replacement) from the period's weeks, each week's trades kept together
  (each trade's P&L as a fraction of the wallet before it, compounded), 10,000 draws: the chance to end x2, x10, x100
  or more, under half, and under a tenth (as good as ruined), and the median.
- The size to use: the one with the highest median month on the SELECT period among sizes whose chance to end a month
  under half is at most 5%; the test period then shows what that size did on data it was not chosen on.
- Basket: the passing candidates together, the starting money split equally (one sub-account each, each its own
  position), months drawn with the same weeks for all, so they move together as they did.
Candidates: the picks that passed confirm.json (all picks with --all-picks, marked as not passed). DeepSeek ones are
left out unless FULLGRID_DS_MONEY=1 (D11). Output: WORK/sizing.json and sizing_KO.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)

import run as R  # noqa: E402

K = R.K
SCALES = (0.25, 0.5, 1.0, 1.5, 2.0)
MAX_MARGIN = 0.98
WEEKS = 4
DRAWS = 10_000
MAX_HALF = 0.05
SEED = 20261010
DS_MONEY = os.environ.get("FULLGRID_DS_MONEY") == "1"
LEVELS = (("x2", 2.0), ("x10", 10.0), ("x100", 100.0))


def size_vector(scale: float) -> np.ndarray:
    """kernel.settings_vector with the four margin fractions times ``scale`` (at most MAX_MARGIN)."""
    S = K.settings_vector().copy()
    for i in (11, 13, 15, 17):
        S[i] = min(MAX_MARGIN, S[i] * scale)
    return S


def account_trades(data_dir: str, T: dict, ex: dict, lo_ms: int, hi_ms: int, e: int, S: np.ndarray) -> dict:
    """run.account_run with settings ``S``, keeping each closed trade's exit time and P&L / wallet before it."""
    sel = (T["close"] >= lo_ms) & (T["close"] < hi_ms)
    cat, starts, ends = R.all_minutes(data_dir)
    em = []
    for q in np.flatnonzero(sel):
        c = T["coin"][q]
        tsc = cat["ts"][starts[c]:ends[c]]
        j0 = np.searchsorted(tsc, T["close"][q] - 60_000)
        em.append(int(tsc[j0 + 1]) if j0 + 1 < len(tsc) else 2 ** 62)
    qs = np.flatnonzero(sel)
    order = np.lexsort((T["coin"][qs], np.asarray(em, np.int64))) if len(qs) else np.zeros(0, int)
    qs = qs[order]
    st, pnl, ext, rs, _lv, wallet = K.account(
        S, np.stack([ex[s][0] for s in R.SYMBOLS]) if R._same_shape(ex) else R._pad(ex), cat["ts"],
        cat["o"], cat["h"], cat["l"], cat["mo"], cat["mh"], cat["ml"], cat["fund"], np.array(starts, np.int64),
        np.array(ends, np.int64), T["coin"][qs].astype(np.int64), T["close"][qs].astype(np.int64),
        T["side"][qs].astype(np.int64), T["atr"][qs], T["best"][qs], np.array([ex[s][1] for s in R.SYMBOLS]),
        np.array([ex[s][2] for s in R.SYMBOLS]), *K.exit_args(e), T["tp"][qs].astype(float))
    done = (st == 1) & (rs != K.R_OPEN)
    p = pnl[done]
    before = S[10] + np.r_[0.0, np.cumsum(p)[:-1]]
    eq = S[10] + np.cumsum(p)
    peak = np.maximum.accumulate(np.r_[S[10], eq])
    return {"exit_ms": ext[done].astype(np.int64), "ret": p / before, "final_x": float(wallet / S[10]),
            "max_dd": float(np.max(1 - np.r_[S[10], eq] / peak)) if len(eq) else 0.0, "bust": bool(wallet < 10.0),
            "trades": int(done.sum()), "liquidations": int((rs[done] == K.R_LIQ).sum())}


def weekly_growth(exit_ms: np.ndarray, ret: np.ndarray, lo_ms: int, hi_ms: int) -> np.ndarray:
    """Each week's wallet multiple over [lo, hi) (weeks from Monday 00:00 UTC; a week with no trade is 1)."""
    w0, w1 = (lo_ms - R.MONDAY0) // R.WEEK_MS, (hi_ms - 1 - R.MONDAY0) // R.WEEK_MS
    g = np.ones(int(w1 - w0 + 1))
    if len(ret):
        wk = (exit_ms - R.MONDAY0) // R.WEEK_MS - w0
        np.multiply.at(g, np.clip(wk, 0, len(g) - 1).astype(int), np.maximum(1.0 + ret, 0.0))
    return g


def months(G: np.ndarray, draws: int = DRAWS, weeks: int = WEEKS, seed: int = SEED) -> np.ndarray:
    """Month multiples of a basket: ``G`` (weeks, sub-accounts) weekly multiples; equal split, the same weeks drawn
    for every sub-account. A single candidate is one column."""
    G = np.atleast_2d(np.asarray(G, float).T).T if np.ndim(G) == 1 else np.asarray(G, float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, G.shape[0], size=(draws, weeks))
    return np.prod(G[idx], axis=1).mean(axis=1)


def month_summary(m: np.ndarray) -> dict:
    d = {k: float((m >= v).mean()) for k, v in LEVELS}
    d.update({"under_half": float((m < 0.5).mean()), "under_tenth": float((m < 0.1).mean()),
              "median": float(np.median(m))})
    return d


def choose(sizes: dict) -> float | None:
    """The scale with the highest select-period median month among those with P(under half) <= MAX_HALF."""
    ok = [(v["select"]["month"]["median"], -s) for s, v in sizes.items() if v["select"]["month"]["under_half"] <= MAX_HALF]
    return -max(ok)[1] if ok else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--results", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--exchange", required=True)
    ap.add_argument("--all-picks", action="store_true")
    ap.add_argument("--procs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args(argv)
    R.FRAME_DIR[0] = os.path.join(a.work, "frames")
    ex = R.exchange(a.exchange, False)
    if not all(os.path.exists(R.outcome_path(a.work, s, tf)) for s in R.SYMBOLS for tf in R.TFS):
        R.stage_outcomes(a.data, a.work, a.procs, ex)
    with open(os.path.join(a.results, "confirm.json")) as fh:
        rows = json.load(fh)["rows"]
    cands = [r for r in rows if (r.get("pass") or a.all_picks) and (r["kind"] == "core" or DS_MONEY)]
    periods = {"select": R.PERIOD_MS[R.P_SELECT][1:], "test": R.PERIOD_MS[R.P_TEST][1:]}
    out, weekly = [], {s: {p: [] for p in periods} for s in SCALES}
    for r in cands:
        T = R.combo_trades(a.data, a.work, r["kind"], r["name"], r["tf"], R._combo(r), r["exit_index"])
        sizes = {}
        for s in SCALES:
            sizes[s] = {}
            for pname, (lo, hi) in periods.items():
                acc = account_trades(a.data, T, ex, lo, hi, r["exit_index"], size_vector(s))
                g = weekly_growth(acc["exit_ms"], acc["ret"], lo, hi)
                weekly[s][pname].append(g)
                sizes[s][pname] = {k: v for k, v in acc.items() if k not in ("exit_ms", "ret")}
                sizes[s][pname]["month"] = month_summary(months(g))
        out.append({"kind": r["kind"], "name": r["name"], "tf": r["tf"], "rank": r.get("rank"), "exit": r.get("exit"),
                    "passed": bool(r.get("pass")), "sizes": sizes, "chosen": choose(sizes)})
        print(f"[sizing] {r['name']} {r['tf']} #{r.get('rank')}: chosen x{out[-1]['chosen']}", flush=True)
    basket = {}
    if len(out) > 1:
        for s in SCALES:
            basket[s] = {p: month_summary(months(np.column_stack(weekly[s][p]))) for p in periods}
    doc = {"rules": {"scales": SCALES, "weeks": WEEKS, "draws": DRAWS, "max_half": MAX_HALF, "seed": SEED},
           "candidates": out, "basket": basket, "ds_money": DS_MONEY}
    with open(os.path.join(a.work, "sizing.json"), "w") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(a.work, "sizing_KO.md"), "w") as fh:
        fh.write(report_ko(doc))
    print(f"[sizing] {len(out)} candidates -> {a.work}/sizing_KO.md", flush=True)
    return 0


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%" if x >= 0.01 or x == 0 else "<1%"


def report_ko(doc: dict) -> str:
    L = ["# 한 번에 얼마씩 걸까 (베팅 크기)", "",
         "크기 = 지금 규칙(좋은 자리 증거금 50%·50배 …)의 증거금을 몇 배로 하느냐. 레버리지는 그대로입니다.",
         "'한 달'은 그 기간의 주(週)를 4개 무작위로 뽑아 이어 붙인 것을 1만 번 해 본 결과입니다. 고르기 기간(2021~2023)으로",
         "크기를 정하고(반토막 확률 5% 이하 중 가장 잘 크는 것), 시험 기간(2024~2026-09)은 그 크기가 처음 보는 자료에서",
         "어땠는지입니다. 과거가 그대로 반복된다는 보장은 없습니다.", ""]
    for c in doc["candidates"]:
        tag = "" if c["passed"] else " (통과 못 한 값, 참고용)"
        L += [f"## {c['name']} {c['tf']} #{c['rank']} ({c['exit']}){tag}", "",
              f"정한 크기: {'없음 (모든 크기가 반토막 위험 5% 넘음)' if c['chosen'] is None else 'x' + format(c['chosen'], 'g')}", "",
              "| 크기 | 기간 | 끝 잔고 | 최대 낙폭 | 파산 | 한 달 중앙값 | x2 | x10 | x100 | 반토막 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for s, v in c["sizes"].items():
            for p in ("select", "test"):
                a, m = v[p], v[p]["month"]
                L.append(f"| x{float(s):g} | {'고르기' if p == 'select' else '시험'} | x{a['final_x']:.2f} | {_pct(a['max_dd'])} | "
                         f"{'예' if a['bust'] else '아니오'} | x{m['median']:.2f} | {_pct(m['x2'])} | {_pct(m['x10'])} | "
                         f"{_pct(m['x100'])} | {_pct(m['under_half'])} |")
        L.append("")
    if doc["basket"]:
        L += ["## 통과한 후보를 같이 돌리면 (돈을 똑같이 나눠서)", "",
              "| 크기 | 기간 | 한 달 중앙값 | x2 | x10 | x100 | 반토막 |", "|---|---|---|---|---|---|---|"]
        for s, v in doc["basket"].items():
            for p in ("select", "test"):
                m = v[p]
                L.append(f"| x{float(s):g} | {'고르기' if p == 'select' else '시험'} | x{m['median']:.2f} | {_pct(m['x2'])} | "
                         f"{_pct(m['x10'])} | {_pct(m['x100'])} | {_pct(m['under_half'])} |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())
