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


def judge_line(res: dict, aid: str, L: int, now_ms: int) -> dict:
    a = A.by_id(aid)
    sim = res[aid]["lines"][L]
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
    if mean is None or mu is None or n < 2:
        checks.append(dict(name_ko=RULES_OURS[4], ok=False, value_ko="거래가 아직 적음"))
    else:
        lim = mu + 1.645 * sd / math.sqrt(n)
        checks.append(dict(name_ko=RULES_OURS[4], ok=mean > lim, value_ko=f"{mean:+.3f}R vs 기준 {lim:+.3f}R"))
    ours = dict(pass_=all(c["ok"] for c in checks), checks=checks)
    # friend rule: last 7 days
    t7 = now_ms - 7 * DAY_MS
    wk = [t for t in closed if t["exit_ms"] and t["exit_ms"] >= t7]
    pnl7 = sum(t["pnl"] for t in wk)
    bad7 = any(t["reason"] == "liq" or t.get("ruin") for t in wk)
    fchecks = [dict(name_ko=RULES_FRIEND[0], ok=pnl7 > 0, value_ko=f"${pnl7:+,.2f} ({len(wk)}건)"),
               dict(name_ko=RULES_FRIEND[1], ok=not bad7, value_ko=("있음" if bad7 else "없음"))]
    friend = dict(pass_=(all(c["ok"] for c in fchecks) if wk else None), checks=fchecks)
    return dict(id=aid, name=a.name, L=L, ours=_pub(ours), friend=_pub(friend))


def _pub(d: dict) -> dict:
    return {"pass": d["pass_"], "checks": d["checks"]}


def judge_all(res: dict, now_ms: int) -> dict:
    rows = []
    for a in A.current_accounts():
        if a.id not in res:
            continue
        for L in (20, 30, 40, 50):
            rows.append(judge_line(res, a.id, L, now_ms))
    passed = [r for r in rows if r["ours"]["pass"]]
    if passed:
        verdict = f"우리 기준 통과 {len(passed)}개 줄. 실제 돈은 두 분이 정합니다"
    else:
        verdict = "실전 금지: 아직 우리 기준을 통과한 계좌가 없습니다"
    return dict(generated_ms=now_ms, verdict_ko=verdict, rules_ko={"ours": RULES_OURS, "friend": RULES_FRIEND},
                rows=rows, passed=[(r["id"], r["L"]) for r in passed])
