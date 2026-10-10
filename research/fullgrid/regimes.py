"""Phase 2, step 1: how each picked custom value did by market state, on the SELECT period only (2021-2023).

    python research/fullgrid/regimes.py --results DIR --data DIR --work DIR --exchange FILE

The owners asked (2026-10-10) whether a strategy needs different numbers on weekends and weekdays, in ranging and
trending markets. This breaks each pick of the full-grid run (and its cell's default: live numbers, live exit) down by
market state. It reads only the select period, where the picks were chosen anyway; the test period (2024-01 ..
2026-09) stays sealed for checking any market-specific rule this suggests, and the 2020 extra period is not read.
It selects nothing and passes nothing: it prints where a pick earned its select-period result.

States, fixed on 2026-10-10 before any full-grid result was seen, taken from code the bots already use:
- 요일 (paperbot.breakdown): weekend = Saturday or Sunday in KST at the signal bar's close (the entry), else weekday.
- 장세 (paperbot.dash.tools.regime5y, the dashboard's 장세 스위치, docs/regime5y.md): the signal bar's regime on the
  strategy's own chart: 급변장 (ATR% in the top 20% of its trailing year), else 추세장 (ADX14 >= 25 and EMA50 slope
  over 10 bars >= 0.5 ATR), else 횡보장 (ADX14 < 20), else 보통. Chosen over demobot.regime's EMA50 slope alone:
  a crossover strategy enters where that slope is flat (a rehearsal run's N01_ST_EMA 4h picks entered at slopes
  between -0.4 and +0.25 only, all "range").
- 큰 흐름: the last completed UTC day's close against the EMA200 of daily closes: 위 (상승장) or 아래 (하락장).
- 변동성 (demobot.regime): 15m ATR14 / close against its previous 90 days: 큼 above the 70th percentile, 작음 below
  the 30th, else 보통.

Inputs: DIR of the results pack (select.json), the 1m data (data.py), the leverage table. The outcome tables are
rebuilt in --work when missing (run.py outcomes, about 15 minutes on 4 cores). Output: --work/regimes.json and
regimes_KO.md. DeepSeek rows keep counts only (D11), unless FULLGRID_DS_MONEY=1.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import run as R  # noqa: E402
from demobot import regime as G  # noqa: E402
from paperbot.dash.tools import regime5y as Y  # noqa: E402

KST = 9 * 3600 * 1000
DAY = 86400 * 1000
M15 = 15 * 60 * 1000
DS_MONEY = os.environ.get("FULLGRID_DS_MONEY") == "1"
STATES = {"요일": ("평일", "주말"), "장세": ("추세장", "횡보장", "급변장", "보통"), "큰 흐름": ("위", "아래"),
          "변동성": ("작음", "보통", "큼")}
EMA_DAYS = 200


def weekend(ms: np.ndarray) -> np.ndarray:
    """Saturday or Sunday in KST (1970-01-01 was a Thursday: (days + 3) % 7 is Monday = 0)."""
    return ((ms + KST) // DAY + 3) % 7 >= 5


def coin_states(data_dir: str, sym: str, tf: str) -> dict:
    """One coin's state arrays for a cell on ``tf``: regime5y on the chart bars (by bar close), demobot.regime's
    volatility on the 15m bars (by 15m open), daily close above its EMA200 by UTC day (days from the 4h bars: a day
    with all six)."""
    df, close = R.frame(data_dir, sym, tf)
    code = Y.regimes(df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float),
                     Y.TF_MIN[tf])["code"]
    d15, _c = R.frame(data_dir, sym, "15m")
    ts = d15["ts"].astype("int64").to_numpy() // 1_000_000
    b = {"ts": ts, "h": d15["high"].to_numpy(float), "l": d15["low"].to_numpy(float), "c": d15["close"].to_numpy(float)}
    _trend, vol, _s, _a = G.coin_regime(b)
    d4, close4 = R.frame(data_dir, sym, "4h")
    c4 = d4["close"].to_numpy(float)
    day = (close4 - 1) // DAY                                    # the UTC day each 4h bar belongs to
    days, first, count = np.unique(day, return_index=True, return_counts=True)
    full = count == 6
    dclose = c4[first + count - 1][full]
    ema = G._ema(dclose, EMA_DAYS)
    return {"close": close, "code": code, "ts15": ts, "vol": vol, "day": days[full],
            "above": np.where(np.isfinite(ema), dclose > ema, np.nan)}


def tag(T: dict, states: list) -> dict:
    """State labels per trade of ``T`` (cell_trades layout); None where there is not enough history."""
    n = len(T["close"])
    out = {"요일": np.where(weekend(T["close"]), "주말", "평일").astype(object)}
    for dim in ("장세", "큰 흐름", "변동성"):
        out[dim] = np.full(n, None, object)
    for ci, st in enumerate(states):
        m = T["coin"] == ci
        if not m.any():
            continue
        t = T["close"][m]
        i = np.searchsorted(st["close"], t)                            # the signal bar (its close is the entry)
        ok = (i < len(st["close"])) & (st["close"][np.minimum(i, len(st["close"]) - 1)] == t)
        cd = np.where(ok, st["code"][np.minimum(i, len(st["close"]) - 1)], Y.UNKNOWN)
        out["장세"][m] = np.array([None if int(v) == Y.UNKNOWN else Y.RKO[int(v)] for v in cd], object)
        ts = st["ts15"]
        j = np.searchsorted(ts, t, side="right") - 1                  # the 15m bar the entry falls in
        okj = (j >= 0) & (ts[np.maximum(j, 0)] + M15 > t)
        vo = np.where(okj, st["vol"][np.maximum(j, 0)], G.UNK)
        out["변동성"][m] = np.array([{2: "큼", 1: "보통", 0: "작음"}.get(int(v)) for v in vo], object)
        d = np.searchsorted(st["day"], t // DAY - 1)                   # the last completed UTC day
        dd = np.minimum(d, len(st["day"]) - 1)
        hit = (d < len(st["day"])) & (st["day"][dd] == t // DAY - 1)
        ab = np.where(hit, st["above"][dd], np.nan)
        out["큰 흐름"][m] = np.array([None if not np.isfinite(v) else "위" if v else "아래" for v in ab], object)
    return out


def summary(x: np.ndarray, money: bool) -> dict:
    d = {"n": int(len(x))}
    if money:
        d.update({"mean": float(x.mean()) if len(x) else None, "win": float((x > 0).mean()) if len(x) else None,
                  "sum": float(x.sum())})
    return d


def breakdown(T: dict, states: list, money: bool) -> dict:
    m = T["pid"] == R.P_SELECT
    sel = {k: v[m] for k, v in T.items()}
    labels = tag(sel, states)
    out = {"all": summary(sel["x"], money)}
    for dim, names in STATES.items():
        out[dim] = {s: summary(sel["x"][labels[dim] == s], money) for s in names}
        out[dim]["모름"] = {"n": int(sum(v is None for v in labels[dim]))}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--results", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--exchange", required=True)
    ap.add_argument("--procs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args(argv)
    R.FRAME_DIR[0] = os.path.join(a.work, "frames")
    if not all(os.path.exists(R.outcome_path(a.work, s, tf)) for s in R.SYMBOLS for tf in R.TFS):
        R.stage_outcomes(a.data, a.work, a.procs, R.exchange(a.exchange, False))
    with open(os.path.join(a.results, "select.json")) as fh:
        sel = json.load(fh)
    states_of = {}
    cells = {}
    for p in sel["picks"]:
        cells.setdefault((p["kind"], p["name"], p["tf"]), []).append(p)
    rows = []
    for (kind, name, tf), picks in sorted(cells.items()):
        money = kind == "core" or DS_MONEY
        if tf not in states_of:
            states_of[tf] = [coin_states(a.data, s, tf) for s in R.SYMBOLS]
        states = states_of[tf]
        specs = [(R.default_combo(kind, name), 0)] + [(R._combo(p), p["exit_index"]) for p in picks]
        Ts = R.cell_trades(a.data, a.work, kind, name, tf, specs)
        base = breakdown(Ts[0], states, money)
        for p, T in zip(picks, Ts[1:]):
            rows.append({"kind": kind, "name": name, "tf": tf, "rank": p.get("rank"), "row": p.get("row"),
                         "exit": R.K.EXITS[p["exit_index"]][0], "combo": p["combo"],
                         "pick": breakdown(T, states, money), "default": base})
        print(f"[regimes] {kind} {name} {tf}: {len(picks)} picks", flush=True)
    doc = {"period": R.PERIODS[R.P_SELECT], "states": STATES, "rows": rows, "ds_money": DS_MONEY}
    with open(os.path.join(a.work, "regimes.json"), "w") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1, default=float)
    with open(os.path.join(a.work, "regimes_KO.md"), "w") as fh:
        fh.write(report_ko(doc))
    print(f"[regimes] {len(rows)} picks -> {a.work}/regimes_KO.md", flush=True)
    return 0


def _cell(d: dict) -> str:
    if d.get("mean") is None:
        return f"{d['n']}건"
    return f"{d['n']}건 {d['mean'] * 100:+.2f}% 승 {d['win'] * 100:.0f}%"


def report_ko(doc: dict) -> str:
    s, e = doc["period"][1], doc["period"][2]
    L = [f"# 고른 커스텀값의 장 상황별 성적 (고르기 기간 {s} ~ {e}만)", "",
         "한 번 매매당 평균 수익(계좌 대비 %)과 승률. 시험 기간(2024-01 ~ 2026-09)은 열지 않았습니다: 여기서 보이는",
         "'주말엔 이 값' 같은 생각은 그 기간으로 따로 확인해야 진짜입니다. 건수가 적은 칸(100건 미만)은 운일 수 있습니다.",
         "딥시크는 두 분 규칙대로 건수만 보입니다.",
         "급변장 거래가 0건인 것은 자료가 빠진 게 아니라 규칙입니다: 변동이 큰 봉에서는 2 ATR 손절선이 청산 가격보다",
         "멀어서 엔진이 진입을 거절합니다(신호는 나지만 거래가 안 됨).", ""]
    for r in doc["rows"]:
        L.append(f"## {r['name']} {r['tf']} #{r['rank']} ({r['exit']})")
        L.append("")
        L.append("| | 고른 값 | 지금 값 |")
        L.append("|---|---|---|")
        L.append(f"| 전체 | {_cell(r['pick']['all'])} | {_cell(r['default']['all'])} |")
        for dim, names in doc["states"].items():
            for nm in names:
                L.append(f"| {dim}: {nm} | {_cell(r['pick'][dim][nm])} | {_cell(r['default'][dim][nm])} |")
        L.append("")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())
