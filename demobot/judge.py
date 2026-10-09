"""Pass judgment of every account line: the owners' pre-set rule ("우리 기준", the study's pass rule carried into
the live demo) and the friend's rule ("친구 기준"). Real money stays the owners' decision either way.

우리 기준 (all required):
  1. at least 100 closed trades in the live period
  2. mean net R > 0 and the week-block bootstrap 95% lower bound > 0
  3. wallet above the start and max drawdown under 30%, never ruined
  4. better P&L than the default-values account of the same strategy, timeframe and leverage (coin flips for the
     default accounts themselves)
  5. beats luck: mean R above the 95th percentile of the coin-flip mean for the same number of trades
친구 기준: the last 7 days made money, without a liquidation or a ruin in those 7 days (one week of demo).
"""
from __future__ import annotations

import math

import numpy as np

from . import accounts as A

DAY_MS = 86400 * 1000
RULES_OURS = ["실시간 거래 100건 이상", "평균 R(수수료 후) > 0, 주 단위 부트스트랩 95% 하한도 > 0",
              "잔고가 시작보다 많고 최대 낙폭 30% 미만, 파산 없음", "같은 매매법·봉·레버리지의 기본값 계좌보다 수익 높음",
              "운 기준선 통과: 같은 거래 수의 동전 던지기 95% 상한보다 평균 R 높음"]
RULES_FRIEND = ["최근 7일(데모 일주일) 수익 +", "그 7일 동안 강제청산·파산 없음",
                "참고: 일주일 거래 수십 건으로는 운과 실력을 가리기 어렵습니다"]


def _flip_pool(res: dict, tf: str, L: int) -> tuple:
    tr = [t for t in res[f"cf-{tf}"]["lines"][L]["trades"] if t["status"] == "closed"]
    r = np.array([t["R"] for t in tr], float)
    if len(r) < 30:
        return None, None
    return float(r.mean()), float(r.std())


def _ours(res: dict, a, L: int, sim: dict) -> dict:
    """The five checks of "우리 기준" on one simulated line (the plain line or its stop-rule variant)."""
    line = sim["line"]
    closed = [t for t in sim["trades"] if t["status"] == "closed"]
    n = len(closed)
    checks = []
    checks.append(dict(name_ko=RULES_OURS[0], ok=n >= 100, value_ko=f"{n}건"))
    wn, ws = A.week_blocks(closed)
    lowb = A.boot_low(wn, ws) if n >= 10 else None
    mean = line["mean_R"]
    ok2 = mean is not None and mean > 0 and lowb is not None and lowb > 0
    checks.append(dict(name_ko=RULES_OURS[1], ok=ok2,
                       value_ko=("-" if mean is None else f"{mean:+.3f}R, 하한 " + ("-" if lowb is None else f"{lowb:+.3f}R"))))
    ok3 = line["equity"] > A.SEED and line["max_dd"] < 0.30 and not line["ruined"]
    checks.append(dict(name_ko=RULES_OURS[2], ok=ok3,
                       value_ko=f"${line['equity']:,.2f}, 낙폭 {line['max_dd'] * 100:.1f}%, 파산 {line['ruins']}회"))
    if (a.kind == "fixed" and a.sub == "default") or a.kind == "private":
        ref = res[f"cf-{a.tf}"]["lines"][L]["line"]
        ref_ko = "동전 던지기"
    elif a.kind == "flip":
        ref, ref_ko = None, None
    else:
        ref = res[f"fx-def-{a.short}-{a.tf}"]["lines"][L]["line"]
        ref_ko = "기본값 계좌"
    if ref is None:
        checks.append(dict(name_ko=RULES_OURS[3], ok=False, value_ko="해당 없음 (비교 기준 계좌)"))
    else:
        checks.append(dict(name_ko=RULES_OURS[3], ok=line["pnl"] > ref["pnl"],
                           value_ko=f"${line['pnl']:+,.2f} vs {ref_ko} ${ref['pnl']:+,.2f}"))
    mu, sd = _flip_pool(res, a.tf, L)
    lim = None
    if mean is None or mu is None or n < 2:
        checks.append(dict(name_ko=RULES_OURS[4], ok=False, value_ko="거래가 아직 적음"))
    else:
        lim = mu + 1.645 * sd / math.sqrt(n)
        checks.append(dict(name_ko=RULES_OURS[4], ok=mean > lim, value_ko=f"{mean:+.3f}R vs 기준 {lim:+.3f}R"))
    return dict(pass_=all(c["ok"] for c in checks), checks=checks, n=n, mean_R=mean, luck_lim=lim, boot_low=lowb)


def judge_line(res: dict, aid: str, L: int, now_ms: int) -> dict:
    a = A.by_id(aid)
    sim = res[aid]["lines"][L]
    closed = [t for t in sim["trades"] if t["status"] == "closed"]
    ours = _ours(res, a, L, sim)
    stops = None
    ssim = (res[aid].get("lines_stop") or {}).get(L)
    if ssim is not None:
        sl = ssim["line"]
        stops = dict(pnl_pct=sl["pnl_pct"], max_dd=sl["max_dd"], ours_pass=bool(_ours(res, a, L, ssim)["pass_"]))
    # friend rule: last 7 days
    t7 = now_ms - 7 * DAY_MS
    wk = [t for t in closed if t["exit_ms"] and t["exit_ms"] >= t7]
    pnl7 = sum(t["pnl"] for t in wk)
    bad7 = any(t["reason"] == "liq" or t.get("ruin") for t in wk)
    fchecks = [dict(name_ko=RULES_FRIEND[0], ok=pnl7 > 0, value_ko=f"${pnl7:+,.2f} ({len(wk)}건)"),
               dict(name_ko=RULES_FRIEND[1], ok=not bad7, value_ko=("있음" if bad7 else "없음"))]
    friend = dict(pass_=(all(c["ok"] for c in fchecks) if wk else None), checks=fchecks)
    return dict(id=aid, name=a.name, L=L, ours=_pub(ours), friend=_pub(friend), stops=stops, n=ours["n"],
                mean_R=ours["mean_R"], luck_lim=ours["luck_lim"], boot_low=ours["boot_low"])


def _pub(d: dict) -> dict:
    return {"pass": d["pass_"], "checks": d["checks"]}


CONFIRM_MIN_MS = 28 * DAY_MS
CONFIRM_MAX_MS = 56 * DAY_MS
CONFIRM_N = 20
STOP_RULES_KO = ["계좌 -20%: 새 진입 영구 정지", "하루 -5%: 그날 새 진입 정지", "5연패: 24시간 새 진입 쉼"]


def _window(res: dict, aid: str, L: int, start_ms: int) -> dict:
    """Stats of the trades entered at/after start_ms (closed ones), for a confirmation period."""
    trades = res[aid]["lines"][L]["trades"]
    w0 = A.SEED + sum(t["pnl"] for t in trades if t["status"] == "closed" and t["exit_ms"] and t["exit_ms"] <= start_ms)
    win = sorted((t for t in trades if t["entry_ms"] >= start_ms and t["status"] == "closed"),
                 key=lambda t: t["exit_ms"] or 0)
    n = len(win)
    pnl = sum(t["pnl"] for t in win)
    W, peak, dd = w0, w0, 0.0
    for t in win:
        W += t["pnl"]
        peak = max(peak, W)
        if peak > 0:
            dd = max(dd, 1 - W / peak)
    return dict(n=n, mean_R=(sum(t["R"] for t in win) / n if n else None), pnl=pnl,
                pnl_pct=pnl / max(w0, 1e-9) * 100, max_dd=dd,
                liqs=sum(1 for t in win if t["reason"] == "liq"), ruins=sum(1 for t in win if t.get("ruin")),
                open=sum(1 for t in trades if t["entry_ms"] >= start_ms and t["status"] == "open"))


def _confirm_verdict(w: dict) -> tuple:
    why = []
    if w["n"] < CONFIRM_N:
        why.append(f"거래 {w['n']}건 (20건 필요)")
    if w["mean_R"] is None or w["mean_R"] <= 0:
        why.append("평균 R이 0 이하")
    if w["pnl"] <= 0:
        why.append("확인 기간 수익이 0 이하")
    if w["max_dd"] >= 0.30:
        why.append(f"낙폭 {w['max_dd'] * 100:.1f}% (30% 미만 필요)")
    if w["liqs"]:
        why.append(f"강제청산 {w['liqs']}번")
    if w["ruins"]:
        why.append(f"파산 {w['ruins']}번")
    ok = not why
    return ("confirmed" if ok else "failed"), ("확인 기간 통과: 실전 후보" if ok else "; ".join(why))


def update_confirms(conn, res: dict, rows: list, now_ms: int) -> dict:
    """Start, follow and decide the confirmation periods (CONTRACT 8.1). Returns {"items": [...], "started": [...],
    "decided": [...]}; ``started`` / ``decided`` are this tick's new ones (for Telegram)."""
    from . import store as ST
    latest = {}
    for p in ST.load_passes(conn):
        latest[(p["acct"], p["L"])] = p
    started, decided = [], []
    for r in rows:
        k = (r["id"], r["L"])
        p = latest.get(k)
        if r["ours"]["pass"] and (p is None or p["status"] == "failed"):
            p = dict(acct=r["id"], L=r["L"], start_ms=now_ms, status="confirming", decided_ms=None, result={})
            ST.put_pass(conn, p["acct"], p["L"], now_ms, "confirming", None, {})
            latest[k] = p
            started.append(p)
    items = []
    for (aid, L), p in latest.items():
        if aid not in res:
            continue
        a = A.by_id(aid)
        start = p["start_ms"]
        if p["status"] == "confirming":
            w = _window(res, aid, L, start)
            due = (now_ms >= start + CONFIRM_MIN_MS and w["n"] >= CONFIRM_N) or now_ms >= start + CONFIRM_MAX_MS
            if due:
                status, why = _confirm_verdict(w)
                p.update(status=status, decided_ms=now_ms, result=dict(w, why_ko=why))
                ST.put_pass(conn, aid, L, start, status, now_ms, p["result"])
                decided.append(p)
            else:
                why = (f"진행 중: {w['n']}/{CONFIRM_N}건, "
                       f"{max(0.0, (start + CONFIRM_MIN_MS - now_ms) / DAY_MS):.1f}일 남음")
        else:
            w = p["result"]
            why = w.get("why_ko", "")
        prog = 1.0 if p["status"] != "confirming" else min((now_ms - start) / CONFIRM_MIN_MS, w["n"] / CONFIRM_N)
        end = p["decided_ms"] or max(start + CONFIRM_MIN_MS, now_ms)
        items.append(dict(id=aid, name=a.name, L=L, status=p["status"], start_ms=start, end_ms=end,
                          min_end_ms=start + CONFIRM_MIN_MS, max_end_ms=start + CONFIRM_MAX_MS,
                          decided_ms=p["decided_ms"], progress=max(0.0, min(1.0, prog)), n=w.get("n", 0),
                          need_n=CONFIRM_N, mean_R=w.get("mean_R"), pnl=w.get("pnl", 0.0),
                          pnl_pct=w.get("pnl_pct", 0.0), max_dd=w.get("max_dd", 0.0), liqs=w.get("liqs", 0),
                          ruins=w.get("ruins", 0), why_ko=why))
    order = {"confirmed": 0, "confirming": 1, "failed": 2}
    items.sort(key=lambda x: (order.get(x["status"], 3), -x["start_ms"]))
    return dict(items=items, started=started, decided=decided)


def judge_all(res: dict, now_ms: int, conn=None) -> dict:
    rows = []
    for a in A.current_accounts():
        if a.id not in res:
            continue
        for L in (20, 30, 40, 50):
            rows.append(judge_line(res, a.id, L, now_ms))
    passed = [r for r in rows if r["ours"]["pass"]]
    conf = update_confirms(conn, res, rows, now_ms) if conn is not None else dict(items=[], started=[], decided=[])
    latest = {(c["id"], c["L"]): c for c in conf["items"]}
    for r in rows:
        c = latest.get((r["id"], r["L"]))
        r["confirm"] = (dict(status=c["status"], start_ms=c["start_ms"], end_ms=c["end_ms"]) if c else None)
    cands = [c for c in conf["items"] if c["status"] == "confirmed"]
    confirming = [c for c in conf["items"] if c["status"] == "confirming"]
    if cands:
        verdict = f"실전 후보 {len(cands)}줄 (확인 기간 통과). 실제 돈은 두 분이 정합니다"
    elif confirming:
        verdict = f"확인 기간 {len(confirming)}줄 진행 중 (우리 기준 통과 {len(passed)}줄). 아직 실전 금지"
    elif passed:
        verdict = f"우리 기준 통과 {len(passed)}줄. 확인 기간을 거쳐야 실전 후보가 됩니다"
    else:
        verdict = "실전 금지: 아직 우리 기준을 통과한 계좌가 없습니다"
    n_lines = len(rows)
    return dict(generated_ms=now_ms, verdict_ko=verdict, rules_ko={"ours": RULES_OURS, "friend": RULES_FRIEND},
                stop_rules_ko=STOP_RULES_KO, lines_judged=n_lines,
                multi_note_ko=(f"{n_lines}줄을 한꺼번에 보면 실력이 없어도 몇 줄은 운으로 통과할 수 있어서, "
                               "통과한 줄은 그 뒤 4주(거래 20건 이상) 확인 기간을 거칩니다"),
                rows=rows, confirm=conf["items"],
                candidates=[dict(id=c["id"], name=c["name"], L=c["L"], decided_ms=c["decided_ms"],
                                 window=dict(n=c["n"], mean_R=c["mean_R"], pnl_pct=c["pnl_pct"], max_dd=c["max_dd"]),
                                 costs=dict(entry_bps=None, roundtrip_pct_of_pnl=None), stops=None)
                            for c in cands],
                passed=[(r["id"], r["L"]) for r in passed],
                confirm_started=[(p["acct"], p["L"], p["start_ms"]) for p in conf["started"]],
                confirm_decided=conf["decided"])
