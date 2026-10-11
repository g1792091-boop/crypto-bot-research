"""The watch league's checkpoint numbers (research/fullgrid/WATCH_PREREG.md section 3, computed as its section 5 says).

    python3 research/fullgrid/diag/watch_check.py SNAPDIR --date 2026-11-11 [--json OUT]

SNAPDIR is the league's snapshot folder (/var/lib/candleague/snap): ``league.json`` gives each account's role, kind and
strategy, ``trades.json`` each account's equity line (every closed trade's wallet after it, from $5,000), from which
each trade's result is taken in the pre-registered unit: P&L / wallet before the trade. Only trades closed before
00:00 UTC of the checkpoint date count (the same numbers whenever on that day the script runs).

* C1 (2026-11-11), per pool (core, ds): stop the pool when its cand pool mean is below both its base pool mean and its
  flip pool mean; reported with the cand, exitonly, base and flip pool means and trade counts.
* C2 (2026-12-11, and 2027-01-11 when C2 did not pass), per pool: pass when the cand pool mean > 0 with a one-sided
  week-block bootstrap p < 0.05 (2,000 resamples of UTC weeks from Monday of the pool's weekly sums, seed
  run._seed("watch", pool, date)), the cand pool mean > the base pool mean and > the flip pool mean, and at least 300
  closed cand trades. Reported with it: cand vs exitonly, the quarter accounts' wallets and drawdowns next to the cand ones.
* Per strategy (from C2 on): each strategy's cand trades pooled the same way with "the same three conditions" (mean > 0
  with p < 0.05, > its base and > its flip, at least 300 closed cand trades; p seed run._seed("watch", strategy, date))
  and Benjamini-Hochberg at 10% over all 16 strategies (a strategy under 300 trades stays in the family with p = 1, as
  research/fullgrid/run.py does). A strategy can be proposed only when it passes this and its pool passes.
* It refuses (exit 1) while the league has not processed past 00:00 UTC of the date.

The computation is candleague/checkpoint.py (the dashboard shows its confirmed result after each date); the pool
means, weeks and bootstrap are candleague/summary.py's (the dashboard's 점검 진행 uses the same functions). A
DeepSeek pool needs its money in the snapshot (CANDLEAGUE_DS_MONEY on, the default since 2026-10-11); without it the
script says so instead of computing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

from candleague import summary as SM  # noqa: E402,F401
from candleague.checkpoint import ROLES, bh, check, drawdown, pool_stats, trades_from_equity  # noqa: E402,F401

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("snap")
    ap.add_argument("--date", required=True, help="the checkpoint date, YYYY-MM-DD (2026-11-11, 2026-12-11, 2027-01-11)")
    ap.add_argument("--json", default=None)
    a = ap.parse_args(argv)
    with open(os.path.join(a.snap, "league.json")) as fh:
        league = json.load(fh)
    with open(os.path.join(a.snap, "trades.json")) as fh:
        book = json.load(fh)
    res = check(league, book, a.date)
    if not res["complete"]:
        print(f"리그가 아직 {a.date} 00:00 UTC까지 처리하지 못했습니다 (처리한 시각 done_ms={res['done_ms']}): 따라잡은 뒤 다시 실행하세요")
        return 1
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(res, fh, indent=1, ensure_ascii=False)
    for pool, p in res["pools"].items():
        if "error" in p:
            print(f"{pool}: {p['error']}")
            continue
        r = p["roles"]
        line = " · ".join(f"{k} {r[k]['n']}번" for k in ROLES)
        print(f"{pool}: {line} · 주 {p['weeks']}개")
        print(f"  C1 멈춤: {p['c1_stop']}  C2 통과: {p['c2']['pass']} (p {p['c2']['p']}, 기본값보다 {p['c2']['beats_base']}, "
              f"동전보다 {p['c2']['beats_flip']}, 300번 {p['c2']['trades_300']})")
    if res.get("strategies_error"):
        print(f"매매법별: {res['strategies_error']}")
    for name, st in sorted(res["strategies"].items()):
        if st["pass"]:
            print(f"매매법 통과: {name} ({st['roles']['cand']['n']}번, p {st['p']:.4f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
