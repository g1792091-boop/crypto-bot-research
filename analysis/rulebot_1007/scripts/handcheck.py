# Hand checks with the csv module only (independent of analyze.py's pandas code)
import csv, sys, math, statistics
B = sys.argv[1]; O = sys.argv[2]
def rows(p):
    with open(p, newline="") as fh:
        return list(csv.DictReader(fh))
# 1. R of single trades
tr = rows(f"{B}/current/trades.csv")
en = {(r["run"], r["id"]): r for r in rows(f"{O}/trades_enriched.csv")}
for tid in ("1", "2", "500"):
    t = next(r for r in tr if r["id"] == tid)
    side, q, e, s0, pnl = int(t["side"]), float(t["qty"]), float(t["entry_price"]), float(t["stop_initial"]), float(t["pnl"])
    R = pnl / (q * abs(e - s0))
    mfe = side * (float(t["mfe_price"]) - e) / abs(e - s0)
    cost_R = (float(t["fees"]) + float(t["funding"])) / (q * abs(e - s0))
    a = en[("current", tid)]
    print(f"trade {tid} {t['account_id']} {t['symbol']} side {side} {t['exit_reason']}: pnl {pnl:.4f} qty {q} entry {e} stop0 {s0}"
          f" -> R hand {R:.6f} vs analyze {float(a['R']):.6f}; mfe_R {mfe:.4f} vs {float(a['mfe_R']):.4f}; cost_R {cost_R:.4f} vs {float(a['cost_R']):.4f}")
    # pnl identity: gross - fees - funding
    gross = side * q * (float(t["exit_price"]) - e)
    print(f"   pnl identity: side*qty*(exit-entry) - fees - funding = {gross - float(t['fees']) - float(t['funding']):.6f} (recorded {pnl:.6f});"
          f" roe = pnl/margin = {pnl / float(t['margin']):.6f} (recorded {float(t['roe']):.6f})")
# 2. one account's statistics by hand
acc = "S2_ST_ROC@15m"
for run in ("run-20261005T014624Z",):
    g = sorted([r for r in rows(f"{B}/{run}/trades.csv") if r["account_id"] == acc], key=lambda r: (int(r["exit_time"]), int(r["id"])))
    Rs = [float(r["pnl"]) / (float(r["qty"]) * abs(float(r["entry_price"]) - float(r["stop_initial"]))) for r in g]
    pnls = [float(r["pnl"]) for r in g]
    wins = sum(p > 0 for p in pnls)
    eq = [float(g[0]["equity_after"]) - pnls[0]] + [float(r["equity_after"]) for r in g]
    peak, mdd = eq[0], 0.0
    for x in eq:
        peak = max(peak, x); mdd = max(mdd, 1 - x / peak)
    best = cur = 0
    for p in pnls:
        cur = cur + 1 if p <= 0 else 0; best = max(best, cur)
    wR = [x for x in Rs if x > 0]; lR = [x for x in Rs if x <= 0]
    pf = sum(p for p in pnls if p > 0) / -sum(p for p in pnls if p <= 0)
    a = next(r for r in rows(f"{O}/account_stats.csv") if r["run"] == run and r["account_id"] == acc)
    print(f"\n{run} {acc}: hand n {len(g)} wins {wins} pnl {sum(pnls):.2f} meanR {statistics.mean(Rs):.5f} medR {statistics.median(Rs):.5f}"
          f" payoff {statistics.mean(wR)/-statistics.mean(lR):.4f} PF {pf:.4f} maxconsec {best} realizedDD {mdd:.5f}")
    print(f"   analyze: n {a['n']} wins {a['wins']} pnl {float(a['pnl_sum']):.2f} meanR {float(a['mean_R']):.5f} medR {float(a['median_R']):.5f}"
          f" payoff {float(a['payoff']):.4f} PF {float(a['profit_factor']):.4f} maxconsec {a['max_consec_losses']} realizedDD {float(a['realized_max_dd']):.5f}")
# 3. replay: one signal the account entered, hand-compare replay ROE with the actual trade
rp = rows(f"{O}/replay_signals.csv")
x = next(r for r in rp if r["run"] == "current" and r["acct_status"] == "ENTERED" and r["acct_funding"] not in ("", "0.0") and r["status"] == "TRADED")
print(f"\nreplay (with funding) {x['account_id']} {x['symbol']} bar_close {x['bar_close']}: replay roe {x['roe']} exit {x['exit_reason']} {x['exit_time']}"
      f" | actual roe {x['acct_roe']} exit {x['acct_exit_reason']} {x['acct_exit_time']} funding {x['acct_funding']}")
y = next(r for r in rp if r["run"] == "current" and r["status"] == "TRADED" and r.get("flip_status") == "TRADED")
print(f"side flip {y['account_id']} {y['symbol']} side {y['side']}: R chosen {float(y['R']):.4f} ({y['exit_reason']}), R other side {float(y['flip_R']):.4f} ({y['flip_exit_reason']})")
