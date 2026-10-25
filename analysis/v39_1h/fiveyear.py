#!/usr/bin/env python3
"""V3.9 1h, five years: every what-if of window.py on every V3.9 1h signal of the six coins, 2021-01 .. 2026-10,
judged by period: pick 2021-01-01 .. 2024-01-01, check 2024-01-01 .. 2026-10-01 (the full-grid study's split), plus
the recent month 2026-10-01 .. data end (the live record's month, for comparison only).

    python3 -I fiveyear.py <five_dir> <out_dir> [--fullgrid default_by_exit.npz --fullgrid-exits grids.json]

<five_dir>: fetch_bars.py five output (5m klines + funding). Signals: the locked V3.9 code (features.v39_signals) on
1h bars built from the 5m bars; trades: sim.py on the 5m bars (mark price = last price; the owners' rule: 1m bars only
for the 20-day window). Because 5m bars are coarser than the bot's 1m steps, the absolute numbers differ a little from
the full-grid study's 1m results; every variant is compared with "now" on the same 5m machinery, and the full-grid's
own 1m numbers are joined where it ran the same exit (research/fullgrid/results/default_by_exit.npz, from the branch
origin/fullgrid-results-20261010-1602).

Outputs (CSV / JSON in <out_dir>): fy_signals.json (counts, calibration), fy_variants.csv (per variant and period:
per-trade and per-signal means, win rate, account replay), fy_rules.csv, fy_streaks.csv, fy_windows20d.csv,
fy_recent_vs_paper.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
sys.dont_write_bytecode = True  # never write .pyc files into the repository
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v39lib as L  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import entries as EN  # noqa: E402
import features as F  # noqa: E402
import sim  # noqa: E402
import variants as VR  # noqa: E402

BAR = 300_000
EQ = 5000.0
PERIODS = (("pick", "2021-01-01", "2024-01-01"), ("check", "2024-01-01", "2026-10-01"),
           ("recent", "2026-10-01", "2027-01-01"))


def ms(day: str) -> int:
    return int(pd.Timestamp(day, tz="UTC").value // 1_000_000)


def log(*a):
    print(*a, flush=True)


def exchange():
    from paperbot.margin import Brackets
    with open(os.path.join(L.REPO, "research", "fullgrid", "exchange.json")) as fh:
        doc = json.load(fh)
    br = {p["symbol"]: Brackets.from_binance(p) for p in doc["brackets"]}
    return br, {s: {"qty_step": float(doc["specs"][s]["qty_step"]), "min_notional": float(doc["specs"][s]["min_notional"])}
                for s in L.SYMBOLS}


class Five:
    def __init__(self, five_dir: str):
        from paperbot.config import v3_settings
        self.S = v3_settings()
        self.Sv = sim.settings_vector(self.S)
        brs, self.specs = exchange()
        self.br = {s: sim.bracket_array(brs[s]) for s in L.SYMBOLS}
        self.A, self.h1, sigs = {}, {}, []
        for s in L.SYMBOLS:
            z = F.load5(five_dir, s)
            self.A[s] = {"ts": z["ts"], "o": z["o"], "h": z["h"], "l": z["l"], "c": z["c"], "mo": z["o"], "mh": z["h"],
                         "ml": z["l"], "fund": z["fund"]}
            self.h1[s] = F.hourly(five_dir, s)
        for s in L.SYMBOLS:
            g = F.v39_signals(self.h1[s])
            g.insert(0, "symbol", s)
            sigs.append(g)
        prio = {s: k for k, s in enumerate(self.S.symbol_priority)}
        G = pd.concat(sigs, ignore_index=True)
        G = G[G["close_ms"] >= ms("2021-01-01")]
        G["prio"] = G["symbol"].map(prio)
        self.G = G.sort_values(["close_ms", "prio"]).reset_index(drop=True)
        self.G["period"] = ""
        for name, a, b in PERIODS:
            self.G.loc[(self.G["close_ms"] >= ms(a)) & (self.G["close_ms"] < ms(b)), "period"] = name
        self.ctx = {s: F.Context(self.h1[s], self.h1["BTCUSDT"]) for s in L.SYMBOLS}

    def base_lev(self, r, equity=EQ) -> int:
        A = self.A[r.symbol]
        e = int(np.searchsorted(A["ts"], r.close_ms))
        if e >= len(A["ts"]):
            return 0
        raw = float(A["o"][e])
        fill = raw * (1 + r.side * self.S.slippage_frac)
        ok, lev, *_ = sim.size_rule(self.Sv, self.br[r.symbol], equity, int(r.side), fill, raw - r.side * 2.0 * r.atr,
                                    float(r.atr), bool(r.best), self.specs[r.symbol]["qty_step"],
                                    self.specs[r.symbol]["min_notional"])
        return int(lev) if ok else 0

    def one(self, r, v, entry=("now", {}), equity=EQ, paper_lev=0):
        A = self.A[r.symbol]
        x = EN.entry(entry[0], entry[1], A, int(r.close_ms), int(r.side), float(r.atr), None, BAR)
        if x is None:
            return None
        e, raw = x
        if e >= len(A["ts"]):
            return None
        return sim.run_one(self.Sv, self.br[r.symbol], A, e, raw, int(r.side), float(r.atr), bool(r.best), equity,
                           self.specs[r.symbol], v, r.symbol, paper_lev=paper_lev, paper_frac=paper_lev / 100.0,
                           bar_ms=BAR)

    def alone(self, v, entry=("now", {}), base_levs=None) -> pd.DataFrame:
        """Every signal alone on a fresh $5,000 wallet (as the full-grid study counts 'per trade')."""
        out = []
        for k, r in enumerate(self.G.itertuples(index=False)):
            pl = base_levs[k] if (base_levs is not None and v.same_lev) else 0
            res = self.one(r, v, entry, paper_lev=pl)
            if res is None:
                out.append((np.nan, "NO_ENTRY", 0, -1, np.nan))
            elif res["reason"] == "REJECTED":
                out.append((np.nan, "REJECTED", 0, -1, np.nan))
            else:
                out.append((res["ret"], res["reason"], res["lev"], res["exit_ts"], res["entry_ts"]))
        return pd.DataFrame(out, columns=["ret", "reason", "lev", "exit_ts", "entry_ts"])

    def account(self, v, period: str | None, entry=("now", {}), compound=True, keep=None, start=EQ) -> pd.DataFrame:
        """One position at a time over the six coins, signals in time order, from ``start`` at the period start;
        bust below $10 ends it. compound=False sizes every trade on $5,000 (the trade sequence a one-position bot
        takes, without the wallet path). ``keep``: boolean mask over self.G (a filter rule)."""
        G = self.G if period is None else self.G[self.G["period"] == period]
        if keep is not None:
            G = G[keep[G.index]]
        wallet, busy, entered_at = start, -1, -1
        rows = []
        for r in G.itertuples():
            A = self.A[r.symbol]
            x = EN.entry(entry[0], entry[1], A, int(r.close_ms), int(r.side), float(r.atr), None, BAR)
            if x is None or x[0] >= len(A["ts"]):
                continue
            t_fill = int(A["ts"][x[0]])
            if t_fill <= busy or t_fill == entered_at:
                continue
            eq = wallet if compound else EQ
            pl = self.base_lev(r, eq) if v.same_lev else 0
            res = sim.run_one(self.Sv, self.br[r.symbol], A, x[0], x[1], int(r.side), float(r.atr), bool(r.best), eq,
                              self.specs[r.symbol], v, r.symbol, paper_lev=pl, paper_frac=pl / 100.0, bar_ms=BAR)
            if res["reason"] == "REJECTED":
                continue
            j = int(res["j"])
            busy = int(A["ts"][j]) if res["reason"] != "OPEN" else 2 ** 62
            entered_at = t_fill
            if compound:
                wallet += res["pnl"]
            rows.append({"idx": r.Index, "symbol": r.symbol, "side": int(r.side), "entry_ts": t_fill,
                         "exit_ts": res["exit_ts"], "ret": res["ret"], "pnl": res["pnl"], "reason": res["reason"],
                         "lev": res["lev"], "wallet": wallet})
            if compound and wallet < self.S.bust_below:
                break
        return pd.DataFrame(rows)


def streaks(win: np.ndarray) -> list[int]:
    out, k = [], 0
    for w in win:
        if w:
            k += 1
        else:
            if k:
                out.append(k)
            k = 0
    if k:
        out.append(k)
    return out


def acct_stats(a: pd.DataFrame, start: float = EQ) -> dict:
    if not len(a):
        return {"acct_trades": 0, "acct_final": start}
    w = a["wallet"].to_numpy(float)
    st = streaks((a["pnl"] > 0).to_numpy())
    bust = bool(w[-1] < 10)
    return {"acct_trades": int(len(a)), "acct_win_pct": 100 * float((a["pnl"] > 0).mean()),
            "acct_final": float(w[-1]), "acct_dd_pct": 100 * L.max_drawdown(w, start),
            "acct_bust": bust, "acct_days": float((a["exit_ts"].iloc[-1] - a["entry_ts"].iloc[0]) / L.DAY),
            "acct_longest_streak": int(max(st) if st else 0)}


def per_period(G: pd.DataFrame, res: pd.DataFrame, base: pd.DataFrame | None) -> dict:
    out = {}
    for p, _a, _b in PERIODS:
        m = (G["period"] == p).to_numpy()
        r = res["ret"].to_numpy(float)[m]
        ok = np.isfinite(r)
        rr = r[ok]
        d = {"signals": int(m.sum()), "trades": int(ok.sum()),
             "per_trade_pct": 100 * float(rr.mean()) if len(rr) else np.nan,
             "per_signal_pct": 100 * float(np.where(ok, r, 0.0).mean()) if m.sum() else np.nan,
             "win_pct": 100 * float((rr > 0).mean()) if len(rr) else np.nan,
             "avg_win_pct": 100 * float(rr[rr > 0].mean()) if (rr > 0).any() else np.nan,
             "avg_loss_pct": 100 * float(rr[rr <= 0].mean()) if (rr <= 0).any() else np.nan}
        if base is not None:
            b = base["ret"].to_numpy(float)[m]
            d["delta_per_signal_pct"] = d["per_signal_pct"] - 100 * float(np.where(np.isfinite(b), b, 0.0).mean())
            both = np.isfinite(b) & ok
            dd = r[both] - b[both]
            d["delta_paired_pct"] = 100 * float(dd.mean()) if both.any() else np.nan
            d["delta_paired_t"] = float(dd.mean() / (dd.std(ddof=1) / np.sqrt(len(dd)))) if len(dd) > 2 and dd.std() > 0 else np.nan
        out[p] = d
    return out


def flat(name, label, group, pp: dict, accts: dict) -> dict:
    row = {"variant": name, "label": label, "group": group}
    for p, d in pp.items():
        for k, v in d.items():
            row[f"{p}_{k}"] = v
    for p, d in accts.items():
        for k, v in d.items():
            row[f"{p}_{k}"] = v
    return row


def fullgrid_table(npz: str, exits_json: str) -> pd.DataFrame:
    z = np.load(npz)
    st = z["core|V39_ALL|1h"]                               # (exits, periods select/test/extra, n/sum/sumsq/wins)
    names = json.load(open(exits_json))["exits"]
    rows = []
    for e, name in enumerate(names):
        r = {"variant": name}
        for p, k in (("pick", 0), ("check", 1)):
            n, s, _ss, w = (float(x) for x in st[e, k])
            r[f"fg_{p}_trades"] = n
            r[f"fg_{p}_per_trade_pct"] = 100 * s / n if n else np.nan
            r[f"fg_{p}_win_pct"] = 100 * w / n if n else np.nan
        rows.append(r)
    return pd.DataFrame(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("five_dir")
    ap.add_argument("out")
    ap.add_argument("--fullgrid", default=None)
    ap.add_argument("--fullgrid-exits", default=None)
    ap.add_argument("--paper-start-ms", type=int, default=None, help="start of the live record (recent comparison)")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    X = Five(a.five_dir)
    G = X.G
    info = {"signals": {p: int((G["period"] == p).sum()) for p, _a, _b in PERIODS},
            "signals_long": int((G["side"] > 0).sum()), "signals_short": int((G["side"] < 0).sum()),
            "best_share": float(G["best"].mean()),
            "data_end_utc": str(pd.Timestamp(int(X.A["BTCUSDT"]["ts"][-1]), unit="ms"))}
    log("signals", info["signals"], f"{time.time() - t0:.0f}s")
    base = X.alone(VR.BASE)
    base_levs = base["lev"].to_numpy(int)
    rows = []
    accts_base = {}

    def run_variant(v, group, entry=("now", {}), label=None):
        res = base if (v is VR.BASE and entry[0] == "now") else X.alone(v, entry, base_levs)
        pp = per_period(G, res, base)
        acc = {}
        for p in ("pick", "check"):
            acc[p] = acct_stats(X.account(v, p, entry))
        rows.append(flat(v.name if entry[0] == "now" else label[0], label[1] if label else v.label, group, pp, acc))
        return res
    run_variant(VR.BASE, "now")
    for v in VR.TP[1:]:
        run_variant(v, "tp")
    for v in VR.SL_SAME + VR.SL_RULE:
        run_variant(v, "sl")
    for v in VR.LEV:
        run_variant(v, "lev")
    for v in VR.PLAN:
        run_variant(v, "plan")
    for name, label, kind, p in VR.ENTRY[1:]:
        run_variant(VR.BASE, "entry", (kind, p), (name, label))
    log(f"variants done {time.time() - t0:.0f}s")
    fgrows = []
    for v in VR.FG:
        res = X.alone(v, ("now", {}), base_levs)
        pp = per_period(G, res, base)
        fgrows.append(flat(v.name, v.label, "fullgrid", pp, {}))
    log(f"full-grid exits done {time.time() - t0:.0f}s")
    R = pd.DataFrame(rows)
    FGR = pd.DataFrame(fgrows)
    if a.fullgrid and a.fullgrid_exits:
        fg = fullgrid_table(a.fullgrid, a.fullgrid_exits)
        FGR = FGR.merge(fg, on="variant", how="left")
        info["fullgrid_now"] = fg[fg["variant"] == "ladder|2"].to_dict("records")[0]
    R.to_csv(os.path.join(a.out, "fy_variants.csv"), index=False)
    FGR.to_csv(os.path.join(a.out, "fy_fullgrid_exits.csv"), index=False)

    # ---- streaks and 20-day windows: the trades a one-position bot takes, each sized on $5,000
    seq = X.account(VR.BASE, None, compound=False)
    seq = seq[seq["entry_ts"] >= ms("2021-01-01")].reset_index(drop=True)
    win = (seq["pnl"] > 0).to_numpy()
    srows = []
    for p, a_, b_ in PERIODS[:2] + (("all", "2021-01-01", "2027-01-01"),):
        m = ((seq["entry_ts"] >= ms(a_)) & (seq["entry_ts"] < ms(b_))).to_numpy()
        st = streaks(win[m])
        srows.append({"period": p, "trades": int(m.sum()), "win_pct": 100 * float(win[m].mean()),
                      "longest_win_streak": int(max(st) if st else 0),
                      "streaks_ge_10": int(sum(s >= 10 for s in st)), "streaks_ge_20": int(sum(s >= 20 for s in st)),
                      "streaks_ge_26": int(sum(s >= 26 for s in st)), "streaks_ge_50": int(sum(s >= 50 for s in st)),
                      "median_streak": float(np.median(st)) if st else 0.0,
                      "trades_per_day": float(m.sum() / max(1, (min(ms(b_), int(seq["entry_ts"].max())) - ms(a_)) / L.DAY))})
    pd.DataFrame(srows).to_csv(os.path.join(a.out, "fy_streaks.csv"), index=False)
    seq.to_csv(os.path.join(a.out, "fy_sequence_now.csv.gz"), index=False, compression="gzip")
    wrows = []
    t_end = int(seq["entry_ts"].max())
    for d0 in range(ms("2021-01-01"), t_end - 20 * L.DAY, L.DAY):
        m = ((seq["entry_ts"] >= d0) & (seq["entry_ts"] < d0 + 20 * L.DAY)).to_numpy()
        m2 = ((seq["entry_ts"] >= d0 + 20 * L.DAY) & (seq["entry_ts"] < d0 + 40 * L.DAY)).to_numpy()
        r = seq["ret"].to_numpy(float)
        wrows.append({"start": str(pd.Timestamp(d0, unit="ms").date()), "trades": int(m.sum()),
                      "losses": int((~win[m]).sum()), "ret_pct": 100 * (float(np.prod(1 + r[m])) - 1),
                      "next20_trades": int(m2.sum()),
                      "next20_ret_pct": 100 * (float(np.prod(1 + r[m2])) - 1) if m2.any() else np.nan})
    Wd = pd.DataFrame(wrows)
    Wd.to_csv(os.path.join(a.out, "fy_windows20d.csv"), index=False)

    # ---- the live month on the same 5m machinery vs the paper record
    if a.paper_start_ms:
        sub = X.account(VR.BASE, None, compound=True, keep=(X.G["close_ms"] >= a.paper_start_ms).to_numpy())
        info["recent_5m_account"] = {"trades": int(len(sub)), "wins": int((sub["pnl"] > 0).sum()),
                                     "final_from_5000": float(sub["wallet"].iloc[-1]) if len(sub) else EQ,
                                     "first_kst": L.kst(sub["entry_ts"].iloc[0]) if len(sub) else None,
                                     "last_kst": L.kst(sub["entry_ts"].iloc[-1]) if len(sub) else None}
        sub.to_csv(os.path.join(a.out, "fy_recent_trades_5m.csv"), index=False)

    # ---- simple 'skip' rules (the loss question), on the base outcome of every signal and on the account
    ctx = [X.ctx[r.symbol].at(int(r.close_ms), int(r.side)) for r in G.itertuples(index=False)]
    ru = []
    for name, label, f in F.RULES:
        skip = np.array([bool(f(c, int(s))) for c, s in zip(ctx, G["side"])])   # NaN context -> False (kept)
        row = {"rule": name, "label": label}
        for p, _a, _b in PERIODS[:2]:
            m = (G["period"] == p).to_numpy()
            r = base["ret"].to_numpy(float)
            ok = np.isfinite(r)
            kept, rem = m & ok & ~skip, m & ok & skip
            row[f"{p}_skip_share_pct"] = 100 * float(skip[m].mean())
            row[f"{p}_kept_per_trade_pct"] = 100 * float(r[kept].mean())
            row[f"{p}_removed_per_trade_pct"] = 100 * float(r[rem].mean()) if rem.any() else np.nan
            row[f"{p}_kept_win_pct"] = 100 * float((r[kept] > 0).mean())
            row[f"{p}_all_per_trade_pct"] = 100 * float(r[m & ok].mean())
            acc = acct_stats(X.account(VR.BASE, p, keep=~skip))
            row.update({f"{p}_{k}": v for k, v in acc.items()})
        ru.append(row)
    pd.DataFrame(ru).to_csv(os.path.join(a.out, "fy_rules.csv"), index=False)
    with open(os.path.join(a.out, "fy_signals.json"), "w") as fh:
        json.dump(info, fh, indent=1, default=lambda x: x.item() if hasattr(x, "item") else str(x))
    log(f"done in {time.time() - t0:.0f}s -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
