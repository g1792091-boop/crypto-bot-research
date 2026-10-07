"""Live side of the 5-year reconciliation: one row per live every-signal outcome, and per-cell statistics.

    python3 -I -B live_cells.py <out_real_dir> <export_dir> <analyze_py> <out_dir>

Sources (read-only):
  replay_signals.csv  v3b + v4: every SUBMITTED signal alone through the repo engine on live_bars (TRADED -> R, ret);
                      UNRESOLVED -> mark_R kept as a sensitivity column.
  trades_enriched.csv v3a entered trades (R, roe_per_lev).
  export v3a d3_shadows.csv kind=skipped: the skipped signal alone (daily3._alone, fresh $5,000, tier walk), ROE only.
      Its leverage is reconstructed with paperbot.sizing.size_position (tier walk, requested 'best', $5,000, the
      pipeline's INFERRED_BRACKETS) from signal_log atr / ref_price -> ret = roe/lev, R = ret/stop_frac.
  export signal_log.csv: signal counts (SUBMITTED / LATE / NO_PRICE / NO_ATR / RECORD, XRP excluded) per run.
"""
from __future__ import annotations

import importlib.util
import os
import sys

sys.path.append('/root/.local/lib/python3.11/site-packages')
REPO = '/home/user/crypto-bot-research'
sys.path.insert(0, REPO)
sys.dont_write_bytecode = True

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

TF_MS = {"5m": 300_000, "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000}
RUN_LABEL = {"run-20261005T014624Z": "v3a", "run-20261005T183457Z": "v3b", "current": "v4"}
SLIP = 0.0002


def cluster_id(run, bc, tf):
    w = np.array([max(TF_MS[t], 3_600_000) for t in tf], dtype=np.int64)
    return pd.Series(run).astype(str).values + ":" + (np.asarray(bc, dtype=np.int64) // w).astype(str)


def cl_stats(x, cl):
    """mean, cluster-robust SE (CR0 with small-sample factor), n, clusters."""
    x = np.asarray(x, float)
    m = np.isfinite(x)
    x, cl = x[m], np.asarray(cl)[m]
    n = len(x)
    if n == 0:
        return np.nan, np.nan, 0, 0
    mu = x.mean()
    s = pd.Series(x - mu).groupby(cl).sum().to_numpy()
    G = len(s)
    if G < 2:
        return mu, np.nan, n, G
    se = np.sqrt((s ** 2).sum() * G / (G - 1)) / n
    return mu, se, n, G


def main(rd, ex, analyze_py, od):
    os.makedirs(od, exist_ok=True)
    spec = importlib.util.spec_from_file_location("rb_analyze_ro", analyze_py)
    A = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(A)
    from paperbot.sizing import size_position
    brackets, _src = A.make_brackets(None)
    s_tw = A.replay_settings("tier_walk", 0.0005)

    rows = []
    # ---------------- v3b + v4 replay (every submitted signal)
    rp = pd.read_csv(os.path.join(rd, "replay_signals.csv"))
    rp = rp[rp["kind"].isin(["strategy", "ds200", "random"])]
    for r in rp.itertuples():
        st = r.status
        if st not in ("TRADED", "UNRESOLVED", "REJECTED_SIZING"):
            continue
        rows.append(dict(run=RUN_LABEL[r.run], kind=r.kind, strategy=r.strategy, tf=r.timeframe, symbol=r.symbol,
                         bar_close=int(r.bar_close), side=int(r.side), source="replay", status=st,
                         R=r.R if st == "TRADED" else np.nan, ret=r.roe_per_lev if st == "TRADED" else np.nan,
                         roe=r.roe if st == "TRADED" else np.nan, lev=r.leverage, stop_frac=r.stop_frac,
                         mark_R=r.mark_R if st == "UNRESOLVED" else np.nan, acct=r.acct_status))
    # ---------------- v3a: entered trades + skipped shadows
    te = pd.read_csv(os.path.join(rd, "trades_enriched.csv"))
    t3 = te[(te["run"] == "run-20261005T014624Z") & te["kind"].isin(["strategy", "random"])]
    for r in t3.itertuples():
        rows.append(dict(run="v3a", kind=r.kind, strategy=r.strategy, tf=r.tf, symbol=r.symbol,
                         bar_close=int(r.signal_ts) + 1, side=int(r.side), source="entered", status="TRADED",
                         R=r.R, ret=r.roe_per_lev, roe=r.roe, lev=r.leverage, stop_frac=r.stop_frac,
                         mark_R=np.nan, acct="ENTERED"))
    sh = pd.read_csv(os.path.join(ex, "run-20261005T014624Z", "d3_shadows.csv"))
    sh = sh[sh["kind"] == "skipped"].drop_duplicates("key")
    parts = sh["key"].str.split("|", expand=True)
    sh["aid"], sh["bc"] = parts[1], pd.to_numeric(parts[3], errors="coerce").astype("Int64")
    sl = pd.read_csv(os.path.join(ex, "run-20261005T014624Z", "signal_log.csv"))
    sl = sl.drop_duplicates(["strategy", "timeframe", "symbol", "bar_close"]).set_index(["strategy", "timeframe", "symbol", "bar_close"])
    n_nomatch = n_unsized = n_noroe = 0
    lev_cache = {}
    for r in sh.itertuples():
        stname, tf = r.aid.split("@")[0], r.aid.split("@")[1]
        if not (r.resolved == 1 and np.isfinite(r.roe)):
            n_noroe += 1
            continue
        key = (stname, tf, r.symbol, int(r.bc))
        if key not in sl.index:
            n_nomatch += 1
            continue
        g = sl.loc[key]
        side, atr, ref = int(r.side), float(g["atr"]), float(g["ref_price"])
        fill = ref * (1 + side * SLIP)
        stop = ref - side * 2.0 * atr
        ck = (r.symbol, side, round(2 * atr / ref, 6))
        if ck not in lev_cache:
            d = size_position(s_tw, 5000.0, side, fill, stop, "best", brackets[r.symbol], atr=atr, min_notional=5.0)
            lev_cache[ck] = d.leverage if d.ok else 0
        lev = lev_cache[ck]
        if lev <= 0:
            n_unsized += 1
            continue
        sf = abs(fill - stop) / fill
        kind = A.infer_kind(r.aid)
        rows.append(dict(run="v3a", kind=kind, strategy=stname, tf=tf, symbol=r.symbol, bar_close=int(r.bc), side=side,
                         source="shadow_skipped", status="TRADED", R=r.roe / lev / sf, ret=r.roe / lev, roe=r.roe, lev=lev,
                         stop_frac=sf, mark_R=np.nan, acct="SKIPPED"))
    L = pd.DataFrame(rows)
    L = L[L["kind"].isin(["strategy", "ds200", "random"])]
    L["cluster"] = cluster_id(L["run"], L["bar_close"], L["tf"])
    L.to_csv(os.path.join(od, "live_signals.csv"), index=False)

    # ---------------- leverage reconstruction check on v3a entered trades (same sizing, fresh $5,000)
    chk = []
    for r in t3.itertuples():
        key = (r.strategy, r.tf, r.symbol, int(r.signal_ts) + 1)
        if key not in sl.index:
            continue
        g = sl.loc[key]
        side, atr, ref = int(r.side), float(g["atr"]), float(g["ref_price"])
        d = size_position(s_tw, 5000.0, side, ref * (1 + side * SLIP), ref - side * 2 * atr, "best", brackets[r.symbol], atr=atr, min_notional=5.0)
        chk.append((r.leverage, d.leverage if d.ok else 0, r.eq_before))
    chk = pd.DataFrame(chk, columns=["actual", "recon", "eq_before"])
    near = chk[(chk["eq_before"] > 4500) & (chk["eq_before"] < 5500)]
    info = dict(v3a_shadow_rows=len(sh), shadow_no_roe=n_noroe, shadow_no_signal_match=n_nomatch, shadow_unsized=n_unsized,
                lev_check_n=len(chk), lev_check_equal=float((chk["actual"] == chk["recon"]).mean()) if len(chk) else np.nan,
                lev_check_n_eq_near_5000=len(near),
                lev_check_equal_eq_near_5000=float((near["actual"] == near["recon"]).mean()) if len(near) else np.nan)
    pd.DataFrame([info]).to_csv(os.path.join(od, "live_v3a_shadow_info.csv"), index=False)
    print(info)

    # ---------------- signal counts per run x strategy x tf
    meta = pd.read_csv(os.path.join(rd, "runs_meta.csv"))
    days = {RUN_LABEL[r]: d for r, d in zip(meta["run"], meta["days"])}
    cnt = []
    for run, lab in RUN_LABEL.items():
        s = pd.read_csv(os.path.join(ex, run, "signal_log.csv"))
        s = s[s["status"].isin(["SUBMITTED", "LATE", "NO_PRICE", "NO_ATR", "RECORD"]) & (s["symbol"] != "XRPUSDT")]
        s = s.drop_duplicates(["strategy", "timeframe", "symbol", "bar_close"])
        for (st, tf), n in s.groupby(["strategy", "timeframe"]).size().items():
            cnt.append(dict(run=lab, strategy=st, tf=tf, n_signals=int(n), days=days[lab]))
    acc_tf = {}
    for run, lab in RUN_LABEL.items():
        a = pd.read_csv(os.path.join(ex, run, "accounts.csv"))
        for st, tf in zip(a["strategy"], a["timeframe"]):
            acc_tf.setdefault((st, tf), set()).add(lab)
    C = pd.DataFrame(cnt)
    C.to_csv(os.path.join(od, "live_signal_counts.csv"), index=False)

    # ---------------- per cell statistics
    out = []
    keys = sorted(set(zip(L["kind"], L["strategy"], L["tf"])) | {(A.infer_kind(st + "@" + tf), st, tf) for (st, tf) in acc_tf})
    for k, st, tf in keys:
        g = L[(L["kind"] == k) & (L["strategy"] == st) & (L["tf"] == tf)]
        d = dict(kind=k, strategy=st, tf=tf, runs=" ".join(sorted(acc_tf.get((st, tf), set()))))
        for lab, sel in (("rp", g["source"] == "replay"), ("v3a", g["run"] == "v3a"), ("all", g.index == g.index)):
            gg = g[sel & (g["status"] == "TRADED")]
            mu, se, n, G = cl_stats(gg["R"], gg["cluster"])
            d.update({f"{lab}_n": n, f"{lab}_clusters": G, f"{lab}_mean_R": mu, f"{lab}_se_R": se,
                      f"{lab}_mean_ret": gg["ret"].mean() if len(gg) else np.nan,
                      f"{lab}_win_pct": 100 * (gg["R"] > 0).mean() if len(gg) else np.nan,
                      f"{lab}_median_stop_frac": gg["stop_frac"].median() if len(gg) else np.nan})
        gu = g[(g["source"] == "replay") & (g["status"] == "UNRESOLVED")]
        d["rp_unresolved"] = len(gu)
        gx = g[(g["source"] == "replay") & g["status"].isin(["TRADED", "UNRESOLVED"])]
        xr = np.where(gx["status"] == "TRADED", gx["R"], gx["mark_R"])
        d["rp_mean_R_incl_mark"] = np.nanmean(xr) if len(gx) else np.nan
        d["rp_rejected_sizing"] = int(((g["source"] == "replay") & (g["status"] == "REJECTED_SIZING")).sum())
        # entered-only (what the one-position accounts actually took): all runs
        ge = te[(te["kind"] == k) & (te["strategy"] == st) & (te["tf"] == tf)]
        d["entered_n"] = len(ge)
        d["entered_mean_R"] = ge["R"].mean() if len(ge) else np.nan
        d["entered_mean_ret"] = ge["roe_per_lev"].mean() if len(ge) else np.nan
        for lab in ("v3a", "v3b", "v4"):
            c = C[(C["run"] == lab) & (C["strategy"] == st) & (C["tf"] == tf)]
            d[f"sig_{lab}"] = int(c["n_signals"].sum()) if lab in acc_tf.get((st, tf), set()) else np.nan
        dd = sum(days[lab] for lab in acc_tf.get((st, tf), set()))
        d["live_days"] = dd
        d["live_signals_per_day"] = np.nansum([d[f"sig_{x}"] for x in ("v3a", "v3b", "v4")]) / dd if dd else np.nan
        out.append(d)
    O = pd.DataFrame(out)
    O.to_csv(os.path.join(od, "live_cells.csv"), index=False)
    print(len(L), "live signal rows;", len(O), "cells")
    print(L.groupby(["run", "kind", "source", "status"]).size())


if __name__ == "__main__":
    main(*sys.argv[1:5])
