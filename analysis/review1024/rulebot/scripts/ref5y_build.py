#!/usr/bin/env python3
"""5-year reference per strategy x timeframe at the DEFAULT numbers and the house exits (what the rule bot runs),
taken from the full-grid report data (research/fullgrid/diag/strat_report.py -> strat_report.json, the numbers of
research/fullgrid/STRATEGIES_KO.md). One-time step; its output ref5y.csv is kept next to the report so the report can
be rebuilt without the full-grid work folder.

    python3 ref5y_build.py <strat_report.json> <out ref5y.csv>

Periods: select = 2021-01..2023-12 (the custom-value search looked at it), test = 2024-01..2026-09 (not looked at),
extra = 2020. 'mean' = net P&L of one trade as a fraction of the account at the live sizing (fees, slippage, funding
in); every signal counts as a trade. account_* = a $5,000 account, one position at a time, compounding, the bot's
leverage / liquidation / bust rules.

DeepSeek (kind ds): the owners' decision D11 hides DeepSeek money figures (STRATEGIES_KO.md does the same), so for
ds rows only trade counts, win rates, the SIGN of the per-trade mean (+1 / -1) and the account outcome class
(up / down / bust) are written; the money columns stay empty.
"""
import csv
import json
import sys

PER = ("select", "test", "extra")


def acct_class(a):
    if not a:
        return ""
    if a.get("bust"):
        return "bust"
    return "up" if a["final_x"] > 1 else "down"


def main(argv) -> int:
    src, out = argv
    rows = []
    for r in json.load(open(src)):
        d = r["default"]
        ds = r["kind"] == "ds"
        o = {"kind": "ds200" if ds else "strategy", "strategy": r["name"], "timeframe": r["tf"]}
        for p in PER:
            s = d["periods"].get(p) or {"n": 0}
            o[f"{p}_n"] = s.get("n", 0)
            o[f"{p}_win"] = s.get("win")
            m = s.get("mean")
            o[f"{p}_sign"] = (1 if m > 0 else -1) if m is not None and s.get("n", 0) else None
            for k in ("mean", "avg_win", "avg_loss", "payoff"):
                o[f"{p}_{k}"] = None if ds else s.get(k)
            a = (d.get("account") or {}).get(p)
            o[f"{p}_acct_class"] = acct_class(a)
            o[f"{p}_acct_trades"] = a.get("trades") if a else None
            o[f"{p}_acct_final_usd"] = None if ds or not a else 5000.0 * a["final_x"]
            o[f"{p}_acct_max_dd"] = None if ds or not a else a["max_dd"]
        for side in ("long", "short"):
            s = (d.get("sides") or {}).get(side) or {"n": 0}
            o[f"{side}_n_2126"] = s.get("n", 0)
            o[f"{side}_win_2126"] = s.get("win")
            o[f"{side}_mean_2126"] = None if ds else s.get("mean")
            m = s.get("mean")
            o[f"{side}_sign_2126"] = (1 if m > 0 else -1) if m is not None and s.get("n", 0) else None
        rows.append(o)
    cols = list(rows[0].keys())
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} rows -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
