#!/usr/bin/env python3
"""Analysis of a paperbot results export (rb_export.py zip, extracted).

    python3 -I analyze.py <extracted_dir> <out_dir> [--repo /home/user/crypto-bot-research] [--ref fiveyear_ref.csv]
                          [--procs 4] [--boot 10000] [--tz-hours 9] [--no-replay] [--brackets FILE]

<extracted_dir> holds one folder per run (run-<UTC stamp>/ ... current/), each with the CSVs of rb_export.py; any
file may be missing. Nothing is written outside <out_dir>; the repository is only imported (paperbot.daily3._alone,
make_signal, _bar_of; paperbot.obsshadows.symbol_steps; paperbot.engine.PaperEngine; paperbot.config.v3_settings;
paperbot.margin), never modified.

Every output table is described in the "Tables" section of <out_dir>/summary.md.
"""

from __future__ import annotations

import argparse
import bisect
import collections
import json
import math
import os
import site
import sys
import time

sys.dont_write_bytecode = True          # importing the repo's modules must never write .pyc files into it
us = site.getusersitepackages()
if us not in sys.path:
    sys.path.append(us)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

REPO_DEFAULT = "/home/user/crypto-bot-research"
MIN, HOUR, DAY = 60_000, 3_600_000, 86_400_000
TF_MIN = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
TF_ORDER = ["5m", "15m", "30m", "1h", "4h", "1d"]
SLIP = 0.0002
TAKER_DEFAULT = 0.0005
EQUITY0 = 5000.0
GROUP_OF_KIND = {"strategy": "core", "random": "flip", "ds200": "ds200", "reel": "reel", "copy": "extra",
                 "newlab": "extra"}

# Leverage brackets inferred from the export's own trades (liq_price, margin, qty, entry of every trade without
# funding fit Binance's isolated liquidation formula exactly with these (mmr, cum) per notional tier; "bracket
# allows 40x" texts in outcomes give the 40x tiers). Format: (notional_cap, max_leverage, mmr, cum). max_leverage
# 50 means "50x was seen to pass" (the rules never try more). Override with --brackets (Binance leverageBracket JSON).
INFERRED_BRACKETS = {
    "BTCUSDT": [(1e12, 50, 0.004, 0.0)],
    "ETHUSDT": [(1e12, 50, 0.004, 0.0)],
    "SOLUSDT": [(50_000, 50, 0.005, 0.0), (1e12, 50, 0.0065, 75.0)],
    "DOGEUSDT": [(80_000, 50, 0.0065, 0.0), (1e12, 50, 0.01, 280.0)],
    "BCHUSDT": [(10_000, 50, 0.005, 0.0), (100_000, 50, 0.01, 50.0), (1e12, 40, 0.0125, 300.0)],
    "LTCUSDT": [(10_000, 50, 0.005, 0.0), (50_000, 50, 0.01, 50.0), (1e12, 40, 0.015, 300.0)],
}

LOG: list[str] = []


def log(msg: str) -> None:
    LOG.append(msg)
    print(msg, flush=True)


# =============================================================================== small helpers
def jload(s) -> dict:
    if isinstance(s, dict):
        return s
    try:
        v = json.loads(s) if isinstance(s, str) and s else {}
    except (TypeError, ValueError):
        return {}
    return v if isinstance(v, dict) else {}


def fnum(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return float("nan")
    return v


def mix(series, top: int = 8) -> str:
    vals = series.tolist() if hasattr(series, "tolist") else list(series)
    c = collections.Counter(v for v in vals if v is not None and v == v)
    return " ".join(f"{k}:{v}" for k, v in c.most_common(top))


def max_consec(flags) -> int:
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f else 0
        best = max(best, cur)
    return best


def bh(p, q: float = 0.05) -> tuple[np.ndarray, np.ndarray]:
    """Benjamini-Hochberg: (reject at q, adjusted q-values)."""
    p = np.asarray(p, float)
    n = len(p)
    if n == 0:
        return np.zeros(0, bool), np.zeros(0)
    order = np.argsort(p)
    ranked = p[order] * n / np.arange(1, n + 1)
    qv = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(n)
    out[order] = np.minimum(qv, 1.0)
    return out <= q, out


def md_table(df: pd.DataFrame, cols=None, n: int = 30, floatfmt: str = "{:.3g}") -> str:
    if df is None or len(df) == 0:
        return "_(none)_\n"
    d = df[[c for c in cols if c in df.columns]] if cols else df
    d = d.head(n)
    head = "| " + " | ".join(str(c) for c in d.columns) + " |"
    sep = "|" + "|".join("---" for _ in d.columns) + "|"
    lines = [head, sep]
    for _, r in d.iterrows():
        cells = []
        for v in r.values:
            if isinstance(v, (float, np.floating)):
                cells.append("" if v != v else floatfmt.format(v))
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def kst(ms, tzh: float) -> pd.Series:
    return pd.to_datetime(pd.Series(ms, dtype="float64") + tzh * HOUR, unit="ms")


def fmt_ts(ms, tzh: float = 9) -> str:
    if ms is None or ms != ms:
        return ""
    return pd.Timestamp(int(ms) + int(tzh * HOUR), unit="ms").strftime("%m/%d %H:%M")


# =============================================================================== loading
def _read(path: str, **kw) -> pd.DataFrame | None:
    if not os.path.exists(path):
        return None
    try:
        return pd.read_csv(path, **kw)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def discover(root: str) -> list[str]:
    runs = []
    for name in os.listdir(root):
        p = os.path.join(root, name)
        if os.path.isdir(p) and any(os.path.exists(os.path.join(p, f"{f}.csv")) for f in ("accounts", "trades",
                                                                                          "outcomes")):
            runs.append(name)
    runs.sort(key=lambda n: (n == "current", n))
    return runs


def load_ctx_strength(path: str) -> dict:
    """{signal_log id: ctx dict with only "strength"} (the leverage group of quality_v1 reads nothing else)."""
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            ctx = d.get("ctx")
            if isinstance(ctx, dict) and "strength" in ctx:
                out[int(d.get("id"))] = {"strength": ctx["strength"]}
    return out


def infer_kind(aid: str) -> str:
    s = aid.split("@")[0]
    if s.startswith("RANDOM_"):
        return "random"
    if s.startswith("REEL"):
        return "reel"
    if s[:1] == "F" and "_" in s and s.split("_")[0][1:].isdigit():
        return "ds200"
    if "~c" in aid:
        return "copy"
    if s.startswith("NL"):
        return "newlab"
    return "strategy"


class Run:
    def __init__(self, root: str, name: str):
        self.name = name
        self.path = os.path.join(root, name)
        p = lambda f: os.path.join(self.path, f)  # noqa: E731
        self.files = sorted(os.listdir(self.path))
        self.acc = _read(p("accounts.csv"))
        self.trades = _read(p("trades.csv"))
        self.out = _read(p("outcomes.csv"))
        self.sig = _read(p("signal_log.csv"))
        self.bars = _read(p("live_bars.csv"))
        self.fills = _read(p("fill_costs.csv"))
        self.eqh = _read(p("equity_hourly.csv"))
        self.runs = _read(p("runs.csv"))
        self.alerts = _read(p("alerts.csv"))
        self.sh = _read(p("d3_shadows.csv"))
        self.rep = _read(p("d3_reports.csv"))
        self.slips = _read(p("d3_stop_slips.csv"))
        self.ctx_path = p("signal_ctx.jsonl")
        self._accounts()

    # ---------------------------------------------------------------- accounts
    def _accounts(self) -> None:
        cols = ["account_id", "strategy", "timeframe", "kind", "created_ts", "settings_version", "parent", "data"]
        acc = self.acc if self.acc is not None and len(self.acc) else pd.DataFrame(columns=cols)
        acc = acc.copy()
        ids = set(acc["account_id"])
        extra = set()
        for df in (self.trades, self.out):
            if df is not None and len(df):
                extra |= set(df["account_id"].unique()) - ids
        rows = []
        for aid in sorted(extra):
            s, _, tf = aid.partition("@")
            rows.append({"account_id": aid, "strategy": s, "timeframe": tf.split("~")[0], "kind": infer_kind(aid),
                         "created_ts": np.nan, "settings_version": "", "parent": None, "data": "{}"})
        if rows:
            acc = pd.concat([acc, pd.DataFrame(rows)], ignore_index=True)
        dd = acc["data"].map(jload)
        acc["group"] = [d.get("group") or GROUP_OF_KIND.get(k, "other") for d, k in zip(dd, acc["kind"])]
        acc["exits"] = [d.get("exits") or ("reel" if k == "reel" else "house") for d, k in zip(dd, acc["kind"])]
        self.accounts = acc.drop(columns=["data"])
        self.version = (acc["settings_version"].replace("", np.nan).dropna().mode().iloc[0]
                        if acc["settings_version"].replace("", np.nan).notna().any() else "?")

    # ---------------------------------------------------------------- time span
    def span(self) -> tuple[float, float]:
        lo = [self.accounts["created_ts"].min()]
        hi = []
        for df, c in ((self.trades, "exit_time"), (self.sig, "bar_close"), (self.bars, "ts"), (self.out, "step_ts")):
            if df is not None and len(df):
                lo.append(df[c].min())
                hi.append(df[c].max())
        lo = [x for x in lo if x == x]
        return (min(lo) if lo else np.nan, max(hi) if hi else np.nan)


# =============================================================================== settings / brackets / specs
def detect_rule(run: Run) -> str:
    t = run.trades
    if t is not None and len(t) and "tier" in t:
        tiers = set(t["tier"].dropna().astype(str))
        if tiers & {"good", "base"}:
            return "tier_walk"
        if "normal" in tiers:
            return "quality_v1"
    return "quality_v1" if "v4" in str(run.version) or run.name >= "run-20261005T1" else "tier_walk"


def implied_taker(run: Run) -> float:
    t = run.trades
    if t is None or not len(t):
        return TAKER_DEFAULT
    g = t[t["exit_reason"].isin(["SL", "LOCK", "TIME"])]
    if not len(g):
        return TAKER_DEFAULT
    v = (g["fees"] / (g["qty"] * (g["entry_price"] + g["exit_price"]))).median()
    return float(round(v, 7)) if v == v else TAKER_DEFAULT


def infer_specs(trades: pd.DataFrame) -> dict:
    out = {}
    if trades is None or not len(trades):
        return out
    for s, g in trades.groupby("symbol"):
        q = g["qty"].to_numpy(float)
        step = 0.0
        for k in range(-2, 9):
            if np.all(np.abs(q * 10.0 ** k - np.round(q * 10.0 ** k)) < 1e-6 * np.maximum(1, q * 10.0 ** k)):
                step = 10.0 ** -k
                break
        out[s] = {"qty_step": step, "min_notional": 5.0}
    return out


def make_brackets(path: str | None):
    from paperbot.margin import BracketTier, Brackets
    if path:
        with open(path) as fh:
            payload = json.load(fh)
        return {p["symbol"]: Brackets.from_binance(p) for p in payload}, f"file {path}"
    return ({s: Brackets([BracketTier(*t) for t in tiers]) for s, tiers in INFERRED_BRACKETS.items()},
            "inferred from export trades (INFERRED_BRACKETS)")


def check_brackets(trades: pd.DataFrame, brackets) -> pd.DataFrame:
    """Recorded liq_price vs the bracket table for trades without funding (funding moves the liq price)."""
    from paperbot.margin import liquidation_price
    rows = []
    t = trades[(trades["funding"] == 0) & trades["symbol"].isin(list(brackets))]
    for s, g in t.groupby("symbol"):
        err = []
        for r in g.itertuples():
            b = brackets[s].for_notional(r.qty * r.entry_price)
            lp = liquidation_price(int(r.side), r.qty, r.entry_price, r.margin, b)
            err.append(abs(lp / r.liq_price - 1) if r.liq_price else np.nan)
        err = np.array(err)
        rows.append({"symbol": s, "n_trades_no_funding": len(err), "max_rel_err": np.nanmax(err),
                     "share_within_1e-6": float(np.mean(err < 1e-6))})
    return pd.DataFrame(rows)


def replay_settings(rule: str, taker: float):
    from paperbot.config import DEFAULT_TIERS, v3_settings
    if rule == "tier_walk":
        return v3_settings(leverage_rule="tier_walk", tiers=DEFAULT_TIERS, max_margin_frac=0.40, taker_fee=taker)
    return v3_settings(taker_fee=taker)


# =============================================================================== trades
def enrich_trades(run: Run, tzh: float, taker: float) -> pd.DataFrame:
    t = run.trades
    if t is None or not len(t):
        return pd.DataFrame()
    t = t.copy()
    t.insert(0, "run", run.name)
    acc = run.accounts.set_index("account_id")
    t["kind"] = t["account_id"].map(acc["kind"]).fillna(t["account_id"].map(infer_kind))
    t["group"] = t["account_id"].map(acc["group"])
    t["exits"] = t["account_id"].map(acc["exits"]).fillna("house")
    t["strategy"] = t["account_id"].map(acc["strategy"]).fillna(t["strategy_id"])
    t["tf"] = t["account_id"].map(acc["timeframe"]).fillna(t["timeframe"])
    # ---- initial stop: stop_initial -> the ENTERED outcome's signal stop -> stop_price (not after a lock) -> 2 ATR
    si = pd.to_numeric(t["stop_initial"], errors="coerce")
    ok = si.notna() & (si > 0) & ((t["entry_price"] - si) * t["side"] > 0)
    t["stop_src"] = np.where(ok, "stop_initial", "")
    stop = si.where(ok)
    if (~ok).any() and run.out is not None and len(run.out):
        e = run.out[run.out["status"] == "ENTERED"][["account_id", "sig_ts", "symbol", "sig_stop_price", "sig_atr"]]
        e = e.drop_duplicates(["account_id", "sig_ts", "symbol"])
        m = t[["account_id", "signal_ts", "symbol"]].merge(e, left_on=["account_id", "signal_ts", "symbol"],
                                                           right_on=["account_id", "sig_ts", "symbol"], how="left")
        cand = pd.to_numeric(m["sig_stop_price"], errors="coerce").to_numpy()
        good = (~ok.to_numpy()) & np.isfinite(cand) & ((t["entry_price"].to_numpy() - cand) * t["side"].to_numpy() > 0)
        stop = stop.where(~good, cand)
        t.loc[good, "stop_src"] = "outcome_signal"
        ok = stop.notna()
        sp = pd.to_numeric(t["stop_price"], errors="coerce")
        lock_null = t["lock_roe"].isna() if "lock_roe" in t else True
        good2 = (~ok) & sp.notna() & (t["exit_reason"] != "LOCK") & lock_null & ((t["entry_price"] - sp) * t["side"] > 0)
        stop = stop.where(~good2, sp)
        t.loc[good2, "stop_src"] = "stop_price"
        ok = stop.notna()
        atr = pd.to_numeric(m["sig_atr"], errors="coerce").to_numpy()
        good3 = (~ok.to_numpy()) & np.isfinite(atr)
        stop = stop.where(~good3, t["entry_price"] - t["side"] * 2 * atr)
        t.loc[good3, "stop_src"] = "2atr_from_signal"
    t["stop_ref"] = stop
    t["stop_dist"] = (t["entry_price"] - t["stop_ref"]).abs()
    t["stop_frac"] = t["stop_dist"] / t["entry_price"]
    t["risk_usd"] = t["qty"] * t["stop_dist"]
    t["R"] = t["pnl"] / t["risk_usd"]
    t["gross"] = t["pnl"] + t["fees"] + t["funding"]
    t["cost_usd"] = t["fees"] + t["funding"]
    slip_exit = np.where(t["exit_reason"].isin(["TP", "LIQ"]), 0.0, SLIP * t["qty"] * t["exit_price"])
    t["slip_est_usd"] = SLIP * t["qty"] * t["entry_price"] + slip_exit
    t["cost_R"] = t["cost_usd"] / t["risk_usd"]
    t["cost_all_R"] = (t["cost_usd"] + t["slip_est_usd"]) / t["risk_usd"]
    t["rt_cost_over_stop"] = 2 * (taker + SLIP) * t["entry_price"] / t["stop_dist"]
    t["mfe_R"] = t["side"] * (t["mfe_price"] - t["entry_price"]) / t["stop_dist"]
    t["mae_R"] = t["side"] * (t["mae_price"] - t["entry_price"]) / t["stop_dist"]
    t["hold_min"] = (t["exit_time"] - t["entry_time"]) / MIN
    t["eq_before"] = t["equity_after"] - t["pnl"]
    t["margin_frac"] = t["margin"] / t["eq_before"]
    t["roe_per_lev"] = t["roe"] / t["leverage"]
    t["win"] = t["pnl"] > 0
    ent = kst(t["entry_time"], tzh)
    ex = kst(t["exit_time"], tzh)
    t["entry_day"] = ent.dt.strftime("%Y-%m-%d").values
    t["exit_day"] = ex.dt.strftime("%Y-%m-%d").values
    t["exit_hour"] = ex.dt.hour.values
    t["entry_hour"] = ent.dt.hour.values
    if "context" in t:
        cx = t["context"].map(jload)
        t["regime"] = cx.map(lambda c: c.get("regime"))
        t["htf_regime"] = cx.map(lambda c: c.get("htf_regime"))
        t = t.drop(columns=["context"])
    return t.sort_values(["account_id", "exit_time", "id"]).reset_index(drop=True)


def trade_stats(g: pd.DataFrame) -> dict:
    n = len(g)
    if n == 0:
        return {"n": 0}
    R = g["R"].to_numpy(float)
    Rv = R[np.isfinite(R)]
    pnl = g["pnl"].to_numpy(float)
    wins = int((pnl > 0).sum())
    wR, lR = Rv[Rv > 0], Rv[Rv <= 0]
    pos, neg = pnl[pnl > 0].sum(), pnl[pnl <= 0].sum()
    long_, short = g[g["side"] > 0], g[g["side"] < 0]
    gross_abs = g["gross"].abs().sum()
    d = {
        "n": n, "wins": wins, "win_pct": 100 * wins / n, "pnl_sum": pnl.sum(), "mean_pnl": pnl.mean(),
        "mean_roe": g["roe"].mean(), "median_roe": g["roe"].median(),
        "mean_R": Rv.mean() if len(Rv) else np.nan, "median_R": np.median(Rv) if len(Rv) else np.nan,
        "sd_R": Rv.std(ddof=1) if len(Rv) > 1 else np.nan,
        "avg_win_R": wR.mean() if len(wR) else np.nan, "avg_loss_R": lR.mean() if len(lR) else np.nan,
        "payoff": (wR.mean() / -lR.mean()) if len(wR) and len(lR) and lR.mean() < 0 else np.nan,
        "profit_factor": (pos / -neg) if neg < 0 else (np.inf if pos > 0 else np.nan),
        "expectancy_R": ((len(wR) / len(Rv)) * (wR.mean() if len(wR) else 0)
                         + (len(lR) / len(Rv)) * (lR.mean() if len(lR) else 0)) if len(Rv) else np.nan,
        "n_R_missing": int(n - len(Rv)),
        "exit_mix": mix(g["exit_reason"]),
        "long_n": len(long_), "long_mean_R": long_["R"].mean() if len(long_) else np.nan,
        "long_pnl": long_["pnl"].sum(), "short_n": len(short),
        "short_mean_R": short["R"].mean() if len(short) else np.nan, "short_pnl": short["pnl"].sum(),
        "fees_sum": g["fees"].sum(), "funding_sum": g["funding"].sum(),
        "cost_share_of_abs_gross": g["cost_usd"].sum() / gross_abs if gross_abs > 0 else np.nan,
        "mean_cost_R": g["cost_R"].mean(), "mean_cost_all_R": g["cost_all_R"].mean(),
        "mean_mfe_R": g["mfe_R"].mean(), "median_mfe_R": g["mfe_R"].median(), "mean_mae_R": g["mae_R"].mean(),
        "mean_hold_min": g["hold_min"].mean(), "median_hold_min": g["hold_min"].median(),
        "max_consec_losses": max_consec((pnl <= 0).tolist()),
        "mean_lev": g["leverage"].mean(), "lev_mix": mix(g["leverage"].astype(int)),
        "mean_roe_per_lev": g["roe_per_lev"].mean(), "mean_stop_frac": g["stop_frac"].mean(),
        "coins": g["symbol"].nunique(), "best_trade_pnl": pnl.max(), "worst_trade_pnl": pnl.min(),
    }
    return d


def realized_dd(g: pd.DataFrame) -> tuple[float, float, float]:
    """(max drawdown fraction, max drawdown $, final equity) from the equity_after sequence (exit order)."""
    if not len(g):
        return np.nan, np.nan, np.nan
    g = g.sort_values(["exit_time", "id"])
    start = float(g["eq_before"].iloc[0])
    eq = np.concatenate([[start], g["equity_after"].to_numpy(float)])
    peak = np.maximum.accumulate(eq)
    dd = 1 - eq / peak
    return float(dd.max()), float((peak - eq).max()), float(eq[-1])


# =============================================================================== (a) account stats
def account_tables(runs: list[Run], T: pd.DataFrame, tzh: float):
    rows = []
    for run in runs:
        tr = T[T["run"] == run.name] if len(T) else T
        by = {a: g for a, g in tr.groupby("account_id")} if len(tr) else {}
        eqh = run.eqh
        hdd = {}
        if eqh is not None and len(eqh):
            g = eqh.groupby("account_id")
            hdd = pd.DataFrame({"hourly_dd_max": g["dd_max"].max(), "eq_min_hourly": g["eq_min"].min(),
                                "eq_max_hourly": g["eq_max"].max(), "eq_hours": g["hour_ts"].nunique()})
        for a in run.accounts.itertuples():
            g = by.get(a.account_id, pd.DataFrame())
            d = {"run": run.name, "version": run.version, "account_id": a.account_id, "kind": a.kind,
                 "group": a.group, "exits": a.exits, "strategy": a.strategy, "timeframe": a.timeframe,
                 "created_kst": fmt_ts(a.created_ts, tzh)}
            d.update(trade_stats(g))
            mdd, mdd_usd, fin = realized_dd(g) if len(g) else (np.nan, np.nan, np.nan)
            d.update(realized_max_dd=mdd, realized_max_dd_usd=mdd_usd, final_equity_realized=fin)
            if len(hdd) and a.account_id in hdd.index:
                d.update(hdd.loc[a.account_id].to_dict())
            rows.append(d)
    A = pd.DataFrame(rows)
    # pooled per (kind, strategy, tf)
    prow = []
    if len(T):
        for (k, s, tf), g in T.groupby(["kind", "strategy", "tf"]):
            d = {"kind": k, "strategy": s, "timeframe": tf, "runs_with_trades": g["run"].nunique()}
            for r in runs:
                d[f"n_{r.name}"] = int((g["run"] == r.name).sum())
            d.update(trade_stats(g.sort_values(["run", "exit_time"])))
            sub = A[(A["kind"] == k) & (A["strategy"] == s) & (A["timeframe"] == tf)]
            d["worst_realized_dd_any_run"] = sub["realized_max_dd"].max()
            d["worst_hourly_dd_any_run"] = sub["hourly_dd_max"].max() if "hourly_dd_max" in sub else np.nan
            prow.append(d)
    P = pd.DataFrame(prow)
    # coin split
    C = pd.DataFrame()
    if len(T):
        C = (T.groupby(["run", "account_id", "kind", "strategy", "tf", "symbol"])
             .agg(n=("R", "size"), wins=("win", "sum"), mean_R=("R", "mean"), mean_roe=("roe", "mean"),
                  pnl=("pnl", "sum")).reset_index())
        Cp = (T.groupby(["kind", "strategy", "tf", "symbol"])
              .agg(n=("R", "size"), wins=("win", "sum"), mean_R=("R", "mean"), mean_roe=("roe", "mean"),
                   pnl=("pnl", "sum")).reset_index())
        Cp.insert(0, "run", "ALL")
        Cp.insert(1, "account_id", Cp["strategy"] + "@" + Cp["tf"])
        C = pd.concat([C, Cp], ignore_index=True)
        C["win_pct"] = 100 * C["wins"] / C["n"]
    # run x kind x tf overview
    K = pd.DataFrame()
    if len(T):
        rows = []
        for (r, k, ex, tf), g in T.groupby(["run", "kind", "exits", "tf"]):
            d = {"run": r, "kind": k, "exits": ex, "timeframe": tf, "accounts_with_trades": g["account_id"].nunique()}
            d.update(trade_stats(g))
            rows.append(d)
        for (k, ex, tf), g in T.groupby(["kind", "exits", "tf"]):
            d = {"run": "ALL", "kind": k, "exits": ex, "timeframe": tf,
                 "accounts_with_trades": g["account_id"].nunique()}
            d.update(trade_stats(g))
            rows.append(d)
        K = pd.DataFrame(rows)
    return A, P, C, K


# =============================================================================== (b) coin-flip comparison
def boot_mean(obs: np.ndarray, pool: np.ndarray, B: int, rng) -> dict:
    n = len(obs)
    m_obs = float(obs.mean())
    means = np.empty(B)
    chunk = max(1, int(4e6 // max(n, 1)))
    for s in range(0, B, chunk):
        k = min(chunk, B - s)
        means[s:s + k] = pool[rng.integers(0, len(pool), size=(k, n))].mean(axis=1)
    eps = 1e-9 * max(1.0, abs(m_obs))
    p = (1 + int((means >= m_obs - eps).sum())) / (B + 1)
    pw = (1 + int((means <= m_obs + eps).sum())) / (B + 1)
    pct = 100 * (float((means < m_obs).mean()) + 0.5 * float((means == m_obs).mean()))
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {"mean_R": m_obs, "rand_boot_mean": float(means.mean()), "rand_boot_p2.5": lo, "rand_boot_p97.5": hi,
            "percentile": pct, "p_one_sided": p, "p_worse_one_sided": pw}


MIN_N_TEST = 5        # trades of the tested cell
MIN_POOL = 20         # coin-flip trades in the pool


def coinflip(T: pd.DataFrame, B: int, seed: int = 20261007) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Each non-random cell's mean R against n-trade bootstrap draws from the coin-flip trades of the same timeframe
    and exit type (house / reel). Tested only with n >= MIN_N_TEST and a pool >= MIN_POOL trades (with fewer the
    bootstrap null is degenerate)."""
    if not len(T):
        return pd.DataFrame(), pd.DataFrame()
    rng = np.random.default_rng(seed)
    T = T[np.isfinite(T["R"])]
    rnd = T[T["kind"] == "random"]
    test = T[T["kind"] != "random"]
    z = 1.6449 + 0.8416      # one-sided 5%, power 80%

    def one(g, pool, extra):
        pool_R = pool["R"].to_numpy(float)
        d = dict(extra)
        d.update(n=len(g), mean_R=g["R"].mean(), rand_pool_n=len(pool_R),
                 rand_pool_accounts=pool["account_id"].nunique() if len(pool) else 0,
                 rand_pool_mean_R=pool_R.mean() if len(pool_R) else np.nan,
                 rand_pool_sd_R=pool_R.std(ddof=1) if len(pool_R) > 1 else np.nan,
                 mean_roe=g["roe"].mean(), rand_pool_mean_roe=pool["roe"].mean() if len(pool) else np.nan)
        d["diff_R"] = d["mean_R"] - d["rand_pool_mean_R"]
        d["mde_R_80pct"] = z * d["rand_pool_sd_R"] / math.sqrt(len(g)) if len(pool_R) > 1 else np.nan
        d["low_power"] = bool(len(g) < 30 or not (abs(d["diff_R"]) >= d["mde_R_80pct"]))
        if len(pool_R) < MIN_POOL or len(g) < MIN_N_TEST:
            d["note"] = f"not tested: n {len(g)} (< {MIN_N_TEST}?) / pool {len(pool_R)} (< {MIN_POOL}?)"
            return d
        d.update(boot_mean(g["R"].to_numpy(float), pool_R, B, rng))
        return d

    rows = []
    for (k, s, tf, ex), g in test.groupby(["kind", "strategy", "tf", "exits"]):
        pool = rnd[(rnd["tf"] == tf) & (rnd["exits"] == ex)]
        rows.append(one(g, pool, {"kind": k, "strategy": s, "timeframe": tf, "exits": ex,
                                  "runs": " ".join(sorted(g["run"].unique()))}))
    P = pd.DataFrame(rows)
    rows = []
    for (r, a, k, s, tf, ex), g in test.groupby(["run", "account_id", "kind", "strategy", "tf", "exits"]):
        pool = rnd[(rnd["tf"] == tf) & (rnd["exits"] == ex) & (rnd["run"] == r)]
        rows.append(one(g, pool, {"run": r, "account_id": a, "kind": k, "strategy": s, "timeframe": tf, "exits": ex}))
    R = pd.DataFrame(rows)
    for D in (P, R):
        if len(D) and "p_one_sided" in D:
            m = D["p_one_sided"].notna()
            rej, q = bh(D.loc[m, "p_one_sided"].to_numpy(), 0.05)
            D.loc[m, "bh_q"] = q
            D.loc[m, "bh_reject_0.05"] = rej
            rej2, q2 = bh(D.loc[m, "p_worse_one_sided"].to_numpy(), 0.05)
            D.loc[m, "bh_q_worse"] = q2
            D.loc[m, "bh_reject_worse_0.05"] = rej2
    return P, R


# =============================================================================== (c1) entered + d3 skipped shadows
def parse_shadows(run: Run) -> pd.DataFrame:
    sh = run.sh
    if sh is None or not len(sh):
        return pd.DataFrame()
    sh = sh.drop_duplicates("key").copy()
    parts = sh["key"].str.split("|", expand=True)
    sh["aid"] = parts[1]
    sh["bc"] = pd.to_numeric(parts[3], errors="coerce")
    sh["run"] = run.name
    return sh


def every_signal_shadow(runs: list[Run], T: pd.DataFrame, SH: dict) -> pd.DataFrame:
    rows = []
    for run in runs:
        acc = run.accounts.set_index("account_id")
        sh = SH.get(run.name, pd.DataFrame())
        sk = sh[sh["kind"] == "skipped"] if len(sh) else pd.DataFrame(columns=["aid", "roe", "resolved", "day"])
        days = sorted(sk["day"].unique()) if len(sk) else []
        tr = T[T["run"] == run.name] if len(T) else pd.DataFrame(columns=["account_id"])
        n_skipped_out = (run.out["status"] == "SKIPPED").groupby(run.out["account_id"]).sum() \
            if run.out is not None and len(run.out) else pd.Series(dtype=float)
        for aid in sorted(set(tr["account_id"]) | set(sk["aid"])):
            g = tr[tr["account_id"] == aid]
            s = sk[sk["aid"] == aid]
            sr = s[s["roe"].notna()]
            k = acc["kind"].get(aid, infer_kind(aid))
            roe_all = pd.Series(np.concatenate([g["roe"].to_numpy(float), sr["roe"].to_numpy(float)]))
            rows.append({"run": run.name, "account_id": aid, "kind": k, "strategy": aid.split("@")[0],
                         "timeframe": aid.split("@")[-1], "shadow_days": " ".join(days),
                         "n_entered": len(g), "mean_roe_entered": g["roe"].mean(),
                         "n_skipped_outcomes": int(n_skipped_out.get(aid, 0)),
                         "n_skipped_shadow": len(s), "n_skipped_resolved": int((s["resolved"] == 1).sum()),
                         "n_skipped_no_trade": int(((s["resolved"] == 1) & s["roe"].isna()).sum()),
                         "mean_roe_skipped": sr["roe"].mean(),
                         "win_pct_skipped": 100 * (sr["roe"] > 0).mean() if len(sr) else np.nan,
                         "n_all": len(roe_all), "mean_roe_all": roe_all.mean(),
                         "win_pct_all": 100 * (roe_all > 0).mean() if len(roe_all) else np.nan})
    D = pd.DataFrame(rows)
    if len(D):
        P = D.groupby(["kind", "strategy", "timeframe"]).apply(
            lambda x: pd.Series({"n_entered": x["n_entered"].sum(), "n_skipped_shadow_roe": (x["n_skipped_resolved"] - x["n_skipped_no_trade"]).sum(),
                                 "mean_roe_all": np.average(x["mean_roe_all"].fillna(0), weights=x["n_all"]) if x["n_all"].sum() else np.nan,
                                 "n_all": x["n_all"].sum()}), include_groups=False).reset_index()
        P.insert(0, "run", "ALL")
        D = pd.concat([D, P], ignore_index=True)
    return D


# =============================================================================== (c2) replay of every signal
_G: dict = {}


def _sim(d: dict) -> dict:
    """One signal alone through the repo's engine (daily3._alone on obsshadows.symbol_steps)."""
    from paperbot.daily3 import _alone, make_signal
    from paperbot.engine import PaperEngine
    G = _G
    sym = d["symbol"]
    ss = G["ssteps"].get(sym)
    if ss is None or sym not in G["brackets"]:
        return {"status": "NO_BARS_SYMBOL"}
    ts_list = G["ts_list"]
    i0 = bisect.bisect_left(ts_list, d["bar_close"])
    if i0 >= len(ts_list):
        return {"status": "NO_BARS_AFTER"}
    out = {"gap_min": (ts_list[i0] - d["bar_close"]) / MIN}
    if out["gap_min"] > 5:
        out["status"] = "BARS_GAP"
        return out
    try:
        sig = make_signal(d)
    except Exception as exc:  # noqa: BLE001
        out["status"] = f"BAD_SIGNAL {type(exc).__name__}"
        return out
    S = G["settings"]
    tr, resolved = _alone(S, G["brackets"], G["specs"], sig, ss, i0)
    out["bars_left"] = len(ts_list) - i0
    if tr is not None:
        dist = abs(tr.entry_price - tr.stop_initial) if tr.stop_initial else np.nan
        out.update(status="TRADED", entry_time=tr.entry_time, exit_time=tr.exit_time, exit_reason=tr.exit_reason,
                   leverage=tr.leverage, tier=tr.tier, entry_price=tr.entry_price, stop_initial=tr.stop_initial,
                   qty=tr.qty, margin=tr.margin, roe=tr.roe, pnl=tr.pnl, fees=tr.fees, funding=tr.funding,
                   R=tr.pnl / (tr.qty * dist) if dist else np.nan,
                   stop_frac=dist / tr.entry_price if dist else np.nan,
                   mfe_R=tr.side * (tr.mfe_price - tr.entry_price) / dist if dist else np.nan,
                   mae_R=tr.side * (tr.mae_price - tr.entry_price) / dist if dist else np.nan,
                   hold_min=(tr.exit_time - tr.entry_time) / MIN, roe_per_lev=tr.roe / tr.leverage)
        return out
    if resolved:
        first = ss[i0][1].get(sym)
        out["status"] = "REJECTED_NO_BAR" if first is None else "REJECTED_SIZING"
        if first is not None:
            e = PaperEngine(S, G["brackets"], symbol_specs=G["specs"], book="why")
            e.submit(sig)
            e.step(ss[i0][1], ss[i0][2])
            if e.outcomes:
                out["reject_reasons"] = " | ".join(e.outcomes[0].detail.get("reasons") or [e.outcomes[0].reason])
        return out
    # unresolved: the position is still open at the last bar; mark it to the last close (exit costs included)
    e = PaperEngine(S, G["brackets"], symbol_specs=G["specs"], book="mark")
    e.submit(sig)
    for ts, bars, fund in ss[i0:]:
        e.step(bars, fund)
    p = e.position
    out["status"] = "UNRESOLVED"
    if p is not None:
        last = e._last_mark.get(sym, p.entry_price)
        px = last * (1 - p.side * S.slippage_frac)
        net = p.side * p.qty * (px - p.entry_price) - p.entry_fee - p.qty * px * S.taker_fee - p.funding_paid
        dist = abs(p.entry_price - p.stop_initial)
        out.update(entry_time=p.entry_time, leverage=p.leverage, tier=p.tier, entry_price=p.entry_price,
                   stop_initial=p.stop_initial, qty=p.qty, margin=p.margin_initial,
                   mark_roe=net / p.margin_initial, mark_R=net / (p.qty * dist) if dist else np.nan,
                   lock_roe=p.lock_roe)
    return out


def _replay_one(i: int) -> dict:
    d = _G["sigs"][i]
    out = {k: d[k] for k in ("sig_id", "bar_close", "timeframe", "strategy", "symbol", "side", "atr", "ref_price")}
    if d.get("not_replayable"):
        out["status"] = d["not_replayable"]
        return out
    out.update(_sim(d))
    # side flip (the timing-matched coin flip): the same signal with the other side, the same leverage group
    if _G.get("flip") and out.get("status") in ("TRADED", "UNRESOLVED"):
        d2 = dict(d)
        d2["side"] = -int(d["side"])
        data = {}
        if _G["settings"].leverage_rule == "quality_v1" and out.get("tier") in ("best", "normal"):
            data["lev_group"] = out["tier"]
        d2["data"] = data
        f = _sim(d2)
        for k in ("status", "exit_reason", "leverage", "roe", "R", "mark_R", "exit_time"):
            if k in f:
                out[f"flip_{k}"] = f[k]
    return out


def _replay_chunk(idx: list[int]) -> list[dict]:
    return [_replay_one(i) for i in idx]


def infer_funding(trades: pd.DataFrame, bars: pd.DataFrame, period_h: int = 8) -> tuple[dict, dict]:
    """{ts: {symbol: rate}} at the funding instants, solved from the trades' recorded funding:
    funding = side x qty x mark_open(ft) x rate for every funding instant ft with entry_time < ft <= exit_time
    (engine.step pays funding first, on the bar's mark open). Single-instant trades first, then trades with one
    unknown instant left. Returns (rates, info)."""
    info = {"funding_trades": 0, "funding_instants_solved": 0, "funding_trades_unexplained": 0}
    if trades is None or not len(trades) or bars is None or not len(bars):
        return {}, info
    P = period_h * HOUR
    mk = {}
    for r in bars.itertuples(index=False):
        m = r.mark_open if r.mark_open == r.mark_open else r.open
        mk[(int(r.ts), r.symbol)] = float(m)
    f = trades[trades["funding"] != 0]
    info["funding_trades"] = len(f)
    items = []
    for r in f.itertuples(index=False):
        fts = [x for x in range((int(r.entry_time) // P + 1) * P, int(r.exit_time) + 1, P) if x > r.entry_time]
        if not fts:
            info["funding_trades_unexplained"] += 1
            continue
        items.append((r.symbol, int(r.side), float(r.qty), float(r.funding), fts))
    known: dict = {}
    for _ in range(4):
        cand = collections.defaultdict(list)
        for sym, side, qty, fund, fts in items:
            unk = [ft for ft in fts if (ft, sym) not in known]
            if len(unk) != 1 or (unk[0], sym) not in mk:
                continue
            rest = sum(side * qty * mk.get((ft, sym), np.nan) * known[(ft, sym)] for ft in fts if ft != unk[0])
            cand[(unk[0], sym)].append((fund - rest) / (side * qty * mk[(unk[0], sym)]))
        if not cand:
            break
        for k, v in cand.items():
            known[k] = float(np.median(v))
    info["funding_instants_solved"] = len(known)
    rates: dict = {}
    for (ft, sym), rate in known.items():
        if rate == rate:
            rates.setdefault(ft, {})[sym] = rate
    return rates, info


def build_steps(bars: pd.DataFrame, funding: dict | None = None):
    from paperbot.daily3 import _bar_of
    from paperbot.obsshadows import symbol_steps
    bars = bars.sort_values(["ts", "symbol"])
    cols = list(bars.columns)
    by_ts: dict = {}
    for row in bars.itertuples(index=False):
        r = dict(zip(cols, row))
        for k in ("mark_open", "mark_high", "mark_low", "mark_close", "volume", "close_time"):
            v = r.get(k)
            if v is not None and isinstance(v, float) and v != v:
                r[k] = None
        by_ts.setdefault(int(r["ts"]), {})[r["symbol"]] = _bar_of(r)
    ts_list = sorted(by_ts)
    funding = funding or {}
    steps = [(t, by_ts[t], dict(funding.get(t, {}))) for t in ts_list]
    syms = sorted(bars["symbol"].unique())
    return ts_list, {s: symbol_steps(steps, s) for s in syms}


def replay_run(run: Run, settings, brackets, specs, procs: int, funding: bool = True,
               flip: bool = True) -> tuple[pd.DataFrame, dict]:
    info = {"run": run.name}
    if run.bars is None or not len(run.bars) or run.sig is None or not len(run.sig):
        info["note"] = "no live_bars.csv (or no signal_log): replay not possible"
        return pd.DataFrame(), info
    t0 = time.time()
    rates, finfo = infer_funding(run.trades, run.bars) if funding else ({}, {"funding": "off"})
    info.update(finfo)
    ts_list, ssteps = build_steps(run.bars, rates)
    info["bars_minutes"] = len(ts_list)
    info["bars_first_kst"], info["bars_last_kst"] = fmt_ts(ts_list[0]), fmt_ts(ts_list[-1])
    missing = (ts_list[-1] - ts_list[0]) // MIN + 1 - len(ts_list)
    info["bars_missing_minutes"] = int(missing)
    strength = load_ctx_strength(run.ctx_path)
    acc = run.accounts.set_index("account_id")
    sub = run.sig[run.sig["status"] == "SUBMITTED"]
    sigs = []
    for r in sub.itertuples(index=False):
        aid = f"{r.strategy}@{r.timeframe}"
        d = {"sig_id": int(r.id), "bar_close": int(r.bar_close), "timeframe": r.timeframe, "strategy": r.strategy,
             "symbol": r.symbol, "side": int(r.side), "atr": fnum(r.atr), "ref_price": fnum(r.ref_price),
             "ref_time": int(r.ref_time) if r.ref_time == r.ref_time else None,
             "delay_ms": int(r.delay_ms) if r.delay_ms == r.delay_ms else None}
        ctx = strength.get(int(r.id))
        d["data"] = {"ctx": ctx} if ctx else {}
        if acc["exits"].get(aid, "house") == "reel":
            d["not_replayable"] = "NOT_REPLAYABLE_REEL (reel levels not in the export)"
        elif not (d["atr"] == d["atr"] and d["atr"] > 0 and d["ref_price"] == d["ref_price"]):
            d["not_replayable"] = "NO_ATR_OR_REF"
        sigs.append(d)
    _G.clear()
    _G.update(sigs=sigs, ssteps=ssteps, ts_list=ts_list, settings=settings, brackets=brackets, specs=specs, flip=flip)
    info["prep_s"] = round(time.time() - t0, 2)
    t1 = time.time()
    idx = list(range(len(sigs)))
    if procs > 1 and len(idx) > 200:
        import multiprocessing as mp
        chunks = [idx[k::procs * 4] for k in range(procs * 4)]
        with mp.get_context("fork").Pool(procs) as pool:
            parts = pool.map(_replay_chunk, chunks)
        res = [x for p in parts for x in p]
    else:
        res = _replay_chunk(idx)
    dt = time.time() - t1
    info.update(signals=len(sigs), replay_s=round(dt, 2), procs=procs, side_flip=flip,
                s_per_1000_signals=round(1000 * dt / max(len(sigs), 1), 2),
                cpu_s_per_1000_signals=round(1000 * dt * (procs if procs > 1 and len(idx) > 200 else 1)
                                             / max(len(sigs), 1), 2))
    R = pd.DataFrame(res).sort_values("sig_id")
    R.insert(0, "run", run.name)
    R["account_id"] = R["strategy"] + "@" + R["timeframe"]
    R["kind"] = R["account_id"].map(acc["kind"]).fillna(R["account_id"].map(infer_kind))
    # the account's own outcome for this signal and its actual trade (parity check)
    if run.out is not None and len(run.out):
        o = run.out[["account_id", "sig_ts", "symbol", "status", "reason"]].drop_duplicates(
            ["account_id", "sig_ts", "symbol"]).rename(columns={"status": "acct_status", "reason": "acct_reason"})
        R["sig_ts"] = R["bar_close"] - 1
        R = R.merge(o, on=["account_id", "sig_ts", "symbol"], how="left")
    if run.trades is not None and len(run.trades):
        a = run.trades[["account_id", "signal_ts", "symbol", "roe", "leverage", "exit_reason", "exit_time",
                        "funding"]].rename(
            columns={"signal_ts": "sig_ts", "roe": "acct_roe", "leverage": "acct_leverage",
                     "exit_reason": "acct_exit_reason", "exit_time": "acct_exit_time", "funding": "acct_funding"})
        R = R.merge(a.drop_duplicates(["account_id", "sig_ts", "symbol"]), on=["account_id", "sig_ts", "symbol"],
                    how="left")
    return R, info


def replay_stats(RP: pd.DataFrame) -> pd.DataFrame:
    if not len(RP):
        return pd.DataFrame()

    def st(g):
        tr = g[g["status"] == "TRADED"]
        Rv = tr["R"].dropna().to_numpy(float)
        wR, lR = Rv[Rv > 0], Rv[Rv <= 0]
        return pd.Series({
            "n_submitted": len(g), "n_traded": len(tr), "n_rejected_sizing": int((g["status"] == "REJECTED_SIZING").sum()),
            "n_unresolved": int((g["status"] == "UNRESOLVED").sum()),
            "n_not_replayable": int(g["status"].str.startswith(("NOT_REPLAYABLE", "NO_", "BARS_GAP", "BAD", "REJECTED_NO_BAR")).sum()),
            "win_pct": 100 * (tr["roe"] > 0).mean() if len(tr) else np.nan,
            "mean_roe": tr["roe"].mean(), "mean_roe_per_lev": tr["roe_per_lev"].mean(),
            "mean_R": Rv.mean() if len(Rv) else np.nan, "median_R": np.median(Rv) if len(Rv) else np.nan,
            "sd_R": Rv.std(ddof=1) if len(Rv) > 1 else np.nan,
            "t_R": Rv.mean() / (Rv.std(ddof=1) / math.sqrt(len(Rv))) if len(Rv) > 2 and Rv.std(ddof=1) > 0 else np.nan,
            "avg_win_R": wR.mean() if len(wR) else np.nan, "avg_loss_R": lR.mean() if len(lR) else np.nan,
            "payoff": wR.mean() / -lR.mean() if len(wR) and len(lR) and lR.mean() < 0 else np.nan,
            "pf_R": wR.sum() / -lR.sum() if lR.sum() < 0 else np.nan,
            "exit_mix": mix(tr["exit_reason"]), "lev_mix": mix(tr["leverage"].dropna().astype(int)),
            "mean_hold_min": tr["hold_min"].mean(),
            "mean_R_entered_signals": tr.loc[tr.get("acct_status", pd.Series(dtype=str)) == "ENTERED", "R"].mean()
            if "acct_status" in tr else np.nan,
            "mean_R_skipped_signals": tr.loc[tr.get("acct_status", pd.Series(dtype=str)) == "SKIPPED", "R"].mean()
            if "acct_status" in tr else np.nan,
            "mean_mark_R_unresolved": g.loc[g["status"] == "UNRESOLVED", "mark_R"].mean() if "mark_R" in g else np.nan,
        })
    a = RP.groupby(["run", "kind", "strategy", "timeframe"]).apply(st, include_groups=False).reset_index()
    b = RP.groupby(["kind", "strategy", "timeframe"]).apply(st, include_groups=False).reset_index()
    b.insert(0, "run", "ALL")
    c = RP.groupby(["run", "kind", "timeframe"]).apply(st, include_groups=False).reset_index()
    c.insert(2, "strategy", "*")
    return pd.concat([a, b, c], ignore_index=True)


def replay_parity(RP: pd.DataFrame) -> pd.DataFrame:
    if not len(RP) or "acct_roe" not in RP:
        return pd.DataFrame()
    rows = []
    for (run, kind), g in RP.groupby(["run", "kind"]):
        e = g[(g.get("acct_status") == "ENTERED") & g["acct_roe"].notna()]
        both = e[e["status"] == "TRADED"]
        diff = (both["roe"] - both["acct_roe"]).abs()
        rows.append({"run": run, "kind": kind, "entered_closed_signals": len(e), "replayed_traded": len(both),
                     "replay_not_traded": int((e["status"] != "TRADED").sum()),
                     "replay_status_of_those": mix(e.loc[e["status"] != "TRADED", "status"]),
                     "roe_equal_1e-6": int((diff < 1e-6).sum()), "roe_within_0.01": int((diff < 0.01).sum()),
                     "median_abs_roe_diff": diff.median(), "max_abs_roe_diff": diff.max(),
                     "same_exit_reason": int((both["exit_reason"] == both["acct_exit_reason"]).sum()),
                     "same_leverage": int((both["leverage"] == both["acct_leverage"]).sum()),
                     "same_exit_time": int((both["exit_time"] == both["acct_exit_time"]).sum()),
                     "mean_roe_replay": both["roe"].mean(), "mean_roe_actual": both["acct_roe"].mean(),
                     "mismatch_gt_1e-6": int((diff >= 1e-6).sum()),
                     "mismatch_with_funding": int(((diff >= 1e-6) & (both.get("acct_funding", 0) != 0)).sum()),
                     "mismatch_without_funding": int(((diff >= 1e-6) & (both.get("acct_funding", 0) == 0)).sum()),
                     "mean_R_replay": both["R"].mean()})
    return pd.DataFrame(rows)


def sideflip_test(RP: pd.DataFrame, B: int, seed: int = 20261008) -> pd.DataFrame:
    """Timing-matched coin flip: every replayed signal is also replayed with the other side (same bar, coin, ATR
    stop, leverage group). Under 'no directional skill' the chosen side is a fair coin given the signal, so the
    statistic sum(R_chosen - R_other) / 2n has a sign-flip randomization distribution (B draws). excess_R =
    mean(R_chosen) - mean((R_chosen + R_other) / 2) = what the strategy's side choice added over a coin flip at the
    same moments. Pairs need both sides TRADED (unresolved / rejected are left out).
    Signals close in time are not independent (several coins at one bar, overlapping trades), so the signs are flipped
    per cluster = (run, bar_close floored to max(timeframe, 1h)): every signal of a cluster gets the same random sign
    (conservative). p_better_indep flips every signal on its own (the plain coin-flipper null), for reference."""
    if not len(RP) or "flip_R" not in RP:
        return pd.DataFrame()
    rng = np.random.default_rng(seed)
    x = RP[(RP["status"] == "TRADED") & (RP.get("flip_status") == "TRADED")].copy()
    x = x[np.isfinite(x["R"]) & np.isfinite(x["flip_R"])]
    blk = np.maximum(x["timeframe"].map(TF_MIN).fillna(60).to_numpy() * MIN, HOUR)
    x["_cl"] = x["run"].astype(str) + "|" + (x["bar_close"].to_numpy() // blk).astype(np.int64).astype(str)
    rows = []

    def flips(vals, n, obs):
        m = len(vals)
        sims = np.empty(B)
        chunk = max(1, int(4e6 // max(m, 1)))
        for s0 in range(0, B, chunk):
            k = min(chunk, B - s0)
            sims[s0:s0 + k] = (vals[None, :] * rng.choice((-1.0, 1.0), size=(k, m))).sum(axis=1) / n
        eps = 1e-9 * max(1.0, abs(obs))          # the same sum computed two ways differs by rounding
        return (1 + int((sims >= obs - eps).sum())) / (B + 1), (1 + int((sims <= obs + eps).sum())) / (B + 1)

    def one(g, keys):
        d = dict(keys)
        n = len(g)
        h = 0.5 * (g["R"].to_numpy(float) - g["flip_R"].to_numpy(float))
        d.update(n_pairs=n, mean_R_chosen=g["R"].mean(), mean_R_other_side=g["flip_R"].mean(),
                 coinflip_expect_R=0.5 * (g["R"].mean() + g["flip_R"].mean()), excess_R=h.mean() if n else np.nan,
                 share_chosen_better=float((h > 0).mean()) if n else np.nan,
                 long_share=float((g["side"] > 0).mean()) if n else np.nan)
        cl = pd.Series(h).groupby(g["_cl"].to_numpy()).sum().to_numpy() if n else np.zeros(0)
        d["n_clusters"] = len(cl)
        if n >= 5 and len(cl) >= 5 and np.any(h != 0):
            obs = h.mean()
            d["p_better"], d["p_worse"] = flips(cl, n, obs)
            d["p_better_indep"], _ = flips(h, n, obs)
            # detectable excess at 80% power with the cluster-level spread
            d["mde_excess_R_80pct"] = 2.486 * math.sqrt((cl ** 2).sum()) / n
        else:
            d["note"] = "n < 5, clusters < 5 or no difference: not tested"
        return d
    for (k, s, tf), g in x.groupby(["kind", "strategy", "timeframe"]):
        rows.append(one(g, {"level": "strategy_tf", "kind": k, "strategy": s, "timeframe": tf}))
    for (k, tf), g in x.groupby(["kind", "timeframe"]):
        rows.append(one(g, {"level": "kind_tf", "kind": k, "strategy": "*", "timeframe": tf}))
    for k, g in x.groupby("kind"):
        rows.append(one(g, {"level": "kind", "kind": k, "strategy": "*", "timeframe": "*"}))
    D = pd.DataFrame(rows)
    m = (D["level"] == "strategy_tf") & D["p_better"].notna() if "p_better" in D else pd.Series(False, index=D.index)
    if m.any():
        r1, q1 = bh(D.loc[m, "p_better"].to_numpy(), 0.05)
        r2, q2 = bh(D.loc[m, "p_worse"].to_numpy(), 0.05)
        D.loc[m, "bh_q_better"], D.loc[m, "bh_reject_better_0.05"] = q1, r1
        D.loc[m, "bh_q_worse"], D.loc[m, "bh_reject_worse_0.05"] = q2, r2
    return D


# =============================================================================== (d) signal flow
def sizing_category(reasons: list) -> str:
    if not reasons:
        return "unknown"
    last = str(reasons[-1])
    if "too close to liq" in last:
        return "stop_too_close_to_liq"
    if "stop loss" in last and "of equity" in last:
        return "loss_at_stop_gt_15pct"
    if "bracket allows" in last:
        return "bracket"
    if "minimum order" in last:
        return "below_min_order"
    if "wrong side" in last:
        return "stop_wrong_side"
    if "no equity" in last:
        return "no_equity"
    return "other"


def signal_flow(runs: list[Run], T: pd.DataFrame):
    rows, rej_rows = [], []
    for run in runs:
        sl = run.sig if run.sig is not None else pd.DataFrame(columns=["strategy", "timeframe", "status"])
        sl_aid = sl["strategy"] + "@" + sl["timeframe"] if len(sl) else pd.Series(dtype=str)
        scount = sl.assign(aid=sl_aid).groupby(["aid", "status"]).size().unstack(fill_value=0) if len(sl) else pd.DataFrame()
        o = run.out if run.out is not None else pd.DataFrame(columns=["account_id", "status", "reason", "detail"])
        cat = pd.Series(index=o.index, dtype=object)
        if len(o):
            cat = o["status"] + ":" + o["reason"].fillna("").map(
                lambda r: "in position" if r == "in position" else "lower score" if r.startswith("lower score")
                else "sizing" if r == "sizing" else r.split(":")[0] if r else "")
        ocount = o.assign(cat=cat).groupby(["account_id", "cat"]).size().unstack(fill_value=0) if len(o) else pd.DataFrame()
        # sizing rejections: categories and an example
        if len(o):
            rz = o[(o["status"] == "REJECTED") & (o["reason"] == "sizing")]
            for r in rz.itertuples():
                det = jload(r.detail)
                rs = det.get("reasons") or []
                rej_rows.append({"run": run.name, "account_id": r.account_id, "symbol": r.symbol,
                                 "sig_ts": r.sig_ts, "category": sizing_category(rs),
                                 "candidates": len(rs), "reasons": " | ".join(map(str, rs)),
                                 "stop_dist_frac": (r.stop_dist / r.ref_price) if r.ref_price == r.ref_price and r.ref_price
                                 else np.nan})
        ntr = T[T["run"] == run.name].groupby("account_id").size() if len(T) else pd.Series(dtype=int)
        for a in run.accounts.itertuples():
            aid = a.account_id
            sc = scount.loc[aid] if aid in scount.index else pd.Series(dtype=int)
            oc = ocount.loc[aid] if aid in ocount.index else pd.Series(dtype=int)
            d = {"run": run.name, "account_id": aid, "kind": a.kind, "strategy": a.strategy, "timeframe": a.timeframe}
            for s in ("SUBMITTED", "RECORD", "LATE", "NO_PRICE", "NO_ATR"):
                d[f"sig_{s}"] = int(sc.get(s, 0))
            d["outcomes"] = int(oc.sum()) if len(oc) else 0
            for c in oc.index:
                d[f"out_{c}"] = int(oc[c])
            d["trades"] = int(ntr.get(aid, 0))
            d["entered"] = int(sum(v for k, v in oc.items() if k.startswith("ENTERED")))
            d["open_at_end"] = d["entered"] - d["trades"]
            rows.append(d)
    F = pd.DataFrame(rows).fillna(0)
    for c in F.columns:
        if c.startswith(("sig_", "out_")):
            F[c] = F[c].astype(int)
    rej = pd.DataFrame(rej_rows)

    def cause(r):
        if r["trades"] > 0:
            return ""
        if r["entered"] > 0:
            return "open_position_at_end (entered, never closed)"
        sub = r["sig_SUBMITTED"]
        if sub == 0 and r["outcomes"] == 0:
            if r["sig_LATE"] > 0:
                return "late_only (signals arrived late: LATE)"
            if r["sig_NO_PRICE"] + r["sig_NO_ATR"] > 0:
                return "no_price_or_atr"
            if r["sig_RECORD"] > 0:
                return "record_only (signals only on non-traded coins)"
            return "no_signal_at_all"
        rejs = r.get("out_REJECTED:sizing", 0)
        if r["outcomes"] > 0 and rejs == r["outcomes"]:
            return "all_rejected_by_sizing (leverage range / stop distance)"
        other_rej = sum(v for k, v in r.items() if isinstance(k, str) and k.startswith("out_REJECTED:")
                        and k != "out_REJECTED:sizing")
        if r["outcomes"] > 0 and rejs + other_rej == r["outcomes"]:
            return "all_rejected (guard / halted / no bar / reel / sizing)"
        if r["outcomes"] == 0:
            return "submitted_but_no_outcome (pending at the end?)"
        return "other: " + ", ".join(f"{k[4:]}={v}" for k, v in r.items()
                                     if isinstance(k, str) and k.startswith("out_") and v)
    F["zero_trade_cause"] = F.apply(cause, axis=1)
    return F, rej


# =============================================================================== (e) duplicates
def dup_tables(runs: list[Run], T: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    pair_rows, group_rows = [], []

    def scan(level: str, run: str, sets: dict, kinds: dict):
        inv = collections.defaultdict(list)
        for a, s in sets.items():
            for k in s:
                inv[k].append(a)
        common = collections.Counter()
        for lst in inv.values():
            if 1 < len(lst) <= 400:
                lst = sorted(lst)
                for i in range(len(lst)):
                    for j in range(i + 1, len(lst)):
                        common[(lst[i], lst[j])] += 1
        parent = {a: a for a in sets}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        for (a, b), c in common.items():
            na, nb = len(sets[a]), len(sets[b])
            ov = c / max(na, nb)
            if ov >= 0.9:
                trivial = max(na, nb) < 3
                pair_rows.append({"level": level, "run": run, "a": a, "b": b, "kind_a": kinds.get(a), "kind_b": kinds.get(b),
                                  "n_a": na, "n_b": nb, "common": c, "overlap_min": ov,
                                  "identical": c == na == nb, "trivial_lt3": trivial})
                if not trivial:
                    parent[find(a)] = find(b)
        comps = collections.defaultdict(list)
        for a in sets:
            comps[find(a)].append(a)
        k = 0
        for members in comps.values():
            if len(members) > 1:
                k += 1
                members = sorted(members)
                ns = [len(sets[m]) for m in members]
                ident = len({frozenset(sets[m]) for m in members}) == 1
                group_rows.append({"level": level, "run": run, "group": f"{level}-{run}-{k}", "size": len(members),
                                   "identical_all": ident, "n_min": min(ns), "n_max": max(ns),
                                   "kinds": mix([kinds.get(m) for m in members]),
                                   "members": " ".join(members)})
    for run in runs:
        kinds = dict(zip(run.accounts["account_id"], run.accounts["kind"]))
        tr = T[T["run"] == run.name] if len(T) else pd.DataFrame()
        if len(tr):
            sets = {a: set(zip(g["symbol"], g["entry_time"], g["side"])) for a, g in tr.groupby("account_id")}
            scan("trades", run.name, sets, kinds)
        if run.sig is not None and len(run.sig):
            s = run.sig[run.sig["status"].isin(["SUBMITTED", "LATE", "NO_PRICE", "NO_ATR"])]
            sets = {}
            for (st, tf), g in s.groupby(["strategy", "timeframe"]):
                sets[f"{st}@{tf}"] = set(zip(g["bar_close"], g["symbol"], g["side"]))
            scan("signals", run.name, sets, kinds)
    return pd.DataFrame(pair_rows), pd.DataFrame(group_rows)


# =============================================================================== (f) time clustering
def time_tables(T: pd.DataFrame):
    if not len(T):
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    keys = ["run", "account_id", "kind", "strategy", "tf"]
    D = T.groupby(keys + ["exit_day"]).agg(n=("pnl", "size"), wins=("win", "sum"), pnl=("pnl", "sum"),
                                           mean_R=("R", "mean")).reset_index()
    H = T.groupby(keys + ["exit_hour"]).agg(n=("pnl", "size"), pnl=("pnl", "sum"), mean_R=("R", "mean")).reset_index()
    HK = T.groupby(["run", "kind", "exit_hour"]).agg(n=("pnl", "size"), pnl=("pnl", "sum"), mean_R=("R", "mean"),
                                                     win_pct=("win", "mean")).reset_index()
    HK["win_pct"] *= 100
    rows = []
    for k, g in T.groupby(keys):
        tot = g["pnl"].sum()
        dd = g.groupby("exit_day")["pnl"].sum()
        best_day, worst_day = dd.max(), dd.min()
        bt = g["pnl"].max()
        rows.append({**dict(zip(keys, k)), "n": len(g), "pnl_total": tot, "days_traded": len(dd),
                     "positive_days": int((dd > 0).sum()), "best_day": dd.idxmax(), "best_day_pnl": best_day,
                     "best_day_share": best_day / tot if tot > 0 else np.nan,
                     "pnl_ex_best_day": tot - best_day, "best_trade_pnl": bt,
                     "best_trade_share": bt / tot if tot > 0 else np.nan, "pnl_ex_best_trade": tot - bt,
                     "worst_day_pnl": worst_day, "worst_day_share_of_loss": worst_day / tot if tot < 0 else np.nan,
                     "lucky_flag": bool(tot > 0 and (tot - bt) <= 0)})
    L = pd.DataFrame(rows)
    return D, H, HK, L


# =============================================================================== (g) market backdrop
def price_series(run: Run) -> tuple[pd.DataFrame, str]:
    if run.bars is not None and len(run.bars):
        b = run.bars[["ts", "symbol", "open", "high", "low", "close"]].copy()
        b["t"] = b["ts"] + MIN
        return b, "live_bars (1m)"
    parts = []
    if run.sig is not None and len(run.sig):
        s = run.sig[run.sig["ref_price"].notna()]
        parts.append(pd.DataFrame({"t": s["ref_time"], "symbol": s["symbol"], "close": s["ref_price"]}))
    if run.trades is not None and len(run.trades):
        tr = run.trades
        parts.append(pd.DataFrame({"t": tr["entry_time"], "symbol": tr["symbol"], "close": tr["entry_price"]}))
        parts.append(pd.DataFrame({"t": tr["exit_time"], "symbol": tr["symbol"], "close": tr["exit_price"]}))
    if not parts:
        return pd.DataFrame(), "none"
    p = pd.concat(parts).dropna().sort_values("t")
    p["open"] = p["high"] = p["low"] = p["close"]
    return p, "APPROX: signal ref prices + trade fills (no live_bars)"


def market_tables(runs: list[Run], T: pd.DataFrame, tzh: float):
    mrows, dayret = [], {}
    for run in runs:
        p, src = price_series(run)
        if not len(p):
            continue
        for s, g in p.groupby("symbol"):
            g = g.sort_values("t")
            c = g["close"].to_numpy(float)
            first = g["open"].iloc[0]
            peak = np.maximum.accumulate(c)
            trough = np.minimum.accumulate(c)
            idx = pd.to_datetime(g["t"], unit="ms")
            hourly = pd.Series(c, index=idx).resample("1h").last().dropna()
            hr = np.diff(np.log(hourly.to_numpy())) if len(hourly) > 2 else np.array([])
            if src.startswith("live"):
                lr = np.diff(np.log(c))
                rv_day = lr.std(ddof=1) * math.sqrt(1440) * 100 if len(lr) > 2 else np.nan
            else:
                rv_day = hr.std(ddof=1) * math.sqrt(24) * 100 if len(hr) > 2 else np.nan
            mrows.append({"run": run.name, "symbol": s, "source": src, "start_kst": fmt_ts(g["t"].iloc[0], tzh),
                          "end_kst": fmt_ts(g["t"].iloc[-1], tzh), "points": len(g), "first": first, "last": c[-1],
                          "return_pct": 100 * (c[-1] / first - 1), "high": g["high"].max(), "low": g["low"].min(),
                          "max_drawdown_pct": 100 * float((1 - c / peak).max()),
                          "max_runup_pct": 100 * float((c / trough - 1).max()),
                          "realized_vol_daily_pct": rv_day,
                          "up_hour_share": float((hr > 0).mean()) if len(hr) else np.nan,
                          "direction": "up" if c[-1] > first * 1.005 else "down" if c[-1] < first * 0.995 else "flat"})
            day = (pd.to_datetime(g["t"] + tzh * HOUR, unit="ms")).dt.strftime("%Y-%m-%d")
            dr = g.assign(day=day.values).groupby("day").agg(o=("open", "first"), c=("close", "last"))
            for dy, r in dr.iterrows():
                dayret[(run.name, s, dy)] = r["c"] / r["o"] - 1
    M = pd.DataFrame(mrows)
    if len(M):
        ew = M.groupby("run").agg(return_pct=("return_pct", "mean"), realized_vol_daily_pct=("realized_vol_daily_pct", "mean"),
                                  up_hour_share=("up_hour_share", "mean")).reset_index()
        ew["symbol"] = "EQUAL_WEIGHT_6"
        M = pd.concat([M, ew], ignore_index=True)
    # direction luck per account
    L = pd.DataFrame()
    if len(T) and len(M):
        runret = {(r.run, r.symbol): r.return_pct for r in M.itertuples()}
        t = T.copy()
        t["day_ret"] = [dayret.get((r, s, d), np.nan) for r, s, d in zip(t["run"], t["symbol"], t["entry_day"])]
        t["run_ret"] = [runret.get((r, s), np.nan) for r, s in zip(t["run"], t["symbol"])]
        t["aligned_day"] = np.sign(t["day_ret"]) * t["side"] > 0
        t["aligned_run"] = np.sign(t["run_ret"]) * t["side"] > 0
        rows = []
        for k, g in t.groupby(["run", "account_id", "kind", "strategy", "tf"]):
            al, ag = g[g["aligned_day"]], g[~g["aligned_day"]]
            d = dict(zip(["run", "account_id", "kind", "strategy", "tf"], k))
            d.update(n=len(g), long_share=float((g["side"] > 0).mean()), pnl=g["pnl"].sum(), mean_R=g["R"].mean(),
                     aligned_day_share=float(g["aligned_day"].mean()), aligned_run_share=float(g["aligned_run"].mean()),
                     mean_R_aligned_day=al["R"].mean(), mean_R_against_day=ag["R"].mean(),
                     pnl_aligned_day=al["pnl"].sum(), pnl_against_day=ag["pnl"].sum())
            d["direction_luck_flag"] = bool(len(g) >= 5 and d["pnl"] > 0 and d["aligned_day_share"] >= 0.7
                                            and not (d["mean_R_against_day"] > 0))
            rows.append(d)
        L = pd.DataFrame(rows)
    return M, L


# =============================================================================== (h) cost
def cost_table(T: pd.DataFrame) -> pd.DataFrame:
    if not len(T):
        return pd.DataFrame()
    rows = []
    for keys, g in list(T.groupby(["run", "kind", "tf"])) + [(("ALL", "*", tf), g) for tf, g in T.groupby("tf")]:
        x = g["rt_cost_over_stop"].dropna()
        rows.append({"run": keys[0], "kind": keys[1], "timeframe": keys[2], "n": len(g),
                     "median_stop_pct": 100 * g["stop_frac"].median(),
                     "rt_cost_over_stop_median": x.median(), "rt_cost_over_stop_mean": x.mean(),
                     "rt_cost_over_stop_p10": x.quantile(0.1), "rt_cost_over_stop_p90": x.quantile(0.9),
                     "actual_fee_funding_R_mean": g["cost_R"].mean(),
                     "actual_fee_funding_slip_R_mean": g["cost_all_R"].mean(),
                     "mean_R": g["R"].mean(), "mean_gross_R": (g["gross"] / g["risk_usd"]).mean()})
    return pd.DataFrame(rows)


# =============================================================================== d3 trade variants
VARIANT_NOTE = {
    "base": "control: the same signal alone, current rules (fresh $5,000 account, Binance final klines + funding)",
    "lock15": "first profit lock 15% instead of 10%", "lock20": "first lock 20%", "lock30": "first lock 30%",
    "timestop": "market exit after TIME_STOP_BARS bars of the tf if the lock never armed",
    "lev10": "fixed 10x, margin 20%, no fallback", "lev20": "fixed 20x, margin 20%",
    "lev30": "fixed 30x, margin 30%", "lev40": "fixed 40x, margin 40%", "lev50": "fixed 50x, margin 40%",
    "lev20m20": "fixed 20x, margin 20%", "lev30m30": "fixed 30x, margin 30%", "lev40m40": "fixed 40x, margin 40%",
    "lev50m50": "fixed 50x, margin 50%",
    "stopw1.5": "initial stop 1.5 ATR at the real trade's leverage (no 15%/liq checks)", "stopw2.5": "stop 2.5 ATR",
    "stopw3": "stop 3 ATR", "tp1R": "fixed TP at 1R (R = 2 ATR), no ladder, real leverage", "tp1.5R": "fixed TP 1.5R",
    "tp2R": "fixed TP 2R", "tp3R": "fixed TP 3R", "ladder_cap2R": "ladder plus exit at 2R",
    "quality": "sizing tier from entry strength (50x/40x best, 30x good, 20x base; tier walk)",
}


def variant_tables(runs: list[Run], T: pd.DataFrame, SH: dict):
    rows = []
    for run in runs:
        sh = SH.get(run.name, pd.DataFrame())
        if not len(sh):
            continue
        tv = sh[~sh["kind"].isin(["limit", "skipped"]) & ~sh["kind"].str.match(r"^stop\d")].copy()
        if not len(tv):
            continue
        dd = tv["data"].map(jload)
        tv["v_lev"] = dd.map(lambda d: d.get("leverage"))
        tv["v_pnl_eq"] = dd.map(lambda d: d.get("pnl_equity"))
        tv["actual_roe_d"] = dd.map(lambda d: d.get("actual_roe"))
        tv["k"] = tv["aid"] + "|" + tv["symbol"] + "|" + tv["bc"].astype("Int64").astype(str)
        base = tv[tv["kind"] == "base"].set_index("k")
        tr = T[T["run"] == run.name] if len(T) else pd.DataFrame()
        if len(tr):
            tk = tr["account_id"] + "|" + tr["symbol"] + "|" + (tr["signal_ts"] + 1).astype(str)
            trk = pd.DataFrame({"k": tk.values, "stop_frac": tr["stop_frac"].values, "t_roe": tr["roe"].values,
                                "t_lev": tr["leverage"].values, "kind_acct": tr["kind"].values,
                                "strategy": tr["strategy"].values}).drop_duplicates("k").set_index("k")
        else:
            trk = pd.DataFrame(columns=["stop_frac", "t_roe", "t_lev", "kind_acct", "strategy"])
        x = tv.join(base[["roe", "v_lev", "v_pnl_eq", "resolved"]].rename(
            columns={"roe": "b_roe", "v_lev": "b_lev", "v_pnl_eq": "b_pnl_eq", "resolved": "b_resolved"}), on="k")
        x = x.join(trk, on="k")
        x["v_R"] = x["roe"] / (pd.to_numeric(x["v_lev"], errors="coerce") * x["stop_frac"])
        x["b_R"] = x["b_roe"] / (pd.to_numeric(x["b_lev"], errors="coerce") * x["stop_frac"])
        x["run"] = run.name
        rows.append(x[["run", "kind", "aid", "symbol", "timeframe", "bc", "roe", "v_lev", "v_pnl_eq", "resolved",
                       "exit_reason", "b_roe", "b_lev", "b_pnl_eq", "b_resolved", "stop_frac", "t_roe", "t_lev",
                       "kind_acct", "strategy", "v_R", "b_R"]])
    if not rows:
        return pd.DataFrame(), pd.DataFrame()
    X = pd.concat(rows, ignore_index=True)
    X["kind_acct"] = X["kind_acct"].fillna(X["aid"].map(infer_kind))
    X["strategy"] = X["strategy"].fillna(X["aid"].str.split("@").str[0])

    # paired columns, then one vectorised aggregation per level
    X["v_pnl_eq"] = pd.to_numeric(X["v_pnl_eq"], errors="coerce")
    X["b_pnl_eq"] = pd.to_numeric(X["b_pnl_eq"], errors="coerce")
    pair = X["roe"].notna() & X["b_roe"].notna()
    X["_pair"] = pair.astype(int)
    X["_b_roe"] = X["b_roe"].where(pair)
    X["_v_roe"] = X["roe"].where(pair)
    X["_d_roe"] = X["_v_roe"] - X["_b_roe"]
    pr = pair & X["v_R"].notna() & X["b_R"].notna() & np.isfinite(X["v_R"]) & np.isfinite(X["b_R"])
    X["_b_R"] = X["b_R"].where(pr)
    X["_v_R"] = X["v_R"].where(pr)
    X["_d_R"] = X["_v_R"] - X["_b_R"]
    pe = pair & X["v_pnl_eq"].notna() & X["b_pnl_eq"].notna()
    X["_b_pe"] = X["b_pnl_eq"].where(pe)
    X["_v_pe"] = X["v_pnl_eq"].where(pe)
    X["_d_pe"] = X["_v_pe"] - X["_b_pe"]
    X["_ne"] = ((X["resolved"] == 1) & X["roe"].isna()).astype(int)
    X["_un"] = (X["resolved"] == 0).astype(int)
    X["_better"] = (X["_d_roe"] > 1e-12).astype(float).where(pair)
    X["_same"] = (X["_d_roe"].abs() <= 1e-12).astype(float).where(pair)

    def agg(keys):
        g = X.groupby(keys)
        a = g.agg(rows=("roe", "size"), n_pairs=("_pair", "sum"), variant_not_entered=("_ne", "sum"),
                  variant_unresolved=("_un", "sum"), mean_roe_base=("_b_roe", "mean"),
                  mean_roe_variant=("_v_roe", "mean"), diff_roe=("_d_roe", "mean"), _sd_roe=("_d_roe", "std"),
                  _n_roe=("_d_roe", "count"), mean_R_base=("_b_R", "mean"), mean_R_variant=("_v_R", "mean"),
                  diff_R=("_d_R", "mean"), _sd_R=("_d_R", "std"), _n_R=("_d_R", "count"),
                  mean_pnl_eq_base=("_b_pe", "mean"), mean_pnl_eq_variant=("_v_pe", "mean"),
                  diff_pnl_eq=("_d_pe", "mean"), share_variant_better_roe=("_better", "mean"),
                  share_variant_same_roe=("_same", "mean")).reset_index()
        with np.errstate(divide="ignore", invalid="ignore"):
            a["t_diff_roe"] = np.where((a["_n_roe"] > 2) & (a["_sd_roe"] > 0),
                                       a["diff_roe"] / (a["_sd_roe"] / np.sqrt(a["_n_roe"])), np.nan)
            a["t_diff_R"] = np.where((a["_n_R"] > 2) & (a["_sd_R"] > 0),
                                     a["diff_R"] / (a["_sd_R"] / np.sqrt(a["_n_R"])), np.nan)
        return a.drop(columns=["_sd_roe", "_n_roe", "_sd_R", "_n_R"])
    parts = [agg(["run", "kind", "timeframe"]).assign(level="run_tf"),
             agg(["kind", "timeframe"]).assign(run="ALL", level="tf"),
             agg(["kind"]).assign(run="ALL", timeframe="*", level="all"),
             agg(["kind_acct", "kind"]).assign(run="ALL", timeframe="*", level="account_kind"),
             agg(["kind_acct", "timeframe", "kind"]).assign(run="ALL", level="account_kind_tf"),
             agg(["kind_acct", "strategy", "timeframe", "kind"]).assign(run="ALL", level="strategy_tf")]
    em = X.groupby(["kind_acct", "kind"])["exit_reason"].agg(mix).rename("variant_exit_mix").reset_index()
    parts[3] = parts[3].merge(em, on=["kind_acct", "kind"], how="left")
    X.drop(columns=[c for c in X.columns if c.startswith("_")], inplace=True)
    V = pd.concat(parts, ignore_index=True).rename(columns={"kind": "variant"})
    V["variant_meaning"] = V["variant"].map(VARIANT_NOTE)
    first = ["level", "run", "kind_acct", "strategy", "timeframe", "variant"]
    V = V[[c for c in first if c in V] + [c for c in V.columns if c not in first]]
    return V, X


def stop_whatif_losers(SH: dict, T: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name, sh in SH.items():
        if not len(sh):
            continue
        s = sh[sh["kind"].str.match(r"^stop\d")].copy()
        if not len(s):
            continue
        s["actual_roe"] = s["data"].map(lambda d: jload(d).get("actual_roe"))
        for (k, tf), g in list(s.groupby(["kind", "timeframe"])) + [((k, "*"), g) for k, g in s.groupby("kind")]:
            p = g[g["roe"].notna() & g["actual_roe"].notna()]
            rows.append({"run": name, "variant": k, "timeframe": tf, "rows": len(g), "n_pairs": len(p),
                         "not_entered": int(((g["resolved"] == 1) & g["roe"].isna()).sum()),
                         "unresolved": int((g["resolved"] == 0).sum()),
                         "mean_actual_roe": p["actual_roe"].mean(), "mean_variant_roe": p["roe"].mean(),
                         "share_variant_better": float((p["roe"] > p["actual_roe"]).mean()) if len(p) else np.nan,
                         "note": "LOSING trades only (selection on the base outcome): biased toward the variant"})
    return pd.DataFrame(rows)


def limit_table(SH: dict, T: pd.DataFrame, RP: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name, sh in SH.items():
        if not len(sh):
            continue
        L = sh[sh["kind"] == "limit"].copy()
        if not len(L):
            continue
        L["k"] = L["aid"] + "|" + L["symbol"] + "|" + L["bc"].astype("Int64").astype(str)
        ref = pd.Series(dtype=float)
        if len(RP):
            r = RP[(RP["run"] == name) & (RP["status"] == "TRADED")]
            ref = pd.Series(r["roe"].values, index=(r["account_id"] + "|" + r["symbol"] + "|" + r["bar_close"].astype(str)).values)
            ref = ref[~ref.index.duplicated()]
        L["market_roe_replay"] = L["k"].map(ref)
        L["kind_acct"] = L["aid"].map(infer_kind)
        for (ka, tf), g in list(L.groupby(["kind_acct", "timeframe"])) + [(("*", "*"), L)]:
            f = g[g["filled"] == 1]
            fr = f[f["roe"].notna()]
            pr = fr[fr["market_roe_replay"].notna()]
            rows.append({"run": name, "kind": ka, "timeframe": tf, "signals": len(g), "filled": len(f),
                         "fill_rate": len(f) / len(g) if len(g) else np.nan, "filled_with_roe": len(fr),
                         "mean_roe_limit_filled": fr["roe"].mean(),
                         "n_paired_with_market_replay": len(pr),
                         "mean_roe_market_same_signals": pr["market_roe_replay"].mean(),
                         "mean_roe_limit_same_signals": pr["roe"].mean()})
    return pd.DataFrame(rows)


# =============================================================================== 5-year comparison
def vs_fiveyear(ref_path: str, P: pd.DataFrame, RS: pd.DataFrame, runs: list[Run], SPANS: dict) -> pd.DataFrame:
    if not ref_path or not os.path.exists(ref_path):
        return pd.DataFrame()
    ref = pd.read_csv(ref_path)
    prof = ref[ref["source"] == "profiles_binance"].set_index(["strategy", "timeframe"])
    ds = ref[ref["source"] == "deepseek200"]
    dsx = {v: ds[ds["variant"] == v].set_index(["strategy", "timeframe"]) for v in ds["variant"].unique()}
    # live signal frequency (SUBMITTED + LATE + NO_* per day over the run spans)
    freq = collections.Counter()
    days_of = collections.Counter()          # (strategy, tf) -> days of the runs that had that account
    for run in runs:
        lo, hi = SPANS[run.name]
        if run.sig is None or not len(run.sig) or lo != lo:
            continue
        days = (hi - lo) / DAY
        for st, tf in zip(run.accounts["strategy"], run.accounts["timeframe"]):
            days_of[(st, tf)] += days
        s = run.sig[run.sig["status"].isin(["SUBMITTED", "LATE", "NO_PRICE", "NO_ATR", "RECORD"])]
        s = s[s["symbol"] != "XRPUSDT"]
        for (st, tf), n in s.groupby(["strategy", "timeframe"]).size().items():
            freq[(st, tf, run.name)] += n
    rows = []
    keys = set()
    if len(P):
        keys |= set(zip(P["kind"], P["strategy"], P["timeframe"]))
    if len(RS):
        a = RS[(RS["run"] == "ALL")]
        keys |= set(zip(a["kind"], a["strategy"], a["timeframe"]))
    for k, s, tf in sorted(keys):
        if k not in ("strategy", "ds200"):
            continue
        d = {"kind": k, "strategy": s, "timeframe": tf}
        p = P[(P["kind"] == k) & (P["strategy"] == s) & (P["timeframe"] == tf)] if len(P) else []
        if len(p):
            p = p.iloc[0]
            d.update(live_trades=p["n"], live_win_pct=p["win_pct"], live_mean_roe=p["mean_roe"],
                     live_mean_ret_notional=p["mean_roe_per_lev"], live_mean_R=p["mean_R"], live_mean_lev=p["mean_lev"])
        r = RS[(RS["run"] == "ALL") & (RS["kind"] == k) & (RS["strategy"] == s) & (RS["timeframe"] == tf)] if len(RS) else []
        if len(r):
            r = r.iloc[0]
            d.update(replay_signals_traded=r["n_traded"], replay_win_pct=r["win_pct"], replay_mean_roe=r["mean_roe"],
                     replay_mean_ret_notional=r["mean_roe_per_lev"], replay_mean_R=r["mean_R"])
        nsig = sum(v for (st, t2, _), v in freq.items() if st == s and t2 == tf)
        dd_ = days_of.get((s, tf), 0.0)
        d["live_days"] = dd_
        d["live_signals_per_day"] = nsig / dd_ if dd_ else np.nan
        if k == "strategy" and (s, tf) in prof.index:
            q = prof.loc[(s, tf)]
            d.update(ref5y_source="profiles_binance (every signal alone, tier_walk leverage)",
                     ref5y_signals_per_day=q["per_day"], ref5y_mean_roe=q["mean_roe"],
                     ref5y_mean_ret_notional=q["mean_ret_notional"], ref5y_win_pct=100 * q["win_rate"],
                     ref5y_mean_lev=q["mean_lev"], ref5y_sized_share=q["sized_share"],
                     ref5y_acct_k2_cf_mean_roe=q.get("acct_k2_cf_mean_roe"))
        elif k == "ds200":
            d["ref5y_source"] = "deepseek200 results.csv (PREREG exits, unlevered)"
            for v, tb in dsx.items():
                if (s, tf) in tb.index:
                    q = tb.loc[(s, tf)]
                    d[f"ref5y_{v}_mean_ret_notional"] = q["mean_ret_notional"]
                    d[f"ref5y_{v}_win_pct"] = 100 * q["win_rate"]
                    d[f"ref5y_{v}_per_day"] = q["per_day"]
                    d[f"ref5y_{v}_stage1"] = q.get("ds_stage1")
        rows.append(d)
    return pd.DataFrame(rows)


# =============================================================================== main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("extracted_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--repo", default=REPO_DEFAULT)
    ap.add_argument("--ref", default=None, help="fiveyear_ref.csv (default: <out_dir>/fiveyear_ref.csv if present)")
    ap.add_argument("--procs", type=int, default=min(4, os.cpu_count() or 1))
    ap.add_argument("--boot", type=int, default=10_000)
    ap.add_argument("--tz-hours", type=float, default=9.0, help="day / hour buckets in UTC+N (default 9 = KST)")
    ap.add_argument("--no-replay", action="store_true")
    ap.add_argument("--no-funding", action="store_true", help="replay with funding 0 (default: rates solved from trades)")
    ap.add_argument("--no-flip", action="store_true", help="skip the side-flip (timing-matched coin flip) replay")
    ap.add_argument("--brackets", default=None, help="Binance leverageBracket JSON (default: brackets inferred)")
    a = ap.parse_args(argv)
    t_start = time.time()
    sys.path.insert(0, a.repo)
    os.makedirs(a.out_dir, exist_ok=True)
    tzh = a.tz_hours
    out = lambda name: os.path.join(a.out_dir, name)  # noqa: E731
    written = []

    def save(df: pd.DataFrame, name: str):
        if df is None:
            return
        df.to_csv(out(name), index=False)
        written.append((name, len(df)))

    names = discover(a.extracted_dir)
    if not names:
        log(f"no run folders under {a.extracted_dir}")
        return 1
    runs = [Run(a.extracted_dir, n) for n in names]
    brackets, br_src = make_brackets(a.brackets)
    SPANS, meta_rows, Ts = {}, [], []
    for run in runs:
        lo, hi = run.span()
        SPANS[run.name] = (lo, hi)
        rule = detect_rule(run)
        taker = implied_taker(run)
        run.rule, run.taker = rule, taker
        T = enrich_trades(run, tzh, taker)
        Ts.append(T)
        rr = run.runs
        br_live = ""
        if rr is not None and len(rr):
            br_live = "; ".join(sorted({str(jload(x).get("brackets_src")) for x in rr["data"]}))
        sh = run.sh
        meta_rows.append({
            "run": run.name, "version": run.version, "files": " ".join(run.files),
            "start_kst": fmt_ts(lo, tzh), "end_kst": fmt_ts(hi, tzh), "days": (hi - lo) / DAY if lo == lo else np.nan,
            "accounts": len(run.accounts), "accounts_by_kind": mix(run.accounts["kind"]),
            "accounts_by_tf": mix(run.accounts["timeframe"]), "trades": len(T),
            "exit_mix": mix(T["exit_reason"]) if len(T) else "", "leverage_mix": mix(T["leverage"]) if len(T) else "",
            "leverage_rule_detected": rule, "taker_fee_implied": taker,
            "live_bars": run.bars is not None and len(run.bars) > 0, "d3_shadow_days": " ".join(sorted(sh["day"].unique())) if sh is not None and len(sh) else "",
            "runs_rows": 0 if rr is None else len(rr), "brackets_src_live": br_live,
            "stop_src_mix": mix(T["stop_src"]) if len(T) else "",
            "signal_status_mix": mix(run.sig["status"]) if run.sig is not None and len(run.sig) else "",
            "outcome_status_mix": mix(run.out["status"]) if run.out is not None and len(run.out) else "",
            "alerts_by_level": mix(run.alerts["level"]) if run.alerts is not None and len(run.alerts) else ""})
        log(f"[load] {run.name}: {len(run.accounts)} accounts, {len(T)} trades, rule {rule}, taker {taker}, "
            f"live_bars {'yes' if meta_rows[-1]['live_bars'] else 'no'}, span {meta_rows[-1]['start_kst']} ~ {meta_rows[-1]['end_kst']} KST")
    T = pd.concat([t for t in Ts if len(t)], ignore_index=True) if any(len(t) for t in Ts) else pd.DataFrame()
    save(pd.DataFrame(meta_rows), "runs_meta.csv")
    save(T, "trades_enriched.csv")
    if len(T):
        save(check_brackets(T, brackets), "brackets_check.csv")
        spec = infer_specs(T)
    else:
        spec = {}
    # (a)
    A, P, C, K = account_tables(runs, T, tzh)
    save(A, "account_stats.csv")
    save(P, "strategy_tf_pooled.csv")
    save(C, "coin_split.csv")
    save(K, "kind_tf_summary.csv")
    log(f"[a] account stats: {len(A)} account rows, {len(P)} pooled rows")
    # (b)
    CP, CR = coinflip(T, a.boot)
    save(CP, "coinflip_pooled.csv")
    save(CR, "coinflip_per_run.csv")
    log(f"[b] coin-flip tests: {len(CP)} pooled, {len(CR)} per run")
    # shadows
    SH = {run.name: parse_shadows(run) for run in runs}
    # (c1)
    ES = every_signal_shadow(runs, T, SH)
    save(ES, "every_signal_shadow.csv")
    # (c2) replay
    RP_parts, rinfo = [], []
    if not a.no_replay:
        for run in runs:
            S = replay_settings(run.rule, run.taker)
            R, info = replay_run(run, S, brackets, spec, a.procs, funding=not a.no_funding, flip=not a.no_flip)
            info.update(leverage_rule=run.rule, taker=run.taker, brackets=br_src)
            rinfo.append(info)
            log(f"[c] replay {run.name}: {info}")
            if len(R):
                RP_parts.append(R)
    RP = pd.concat(RP_parts, ignore_index=True) if RP_parts else pd.DataFrame()
    save(RP, "replay_signals.csv")
    RS = replay_stats(RP)
    save(RS, "replay_stats.csv")
    RPar = replay_parity(RP)
    save(RPar, "replay_parity.csv")
    SF = sideflip_test(RP, a.boot)
    save(SF, "coinflip_sideflip.csv")
    XT = pd.DataFrame()
    if len(RP) and "acct_status" in RP:
        XT = pd.crosstab([RP["run"], RP["acct_status"].fillna("no outcome") + ":" + RP["acct_reason"].fillna("")
                          .str.split(":").str[0]], RP["status"].str.split(" ").str[0]).reset_index()
        XT.columns = ["run", "account_outcome"] + [str(c) for c in XT.columns[2:]]
    save(XT, "replay_vs_outcome.csv")
    save(pd.DataFrame(rinfo), "replay_info.csv")
    # (d)
    F, REJ = signal_flow(runs, T)
    save(F, "signal_flow.csv")
    save(REJ, "sizing_rejections.csv")
    Z = F[F["trades"] == 0].groupby(["run", "kind", "zero_trade_cause"]).size().reset_index(name="accounts") if len(F) else pd.DataFrame()
    save(Z, "zero_trade_causes.csv")
    # (e)
    DP, DG = dup_tables(runs, T)
    save(DP, "dup_pairs.csv")
    save(DG, "dup_groups.csv")
    # (f)
    D, H, HK, L = time_tables(T)
    save(D, "pnl_by_day.csv")
    save(H, "pnl_by_hour.csv")
    save(HK, "pnl_by_hour_kind.csv")
    save(L, "luck_concentration.csv")
    # (g)
    M, DL = market_tables(runs, T, tzh)
    save(M, "market_backdrop.csv")
    save(DL, "direction_luck.csv")
    # (h)
    CT = cost_table(T)
    save(CT, "cost_by_tf.csv")
    # d3 variants
    V, VX = variant_tables(runs, T, SH)
    save(V, "variants_paired.csv")
    save(VX, "variants_rows.csv")
    SW = stop_whatif_losers(SH, T)
    save(SW, "stop_whatif_losers.csv")
    LM = limit_table(SH, T, RP)
    save(LM, "limit_shadow.csv")
    # realistic stop slippage (daily3 stop_slips: paper vs aggTrades-based fill of every SL / LOCK / LIQ exit)
    sl_rows = []
    for run in runs:
        x = run.slips
        if x is None or not len(x):
            continue
        for keys, g in list(x.groupby(["exit_reason", "timeframe"])) + [(("*", "*"), x)]:
            ok = g[g["real_bps"].notna() & g["paper_bps"].notna()]
            sl_rows.append({"run": run.name, "exit_reason": keys[0], "timeframe": keys[1], "exits": len(g),
                            "status_mix": mix(g["status"]), "with_real": len(ok),
                            "paper_bps_median": ok["paper_bps"].median(), "real_bps_median": ok["real_bps"].median(),
                            "real_bps_p90": ok["real_bps"].quantile(0.9) if len(ok) else np.nan,
                            "real_minus_paper_bps_mean": (ok["real_bps"] - ok["paper_bps"]).mean(),
                            "diff_usd_sum": g["diff_usd"].sum()})
    save(pd.DataFrame(sl_rows), "stop_slips_summary.csv")
    # 5-year comparison
    ref = a.ref or (out("fiveyear_ref.csv") if os.path.exists(out("fiveyear_ref.csv")) else None)
    FY = vs_fiveyear(ref, P, RS, runs, SPANS)
    save(FY, "vs_fiveyear.csv")
    elapsed = time.time() - t_start
    write_summary(a, out("summary.md"), runs, meta_rows, T, A, P, K, CP, CR, ES, RS, RPar, rinfo, F, Z, REJ, DP, DG,
                  L, HK, M, DL, CT, V, SW, LM, FY, br_src, brackets, written, elapsed, ref, SF, XT)
    log(f"done in {elapsed:.1f}s -> {a.out_dir}")
    return 0


# =============================================================================== summary.md
def run_order(df: pd.DataFrame, runs) -> pd.DataFrame:
    order = {r.name: i for i, r in enumerate(runs)}
    order["ALL"] = len(order)
    d = df.copy()
    d["_r"] = d["run"].map(order).fillna(99)
    if "timeframe" in d:
        d["_t"] = d["timeframe"].map({t: i for i, t in enumerate(TF_ORDER)}).fillna(99)
    else:
        d["_t"] = 0
    return d.sort_values(["_r"] + [c for c in ("kind",) if c in d] + ["_t"]).drop(columns=["_r", "_t"])


def write_summary(a, path, runs, meta_rows, T, A, P, K, CP, CR, ES, RS, RPar, rinfo, F, Z, REJ, DP, DG, L, HK, M, DL,
                  CT, V, SW, LM, FY, br_src, brackets, written, elapsed, ref, SF=None, XT=None):
    w = []
    add = w.append
    add("# Paper bot export analysis\n")
    add(f"Export: `{a.extracted_dir}`. Generated by `analyze.py` in {elapsed:.0f}s. Days and hours are UTC+{a.tz_hours:g} "
        "(KST). R = net pnl / (qty x |entry - initial stop|); the initial stop is the 2 ATR house stop (or the reel's "
        "own stop). ROE = net pnl / margin. All money in USDT; each account starts at $5,000.\n")
    add("**Read with care:** every run is days long. Per account n is small (often < 20), so almost nothing below can "
        "separate skill from luck; the coin-flip tests report their power (mde_R_80pct = the smallest mean-R "
        "difference the test would detect 80% of the time).\n")
    add("## Headlines (computed)\n")
    try:
        for r in runs:
            t = T[T["run"] == r.name] if len(T) else T
            if not len(t):
                continue
            parts = []
            for k, g in t.groupby("kind"):
                parts.append(f"{k} {len(g)} trades, pnl ${g['pnl'].sum():,.0f}, mean R {g['R'].mean():+.3f}, "
                             f"win {100 * g['win'].mean():.0f}%")
            add(f"- {r.name} ({r.version}): " + "; ".join(parts) + ".")
        if len(RPar):
            ok = int(RPar["roe_equal_1e-6"].sum())
            tot = int(RPar["replayed_traded"].sum())
            add(f"- Replay parity: {ok} of {tot} replayed signals that the accounts really entered and closed reproduce "
                f"the real ROE to 1e-6 (same exit time / reason / leverage: {int(RPar['same_exit_time'].sum())}).")
        if SF is not None and len(SF):
            for k in ("strategy", "ds200", "random"):
                x = SF[(SF["level"] == "kind") & (SF["kind"] == k)]
                if len(x):
                    x = x.iloc[0]
                    add(f"- Side-flip (direction skill vs a coin flip at the same moments), {k}: excess "
                        f"{x['excess_R']:+.3f} R over {int(x['n_pairs'])} signals, p(better) {x.get('p_better', np.nan):.3f}.")
        if len(CP) and "p_one_sided" in CP:
            tt = CP[CP["p_one_sided"].notna()]
            add(f"- Trade-based coin-flip bootstrap: {len(tt)} testable cells, {int(tt['bh_reject_0.05'].astype(bool).sum())} "
                f"BH-better, {int(tt['bh_reject_worse_0.05'].astype(bool).sum())} BH-worse; every tested cell is low power.")
    except Exception as exc:  # noqa: BLE001  (headlines only)
        add(f"- (headline error: {type(exc).__name__}: {exc})")
    add("")
    add("## Runs\n")
    add(md_table(pd.DataFrame(meta_rows), ["run", "version", "start_kst", "end_kst", "days", "accounts", "accounts_by_kind",
                                           "trades", "exit_mix", "leverage_mix", "leverage_rule_detected",
                                           "live_bars", "d3_shadow_days"], 10))
    # overview by kind x tf
    add("\n## (a) Results by run x kind x timeframe (all accounts pooled)\n")
    if len(K):
        k = run_order(K, runs)
        add(md_table(k, ["run", "kind", "exits", "timeframe", "accounts_with_trades", "n", "win_pct", "pnl_sum", "mean_roe",
                         "mean_R", "median_R", "payoff", "profit_factor", "mean_cost_R", "mean_mfe_R", "mean_hold_min",
                         "lev_mix"], 60))
    add("\n### Pooled per strategy x tf (kind strategy / ds200 / reel): top and bottom 15 by mean R, n >= 10\n")
    if len(P):
        p = P[(P["kind"] != "random") & (P["n"] >= 10)].sort_values("mean_R", ascending=False)
        cols = ["kind", "strategy", "timeframe", "n", "win_pct", "pnl_sum", "mean_R", "median_R", "payoff",
                "profit_factor", "max_consec_losses", "worst_realized_dd_any_run"]
        add(md_table(p, cols, 15))
        add("\nBottom 15:\n")
        add(md_table(p.iloc[::-1], cols, 15))
        tot = P[P["kind"] != "random"]
        add(f"\nAccounts-cells with trades: {len(tot)}; with mean R > 0: {int((tot['mean_R'] > 0).sum())}; "
            f"with pnl > 0: {int((tot['pnl_sum'] > 0).sum())}.\n")
    # (b)
    add("\n## (b) Against coin flips (bootstrap of the random accounts' trades, same timeframe and exit type)\n")
    add(f"{a.boot:,} bootstrap draws of n coin-flip trades (R) per tested cell; p = one-sided P(random mean >= observed). "
        f"BH FDR at 0.05 across all tested cells of a table. Pooled = all runs together per strategy x tf. A cell is "
        f"tested only with n >= {MIN_N_TEST} trades and a coin-flip pool >= {MIN_POOL} trades of the same timeframe and "
        "exit type: the one-position coin-flip accounts took few trades, so the 1h / 4h pools are too small to test "
        "against at all (see the pools table). The side-flip test below has far more n.\n")
    for name, D in (("pooled", CP), ("per run", CR)):
        if len(D) and "p_one_sided" in D:
            tested = D[D["p_one_sided"].notna()]
            add(f"- {name}: {len(D)} cells, {len(D) - len(tested)} not testable; {len(tested)} tested, BH-significant better than coin flips: "
                f"{int(tested['bh_reject_0.05'].astype(bool).sum())}, BH-significant worse: "
                f"{int(tested['bh_reject_worse_0.05'].astype(bool).sum())}; raw p < 0.05: {int((tested['p_one_sided'] < 0.05).sum())} "
                f"(expected by chance ~{0.05 * len(tested):.0f}); low power (n < 30 or |diff| < mde): "
                f"{int(tested['low_power'].astype(bool).sum())}; median n {tested['n'].median():.0f}.\n")
    if len(CP) and "p_one_sided" in CP:
        add("\nLowest p (pooled):\n")
        add(md_table(CP[CP["p_one_sided"].notna()].sort_values("p_one_sided"), ["kind", "strategy", "timeframe", "n", "mean_R", "rand_pool_mean_R",
                                                     "rand_pool_n", "percentile", "p_one_sided", "bh_q", "mde_R_80pct"], 15))
        pools = CP.groupby(["timeframe", "exits"]).agg(rand_pool_n=("rand_pool_n", "first"),
                                                       rand_pool_mean_R=("rand_pool_mean_R", "first"),
                                                       rand_pool_sd_R=("rand_pool_sd_R", "first")).reset_index()
        add("\nCoin-flip pools (pooled across runs):\n")
        add(md_table(pools))
    if SF is not None and len(SF):
        add("\n### Side-flip test (timing-matched coin flip, from the replay)\n")
        add("Every replayed signal is also replayed with the OTHER side at the same moment (same coin, bar, 2 ATR stop, "
            "leverage group). A coin flip at those moments earns (R_chosen + R_other) / 2 on average, so excess_R = "
            "mean(R_chosen - R_other) / 2 is what the side choice added. p from a sign-flip randomization "
            f"({a.boot:,} draws) with one sign per cluster (run x bar close floored to max(tf, 1h): signals close in "
            "time are not independent); p_better_indep flips each signal alone (too optimistic when signals cluster). "
            "BH over the strategy x tf cells. The other side uses the same reference quote "
            "(the real one would be the other side of the spread: about 1 bp, a small bias in favour of the flipped "
            "side).\n")
        sk = SF[SF["level"] != "strategy_tf"]
        add(md_table(run_order(sk.assign(run="ALL"), runs), ["level", "kind", "timeframe", "n_pairs", "n_clusters",
                                                            "mean_R_chosen", "mean_R_other_side", "excess_R",
                                                            "share_chosen_better", "p_better", "p_worse",
                                                            "p_better_indep", "mde_excess_R_80pct"], 40))
        st = SF[(SF["level"] == "strategy_tf") & SF.get("p_better", pd.Series(dtype=float)).notna()]
        if len(st):
            add(f"\nstrategy x tf cells tested: {len(st)}; BH-significant better: "
                f"{int(st['bh_reject_better_0.05'].astype(bool).sum())}, worse: {int(st['bh_reject_worse_0.05'].astype(bool).sum())}; "
                f"raw p_better < 0.05: {int((st['p_better'] < 0.05).sum())} (chance ~{0.05 * len(st):.0f}).\n")
            add(md_table(st.sort_values("p_better"), ["kind", "strategy", "timeframe", "n_pairs", "n_clusters",
                                                      "mean_R_chosen", "mean_R_other_side", "excess_R", "p_better",
                                                      "bh_q_better", "p_better_indep", "mde_excess_R_80pct"], 12))
    # (c)
    add("\n## (c) Every signal, not only the ones a one-position account could take\n")
    add("### c1. Entered trades + nightly 'skipped' shadows (daily3: the skipped signal alone, house rules, ROE only)\n")
    if len(ES):
        e = ES[ES["run"] != "ALL"].groupby(["run", "kind"]).agg(
            accounts=("account_id", "nunique"), n_entered=("n_entered", "sum"), skipped_outcomes=("n_skipped_outcomes", "sum"),
            skipped_shadows=("n_skipped_shadow", "sum"), shadow_no_trade=("n_skipped_no_trade", "sum"),
            n_all=("n_all", "sum")).reset_index()
        roe = ES[ES["run"] != "ALL"].assign(w=lambda x: x["mean_roe_all"] * x["n_all"]).groupby(["run", "kind"])["w"].sum()
        e["mean_roe_all"] = (roe.values / e["n_all"].replace(0, np.nan)).values
        add(md_table(e))
        add("\nShadows exist only for the days the nightly job ran (see runs table); skipped outcomes outside those days "
            "have no shadow row.\n")
    add("\n### c2. Independent replay: every SUBMITTED signal alone through the repo's engine on live_bars\n")
    add(f"`paperbot.daily3._alone` + `make_signal` on `obsshadows.symbol_steps` of the run's live_bars (1m, last + mark), "
        f"funding 0, fresh $5,000 account per signal, run's own leverage rule, brackets: {br_src}.\n")
    if rinfo:
        add(md_table(pd.DataFrame(rinfo)))
    if len(RPar):
        add("\nParity (signals the account actually ENTERED and closed: replay ROE vs the account's real ROE):\n")
        add(md_table(RPar))
    if XT is not None and len(XT):
        add("\nWhat the account did with each signal (rows) vs what the replay alone did (columns):\n")
        add(md_table(XT, n=40, floatfmt="{:.0f}"))
    if len(RS):
        add("\nReplay by run x kind x tf:\n")
        rs = run_order(RS[RS["strategy"] == "*"], runs)
        add(md_table(rs, ["run", "kind", "timeframe", "n_submitted", "n_traded",
                                                               "n_rejected_sizing", "n_unresolved", "n_not_replayable",
                                                               "win_pct", "mean_roe", "mean_R", "t_R", "payoff", "pf_R",
                                                               "mean_R_entered_signals", "mean_R_skipped_signals"], 40))
        rs2 = RS[(RS["run"] == "ALL") & (RS["n_traded"] >= 15)].sort_values("mean_R", ascending=False)
        add("\nReplay pooled per strategy x tf (n_traded >= 15), top 15 by mean R:\n")
        add(md_table(rs2, ["kind", "strategy", "timeframe", "n_traded", "win_pct", "mean_roe", "mean_R", "t_R", "payoff"], 15))
    # (d)
    add("\n## (d) Signal flow and accounts without trades\n")
    if len(F):
        fl = F.groupby(["run", "kind"]).agg(accounts=("account_id", "size"), submitted=("sig_SUBMITTED", "sum"),
                                            record=("sig_RECORD", "sum"), late=("sig_LATE", "sum"),
                                            outcomes=("outcomes", "sum"), entered=("entered", "sum"),
                                            trades=("trades", "sum"), open_at_end=("open_at_end", "sum"),
                                            zero_trade_accounts=("trades", lambda x: int((x == 0).sum()))).reset_index()
        oc = [c for c in F.columns if c.startswith("out_")]
        ocs = F.groupby(["run", "kind"])[oc].sum().reset_index()
        add(md_table(fl))
        add("\nOutcome reasons (counts):\n")
        add(md_table(ocs.loc[:, (ocs != 0).any(axis=0)]))
        add("\nZero-trade causes:\n")
        add(md_table(Z, n=60))
    if len(REJ):
        add("\nSizing rejections by category (the last candidate's reason):\n")
        add(md_table(REJ.groupby(["run", "category"]).size().reset_index(name="n")))
    # (e)
    add("\n## (e) Duplicate accounts (identical or >= 90% overlapping entries)\n")
    if len(DG):
        add(md_table(DG.groupby(["level", "run"]).agg(groups=("group", "size"), accounts=("size", "sum"),
                                                      identical_groups=("identical_all", "sum")).reset_index()))
        add("\nLargest groups:\n")
        add(md_table(DG.sort_values(["size", "n_max"], ascending=False), ["level", "run", "size", "identical_all", "n_min",
                                                                          "n_max", "kinds", "members"], 15))
    else:
        add("_No duplicate groups (pairs with < 3 entries are ignored for grouping; see dup_pairs.csv)._\n")
    # (f)
    add("\n## (f) Time clustering and luck concentration\n")
    if len(L):
        lp = L[(L["pnl_total"] > 0) & (L["kind"] != "random")]
        l5 = lp[lp["n"] >= 5]
        add(f"Profitable non-random accounts: {len(lp)}; of these, profit gone without the single best trade: "
            f"{int(lp['lucky_flag'].sum())}. Among the {len(l5)} with n >= 5: gone without the best trade "
            f"{int(l5['lucky_flag'].sum())}, median best-trade share of profit {l5['best_trade_share'].median():.2f}, "
            f"median best-day share {l5['best_day_share'].median():.2f}.\n")
        add(md_table(lp.sort_values("pnl_total", ascending=False), ["run", "account_id", "n", "pnl_total", "best_trade_pnl",
                                                                     "best_trade_share", "pnl_ex_best_trade", "best_day",
                                                                     "best_day_share", "days_traded"], 15))
    if len(HK):
        add("\nP&L by exit hour (KST), all non-random accounts, all runs:\n")
        hk = HK[HK["kind"] != "random"].groupby("exit_hour").agg(n=("n", "sum"), pnl=("pnl", "sum")).reset_index()
        add(md_table(hk.T.reset_index(), n=5, floatfmt="{:.0f}"))
    # (g)
    add("\n## (g) Market backdrop\n")
    if len(M):
        add(md_table(M, ["run", "symbol", "source", "start_kst", "end_kst", "return_pct", "max_drawdown_pct",
                         "max_runup_pct", "realized_vol_daily_pct", "up_hour_share", "direction"], 40))
    if len(DL):
        fl = DL[DL["direction_luck_flag"]]
        add(f"\nAccounts flagged for possible direction luck (n >= 5, pnl > 0, >= 70% of trades on the side of the coin's "
            f"day move, and the trades against the day move not positive): {len(fl)}.\n")
        add(md_table(fl.sort_values("pnl", ascending=False), ["run", "account_id", "n", "long_share", "pnl", "mean_R",
                                                               "aligned_day_share", "mean_R_aligned_day",
                                                               "mean_R_against_day"], 15))
        bal = DL.groupby(["run", "kind"]).apply(lambda g: pd.Series({
            "accounts": len(g), "trades": g["n"].sum(), "long_share": np.average(g["long_share"], weights=g["n"]),
            "aligned_day_share": np.average(g["aligned_day_share"], weights=g["n"])}), include_groups=False).reset_index()
        add("\nLong share and share of trades aligned with the coin's day move, by run x kind:\n")
        add(md_table(bal))
    # (h)
    add("\n## (h) Cost vs stop distance\n")
    add("rt_cost_over_stop = 2 x (taker + slippage) x entry / |entry - initial stop| = the round trip in R.\n")
    if len(CT):
        add(md_table(CT[CT["run"] == "ALL"], ["timeframe", "n", "median_stop_pct", "rt_cost_over_stop_median",
                                             "rt_cost_over_stop_p10", "rt_cost_over_stop_p90",
                                             "actual_fee_funding_R_mean", "actual_fee_funding_slip_R_mean", "mean_R",
                                             "mean_gross_R"]))
    sp = os.path.join(os.path.dirname(path), "stop_slips_summary.csv")
    ss_ = _read(sp)
    if ss_ is not None:
        if len(ss_):
            add("\nStop-exit slippage, paper vs real (daily3 stop_slips: where a real STOP_MARKET of the trade's size would "
                "have filled, from public aggTrades; diff_usd < 0 = paper was the more expensive):\n")
            add(md_table(ss_, n=40))
    # variants
    add("\n## Nightly what-if variants (d3_shadows) vs base, paired on the same trades\n")
    add("Each variant re-runs a closed trade's signal alone (fresh $5,000 account, Binance final klines + funding). "
        "`diff_R` is in units of the base trade's initial 2 ATR stop distance (so leverage variants compare on price "
        "terms; ROE differences of leverage variants mostly reflect leverage). Rows with roe empty and resolved=1 are "
        "'not entered' (sizing refused); resolved=0 are open at the end of the fetched horizon and are NOT in the "
        "pairs: variants that hold longer (tp2R / tp3R, lock30, lev10) lose their slow trades from the pairs, which "
        "biases them toward their quick (mostly losing) exits; compare n_pairs with rows. 'base' itself can differ "
        "from the real trade (fresh $5,000 account, final klines).\n")
    if len(V):
        add(md_table(V[V["level"] == "account_kind"].sort_values(["kind_acct", "variant"]),
                     ["kind_acct", "variant", "n_pairs", "variant_not_entered", "variant_unresolved", "mean_roe_base",
                      "mean_roe_variant", "diff_roe", "t_diff_roe", "mean_R_base", "mean_R_variant", "diff_R", "t_diff_R",
                      "diff_pnl_eq", "share_variant_better_roe"], 80))
        kt = V[V["level"] == "account_kind_tf"]
        for ka in ("strategy", "ds200"):
            x = kt[kt["kind_acct"] == ka]
            if not len(x):
                continue
            pv = x.pivot_table(index="variant", columns="timeframe", values="diff_R", aggfunc="first")
            pn = x.pivot_table(index="variant", columns="timeframe", values="n_pairs", aggfunc="first")
            cols = [t for t in TF_ORDER if t in pv.columns]
            tab = pd.DataFrame({"variant": pv.index})
            for t in cols:
                tab[f"{t} diff_R"] = pv[t].values
                tab[f"{t} n"] = pn[t].values
            add(f"\nPer timeframe, account kind {ka}: diff_R (variant - base, base-stop R units) and pairs:\n")
            add(md_table(tab, n=40))
    if len(SW):
        add("\nLoss-card stop what-ifs (losing trades only, biased):\n")
        add(md_table(SW[SW["timeframe"] == "*"]))
    if len(LM):
        add("\nLimit-order what-if (0.25 ATR better than the reference, within one bar):\n")
        add(md_table(LM[LM["kind"] == "*"]))
    # 5y
    add("\n## Side by side with the 5-year backtest\n")
    if len(FY):
        add(f"Reference: `{ref}`. live_mean_ret_notional = mean ROE / leverage (net return per unit notional), the fair "
            "comparison across leverage rules; the 5-year profiles are every signal alone with the old tier-walk "
            "leverage. Signals per day: live = all computed signals of the strategy x tf on the six coins / run days.\n")
        fy = FY[FY["kind"] == "strategy"].copy()
        if len(fy):
            fy["_t"] = fy["timeframe"].map({t: i for i, t in enumerate(TF_ORDER)}).fillna(99)
            add(md_table(fy.sort_values(["strategy", "_t"]),
                         [c for c in ["strategy", "timeframe", "live_trades", "live_mean_ret_notional", "replay_signals_traded",
                                      "replay_mean_ret_notional", "ref5y_mean_ret_notional", "live_win_pct", "replay_win_pct",
                                      "ref5y_win_pct", "live_signals_per_day", "ref5y_signals_per_day"] if c in fy], 200))
    else:
        add("_No reference file (run fiveyear_ref.py first, or pass --ref)._\n")
    # caveats
    add("\n## Caveats and data notes\n")
    notes = [
        "Replay brackets: " + br_src + " (see brackets_check.csv: recorded vs recomputed liquidation price of every "
        "trade without funding). The live runs used Binance's live bracket table (runs.csv brackets_src).",
        "Replay funding: live_bars carry no funding; the rates are solved from the trades' recorded funding "
        "(funding = side x qty x mark_open x rate at 00/08/16 UTC, replay_info.csv funding_* columns). A replayed "
        "signal holding over a funding instant no trade held gets funding 0. With --no-funding the parity table shows "
        "every ROE mismatch is a trade with funding (the funding shifts the ladder's lock prices).",
        "Trades are not independent: many accounts take the same coin at the same minute (duplicate groups, (e)), so "
        "paired t-values in the variant table and pooled tests overstate the evidence.",
        "The reel and the v4 5m coin flips cannot be replayed: their entry levels (signal_log data.reel) are not in the "
        "export; they are marked NOT_REPLAYABLE_REEL.",
        "Run run-20261005T014624Z has no live_bars.csv: no replay; its market backdrop is approximated from signal "
        "reference prices and trade fills (marked APPROX).",
        "d3_shadows use Binance final klines + funding fetched at night; the replay uses the bot's own live_bars.",
        "The 5-year profiles are every signal alone at a $1,000 sizing equity with the old tier-walk leverage and "
        "EXAMPLE brackets; compare ROE per unit leverage (mean_ret_notional) rather than raw ROE.",
        "The DeepSeek 5-year numbers use the PREREG's own exits (X5_TRAIL2 / X2_SL15_TP3), not the live house ladder, "
        "and are unlevered % per trade.",
        "research/paper_rules/out_binance/accounts.csv calls its per-trade metric mean_R, but it is pnl / margin = ROE.",
    ]
    for n_ in notes:
        add(f"- {n_}")
    add("\n## Tables\n")
    desc = TABLE_DOC
    for name, n in written:
        add(f"- `{name}` ({n} rows): {desc.get(name, '')}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(w) + "\n")


TABLE_DOC = {
    "runs_meta.csv": "one row per run folder: version, span (KST), accounts, trades, exit / leverage mix, detected "
                     "leverage rule, implied taker fee, files present.",
    "trades_enriched.csv": "every trade + derived columns: kind, initial stop used (stop_src), stop_frac, risk_usd, R, "
                           "gross, cost_R, cost_all_R (incl. estimated slippage), rt_cost_over_stop, mfe_R, mae_R, "
                           "hold_min, eq_before, margin_frac, roe_per_lev, KST entry/exit day and hour, regime.",
    "brackets_check.csv": "per symbol: recorded liq_price vs the replay bracket table (trades without funding).",
    "account_stats.csv": "per run x account (all accounts, also without trades): n, wins, win%, pnl, mean ROE, mean/"
                         "median R, avg win/loss R, payoff, profit factor, expectancy R, exit mix, long/short n and "
                         "mean R, cost share, cost R, MFE/MAE R, hold, max consecutive losses, realized max DD "
                         "(equity_after), hourly DD (equity_hourly dd_max), leverage mix.",
    "strategy_tf_pooled.csv": "the same statistics pooled across runs per (kind, strategy, timeframe), n per run.",
    "coin_split.csv": "per run x account x coin (run = ALL: pooled per strategy x tf x coin).",
    "kind_tf_summary.csv": "pooled statistics per run x kind x timeframe (run = ALL: all runs).",
    "coinflip_pooled.csv": "per (kind, strategy, tf, exits), all runs: mean R vs bootstrap of the same-tf coin-flip "
                           "trades: percentile, one-sided p, BH q / reject at 0.05 (better and worse tails), mde_R_80pct, "
                           "low_power.",
    "coinflip_per_run.csv": "the same per run x account against that run's coin flips.",
    "every_signal_shadow.csv": "per run x account: entered trades + nightly skipped shadows (ROE only), coverage, "
                               "pooled ROE of all; run = ALL pooled per strategy x tf.",
    "replay_signals.csv": "every SUBMITTED signal replayed alone: status (TRADED / REJECTED_SIZING / UNRESOLVED / "
                          "NOT_REPLAYABLE_REEL / ...), entry/exit, leverage, ROE, R, MFE/MAE R, mark ROE/R if "
                          "unresolved, the account's own outcome and actual ROE for parity.",
    "replay_stats.csv": "replay statistics per run x kind x strategy x tf (run = ALL pooled; strategy = * per tf).",
    "replay_parity.csv": "replay vs the accounts' real trades for signals they entered (ROE equality, exit, leverage).",
    "replay_info.csv": "replay timing (s per 1,000 signals), bars span, missing minutes, rule, brackets.",
    "signal_flow.csv": "per run x account: signal_log counts by status, outcome counts by status:reason, trades, "
                       "entered but open at the end, zero_trade_cause.",
    "sizing_rejections.csv": "every sizing rejection with its category and the candidate reasons text.",
    "zero_trade_causes.csv": "count of zero-trade accounts per run x kind x cause.",
    "dup_pairs.csv": "account pairs with >= 90% overlap of entries (level trades: symbol, entry_time, side; level "
                     "signals: bar_close, symbol, side); identical flag; trivial_lt3 when < 3 entries.",
    "dup_groups.csv": "connected groups of non-trivial >= 90% pairs.",
    "pnl_by_day.csv": "per run x account x KST exit day: n, wins, pnl, mean R.",
    "pnl_by_hour.csv": "per run x account x KST exit hour.",
    "pnl_by_hour_kind.csv": "per run x kind x KST exit hour.",
    "luck_concentration.csv": "per run x account: total pnl, best day / best trade and their share of the profit, "
                              "pnl without them, lucky_flag (profit gone without the best trade).",
    "market_backdrop.csv": "per run x coin (and equal-weight): return, max DD / run-up, realized daily vol, up-hour "
                           "share, direction; source live_bars or APPROX.",
    "direction_luck.csv": "per run x account: long share, share of trades with the coin's KST-day move and with the "
                          "run move, mean R / pnl aligned vs against, direction_luck_flag.",
    "cost_by_tf.csv": "per run x kind x tf (run ALL per tf): stop distance %, round-trip cost as a share of the stop "
                      "(R), actual fees+funding(+slippage) in R, mean net and gross R.",
    "variants_paired.csv": "nightly what-if variants vs base on the same trades: levels run_tf, tf, all, account_kind, "
                           "strategy_tf; mean ROE / R (base-stop units) / pnl-on-equity, paired differences and t.",
    "variants_rows.csv": "the variant rows joined to their base row and the actual trade (input of the above).",
    "stop_whatif_losers.csv": "stop1.5 / 2.5 / 3.0 loss-card what-ifs (losing trades only; biased).",
    "limit_shadow.csv": "limit-order what-if: fill rate, mean ROE when filled, paired with the market replay.",
    "vs_fiveyear.csv": "per strategy x tf: live / replay mean ROE per unit leverage, win %, signals per day next to "
                       "the 5-year reference.",
    "coinflip_sideflip.csv": "timing-matched coin flip from the replay: chosen side vs the other side of the same "
                             "signals (R), excess_R, cluster sign-flip p (better / worse), p_better_indep, BH q, mde; "
                             "levels strategy_tf, kind_tf, kind.",
    "replay_vs_outcome.csv": "per run: the account's outcome of each submitted signal vs the replay status.",
    "stop_slips_summary.csv": "daily3 stop_slips per run x exit reason x tf: paper vs real stop slippage (bps), $ diff.",
}


if __name__ == "__main__":
    sys.exit(main())
