"""Live test (out of sample vs the 5-year discovery): do our 36 strategies' 15m/30m signals do better when they agree
with the 1h/4h state? Every-signal outcomes (es_signals.csv: v3a entered + skipped shadows, v3b/v4 replay).

    python3 -I live_htf.py <export_dir> <out_real_dir> <es_signals.csv> <out_dir>

States at the signal's bar close T (all strictly from information available at T):
  ctx_htf_regime   the signal's own ctx 'htf_regime' (15m -> 1h regime, 30m -> 4h regime): trend_up/down vs side
  same_sig_1h/4h   the same strategy's latest 1h / 4h signal on the same coin (signal_log SUBMITTED or RECORD) with
                   bar close in (T - 4 bars, T]: same side = agree, other side = against; none = neutral. Signals
                   within the first 4 bars of a run have no full look-back: 'unknown' (left out of agree-vs-neutral).
  same_pos_1h/4h   the same strategy's 1h / 4h RULE ACCOUNT holds a position on the same coin at T (trades.csv
                   entry_time <= T < exit_time; entered-but-open positions run to the end of the run)
  mkt_mom_1h/4h    sign of price(T) - price(T - 4 h) / price(T - 16 h) on the same coin (live_bars close; v3a: the
                   nearest signal reference price or trade fill within 15 minutes, as rb_analyze's APPROX backdrop)
Contrast agree - against within strategy x tf (fixed effects); 95% CI by cluster bootstrap over run x 4-hour blocks
(2,000 draws). Writes live_htf_groups.csv, live_htf_contrasts.csv, live_ltf_features.csv.
"""
import json
import site
import sys

sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

E, O, ESF, OUTD = sys.argv[1:5]
RUNS = {"run-20261005T014624Z": "v3a", "run-20261005T183457Z": "v3b", "current": "v4"}
TFMS = {"1h": 3_600_000, "4h": 14_400_000}
H4 = 14_400_000
RNG = np.random.default_rng(20261009)
DEFS = ["ctx_htf_regime", "same_sig_1h", "same_sig_4h", "same_pos_1h", "same_pos_4h", "mkt_mom_1h", "mkt_mom_4h"]


def price_series(run):
    """{symbol: (ts_ms sorted, price)}"""
    out = {}
    try:
        lb = pd.read_csv(f"{E}/{run}/live_bars.csv", usecols=["ts", "symbol", "close"])
        lb["t"] = lb["ts"] + 60_000          # close of the 1m bar
        for s, g in lb.groupby("symbol"):
            g = g.sort_values("t")
            out[s] = (g["t"].to_numpy(), g["close"].to_numpy(float))
        return out, "live_bars"
    except FileNotFoundError:
        sl = pd.read_csv(f"{E}/{run}/signal_log.csv", usecols=["symbol", "ref_time", "ref_price"]).dropna()
        tr = pd.read_csv(f"{E}/{run}/trades.csv", usecols=["symbol", "entry_time", "entry_price", "exit_time",
                                                            "exit_price"])
        a = pd.concat([sl.rename(columns={"ref_time": "t", "ref_price": "p"}),
                       tr[["symbol", "entry_time", "entry_price"]].rename(columns={"entry_time": "t", "entry_price": "p"}),
                       tr[["symbol", "exit_time", "exit_price"]].rename(columns={"exit_time": "t", "exit_price": "p"})])
        for s, g in a.groupby("symbol"):
            g = g.sort_values("t")
            out[s] = (g["t"].to_numpy(np.int64), g["p"].to_numpy(float))
        return out, "APPROX signal ref prices + fills"


def px_at(ser, t, tol=15 * 60_000):
    ts, p = ser
    j = np.searchsorted(ts, t, side="right") - 1
    v = np.full(len(t), np.nan)
    ok = (j >= 0)
    ok[ok] = (t[ok] - ts[j[ok]]) <= tol
    v[ok] = p[j[ok]]
    return v


def fe(df, mask, B=2000):
    d = df[mask]
    if len(d) < 6 or d["_a"].nunique() < 2:
        return np.nan, np.nan, np.nan, len(d)
    g = d["stratum"].to_numpy()

    def est(dd, gg):
        y = dd["R"].to_numpy(float)
        x = dd["_a"].to_numpy(float)
        ym = pd.Series(y).groupby(gg).transform("mean").to_numpy()
        xm = pd.Series(x).groupby(gg).transform("mean").to_numpy()
        xd = x - xm
        sxx = (xd ** 2).sum()
        return (xd * (y - ym)).sum() / sxx if sxx > 0 else np.nan
    b = est(d, g)
    cl = d["cl"].to_numpy()
    u = np.unique(cl)
    if len(u) < 4:
        return b, np.nan, np.nan, len(d)
    pos = {c: np.nonzero(cl == c)[0] for c in u}
    bs = []
    for _ in range(B):
        pick = RNG.choice(u, size=len(u), replace=True)
        ii = np.concatenate([pos[c] for c in pick])
        dd = d.iloc[ii]
        # make strata unique per draw is unnecessary: FE by stratum label is fine with repeats
        bs.append(est(dd, dd["stratum"].to_numpy()))
    bs = np.array(bs, float)
    bs = bs[np.isfinite(bs)]
    return b, np.percentile(bs, 2.5), np.percentile(bs, 97.5), len(d)


def main():
    ES = pd.read_csv(ESF)
    L = ES[ES["timeframe"].isin(["15m", "30m"])].copy()
    feats = []
    for run, rk in RUNS.items():
        x = L[L["run"] == run].copy()
        if not len(x):
            continue
        sl = pd.read_csv(f"{E}/{run}/signal_log.csv")
        t0 = sl["bar_close"].min()
        # ctx
        ctx = {}
        with open(f"{E}/{run}/signal_ctx.jsonl") as fh:
            for line in fh:
                dd = json.loads(line)
                c = dd.get("ctx") or {}
                ctx[int(dd["id"])] = c.get("htf_regime")
        reg = x["sig_id"].map(lambda i: ctx.get(int(i)) if i == i else None)
        rv = reg.map({"trend_up": 1, "trend_down": -1}).fillna(0).astype(int)
        x["ctx_htf_regime"] = rv * x["side"]
        x["ctx_htf_regime_label"] = reg.fillna("NA")
        # same strategy HTF signals
        hs = sl[sl["timeframe"].isin(["1h", "4h"]) & sl["status"].isin(["SUBMITTED", "RECORD"])]
        T = x["bc"].to_numpy(np.int64)
        for htf in ("1h", "4h"):
            v = np.zeros(len(x), int)
            unknown = (T - t0) < 4 * TFMS[htf]
            h = hs[hs["timeframe"] == htf]
            for (s, sym), g in h.groupby(["strategy", "symbol"]):
                sel = ((x["strategy"] == s) & (x["symbol"] == sym)).to_numpy()
                if not sel.any():
                    continue
                g = g.sort_values("bar_close")
                cm, sd = g["bar_close"].to_numpy(np.int64), g["side"].to_numpy(int)
                j = np.searchsorted(cm, T[sel], side="right") - 1
                ok = j >= 0
                rec = ok & ((T[sel] - cm[np.maximum(j, 0)]) < 4 * TFMS[htf])
                vv = np.zeros(sel.sum(), int)
                vv[rec] = sd[j[rec]] * x["side"].to_numpy()[sel][rec]
                v[sel] = vv
            x[f"same_sig_{htf}"] = v
            x[f"same_sig_{htf}_unknown"] = unknown & (v == 0)
        # same strategy HTF rule account positions
        tr = pd.read_csv(f"{E}/{run}/trades.csv", usecols=["account_id", "symbol", "side", "entry_time", "exit_time"])
        oc = pd.read_csv(f"{E}/{run}/outcomes.csv", usecols=["account_id", "status", "symbol", "sig_ts", "sig_side",
                                                              "step_ts"])
        end = sl["bar_close"].max() + 60 * 60_000
        ent = oc[oc["status"] == "ENTERED"]
        for htf in ("1h", "4h"):
            v = np.zeros(len(x), int)
            for s in x["strategy"].unique():
                aid = f"{s}@{htf}"
                t = tr[tr["account_id"] == aid]
                iv = [(int(r.entry_time), int(r.exit_time), r.symbol, int(r.side)) for r in t.itertuples()]
                # entered but never closed
                e = ent[ent["account_id"] == aid]
                for r in e.itertuples():
                    if not ((t["symbol"] == r.symbol) & (t["entry_time"] == r.step_ts)).any() and \
                            not ((t["symbol"] == r.symbol) & ((t["entry_time"] - r.step_ts).abs() <= 120_000)).any():
                        iv.append((int(r.step_ts), int(end), r.symbol, int(r.sig_side)))
                sel = np.nonzero((x["strategy"] == s).to_numpy())[0]
                for a0, a1, sym, sd in iv:
                    m = (x["symbol"].to_numpy()[sel] == sym) & (T[sel] >= a0) & (T[sel] < a1)
                    v[sel[m]] = sd * x["side"].to_numpy()[sel[m]]
            x[f"same_pos_{htf}"] = v
        # market momentum
        ps, src = price_series(run)
        for htf, back in (("1h", 4 * 3_600_000), ("4h", 16 * 3_600_000)):
            v = np.zeros(len(x), int)
            unk = np.zeros(len(x), bool)
            for sym in x["symbol"].unique():
                sel = (x["symbol"] == sym).to_numpy()
                if sym not in ps:
                    unk[sel] = True
                    continue
                p1 = px_at(ps[sym], T[sel])
                p0 = px_at(ps[sym], T[sel] - back)
                ok = np.isfinite(p1) & np.isfinite(p0)
                vv = np.zeros(sel.sum(), int)
                vv[ok] = np.sign(p1[ok] - p0[ok]).astype(int) * x["side"].to_numpy()[sel][ok]
                v[sel] = vv
                unk[np.nonzero(sel)[0][~ok]] = True
            x[f"mkt_mom_{htf}"] = v
            x[f"mkt_mom_{htf}_unknown"] = unk
        x["price_src"] = src
        feats.append(x)
    F = pd.concat(feats, ignore_index=True)
    F["stratum"] = F["strategy"] + "|" + F["timeframe"]
    F["cl"] = F["run"] + "|" + (F["bc"] // H4).astype(np.int64).astype(str)
    F.to_csv(f"{OUTD}/live_ltf_features.csv", index=False)

    grows, crows = [], []
    for rk in ("v3a", "v3b", "v4", "all"):
        for ltf in ("15m", "30m", "both"):
            base = F if rk == "all" else F[F["rk"] == rk]
            if ltf != "both":
                base = base[base["timeframe"] == ltf]
            for dfn in DEFS:
                unk_col = f"{dfn}_unknown"
                b = base[~base[unk_col]] if unk_col in base else base
                v = b[dfn]
                for lab, code in (("agree", 1), ("against", -1), ("neutral", 0)):
                    g = b[v == code]
                    grows.append({"run": rk, "ltf": ltf, "def": dfn, "group": lab, "n": len(g),
                                  "mean_R": g["R"].mean(), "win_pct": 100 * (g["R"] > 0).mean() if len(g) else np.nan,
                                  "long_share": (g["side"] > 0).mean() if len(g) else np.nan,
                                  "clusters": g["cl"].nunique()})
                tmp = b.assign(_a=(v == 1).astype(float))
                est, lo, hi, n = fe(tmp, (v != 0).to_numpy())
                est2, lo2, hi2, n2 = fe(tmp, (v != -1).to_numpy())
                crows.append({"run": rk, "ltf": ltf, "def": dfn, "agree_minus_against": est, "ci_lo": lo, "ci_hi": hi,
                              "n_agree_or_against": n, "agree_minus_neutral": est2, "ci2_lo": lo2, "ci2_hi": hi2,
                              "n_agree_or_neutral": n2})
    G = pd.DataFrame(grows)
    C = pd.DataFrame(crows)
    G.to_csv(f"{OUTD}/live_htf_groups.csv", index=False)
    C.to_csv(f"{OUTD}/live_htf_contrasts.csv", index=False)
    pd.set_option("display.width", 250)
    print(C[C["ltf"] == "both"].round(3).to_string())
    print(pd.crosstab([F["rk"], F["timeframe"]], F["ctx_htf_regime_label"]))


if __name__ == "__main__":
    main()
