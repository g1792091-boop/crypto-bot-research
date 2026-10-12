"""Tier A reads of the extra file (research/exitflex/PREREG_EXITFLEX_EXTRA.md E.3): the body of EXTRA_READS_KO.md, in the order X-046,
X-024, X-025, X-027, X-047, X-014, X-001, X-037 (reads_lib.BODY_ORDER).

Each ``read_X_nnn(ctx) -> dict`` (reads_lib.new_result) computes from A's step-1 result files (common.account), the C4 / C5 records of
reads_lib and select.json's choosable ids, and returns:
  public['core']   counts on every row; money only on E0 and the pool's choosable rows (E.1 item 4);
  public['ds']     count class only, through reads_lib.ds_public (C8; no offered / no_fill, main session decision (a));
  private['ds']    the DeepSeek money (ds_private/extra_reads_ds.json and the private report, E.1 item 5);
  md / md_appendix / md_private / md_private_appendix / csv / headline   (see reads_lib).
``read_X_046(ctx, results)`` only assembles the other reads' headline sentences and select.json (no new computation).
Nothing here prints a figure.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import common as XC  # noqa: E402
import reads_lib as RL  # noqa: E402
from common import KX, MT  # noqa: E402

Q, LIVE = XC.SIZE_Q, XC.SIZE_LIVE
NM = XC.N_MONTHS
W = RL.W_KO
fn, fsh, fkn, fg, fx, fh, fc = RL.fmt_n, RL.fmt_share, RL.fmt_kn, RL.fmt_growth, RL.fmt_x, RL.fmt_h, RL.fmt_contrib
TAG_FIT = "맞춘 기간의 성적"                     # the tag of every page of goal-scale figures (X-014, X-047)


# ====================================================================================================== small helpers
def _N(ctx, pool: str) -> int:
    return len(ctx.pool_picks(pool))


def _closed(a: dict) -> np.ndarray:
    return np.asarray(a["tr_reason"]) != KX.R_OPEN


def _busts(accs: list) -> int:
    return int(sum(1 for a in accs if float(a["w_end"]) < XC.BUST_W))


def _hold(h: np.ndarray) -> dict:
    h = np.asarray(h, float)
    if not len(h):
        return {"hold_median": None, "share_gt4h": None, "share_gt8h": None, "share_gt18h": None, "n_gt8h": 0}
    return {"hold_median": float(np.median(h)), "share_gt4h": float((h > 4).mean()), "share_gt8h": float((h > 8).mean()),
            "share_gt18h": float((h > 18).mean()), "n_gt8h": int((h > 8).sum())}


def _month_label(ctx, m: int) -> str:
    return dt.datetime.fromtimestamp(int(ctx.edges[m]) / 1000, dt.timezone.utc).strftime("%Y-%m")


def _num(x):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else x


def _sec(read_id: str, appendix: bool = False) -> str:
    return f"## {read_id} {RL.TITLE_KO[read_id]}" + (" (부록)" if appendix else "")


def _psec(read_id: str, part: str) -> str:
    return f"### {read_id} {RL.TITLE_KO[read_id]} · 딥시크 비공개 ({part})"


def _plab(arm: str) -> str:
    """A private row label (it holds the pool word, so no private line can equal a committed line, A8 (3))."""
    return f"딥시크 {arm}"


def _route(r: dict, pool: str) -> tuple:
    """(count target, money target) of a pool: core money is committed (E0 and choosable rows), DeepSeek money is private."""
    pub = r["public"][pool]
    return pub, (pub if pool == "core" else r["private"].setdefault("ds", {}))


def _finish_ds(r: dict) -> dict:
    r["public"]["ds"] = RL.ds_public({**r["public"]["ds"], "read": r["id"]})
    return r


def _row_label(ctx, pool: str, arm: str) -> str:
    return RL.arm_label(ctx, pool, arm)


def _thin_line(n_cells: int, n_thin: int, n_out: int | None = None) -> str:
    return XC.c15_line(n_cells, n_thin, n_out)


# ====================================================================================================== X-001 코인별 성적표
def _dd_log(l: np.ndarray) -> float:
    """X-001: y_0 = 0, y_t = cumulative l over the coin's trades; DD = 1 - exp(-max_t(max_(s<=t) y_s - y_t))."""
    y = np.r_[0.0, np.cumsum(np.asarray(l, float))]
    return 1.0 - math.exp(-float(np.max(np.maximum.accumulate(y) - y)))


def _coin_counts(ctx, pool: str, arm: str, size: float = Q) -> list:
    K, N = len(RL.coins(ctx)), _N(ctx, pool)
    n, ent, wins = np.zeros(K, int), np.zeros(K, int), np.zeros(K, int)
    rs = np.zeros((K, len(RL.REASON_COLS)), int)
    hold = [[] for _ in range(K)]
    for a in RL.pool_accounts(ctx, pool, arm, size):
        coin, cl, pnl = np.asarray(a["tr_coin"]), _closed(a), np.asarray(a["tr_pnl"])
        rsn, hh = np.asarray(a["tr_reason"]), np.asarray(a["hold_h"], float)
        for k in range(K):
            s = coin == k
            c = s & cl
            ent[k] += int(s.sum())
            n[k] += int(c.sum())
            wins[k] += int((c & (pnl > 0)).sum())
            hold[k].append(hh[c])
            rs[k] += [int((rsn[c] == RL.REASON_CODE[x]).sum()) for x in RL.REASON_COLS]
    out = []
    for k, sym in enumerate(RL.coins(ctx)):
        h = np.concatenate(hold[k]) if hold[k] else np.zeros(0)
        hs = _hold(h)
        out.append({"coin": sym, "n": int(n[k]), "entered": int(ent[k]), "entered_per_month": XC.per_account_month(ent[k], N),
                    "wins": int(wins[k]), "losses": int(n[k] - wins[k]), "win_share": wins[k] / n[k] if n[k] else None,
                    "hold_median": hs["hold_median"], "share_gt8h": hs["share_gt8h"], "n_gt8h": hs["n_gt8h"],
                    "reasons": {x: int(rs[k, i]) for i, x in enumerate(RL.REASON_COLS)}, "flag": XC.c7_mark(int(n[k]))})
    return out


def _coin_money(ctx, pool: str, arm: str, size: float = Q) -> dict:
    K, picks = len(RL.coins(ctx)), ctx.pool_picks(pool)
    N = len(picks)
    s, sy = np.zeros((N, K)), np.zeros((N, K, 3))
    xs, Rs, dd = [[] for _ in range(K)], [[] for _ in range(K)], [[] for _ in range(K)]
    left = np.zeros(K, int)
    for i, p in enumerate(picks):
        fr = RL.c4_trade_frame(ctx, p, XC.account(ctx, p, arm, size))
        yr = fr["exit_ts"].astype("datetime64[ms]").astype("datetime64[Y]").astype(int) + 1970
        for k in range(K):
            sel = fr["coin"] == k
            s[i, k] = float(fr["l"][sel].sum())
            for y in range(3):
                sy[i, k, y] = float(fr["l"][sel & (yr == 2021 + y)].sum())
            xs[k].append(fr["x_ret"][sel])
            Rs[k].append(fr["R"][sel])
            if sel.sum() >= 30:
                dd[k].append(_dd_log(fr["l"][sel]))
            else:
                left[k] += 1
    cat = lambda L: np.concatenate(L) if L else np.zeros(0)  # noqa: E731
    return {"c": (100.0 * s.mean(axis=0) / NM) if N else np.zeros(K), "c_pick": 100.0 * s / NM,
            "cy": (100.0 * sy.mean(axis=0) / 12.0) if N else np.zeros((K, 3)),
            "x_mean": [float(cat(xs[k]).mean()) if len(cat(xs[k])) else None for k in range(K)],
            "R_mean": [float(cat(Rs[k]).mean()) if len(cat(Rs[k])) else None for k in range(K)],
            "dd_median": [float(np.median(dd[k])) if dd[k] else None for k in range(K)],
            "dd_max": [float(np.max(dd[k])) if dd[k] else None for k in range(K)], "dd_left_out": left.tolist()}


def read_X_001(ctx) -> dict:
    """X-001 코인별 성적표 (see E.3)."""
    r = RL.new_result("X-001", "A")
    syms = RL.coins(ctx)
    K = len(syms)
    short = [s[:-4] for s in syms]
    for pool in XC.POOLS:
        N = _N(ctx, pool)
        pub, mon = _route(r, pool)
        counts = {arm: _coin_counts(ctx, pool, arm) for arm in RL.arm_rows(ctx, pool)}
        e0c = counts["E0"]
        for arm, rows in counts.items():
            for k, row in enumerate(rows):
                row["dn"] = (row["n"] / e0c[k]["n"] - 1.0) if e0c[k]["n"] else None
                r["csv"].append({"read": "X-001", "pool": pool, "arm": arm, "coin": row["coin"], "n": row["n"], "entered": row["entered"],
                                 "entered_per_month": row["entered_per_month"], "wins": row["wins"], "losses": row["losses"],
                                 "win_share": row["win_share"], "hold_median": row["hold_median"], "share_gt8h": row["share_gt8h"],
                                 **{f"reasons_{x}": row["reasons"][x] for x in RL.REASON_COLS}, "dn": row["dn"]})
        pub["by_arm"] = [{"arm": a, "cells": counts[a]} for a in RL.money_rows(ctx, pool)]
        n_cells = len(pub["by_arm"]) * K
        n_thin = sum(1 for b in pub["by_arm"] for c in b["cells"] if c["n"] and c["n"] < XC.THIN_MIN)
        pub["n_cells"], pub["n_thin"] = n_cells, n_thin
        money = {a: _coin_money(ctx, pool, a) for a in RL.money_rows(ctx, pool)}
        m0 = money["E0"]
        M = {}
        out_m = []
        for a, m in money.items():
            dc = m["c"] - m0["c"]
            MP = XC.pooled_M(ctx, pool, a)
            if abs(float(dc.sum()) - 100.0 * MP) > 1e-9:
                raise AssertionError(f"X-001: the sum of dc_k differs from 100 M_P ({pool} {a})")
            M[a] = MP
            row = {"arm": a, "c": m["c"].tolist(), "dc": dc.tolist(), "x_mean": m["x_mean"], "R_mean": m["R_mean"], "dd_median": m["dd_median"],
                   "dd_max": m["dd_max"], "dd_left_out": m["dd_left_out"], "cy": m["cy"].tolist(), "dcy": (m["cy"] - m0["cy"]).tolist(),
                   "own_growth_log": XC.own_growth_log(RL.pool_accounts(ctx, pool, a))}
            if a == "E0":
                sh = XC.c17_shares(m["c"] / 100.0, float(m["c"].sum()) / 100.0)
                row["share"] = None if sh is None else sh.tolist()
            else:
                ks = int(np.argmax(dc))
                yrs = ((m["cy"] - m0["cy"]) > 0).sum(axis=1)
                row.update(n_up=int((dc > 0).sum()), k_top=syms[ks], M=MP, without_top=MP - float(dc[ks]) / 100.0,
                           picks_up=[int(v) for v in (m["c_pick"] > m0["c_pick"]).sum(axis=0)], coin_years=[int((yrs == y).sum()) for y in (3, 2, 1, 0)])
            out_m.append(row)
        mon["money_by_arm"] = out_m
        # ---------------------------------------------------------------- Korean lines
        ds = pool == "ds"
        body = [RL.pool_head(pool, N)]
        head = ["방식"] + short + ["좋아진 코인 · 가장 좋아진 코인을 빼면"]
        rows = []
        for b in pub["by_arm"]:
            cells = []
            for c in b["cells"]:
                if not c["entered"]:
                    cells.append(XC.EMPTY)
                    continue
                ws = f"승 {fkn(c['wins'], c['n'])}" if ds else fsh(c["win_share"])
                cells.append(f"{c['entered_per_month']:.2f}번 · {c['wins']}/{c['losses']} · {ws} · {fh(c['hold_median'])}{RL.mark(c['n'])}")
            last = XC.EMPTY
            if not ds and b["arm"] != "E0":
                mm = next(x for x in out_m if x["arm"] == b["arm"])
                last = (f"{mm['n_up']}/{K} · {mm['k_top'][:-4]} 빼면 E0 대비 {fg(mm['without_top'])} (자체 {fg(mm['own_growth_log'])})"
                        + (f" · {W['W12']}" if XC.pct_month(mm["own_growth_log"]) <= 0 else ""))
            rows.append([_row_label(ctx, pool, b["arm"])] + cells + [last])
        if not ds:
            e0m = out_m[0]
            share = e0m.get("share")
            rows.append(["E0 몫 · 이 코인만의 최대 하락(중앙값)"] + [
                f"{e0m['c'][k]:+.2f}" + (f" ({fsh(share[k], 0)})" if share is not None else "") + f" · {fsh(e0m['dd_median'][k], 0)}"
                for k in range(K)] + [XC.EMPTY])
        body += ["칸 = '한 달 진입 · 승/패 · 승률 · 보유 중앙값'. 한 달 진입은 픽 하나가 한 달에 들어간 평균 횟수입니다.", ""]
        body += RL.md_table(head, rows)
        body += [_thin_line(n_cells, n_thin)]
        if not ds:
            if out_m and out_m[0].get("share") is None:
                body.append(W["W15"])
            body += ["E0 몫은 '%/월 기여(근사)'입니다. 새 방식과 지금 청산은 같은 코인에서도 거래가 서로 달라서(다른 진입이 가능해짐), "
                     "코인별 차이는 월 성장을 나눠 적은 회계일 뿐 원인이 아닙니다.", XC.CONTRIB_NOTE_KO]
        body += [W["W14"], W["W3"], ""]
        r["md"] += body
        # appendix (core committed) and the private parts (DeepSeek)
        app = [RL.pool_head(pool, N)]
        if not ds:
            ch = [x for x in out_m if x["arm"] != "E0"]
            app += ["E0 대비 코인별 기여 차이(dc, %/월 기여(근사)):", ""]
            app += RL.md_table(["방식"] + short + ["좋아진 픽 수(코인별)"],
                               [[x["arm"]] + [f"{v:+.2f}" for v in x["dc"]] + [" · ".join(fkn(v, N) for v in x["picks_up"])] for x in ch])
            app += [_thin_line(len(ch) * K, sum(1 for b in pub["by_arm"] if b["arm"] != "E0" for c in b["cells"] if c["n"] < XC.THIN_MIN)), ""]
            app += ["거래 1건 평균(지갑 대비 x, R): R은 거래 하나의 손익을 처음 손절 거리로 나눈 값입니다(1R = 손절 한 번만큼).", ""]
            app += RL.md_table(["방식"] + short,
                               [[_row_label(ctx, pool, x["arm"])] + [f"{fsh(x['x_mean'][k], 2)} · {RL.fmt_f(x['R_mean'][k])}R" for k in range(K)]
                                for x in out_m])
            app += ["코인별 최대 하락(그 코인 거래만, 중앙값 / 최대, 30건 미만 계좌는 빼고 수를 적음):", ""]
            app += RL.md_table(["방식"] + short, [[_row_label(ctx, pool, x["arm"])] + [
                f"{fsh(x['dd_median'][k], 0)} / {fsh(x['dd_max'][k], 0)} (뺀 계좌 {x['dd_left_out'][k]}개)" for k in range(K)] for x in out_m])
            app += ["해마다 코인별 기여(%/월 기여(근사), 2021 / 2022 / 2023)와 E0 대비 차이가 + 인 해의 수별 코인 수(3해 / 2해 / 1해 / 0해):", ""]
            app += RL.md_table(["방식"] + short + ["코인 수"], [[_row_label(ctx, pool, x["arm"])] + [
                " / ".join(f"{v:+.2f}" for v in (x["cy"][k] if x["arm"] == "E0" else x["dcy"][k])) for k in range(K)]
                + [" / ".join(str(v) for v in x.get("coin_years", [])) or XC.EMPTY] for x in out_m])
        app += ["끝난 이유별 건수(익절 TP · 손절 SL · 잠금 LOCK · 규칙 RULE · 강제청산 LIQ · 기간 끝 END):", ""]
        app += RL.md_table(["방식"] + short, [[_row_label(ctx, pool, b["arm"])] + [
            " · ".join(f"{x} {c['reasons'][x]}" for x in RL.REASON_COLS) for c in b["cells"]] for b in pub["by_arm"]])
        app += [_thin_line(n_cells, n_thin), ""]
        app += ["코인별 거래 수가 다른 이유: 코인마다 신호 수가 다르고, 들고 있는 동안 다른 코인 신호를 놓치기 때문입니다. 89개 방식 전체의 건수는 "
                "extra_reads_rows.csv에 있습니다.", ""]
        r["md_appendix"] += app
        if ds:
            pv = [_psec("X-001", "핵심"), "", "| 딥시크 방식 | " + " | ".join(short) + " | 좋아진 코인 · 가장 좋아진 코인 뺀 E0 대비 |",
                  "|" + "---|" * (K + 2)]
            for x in out_m:
                if x["arm"] == "E0":
                    sh = x.get("share")
                    pv.append(f"| {_plab('E0')} 몫 · 하락 | " + " | ".join(
                        f"{x['c'][k]:+.2f}" + (f" ({fsh(sh[k], 0)})" if sh is not None else "") + f" · {fsh(x['dd_median'][k], 0)}"
                        for k in range(K)) + " | - |")
                else:
                    pv.append(f"| {_plab(x['arm'])} | " + " | ".join(f"{v:+.2f}" for v in x["dc"])
                              + f" | {x['n_up']}/{K} · {x['k_top'][:-4]} 빼면 {fg(x['without_top'])} (자체 {fg(x['own_growth_log'])}) |")
            pv += ["", "딥시크 코인별 숫자는 '%/월 기여(근사)'이며 원인이 아니라 회계상 나눔입니다.", ""]
            r["md_private"] += pv
            pa = [_psec("X-001", "부록"), ""]
            for x in out_m:
                pa.append(f"- {_plab(x['arm'])}: 평균 x " + ", ".join(f"{short[k]} {fsh(x['x_mean'][k], 2)}" for k in range(K))
                          + "; 평균 R " + ", ".join(f"{short[k]} {RL.fmt_f(x['R_mean'][k])}" for k in range(K))
                          + "; 해마다 " + ", ".join(f"{short[k]} " + "/".join(f"{v:+.2f}" for v in (x["cy"][k] if x["arm"] == "E0" else x["dcy"][k]))
                                                    for k in range(K))
                          + (f"; 좋아진 픽 " + ", ".join(f"{short[k]} {fkn(x['picks_up'][k], N)}" for k in range(K)) if "picks_up" in x else ""))
            r["md_private_appendix"] += pa + [""]
    return _finish_ds(r)


# ====================================================================================================== X-014 한 달 눈금
SHARE_X = (("ge1.1", 1.1, True), ("ge1.5", 1.5, True), ("ge2", 2.0, True), ("ge5", 5.0, True), ("lt1", 1.0, False), ("lt0.5", 0.5, False))
PEAK_X = (1.5, 2.0, 5.0, 10.0)


def _hits(hit: np.ndarray, month: np.ndarray) -> dict:
    k = int(hit.sum())
    if not k:
        return {"k": 0, "n": int(len(hit)), "months": 0, "top_month_share": None}
    cnt = np.bincount(month[hit], minlength=NM)
    return {"k": k, "n": int(len(hit)), "months": int((cnt > 0).sum()), "top_month_share": float(cnt.max() / k)}


def month_dist(ctx, pool: str, arm: str, size: float = Q) -> dict:
    """X-014 for one pool, arm and size (cached; X-047 quotes p50 and the share of months x >= 2)."""
    cache = RL._cache(ctx, "_xr_x014")
    key = (pool, arm, float(size))
    if key in cache:
        return cache[key]
    if not XC.money_allowed(ctx, pool, arm):
        raise XC.Refused(f"X-014 is money: not on {arm} in {pool}")
    accs = RL.pool_accounts(ctx, pool, arm, size)
    xs, flat, mon, peaks = [], [], [], []
    gsum, gcnt = np.zeros(NM), np.zeros(NM)
    for a in accs:
        g = np.asarray(a["g"], float)
        alive = XC.alive_months(a)
        mi = np.asarray(a["month"], np.int64)
        has_exit = np.bincount(mi, minlength=NM) > 0
        w0, Wm = float(a["w0"]), np.asarray(a["W"], float)
        Wprev = np.r_[w0, Wm[:-1]]
        pk = np.ones(NM)
        if len(mi):
            Wt = w0 + np.cumsum(np.asarray(a["tr_pnl"], float))
            np.maximum.at(pk, mi, Wt / Wprev[mi])
        idx = np.flatnonzero(alive)
        xs.append(np.exp(g[idx]))
        flat.append(~has_exit[idx])
        mon.append(idx)
        peaks.append(pk[idx])
        gsum[idx] += g[idx]
        gcnt[idx] += 1
    cat = lambda L, t=float: np.concatenate(L).astype(t) if L else np.zeros(0, t)  # noqa: E731
    x, fl, mo, pk = cat(xs), cat(flat, bool), cat(mon, np.int64), cat(peaks)
    with np.errstate(invalid="ignore", divide="ignore"):
        gm = np.where(gcnt > 0, gsum / np.maximum(gcnt, 1), np.nan)
    q = np.percentile(x, [10, 25, 50, 75, 90]).tolist() if len(x) else [None] * 5
    shares = {nm: _hits((x >= t) if ge else (x < t), mo) for nm, t, ge in SHARE_X}
    touch = {f"peak_ge{t:g}": _hits(pk >= t, mo) for t in PEAK_X}
    fin = np.isfinite(gm)
    best = int(np.nanargmax(gm)) if fin.any() else None
    worst = int(np.nanargmin(gm)) if fin.any() else None
    out = {"pool": pool, "arm": arm, "size": size, "n": int(len(x)), "p10": q[0], "p25": q[1], "p50": q[2], "p75": q[3], "p90": q[4],
           "min": float(x.min()) if len(x) else None, "max": float(x.max()) if len(x) else None, "shares": shares, "touch": touch,
           "flat": {"k": int(fl.sum()), "n": int(len(fl))}, "grid_g": [None if not math.isfinite(v) else float(v) for v in gm],
           "months_pos": int((gm[fin] > 0).sum()), "best_month": best, "worst_month": worst,
           "year_g": [float(np.nanmean(gm[12 * y:12 * y + 12])) if np.isfinite(gm[12 * y:12 * y + 12]).any() else None for y in range(3)],
           "year_n": [int(gcnt[12 * y:12 * y + 12].sum()) for y in range(3)],
           "goal": {"ge2": int((x >= 2).sum()), "ge5": int((x >= 5).sum()), "le0.5": int((x <= 0.5).sum()), "n": int(len(x))},
           "busts": _busts(accs), "n_accounts": len(accs), "flag": XC.c7_mark(int(len(x)))}
    cache[key] = out
    return out


def _x014_row(ctx, d: dict, live: bool, private: bool = False) -> list:
    s, t = d["shares"], d["touch"]["peak_ge5"]
    lab = (_plab(d["arm"]) if private else _row_label(ctx, d["pool"], d["arm"])) + (" · 1/1 크기" if live else "")
    p50 = fx(d["p50"]) + (f" · {XC.bust_cell(d['busts'], d['n_accounts'])}" if live else "")
    touch = f"{fkn(t['k'], t['n'])} ({t['months']}개 달에 몰림)" if t["k"] else f"{fkn(0, t['n'])}"
    return [lab, p50 + RL.mark(d["n"]), fx(d["p90"]), fx(d["max"]), fsh(s["lt1"]["k"] / max(1, s["lt1"]["n"])),
            fsh(s["ge1.5"]["k"] / max(1, s["ge1.5"]["n"])), fsh(s["ge2"]["k"] / max(1, s["ge2"]["n"])), fsh(s["ge5"]["k"] / max(1, s["ge5"]["n"])),
            touch, fsh(d["flat"]["k"] / max(1, d["flat"]["n"]))]


X014_HEAD = ["방식", "보통 달", "좋은 달(10번 중 1번)", "가장 좋은 달", "손해 본 달", "x1.5 이상", "x2 이상", "x5 이상", "달 중에 x5에 닿은 달",
             "거래 없던 달"]


def read_X_014(ctx) -> dict:
    """X-014 한 달 눈금: 월 배수 분포 (see E.3)."""
    r = RL.new_result("X-014", "A")
    for pool in XC.POOLS:
        N = _N(ctx, pool)
        _pub, mon = _route(r, pool)
        rows = []
        for a in RL.money_rows(ctx, pool):
            rows.append({"arm": a, "quarter": month_dist(ctx, pool, a, Q), "live": month_dist(ctx, pool, a, LIVE)})
        mon["by_arm"] = rows
        ds = pool == "ds"
        if not ds:
            body = [RL.pool_head(pool, N), "", f"꼬리표: {TAG_FIT}. 한 달 배수 x = 그 달 말 지갑 / 지난달 말 지갑 (1/4 크기, 아래 줄은 1/1 크기).", ""]
            body += RL.md_table(X014_HEAD, [row for d in rows for row in (_x014_row(ctx, d["quarter"], False), _x014_row(ctx, d["live"], True))])
            body += [_thin_line(2 * len(rows), sum(1 for d in rows for k in ("quarter", "live") if d[k]["n"] < XC.THIN_MIN)),
                     "겹치지 않는 독립 표본은 약 36달입니다.", W["W7"], W["W9"], ""]
            r["md"] += body
            app = [RL.pool_head(pool, N), "", "달력표: 달마다 픽 평균 성장(%, 1/4 크기, 살아 있는 계좌만).", ""]
            for d in rows:
                q = d["quarter"]
                grid = [[str(2021 + y)] + [RL.fmt_f(XC.pct_month(v), 1) if v is not None else XC.EMPTY for v in q["grid_g"][12 * y:12 * y + 12]]
                        for y in range(3)]
                app += [f"**{_row_label(ctx, pool, d['arm'])}**: 더 좋은 달 {fkn(q['months_pos'], NM)}, 가장 좋은 달 "
                        f"{_month_label(ctx, q['best_month']) if q['best_month'] is not None else XC.EMPTY}, 가장 나쁜 달 "
                        f"{_month_label(ctx, q['worst_month']) if q['worst_month'] is not None else XC.EMPTY}, 해마다 평균 "
                        + " / ".join(fg(v) + RL.mark(n) for v, n in zip(q["year_g"], q["year_n"]))
                        + f"; 픽-달 칸 중 x2 이상 {q['goal']['ge2']}개, x5 이상 {q['goal']['ge5']}개, x0.5 이하 {q['goal']['le0.5']}개 "
                        f"(전체 {q['goal']['n']}칸); 분위 x{RL.fmt_f(q['p10'])} / x{RL.fmt_f(q['p25'])} / x{RL.fmt_f(q['p50'])} / "
                        f"x{RL.fmt_f(q['p75'])} / x{RL.fmt_f(q['p90'])} (10/25/50/75/90번째), 가장 나쁜 달 {fx(q['min'])}", ""]
                app += RL.md_table(["해"] + [f"{m}월" for m in range(1, 13)], grid)
                t = q["touch"]
                hit = lambda h: (f"{fkn(h['k'], h['n'])} ({h['months']}개 달, 가장 많은 달이 {fsh(h['top_month_share'], 0)})" if h["k"]  # noqa: E731
                                 else f"{fkn(0, h['n'])} (-)")
                app += ["한 달 배수 비율: " + ", ".join(f"{lab} {hit(q['shares'][key])}" for key, lab in (
                    ("ge1.1", "x1.1 이상"), ("ge1.5", "x1.5 이상"), ("ge2", "x2 이상"), ("ge5", "x5 이상"), ("lt1", "x1 미만"), ("lt0.5", "x0.5 미만")))
                        + f"; 거래 없던 달 {fkn(q['flat']['k'], q['flat']['n'])}", "",
                        "달 중에 닿은 최고(실현 지갑, 거래가 끝날 때만): " + ", ".join(f"x{th:g} 이상 {hit(t[f'peak_ge{th:g}'])}" for th in PEAK_X), ""]
            r["md_appendix"] += app
        else:
            r["md"] += [RL.pool_head(pool, N), "", "이 표는 모두 돈 숫자라 이 문서에 적지 않습니다(비공개 보고서).", ""]
            pv = [_psec("X-014", "핵심"), "", f"꼬리표: {TAG_FIT} (딥시크).", "", "| 딥시크 방식 | " + " | ".join(X014_HEAD[1:]) + " |",
                  "|" + "---|" * len(X014_HEAD)]
            pv += ["| " + " | ".join(_x014_row(ctx, d[k], k == "live", private=True)) + " |" for d in rows for k in ("quarter", "live")]
            r["md_private"] += pv + ["", "딥시크 달은 겹치지 않는 독립 표본이 약 36달입니다.", ""]
            pa = [_psec("X-014", "부록"), ""]
            for d in rows:
                q = d["quarter"]
                pa.append(f"- {_plab(d['arm'])}: 달력 " + " ".join(RL.fmt_f(XC.pct_month(v), 1) if v is not None else "-" for v in q["grid_g"])
                          + f"; 더 좋은 달 {fkn(q['months_pos'], NM)}; 해마다 " + " / ".join(fg(v) for v in q["year_g"]))
            r["md_private_appendix"] += pa + [""]
    return _finish_ds(r)


# ====================================================================================================== X-024 봉 종류별
CELLS = (("단타", ("15m", "30m")), ("15m", ("15m",)), ("30m", ("30m",)), ("1h", ("1h",)), ("4h", ("4h",)), ("1h+4h", ("1h", "4h")))
CELL_KO = {"단타": "단타(15분+30분)", "15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간", "1h+4h": "1시간+4시간"}
BODY_CELLS = ("단타", "15m", "30m", "1h", "4h")


def _cell_counts(ctx, picks: list, arm: str, size: float) -> dict:
    if not picks:
        return {"picks": 0, "entered": 0, "skipped": 0, "closed": 0, "wins": 0, "flag": XC.EMPTY}
    accs = [XC.account(ctx, p, arm, size) for p in picks]
    c = lambda nm: int(sum(MT.count(a, nm) for a in accs))  # noqa: E731
    hold = np.concatenate([np.asarray(a["hold_h"], float)[_closed(a)] for a in accs])
    rs = np.sum([a["reasons"] for a in accs], axis=0)
    closed = c("closed")
    return {"picks": len(picks), "entered": c("entered"), "entered_per_month": XC.per_account_month(c("entered"), len(picks)),
            "skipped": c("skipped"), "closed": closed, "wins": c("wins"), "win_share": c("wins") / closed if closed else None, **_hold(hold),
            "reasons": {x: (int(rs[RL.REASON_CODE[x]]) / closed if closed else None) for x in RL.REASON_COLS},
            "entries_at_rule_minute": c("entries_at_rule_minute"), "flag": XC.c7_mark(closed, len(picks))}


def read_X_024(ctx) -> dict:
    """X-024 봉 종류별 (see E.3)."""
    r = RL.new_result("X-024", "A")
    for pool in XC.POOLS:
        picks = ctx.pool_picks(pool)
        N = len(picks)
        pub, mon = _route(r, pool)
        cp = {nm: [p for p in picks if p["tf"] in tfs] for nm, tfs in CELLS}
        rows = {}
        for size in (Q, LIVE):
            e0 = {nm: _cell_counts(ctx, cp[nm], "E0", size) for nm, _ in CELLS}
            for arm in RL.arm_rows(ctx, pool):
                cells = e0 if arm == "E0" else {nm: _cell_counts(ctx, cp[nm], arm, size) for nm, _ in CELLS}
                for nm, _ in CELLS:
                    c = cells[nm]
                    c["entered_e0"], c["skipped_e0"] = e0[nm]["entered"], e0[nm]["skipped"]
                    c["entered_change_pct"] = (100.0 * (c["entered"] / e0[nm]["entered"] - 1.0)) if e0[nm]["entered"] else None
                    base = RL.q15_base(arm)
                    if base and nm in ("단타", "15m", "30m"):
                        c["label"] = f"= {base}"
                    if len(cp[nm]) == 1 and XC.c13_mark(cp[nm][0], arm):
                        c["label"] = XC.c13_mark(cp[nm][0], arm)
                    r["csv"].append({"read": "X-024", "pool": pool, "arm": arm, "size": size, "tf": nm, "picks": c["picks"], "entered": c["entered"],
                                     "entered_e0": c["entered_e0"], "skipped": c["skipped"], "skipped_e0": c["skipped_e0"], "closed": c["closed"],
                                     "wins": c["wins"], "hold_median": c.get("hold_median"), "share_gt4h": c.get("share_gt4h"),
                                     "share_gt8h": c.get("share_gt8h"), "share_gt18h": c.get("share_gt18h"),
                                     **{f"reasons_{x}": (c.get("reasons") or {}).get(x) for x in RL.REASON_COLS},
                                     "entries_at_rule_minute": c.get("entries_at_rule_minute")})
                rows.setdefault(arm, {})[size] = cells
        pub["by_arm"] = [{"arm": a, "size": s, "cells": [{"tf": nm, **rows[a][s][nm]} for nm, _ in CELLS]}
                         for a in RL.money_rows(ctx, pool) for s in (Q, LIVE)]
        # money (E0 and choosable rows, quarter size)
        mrows = []
        for a in RL.money_rows(ctx, pool):
            cells = {}
            for nm, _ in CELLS:
                ps = cp[nm]
                if not ps:
                    cells[nm] = {"picks": 0}
                    continue
                av = [XC.account(ctx, p, a, Q) for p in ps]
                ae = [XC.account(ctx, p, "E0", Q) for p in ps]
                mp = np.array([MT.pick_Mp(v, e) for v, e in zip(av, ae)])
                D = np.mean([np.asarray(v["g"]) - np.asarray(e["g"]) for v, e in zip(av, ae)], axis=0)
                cells[nm] = {"picks": len(ps), "M": float(mp.mean()), "Mp_pos": int((mp > 0).sum()), "D_pos": int((D > 0).sum()),
                             "own_growth_log": XC.own_growth_log(av),
                             "final_multiple_median": float(np.median([float(x["w_end"]) / float(x["w0"]) for x in av]))}
            parts = [len(cp[nm]) / N * cells[nm]["M"] if cp[nm] else 0.0 for nm in ("15m", "30m", "1h", "4h")]
            MP = XC.pooled_M(ctx, pool, a)
            if abs(sum(parts) - MP) > 1e-9:
                raise AssertionError(f"X-024: the timeframe contributions do not add up to M_P ({pool} {a})")
            sh = XC.c17_shares(parts, MP)
            mrows.append({"arm": a, "M": MP, "cells": [{"tf": nm, **cells[nm]} for nm, _ in CELLS], "contrib": parts,
                          "contrib_share": None if sh is None else sh.tolist()})
        mon["money_by_arm"] = mrows
        # ---------------------------------------------------------------- Korean lines
        ds = pool == "ds"
        body = [RL.pool_head(pool, N), "", "읽는 법: 칸마다 '픽 수 · 진입(E0 대비) · 보유 중앙값 · 8시간 넘게 든 비율 · 승률'입니다. 보유와 진입을 먼저 봅니다.", ""]
        tab = []
        for a in RL.money_rows(ctx, pool):
            cells = rows[a][Q]
            line = [_row_label(ctx, pool, a)]
            for nm in BODY_CELLS:
                c = cells[nm]
                if not c["picks"]:
                    line.append(XC.EMPTY)
                    continue
                if ds:
                    ent = f"진입 {fn(c['entered'])} (E0 {fn(c['entered_e0'])})"
                    s8, ws = f"8시간 넘음 {fkn(c['n_gt8h'], c['closed'])}", f"승 {fkn(c['wins'], c['closed'])}"
                else:
                    ent = f"진입 {fn(c['entered'])} ({'+' if (c['entered_change_pct'] or 0) >= 0 else ''}{RL.fmt_f(c['entered_change_pct'], 1)}%)"
                    s8, ws = f"8시간 넘음 {fsh(c['share_gt8h'], 0)}", f"승률 {fsh(c['win_share'], 0)}"
                lab = f" [{c['label']}]" if c.get("label") else ""
                line.append(f"픽 {c['picks']}개 · {ent} · {fh(c['hold_median'])} · {s8} · {ws}{RL.mark(c['closed'], c['picks'])}{lab}")
            tab.append(line)
            if not ds and a != "E0":
                mm = next(x for x in mrows if x["arm"] == a)
                cm = {x["tf"]: x for x in mm["cells"]}
                tab.append([f"{a} 돈"] + [
                    (f"좋아진 픽 {fkn(cm[nm]['Mp_pos'], cm[nm]['picks'])} · E0 대비 {fg(cm[nm]['M'])} (자체 {fg(cm[nm]['own_growth_log'])}) · "
                     f"36달 중 {cm[nm]['D_pos']}달 더 좋음" if cm[nm]["picks"] else XC.EMPTY) for nm in BODY_CELLS])
            if not ds and a == "E0":
                e0m = next(x for x in mrows if x["arm"] == "E0")
                cm = {x["tf"]: x for x in e0m["cells"]}
                tab.append(["E0 자체 성장 · 최종 배수 중앙값"] + [
                    (f"{fg(cm[nm]['own_growth_log'])} · {fx(cm[nm]['final_multiple_median'])}" if cm[nm]["picks"] else XC.EMPTY) for nm in BODY_CELLS])
        head = ["방식"] + [CELL_KO[nm] for nm in BODY_CELLS]
        body += RL.md_table(head, tab)
        n_cells = len(RL.money_rows(ctx, pool)) * len(BODY_CELLS)
        n_thin = sum(1 for a in RL.money_rows(ctx, pool) for nm in BODY_CELLS
                     if rows[a][Q][nm]["picks"] and (rows[a][Q][nm]["closed"] < XC.THIN_MIN or rows[a][Q][nm]["picks"] < XC.FEW_PICKS))
        body += [_thin_line(n_cells, n_thin), "봉마다 규칙을 따로 고르지 않습니다.", W["W21"]]
        if not ds:
            for mm in mrows[1:]:
                if mm["contrib_share"] is None:
                    body.append(f"{mm['arm']}: 봉별 몫 " + " / ".join(f"{CELL_KO[nm]} {fc(v) if cp[nm] else XC.EMPTY}" for nm, v in
                                                                    zip(("15m", "30m", "1h", "4h"), mm["contrib"]))
                                + f" (%/월 기여(근사)). {W['W15']}")
                else:
                    body.append(f"{mm['arm']}: 봉별 몫 " + " / ".join(f"{CELL_KO[nm]} {fsh(v, 0) if cp[nm] else XC.EMPTY}" for nm, v in
                                                                    zip(("15m", "30m", "1h", "4h"), mm["contrib_share"])) + " (E0 대비 차이 = 100%)")
                if XC.pct_month(XC.own_growth_log(RL.pool_accounts(ctx, pool, mm["arm"]))) <= 0:
                    body.append(f"{mm['arm']}: {W['W12']}")
            body.append(XC.CONTRIB_NOTE_KO)
            if any(RL.q15_base(a) for a in RL.money_rows(ctx, pool)):
                body.append("q15 방식은 15분·30분 픽에서 바탕 방식과 같습니다([= …] 표시).")
        body.append("")
        r["md"] += body
        # appendix: live size counts and coin x bar group counts (E0 and choosable rows)
        app = [RL.pool_head(pool, N), "", "1/1 크기 건수(진입 / 들고 있어서 놓친 신호 / 보유 중앙값):", ""]
        app += RL.md_table(["방식"] + [CELL_KO[nm] for nm, _ in CELLS], [[_row_label(ctx, pool, a)] + [
            (f"{fn(rows[a][LIVE][nm]['entered'])} / {fn(rows[a][LIVE][nm]['skipped'])} / {fh(rows[a][LIVE][nm].get('hold_median'))}"
             if rows[a][LIVE][nm]["picks"] else XC.EMPTY) for nm, _ in CELLS] for a in RL.money_rows(ctx, pool)])
        syms = RL.coins(ctx)
        app += ["코인 x 봉 묶음 거래 수(단타 / 1시간+4시간):", ""]
        grid = []
        for a in RL.money_rows(ctx, pool):
            cnt = {}
            for nm in ("단타", "1h+4h"):
                cc = np.zeros(len(syms), int)
                for p in cp[nm]:
                    acc = XC.account(ctx, p, a, Q)
                    cc += np.bincount(np.asarray(acc["tr_coin"])[_closed(acc)], minlength=len(syms))[:len(syms)]
                cnt[nm] = cc
            grid.append([_row_label(ctx, pool, a)] + [f"{cnt['단타'][k]} / {cnt['1h+4h'][k]}" for k in range(len(syms))])
            pub.setdefault("by_coin_tf", []).append({"arm": a, "cells": [{"coin": s, "n_scalp": int(cnt["단타"][k]), "n_long_tf": int(cnt["1h+4h"][k])}
                                                                         for k, s in enumerate(syms)]})
        app += RL.md_table(["방식"] + [s[:-4] for s in syms], grid)
        app += [_thin_line(len(grid) * len(syms), sum(1 for b in pub["by_coin_tf"] for c in b["cells"] for v in (c["n_scalp"], c["n_long_tf"])
                                                        if 0 < v < XC.THIN_MIN)), ""]
        r["md_appendix"] += app
        if ds:
            pv = [_psec("X-024", "핵심"), "", "| 딥시크 방식 | " + " | ".join(CELL_KO[nm] for nm, _ in CELLS) + " |", "|" + "---|" * (len(CELLS) + 1)]
            for mm in mrows:
                cm = {x["tf"]: x for x in mm["cells"]}
                if mm["arm"] == "E0":
                    pv.append(f"| {_plab('E0')} 자체 · 최종 배수 | " + " | ".join(
                        (f"{fg(cm[nm]['own_growth_log'])} · {fx(cm[nm]['final_multiple_median'])}" if cm[nm]["picks"] else "-") for nm, _ in CELLS) + " |")
                else:
                    pv.append(f"| {_plab(mm['arm'])} | " + " | ".join(
                        (f"좋아진 픽 {fkn(cm[nm]['Mp_pos'], cm[nm]['picks'])} · E0 대비 {fg(cm[nm]['M'])} (자체 {fg(cm[nm]['own_growth_log'])}) · "
                         f"36달 중 {cm[nm]['D_pos']}달" if cm[nm]["picks"] else "-") for nm, _ in CELLS) + " |")
            pv += ["", "딥시크 봉별 몫(%/월 기여(근사), 15분 / 30분 / 1시간 / 4시간): " + "; ".join(
                f"{mm['arm']} " + " / ".join(fc(v) for v in mm["contrib"]) for mm in mrows[1:]), ""]
            r["md_private"] += pv
    return _finish_ds(r)


# ====================================================================================================== X-025 신호는 어디로 갔나
def _funnel(ctx, pool: str, arm: str, size: float, money: bool) -> dict:
    picks = ctx.pool_picks(pool)
    N = len(picks)
    syms = RL.coins(ctx)
    K = len(syms)
    tot = {"offered": 0, "rejected": 0, "skipped": 0, "entered": 0, "e_rest": 0}
    hold_ms, holds = 0, []
    sizeable_n = 0
    pm = []
    B = np.zeros((K, K), int)
    ages, states = [], {"same_minute": 0, "profit": 0, "loss": 0, "even": 0}
    sp_coin = np.zeros((K, 4), int)                                    # columns: offered, rejected, skipped, entered
    sp_tf = {tf: np.zeros(4, int) for tf in ("15m", "30m", "1h", "4h")}
    sp_state = np.zeros((len(MT.DX.STATE_KO), 4), int)
    for p in picks:
        st = RL.c5_status(ctx, p, arm, size)
        a = XC.account(ctx, p, arm, size)
        s = st["status"]
        n_off = len(s)
        cnt = [int((s == c).sum()) for c in range(5)]
        if n_off != cnt[0] + cnt[1] + cnt[2] + cnt[3] + cnt[4] or cnt[1] != MT.count(a, "entered"):
            raise AssertionError(f"X-025: the identity (a) = (b) + (c) + (d) + (e) fails ({pool} {arm})")
        tot["offered"] += n_off
        tot["skipped"] += cnt[0]
        tot["entered"] += cnt[1]
        tot["rejected"] += cnt[2]
        tot["e_rest"] += cnt[3] + cnt[4]
        fi, ex = np.asarray(a["tr_fill"], np.int64), np.asarray(a["tr_exit"], np.int64)
        hold_ms += int((ex - fi).sum())
        holds.append(np.asarray(a["hold_h"], float)[_closed(a)])
        off = RL.offered(ctx, p)
        if money:                                                          # the splits are printed for E0 and choosable rows only
            masks = (np.ones(n_off, bool), s == 2, s == 0, s == 1)
            for j_, m_ in enumerate(masks):
                sp_coin[:, j_] += np.bincount(off["coin"][m_], minlength=K)[:K]
                sp_state[:, j_] += np.bincount(off["state"][m_].astype(np.int64), minlength=len(MT.DX.STATE_KO))[:len(MT.DX.STATE_KO)]
                sp_tf[p["tf"]][j_] += int(m_.sum())
        # blockers: for each skipped q the entered trade with the greatest tr_fill <= fill_q
        sk = np.flatnonzero(s == 0)
        if len(sk) and money:
            tf_q = st["t_fill"][sk]
            j = np.searchsorted(fi, tf_q, side="right") - 1
            if np.any(j < 0):
                raise AssertionError("X-025: a skipped signal without a blocker")
            cb = np.asarray(a["tr_coin"], np.int64)[j]
            np.add.at(B, (off["coin"][sk], cb), 1)
            ages.append((tf_q - fi[j]) / XC.HOUR_MS)
            fr = RL.c4_trade_frame(ctx, p, a)
            same = fi[j] == tf_q
            states["same_minute"] += int(same.sum())
            mk = ctx.market
            for c in np.unique(cb[~same]).tolist():
                sel = np.flatnonzero((~same) & (cb == c))
                ts = RL.coin_ts(ctx, c)
                m = np.minimum(np.searchsorted(ts, tf_q[sel], side="left"), len(ts) - 1)
                v = fr["side"][j[sel]] * (mk.cat["o"][mk.starts[c] + m] - fr["fill"][j[sel]])
                states["profit"] += int((v > 0).sum())
                states["loss"] += int((v < 0).sum())
                states["even"] += int((v == 0).sum())
            sz = RL.sizeable(ctx, p, arm, size)
            sizeable_n += int(sz["sizeable"].sum())
        if money:
            mf = np.bincount(np.asarray(a["month_fill"], np.int64), minlength=NM)[:NM]
            pm.append(mf)
    hh = np.concatenate(holds) if holds else np.zeros(0)
    out = {"arm": arm, "size": size, "offered": tot["offered"], "rejected": tot["rejected"], "skipped": tot["skipped"], "entered": tot["entered"],
           "rejected_per_month": XC.per_account_month(tot["rejected"], N), "skipped_per_month": XC.per_account_month(tot["skipped"], N),
           "entered_per_month": XC.per_account_month(tot["entered"], N), "offered_per_month": XC.per_account_month(tot["offered"], N),
           "hold_time_in_market": hold_ms / (N * XC.N_DAYS * XC.DAY_MS) if N else None,
           "hold_hours_in_market": hold_ms / XC.HOUR_MS, "hold_hours_total": N * XC.N_DAYS * 24.0,
           "hold_capacity": (720.0 / float(hh.mean())) if len(hh) and hh.mean() > 0 else None,
           "flag": XC.c7_mark(tot["entered"])}
    if money:
        cell = lambda b, v: {"bucket": b, "offered": int(v[0]), "rejected": int(v[1]), "skipped": int(v[2]), "entered": int(v[3]),  # noqa: E731
                             "flag": XC.c7_mark(int(v[0]))}
        out["by_signal"] = {"coin": [cell(syms[k], sp_coin[k]) for k in range(K) if sp_coin[k, 0]],
                            "tf": [cell(tf, v) for tf, v in sp_tf.items() if v[0]],
                            "state": [cell(MT.DX.STATE_KO[c], sp_state[c]) for c in MT.DX.STATE_ORDER if sp_state[c, 0]]}
    if money:
        PM = np.concatenate(pm) if pm else np.zeros(0)
        ag = np.concatenate(ages) if ages else np.zeros(0)
        out.update(e_nofill_after_bust=tot["e_rest"], skipped_sizeable=sizeable_n, skipped_not_sizeable=tot["skipped"] - sizeable_n,
                   take_rate=tot["entered"] / tot["offered"] if tot["offered"] else None,
                   pick_month_p10=float(np.percentile(PM, 10)) if len(PM) else None, pick_month_p50=float(np.percentile(PM, 50)) if len(PM) else None,
                   pick_month_p90=float(np.percentile(PM, 90)) if len(PM) else None, pick_month_zero=float((PM == 0).mean()) if len(PM) else None,
                   by_blocker=B.tolist(), share_same_coin=float(np.trace(B) / B.sum()) if B.sum() else None,
                   hold_blocker_age=float(np.median(ag)) if len(ag) else None, blocker_state=states, flag_blockers=XC.c7_mark(int(B.sum())))
        if int(B.sum()) != tot["skipped"]:
            raise AssertionError("X-025: the blocker matrix does not sum to the skipped signals")
    return out


def read_X_025(ctx) -> dict:
    """X-025 신호는 어디로 갔나 (see E.3). The C5 audit (152 real re-runs) is a stage step of reads.py, recorded under X-025."""
    r = RL.new_result("X-025", "A")
    syms = RL.coins(ctx)
    for pool in XC.POOLS:
        picks = ctx.pool_picks(pool)
        N = len(picks)
        pub, mon = _route(r, pool)
        ds = pool == "ds"
        rows = {}
        for arm in RL.arm_rows(ctx, pool):
            money = XC.money_allowed(ctx, pool, arm)
            for size in (Q, LIVE):
                f = _funnel(ctx, pool, arm, size, money)
                rows[(arm, size)] = f
                r["csv"].append({"read": "X-025", "pool": pool, "arm": arm, "size": size, "offered": None if ds else f["offered"], "rejected": f["rejected"],
                                 "skipped": f["skipped"], "entered": f["entered"], "rejected_per_month": f["rejected_per_month"],
                                 "skipped_per_month": f["skipped_per_month"], "entered_per_month": f["entered_per_month"],
                                 "hold_time_in_market": f["hold_time_in_market"], "hold_capacity": f["hold_capacity"]})
        ceil = {size: sum(RL.entry_ceiling(ctx, p, size) for p in picks) for size in (Q, LIVE)}
        ceil15 = {size: sum(RL.entry_ceiling(ctx, p, size, 15 * 60_000 if p["tf"] in RL.Q15_ON else None) for p in picks) for size in (Q, LIVE)}
        count_keys = ("arm", "size", "rejected", "skipped", "entered", "rejected_per_month", "skipped_per_month", "entered_per_month",
                      "hold_time_in_market", "hold_hours_in_market", "hold_hours_total", "hold_capacity", "flag", "by_signal")
        money_keys = ("e_nofill_after_bust", "skipped_sizeable", "skipped_not_sizeable", "take_rate", "pick_month_p10", "pick_month_p50",
                      "pick_month_p90", "pick_month_zero", "blocker_state")
        blk_keys = ("by_blocker", "share_same_coin", "hold_blocker_age", "flag_blockers")
        mr = RL.money_rows(ctx, pool)
        pub["offered_per_pool"] = rows[("E0", Q)]["offered"] if not ds else None
        pub["by_arm"] = []
        for a in mr:
            for s in (Q, LIVE):
                f = rows[(a, s)]
                row = {k: f[k] for k in count_keys}
                if not ds:
                    row["offered"] = f["offered"]
                    row["offered_per_month"] = f["offered_per_month"]
                    row.update({k: f[k] for k in money_keys})
                row.update({k: f[k] for k in blk_keys})
                pub["by_arm"].append(row)
        if ds:
            mon["by_arm"] = [{k: rows[(a, s)][k] for k in ("arm", "size", "offered", "offered_per_month") + money_keys} for a in mr for s in (Q, LIVE)]
        mon["ceiling"] = {"quarter": ceil[Q], "live": ceil[LIVE], "quarter_q15": ceil15[Q], "live_q15": ceil15[LIVE]}
        if ds:
            pub.pop("offered_per_pool", None)
        # ---------------------------------------------------------------- Korean lines
        e0 = rows[("E0", Q)]
        body = [RL.pool_head(pool, N), "", "읽는 법: 나온 신호는 진입 조건이 맞은 신호 전부이고, 그중 일부는 크기 규칙에 걸리거나(지갑에 맞는 크기가 없음) "
                "포지션을 들고 있어서 놓칩니다. 건수 칸은 '1/4 크기 / 1/1 크기'이며 1/4 크기가 기준입니다.", ""]
        tab = []
        for a in mr:
            f, fl = rows[(a, Q)], rows[(a, LIVE)]
            if ds:
                tab.append([_row_label(ctx, pool, a), f"{fn(f['rejected'])} / {fn(fl['rejected'])}", f"{fn(f['skipped'])} / {fn(fl['skipped'])}",
                            f"{fn(f['entered'])} / {fn(fl['entered'])}{RL.mark(f['entered'])}",
                            f"{fn(f['hold_hours_in_market'])}시간 / 전체 {fn(f['hold_hours_total'])}시간", f"{RL.fmt_f(f['entered_per_month'])}번"])
            else:
                tab.append([_row_label(ctx, pool, a), fn(f["offered"]), f"{fn(f['rejected'])} / {fn(fl['rejected'])}",
                            f"{fn(f['skipped'])} / {fn(fl['skipped'])} · 그중 탈 수 있었던 것 {fn(f['skipped_sizeable'])}",
                            f"{fn(f['entered'])} / {fn(fl['entered'])}{RL.mark(f['entered'])}",
                            f"{fn(ceil[Q])} / {fn(ceil[LIVE])}" if a == "E0" else "E0 줄과 같음",
                            fsh(f["hold_time_in_market"]), f"{RL.fmt_f(f['entered_per_month'])}번"])
        if ds:
            head = ["방식", "크기 규칙에 걸려 못 탄 신호", "들고 있어서 놓친 신호", "탄 신호", "포지션을 들고 있던 시간", "한 달 진입"]
        else:
            head = ["방식", "나온 신호", "크기 규칙에 걸려 못 탄 신호", "들고 있어서 놓친 신호", "탄 신호", "어떤 청산으로도 최대로 탈 수 있었던 수",
                    "포지션을 들고 있던 시간 비율", "한 달 진입"]
        body += RL.md_table(head, tab)
        body += [_thin_line(len(mr), sum(1 for a in mr if rows[(a, Q)]["entered"] < XC.THIN_MIN))]
        if not ds:
            body += [f"지금 청산(E0): 들고 있어서 놓친 {fn(e0['skipped'])}개 중 실제로 탈 수 있었던 것은 {fn(e0['skipped_sizeable'])}개입니다. "
                     f"어떤 청산으로도 최대 {fn(ceil[Q])}번(15분마다 볼 때 {fn(ceil15[Q])}번)까지 탈 수 있었습니다.",
                     "'탈 수 있었던 것'은 그 신호가 나온 때의 지갑으로 크기 규칙을 통과했다는 뜻이며, 그 거래가 이겼을지는 따로 봅니다."]
        body.append("")
        r["md"] += body
        app = [RL.pool_head(pool, N), "", "자리를 막은 코인(행 = 놓친 신호의 코인, 열 = 그때 들고 있던 거래의 코인), 지금 청산(E0):", ""]
        f0 = rows[("E0", Q)]
        app += RL.md_table(["놓친 \\ 막은"] + [s[:-4] for s in syms],
                           [[syms[i][:-4] + RL.mark(sum(f0["by_blocker"][i]))] + [str(v) for v in f0["by_blocker"][i]] for i in range(len(syms))])
        app += ["같은 코인끼리 막은 비율: " + (fkn(int(np.trace(np.array(f0["by_blocker"]))), int(np.sum(f0["by_blocker"]))) if f0["by_blocker"] else XC.EMPTY)
                + f"; 막은 거래가 열린 지 중앙값 {fh(f0['hold_blocker_age'])}.", ""]
        for key, lab in (("coin", "신호 코인"), ("tf", "픽 봉"), ("state", "신호 때 장세")):
            app += [f"{lab}별 (나온 신호 / 크기 규칙 / 놓침 / 탐), 1/4 크기:" if not ds else f"{lab}별 (크기 규칙 / 놓침 / 탐), 1/4 크기:", ""]
            buckets = [c["bucket"] for c in f0["by_signal"][key]]
            tabs = []
            for a in mr:
                bs = {c["bucket"]: c for c in rows[(a, Q)]["by_signal"][key]}
                tabs.append([_row_label(ctx, pool, a)] + [
                    (f"{bs[b]['offered']} / " if not ds else "") + f"{bs[b]['rejected']} / {bs[b]['skipped']} / {bs[b]['entered']}"
                    + RL.mark(bs[b]["offered"]) for b in buckets])
            app += RL.md_table(["방식"] + [str(b)[:-4] if key == "coin" else str(b) for b in buckets], tabs)
            cells = [c for a in mr for c in rows[(a, Q)]["by_signal"][key]]
            app += [_thin_line(len(cells), sum(1 for c in cells if c["offered"] < XC.THIN_MIN)), ""]
        if not ds:
            app += ["막은 거래의 상태(놓친 신호가 나온 때): " + ", ".join(
                f"{_row_label(ctx, pool, a)} 같은 분 {rows[(a, Q)]['blocker_state']['same_minute']} · 수익 중 {rows[(a, Q)]['blocker_state']['profit']} · "
                f"손실 중 {rows[(a, Q)]['blocker_state']['loss']} · 본전 {rows[(a, Q)]['blocker_state']['even']}" for a in mr), "",
                    "한 픽-달 진입 수(10% / 50% / 90%, 진입 없던 픽-달 비율): " + ", ".join(
                f"{_row_label(ctx, pool, a)} {RL.fmt_f(rows[(a, Q)]['pick_month_p10'], 0)} / {RL.fmt_f(rows[(a, Q)]['pick_month_p50'], 0)} / "
                f"{RL.fmt_f(rows[(a, Q)]['pick_month_p90'], 0)} ({fsh(rows[(a, Q)]['pick_month_zero'])})" for a in mr), "",
                    "보유 시간으로 본 한 달 최대 진입(720시간 / 평균 보유): " + ", ".join(
                f"{_row_label(ctx, pool, a)} {RL.fmt_f(rows[(a, Q)]['hold_capacity'], 1)}번" for a in mr)
                    + "; 진입 비율(탄 / 나온): " + ", ".join(f"{_row_label(ctx, pool, a)} {fsh(rows[(a, Q)]['take_rate'])}" for a in mr), ""]
        r["md_appendix"] += app
        hd = r["headline"][pool]
        if ds:
            hd["funnel"] = {"public": f"지금 청산(E0)은 크기 규칙에 걸린 신호 {fn(e0['rejected'])}개, 들고 있어서 놓친 신호 {fn(e0['skipped'])}개, "
                                      f"탄 신호 {fn(e0['entered'])}개였습니다.",
                            "private": f"딥시크 지금 청산(E0): 나온 신호 {fn(e0['offered'])}개, 들고 있어서 놓친 {fn(e0['skipped'])}개 중 탈 수 있었던 것 "
                                       f"{fn(e0['skipped_sizeable'])}개, 어떤 청산으로도 최대 {fn(ceil[Q])}번."}
            pv = [_psec("X-025", "핵심"), "", "| 딥시크 방식 | 나온 신호 | 놓친 신호 중 탈 수 있었던 것 | 나머지(체결 안 됨 + 파산 뒤) | 진입 비율 |", "|---|---|---|---|---|"]
            pv += [f"| {_plab(a)} | {fn(rows[(a, Q)]['offered'])} | {fn(rows[(a, Q)]['skipped_sizeable'])} / {fn(rows[(a, Q)]['skipped'])} | "
                   f"{fn(rows[(a, Q)]['e_nofill_after_bust'])} | {fsh(rows[(a, Q)]['take_rate'])} |" for a in mr]
            pv += ["", f"딥시크 어떤 청산으로도 최대로 탈 수 있었던 수: {fn(ceil[Q])}번(15분마다 볼 때 {fn(ceil15[Q])}번), 1/1 크기 {fn(ceil[LIVE])}번.", ""]
            r["md_private"] += pv
            pa = [_psec("X-025", "부록"), ""]
            pa += [f"- {_plab(a)}: 픽-달 진입 {RL.fmt_f(rows[(a, Q)]['pick_month_p10'], 0)} / {RL.fmt_f(rows[(a, Q)]['pick_month_p50'], 0)} / "
                   f"{RL.fmt_f(rows[(a, Q)]['pick_month_p90'], 0)}, 진입 없던 픽-달 {fsh(rows[(a, Q)]['pick_month_zero'])}; 막은 거래 상태 "
                   f"같은 분 {rows[(a, Q)]['blocker_state']['same_minute']} · 수익 중 {rows[(a, Q)]['blocker_state']['profit']} · "
                   f"손실 중 {rows[(a, Q)]['blocker_state']['loss']} · 본전 {rows[(a, Q)]['blocker_state']['even']}" for a in mr]
            r["md_private_appendix"] += pa + [""]
        else:
            hd["funnel"] = {"public": f"지금 청산(E0)은 나온 신호 {fn(e0['offered'])}개 중 {fn(e0['entered'])}개를 탔고, 크기 규칙에 걸린 것 "
                                      f"{fn(e0['rejected'])}개, 들고 있어서 놓친 것 {fn(e0['skipped'])}개(그중 실제로 탈 수 있었던 것 "
                                      f"{fn(e0['skipped_sizeable'])}개)였습니다. 어떤 청산으로도 최대 {fn(ceil[Q])}번까지 탈 수 있었습니다.",
                            "private": None}
    return _finish_ds(r)


# ====================================================================================================== X-027 이긴 이유 나누기
def read_X_027(ctx) -> dict:
    """X-027 이긴 이유 나누기 (see E.3)."""
    r = RL.new_result("X-027", "A")
    for pool in XC.POOLS:
        picks = ctx.pool_picks(pool)
        N = len(picks)
        pub, mon = _route(r, pool)
        ds = pool == "ds"
        part1 = {}
        for arm in RL.arm_rows(ctx, pool):
            t = {"n": 0, "n_e0": 0, "n_same": 0, "n_exit": 0, "n_new": 0, "n_drop": 0, "changed": 0}
            for p in picks:
                v, e = XC.account(ctx, p, arm, Q), XC.account(ctx, p, "E0", Q)
                m = RL.c4_match(v, e)
                t["n"] += m["n_v"]
                t["n_e0"] += m["n_e0"]
                for k in ("n_same", "n_exit", "n_new", "n_drop"):
                    t[k] += m[k]
                t["changed"] += MT.changed_trades(v, e)
            if t["n_exit"] + t["n_new"] != t["changed"]:
                raise AssertionError("X-027: EXIT + NEW differs from the trades changed")
            t.update(share_same=t["n_same"] / t["n"] if t["n"] else None, share_exit=t["n_exit"] / t["n"] if t["n"] else None,
                     share_new=t["n_new"] / t["n"] if t["n"] else None, share_drop=t["n_drop"] / t["n_e0"] if t["n_e0"] else None,
                     flag=XC.c7_mark(t["n"]))
            part1[arm] = t
            r["csv"].append({"read": "X-027", "pool": pool, "arm": arm, "n": t["n"], "n_e0": t["n_e0"], "n_same": t["n_same"], "n_exit": t["n_exit"],
                             "n_new": t["n_new"], "n_drop": t["n_drop"]})
        mr = RL.money_rows(ctx, pool)
        part2, part3 = {}, {}
        for a in mr:
            T = np.zeros((N, 4))
            n_parts = np.zeros(4, int)
            early_n = matched = 0
            dR, twin_r = [], np.zeros(len(RL.REASON_COLS), int)
            hv, he = [], []
            fam13 = a.startswith("F13.")
            for i, p in enumerate(picks):
                v, e = XC.account(ctx, p, a, Q), XC.account(ctx, p, "E0", Q)
                fv, fe = RL.c4_trade_frame(ctx, p, v), RL.c4_trade_frame(ctx, p, e)
                m = RL.c4_match(v, e)
                cls, j = m["cls"], m["e0_idx"]
                lv, le = fv["l"], fe["l"]
                T[i, 0] = float(lv[cls == RL.NEW].sum())
                T[i, 1] = float((lv[cls == RL.EXIT] - le[j[cls == RL.EXIT]]).sum())
                T[i, 2] = float((lv[cls == RL.SAME] - le[j[cls == RL.SAME]]).sum())
                T[i, 3] = -float(le[m["drop"]].sum())
                n_parts += [int((cls == RL.NEW).sum()), int((cls == RL.EXIT).sum()), int((cls == RL.SAME).sum()), int(m["drop"].sum())]
                if abs(float(T[i].sum()) - NM * MT.pick_Mp(v, e)) > 1e-9:
                    raise AssertionError(f"X-027: T_new + T_exit + T_same + T_drop differs from 36 M_p ({pool} {a})")
                if a != "E0":
                    rs = fv["reason"]
                    early = (rs == KX.R_RULE) | ((rs == KX.R_LOCK) if fam13 else False)
                    mt = early & (cls != RL.NEW)
                    early_n += int(early.sum())
                    matched += int(mt.sum())
                    dR.append(fv["R"][mt] - fe["R"][j[mt]])
                    tr = fe["reason"][j[mt]]
                    twin_r += [int((tr == RL.REASON_CODE[x]).sum()) for x in RL.REASON_COLS]
                    hv.append(fv["hold_h"][mt])
                    he.append(fe["hold_h"][j[mt]])
            P = T.mean(axis=0) / NM if N else np.zeros(4)
            MP = XC.pooled_M(ctx, pool, a)
            sh = XC.c17_shares(P, MP) if a != "E0" else None
            part2[a] = {"arm": a, "T_new": float(P[0]), "T_exit": float(P[1]), "T_same": float(P[2]), "T_drop": float(P[3]), "M": MP,
                        "share": None if sh is None else sh.tolist(), "n_parts": n_parts.tolist(),
                        "flags": [XC.c7_mark(int(x)) for x in n_parts], "own_growth_log": XC.own_growth_log(RL.pool_accounts(ctx, pool, a))}
            if a != "E0":
                d = np.concatenate(dR) if dR else np.zeros(0)
                part3[a] = {"arm": a, "n_early": early_n, "n_matched": matched, "n_unmatched": early_n - matched,
                            "share_better": float((d > 1e-9).mean()) if len(d) else None, "share_equal": float((np.abs(d) < 1e-9).mean()) if len(d) else None,
                            "share_worse": float((d < -1e-9).mean()) if len(d) else None,
                            "mean_dR_better": float(d[d > 1e-9].mean()) if (d > 1e-9).any() else None,
                            "mean_dR_worse": float(d[d < -1e-9].mean()) if (d < -1e-9).any() else None, "mean_dR": float(d.mean()) if len(d) else None,
                            "twin_reasons": {x: int(c) for x, c in zip(RL.REASON_COLS, twin_r)},
                            "hold_median_v": float(np.median(np.concatenate(hv))) if hv and len(np.concatenate(hv)) else None,
                            "hold_median_twin": float(np.median(np.concatenate(he))) if he and len(np.concatenate(he)) else None,
                            "flag": XC.c7_mark(matched)}
        pub["by_arm"] = [{"arm": a, **{k: part1[a][k] for k in ("n", "n_e0", "n_same", "n_exit", "n_new", "n_drop", "share_same", "share_exit",
                                                                  "share_new", "share_drop", "changed", "flag")}} for a in mr]
        pub["by_arm_early"] = [{"arm": a, "n_early": part3[a]["n_early"], "n_matched": part3[a]["n_matched"], "flag": part3[a]["flag"]} for a in mr if a in part3]
        mon["part2"] = [part2[a] for a in mr]
        mon["part3"] = [part3[a] for a in mr if a in part3]
        if ds:
            for row in mon["part3"]:
                row.pop("flag", None)
        # ---------------------------------------------------------------- Korean lines
        body = [RL.pool_head(pool, N), "", "읽는 법: 새 방식의 거래를 지금 청산(E0)의 거래와 진입(코인·방향·체결 분)으로 맞춰 봅니다. '같은 거래'는 진입과 끝이 모두 "
                "같고, '같은 진입 다른 청산'은 들어간 건 같은데 끝이 다르며, '새 진입'은 E0에는 없던 진입, '빠진 것'은 E0의 진입 중 이 방식에는 없는 것입니다.", ""]
        tab = []
        for a in mr:
            t = part1[a]
            if ds:
                cells = [f"{fkn(t['n_same'], t['n'])}", f"{fkn(t['n_exit'], t['n'])}", f"{fkn(t['n_new'], t['n'])}", f"{fkn(t['n_drop'], t['n_e0'])}"]
            else:
                cells = [fsh(t["share_same"]), fsh(t["share_exit"]), fsh(t["share_new"]), fsh(t["share_drop"])]
            tab.append([_row_label(ctx, pool, a)] + cells + [f"{fn(t['n'])}{RL.mark(t['n'])}"])
            if a in part3:
                p3 = part3[a]
                if ds:
                    tab.append([f"{a} 일찍 나옴", f"일찍 나온 {fn(p3['n_early'])}건 중 같은 진입이 E0에 있는 것 {fn(p3['n_matched'])}건{RL.mark(p3['n_matched'])}",
                                "", "", "", ""])
                else:
                    p2 = part2[a]
                    if part1[a]["n"] < XC.THIN_MIN:
                        src = f"건수 적음(거래 {part1[a]['n']}건): 나눠 적지 않습니다"
                    elif p2["share"] is not None:
                        src = ("E0 대비 차이의 출처(합 100%): 새 진입 " + fsh(p2["share"][0], 0) + " · 청산 방법만 바뀐 곳 " + fsh(p2["share"][1], 0)
                               + " · 크기 차이 " + fsh(p2["share"][2], 0) + " · 빠진 진입 " + fsh(p2["share"][3], 0))
                    else:
                        src = (f"E0 대비 차이의 출처(%/월 기여(근사)): 새 진입 {fc(p2['T_new'])} · 청산 방법만 바뀐 곳 {fc(p2['T_exit'])} · 크기 차이 "
                               f"{fc(p2['T_same'])} · 빠진 진입 {fc(p2['T_drop'])}. {W['W15']}")
                    early = (f"일찍 나온 {fn(p3['n_early'])}건 중 같은 진입의 E0보다 나았던 건 {fsh(p3['share_better'], 0)}"
                             f" (맞춘 {fn(p3['n_matched'])}건{RL.mark(p3['n_matched'])})")
                    w12 = f" {W['W12']}" if XC.pct_month(p2["own_growth_log"]) <= 0 else ""
                    tab.append([f"{a} 출처", src + f" (자체 {fg(p2['own_growth_log'])})" + w12, early, "", "", ""])
        body += RL.md_table(["방식", "같은 거래", "같은 진입 다른 청산", "새 진입", "지금 방식 진입 중 빠진 것", "거래 수"], tab)
        body += [_thin_line(len(mr), sum(1 for a in mr if part1[a]["n"] < XC.THIN_MIN))]
        if not ds:
            body += ["'크기 차이'는 같은 거래인데 지갑 크기가 달라 생긴 차이입니다. 출처는 '%/월 기여(근사)'이고 합하면 E0 대비 차이가 됩니다.", XC.CONTRIB_NOTE_KO]
        body.append("")
        r["md"] += body
        if not ds:
            app = [RL.pool_head(pool, N), "", "이득의 출처(%/월 기여(근사))와 일찍 나온 거래 비교(R: 손익 / 처음 손절 거리):", ""]
            app += RL.md_table(["방식", "새 진입", "청산만 바뀜", "크기 차이", "빠진 진입", "나음 / 같음 /못함", "평균 R 차이(나음 · 못함 · 전체)",
                                "E0 쪽 끝난 이유", "보유 중앙값(이 방식 / E0)"],
                               [[a, fc(part2[a]["T_new"]) + RL.mark(part2[a]["n_parts"][0]), fc(part2[a]["T_exit"]) + RL.mark(part2[a]["n_parts"][1]),
                                 fc(part2[a]["T_same"]) + RL.mark(part2[a]["n_parts"][2]), fc(part2[a]["T_drop"]) + RL.mark(part2[a]["n_parts"][3]),
                                 f"{fsh(part3[a]['share_better'], 0)} / {fsh(part3[a]['share_equal'], 0)} / {fsh(part3[a]['share_worse'], 0)}",
                                 f"{RL.fmt_f(part3[a]['mean_dR_better'])} · {RL.fmt_f(part3[a]['mean_dR_worse'])} · {RL.fmt_f(part3[a]['mean_dR'])}",
                                 " · ".join(f"{x} {c}" for x, c in part3[a]["twin_reasons"].items()),
                                 f"{fh(part3[a]['hold_median_v'])} / {fh(part3[a]['hold_median_twin'])}"] for a in mr if a in part3])
            app += ["일찍 나온 거래 비교는 그 청산이 비워 준 자리에서 새로 탄 거래를 세지 않습니다(그것은 '새 진입'에 들어 있습니다).", ""]
            r["md_appendix"] += app
        else:
            pv = [_psec("X-027", "핵심"), "", "| 딥시크 방식 | 새 진입 | 청산만 바뀜 | 크기 차이 | 빠진 진입 | 일찍 나와 나았던 비율 |", "|---|---|---|---|---|---|"]
            pv += [f"| {_plab(a)} | {fc(part2[a]['T_new'])} | {fc(part2[a]['T_exit'])} | {fc(part2[a]['T_same'])} | {fc(part2[a]['T_drop'])} | "
                   f"{fsh(part3[a]['share_better'], 0) if a in part3 else '-'} |" for a in mr]
            r["md_private"] += pv + ["", "딥시크 출처는 '%/월 기여(근사)'입니다.", ""]
            pa = [_psec("X-027", "부록"), ""]
            pa += [f"- {_plab(a)}: 나음/같음/못함 {fsh(part3[a]['share_better'], 0)}/{fsh(part3[a]['share_equal'], 0)}/{fsh(part3[a]['share_worse'], 0)}, "
                   f"평균 R 차이 {RL.fmt_f(part3[a]['mean_dR'])}, E0 쪽 이유 {part3[a]['twin_reasons']}, 보유 {fh(part3[a]['hold_median_v'])} / "
                   f"{fh(part3[a]['hold_median_twin'])}" for a in mr if a in part3]
            r["md_private_appendix"] += pa + [""]
    return _finish_ds(r)


# ====================================================================================================== X-047 한 줄 성적표
def scorecard(ctx, pool: str, arm: str) -> dict:
    """X-047's row of one arm (money row): quarter values with live beside."""
    if not XC.money_allowed(ctx, pool, arm):
        raise XC.Refused(f"X-047 is money: not on {arm} in {pool}")
    N = _N(ctx, pool)
    out = {"arm": arm}
    for size, tag in ((Q, "quarter"), (LIVE, "live")):
        accs = RL.pool_accounts(ctx, pool, arm, size)
        ent = sum(MT.count(a, "entered") for a in accs)
        closed = sum(MT.count(a, "closed") for a in accs)
        wins = sum(MT.count(a, "wins") for a in accs)
        roe_w, roe_l, x_w, x_l, lo, hi = [], [], [], [], [], []
        for p, a in zip(ctx.pool_picks(pool), accs):
            fr = RL.c4_trade_frame(ctx, p, a)
            cl = fr["reason"] != KX.R_OPEN
            w = (fr["pnl"] > 0) & cl
            ls = (~(fr["pnl"] > 0)) & cl
            roe_w.append(fr["ROE"][w])
            roe_l.append(fr["ROE"][ls])
            x_w.append(fr["x_ret"][w])
            x_l.append(fr["x_ret"][ls])
            a_, b_ = RL.open_dd_range(fr, RL.excursions(ctx, p, fr), float(a["w0"]))
            lo.append(a_)
            hi.append(b_)
        cat = lambda L: np.concatenate(L) if L else np.zeros(0)  # noqa: E731
        rw, rl, xw, xl = cat(roe_w), cat(roe_l), cat(x_w), cat(x_l)
        payoff = float(xw.mean() / abs(xl.mean())) if len(xw) and len(xl) and xl.mean() != 0 else None
        md = month_dist(ctx, pool, arm, size)
        s = {"entered": ent, "entered_per_month": XC.per_account_month(ent, N), "closed": closed, "wins": wins, "losses": closed - wins,
             "win_share": wins / closed if closed else None, "flag": XC.c7_mark(closed)}
        m = {"roe_win": float(rw.mean()) if len(rw) else None, "roe_loss": float(rl.mean()) if len(rl) else None,
             "flag_roe_win": XC.c7_mark(len(rw), None, 20), "flag_roe_loss": XC.c7_mark(len(rl), None, 20), "payoff": payoff,
             "breakeven": (1.0 / (1.0 + payoff)) if payoff is not None else None, "month_p50": md["p50"],
             "share_ge2": md["shares"]["ge2"]["k"] / md["shares"]["ge2"]["n"] if md["shares"]["ge2"]["n"] else None,
             "max_dd_median": float(np.median([float(a["max_dd"]) for a in accs])) if accs else None,
             "open_dd_low": float(np.median(lo)) if lo else None, "open_dd_high": float(np.median(hi)) if hi else None,
             "busts": _busts(accs), "n_accounts": len(accs), "own_growth_log": XC.own_growth_log(accs) if accs else None}
        if arm != "E0":
            m["M"] = XC.pooled_M(ctx, pool, arm, size)
        out[tag] = {"count": s, "money": m}
    return out


def _x047_cells(s: dict, m: dict, ml: dict, ds_count: bool = False) -> list:
    ws = f"승 {fkn(s['wins'], s['closed'])}" if ds_count else fsh(s["win_share"])
    return [f"{RL.fmt_f(s['entered_per_month'])}번", f"{s['wins']}/{s['losses']}", ws + RL.mark(s["closed"])]


def _x047_money_cells(m: dict, ml: dict) -> list:
    own = fg(m["own_growth_log"]) + (f" (E0 대비 {fg(m['M'])})" if "M" in m else "")
    if m["own_growth_log"] is not None and XC.pct_month(m["own_growth_log"]) <= 0 and "M" in m:
        own += f" {W['W12']}"
    flag = lambda f: f" ({f})" if f not in ("", XC.EMPTY) else ""  # noqa: E731
    return [RL.fmt_roe(m["roe_win"]) + flag(m["flag_roe_win"]), RL.fmt_roe(m["roe_loss"]) + flag(m["flag_roe_loss"]),
            RL.fmt_f(m["payoff"]), fsh(m["breakeven"]), fx(m["month_p50"]), fsh(m["share_ge2"]),
            f"{fsh(m['max_dd_median'], 0)} / {fsh(m['open_dd_low'], 0)}~{fsh(m['open_dd_high'], 0)}",
            f"{XC.bust_cell(m['busts'], m['n_accounts'])} · 1/1 {XC.bust_cell(ml['busts'], ml['n_accounts'])}",
            own + f" · 1/1 크기 {fg(ml['own_growth_log'])} ({XC.bust_cell(ml['busts'], ml['n_accounts'])})"]


X047_HEAD = ["방식", "한 달 진입", "승/패", "승률", "이길 때 평균 ROE", "질 때 평균 ROE", "손익비", "본전 승률", "보통 달 x", "x2 이상 달",
             "최대 하락(닫힌 거래 / 들고 있는 동안 포함 범위)", "파산(1/4 크기, 1/1 크기)", "한 달 성장"]


def read_X_047(ctx) -> dict:
    """X-047 한 줄 성적표 (see E.3). X-019's open-position range is computed here from the C4 excursions (X-019 itself is dropped at O8)."""
    r = RL.new_result("X-047", "A")
    for pool in XC.POOLS:
        N = _N(ctx, pool)
        pub, mon = _route(r, pool)
        ds = pool == "ds"
        rows = [scorecard(ctx, pool, a) for a in RL.money_rows(ctx, pool)]
        pub["by_arm"] = [{"arm": x["arm"], "size": tag, **x[tag]["count"]} for x in rows for tag in ("quarter", "live")]
        mon["money_by_arm"] = [{"arm": x["arm"], "size": tag, **x[tag]["money"]} for x in rows for tag in ("quarter", "live")]
        if not ds:
            body = [RL.pool_head(pool, N), "", f"꼬리표: {TAG_FIT}. 읽는 법: 한 줄에 그 방식의 승률·승패·손익·하락·진입 횟수·성장·파산을 모았습니다. "
                    "ROE는 거래 하나의 손익을 그 거래의 증거금으로 나눈 값(%)이고, 손익비는 이길 때 평균 / 질 때 평균(지갑 대비)입니다.", ""]
            tab = [[_row_label(ctx, pool, x["arm"])] + _x047_cells(x["quarter"]["count"], x["quarter"]["money"], x["live"]["money"])
                   + _x047_money_cells(x["quarter"]["money"], x["live"]["money"]) for x in rows]
            body += RL.md_table(X047_HEAD, tab)
            body += [_thin_line(len(rows), sum(1 for x in rows if x["quarter"]["count"]["closed"] < XC.THIN_MIN)), W["W14"], W["W9"],
                     "'들고 있는 동안 포함 범위'는 거래 중 가장 나빴던 가격까지 계산한 하락의 아래·위 끝입니다(한 거래 안에서 최고와 최저의 순서를 몰라 범위로 적음, 펀딩 제외).",
                     ""]
            r["md"] += body
        else:
            body = [RL.pool_head(pool, N), "", "읽는 법: 이 풀은 한 달 진입·승패·승률만 적습니다.", ""]
            body += RL.md_table(["방식", "한 달 진입", "승/패", "승"], [[_row_label(ctx, pool, x["arm"])] + _x047_cells(x["quarter"]["count"], None, None, True)
                                                              for x in rows])
            body += [_thin_line(len(rows), sum(1 for x in rows if x["quarter"]["count"]["closed"] < XC.THIN_MIN)), W["W14"], ""]
            r["md"] += body
            pv = [_psec("X-047", "핵심"), "", "| 딥시크 방식 | " + " | ".join(X047_HEAD[4:]) + " |", "|" + "---|" * (len(X047_HEAD) - 3)]
            pv += [f"| {_plab(x['arm'])} | " + " | ".join(_x047_money_cells(x["quarter"]["money"], x["live"]["money"])) + " |" for x in rows]
            r["md_private"] += pv + [""]
        e0 = rows[0]
        q, l = e0["quarter"]["money"], e0["live"]["money"]
        line = (f"지금 청산(E0)은 한 달에 {fg(q['own_growth_log'])}({TAG_FIT}), 1/1 크기로는 {fg(l['own_growth_log'])}"
                f"({XC.bust_cell(l['busts'], l['n_accounts'])})입니다. 각 방식의 자체 성장은 대략 E0의 성장에 'E0 대비' 칸을 더한 값입니다.")
        r["headline"][pool]["e0_growth"] = {"public": None if ds else line, "private": ("딥시크 " + line) if ds else None}
    return _finish_ds(r)


# ====================================================================================================== X-037 기간을 나눠도 나은가
def _robust(D: np.ndarray) -> dict:
    """X-037 (a)-(c) on a pooled monthly series D (36 values)."""
    M = float(D.mean())
    first, second = float(D[:24].mean()), float(D[24:].mean())
    odd, even = float(D[0::2].mean()), float(D[1::2].mean())
    if abs((24 * first + 12 * second) / 36 - M) > 1e-12 or abs((odd + even) / 2 - M) > 1e-12:
        raise AssertionError("X-037: the halves do not average to M")
    yrs = [float(D[12 * y:12 * y + 12].mean()) for y in range(3)]
    k = sum(1 for v in yrs if v > 0)
    loo = [(36 * M - 12 * yrs[y]) / 24 for y in range(3)]
    win = [float(D[i:i + 12].mean()) for i in range(25)]
    ms = int(np.argmax(D))
    s = float(D.sum())
    top3 = float(np.sort(D)[-3:].sum())
    quarters = D.reshape(12, 3).sum(axis=1)
    halves = D.reshape(6, 6).sum(axis=1)
    return {"M": M, "first": first, "second": second, "odd": odd, "even": even,
            "label_halves": "같은 방향" if first > 0 and second > 0 else "엇갈림", "label_odd_even": "같은 방향" if odd > 0 and even > 0 else "엇갈림",
            "years": yrs, "k_years": k, "label_years": {3: "세 해 모두 +", 2: "두 해만 +", 1: "한 해만 +", 0: "0해"}[k],
            "loo_min": float(min(loo)), "loo_year": 2021 + int(np.argmin(loo)), "win_worst": float(min(win)), "win_pos": int(sum(v > 0 for v in win)),
            "m_star": ms, "m_star_share": (None if XC.c17_shares([float(D[ms]) / NM], M) is None else float(D[ms] / s)),
            "without_m_star": (36 * M - float(D[ms])) / 35, "better": int((D > 1e-9).sum()), "equal": int((np.abs(D) <= 1e-9).sum()),
            "worse": int((D < -1e-9).sum()), "signs": "".join("+" if v > 1e-9 else "-" if v < -1e-9 else "=" for v in D),
            "top3_removed": (s - top3) / 33, "label_top3": "상위 3개월 의존" if (s - top3) / 33 <= 0 and M > 0 else "",
            "quarters_pos": int((quarters > 0).sum()), "halves_pos": int((halves > 0).sum()), "windows": win}


def read_X_037(ctx) -> dict:
    """X-037 기간을 나눠도 나은가 (운 눈금 포함) (see E.3)."""
    r = RL.new_result("X-037", "A")
    for pool in XC.POOLS:
        picks = ctx.pool_picks(pool)
        N = len(picks)
        _pub, mon = _route(r, pool)
        ds = pool == "ds"
        g0 = [np.asarray(XC.account(ctx, p, "E0", Q)["g"], float) for p in picks]
        n0 = np.zeros(NM, int)
        for p in picks:
            a = XC.account(ctx, p, "E0", Q)
            n0 += np.bincount(np.asarray(a["month"], np.int64)[_closed(a)], minlength=NM)[:NM]
        ch = [a for a in RL.money_rows(ctx, pool) if a != "E0"]
        rows = []
        e0_own = np.mean(g0, axis=0) if N else np.zeros(NM)
        e0_row = {"arm": "E0", "own_year": [float(e0_own[12 * y:12 * y + 12].mean()) for y in range(3)], "own": float(e0_own.mean())}
        for v in ch:
            gv = [np.asarray(XC.account(ctx, p, v, Q)["g"], float) for p in picks]
            D = np.mean([a - b for a, b in zip(gv, g0)], axis=0)
            if abs(float(D.mean()) - XC.pooled_M(ctx, pool, v)) > 1e-12:
                raise AssertionError("X-037: the pooled series does not average to M_P")
            nv = np.zeros(NM, int)
            for p in picks:
                a = XC.account(ctx, p, v, Q)
                nv += np.bincount(np.asarray(a["month"], np.int64)[_closed(a)], minlength=NM)[:NM]
            rb = _robust(D)
            lo, hi = MT.block_bootstrap_ci(D, seed=XC.seed_c11("X-037", pool, v), n_boot=2000, block=3, level=95.0)
            cells = {"first": slice(0, 24), "second": slice(24, 36), "y2021": slice(0, 12), "y2022": slice(12, 24), "y2023": slice(24, 36)}
            thin = {k: bool(min(nv[s].sum(), n0[s].sum()) < XC.THIN_MIN) for k, s in cells.items()}
            thin["odd"] = bool(min(nv[0::2].sum(), n0[0::2].sum()) < XC.THIN_MIN)
            thin["even"] = bool(min(nv[1::2].sum(), n0[1::2].sum()) < XC.THIN_MIN)
            thin["m_star"] = bool(min(nv[rb["m_star"]], n0[rb["m_star"]]) < XC.THIN_MIN)
            thin["months"] = int(sum(1 for m in range(NM) if min(nv[m], n0[m]) < XC.THIN_MIN))
            own = np.mean(gv, axis=0)
            rows.append({"arm": v, **rb, "ci_lo": lo, "ci_hi": hi, "label_ci": "0을 걸침" if lo <= 0 <= hi else "0을 안 걸침(88개 중 고른 것이라 증거 아님)",
                         "thin": thin, "own_year": [float(own[12 * y:12 * y + 12].mean()) for y in range(3)], "own": float(own.mean()),
                         "own_total": XC.own_growth_log(RL.pool_accounts(ctx, pool, v)),
                         "D": D.tolist()})
        # (e) / (f) chance yardstick over the choosable variants with a placebo
        C = [v for v in ch if KX.has_placebo(KX.variant_by_id(v))]
        yard = {"n_C": len(C), "n_h": None, "n_y": None, "seeds": 0, "n_h_median": None, "n_h_p95": None, "n_y_median": None, "n_y_p95": None}
        own_seed = {}
        if C:
            Ds = {}
            for v in C:
                blocks = [XC.placebo(ctx, p, v)["g"] for p in picks]
                ns = min(b.shape[0] for b in blocks)
                Ds[v] = np.mean([b[:ns] - g0[i][None, :] for i, b in enumerate(blocks)], axis=0)       # (seeds, 36)
            S = min(d.shape[0] for d in Ds.values())
            byv = {x["arm"]: x for x in rows}
            yard["n_h"] = sum(1 for v in C if byv[v]["first"] > 0 and byv[v]["second"] > 0)
            yard["n_y"] = sum(1 for v in C if all(y > 0 for y in byv[v]["years"]))
            hs = np.zeros(S, int)
            ys = np.zeros(S, int)
            for v in C:
                d = Ds[v][:S]
                h_ok = (d[:, :24].mean(axis=1) > 0) & (d[:, 24:].mean(axis=1) > 0)
                y_ok = np.all(d.reshape(S, 3, 12).mean(axis=2) > 0, axis=1)
                hs += h_ok
                ys += y_ok
                dd = Ds[v]
                own_seed[v] = {"seeds": int(dd.shape[0]),
                               "share_halves": float(((dd[:, :24].mean(axis=1) > 0) & (dd[:, 24:].mean(axis=1) > 0)).mean()),
                               "share_years": float(np.all(dd.reshape(dd.shape[0], 3, 12).mean(axis=2) > 0, axis=1).mean())}
            yard.update(seeds=int(S), n_h_median=float(np.median(hs)), n_h_p95=float(np.percentile(hs, 95)), n_y_median=float(np.median(ys)),
                        n_y_p95=float(np.percentile(ys, 95)))
        for x in rows:
            x["placebo_own"] = own_seed.get(x["arm"])
        mon["e0"] = e0_row
        mon["by_arm"] = rows
        mon["yardstick"] = yard
        # ---------------------------------------------------------------- Korean lines
        if yard["n_C"]:
            ysent = (f"나오는 때만 무작위로 바꾼 가짜 청산에서도 앞뒤 반 모두 + 가 보통 {RL.fmt_f(yard['n_h_median'], 0)}개(상위 5% "
                     f"{RL.fmt_f(yard['n_h_p95'], 0)}개), 세 해 모두 + 가 보통 {RL.fmt_f(yard['n_y_median'], 0)}개였고, 실제 선택 가능 방식은 "
                     f"{yard['n_h']}개·{yard['n_y']}개입니다(가짜 청산이 있는 선택 가능 방식 {yard['n_C']}개, 가짜 청산 {yard['seeds']}번).")
        else:
            ysent = "가짜 청산이 있는 선택 가능 방식이 없어 운 눈금은 없습니다."
        n_out = sum(1 for x in rows if not (x["ci_lo"] <= 0 <= x["ci_hi"]))
        tab = []
        for x in rows:
            fl = lambda *ks: f" ({XC.THIN_KO})" if any(x["thin"].get(k) for k in ks) else ""  # noqa: E731
            sh = (f"전체 차이의 {fsh(x['m_star_share'], 0)}" if x["m_star_share"] is not None
                  else f"{fc(x['D'][x['m_star']] / NM)}%/월 기여(근사), {W['W15']}")
            plc = x["placebo_own"]
            tab.append([x["arm"], f"{x['label_halves']}{fl('first', 'second')}", f"{x['label_odd_even']}{fl('odd', 'even')}",
                        f"{x['label_years']}{fl('y2021', 'y2022', 'y2023')}",
                        f"{_month_label(ctx, x['m_star'])} ({sh}), 빼면 {fg(x['without_m_star'])}{fl('m_star')}",
                        f"{fg(x['ci_lo'])}~{fg(x['ci_hi'])} → {x['label_ci']}",
                        (f"앞뒤 반 {fsh(plc['share_halves'], 0)} · 세 해 {fsh(plc['share_years'], 0)}" if plc else "해당 없음(가짜 청산 없음)"),
                        f"E0 {' / '.join(fg(v) for v in e0_row['own_year'])} · 이 방식 {' / '.join(fg(v) for v in x['own_year'])} "
                        f"(3년 자체 {fg(x['own_total'])})" + (f" {W['W12']}" if XC.pct_month(x["own_total"]) <= 0 else "")])
        head = ["방식", "앞(21~22년) · 뒤(23년)", "홀짝 달", "2021·2022·2023", "가장 잘한 달", "운 폭", "이 방식의 가짜 청산이 같은 표시를 받은 비율",
                "해마다 자체 성장"]
        if not ds:
            body = [RL.pool_head(pool, N), "", ysent, "", "읽는 법: E0 대비 차이를 기간으로 나눠 봅니다. '같은 방향'은 두 기간 모두 E0보다 나았다는 뜻입니다.", ""]
            body += RL.md_table(head, tab) if tab else ["선택 가능 방식이 없어 이 표는 비어 있습니다.", ""]
            body += [_thin_line(len(rows), sum(1 for x in rows if any(v for k, v in x["thin"].items() if k != "months")), n_out),
                     W["W8"].format(n=RL.fmt_f(yard["n_h_median"], 0) if yard["n_C"] else XC.EMPTY), ""]
            r["md"] += body
            app = [RL.pool_head(pool, N), "", "36달 부호(+ 나음, = 같음, - 못함; 2021-01부터)와 12달 창 25개:", ""]
            for x in rows:
                app += [f"- {x['arm']}: `{x['signs']}` (나음 {x['better']} · 같음 {x['equal']} · 못함 {x['worse']}, 건수 적은 달 {x['thin']['months']}개); "
                        f"한 해 빼고 가장 낮음 {fg(x['loo_min'])}({x['loo_year']}년 뺌); 12달 창 중 + {fkn(x['win_pos'], 25)}, 가장 나쁜 창 {fg(x['win_worst'])} "
                        f"(창은 서로 겹침); 분기 + {fkn(x['quarters_pos'], 12)}, 반년 + {fkn(x['halves_pos'], 6)}; 상위 3달 빼면 {fg(x['top3_removed'])}"
                        + (f" ({x['label_top3']})" if x["label_top3"] else "")
                        + "; 12달 창(2021-01~2021-12부터 한 달씩): " + " ".join(fg(v) for v in x["windows"])]
            app.append("")
            r["md_appendix"] += app
            r["headline"][pool]["yardstick"] = {"public": ysent, "private": None}
        else:
            r["md"] += [RL.pool_head(pool, N), "", "이 표는 모두 돈 숫자라 이 문서에 적지 않습니다(비공개 보고서).", ""]
            pv = [_psec("X-037", "핵심"), "", "딥시크 " + ysent, "", "| 딥시크 방식 | " + " | ".join(head[1:]) + " |", "|" + "---|" * len(head)]
            pv += ["| " + " | ".join([_plab(t[0])] + t[1:]) + " |" for t in tab]
            pv += ["", "딥시크: 같은 기간에 여러 방식을 돌려 좋은 것을 고르면 실력이 없어도 좋은 표시가 나옵니다.", ""]
            r["md_private"] += pv
            pa = [_psec("X-037", "부록"), ""]
            pa += [f"- {_plab(x['arm'])}: 부호 {x['signs']}; 상위 3달 빼면 {fg(x['top3_removed'])}; 12달 창 + {fkn(x['win_pos'], 25)}" for x in rows]
            r["md_private_appendix"] += pa + [""]
            r["headline"][pool]["yardstick"] = {"public": None, "private": "딥시크 " + ysent}
    return _finish_ds(r)


# ====================================================================================================== X-046 한 장 요약
def _quote(results: dict | None, read_id: str, pool: str, private: bool = False) -> str | None:
    res = (results or {}).get(read_id)
    if not res or res.get("status", "ok") != "ok":
        return None
    q = ((res.get("headline") or {}).get(pool) or {}).get(RL.HEADLINE_KEYS[read_id])
    return (q or {}).get("private" if private else "public")


def _missing(read_id: str) -> str:
    return f"{XC.EMPTY} ({read_id} 결과 없음)"


def read_X_046(ctx, results: dict | None = None) -> dict:
    """X-046 한 장 요약: filled only from the other reads' headline sentences (``results``: {read id: result}) and select.json; no new
    computation and no ranking. Without ``results`` every quoted cell prints '-' with the read id."""
    r = RL.new_result("X-046", "A")
    for pool in XC.POOLS:
        N = _N(ctx, pool)
        pub, mon = _route(r, pool)
        ds = pool == "ds"
        K = len(ctx.choosable.get(pool, set()))
        dflt = list(ctx.default_ids.get(pool, []))
        pub["n_choosable"] = K
        pub["labels"] = {"default_would_take": dflt}
        q = lambda rid, private=False: _quote(results, rid, pool, private)  # noqa: E731
        if not ds:
            nums = [("1", q("X-047") or _missing("X-047")), ("2", q("X-016") or _missing("X-016")), ("3", q("X-025") or _missing("X-025")),
                    ("4", f"88개 중 고를 수 있는 방식은 {K}개입니다. 기본값(8.4)이 고를 방식: {', '.join(dflt) if dflt else '없음'}."),
                    ("5", " ".join(x for x in (q("X-043") or _missing("X-043"), q("X-021") or _missing("X-021"))))]
            warn = [W["W22"] + (" " + q("X-037") if q("X-037") else ""), W["W23"], W["W9"],
                    W["W24"] + " " + " ".join(x for x in (q("X-034") or _missing("X-034"), q("X-041") or _missing("X-041"))), W["W11"]]
            body = [RL.pool_head(pool, N), "", "**먼저 볼 숫자 5개**", ""]
            body += [f"{k}. {v}" for k, v in nums] + ["", "**주의**", ""] + [f"- **{w}**" for w in warn] + [""]
        else:
            nums = [("3", q("X-025") or _missing("X-025")),
                    ("4", f"88개 중 고를 수 있는 방식은 {K}개입니다. 기본값(8.4)이 고를 방식: {', '.join(dflt) if dflt else '없음'}.")]
            body = [RL.pool_head(pool, N), "", RL.W_KO["W18"], "", "**먼저 볼 숫자**", ""]
            body += [f"{k}. {v}" for k, v in nums] + ["", "**주의**", ""]
            body += [f"- **{RL.W_DS[k]}**" for k in ("W22", "W23", "W9", "W24", "W11")] + [""]
            pv = [_psec("X-046", "핵심"), ""]
            for rid in ("X-047", "X-016", "X-025", "X-043", "X-021", "X-034", "X-041", "X-037"):
                s = q(rid, private=True)
                pv.append(f"- {rid}: {s if s else '딥시크 ' + _missing(rid)}")
            r["md_private"] += pv + [""]
        mon["quoted"] = {rid: bool(q(rid, ds)) for rid in ("X-047", "X-016", "X-025", "X-043", "X-021", "X-034", "X-041", "X-037")}
        r["md"] += body
    return _finish_ds(r)


READS = {"X-046": read_X_046, "X-024": read_X_024, "X-025": read_X_025, "X-027": read_X_027, "X-047": read_X_047, "X-014": read_X_014,
         "X-001": read_X_001, "X-037": read_X_037}
assert set(READS) == set(RL.BODY_ORDER)                   # the page order is reads_lib.BODY_ORDER (E.3)
