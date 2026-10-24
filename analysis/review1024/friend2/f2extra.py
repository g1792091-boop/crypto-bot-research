"""After the PLAN (post-hoc reading, not a test; nothing here changes a verdict): does a good last 19 days say anything about the
next 19 days? On the 384 settings of f2study.py:
  1. the ten settings with the largest margin-40 % multiple in the last 19 days (10/04 .. 10/23 KST 09:00) and what they did
     before (2024 .. 2026-09, 2026) and after (10/23 .. 10/24 23:00 KST, the live-bar extension);
  2. follow the leader: every 7 days from 2024-01-01, rank the settings by their margin-40 % multiple over the previous 19 days,
     then read the next 19 days of the top 1 / top 5 / top 20 / all (one pass of each setting from 2023-12 to the data end;
     each 19-day window from 1);
  3. rank correlation between 2026-01-01 .. 10-04 and the last 19 days (per-trade net ROE with payback).

    python3 -I f2extra.py                  -> extra.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from f2common import *
from f2common import _take_nb
import f2study as ST

W = 19 * DAY


def main():
    S = pd.read_csv(os.path.join(F2_DIR, "settings.csv"))
    R = ST.load()
    B = ST.Book(R)
    del R
    out = {}
    cols = ["setting", "last19_n", "last19_win", "last19_roe_pct", "last19_mult40", "last19_twin_pct", "ext_only_n", "ext_only_roe_pct",
            "ext_only_mult40", "oct_mult40", "y2026_roe_pct", "confirm_roe_pct", "select_roe_pct"]
    top = S.sort_values("last19_mult40", ascending=False).head(10)[cols]
    out["top10_last19"] = top.to_dict("records")
    print(top.to_string(index=False), flush=True)
    # 2. follow the leader
    a0 = ms("2023-12-01")
    ends = np.arange(ms("2024-01-01"), ms("2026-10-04") + 1, 7 * DAY)
    M = np.zeros((len(S), len(ends)))          # past 19-day multiple at each pick time
    N = np.zeros((len(S), len(ends)))          # next 19-day multiple
    per26 = np.zeros(len(S)); per19 = np.zeros(len(S))
    for si, row in S.iterrows():
        fam, xi = row["family"], XN.index(row["setting"].split("|")[1])
        _, idx, roe0, roe = ST.trades(B, fam, xi, a0, END2)
        tt = B.t[idx]
        lx = np.log(np.maximum(1 + 0.40 * roe, 1e-12))
        cs = np.r_[0, np.cumsum(lx)]
        lo = np.searchsorted(tt, ends - W); mid = np.searchsorted(tt, ends); hi = np.searchsorted(tt, ends + W)
        M[si] = np.exp(cs[mid] - cs[lo])
        N[si] = np.exp(cs[hi] - cs[mid])
        m26 = (tt >= ms("2026-01-01")) & (tt < ms("2026-10-04"))
        m19 = (tt >= ms("2026-10-04")) & (tt < ms("2026-10-23"))
        per26[si] = roe[m26].mean() if m26.any() else np.nan
        per19[si] = roe[m19].mean() if m19.any() else np.nan
    full = (ends + W) <= ms("2026-10-23")
    res = {}
    for k in (1, 5, 20, len(S)):
        v = []
        for j in np.flatnonzero(full):
            order = np.argsort(-M[:, j], kind="stable")[:k]
            v.append(np.exp(np.mean(np.log(np.maximum(N[order, j], 1e-12)))))      # geometric mean of the k picks
        v = np.array(v)
        res[f"top{k}" if k < len(S) else "all"] = {"windows": int(len(v)), "median_next19": rnd(np.median(v), 4),
                                                   "share_next19_up": rnd((v > 1).mean(), 4), "mean_log": rnd(np.log(v).mean(), 4)}
    out["follow_the_leader"] = res
    print(json.dumps(res, indent=1), flush=True)
    ok = np.isfinite(per26) & np.isfinite(per19)
    rho = pd.Series(per26[ok]).rank().corr(pd.Series(per19[ok]).rank())
    out["spearman_2026_to_1004_vs_last19"] = rnd(rho, 4)
    print("spearman", rho, flush=True)
    json.dump(out, open(os.path.join(F2_DIR, "extra.json"), "w"), ensure_ascii=False, indent=1, default=float)


if __name__ == "__main__":
    main()
