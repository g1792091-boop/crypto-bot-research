"""Full grid phase 2, section 7 (PHASE2_PREREG.md): role-split teams by market state.

    python research/fullgrid/teams.py --results DIR --data DIR --work DIR --exchange FILE

Owners 2026-10-10: a candidate that earns in trending markets plus one that earns in ranging markets, each trading only
in its own market state. Home states are chosen on the select period only; the test period checks that the home
advantage persists (against the same switch on coin-flip sides) and that a team beats each member alone, both members
always on, and the flipped team. Output: --work/teams.json and teams_KO.md. Passing teams are only proposed as new
paper accounts in the 후보 리그. DeepSeek rows: verdicts and counts only (D11) unless FULLGRID_DS_MONEY=1.
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

import checks as CK  # noqa: E402
import regimes as RG  # noqa: E402
import run as R  # noqa: E402

STATES = ("추세장", "횡보장", "급변장", "보통")
DIMS = {"장세": STATES, "큰 흐름": ("위", "아래"), "변동성": ("작음", "보통", "큼")}
ACTIVE_DIMS = ("장세", "큰 흐름", "변동성")   # PHASE2_PREREG 7 + PHASE2_AMEND_1 (fixed before any result)
SHOW = {"위": "상승장(일봉 EMA200 위)", "아래": "하락장(아래)", "작음": "조용한 장", "큼": "출렁이는 장"}
MIN_HOME, MIN_PERSIST, MIN_TEAM = 30, 20, 30
N_BOOT = 2000
DS_MONEY = os.environ.get("FULLGRID_DS_MONEY") == "1"


def flip_side(cid: str, close_ms: int) -> int:
    from candleague.league import flip_side as fs
    return fs(f"flip|{cid}", int(close_ms))


def home_states(x: np.ndarray, state: np.ndarray, states: tuple = STATES) -> list | None:
    """States (select period) with >= MIN_HOME trades whose mean is > 0 and > the overall mean; None when that is no
    state or every state with enough trades (no role)."""
    if not len(x):
        return None
    overall = float(x.mean())
    eligible = [s for s in states if int((state == s).sum()) >= MIN_HOME]
    home = [s for s in eligible if x[state == s].mean() > 0 and x[state == s].mean() > overall]
    if not home or set(home) == set(eligible):
        return None
    return home


def week_of(ms: np.ndarray) -> np.ndarray:
    return (np.asarray(ms, np.int64) - R.MONDAY0) // R.WEEK_MS


def diff(x: np.ndarray, inside: np.ndarray) -> float | None:
    if inside.sum() == 0 or (~inside).sum() == 0:
        return None
    return float(x[inside].mean() - x[~inside].mean())


def boot_diff_p(week: np.ndarray, x: np.ndarray, inside: np.ndarray, tag: str, n_boot: int = N_BOOT) -> float | None:
    """One-sided week-block bootstrap p for mean(inside) - mean(outside) > 0."""
    if diff(x, inside) is None:
        return None
    weeks = np.unique(week)
    groups = [np.flatnonzero(week == w) for w in weeks]
    rng = np.random.default_rng(CK.seed_of(tag))
    le = 0
    for _ in range(n_boot):
        pick = rng.integers(0, len(groups), len(groups))
        idx = np.concatenate([groups[k] for k in pick])
        d = diff(x[idx], inside[idx])
        le += d is None or d <= 0
    return (1 + le) / (n_boot + 1)


def weekly_sums(ms: np.ndarray, x: np.ndarray, lo: int, hi: int) -> np.ndarray:
    w0, w1 = week_of(np.array([lo]))[0], week_of(np.array([hi - 1]))[0]
    out = np.zeros(int(w1 - w0 + 1))
    if len(x):
        np.add.at(out, np.clip(week_of(ms) - w0, 0, len(out) - 1).astype(int), x)
    return out


def boot_mean_p(v: np.ndarray, tag: str, n_boot: int = N_BOOT) -> float | None:
    """One-sided bootstrap p for mean(weekly sums) > 0 (weeks resampled)."""
    if not len(v):
        return None
    rng = np.random.default_rng(CK.seed_of(tag))
    m = v[rng.integers(0, len(v), size=(n_boot, len(v)))].mean(axis=1)
    return float((1 + (m <= 0).sum()) / (n_boot + 1))


def member(data_dir: str, out: str, r: dict, states_of: dict) -> dict:
    """A candidate's trades with their market state and the coin-flip P&L of the same entries."""
    kind, name, tf, e = r["kind"], r["name"], r["tf"], r["exit_index"]
    cid = CK.cand_id(r)
    T = R.combo_trades(data_dir, out, kind, name, tf, R._combo(r), e)
    if tf not in states_of:
        states_of[tf] = [RG.coin_states(data_dir, s, tf) for s in R.SYMBOLS]
    labels = RG.tag(T, states_of[tf])
    state = {d: np.array([s if s is not None else "모름" for s in labels[d]], object) for d in DIMS}
    xf = np.full(len(T["x"]), np.nan)
    for ci, sym in enumerate(R.SYMBOLS):
        m = np.flatnonzero(T["coin"] == ci)
        if not len(m):
            continue
        P = R.trade_table(data_dir, out, kind, name, sym, tf)[e]
        _df, close = R.frame(data_dir, sym, tf)
        idx = np.searchsorted(close, T["close"][m])
        side = np.array([flip_side(cid, t) for t in T["close"][m]])
        xf[m] = np.where(side > 0, P[idx, 0], P[idx, 1])
    return {"id": cid, "row": r, "T": T, "state": state, "xf": xf}


def persistence(mb: dict, home: list, tag: str) -> dict:
    T, st = mb["T"], mb["state"]
    m = (T["pid"] == R.P_TEST) & (st != "모름")
    x, inside, wk = T["x"][m], np.isin(st[m], home), week_of(T["close"][m])
    ok = np.isfinite(mb["xf"][m])
    d_flip = diff(mb["xf"][m][ok], inside[ok])
    return {"n_in": int(inside.sum()), "n_out": int((~inside).sum()), "d": diff(x, inside), "d_flip": d_flip,
            "p": boot_diff_p(wk, x, inside, tag)}


def team_test(a: dict, b: dict, tag: str) -> dict:
    lo, hi = R.PERIOD_MS[R.P_TEST][1], R.PERIOD_MS[R.P_TEST][2]

    def part(mb, home, flipped=False, all_on=False):
        T, st = mb["T"], mb["state"]
        m = T["pid"] == R.P_TEST
        if not all_on:
            m &= np.isin(st, home)
        x = mb["xf"][m] if flipped else T["x"][m]
        ms = T["close"][m]
        ok = np.isfinite(x)
        return ms[ok], x[ok]

    ta, xa = part(a, a["home"])
    tb, xb = part(b, b["home"])
    fa, fxa = part(a, a["home"], flipped=True)
    fb, fxb = part(b, b["home"], flipped=True)
    _ta, xa_all = part(a, None, all_on=True)
    _tb, xb_all = part(b, None, all_on=True)
    w = weekly_sums(np.r_[ta, tb], np.r_[xa, xb], lo, hi)
    total = float(w.sum())
    res = {"n": int(len(xa) + len(xb)), "total": total, "weekly_mean": float(w.mean()), "p": boot_mean_p(w, tag),
           "a_total": float(xa_all.sum()), "b_total": float(xb_all.sum()), "pair_total": float(xa_all.sum() + xb_all.sum()),
           "flip_total": float(np.r_[fxa, fxb].sum())}
    res["beats"] = {"a": total > res["a_total"], "b": total > res["b_total"], "pair": total > res["pair_total"],
                    "flip": total > res["flip_total"], "trades": res["n"] >= MIN_TEAM}
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--results", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--exchange", required=True)
    ap.add_argument("--procs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--dims", help="comma separated (default: the pre-registered ones)")
    a = ap.parse_args(argv)
    bad = CK.data_mismatch(a.results, a.data)
    if bad:
        raise SystemExit(f"1m data differs from the run's for {bad}: stop (PHASE2_PREREG 0)")
    R.FRAME_DIR[0] = os.path.join(a.work, "frames")
    if not all(os.path.exists(R.outcome_path(a.work, s, tf)) for s in R.SYMBOLS for tf in R.TFS):
        R.stage_outcomes(a.data, a.work, a.procs, R.exchange(a.exchange, False))
    with open(os.path.join(a.results, "confirm.json")) as fh:
        cands = [r for r in json.load(fh)["rows"] if r.get("pass")]
    dims = tuple(d for d in (a.dims.split(",") if a.dims else ACTIVE_DIMS))
    doc = {"rules": "PHASE2_PREREG.md 7", "dims": list(dims), "members": [], "teams": [], "ds_money": DS_MONEY}
    states_of: dict = {}
    members = [member(a.data, a.work, r, states_of) for r in cands]
    roles = []
    for dim in dims:
        for mb in members:
            T, st = mb["T"], mb["state"][dim]
            s = T["pid"] == R.P_SELECT
            home = home_states(T["x"][s], st[s], DIMS[dim])
            by_state = {k: {"n": int((st[s] == k).sum()),
                            "mean": float(T["x"][s][st[s] == k].mean()) if (st[s] == k).any() else None} for k in DIMS[dim]}
            row = {"id": mb["id"], "dim": dim, "kind": mb["row"]["kind"], "name": mb["row"]["name"], "tf": mb["row"]["tf"],
                   "rank": mb["row"].get("rank"), "exit": mb["row"].get("exit"), "select_by_state": by_state, "home": home}
            if home:
                view = {"id": mb["id"], "T": T, "state": st, "xf": mb["xf"], "home": home}
                row["persist"] = persistence(view, home, f"persist|{dim}|{mb['id']}")
                roles.append((dim, view, row))
            doc["members"].append(row)
            print(f"[teams] {dim} {mb['id']}: home {home}", flush=True)
    sig = R.bh([row["persist"]["p"] if row["persist"]["p"] is not None else 1.0 for _d, _v, row in roles])
    for (_d, _v, row), s in zip(roles, sig):
        p = row["persist"]
        p["holds"] = bool(s and p["d"] is not None and p["d_flip"] is not None and p["d"] - p["d_flip"] > 0
                          and p["n_in"] >= MIN_PERSIST and p["n_out"] >= MIN_PERSIST)
    for dim in dims:
        rd = [v for d, v, _row in roles if d == dim]
        for i in range(len(rd)):
            for j in range(i + 1, len(rd)):
                va, vb = rd[i], rd[j]
                if set(va["home"]) & set(vb["home"]):
                    continue
                t = team_test(va, vb, f"team|{dim}|{va['id']}|{vb['id']}")
                doc["teams"].append({"dim": dim, "a": va["id"], "b": vb["id"], "a_home": va["home"], "b_home": vb["home"],
                                     **t})
    tsig = R.bh([t["p"] if t["p"] is not None else 1.0 for t in doc["teams"]])
    for t, s in zip(doc["teams"], tsig):
        t["fdr"] = bool(s)
        t["pass"] = bool(s and t["weekly_mean"] > 0 and all(t["beats"].values()))
    doc["no_teams"] = {dim: sum(d == dim for d, _v, _r in roles) < 2 for dim in dims}
    with open(os.path.join(a.work, "teams.json"), "w") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(a.work, "teams_KO.md"), "w") as fh:
        fh.write(report_ko(doc))
    print(f"[teams] {len(doc['teams'])} teams, {sum(t['pass'] for t in doc['teams'])} pass -> {a.work}/teams_KO.md")
    return 0


def _p(x, d=2) -> str:
    return "-" if x is None else f"{x * 100:+.{d}f}%"


def report_ko(doc: dict) -> str:
    L = ["# 장세별 역할 분담 팀 (미리 정한 규칙: PHASE2_PREREG.md 7)", "",
         "후보마다 고르기 기간(2021~2023)에서 '잘하는 장'을 정하고, 시험 기간(2024~2026-09)에서 그 강점이 이어지는지,",
         "그리고 잘하는 장에서만 거래하는 두 후보의 팀이 각자 따로, 둘 다 늘 켠 것, 같은 스위치를 단 동전 던지기보다 나은지",
         "봅니다. 장세는 신호 봉까지의 자료로만 정합니다. 통과한 팀은 후보 리그에 새 종이 계좌로 넣자고 제안만 합니다.", ""]
    money = DS_MONEY

    def nm(v):
        return SHOW.get(v, v)
    for dim in doc.get("dims", ["장세"]):
        L += [f"## 기준: {dim}", "", "| 후보 | 잘하는 장 | 강점이 이어짐 |", "|---|---|---|"]
        for m in doc["members"]:
            if m.get("dim", "장세") != dim:
                continue
            p = m.get("persist")
            hold = "-" if p is None else ("예" if p.get("holds") else "아니오")
            L.append(f"| {m['id']} | {', '.join(nm(h) for h in m['home']) if m['home'] else '정해진 장 없음'} | {hold} |")
        L.append("")
        teams = [t for t in doc["teams"] if t.get("dim", "장세") == dim]
        nt = doc.get("no_teams")
        if (nt.get(dim) if isinstance(nt, dict) else nt):
            L += ["잘하는 장이 정해진 후보가 2개 미만이라 팀을 만들 수 없습니다.", ""]
            continue
        if not teams:
            L += ["잘하는 장이 서로 겹치지 않는 짝이 없어 팀을 만들 수 없습니다.", ""]
            continue
        L += ["| A (장) | B (장) | 거래 | 팀 합계 | A만 | B만 | 둘 다 늘 | 동전 팀 | 판정 |",
              "|---|---|---|---|---|---|---|---|---|"]
        for t in teams:
            ds = t["a"].startswith("ds-") or t["b"].startswith("ds-")
            show = money or not ds
            f = (lambda v: _p(v)) if show else (lambda v: "숨김")
            L.append(f"| {t['a']} ({'/'.join(nm(h) for h in t['a_home'])}) | {t['b']} ({'/'.join(nm(h) for h in t['b_home'])}) | "
                     f"{t['n']} | {f(t['total'])} | {f(t['a_total'])} | {f(t['b_total'])} | {f(t['pair_total'])} | "
                     f"{f(t['flip_total'])} | {'통과' if t['pass'] else '못 넘음'} |")
        L.append("")
    L += ["합계 = 시험 기간 매매 손익 ÷ 잔고의 합(모든 신호). 통과 = 우연 보정(BH 10%, 모든 기준의 팀을 한꺼번에)을 넘고",
          "A만, B만, 둘 다 늘, 동전 팀 넷 모두보다 크며 30건 이상."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())
