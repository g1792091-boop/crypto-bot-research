"""vco step 3: paper vs live fills from the DBs (read-only, immutable): entry/exit bp vs paper, live fee rate, live
margin fraction, live ROE vs paper ROE. Run: python3 vco_exec.py <dir with live-ac.db and executor DBs>"""
import json, sqlite3, sys, os
import numpy as np, pandas as pd
D = sys.argv[1]
ro = lambda f: sqlite3.connect(f"file:{os.path.join(D, f)}?mode=ro&immutable=1", uri=True)
START = 1792591200000
c = ro("db__paperbot__combo__live-ac.db")
P = pd.DataFrame([json.loads(d) for (d,) in c.execute(
    "select data from trades where account_id='COMBO@mix' and entry_time >= ? order by entry_time", (START,))])
P["notional"] = P.qty * P.entry_price
P["fee_rate_side"] = P.fees / (P.qty * (P.entry_price + P.exit_price))
P["margin_frac"] = P.margin / (P.equity_after - P.pnl)
P["key"] = "COMBO@mix|" + P.symbol + "|" + P.entry_time.astype(str)
print(P[["symbol", "strategy_id", "timeframe", "side", "entry_price", "exit_price", "exit_reason", "roe", "fee_rate_side",
         "margin_frac", "leverage"]].to_string())
rows = []
for name, f in (("bybit", "db__paperbot__exec__executor-bybit-live.db"), ("woo", "db__paperbot__exec__executor-wooxpro-live.db")):
    e = ro(f)
    X = {k: (sym, side, qty, lev, ets, ep, xts, xr, pnl, json.loads(d)) for k, sym, side, qty, lev, ets, ep, xts, xr, pnl, d in
         e.execute("select key,symbol,side,qty,leverage,entry_ts,entry_price,exit_ts,exit_reason,pnl,data from trades")}
    F = pd.DataFrame([dict(json.loads(d), trade_key=k) for k, d in e.execute("select trade_key, data from fills")])
    FU = pd.DataFrame(e.execute("select trade_key, income from funding").fetchall(), columns=["trade_key", "income"])
    for _, p in P.iterrows():
        if p.key not in X:
            continue
        sym, side, qty, lev, ets, ep, xts, xr, pnl, d = X[p.key]
        f = F[F.trade_key == p.key].copy()
        for col in ("price", "qty", "commission"):
            f[col] = pd.to_numeric(f[col], errors="coerce")
        # opening fills: side same as position (Buy for long)
        is_buy = f.side.astype(str).str.upper().str.startswith(("BUY", "B"))
        op = f[is_buy == (side > 0)]; cl = f[is_buy != (side > 0)]
        e_px = np.average(op.price, weights=op.qty) if len(op) else np.nan
        x_px = np.average(cl.price, weights=cl.qty) if len(cl) else np.nan
        fees = f.commission.sum()
        fee_rate = fees / (op.qty * op.price).sum() / 2 if len(op) else np.nan
        fund = FU[FU.trade_key == p.key].income.sum()
        wb = d.get("wallet_before")
        margin = qty * ep / lev
        rows.append({"ex": name, "sym": sym, "member": f"{p.strategy_id}@{p.timeframe}", "side": side, "lev": lev,
                     "paper_lev": p.leverage, "entry_bp": 1e4 * side * (e_px / p.entry_price - 1),
                     "exit_bp": -1e4 * side * (x_px / p.exit_price - 1),
                     "fill_entry_vs_db": e_px / ep - 1, "fee_rate_side_pct": 100 * fee_rate,
                     "maker_fills": int(pd.Series(f.get("maker", pd.Series([], dtype=object))).astype(str).str.lower().isin(["true", "1"]).sum()),
                     "n_fills": len(f), "funding": fund, "margin_frac": margin / wb if wb else np.nan,
                     "live_roe": pnl / margin, "paper_roe": p.roe, "live_pct_wallet": 100 * pnl / wb if wb else np.nan,
                     "paper_pct_eq": 100 * p.pnl / (p.equity_after - p.pnl), "live_exit": xr, "paper_exit": p.exit_reason,
                     "delay_s": (ets - p.entry_time) / 1000})
R = pd.DataFrame(rows)
pd.set_option("display.width", 260)
print(R.round(4).to_string())
print(R.groupby("ex")[["entry_bp", "exit_bp", "fee_rate_side_pct", "live_roe", "paper_roe", "live_pct_wallet", "paper_pct_eq", "delay_s", "margin_frac"]].agg(["mean", "sum"]).round(4).T)
