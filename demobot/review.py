"""The weekly review ("주간 회의록", CONTRACT 8.10): made by code from the tick's results, no AI and no cost.

Weeks are KST Monday 00:00 to Sunday 24:00. The current week is rebuilt every tick ("진행 중"); at the first tick of a
new week the week that just ended is finished from the same data and kept in the DB (meta ``reviews``, newest
first, at most 26). The baseline of "closer / further from a pass" is the check count of every line at the week's
first tick (meta ``review_base``).
"""
from __future__ import annotations

import time
from typing import Optional

import numpy as np

from . import accounts as A
from . import regime as RG
from . import store as ST

DAY_MS = 86400 * 1000
WEEK_MS = 7 * DAY_MS
KST = 9 * 3600 * 1000
MONDAY0_KST = 1577631600000          # 2019-12-30 00:00 KST (a Monday)
KEEP = 26
TOP = 5


def week_start(t_ms: int) -> int:
    return MONDAY0_KST + ((int(t_ms) - MONDAY0_KST) // WEEK_MS) * WEEK_MS


def week_ko(start_ms: int) -> str:
    a = time.gmtime((start_ms + KST) / 1000)
    b = time.gmtime((start_ms + WEEK_MS - 1 + KST) / 1000)
    return f"{a.tm_mon}/{a.tm_mday}~{b.tm_mon}/{b.tm_mday}"


def _week_pnl(trades: list, t0: int, t1: int) -> float:
    return sum(t["pnl"] for t in trades if t["status"] == "closed" and t["exit_ms"] and t0 <= t["exit_ms"] < t1)


def _ok_counts(judge: dict) -> dict:
    return {f"{r['id']}|{r['L']}": sum(1 for c in r["ours"]["checks"] if c["ok"]) for r in judge.get("rows", [])}


def build_week(res: dict, judge: dict, costs: dict, reg: dict, views: Optional[dict], base: dict,
               t0: int, now_ms: int, final: bool, backup: Optional[dict] = None) -> dict:
    t1 = t0 + WEEK_MS
    end = min(t1, now_ms)
    names = {a.id: a.name for a in A.current_accounts()}
    kinds = {a.id: a.kind for a in A.current_accounts()}
    lines = []
    n_trades = 0
    for aid, r in res.items():
        for L, sim in r["lines"].items():
            tr = sim["trades"]
            wk = _week_pnl(tr, t0, t1)
            pct = wk / A.SEED * 100                  # of the $1,000 start, as pnl_pct everywhere
            if L == 20:
                n_trades += sum(1 for t in tr if t["status"] == "closed" and t["exit_ms"] and t0 <= t["exit_ms"] < t1)
            ssim = (r.get("lines_stop") or {}).get(L)
            spct = None
            if ssim is not None:
                st = ssim["trades"]
                spct = _week_pnl(st, t0, t1) / A.SEED * 100
            lines.append(dict(id=aid, name=names.get(aid, aid), L=int(L), kind=kinds.get(aid), pnl_pct=pct,
                              stop_pct=spct, n=sum(1 for t in tr if t["status"] == "closed" and t["exit_ms"]
                                                   and t0 <= t["exit_ms"] < t1)))
    active = [x for x in lines if x["n"] > 0]
    l20 = [x for x in active if x["L"] == 20]
    best = sorted(active, key=lambda x: -x["pnl_pct"])[:TOP]
    worst = sorted(active, key=lambda x: x["pnl_pct"])[:TOP]
    by_kind = []
    from .report import KIND_KO
    for k, ko in KIND_KO.items():
        v = [x["pnl_pct"] for x in active if x["kind"] == k]
        if v:
            by_kind.append(dict(kind=k, kind_ko=ko, mean_pnl_pct=float(np.mean(v))))
    pub = lambda x: dict(id=x["id"], name=x["name"], L=x["L"], pnl_pct=x["pnl_pct"])   # noqa: E731
    numbers = dict(trades=n_trades, accounts_up=sum(1 for x in l20 if x["pnl_pct"] > 0),
                   accounts_down=sum(1 for x in l20 if x["pnl_pct"] < 0), best=[pub(x) for x in best],
                   worst=[pub(x) for x in worst], by_kind=by_kind)
    # judgment progress
    now_ok = _ok_counts(judge)
    closer, further = [], []
    for k, ok in now_ok.items():
        b = base.get(k)
        if b is None or b == ok or k.startswith("cf-"):
            continue
        aid, L = k.rsplit("|", 1)
        row = dict(id=aid, name=names.get(aid, aid), L=int(L), ok_from=int(b), ok_to=int(ok))
        (closer if ok > b else further).append(row)
    closer.sort(key=lambda x: (-x["ok_to"], x["ok_from"]))
    further.sort(key=lambda x: (x["ok_to"], -x["ok_from"]))
    conf = judge.get("confirm", [])
    jd = dict(passed=len(judge.get("passed", [])), confirming=sum(1 for c in conf if c["status"] == "confirming"),
              candidates=sum(1 for c in conf if c["status"] == "confirmed"), closer=closer[:TOP], further=further[:TOP])
    # stop rules
    diffs = [dict(id=x["id"], name=x["name"], L=x["L"], diff_pct=x["stop_pct"] - x["pnl_pct"])
             for x in active if x["stop_pct"] is not None]
    saved = sorted([d for d in diffs if d["diff_pct"] > 0.05], key=lambda d: -d["diff_pct"])[:TOP]
    cost = sorted([d for d in diffs if d["diff_pct"] < -0.05], key=lambda d: d["diff_pct"])[:TOP]
    stops = dict(saved=saved, cost=cost, net_pct=(float(np.mean([d["diff_pct"] for d in diffs])) if diffs else 0.0))
    # costs
    from . import costs as CO
    eaten = []
    for r in costs.get("lines", []):
        if r["pnl"] > 0 and r.get("extra_cost", 0) > 0:
            eaten.append(dict(id=r["id"], name=r["name"], L=r["L"], share=r["extra_cost"] / r["pnl"]))
    eaten.sort(key=lambda x: -x["share"])
    med = CO.median_entry_bps(costs)
    costs_w = dict(median_entry_bps=med, assumed_bps=CO.ASSUMED_BPS, eaten=eaten[:TOP])
    # regime shares over the week's bars
    regime = []
    for coin, (ts, tr, vo, _sl, _ap) in reg.items():
        m = (ts >= t0) & (ts < end)
        k = int(m.sum())
        share = {key: (float((tr[m] == code).sum()) / k if k else 0.0) for code, key in RG.TREND_KEY.items()}
        regime.append(dict(coin=coin, trend=RG.TREND_KEY.get(int(tr[-1])), vol=RG.VOL_KEY.get(int(vo[-1])),
                           share=share))
    # views
    vs = (views or {}).get("views", [])
    wv = [v for v in vs if t0 <= (v.get("t_ms") or 0) < t1 and v.get("status") != "cancelled"]
    done = [v for v in wv if v.get("status") == "done"]
    d24 = [v["dir"]["24h"] for v in done if (v.get("dir") or {}).get("24h") is not None]
    views_w = dict(n=len(wv), done=len(done), dir24_rate=(sum(1 for d in d24 if d > 0) / len(d24) if d24 else None))
    week = dict(week_ko=week_ko(t0), start_ms=t0, end_ms=t1, final=final, numbers=numbers, judge=jd, stops=stops,
                costs=costs_w, regime=regime, views=views_w)
    week["summary_ko"] = summary_ko(week)
    week["decide_ko"] = decide_ko(week, judge, backup, t0, t1)
    return week


def summary_ko(w: dict) -> list:
    n, j, s, c = w["numbers"], w["judge"], w["stops"], w["costs"]
    out = [f"{'이번 주' if not w['final'] else '지난주'} 거래 {n['trades']}건 (20배 줄 기준), 번 줄 {n['accounts_up']}개 · "
           f"잃은 줄 {n['accounts_down']}개."]
    if n["best"]:
        b, z = n["best"][0], n["worst"][0]
        out.append(f"가장 잘한 줄은 {b['name']} {b['L']}배 {b['pnl_pct']:+.1f}%, 가장 못한 줄은 {z['name']} {z['L']}배 "
                   f"{z['pnl_pct']:+.1f}%.")
    out.append(f"우리 기준 통과 {j['passed']}줄, 확인 기간 {j['confirming']}줄, 실전 후보 {j['candidates']}줄. "
               f"통과에 가까워진 줄 {len(j['closer'])}개, 멀어진 줄 {len(j['further'])}개.")
    if s["saved"] or s["cost"]:
        word = "덜 잃거나 더 벌었" if s["net_pct"] > 0 else "더 잃거나 덜 벌었"
        out.append(f"정지 규칙을 썼다면 평균 {abs(s['net_pct']):.1f}%p {word}습니다.")
    if c["median_entry_bps"] is not None:
        cmp_ = "작습니다" if c["median_entry_bps"] <= c["assumed_bps"] else "큽니다"
        out.append(f"실제 호가로 잰 진입 비용은 중간값 {c['median_entry_bps']:.1f}bp로, 가정한 "
                   f"{c['assumed_bps']:.0f}bp보다 {cmp_}.")
    tr = [r["trend"] for r in w["regime"] if r["trend"]]
    if tr:
        top = max(set(tr), key=tr.count)
        out.append(f"시장은 지금 대체로 {RG.TREND_KO[top]} ({tr.count(top)}/{len(tr)} 코인).")
    return out


def decide_ko(w: dict, judge: dict, backup: Optional[dict], t0: int, t1: int) -> list:
    out = []
    for c in judge.get("confirm", []):
        if c["status"] == "confirmed" and c.get("decided_ms") and t0 <= c["decided_ms"] < t1:
            out.append(f"실전 후보 {c['name']} {c['L']}배: 실제 돈을 쓸지, 쓴다면 얼마로 할지 정해 주세요")
    cs = w["costs"]
    if cs["median_entry_bps"] is not None and cs["median_entry_bps"] > 2 * cs["assumed_bps"]:
        out.append("실제 비용이 가정의 2배를 넘습니다: 레버리지나 주문 크기를 줄일지 정해 주세요")
    for e in cs["eaten"]:
        if e["share"] >= 0.5:
            out.append(f"{e['name']} {e['L']}배는 실제 비용이 수익의 {e['share'] * 100:.0f}%를 먹습니다: 실전 후보에서 뺄지 봐 주세요")
            break
    if backup is not None and backup.get("error_ko"):
        out.append(f"밤 백업 실패: {backup['error_ko']} (서버 확인 필요)")
    s = w["stops"]
    if s["net_pct"] < -1.0:
        out.append("이번 주는 정지 규칙이 오히려 수익을 깎았습니다: 규칙 숫자(-20%, -5%, 5연패)를 바꿀지 다음 주까지 지켜봐 주세요")
    return out


def load_reviews(conn) -> list:
    return ST.get_meta(conn, "reviews", []) or []


def update(conn, res: dict, judge: dict, costs: dict, reg: dict, views: Optional[dict], now_ms: int,
           backup: Optional[dict] = None) -> tuple:
    """(review.json dict, finished week or None). Keeps the baseline and the finished weeks in meta."""
    t0 = week_start(now_ms)
    base = ST.get_meta(conn, "review_base") or {}
    finished = None
    if base.get("week") != t0:
        if base.get("week") is not None and base["week"] < t0:
            prev = base["week"]
            finished = build_week(res, judge, costs, reg, views, base.get("ok", {}), prev, now_ms, True, backup)
            done = [w for w in load_reviews(conn) if w.get("start_ms") != prev]
            done.insert(0, finished)
            ST.set_meta(conn, "reviews", done[:KEEP])
        base = dict(week=t0, ok=_ok_counts(judge))
        ST.set_meta(conn, "review_base", base)
    cur = build_week(res, judge, costs, reg, views, base.get("ok", {}), t0, now_ms, False, backup)
    weeks = [cur] + load_reviews(conn)
    return dict(generated_ms=now_ms, weeks=weeks[:KEEP + 1]), finished
