"""Summary of combo_watch.json: pairwise entry overlap, daily correlation and bad-day overlap (all accounts), and an
equal-split basket of the core accounts per size and period (final multiple, max drawdown on daily closes, worst
calendar month). DeepSeek accounts enter the pairs only (D11).

    python research/fullgrid/diag/combo_sum.py combo_watch.json combo_sum.json
"""

import itertools
import json
import os
import statistics as st
import sys

FG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(FG)))
sys.path.insert(0, FG)

import numpy as np  # noqa: E402

import checks as CK  # noqa: E402
import run as R  # noqa: E402

TFMS = {"15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}
DAY = 86_400_000


def pairs_of(res: list) -> list:
    ent = {o["id"]: {k: np.array(v) for k, v in o["entries"].items()} for o in res}
    daily = {o["id"]: {int(k): v for k, v in o["daily"].items()} for o in res}
    tf = {o["id"]: o["tf"] for o in res}
    out = []
    for a, b in itertools.combinations([o["id"] for o in res], 2):
        w = max(TFMS[tf[a]], TFMS[tf[b]])
        oa, ob = CK.overlap_share(ent[a], ent[b], w), CK.overlap_share(ent[b], ent[a], w)
        out.append({"a": a, "b": b, "overlap": None if oa is None or ob is None else 0.5 * (oa + ob),
                    "corr": CK.corr_daily(daily[a], daily[b]), "bad": CK.bad_day_overlap(daily[a], daily[b])})
    return out


def curve(acct: dict, days: np.ndarray) -> np.ndarray:
    ex = np.array(acct["exit_ms"], np.int64) // DAY
    r = np.array(acct["ret"])
    order = np.argsort(ex, kind="stable")
    ex, r = ex[order], r[order]
    eq = np.ones(len(days))
    v, j = 1.0, 0
    for i, d in enumerate(days):
        while j < len(ex) and ex[j] <= d:
            v *= 1 + r[j]
            j += 1
        eq[i] = v
    return eq


def basket(res: list) -> dict:
    core = [o for o in res if o["kind"] == "core"]
    out = {}
    for scale in ("1.0", "0.25"):
        for pname, lo, hi in R.PERIOD_MS:
            days = np.arange(lo // DAY, hi // DAY + 1)
            accts = [o["acct"][f"{scale}|{pname}"] for o in core]
            B = np.mean([curve(a, days) for a in accts], axis=0)
            mdd = float(np.max(1 - B / np.maximum.accumulate(B)))
            months = (days * DAY).astype("datetime64[ms]").astype("datetime64[M]")
            worst = min(B[months == m][-1] / (B[months < m][-1] if (months < m).any() else 1.0) - 1
                        for m in np.unique(months))
            finals = [a["final_x"] for a in accts]
            out[f"{scale}|{pname}"] = dict(basket_final=float(B[-1]), basket_mdd=mdd, worst_month=float(worst),
                                           single_median_final=float(np.median(finals)),
                                           single_median_mdd=float(np.median([a["max_dd"] for a in accts])),
                                           singles_up=int(sum(f > 1 for f in finals)), n=len(core))
            print(f"size x{scale} {pname:6}: basket x{B[-1]:.2f} mdd {mdd:.0%} worst month {worst:+.0%} | "
                  f"single median x{np.median(finals):.2f} up {sum(f > 1 for f in finals)}/{len(core)}")
    return out


def main(src: str, dst: str) -> None:
    res = json.load(open(src))
    pairs = pairs_of(res)
    cs = [p["corr"] for p in pairs if p["corr"] is not None]
    ovs = [p["overlap"] for p in pairs if p["overlap"] is not None]
    same = [p for p in pairs if (p["overlap"] or 0) >= 0.5 or (p["corr"] or 0) >= 0.7]
    print(f"pairs {len(pairs)} | corr median {st.median(cs):+.3f} p90 {np.percentile(cs, 90):+.3f} | "
          f"overlap median {st.median(ovs):.1%} p90 {np.percentile(ovs, 90):.1%} | near-identical {len(same)}")
    json.dump({"pairs": pairs, "basket": basket(res)}, open(dst, "w"))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
