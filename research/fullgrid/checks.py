"""Full grid phase 2 (PHASE2_PREREG.md 1-6 and 8): descriptive checks on the candidates.

    python research/fullgrid/checks.py --results DIR --data DIR --work DIR --exchange FILE [--all-picks]

Cost twice and three times, years, coins and sides, the worst stretch of the live-sized account, overlap with the
rule bot's default signals, overlap between candidates, and the forward band the 후보 리그 shows. Never adds, removes or
reorders a candidate (PREREG 6.5). Inputs: the results pack (confirm.json, data_build.json), the 1m data (checked
against data_build.json first), the leverage table. The outcome tables are rebuilt in --work when missing (run.py
outcomes). Output: --work/phase2.json and phase2_KO.md. DeepSeek rows: labels and counts only (D11), unless
FULLGRID_DS_MONEY=1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)

import run as R  # noqa: E402
import sizing as SZ  # noqa: E402

K = R.K
DAY = 86_400_000
DS_MONEY = os.environ.get("FULLGRID_DS_MONEY") == "1"
COST_IDX = (0, 1, 5, 19)            # taker fee, slippage, round-trip cost (ladder), maker fee in settings_vector
COST_MULTS = (2.0, 3.0)
YEARS = tuple(range(2020, 2027))
MIN_YEAR, MIN_COIN, MIN_SIDE = 20, 20, 30
SHARE_MAX = 0.60
STEADY = 0.70
SAME_OVERLAP, SAME_CORR = 0.50, 0.70
BAND_NS = (10, 20, 30, 50, 100)
BAND_DRAWS = 10_000
SPAN = (R.PERIOD_MS[R.P_SELECT][1], R.PERIOD_MS[R.P_TEST][2])          # 2021-01-01 .. 2026-10-01


def cand_id(r: dict) -> str:
    return f"{r['kind']}-{r['name']}-{r['tf']}-{r.get('rank')}"


def seed_of(tag: str) -> int:
    return int.from_bytes(hashlib.sha256(tag.encode()).digest()[:8], "big")


def data_mismatch(results: str, data_dir: str) -> list[str]:
    """Coins whose 1m data differs from the run's (data_build.json sha256); [] when they all match."""
    with open(os.path.join(results, "data_build.json")) as fh:
        run_b = {s["symbol"]: s.get("sha256") for s in json.load(fh)["symbols"]}
    with open(os.path.join(data_dir, "build.json")) as fh:
        mine = {s["symbol"]: s.get("sha256") for s in json.load(fh)["symbols"]}
    return [s for s in R.SYMBOLS if run_b.get(s) is None or run_b.get(s) != mine.get(s)]


# ------------------------------------------------------------------ 1. cost
def cost_vector(mult: float) -> np.ndarray:
    S = K.settings_vector().copy()
    for i in COST_IDX:
        S[i] *= mult
    return S


def cost_table(data_dir: str, ex: dict, kind: str, name: str, sym: str, tf: str, e: int, S: np.ndarray) -> np.ndarray:
    """(n bars, 2 sides) P&L / equity of exit ``e`` with settings ``S`` (run.outcomes_job for one exit, then
    run.trade_table's leverage groups)."""
    d = R.minute_data(data_dir, sym)
    df, close = R.frame(data_dir, sym, tf)
    atr = R._vendor_fg().atr(df, 14).to_numpy(float)
    br, step, mn = ex[sym]
    n = len(close)
    out = {}
    for g, flag in (("best", True), ("normal", False)):
        if g == "best" and kind != "core":
            continue
        f = np.full(n, flag)
        p, _e, _r, _l = K.outcomes(S, br, d["ts"], d["o"], d["h"], d["l"], d["mo"], d["mh"], d["ml"], d["fund"],
                                   close.astype(np.int64), atr, f, f, R.EQUITY, step, mn, *K.exit_args(e),
                                   *R.exit_levels(data_dir, sym, tf, e, n))
        out[g] = np.asarray(p, float)
    P = out["normal"].copy()
    if kind == "core":
        bl, bs = R.best_flags(data_dir, name, sym, tf)
        P[bl, 0] = out["best"][bl, 0]
        P[bs, 1] = out["best"][bs, 1]
    return P


def cost_job(args) -> tuple:
    data_dir, ex, r = args
    kind, name, tf, e = r["kind"], r["name"], r["tf"], r["exit_index"]
    res = {}
    for mult in COST_MULTS:
        S = cost_vector(mult)
        xs, ps = [], []
        for sym in R.SYMBOLS:
            P = cost_table(data_dir, ex, kind, name, sym, tf, e, S)
            lo, sh = R.signals(data_dir, kind, name, sym, tf, R._combo(r))
            idx, _side, x = R.per_trade(P, lo, sh)
            _df, close = R.frame(data_dir, sym, tf)
            xs.append(x)
            ps.append(R.period_ids(close)[idx])
        x, pid = np.concatenate(xs), np.concatenate(ps)
        res[f"x{mult:g}"] = {p: _stat(x[pid == k]) for p, k in (("select", R.P_SELECT), ("test", R.P_TEST))}
    return cand_id(r), res


def _stat(x: np.ndarray) -> dict:
    return {"n": int(len(x)), "mean": float(x.mean()) if len(x) else None, "sum": float(x.sum()),
            "win": float((x > 0).mean()) if len(x) else None}


def cost_label(x2_test_mean, x3_test_mean) -> str:
    if x2_test_mean is not None and x2_test_mean > 0:
        return "비용 3배에도 남음" if x3_test_mean is not None and x3_test_mean > 0 else "비용 2배에도 남음"
    return "비용에 약함"


# ------------------------------------------------------------------ 2-3. years, coins, sides
def year_of(ms: np.ndarray) -> np.ndarray:
    return np.array([int(np.datetime64(int(t), "ms").astype("datetime64[Y]").astype(int)) + 1970 for t in ms], int) \
        if len(ms) else np.zeros(0, int)


def years(T: dict) -> dict:
    y = year_of(T["close"])
    rows = {str(Y): _stat(T["x"][y == Y]) for Y in YEARS}
    counted = [Y for Y in YEARS if rows[str(Y)]["n"] >= MIN_YEAR]
    k = sum(rows[str(Y)]["mean"] > 0 for Y in counted)
    total = sum(rows[str(Y)]["sum"] for Y in YEARS if Y >= 2021)
    top = max((rows[str(Y)]["sum"] for Y in YEARS if Y >= 2021), default=0.0)
    lumpy = total > 0 and top > SHARE_MAX * total
    steady = bool(counted) and k / len(counted) >= STEADY and not lumpy
    return {"rows": rows, "plus": k, "counted": len(counted), "lumpy": bool(lumpy), "steady": bool(steady)}


def coins_sides(T: dict) -> dict:
    m = (T["close"] >= SPAN[0]) & (T["close"] < SPAN[1])
    x, coin, side = T["x"][m], T["coin"][m], T["side"][m]
    coins = {s: _stat(x[coin == i]) for i, s in enumerate(R.SYMBOLS)}
    sides = {"long": _stat(x[side > 0]), "short": _stat(x[side < 0])}
    total, tmean = float(x.sum()), (float(x.mean()) if len(x) else 0.0)
    good = sum(1 for v in coins.values() if v["n"] >= MIN_COIN and v["mean"] > 0)
    one_coin = total > 0 and max(v["sum"] for v in coins.values()) > SHARE_MAX * total
    one_side = tmean > 0 and any(v["n"] >= MIN_SIDE and v["mean"] <= 0 for v in sides.values())
    return {"coins": coins, "sides": sides, "spread": good >= 4, "good_coins": good, "one_coin": bool(one_coin),
            "one_side": bool(one_side)}


# ------------------------------------------------------------------ 4. worst stretch
def longest_losing_run(ret: np.ndarray) -> int:
    best = cur = 0
    for v in ret:
        cur = cur + 1 if v < 0 else 0
        best = max(best, cur)
    return best


def month_key(ms: np.ndarray) -> np.ndarray:
    return np.asarray(ms, "datetime64[ms]").astype("datetime64[M]").astype(int) if len(ms) else np.zeros(0, int)


def worst_month(exit_ms: np.ndarray, ret: np.ndarray) -> dict | None:
    if not len(ret):
        return None
    mk = month_key(exit_ms)
    best = None
    for m in np.unique(mk):
        g = float(np.prod(1 + ret[mk == m]) - 1)
        if best is None or g < best[1]:
            best = (int(m), g)
    y, mo = divmod(best[0], 12)
    return {"month": f"{1970 + y}-{mo + 1:02d}", "change": best[1]}


def under_water(exit_ms: np.ndarray, ret: np.ndarray, start_ms: int, end_ms: int) -> dict:
    """Longest time from a peak (the start counts as one) to the first close back at or above it, in days; ``open``
    when the end of the period came first and that stretch is the longest."""
    eq = np.cumprod(1 + np.asarray(ret, float))
    peak_v, peak_t, under, longest, open_ = 1.0, start_ms, False, 0.0, False
    for v, t in zip(eq, exit_ms):
        if v >= peak_v:
            if under:
                longest = max(longest, (int(t) - peak_t) / DAY)
            peak_v, peak_t, under = float(v), int(t), False
        else:
            under = True
    if under and (end_ms - peak_t) / DAY >= longest:
        longest, open_ = (end_ms - peak_t) / DAY, True
    return {"days": float(longest), "open": bool(open_)}


def worst(data_dir: str, T: dict, ex: dict, e: int, lo: int, hi: int) -> dict:
    acc = SZ.account_trades(data_dir, T, ex, lo, hi, e, K.settings_vector())
    return {"trades": acc["trades"], "final_x": acc["final_x"], "max_dd": acc["max_dd"], "bust": acc["bust"],
            "losing_run": longest_losing_run(acc["ret"]), "worst_month": worst_month(acc["exit_ms"], acc["ret"]),
            "under_water": under_water(acc["exit_ms"], acc["ret"], lo, hi)}


# ------------------------------------------------------------------ 5-6. overlaps
def overlap_share(a: dict, b: dict, window_ms: int) -> float | None:
    """Share of a's entries with a b entry on the same coin and side within ``window_ms`` of its signal close."""
    if not len(a["close"]):
        return None
    hit = 0
    for c in np.unique(a["coin"]):
        for s in (1, -1):
            ma = (a["coin"] == c) & (a["side"] == s)
            if not ma.any():
                continue
            tb = np.sort(b["close"][(b["coin"] == c) & (b["side"] == s)])
            if not len(tb):
                continue
            ta = a["close"][ma]
            i = np.searchsorted(tb, ta)
            near = np.full(len(ta), np.inf)
            for j in (i - 1, i):
                ok = (j >= 0) & (j < len(tb))
                near[ok] = np.minimum(near[ok], np.abs(tb[j[ok]] - ta[ok]))
            hit += int((near <= window_ms).sum())
    return hit / len(a["close"])


def signal_entries(data_dir: str, kind: str, name: str, tf: str, combo: dict, cache: dict) -> dict:
    """Every signal bar (coin, side, close) of a strategy on ``tf`` over the six coins (no sizing)."""
    key = (kind, name, tf, json.dumps(combo, sort_keys=True, default=str))
    if key not in cache:
        cols = {"close": [], "coin": [], "side": []}
        for ci, sym in enumerate(R.SYMBOLS):
            lo, sh = R.signals(data_dir, kind, name, sym, tf, combo)
            _df, close = R.frame(data_dir, sym, tf)
            for s, arr in ((1, lo), (-1, sh)):
                idx = np.flatnonzero(arr)
                cols["close"].append(close[idx])
                cols["coin"].append(np.full(len(idx), ci))
                cols["side"].append(np.full(len(idx), s, np.int8))
        cache[key] = {k: np.concatenate(v) for k, v in cols.items()}
    return cache[key]


def in_span(T: dict) -> dict:
    m = (T["close"] >= SPAN[0]) & (T["close"] < SPAN[1])
    return {k: T[k][m] for k in ("close", "coin", "side", "x")}


def daily(T: dict) -> dict:
    d = T["close"] // DAY
    out: dict = {}
    for k, v in zip(d.tolist(), T["x"].tolist()):
        out[k] = out.get(k, 0.0) + v
    return out


def corr_daily(a: dict, b: dict) -> float | None:
    days = sorted(set(a) | set(b))
    if len(days) < 3:
        return None
    x = np.array([a.get(d, 0.0) for d in days])
    y = np.array([b.get(d, 0.0) for d in days])
    if x.std() == 0 or y.std() == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def worst_days(dd: dict) -> set:
    losing = sorted((v, d) for d, v in dd.items() if v < 0)
    k = max(1, int(round(0.05 * len(losing)))) if losing else 0
    return {d for _v, d in losing[:k]}


def bad_day_overlap(a: dict, b: dict) -> float | None:
    wa, wb = worst_days(a), worst_days(b)
    if not wa or not wb:
        return None
    return 0.5 * (len(wa & wb) / len(wa) + len(wa & wb) / len(wb))


# ------------------------------------------------------------------ 8. forward band
def band(x: np.ndarray, tag: str, ns=BAND_NS, draws: int = BAND_DRAWS) -> dict:
    """{n: {p5, median}} of the mean of n trades resampled from ``x``."""
    if len(x) == 0:
        return {}
    rng = np.random.default_rng(seed_of(tag))
    out = {}
    for n in ns:
        m = x[rng.integers(0, len(x), size=(draws, n))].mean(axis=1)
        out[str(n)] = {"p5": float(np.percentile(m, 5)), "median": float(np.median(m))}
    return out


# ------------------------------------------------------------------ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--results", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--exchange", required=True)
    ap.add_argument("--all-picks", action="store_true")
    ap.add_argument("--procs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args(argv)
    bad = data_mismatch(a.results, a.data)
    if bad:
        raise SystemExit(f"1m data differs from the run's for {bad}: stop (PHASE2_PREREG 0)")
    R.FRAME_DIR[0] = os.path.join(a.work, "frames")
    ex = R.exchange(a.exchange, False)
    if not all(os.path.exists(R.outcome_path(a.work, s, tf)) for s in R.SYMBOLS for tf in R.TFS):
        R.stage_outcomes(a.data, a.work, a.procs, ex)
    with open(os.path.join(a.results, "confirm.json")) as fh:
        rows = json.load(fh)["rows"]
    cands = [r for r in rows if r.get("pass") or a.all_picks]
    doc = {"rules": "PHASE2_PREREG.md 1-6, 8", "candidates": [], "pairs": [], "ds_money": DS_MONEY,
           "all_picks": a.all_picks}
    if not cands:
        doc["none"] = True
        _write(a.work, doc)
        return 0
    costs = dict(R.run_pool(cost_job, [(a.data, ex, r) for r in cands], a.procs, "cost"))
    sig_cache: dict = {}
    per = []
    for r in cands:
        kind, name, tf, e = r["kind"], r["name"], r["tf"], r["exit_index"]
        T = R.combo_trades(a.data, a.work, kind, name, tf, R._combo(r), e)
        span = in_span(T)
        win = R.TF_MS[tf]
        own = signal_entries(a.data, kind, name, tf, R.default_combo(kind, name), sig_cache)
        core36 = [signal_entries(a.data, "core", n, tf, R.default_combo("core", n), sig_cache) for n in R.core_names()]
        any36 = {k: np.concatenate([c[k] for c in core36]) for k in ("close", "coin", "side")}
        c = costs[cand_id(r)]
        row = {"id": cand_id(r), "kind": kind, "name": name, "tf": tf, "rank": r.get("rank"), "exit": r.get("exit"),
               "passed": bool(r.get("pass")), "cost": c,
               "cost_label": cost_label(c["x2"]["test"]["mean"], c["x3"]["test"]["mean"]),
               "years": years(T), "coins_sides": coins_sides(T),
               "worst": {"all": worst(a.data, T, ex, e, *SPAN),
                         "test": worst(a.data, T, ex, e, R.PERIOD_MS[R.P_TEST][1], R.PERIOD_MS[R.P_TEST][2])},
               "rulebot_overlap": {"own_default": overlap_share(span, own, win), "any_core36": overlap_share(span, any36, win)},
               "band": band(T["x"][T["pid"] == R.P_TEST], cand_id(r))}
        per.append((row, span, daily(span)))
        doc["candidates"].append(row)
        print(f"[checks] {row['id']}: {row['cost_label']}, years {row['years']['plus']}/{row['years']['counted']}",
              flush=True)
    for i in range(len(per)):
        for j in range(i + 1, len(per)):
            (ra, sa, da), (rb, sb, db) = per[i], per[j]
            w = max(R.TF_MS[ra["tf"]], R.TF_MS[rb["tf"]])
            o1, o2 = overlap_share(sa, sb, w), overlap_share(sb, sa, w)
            ov = None if o1 is None or o2 is None else 0.5 * (o1 + o2)
            cr = corr_daily(da, db)
            doc["pairs"].append({"a": ra["id"], "b": rb["id"], "overlap": ov, "corr": cr, "bad_days": bad_day_overlap(da, db),
                                 "same": bool((ov is not None and ov >= SAME_OVERLAP) or (cr is not None and cr >= SAME_CORR))})
    _write(a.work, doc)
    return 0


def _write(work: str, doc: dict) -> None:
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(work, "phase2.json"), "w") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(work, "phase2_KO.md"), "w") as fh:
        fh.write(report_ko(doc))
    print(f"[checks] {len(doc['candidates'])} candidates -> {work}/phase2_KO.md", flush=True)


# ------------------------------------------------------------------ report
def _p(x, d=2) -> str:
    return "-" if x is None else f"{x * 100:+.{d}f}%"


def _share(x) -> str:
    return "-" if x is None else f"{x * 100:.0f}%"


def _money(row: dict) -> bool:
    return row["kind"] == "core" or DS_MONEY


def report_ko(doc: dict) -> str:
    L = ["# 후보 추가 점검 (2단계, 미리 정한 규칙: PHASE2_PREREG.md)", "",
         "후보 목록을 바꾸지 않는 설명용 점검입니다. 얼마나 믿고 얼마나 걸지 정하는 데 씁니다. 숫자 단위는 '한 번 매매의",
         "손익 ÷ 잔고'(모든 신호, 포지션 제한 없음)이고, '계좌'라고 적힌 곳만 실제 계좌(한 번에 하나, 복리, 지금 크기)입니다.",
         "딥시크는 두 분 규칙대로 판정과 건수만 보입니다.", ""]
    if doc.get("none"):
        L.append("통과한 후보가 없어 점검할 것이 없습니다.")
        return "\n".join(L) + "\n"
    if doc.get("all_picks"):
        L += ["**참고: 통과 못 한 값도 함께 넣어 돌린 것입니다 (통과한 것만 후보).**", ""]
    for r in doc["candidates"]:
        m = _money(r)
        ys, cs, w = r["years"], r["coins_sides"], r["worst"]
        tag = "" if r["passed"] else " (통과 못 함, 참고용)"
        L += [f"## {r['name']} {r['tf']} #{r['rank']} ({r['exit']}){tag}", ""]
        labels = [r["cost_label"], f"플러스인 해 {ys['plus']}/{ys['counted']}"]
        labels += ["꾸준함"] if ys["steady"] else []
        labels += ["한 해 몰림"] if ys["lumpy"] else []
        labels += [f"코인 고름 ({cs['good_coins']}/6)" if cs["spread"] else f"플러스 코인 {cs['good_coins']}/6"]
        labels += ["한 코인 몰림"] if cs["one_coin"] else []
        labels += ["한쪽 방향만"] if cs["one_side"] else []
        L += ["판정: " + " · ".join(labels), ""]
        if m:
            c = r["cost"]
            L += [f"- 비용 2배: 시험 기간 한 번 평균 {_p(c['x2']['test']['mean'])} ({c['x2']['test']['n']}건), "
                  f"3배: {_p(c['x3']['test']['mean'])}",
                  "- 해마다 한 번 평균: " + ", ".join(f"{y} {_p(v['mean'])}({v['n']})" for y, v in ys["rows"].items()
                                                if v["n"]),
                  "- 코인마다: " + ", ".join(f"{s[:-4]} {_p(v['mean'])}({v['n']})" for s, v in cs["coins"].items() if v["n"]),
                  f"- 방향: 롱 {_p(cs['sides']['long']['mean'])}({cs['sides']['long']['n']}), "
                  f"숏 {_p(cs['sides']['short']['mean'])}({cs['sides']['short']['n']})"]
            for k, nm in (("all", "2021-01 ~ 2026-09"), ("test", "시험 기간")):
                v = w[k]
                wm = v["worst_month"]
                uw = v["under_water"]
                L.append(f"- 계좌 {nm}: 끝 잔고 x{v['final_x']:.2f}, 최대 낙폭 {v['max_dd'] * 100:.0f}%, "
                         f"최장 연속 손실 {v['losing_run']}번, 최악의 달 {wm['month'] + ' ' + _p(wm['change'], 0) if wm else '-'}, "
                         f"가장 긴 회복 {uw['days']:.0f}일{' (아직 회복 못 함)' if uw['open'] else ''}"
                         f"{', 파산' if v['bust'] else ''}")
        else:
            L.append("- 거래 수: 해마다 " + ", ".join(f"{y} {v['n']}" for y, v in ys["rows"].items() if v["n"]))
        ro = r["rulebot_overlap"]
        L.append(f"- 규칙봇과 겹침: 같은 매매법 기본값과 {_share(ro['own_default'])}, 36개 기본값 중 하나라도 "
                 f"{_share(ro['any_core36'])} (같은 코인·같은 방향·한 봉 안)")
        L.append("")
    if doc["pairs"]:
        L += ["## 후보끼리 겹침 (같이 돌릴 때)", "",
              "| 후보 A | 후보 B | 같은 진입 | 하루 손익 상관 | 나쁜 날 겹침 | |", "|---|---|---|---|---|---|"]
        for p in doc["pairs"]:
            L.append(f"| {p['a']} | {p['b']} | {_share(p['overlap'])} | "
                     f"{'-' if p['corr'] is None else format(p['corr'], '.2f')} | {_share(p['bad_days'])} | "
                     f"{'거의 같은 매매' if p['same'] else ''} |")
        L += ["", "나쁜 날 겹침은 서로 상관없으면 5% 안팎입니다. '거의 같은 매매'는 같이 돌려도 위험이 줄지 않습니다.", ""]
    L += ["## 후보 리그 '예상 범위'", "",
          "시험 기간 거래로 만든 범위입니다. 후보 리그에서 그 건수만큼 거래한 뒤 한 번 평균이 '하위 5%'보다 낮으면",
          "'예상보다 아래'로 표시됩니다. 후보가 많으면 20개 중 1개쯤은 운만으로도 그렇게 나옵니다.", "",
          "| 후보 | 10건 하위 5% | 30건 하위 5% | 100건 하위 5% | 가운데 |", "|---|---|---|---|---|"]
    for r in doc["candidates"]:
        b = r.get("band") or {}
        if not b:
            continue
        if not _money(r):
            L.append(f"| {r['id']} | 숨김 | 숨김 | 숨김 | 숨김 |")
            continue
        L.append(f"| {r['id']} | {_p(b['10']['p5'])} | {_p(b['30']['p5'])} | {_p(b['100']['p5'])} | {_p(b['30']['median'])} |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())
