"""(docs/combo-bot-ko.md 3) What the combined bot would have done on the rule bot's 11 days (rb1016 export): same engine code
(paperbot.combo ComboEngine, rule_signal, flip_side, settings_of), signals submitted before the minute that opens at
their bar's close, as the runner does. Rule-bot members only (custom numbers need 60-100 days of history)."""
import sys, json, dataclasses
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import pandas as pd, numpy as np
from paperbot import combo as C
from paperbot.margin import Brackets
from paperbot.models import Bar

# usage: python3 analysis/live1019/combo_replay.py <the rule bot export's current/ folder> <output folder>
D = sys.argv[1].rstrip("/") + "/"
S = sys.argv[2].rstrip("/") + "/"
os.makedirs(S + "combo_replay", exist_ok=True)
EX = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                 "research", "fullgrid", "exchange.json")))
SYMS = C.V3_SYMBOLS
BR = {p["symbol"]: Brackets.from_binance(p) for p in EX["brackets"] if p["symbol"] in SYMS}
SPECS = {s: dict(EX["specs"][s]) for s in SYMS}
lb = pd.read_csv(D + "live_bars.csv")
sl = pd.read_csv(D + "signal_log.csv")
sl = sl[sl.status == "SUBMITTED"]
CTX = {}
for line in open(D + "signal_ctx.jsonl"):
    d = json.loads(line)
    st = (d.get("ctx") or {}).get("strength")
    if st is not None:
        CTX[int(d["id"])] = {"strength": st}
MIN = 60_000

minutes = {}
for r in lb.itertuples(index=False):
    if r.symbol in SYMS:
        minutes.setdefault(int(r.ts), {})[r.symbol] = Bar(r.symbol, int(r.ts), int(r.close_time), r.open, r.high, r.low,
                                                           r.close, r.mark_open, r.mark_high, r.mark_low, r.mark_close,
                                                           volume=r.volume)
TS = sorted(minutes)

OWNERS6 = [{"strategy": "V39_ALL", "tf": "1h"}, {"strategy": "OBV_S", "tf": "30m"}, {"strategy": "N24_DMI", "tf": "30m"},
           {"strategy": "N05_PSAR_POC", "tf": "30m"}, {"strategy": "S3_CMO_SANDWICH", "tf": "30m"},
           {"strategy": "OBV_S", "tf": "4h"}]


def run(members_spec, label, **kw):
    cfg = C.ComboConfig.from_dict(dict(paper_db="x", db="y", members=members_spec, telegram=False, **kw))
    members = C.resolve_members(cfg.members)
    st = C.settings_of(cfg)
    engines = {a: C.ComboEngine(st, BR, combo=cfg, symbol_specs=SPECS, book=a) for a in (C.ACCOUNT, C.FLIP_ACCOUNT)}
    want = {(m.name, m.tf): m for m in members}
    by_close = {}
    for r in sl.itertuples(index=False):
        m = want.get((r.strategy, r.timeframe))
        if m is None or r.symbol not in SYMS or pd.isna(r.atr) or pd.isna(r.ref_price):
            continue
        sig = C.rule_signal(cfg, m, {"bar_close": int(r.bar_close), "symbol": r.symbol, "side": int(r.side),
                                     "atr": float(r.atr), "ref_price": float(r.ref_price), "ref_time": int(r.ref_time),
                                     "delay_ms": int(r.delay_ms),
                                     "data": json.dumps({"ctx": CTX.get(int(r.id), {})})})
        by_close.setdefault(int(r.bar_close), []).append(sig)
    for ts in TS:
        for sig in by_close.pop(ts, []) if ts in by_close else []:
            for a, e in engines.items():
                e.submit(sig if a == C.ACCOUNT else dataclasses.replace(sig, side=C.flip_side(a, sig), meta=dict(sig.meta)))
        for e in engines.values():
            e.step(minutes[ts])
            # signals of a bar whose open minute is missing go in on the next minute (rare)
        late = [k for k in by_close if k < ts]
        for k in late:
            for sig in by_close.pop(k):
                for a, e in engines.items():
                    e.submit(sig if a == C.ACCOUNT else dataclasses.replace(sig, side=C.flip_side(a, sig), meta=dict(sig.meta)))
    out = {}
    for a, e in engines.items():
        tr = e.trades
        n = len(tr)
        rej = {}
        for o in e.outcomes:
            if o.status == "REJECTED":
                why = (o.detail.get("reasons") or [o.reason])[-1]
                key = "liq" if "liq" in why else ("fit" if "fit" in why else ("min" if "minimum" in why else o.reason))
                rej[key] = rej.get(key, 0) + 1
        skipped = sum(1 for o in e.outcomes if o.status == "SKIPPED" and o.reason.startswith("lower"))
        inpos = sum(1 for o in e.outcomes if o.status == "SKIPPED" and o.reason == "in position")
        # the live account: $100, executor qty = paper qty x 0.1, cut to $400 and to a $10 loss at the stop
        live = 0.0
        for t in tr:
            q_paper = t.qty
            q = q_paper * 0.1
            q = min(q, 400.0 / t.entry_price)
            per = abs(t.entry_price - t.stop_initial) * (1 + 0.0004) + t.entry_price * 0.001
            q = min(q, 10.0 / per)
            live += t.pnl * q / q_paper
        eq = [cfg.initial_equity] + [t.equity_after for t in tr]
        peak, mdd = eq[0], 0.0
        for x in eq:
            peak = max(peak, x); mdd = max(mdd, 1 - x / peak)
        out[a] = dict(label=label, trades=n, wins=sum(t.pnl > 0 for t in tr), ret_pct=100 * (e.wallet / cfg.initial_equity - 1),
                      maxdd_pct=100 * mdd, rejected=sum(rej.values()), rej=rej, collisions=skipped, in_position=inpos,
                      live_usd=live, by_strategy={})
        for t in tr:
            k = f"{t.strategy_id}@{t.timeframe}"
            b = out[a]["by_strategy"].setdefault(k, [0, 0, 0.0])
            b[0] += 1; b[1] += t.pnl > 0; b[2] += t.pnl
        if a == C.ACCOUNT:
            out[a]["exits"] = pd.Series([t.exit_reason for t in tr]).value_counts().to_dict() if tr else {}
            out[a]["lev"] = pd.Series([t.leverage for t in tr]).value_counts().to_dict() if tr else {}
            out[a]["sym"] = pd.Series([t.symbol for t in tr]).value_counts().to_dict() if tr else {}
            out[a]["avg_win_roe"] = float(np.mean([t.roe for t in tr if t.pnl > 0])) if tr else None
            out[a]["avg_loss_roe"] = float(np.mean([t.roe for t in tr if t.pnl <= 0])) if any(t.pnl <= 0 for t in tr) else None
    return out


rows = []
for lab, kw in [("2ATR (house)", dict(stop={"mode": "atr", "atr": 2.0})),
                ("2ATR pulled in to fit", dict(stop={"mode": "atr_fit", "atr": 2.0, "min_atr": 1.0})),
                ("ROE -50%", dict(stop={"mode": "roe", "roe": 0.5})),
                ("ROE -60%", dict(stop={"mode": "roe", "roe": 0.6}))]:
    res = run(OWNERS6, lab, **kw)
    for a, r in res.items():
        r["account"] = a
        rows.append(r)
        print(json.dumps(r, default=str))
json.dump(rows, open(S + "combo_replay/replay_owners6.json", "w"), default=str, indent=1)


# ---------------------------------------------------------------- fair version: choose on the first half, trade the second
SPLIT = 1791709200000            # 2026-10-11 09:00 UTC (18:00 KST), the halves of every other analysis
tr = pd.read_csv(D + "trades.csv")
acc = pd.read_csv(D + "accounts.csv")[["account_id", "kind"]]
tr = tr.merge(acc, on="account_id")
first = tr[(tr.kind == "strategy") & (tr.entry_time < SPLIT) & tr.timeframe.isin(["15m", "30m", "1h", "4h"])]
top = first.groupby("account_id").pnl.sum().sort_values(ascending=False).head(6)
print("first-half top 6:", top.round(0).to_dict())
chosen = [{"strategy": a.split("@")[0], "tf": a.split("@")[1]} for a in top.index]
TS_ALL = TS
TS = [t for t in TS_ALL if t >= SPLIT]
sl_all = sl
sl = sl_all[sl_all.bar_close >= SPLIT]
fair = []
for lab, kw in [("2ATR (house)", dict(stop={"mode": "atr", "atr": 2.0})),
                ("2ATR pulled in to fit", dict(stop={"mode": "atr_fit", "atr": 2.0, "min_atr": 1.0})),
                ("ROE -50%", dict(stop={"mode": "roe", "roe": 0.5}))]:
    for who, mem in (("first-half top 6", chosen), ("owners 6 (second half only)", OWNERS6)):
        res = run(mem, f"{who} | {lab}", **kw)
        for a, r in res.items():
            r["account"] = a
            fair.append(r)
            print(json.dumps({k: r[k] for k in ("label", "account", "trades", "wins", "ret_pct", "maxdd_pct", "rejected",
                                                 "collisions", "live_usd")}, default=str))
json.dump(fair, open(S + "combo_replay/replay_fair.json", "w"), default=str, indent=1)
