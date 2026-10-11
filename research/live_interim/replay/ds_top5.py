"""DS top-5 live cells: 5-year default record, same-day replay sides, how often a week this good happened (labels)."""
import csv
import json
import os
import sys
FG = "/home/user/crypto-bot-research/research/fullgrid"
sys.path.insert(0, os.path.dirname(os.path.dirname(FG)))
sys.path.insert(0, FG)
os.environ.setdefault("OMP_NUM_THREADS", "1")
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import run as R  # noqa
SP = os.environ["WORKROOT"]
D = 86_400_000
CELLS = [("F3_BOS", "1h"), ("F1_PVT_DIV", "30m"), ("F3_BOS", "30m"), ("F9_FVG", "30m"), ("F15_ORB", "15m")]
ms = lambda s: int(pd.Timestamp(s, tz="UTC").value // 1_000_000)  # noqa
D0, END = ms("2026-10-05 18:35"), ms("2026-10-10")
cands = list(csv.DictReader(open(SP + "/fgresults/fullgrid-results-20261010-1602/candidates.csv")))
checks = [c for c in cands[0] if c.startswith("check_") and c != "check_test_fdr"]
out = {}
for name, tf in CELLS:
    res = {}
    # same days (replay data through 10/09)
    R.FRAME_DIR[0] = SP + "/interim/lw/frames"
    T = R.cell_trades(SP + "/interim/ld", SP + "/interim/lw2", "ds", name, tf, [(R.default_combo("ds", name), 0)])[0]
    m = (T["close"] >= D0) & (T["close"] < END) & np.isfinite(T["x"])
    x, s = T["x"][m], T["side"][m]
    thr = float(x.mean()) if len(x) else 0.0
    res["replay"] = {"signals": int(m.sum()), "win": round(float((x > 0).mean()), 2) if len(x) else None,
                     "sign": "+" if thr > 0 else "−", "long_n": int((s > 0).sum()), "long_sign": "+" if x[s > 0].mean() > 0 else "−",
                     "short_n": int((s < 0).sum()), "short_sign": ("+" if x[s < 0].mean() > 0 else "−") if (s < 0).any() else None}
    # 5 years
    R.FRAME_DIR[0] = SP + "/fgwork/frames"
    T5 = R.cell_trades(SP + "/fg1m", SP + "/fgwork", "ds", name, tf, [(R.default_combo("ds", name), 0)])[0]
    ok = np.isfinite(T5["x"]) & ((T5["pid"] == 0) | (T5["pid"] == 1))
    o = np.argsort(T5["close"][ok], kind="stable")
    c, xx, sd = T5["close"][ok][o], T5["x"][ok][o], T5["side"][ok][o]
    yrs = {}
    for y in range(2021, 2027):
        mm = (c >= ms(f"{y}-01-01")) & (c < ms(f"{y + 1}-01-01"))
        yrs[y] = "+" if xx[mm].sum() > 0 else "−"
    q3 = (c >= ms("2026-07-01"))
    res["five"] = {"signals": int(len(xx)), "win": round(float((xx > 0).mean()), 2), "sign": "+" if xx.mean() > 0 else "−",
                   "years": yrs, "positive_years": sum(v == "+" for v in yrs.values()),
                   "last3m_sign": "+" if xx[q3].mean() > 0 else "−", "long_sign": "+" if xx[sd > 0].mean() > 0 else "−",
                   "short_sign": "+" if xx[sd < 0].mean() > 0 else "−"}
    # weeks at least this good (per signal), then the next 30 days
    starts = np.arange(c[0], c[-1] - 36 * D, D)
    cs = np.r_[0, np.cumsum(xx)]
    a, b, b2 = np.searchsorted(c, starts), np.searchsorted(c, starts + 6 * D), np.searchsorted(c, starts + 36 * D)
    good, nxt, last = 0, [], -10 ** 18
    nwin = 0
    for st, i, j, k in zip(starts, a, b, b2):
        if j - i < 3:
            continue
        nwin += 1
        if (cs[j] - cs[i]) / (j - i) >= thr:
            good += 1
            if st >= last + 6 * D and k - j >= 3:
                nxt.append((cs[k] - cs[j]) / (k - j))
                last = st
    yrs_n = (c[-1] - c[0]) / (365.25 * D)
    res["like_this"] = {"share_windows": round(good / max(1, nwin), 3), "episodes_per_year": round(len(nxt) / yrs_n, 1),
                        "next30_positive_share": round(float(np.mean(np.array(nxt) > 0)), 2) if nxt else None,
                        "next30_sign": ("+" if np.mean(nxt) > 0 else "−") if nxt else None}
    rs = [r for r in cands if r["kind"] == "ds" and r["name"] == name and r["tf"] == tf]
    res["fullgrid"] = {"candidates": len(rs), "passing_all_but_chance": sum(all(r[k] == "True" for k in checks) for r in rs)}
    out[f"{name}@{tf}"] = res
    print(name, tf, json.dumps(res, ensure_ascii=False))
json.dump(out, open(SP + "/interim/ds_top5.json", "w"), ensure_ascii=False, indent=1)
