"""Expected trades / day and AI calls for one AI trader = one strategy on 15m + 30m, one position at a time.

Simulation on the replay (every SUBMITTED signal alone through the repo engine on live_bars; v3b and v4): the merged
15m + 30m signal stream of a strategy, in time order; when flat, the first enterable signal of a bar close is taken
(the account then holds until that signal's replay exit; UNRESOLVED = held to the end of the data); while holding,
signals are skipped. This is a rule-following trader that takes every signal it can (an upper bound on entries for an
AI that also skips). Wake-up calls counted as in AIBOT_DESIGN_KO_v2 6-2 (adapted to 15m / 30m entries):
  signal wake  = a bar close with >= 1 signal while flat (one bundled call)
  switch wake  = while holding, an opposite-side signal on the held coin
  event wakes  = per trade: 1 ATR move (|MFE| or |MAE| >= 0.5 R, the stop is 2 ATR), 70% of the stop (MAE <= -0.7 R),
                 funding instant -10 min inside the hold (00/08/16 UTC)
  scan wakes   = 4h scans while flat (6 / day x flat share; upper bound: the design calls the AI only if a
                 near-signal candidate exists)
  hold checks  = optional scenario: one check per 15m bar close while holding ("human-like" monitoring)
Analytic cross-check with the 5-year signal rate: trades/day = lam / (1 + lam * h) (one-server loss system with
Poisson arrivals, lam = signal moments / day, h = mean hold in days).

    python3 -I ai_trader.py <export_dir> <out_real_dir> <work_dir>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import *  # noqa

E, O, W = sys.argv[1], sys.argv[2], sys.argv[3]
RP = pd.read_csv(os.path.join(O, "replay_signals.csv"), low_memory=False)
meta = pd.read_csv(os.path.join(O, "runs_meta.csv"))
DAYS = dict(zip(meta["run"], meta["days"]))
END, START = {}, {}
for r in ("run-20261005T183457Z", "current"):
    b = pd.read_csv(os.path.join(E, r, "live_bars.csv"), usecols=["ts"])
    END[r], START[r] = int(b["ts"].max()) + MIN, int(b["ts"].min())
FUND = 8 * HOUR

x = RP[RP["timeframe"].isin(["15m", "30m"]) & RP["kind"].isin(["strategy", "ds200"])].copy()
x["tf_rank"] = x["timeframe"].map({"30m": 0, "15m": 1})


def sim(g: pd.DataFrame, run: str, dedup_bars: int = 0) -> dict:
    g = g.sort_values(["bar_close", "tf_rank", "symbol"])
    free_at, held = -1, None
    n_tr = calls_sig = calls_switch = calls_evt = calls_fund = hold_checks = 0
    flat_ms = 0
    last_seen = {}       # (symbol, side, tf) -> bar_close of the last signal (dedup)
    Rs = []
    t_prev = START[run]
    for bc, grp in g.groupby("bar_close", sort=True):
        if bc >= free_at:
            # flat: wake once for the bundle unless every signal is a recent duplicate
            fresh = []
            for r in grp.itertuples(index=False):
                k = (r.symbol, r.side, r.timeframe)
                lastbc = last_seen.get(k)
                if dedup_bars and lastbc is not None and bc - lastbc <= dedup_bars * TF_MIN[r.timeframe] * MIN:
                    pass
                else:
                    fresh.append(r)
            for r in grp.itertuples(index=False):
                last_seen[(r.symbol, r.side, r.timeframe)] = bc
            if not fresh:
                continue
            calls_sig += 1
            ent = [r for r in fresh if r.status in ("TRADED", "UNRESOLVED")]
            if not ent:
                continue
            r = ent[0]
            n_tr += 1
            et = int(r.entry_time)
            xt = int(r.exit_time) if r.status == "TRADED" and r.exit_time == r.exit_time else END[run]
            free_at = xt
            held = (r.symbol, int(r.side))
            if r.status == "TRADED":
                Rs.append(float(r.R))
                mfe, mae = float(r.mfe_R), float(r.mae_R)
            else:
                mfe = mae = 0.0
            calls_evt += int(max(abs(mfe), abs(mae)) >= 0.5) + int(mae <= -0.7)
            calls_fund += len(range((et - 10 * MIN) // FUND + 1, (xt - 10 * MIN) // FUND + 1))
            hold_checks += max(0, (xt - et) // (15 * MIN))
        else:
            for r in grp.itertuples(index=False):
                last_seen[(r.symbol, r.side, r.timeframe)] = bc
                if held and r.symbol == held[0] and int(r.side) == -held[1]:
                    calls_switch += 1
                    break
    days = DAYS[run]
    # time flat: total minus time in positions (approx by sum of holds capped at the run end)
    return {"trades": n_tr, "mean_R_taken": float(np.mean(Rs)) if Rs else np.nan, "n_R": len(Rs),
            "calls_signal": calls_sig, "calls_switch": calls_switch, "calls_events": calls_evt,
            "calls_funding": calls_fund, "hold_checks_15m": hold_checks, "days": days}


rows = []
for (run, kind, s), g in x.groupby(["run", "kind", "strategy"]):
    for dd in (0, 4):
        d = sim(g, run, dd)
        d.update(run=RUN_LABEL[run], kind=kind, strategy=s, dedup_bars=dd, signals_15m=int((g.timeframe == "15m").sum()),
                 signals_30m=int((g.timeframe == "30m").sum()),
                 moments=int(g["bar_close"].nunique()),
                 mean_hold_min=float(g.loc[g.status == "TRADED", "hold_min"].mean()))
        rows.append(d)
S = pd.DataFrame(rows)
S.to_csv(os.path.join(W, "ai_trader_sim_runs.csv"), index=False)

# pooled over v3b + v4 (strategy kind) / v4 only (ds200), per dedup setting. Every strategy of a kind gets the
# full span of the runs it existed in (a strategy without any 15m / 30m signal in a run still lived through it).
F0 = pd.read_csv(os.path.join(W, "flow.csv"))
full = []
for k, runs in (("strategy", ("v3b", "v4")), ("ds200", ("v4",))):
    names = sorted(F0.loc[F0["kind"] == k, "strategy"].unique())
    for s in names:
        for run in runs:
            for dd in (0, 4):
                full.append({"kind": k, "strategy": s, "run": run, "dedup_bars": dd})
full = pd.DataFrame(full)
rlab = {v: kk for kk, v in RUN_LABEL.items()}
full["days"] = full["run"].map(lambda r: DAYS[rlab[r]])
S = full.merge(S.drop(columns=["days"]), on=["kind", "strategy", "run", "dedup_bars"], how="left")
for c in ["trades", "n_R", "calls_signal", "calls_switch", "calls_events", "calls_funding", "hold_checks_15m",
          "signals_15m", "signals_30m", "moments"]:
    S[c] = S[c].fillna(0)
S.to_csv(os.path.join(W, "ai_trader_sim_runs.csv"), index=False)
agg = S.groupby(["kind", "strategy", "dedup_bars"]).agg(
    days=("days", "sum"), trades=("trades", "sum"), signals_15m=("signals_15m", "sum"),
    signals_30m=("signals_30m", "sum"), moments=("moments", "sum"), calls_signal=("calls_signal", "sum"),
    calls_switch=("calls_switch", "sum"), calls_events=("calls_events", "sum"), calls_funding=("calls_funding", "sum"),
    hold_checks_15m=("hold_checks_15m", "sum"), n_R=("n_R", "sum")).reset_index()
# strategies with no 15m/30m signal in v3b/v4 at all still need a row
for c in ["trades", "signals_15m", "signals_30m", "moments", "calls_signal", "calls_switch", "calls_events",
          "calls_funding", "hold_checks_15m"]:
    agg[c + "_per_day"] = agg[c] / agg["days"]
hold = x[x.status == "TRADED"].groupby(["kind", "strategy"])["hold_min"].mean().rename("mean_hold_min_replay")
agg = agg.merge(hold, on=["kind", "strategy"], how="left")
# flat share and scan calls
agg["busy_share"] = np.clip(agg["trades_per_day"] * agg["mean_hold_min_replay"].fillna(0) / 1440, 0, 1)
agg["calls_scan_per_day_ub"] = 6 * (1 - agg["busy_share"])
agg["calls_event_driven_per_day"] = (agg["calls_signal_per_day"] + agg["calls_switch_per_day"] +
                                     agg["calls_events_per_day"] + agg["calls_funding_per_day"])
agg["calls_with_scans_per_day"] = agg["calls_event_driven_per_day"] + agg["calls_scan_per_day_ub"]
agg["calls_with_15m_checks_per_day"] = agg["calls_with_scans_per_day"] + agg["hold_checks_15m_per_day"]
for c in ["calls_event_driven_per_day", "calls_with_scans_per_day", "calls_with_15m_checks_per_day"]:
    agg[c.replace("_per_day", "_per_month")] = 30 * agg[c]
agg["trades_per_month"] = 30 * agg["trades_per_day"]
# dollars per month for one trader (Sonnet 5.5 at $2 / $10 per MTok: ~10k input + 1k output = $0.030 per call
# uncached, ~$0.016 with 8k of the input read from cache at $0.20 / MTok; skill claude-api price table 2026-09-25)
for c in ["calls_event_driven_per_month", "calls_with_scans_per_month", "calls_with_15m_checks_per_month"]:
    agg[c.replace("calls_", "usd_lo_").replace("_per_month", "")] = 0.016 * agg[c]
    agg[c.replace("calls_", "usd_hi_").replace("_per_month", "")] = 0.030 * agg[c]

# analytic cross-check from the 5-year signal rate (moments per signal ratio taken from live)
F = pd.read_csv(os.path.join(W, "flow.csv"))
f = F[F["timeframe"].isin(["15m", "30m"]) & F["kind"].isin(["strategy", "ds200"])]
lam = f.groupby(["kind", "strategy"]).agg(ref5y_sig_per_day=("ref5y_per_day", "sum"),
                                          live_sig_per_day_all_runs=("sub_per_day_pooled", "sum")).reset_index()
agg = agg.merge(lam, on=["kind", "strategy"], how="left")
mps = (agg["moments"] / (agg["signals_15m"] + agg["signals_30m"]).replace(0, np.nan)).fillna(0.8)
agg["moments_per_signal"] = mps
h = agg["mean_hold_min_replay"].fillna(agg["mean_hold_min_replay"].median()) / 1440
l5 = agg["ref5y_sig_per_day"] * mps
agg["trades_per_day_5y_analytic"] = l5 / (1 + l5 * h)
la = agg["live_sig_per_day_all_runs"] * mps
agg["trades_per_day_live_analytic"] = la / (1 + la * h)
agg = agg.sort_values(["dedup_bars", "kind", "trades_per_day"], ascending=[True, True, False])
agg.to_csv(os.path.join(W, "ai_trader_15m30m.csv"), index=False)

pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 300)
a0 = agg[agg.dedup_bars == 0]
cols = ["kind", "strategy", "days", "signals_15m_per_day", "signals_30m_per_day", "moments_per_day", "trades_per_day",
        "trades_per_day_live_analytic", "trades_per_day_5y_analytic", "mean_hold_min_replay", "busy_share",
        "calls_signal_per_day", "calls_switch_per_day", "calls_events_per_day", "calls_funding_per_day",
        "calls_event_driven_per_day", "calls_with_scans_per_day", "calls_with_15m_checks_per_day"]
print(a0[cols].round(2).to_string())
for k in ("strategy", "ds200"):
    b = a0[a0.kind == k]
    print(k, "n", len(b), "median trades/day", round(b.trades_per_day.median(), 2),
          "share >= 1/day", round((b.trades_per_day >= 1).mean(), 2),
          "median event calls/day", round(b.calls_event_driven_per_day.median(), 1),
          "median calls w scans", round(b.calls_with_scans_per_day.median(), 1),
          "median calls w 15m checks", round(b.calls_with_15m_checks_per_day.median(), 1))
a4 = agg[agg.dedup_bars == 4]
print("dedup 4 bars: median signal calls/day", a4.groupby("kind").calls_signal_per_day.median().round(2).to_dict(),
      "vs dedup 0", a0.groupby("kind").calls_signal_per_day.median().round(2).to_dict())
