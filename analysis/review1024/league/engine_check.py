"""Check that fivey.py's way of driving the league engine on archive bars reproduces the real forward league.

    python3 engine_check.py --data FG1M_DIR --market-cache MARKET_DIR --league-db WORK/league/db/league_exits.db \
        --cands WORK/league/etc/candidates.json --rules WORK/league/etc/rules.json --accounts id,id,... --work NEW_DIR

It replays the chosen accounts from the league's start to the end of the public archive (data.binance.vision daily 1m files,
the same bars market.py caches) with the five-year archive (to 2026-09) in front for the indicators' warm-up, and compares
each trade with the league's own record: entry minute, side, exit minute, exit reason and money. Known small gaps: October
mark prices are taken as last prices and October funding as zero (both only move money by cents unless a liquidation is near).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

import numpy as np
import pandas as pd

import fivey as F
import lg_lib as L
import market as M


def extend(mins: F.Minutes, cache: str, d0: str, d1: str) -> None:
    bars, missing = M.load(d0, d1, cache)
    for s, df in bars.items():
        d = mins.c[s]
        keep = df["t"].values > d["ts"][-1]
        df = df[keep & (df["v"].values > 0)]
        n = len(df)
        add = {"ts": df["t"].values.astype(np.int64), "o": df["o"].values, "h": df["h"].values, "l": df["l"].values,
               "c": df["c"].values, "v": df["v"].values, "mo": df["o"].values, "mh": df["h"].values, "ml": df["l"].values,
               "mc": df["c"].values, "fund": np.zeros(n)}
        for k in d:
            d[k] = np.concatenate([d[k], add[k]])
    # rebuild 5m bars
    tmp = F.Minutes.__new__(F.Minutes)
    tmp.c = mins.c
    five = {}
    for s, d in mins.c.items():
        b = d["ts"] // 300_000
        starts = np.r_[0, np.flatnonzero(np.diff(b)) + 1]
        ends = np.r_[starts[1:], len(b)]
        five[s] = (b[starts] * 300_000, d["o"][starts], np.maximum.reduceat(d["h"], starts), np.minimum.reduceat(d["l"], starts),
                   d["c"][ends - 1], np.add.reduceat(d["v"], starts))
    mins.five = five


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--market-cache", required=True)
    ap.add_argument("--league-db", required=True)
    ap.add_argument("--cands", required=True)
    ap.add_argument("--rules", required=True)
    ap.add_argument("--accounts", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out")
    a = ap.parse_args()
    from candleague import rulex as RX
    from paperbot.config import V3_SYMBOLS
    db = L.load_db(a.league_db)
    start = int(db["meta"]["start_ms"])
    cands = L.read_json(a.cands)["candidates"]
    cfg = RX.load_config(a.rules)
    all_accts = {x["id"]: x for x in RX.accounts(cands, cfg)}
    want = set(a.accounts.split(","))
    accts = [all_accts[x] for x in all_accts if x in want]
    mins = F.Minutes(a.data, V3_SYMBOLS)
    last_day = dt.datetime.fromtimestamp(db["meta"]["done"] / 1000, dt.timezone.utc).date()
    extend(mins, a.market_cache, "2026-10-01", last_day.isoformat())
    end = int(min(d["ts"][-1] + 60_000 for d in mins.c.values()) // L.DAY_MS * L.DAY_MS)      # end of the last whole UTC day in the archive
    os.makedirs(a.work, exist_ok=True)
    t, _st = F.run_window(accts, mins, start, end, os.path.join(a.work, "check.db"))
    real = db["trades"]
    real = real[real["account"].isin(want) & (real["exit_time"] < end)]
    key = ["account", "entry_time", "symbol", "side"]
    m = real.merge(t, on=key, how="outer", suffixes=("_real", "_replay"), indicator=True)
    both = m[m["_merge"] == "both"]
    out = {"accounts": sorted(want), "start_ms": start, "end_ms": end, "real": int(len(real)), "replay": int(len(t)),
           "matched": int(len(both)), "only_real": int((m["_merge"] == "left_only").sum()),
           "only_replay": int((m["_merge"] == "right_only").sum()),
           "same_exit_minute": int((both["exit_time_real"] // 60000 == both["exit_time_replay"] // 60000).sum()),
           "same_reason": int((both["exit_reason_real"] == both["exit_reason_replay"]).sum()),
           "max_abs_pnl_diff": float((both["pnl_real"] - both["pnl_replay"]).abs().max()) if len(both) else None,
           "sum_pnl_real": float(real["pnl"].sum()), "sum_pnl_replay": float(t["pnl"].sum()) if len(t) else 0.0}
    un = m[m["_merge"] != "both"]
    out["unmatched"] = [{"side_of": ("실제에만" if r_["_merge"] == "left_only" else "다시 돌린 쪽에만"), "account": r_["account"], "symbol": r_["symbol"],
                         "side": int(r_["side"]), "entry_time": int(r_["entry_time"])} for _i, r_ in un.iterrows()]
    diff = both[(both["exit_time_real"] // 60000 != both["exit_time_replay"] // 60000) | ((both["pnl_real"] - both["pnl_replay"]).abs() > 1)]
    out["differences"] = diff[["account", "symbol", "side", "entry_time", "exit_time_real", "exit_time_replay", "exit_reason_real",
                               "exit_reason_replay", "pnl_real", "pnl_replay"]].to_dict("records")
    print(json.dumps(L.jsonable(out), indent=1))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(L.jsonable(out), f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
