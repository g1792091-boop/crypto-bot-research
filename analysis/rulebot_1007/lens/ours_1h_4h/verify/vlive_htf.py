"""Verifier: live HTF agreement for our 15m/30m every-signal outcomes (own code).

    python3 -I vlive_htf.py <export_dir> <v_live_es.csv> <out_dir>

States at the LTF signal's bar close T:
  ctx       signal_ctx htf_regime of the signal itself (trend_up/down vs side)
  sig_1h/4h same strategy's latest 1h/4h signal_log row (SUBMITTED or RECORD) on the same coin with bar close in
            (T - 4 bars, T]; signals in the first 4 HTF bars of a run are left out (unknown look-back)
  mom_4h    sign(close(T) - close(T - 4 h)) from live_bars (v3b, v4 only; v3a has no live_bars)
FE contrast agree - against within strategy x tf; CI by cluster bootstrap over run x 4 h blocks (2,000 draws).
"""
import json
import site
import sys

sys.dont_write_bytecode = True
sys.path.append(site.getusersitepackages())
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

E, ESF, OUTD = sys.argv[1:4]
RUNS = {"run-20261005T014624Z": "v3a", "run-20261005T183457Z": "v3b", "current": "v4"}
TFMS = {"1h": 3_600_000, "4h": 14_400_000}
RNG = np.random.default_rng(2024)


def est(y, a, st):
    ym = pd.Series(y).groupby(st).transform("mean").to_numpy()
    am = pd.Series(a).groupby(st).transform("mean").to_numpy()
    ad = a - am
    sxx = (ad ** 2).sum()
    return (ad * (y - ym)).sum() / sxx if sxx > 0 else np.nan


def contrast(d, col, B=2000):
    d = d[d[col] != 0]
    if len(d) < 6 or d[col].nunique() < 2:
        return dict(n=len(d))
    y = d.R.to_numpy(float)
    a = (d[col] == 1).to_numpy(float)
    st = d.stratum.to_numpy()
    b = est(y, a, st)
    cl = d.cl.to_numpy()
    u = np.unique(cl)
    pos = {c: np.nonzero(cl == c)[0] for c in u}
    bs = []
    for _ in range(B):
        ii = np.concatenate([pos[c] for c in RNG.choice(u, size=len(u))])
        bs.append(est(y[ii], a[ii], st[ii]))
    bs = np.array(bs)
    bs = bs[np.isfinite(bs)]
    if len(bs) < 100:
        bs = np.array([np.nan])
    return dict(n=len(d), n_agree=int(a.sum()), n_against=int((1 - a).sum()), aa=b, lo=np.percentile(bs, 2.5),
                hi=np.percentile(bs, 97.5), R_agree=y[a == 1].mean(), R_against=y[a == 0].mean(), clusters=len(u))


def main():
    ES = pd.read_csv(ESF)
    L = ES[ES.tf.isin(["15m", "30m"]) & (ES.status == "TRADED") & ES.R.notna()].copy()
    parts = []
    nctx = {}
    for run, rk in RUNS.items():
        x = L[L.run == run].copy()
        sl = pd.read_csv(f"{E}/{run}/signal_log.csv")
        t0 = sl.bar_close.min()
        # ctx via signal id
        sid = sl[sl.status == "SUBMITTED"][["id", "strategy", "timeframe", "symbol", "bar_close"]]
        ctx = {}
        with open(f"{E}/{run}/signal_ctx.jsonl") as fh:
            for line in fh:
                dd = json.loads(line)
                ctx[int(dd["id"])] = (dd.get("ctx") or {}).get("htf_regime")
        sid = sid.assign(htf_regime=sid.id.map(ctx))
        x = x.merge(sid.rename(columns={"timeframe": "tf", "bar_close": "bc"}).drop(columns="id"),
                    on=["strategy", "tf", "symbol", "bc"], how="left")
        lab = x.htf_regime.map({"trend_up": 1, "trend_down": -1}).fillna(0).to_numpy()
        x["ctx"] = lab * x.side.to_numpy()
        nctx[rk] = (int((lab != 0).sum()), len(x), x.htf_regime.value_counts(dropna=False).to_dict())
        T = x.bc.to_numpy(np.int64)
        hs = sl[sl.timeframe.isin(["1h", "4h"]) & sl.status.isin(["SUBMITTED", "RECORD"])]
        for htf in ("1h", "4h"):
            v = np.zeros(len(x))
            h = hs[hs.timeframe == htf]
            for (s, sym), g in h.groupby(["strategy", "symbol"]):
                sel = ((x.strategy == s) & (x.symbol == sym)).to_numpy()
                if not sel.any():
                    continue
                g = g.sort_values("bar_close")
                cm, sd = g.bar_close.to_numpy(np.int64), g.side.to_numpy()
                j = np.searchsorted(cm, T[sel], side="right") - 1
                rec = (j >= 0) & ((T[sel] - cm[np.maximum(j, 0)]) < 4 * TFMS[htf])
                vv = np.zeros(sel.sum())
                vv[rec] = sd[j[rec]] * x.side.to_numpy()[sel][rec]
                v[sel] = vv
            v[(T - t0) < 4 * TFMS[htf]] = 0      # unknown look-back: dropped from agree/against
            x[f"sig_{htf}"] = v
        x["mom_4h"] = 0.0
        try:
            lb = pd.read_csv(f"{E}/{run}/live_bars.csv", usecols=["ts", "symbol", "close"])
            lb["t"] = lb.ts + 60_000
            for sym, g in lb.groupby("symbol"):
                g = g.sort_values("t")
                tt, cc = g.t.to_numpy(), g.close.to_numpy(float)
                sel = (x.symbol == sym).to_numpy()
                j1 = np.searchsorted(tt, T[sel], side="right") - 1
                j0 = np.searchsorted(tt, T[sel] - 4 * 3_600_000, side="right") - 1
                ok = (j1 >= 0) & (j0 >= 0) & ((T[sel] - 4 * 3_600_000 - tt[np.maximum(j0, 0)]) < 120_000)
                m = np.zeros(sel.sum())
                m[ok] = np.sign(cc[j1[ok]] - cc[j0[ok]])
                x.loc[sel, "mom_4h"] = m * x.side.to_numpy()[sel]
        except FileNotFoundError:
            pass
        parts.append(x)
    X = pd.concat(parts, ignore_index=True)
    X["stratum"] = X.strategy + "|" + X.tf
    print("ctx htf_regime trend labels (count, rows, labels):", nctx)
    rows = []
    for col in ("ctx", "sig_1h", "sig_4h", "mom_4h"):
        for rk in ("all", "v3a", "v3b", "v4"):
            d = X if rk == "all" else X[X.rk == rk]
            r = contrast(d, col)
            r.update(defn=col, run=rk)
            rows.append(r)
    P = pd.DataFrame(rows)
    P.to_csv(f"{OUTD}/v_live_htf.csv", index=False)
    pd.set_option("display.width", 220)
    print(P.round(3).to_string())
    v4 = X[(X.rk == "v4") & (X.mom_4h == 1)]
    print("v4 mom_4h agree: n", len(v4), "mean R", round(v4.R.mean(), 3), "long share", round((v4.side > 0).mean(), 3))


if __name__ == "__main__":
    main()
