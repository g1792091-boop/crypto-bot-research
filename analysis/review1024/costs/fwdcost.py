"""Rule bot (v4 export) and league forward totals under the cost scenarios of frcost.py (analysis only).

Both files are paper records: the engine (paperbot/engine.py) fills market entries and market / stop exits 2 bp a side worse than the
raw price, charges the taker fee on each fill's notional (the export's fees are 5 bp a side; TP exits are maker 2 bp without
slippage), and pnl = side x qty x (exit - entry) - fees - funding paid. Here the modelled costs are removed (raw prices, no fees,
the recorded funding kept) and each scenario's costs charged on entry + exit notional at the raw prices (qty x price); the
payback scenarios give back 0.9 x commission x notional. Sizes stay as recorded (no wallet feedback).

The export is downloaded data: read as CSV only, never executed; run with python3 -I from a scratch folder:

    cd <scratch> && python3 -I -B <repo>/analysis/review1024/costs/fwdcost.py <export>/current/trades.csv \\
        <repo>/analysis/review1024/league/out/trades.csv <repo>/analysis/review1024/league/trades_norm.csv
    -> analysis/review1024/costs/fwdcost.json, fwdcost_table.csv"""
import os, sys
sys.path.append("/root/.local/lib/python3.11/site-packages")      # dateutil (dropped by -I)
import json
import numpy as np
import pandas as pd

OUTDIR = os.path.dirname(os.path.abspath(__file__))
SLIP0 = 0.0002                                                       # paperbot/config.py slippage_frac
SCEN = {"A": (0.00042, 0.00020, 0.9), "B": (0.00042, 0.00020, 0.0), "C": (0.000421, 0.000437, 0.9),
        "D": (0.000421, 0.000437, 0.0), "E": (0.000441, 0.000139, 0.0)}
SCEN_KO = {"A": "가정 + 페이백", "B": "가정, 페이백 없음", "C": "WOO 실측 + 페이백", "D": "WOO 실측", "E": "바이비트 실측"}


def scen_totals(direction, funding, notional, n):
    out = {}
    for sc, (f, s, p) in SCEN.items():
        cost = notional * (f + s)
        back = notional * f * p
        pnl = direction - funding - cost + back
        out[sc] = {"label": SCEN_KO[sc], "total": round(float(pnl.sum()), 0), "cost": round(float(cost.sum()), 0),
                   "payback": round(float(back.sum()), 0), "per_trade": round(float(pnl.mean()), 2),
                   "win": round(float((pnl > 0).mean()), 4), "n": int(n)}
    return out


def rulebot(path):
    t = pd.read_csv(path, usecols=lambda c: c != "context")
    s = t.side.to_numpy(float)
    q = t.qty.to_numpy(float)
    tp = (t.exit_reason == "TP").to_numpy()
    assert not (t.exit_reason == "LIQ").any()
    e_raw = t.entry_price.to_numpy(float) / (1 + s * SLIP0)
    x_raw = np.where(tp, t.exit_price.to_numpy(float), t.exit_price.to_numpy(float) / (1 - s * SLIP0))
    chk = s * q * (t.exit_price - t.entry_price) - t.fees - t.funding - t.pnl
    assert float(np.abs(chk).max()) < 1e-6
    notional = q * (e_raw + x_raw)
    fee_rate = (t.fees / (q * (t.entry_price + t.exit_price))).to_numpy()
    direction = s * q * (x_raw - e_raw)
    slip = (t.qty * t.entry_price - q * e_raw) * s + (q * x_raw - t.qty * t.exit_price) * s
    rec = {"trades": int(len(t)), "accounts": int(t.account_id.nunique()), "recorded_total": round(float(t.pnl.sum()), 0),
           "recorded_fees": round(float(t.fees.sum()), 0), "recorded_slippage": round(float(np.asarray(slip).sum()), 0),
           "funding_paid": round(float(t.funding.sum()), 0), "direction_before_costs": round(float(direction.sum()), 0),
           "notional_entry_plus_exit": round(float(notional.sum()), 0),
           "fee_rate_bp_median": {r: round(float(np.median(fee_rate[(t.exit_reason == r).to_numpy()]) * 1e4), 2) for r in ("SL", "LOCK", "TP")},
           "exit_reasons": t.exit_reason.value_counts().to_dict()}
    return rec, scen_totals(direction, t.funding.to_numpy(float), notional, len(t))


def league(path, norm_path):
    L = pd.read_csv(path)
    need = {"fees", "slip_cost", "funding", "gross", "pnl", "exit_reason", "margin", "leverage"}
    miss = need - set(L.columns)
    if miss:
        return {"missing_columns": sorted(miss)}, None
    N = pd.read_csv(norm_path)
    key = ["account", "entry_time", "exit_time"]
    N = N.rename(columns={"account_id": "account", "entry_ms": "entry_time", "exit_ms": "exit_time"})[key + ["entry_price", "exit_price", "side"]]
    M = L.merge(N, on=key, how="left", suffixes=("", "_n"), validate="one_to_one")
    assert M.entry_price.notna().all() and len(M) == len(L)
    s = M.side.to_numpy(float)
    tp = (M.exit_reason == "TP").to_numpy()
    # lg_lib.enrich: slip_cost = SLIP x qty x entry + SLIP x qty x exit (exit only when not TP): qty from that and the prices
    pe, px = M.entry_price.to_numpy(float), M.exit_price.to_numpy(float)
    q = M.slip_cost.to_numpy(float) / (SLIP0 * (pe + np.where(tp, 0.0, px)))
    e_raw = pe / (1 + s * SLIP0)
    x_raw = np.where(tp, px, px / (1 - s * SLIP0))
    direction = s * q * (x_raw - e_raw)
    notional = q * (e_raw + x_raw)
    chk_gross = float(np.abs(s * q * (px - pe) - (M.pnl + M.fees + M.funding)).max())
    rec = {"trades": int(len(M)), "accounts": int(M.account.nunique()), "recorded_total": round(float(M.pnl.sum()), 0),
           "recorded_fees": round(float(M.fees.sum()), 0), "recorded_slippage": round(float(M.slip_cost.sum()), 0),
           "funding_paid": round(float(M.funding.sum()), 0), "gross_column": round(float(M.gross.sum()), 0),
           "direction_before_costs": round(float(direction.sum()), 0), "notional_entry_plus_exit": round(float(notional.sum()), 0),
           "max_abs_price_pnl_check": chk_gross, "qty_vs_margin_x_lev_median": round(float(np.median(q * pe / (M.margin * M.leverage))), 4),
           "exit_reasons": M.exit_reason.value_counts().to_dict()}
    return rec, scen_totals(direction, M.funding.to_numpy(float), notional, len(M))


def main():
    rb_rec, rb = rulebot(sys.argv[1])
    lg_rec, lg = league(sys.argv[2], sys.argv[3])
    res = {"rulebot_v4": {"record": rb_rec, "scenarios": rb}, "league": {"record": lg_rec, "scenarios": lg}}
    rows = [{"book": b, "scenario": sc, **v} for b, d in (("rulebot_v4", rb), ("league", lg)) if d for sc, v in d.items()]
    pd.DataFrame(rows).to_csv(os.path.join(OUTDIR, "fwdcost_table.csv"), index=False)
    json.dump(res, open(os.path.join(OUTDIR, "fwdcost.json"), "w"), ensure_ascii=False, indent=1, default=float)
    for b, d in res.items():
        print("==", b, d["record"], flush=True)
        for sc, v in (d["scenarios"] or {}).items():
            print(f"  {sc} {v['label']:12s} total {v['total']:>12,.0f}  cost {v['cost']:>10,.0f}  payback {v['payback']:>9,.0f}  per trade {v['per_trade']:+.2f}  win {v['win']}", flush=True)


if __name__ == "__main__":
    main()
