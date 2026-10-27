#!/usr/bin/env python3
"""OBV 추세형 study (PLAN.md section 7): the recent weeks on 1m bars with mark prices, and the real records.

    python3 -E -P forward.py --work WORK --m1 M1DIR --export EXPORT --league LEAGUE_TRADES --out OUT

- parity_rulebot.csv: the rule bot's OBV_S@30m / @1h trades (export to 2026-10-25) next to the replay with RBX, once
  from the bot's own logged signals (ref price, ATR, best group) and once from this study's signals;
- parity_league.json: every OBV entry of the candidate league export (all its account kinds share the signals) found
  among this study's CV30 / CV1h / CV4h signals;
- recent.csv: the four cells (+ the 4h references) x RBX / CVX / TBX (and the picks of run.py when OUT/picks.json is
  there) over 2026-10-01 / 10-06 / 10-13 .. 10-26 end, on 1m bars.
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import obvsim as O  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ACCOUNTS = {"RB30": "OBV_S@30m", "RB1h": "OBV_S@1h"}
LEAGUE = {"CV30": "core-OBV_S-30m-2", "CV1h": "core-OBV_S-1h-3", "CV4h": "core-OBV_S-4h-1"}


def logged_signals(export: str, tf: str) -> pd.DataFrame:
    from paperbot.daily3 import make_signal
    from paperbot.levrule import signal_group
    cur = os.path.join(export, "current")
    sig = pd.read_csv(os.path.join(cur, "signal_log.csv"), low_memory=False)
    s = sig[(sig["strategy"] == "OBV_S") & (sig["timeframe"] == tf) & (sig["status"] == "SUBMITTED")]
    ids = set(int(x) for x in s["id"])
    ctx = {}
    with open(os.path.join(cur, "signal_ctx.jsonl")) as fh:
        for line in fh:
            d = json.loads(line)
            if int(d.get("id", -1)) in ids:
                ctx[int(d["id"])] = d.get("ctx")
    rows = []
    for r in s.itertuples(index=False):
        d = {"sig_id": int(r.id), "bar_close": int(r.bar_close), "timeframe": r.timeframe, "strategy": r.strategy,
             "symbol": r.symbol, "side": int(r.side), "atr": float(r.atr), "ref_price": float(r.ref_price),
             "ref_time": int(r.ref_time), "delay_ms": int(r.delay_ms)}
        c = ctx.get(int(r.id))
        d["data"] = {"ctx": c} if c else {}
        rows.append({"symbol": r.symbol, "close_ms": int(r.bar_close), "side": int(r.side), "atr": float(r.atr),
                     "ref": float(r.ref_price), "best": signal_group(make_signal(d))["group"] == "best"})
    prio = {s_: k for k, s_ in enumerate(O.SYMBOLS)}
    G = pd.DataFrame(rows)
    G["prio"] = G["symbol"].map(prio)
    return G.sort_values(["close_ms", "prio"]).reset_index(drop=True)


def match(real: pd.DataFrame, T: pd.DataFrame) -> pd.DataFrame:
    a = real[["symbol", "side", "entry_time", "exit_time", "exit_reason", "leverage", "pnl"]].rename(
        columns={"entry_time": "entry_ts", "exit_time": "exit_real", "exit_reason": "reason_real", "leverage": "lev_real",
                 "pnl": "pnl_real"})
    b = T[["symbol", "side", "entry_ts", "exit_ts", "reason", "lev", "pnl"]].rename(
        columns={"exit_ts": "exit_rep", "reason": "reason_rep", "lev": "lev_rep", "pnl": "pnl_rep"})
    return a.merge(b, on=["symbol", "side", "entry_ts"], how="outer", indicator=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--m1", required=True)
    ap.add_argument("--export", required=True)
    ap.add_argument("--league", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    B = O.Book.minute(a.m1, a.work)
    cells = pickle.load(open(os.path.join(a.work, "signals.pkl"), "rb"))["cells"]
    tr = pd.read_csv(os.path.join(a.export, "current", "trades.csv"), low_memory=False)
    end_export = int(tr["exit_time"].max()) + 1
    par, summary = [], {}
    for c, acct in ACCOUNTS.items():
        real = tr[tr["account_id"] == acct].sort_values("entry_time")
        tf = cells[c]["tf"].iloc[0]
        GL = logged_signals(a.export, tf)
        T1 = B.account(GL, O.RBX, "bin", 5000.0, 10.0, raw_px=GL["ref"].to_numpy(float))
        G = cells[c]
        g = G[(G["close_ms"] >= GL["close_ms"].min()) & (G["close_ms"] <= GL["close_ms"].max())].reset_index(drop=True)
        T2 = B.account(g, O.RBX, "bin", 5000.0, 10.0)
        for label, T in (("bot_signals", T1), ("study_signals", T2)):
            T = T[T["entry_ts"] < end_export]
            m = match(real, T)
            m.insert(0, "cell", c)
            m.insert(1, "from", label)
            par.append(m)
            both = m[m["_merge"] == "both"]
            summary[f"{c}|{label}"] = {
                "real_trades": int(len(real)), "replay_trades": int(len(T)), "same_entry": int(len(both)),
                "same_reason": int((both["reason_real"] == both["reason_rep"]).sum()),
                "same_lev": int((both["lev_real"] == both["lev_rep"]).sum()),
                "pnl_real": float(real["pnl"].sum()), "pnl_replay_same": float(both["pnl_rep"].sum()),
                "pnl_real_same": float(both["pnl_real"].sum()),
                "max_abs_pnl_diff": float((both["pnl_rep"] - both["pnl_real"]).abs().max()) if len(both) else None}
    pd.concat(par, ignore_index=True).to_csv(os.path.join(a.out, "parity_rulebot.csv"), index=False)
    # league: entries of all kinds of each candidate among this study's signals (entry minute = the signal close)
    lg = pd.read_csv(a.league)
    lp = {}
    for c, pre in LEAGUE.items():
        x = lg[lg["account_id"].str.startswith(pre + "-")]
        keys = set(zip(x["symbol"], x["entry_ms"].astype(np.int64), x["side"].astype(int)))
        G = cells[c]
        mine = set(zip(G["symbol"], G["close_ms"].astype(np.int64), G["side"].astype(int)))
        flip = set((s, t, -d) for s, t, d in mine)
        lp[c] = {"league_entries": len(keys), "found": len(keys & mine), "found_as_coin_flip_twin": len((keys - mine) & flip),
                 "missing": sorted(str(k) for k in keys - mine - flip)[:10]}
    json.dump({"rulebot": summary, "league": lp}, open(os.path.join(a.out, "parity.json"), "w"), ensure_ascii=False,
              indent=1)
    # recent windows on 1m bars
    picks = {}
    pj = os.path.join(a.out, "picks.json")
    if os.path.exists(pj):
        d = json.load(open(pj))
        picks = {c: v["picked"] for c, v in d["verdict"].items() if v.get("picked")}
    rows = []
    for c in ("RB30", "RB1h", "CV30", "CV1h", "RB4h", "CV4h"):
        G = cells[c]
        setups = [("RBX", "F0", O.RBX, "bin")] + ([("CVX", "F0", O.CVX[c], "bin")] if c in O.CVX else []) + \
                 [("TBX", "F0", O.EXITS["T0"], "tb")]
        if c in picks:
            _c, f, x = picks[c].split("|")
            setups.append((f"pick:{f}|{x}", f, O.EXITS[x], "tb"))
        for name, f, v, mode in setups:
            for p in ("oct", "rbwin", "lgwin"):
                lo, hi = O.PERIODS[p]
                m = (G["close_ms"] >= lo) & (G["close_ms"] < hi) & G[f].astype(bool)
                start, bust = (50.0, 1.0) if mode == "tb" else (5000.0, 10.0)
                T = B.account(G[m].reset_index(drop=True), v, mode, start, bust)
                st = O.stats(T, start, bust)
                rows.append({"cell": c, "setup": name, "period": p, **st,
                             "open_at_end": int((T["reason"] == "OPEN").sum()) if len(T) else 0})
    pd.DataFrame(rows).to_csv(os.path.join(a.out, "recent.csv"), index=False)
    print(json.dumps({"rulebot": summary, "league": lp}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
