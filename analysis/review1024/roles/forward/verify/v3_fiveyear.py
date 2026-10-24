"""Verifier 3: is a +4.7-point with-minus-against gap in a 19-day window unusual over 5 years?
Every non-trend entry signal (77 strategies, 15m-4h, bar number >= 300), 2020-03 .. 2026-10-23 UTC, w35 (35x, net
-50 % stop, ladder; costs in, payback out), the live judge Jdir on the auto mapping (15m/30m->1h, 1h->4h, 4h->1d),
aggregated per (UTC day, coin, tf, side, alignment).  Then:
  - 5-year pooled gap, within-side gaps, within (side, day) stratified gap, gap per tf (= per mapping)
  - every 19-day window (step 1 day): pooled gap, side-standardised gap, market move (6-coin mean close-to-close)
  - share of windows with gap >= the forward +4.7 points, and among windows that fell >= 10 %
Writes v3_windows.csv.gz and v3_out.json in this folder.  Run without -I: python3 v3_fiveyear.py"""
import sys
import os
sys.path.insert(0, "/home/user/crypto-bot-research/analysis/review1024/roles/data")
from common import *  # noqa
import rolesdata as RD
import json

HERE = os.path.dirname(os.path.abspath(__file__))
ROLES = ("pullback", "range", "breakout", "reversal", "timing", "other")
parts = []
for tf in TFS:
    for ci, coin in enumerate(COINS):
        S = RD.signals(tfs=[tf], period="five", coins=[coin], roles_=ROLES)
        if not len(S):
            continue
        S = RD.add_outcomes(S, ["w35"], opp=False)
        S = RD.add_judge(S, check=False)
        S = S[S.w35_why != 3]
        r = np.maximum(S.w35_roe.to_numpy(), -1.0)
        d = np.nan_to_num(S.tj_dir.to_numpy())
        al = (np.sign(d) * S.side.to_numpy()).astype(np.int8)
        df = pd.DataFrame({"day": (S.t.to_numpy(np.int64) // DAY).astype(np.int32), "coin": np.int8(ci), "tf": tf,
                           "side": S.side.to_numpy(np.int8), "al": al, "r": r})
        g = df.groupby(["day", "coin", "tf", "side", "al"]).r.agg(["sum", "count"]).reset_index()
        parts.append(g)
        log(tf, coin, len(S))
        drop(coin)
A = pd.concat(parts, ignore_index=True)
# (aggregate table not kept: disk nearly full)
out = {}


def gap(G):
    w = G[G.al == 1]
    g = G[G.al == -1]
    return w["sum"].sum() / w["count"].sum() - g["sum"].sum() / g["count"].sum()


out["n_with"] = int(A[A.al == 1]["count"].sum())
out["n_against"] = int(A[A.al == -1]["count"].sum())
out["with"] = float(A[A.al == 1]["sum"].sum() / out["n_with"])
out["against"] = float(A[A.al == -1]["sum"].sum() / out["n_against"])
out["gap"] = out["with"] - out["against"]
for sd, s in (("L", 1), ("S", -1)):
    out[f"gap_{sd}"] = float(gap(A[A.side == s]))
for tf in TFS:
    out[f"gap_tf_{tf}"] = float(gap(A[A.tf == tf]))
    for sd, s in (("L", 1), ("S", -1)):
        out[f"gap_tf_{tf}_{sd}"] = float(gap(A[(A.tf == tf) & (A.side == s)]))
# within (side, day)
Y = A[A.al != 0].groupby(["day", "side", "al"])[["sum", "count"]].sum().unstack("al").dropna()
mw = Y[("sum", 1)] / Y[("count", 1)]
mg = Y[("sum", -1)] / Y[("count", -1)]
wt = Y[("count", 1)] + Y[("count", -1)]
out["within_side_day"] = float(((mw - mg) * wt).sum() / wt.sum())
log("5y", json.dumps({k: round(100 * v, 2) if isinstance(v, float) else v for k, v in out.items()}))

# ---------------- market move per day (6-coin mean of daily log returns)
rets = []
for ci, coin in enumerate(COINS):
    b = bars(coin, "1d")
    d = (b.ts.to_numpy(np.int64) // DAY).astype(np.int32)
    lr = np.log(b.close.to_numpy() / b.open.to_numpy())
    rets.append(pd.Series(lr, index=d))
    drop(coin)
R = pd.concat(rets, axis=1).mean(axis=1)

# ---------------- 19-day windows
D = A.groupby(["day", "side", "al"])[["sum", "count"]].sum().unstack(["side", "al"]).fillna(0)
days = np.arange(D.index.min(), D.index.max() + 1)
D = D.reindex(days).fillna(0)
cs = D.cumsum()
W = 19
rows = []
for i in range(W, len(days) + 1):
    a, b = i - W, i
    tot = cs.iloc[b - 1] - (cs.iloc[a - 1] if a > 0 else 0)
    def m(sd, c):
        n = tot[("count", sd, c)] if ("count", sd, c) in tot.index else 0
        s = tot[("sum", sd, c)] if ("sum", sd, c) in tot.index else 0
        return s, n
    sw = sum(m(sd, 1)[0] for sd in (1, -1)); nw = sum(m(sd, 1)[1] for sd in (1, -1))
    sg = sum(m(sd, -1)[0] for sd in (1, -1)); ng = sum(m(sd, -1)[1] for sd in (1, -1))
    gL = m(1, 1)[0] / max(m(1, 1)[1], 1) - m(1, -1)[0] / max(m(1, -1)[1], 1)
    gS = m(-1, 1)[0] / max(m(-1, 1)[1], 1) - m(-1, -1)[0] / max(m(-1, -1)[1], 1)
    nL = m(1, 1)[1] + m(1, -1)[1]
    nS = m(-1, 1)[1] + m(-1, -1)[1]
    pL = nL / max(nL + nS, 1)
    mv = float(np.expm1(R.reindex(days[a:b]).fillna(0).sum()))
    rows.append({"day0": int(days[a]), "with": sw / max(nw, 1), "against": sg / max(ng, 1),
                 "gap": sw / max(nw, 1) - sg / max(ng, 1), "gapL": gL, "gapS": gS, "side_std": pL * gL + (1 - pL) * gS,
                 "n_with": nw, "n_against": ng, "move": mv})
Wd = pd.DataFrame(rows)
Wd["date0"] = pd.to_datetime(Wd.day0 * 86400, unit="s").dt.strftime("%Y-%m-%d")
Wd.to_csv(os.path.join(HERE, "v3_windows.csv.gz"), index=False, compression="gzip")
FWD = 0.0470
nonover = Wd.iloc[::19]
out["windows"] = {
    "n_windows": int(len(Wd)), "n_nonoverlap": int(len(nonover)),
    "share_gap_ge_fwd": float(np.mean(Wd.gap >= FWD)), "share_gap_ge_fwd_nonoverlap": float(np.mean(nonover.gap >= FWD)),
    "share_gap_gt0": float(np.mean(Wd.gap > 0)),
    "mean_gap": float(Wd.gap.mean()), "median_gap": float(Wd.gap.median()),
    "q05": float(Wd.gap.quantile(0.05)), "q95": float(Wd.gap.quantile(0.95)),
    "corr_gap_absmove": float(np.corrcoef(Wd.gap, Wd.move.abs())[0, 1]),
    "fell10_n": int((Wd.move <= -0.10).sum()),
    "fell10_mean_gap": float(Wd.gap[Wd.move <= -0.10].mean()),
    "fell10_share_gap_ge_fwd": float(np.mean(Wd.gap[Wd.move <= -0.10] >= FWD)),
    "fell10_share_gap_gt0": float(np.mean(Wd.gap[Wd.move <= -0.10] > 0)),
    "rose10_mean_gap": float(Wd.gap[Wd.move >= 0.10].mean()),
    "flat5_mean_gap": float(Wd.gap[Wd.move.abs() < 0.05].mean()),
    "flat5_share_gap_gt0": float(np.mean(Wd.gap[Wd.move.abs() < 0.05] > 0)),
    "side_std_mean": float(Wd.side_std.mean()), "side_std_share_gt0": float(np.mean(Wd.side_std > 0)),
    "fell10_side_std_mean": float(Wd.side_std[Wd.move <= -0.10].mean()),
}
# by move bucket
Wd["bucket"] = pd.cut(Wd.move, [-1, -0.2, -0.1, -0.05, 0.05, 0.1, 0.2, 10])
out["by_move"] = Wd.groupby("bucket", observed=True).agg(n=("gap", "size"), gap=("gap", "mean"),
                                                          share_pos=("gap", lambda x: float(np.mean(x > 0))),
                                                          side_std=("side_std", "mean")).reset_index().astype(
    {"bucket": str}).to_dict("records")
json.dump(out, open(os.path.join(HERE, "v3_out.json"), "w"), indent=1, default=float)
print(json.dumps(out, indent=1, default=float))
