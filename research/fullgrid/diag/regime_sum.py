"""Summary of regime_explore.json: does a home-state advantage chosen on the select period persist in the test period,
and does a team of the best three cells per state (chosen on select) beat running every cell?

    python research/fullgrid/diag/regime_sum.py regime_explore.json
"""

import json
import statistics as st
import sys

DIMS = {"장세": ("추세장", "횡보장", "급변장", "보통"), "큰 흐름": ("위", "아래"), "변동성": ("작음", "보통", "큼")}


def mean(per: dict, states) -> tuple:
    n = sum(per[s][0] for s in states)
    return (sum(per[s][1] for s in states) / n if n else None), n


def persistence(res: list) -> None:
    for grp in ("default|ladder", "default|tp3R4", "pick"):
        rows = [r for r in res if r["tag"].startswith(grp)]
        for d, states in DIMS.items():
            roles = [r for r in rows if r["dims"][d]["home"]]
            better = positive = cnt = 0
            sel_home = []
            for r in roles:
                home = r["dims"][d]["home"]
                rest = [s for s in states if s not in home]
                test = r["dims"][d]["per"]["test"]
                mi, ni = mean(test, home)
                mo, no = mean(test, rest)
                if mi is None or mo is None or ni < 20 or no < 20:
                    continue
                cnt += 1
                better += mi > mo
                positive += mi > 0
                sel_home.append(mean(r["dims"][d]["per"]["select"], home)[0])
            if cnt:
                print(f"{grp:15} {d:5} roles {len(roles):3}/{len(rows)} usable {cnt:3} | select home median "
                      f"{st.median(sel_home) * 100:+.2f}% | test: home > rest {better}/{cnt}, home mean > 0 {positive}/{cnt}")


def teams(res: list) -> None:
    for grp in ("default|ladder", "default|tp3R4"):
        for d, states in DIMS.items():
            tn = ts = an = as_ = 0
            for tf in ("15m", "30m", "1h", "4h"):
                rows = [r for r in res if r["tag"] == grp and r["tf"] == tf]
                for s in states:
                    ok = [r for r in rows if r["dims"][d]["per"]["select"][s][0] >= 30]
                    if not ok:
                        continue
                    sel = lambda r: r["dims"][d]["per"]["select"][s][1] / r["dims"][d]["per"]["select"][s][0]  # noqa: E731
                    top = sorted(ok, key=sel, reverse=True)[:3]
                    tn += sum(r["dims"][d]["per"]["test"][s][0] for r in top)
                    ts += sum(r["dims"][d]["per"]["test"][s][1] for r in top)
                    an += sum(r["dims"][d]["per"]["test"][s][0] for r in ok)
                    as_ += sum(r["dims"][d]["per"]["test"][s][1] for r in ok)
            print(f"{grp:15} {d:5} team (top 3 per state) test mean {ts / tn * 100:+.3f}% (n {tn}) "
                  f"vs every cell {as_ / an * 100:+.3f}% (n {an})")


if __name__ == "__main__":
    data = json.load(open(sys.argv[1]))
    persistence(data)
    teams(data)
