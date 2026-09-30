"""Chart-review rules: features at the signal bar, and the full test (PREREG_CHART.md steps 5-7).

    SWEEP_DATA=<rebuilt sweep data> python3 research/chart_review/rules.py build <charts_dir>
    python3 research/chart_review/rules.py calib <charts_dir>     # rule vs chart code, reviewed 60 only
    python3 research/chart_review/rules.py test <charts_dir>      # full test (after PRERULES_CHART.md)

Every feature uses only bars up to and including the signal bar (what the chart showed).
"""

from __future__ import annotations

import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research", "diagnosis"))
warnings.filterwarnings("ignore")

TF, H = "15m", 16
STRATS = {"V45_AMB": "V45", "V39_ALL": "V39", "DOGE_L": "DOGE"}
HALF = pd.Timestamp("2023-01-01", tz="UTC")
FEATS = ["pos100", "counter4", "bigbody4", "range16", "vol_level", "atr_rel", "trend100", "srsi_k"]

# Rules fixed in PRERULES_CHART.md. kind: "exclude" = do not enter when the condition holds (expect the
# condition's trades to be worse, d < 0); "only" = enter only when it holds (expect d > 0).
RULES = [
    ("V45", "R1_fade_strong", "only", "counter4 >= 0.6"),
    ("V45", "R2_ctx_with", "exclude", "trend100 >= 3"),
    ("V45", "R3_low_vol", "exclude", "atr_rel < 0.075"),
    ("V39", "R4_recent_spike", "exclude", "bigbody4 >= 1.2"),
    ("V39", "R5_tight", "only", "range16 <= 2.8"),
    ("V39", "R6_low_vol", "only", "atr_rel < 0.075"),
    ("V39", "R7_chase", "exclude", "pos100 >= 0.8"),
    ("V39", "R8_ctx_range", "only", "abs(trend100) < 3"),
    ("DOGE", "R9_low_vol", "only", "atr_rel < 0.075"),
    ("DOGE", "R10_tight", "only", "range16 <= 2.8"),
    ("DOGE", "R11_srsi_low", "exclude", "srsi_k < 25"),
    ("DOGE", "R12_chase", "exclude", "pos100 >= 0.8"),
    ("DOGE", "R13_full_stack", "exclude", "full_stack == 1"),
]


def lib():
    from paperbot import sweepsig
    return sweepsig.lib()


def bar_feats(L, fg, df: pd.DataFrame) -> pd.DataFrame:
    import doge_strategy as ds
    o, h, lo, c = (df[k].astype(float) for k in ("open", "high", "low", "close"))
    atr = fg.atr(df, 14).astype(float)
    f = pd.DataFrame(index=df.index)
    f["atr"] = atr
    f["hi100"], f["lo100"] = h.rolling(101).max(), lo.rolling(101).min()
    f["c4"] = c - c.shift(4)
    f["bigbody4"] = ((c - o).abs().rolling(4).max()) / atr
    f["range16"] = (h.rolling(16).max() - lo.rolling(16).min()) / atr
    f["vol_level"] = atr / atr.rolling(500, min_periods=100).median()
    f["c100"] = c - c.shift(100)
    f["close"] = c
    p = L.doge_params(TF)
    d = df.set_index(pd.DatetimeIndex(pd.to_datetime(df["ts"], utc=True)))[["open", "high", "low", "close", "volume"]]
    ind = ds.compute_indicators(d, p)
    f["srsi_k"] = ind["K"].to_numpy(float)
    e = [ind[k].to_numpy(float) for k in ("ema_short", "ema_fast", "ema_slow", "ema_trend")]
    f["full_stack"] = ((e[0] > e[1]) & (e[1] > e[2]) & (e[2] > e[3])).astype(int)
    return f


def trade_feats(tr: pd.DataFrame, panel: dict, feats: dict) -> pd.DataFrame:
    rows = []
    for c, g in tr.groupby("symbol", sort=False):
        f = feats[c].iloc[g["signal_idx"].to_numpy()].reset_index(drop=True)
        s = g["side"].to_numpy()
        x = pd.DataFrame({"row": g.index.to_numpy(), "symbol": c, "side": s, "net": g["net"].to_numpy(),
                          "entry_ts": panel[c]["ts"].to_numpy()[g["entry_idx"].to_numpy()]})
        pos = (f["close"] - f["lo100"]) / (f["hi100"] - f["lo100"])
        x["pos100"] = np.where(s > 0, pos, 1 - pos)
        x["counter4"] = -s * f["c4"] / f["atr"]
        x["bigbody4"] = f["bigbody4"].to_numpy()
        x["range16"] = f["range16"].to_numpy()
        x["vol_level"] = f["vol_level"].to_numpy()
        x["trend100"] = s * f["c100"] / f["atr"]
        x["srsi_k"] = f["srsi_k"].to_numpy()
        x["full_stack"] = f["full_stack"].to_numpy()
        x["atr_rel"] = (f["atr"] / (f["hi100"] - f["lo100"])).to_numpy()
        x["tgt_beyond"] = np.where(s > 0, f["close"] + 3 * f["atr"] > f["hi100"],
                                   f["close"] - 3 * f["atr"] < f["lo100"]).astype(int)
        rows.append(x)
    return pd.concat(rows, ignore_index=True).sort_values("row").reset_index(drop=True)


def build(out: str, seeds: int = 5) -> None:
    L = lib()
    import fg_indicators as fg
    panel = L.load_panel(TF, "is")
    ex = [e for e in L.exit_set(H) if e[0] == "ATR_SL2_TP3"]
    atrs = {c: fg.atr(df, 14).to_numpy(float) for c, df in panel.items()}
    windows = {}
    for c, df in panel.items():
        lo, hi = L.signal_window(df, TF, "is", 0)
        if hi - lo > 2 * L.EXIT_CAP_MULT * H + 4:
            windows[c] = (lo, hi)
    feats = {c: bar_feats(L, fg, df) for c, df in panel.items()}
    counts = []
    for name, short in STRATS.items():
        tr = pd.read_pickle(os.path.join(out, f"trades_{short}.pkl"))
        counts.append(tr.groupby("symbol").size().mean())
        trade_feats(tr, panel, feats).to_pickle(os.path.join(out, f"feat_{short}.pkl"))
    nbars = sum(hi - lo for lo, hi in windows.values()) / len(windows)
    rate = min(0.5, 1.3 * float(np.mean(counts)) / nbars)
    parts = []
    for s in range(seeds):
        rng = np.random.default_rng([s, 20260930, 2])
        dsig = {c: np.where(rng.random(len(df)) < rate, rng.choice([-1, 1], len(df)), 0).astype(np.int8)
                for c, df in panel.items()}
        tr = L._run_exits_panel(panel, dsig, TF, "is", H, atrs, windows, 0, ex)["ATR_SL2_TP3"].reset_index(drop=True)
        parts.append(trade_feats(tr, panel, feats).assign(seed=s))
    pd.concat(parts, ignore_index=True).to_pickle(os.path.join(out, "feat_RANDOM.pkl"))
    print("built", {s: len(pd.read_pickle(os.path.join(out, f"feat_{s}.pkl"))) for s in [*STRATS.values(), "RANDOM"]})


def calib(out: str) -> None:
    """Agreement between each rule and the blind chart code, on the reviewed 60 only (no outcomes)."""
    pairs = {"counter4": ("MOVE", {"FADE-SPIKE"}), "bigbody4": ("MOVE", {"FADE-SPIKE", "BREAK"}),
             "range16": ("MOVE", {"FLAT"}), "vol_level": ("VOL", {"LOW"}), "pos100": ("LOC", {"EXTREME-CHASE"}),
             "trend100": ("CTX", {"WITH"}), "full_stack": ("STACK", {"FULL"}), "srsi_k": ("STOCH", {"OS"})}
    for short in STRATS.values():
        j = pd.read_csv(os.path.join(out, f"joined_{short}.csv"))
        f = pd.read_pickle(os.path.join(out, f"feat_{short}.pkl")).set_index("row")
        j = j.join(f.drop(columns=["symbol", "side", "net"]), on="trade_row")
        print(f"== {short}")
        for feat, (col, vals) in pairs.items():
            if col not in j:
                continue
            code = j[col].isin(vals)
            print(f"  {feat:10s} vs {col}={'/'.join(sorted(vals))}: coded {code.mean():.2f}; "
                  f"feature median coded {j.loc[code, feat].median():.2f} / not {j.loc[~code, feat].median():.2f}")


def _cond(df: pd.DataFrame, expr: str) -> np.ndarray:
    return df.eval(expr).to_numpy(bool)


def one_test(df: pd.DataFrame, b: np.ndarray) -> dict:
    from diag import diff_test
    from scipy import stats
    y = df["net"].to_numpy(float)
    day = pd.to_datetime(df["entry_ts"], utc=True).dt.floor("D").to_numpy()
    out = {"n_cond": int(b.sum()), "n_rest": int((~b).sum())}
    if b.sum() < 100 or (~b).sum() < 100:
        return {**out, "d": np.nan, "p": np.nan}
    d, se = diff_test(y, b, day)
    out.update(d=d, se=se, p=float(2 * stats.norm.sf(abs(d / se))),
               mean_cond=float(y[b].mean()), mean_rest=float(y[~b].mean()))
    coin = {}
    for c, g in df.assign(b=b).groupby("symbol"):
        if g["b"].sum() >= 20 and (~g["b"]).sum() >= 20:
            coin[c] = float(g.loc[g["b"], "net"].mean() - g.loc[~g["b"], "net"].mean())
    out["coin_d"] = coin
    ts = pd.to_datetime(df["entry_ts"], utc=True)
    for k, m in (("half1", (ts < HALF).to_numpy()), ("half2", (ts >= HALF).to_numpy())):
        bb = b[m]
        out[k] = float(y[m][bb].mean() - y[m][~bb].mean()) if bb.sum() >= 20 and (~bb).sum() >= 20 else np.nan
    return out


def test(out: str) -> None:
    from diag import bh
    reviewed = {s: set(pd.read_csv(os.path.join(out, f"key_{s}.csv"))["trade_row"]) for s in STRATS.values()}
    rnd = pd.read_pickle(os.path.join(out, "feat_RANDOM.pkl"))
    res = []
    for short, rid, kind, expr in RULES:
        df = pd.read_pickle(os.path.join(out, f"feat_{short}.pkl"))
        df = df[~df["row"].isin(reviewed[short])].reset_index(drop=True)
        df = df.dropna(subset=FEATS).reset_index(drop=True)
        r = one_test(df, _cond(df, expr))
        rr = rnd[rnd["side"] > 0] if short == "DOGE" else rnd
        rr = rr.dropna(subset=FEATS).reset_index(drop=True)
        rt = one_test(rr, _cond(rr, expr))
        res.append({"strategy": short, "rule": rid, "kind": kind, "expr": expr, **r,
                    "rand_d": rt.get("d"), "rand_p": rt.get("p"), "rand_n_cond": rt.get("n_cond")})
    t = pd.DataFrame(res)
    ok = t["p"].notna().to_numpy()
    t["bh_pass"] = False
    t.loc[ok, "bh_pass"] = bh(t.loc[ok, "p"].to_numpy(), 0.10)
    want = np.where(t["kind"] == "exclude", -1, 1)
    t["dir_ok"] = np.sign(t["d"]) == want

    def coins_ok(row):
        cd = row["coin_d"] if isinstance(row["coin_d"], dict) else {}
        same = sum(1 for v in cd.values() if np.sign(v) == np.sign(row["d"]))
        return same >= 4 and same > len(cd) / 2

    t["coins_ok"] = t.apply(coins_ok, axis=1)
    t["halves_ok"] = (np.sign(t["half1"]) == np.sign(t["d"])) & (np.sign(t["half2"]) == np.sign(t["d"]))
    t["pass"] = t["bh_pass"] & t["dir_ok"] & t["coins_ok"] & t["halves_ok"]
    # Step 7: the fix each rule implies, on all selection-window trades of that strategy (reviewed 60 included).
    fixes = []
    for short in STRATS.values():
        full = pd.read_pickle(os.path.join(out, f"feat_{short}.pkl"))
        base = full["net"]
        rules = t[t["strategy"] == short]
        for r in rules.itertuples():
            keep = _cond(full, r.expr)
            keep = ~keep if r.kind == "exclude" else keep
            k = full[keep]
            pc = k.groupby("symbol")["net"].mean()
            fixes.append({"strategy": short, "fix": r.rule, "passed_test": bool(t.loc[r.Index, "pass"]),
                          "n_before": len(full), "mean_before": float(base.mean()), "win_before": float((base > 0).mean()),
                          "n_after": len(k), "mean_after": float(k["net"].mean()), "win_after": float((k["net"] > 0).mean()),
                          "coins_positive": int((pc > 0).sum())})
        passed = rules[t.loc[rules.index, "pass"]]
        if len(passed) >= 2:
            keep = np.ones(len(full), bool)
            for r in passed.itertuples():
                c = _cond(full, r.expr)
                keep &= ~c if r.kind == "exclude" else c
            k = full[keep]
            pc = k.groupby("symbol")["net"].mean()
            fixes.append({"strategy": short, "fix": "+".join(passed["rule"]), "passed_test": True,
                          "n_before": len(full), "mean_before": float(base.mean()), "win_before": float((base > 0).mean()),
                          "n_after": len(k), "mean_after": float(k["net"].mean()), "win_after": float((k["net"] > 0).mean()),
                          "coins_positive": int((pc > 0).sum())})
    fx = pd.DataFrame(fixes)
    fx["lockable"] = fx["passed_test"] & (fx["mean_after"] > 0) & (fx["n_after"] >= 100) & (fx["coins_positive"] >= 4)
    rdir = os.path.join(ROOT, "research", "chart_review", "out")
    os.makedirs(rdir, exist_ok=True)
    t.assign(coin_d=t["coin_d"].map(json.dumps)).to_csv(os.path.join(rdir, "rule_tests.csv"), index=False)
    fx.to_csv(os.path.join(rdir, "fixes.csv"), index=False)
    pd.set_option("display.width", 250)
    cols = ["strategy", "rule", "kind", "n_cond", "n_rest", "mean_cond", "mean_rest", "d", "p", "bh_pass", "dir_ok",
            "coins_ok", "halves_ok", "pass", "half1", "half2", "rand_d", "rand_p"]
    print(t[cols].to_string())
    print(t[["rule", "coin_d"]].to_string())
    print(fx.to_string())


if __name__ == "__main__":
    {"build": build, "calib": calib, "test": test}[sys.argv[1]](sys.argv[2])
