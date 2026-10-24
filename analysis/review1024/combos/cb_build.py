"""Step 1 of the combinations review: one normalised trade table for both bots, and a per-signal replay of the rule
bot (what every strategy would have done on every signal, taken or not, with the house exits and the house sizing).

usage (run from this folder, without -I; pandas is not importable under -I here):
    python3 cb_build.py <rule bot export zip> <league export zip> <new empty work folder> [out folder]

Writes into the out folder (default: this folder):
    trades_all.csv     every closed trade of every account of both bots (bot, account, strategy, tf, kind, coin, side,
                       entry/exit time, roe after fees and funding, wallet_ret, ret_not, leverage, margin ...)
    accounts_all.csv   one row per account (bot, kind, start wallet, trades, realised end wallet)
    signals_sim.csv    rule bot: every submitted 15m-4h signal with the house-exit replay of its own side and of the
                       opposite side (the "coin-flip twin" at the same moment), at the leverage the house sizing picks
    build_meta.json    periods, file hashes, replay check against the real trades
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np
import pandas as pd

import cb_lib as L

RULE_MEMBERS = {f"current/{n}" for n in ("accounts.csv", "trades.csv", "outcomes.csv", "signal_log.csv",
                                         "signal_ctx.jsonl", "live_bars.csv", "runs.csv")} | {"manifest.txt"}
LEAGUE_MEMBERS = {"db/league_exits.db", "db/league_exits_start.json", "etc/candidates.json", "etc/rules.json",
                  "manifest.txt"}


def load_rule(folder: str):
    d = folder + "/current/"
    acc = pd.read_csv(d + "accounts.csv")
    t = pd.read_csv(d + "trades.csv", usecols=lambda c: c != "context")
    o = pd.read_csv(d + "outcomes.csv")
    sl = pd.read_csv(d + "signal_log.csv")
    bars = pd.read_csv(d + "live_bars.csv", usecols=["ts", "symbol", "open", "high", "low", "close", "close_time"])
    runs = pd.read_csv(d + "runs.csv")
    strength = {}
    with open(d + "signal_ctx.jsonl") as fh:
        for line in fh:
            x = json.loads(line)
            st = (x.get("ctx") or {}).get("strength")
            if st:
                strength[int(x["id"])] = st
    return acc, t, o, sl, bars, runs, strength


def norm_rule(acc: pd.DataFrame, t: pd.DataFrame) -> pd.DataFrame:
    kind = acc.set_index("account_id")["kind"]
    exits = acc.set_index("account_id")["data"].map(lambda s: json.loads(s).get("exits"))
    n = pd.DataFrame({
        "bot": "rule", "account": t.account_id, "pick": t.account_id, "strategy": t.strategy_id, "tf": t.timeframe,
        "kind": t.account_id.map(kind), "exits": t.account_id.map(exits), "coin": t.symbol, "side": t.side.astype(int),
        "signal_ts": t.signal_ts, "entry_time": t.entry_time, "exit_time": t.exit_time,
        "entry_price": t.entry_price, "exit_price": t.exit_price, "exit_reason": t.exit_reason,
        "leverage": t.leverage, "tier": t.tier, "margin": t.margin, "notional": t.qty * t.entry_price,
        "pnl": t.pnl, "fees": t.fees, "funding": t.funding, "roe": t.roe, "equity_after": t.equity_after,
    })
    n["is_coin"] = n.kind.eq("random")
    return n


def load_league(folder: str):
    c = L.open_ro(folder + "/db/league_exits.db")
    kv = dict(c.execute("SELECT k, v FROM kv").fetchall())
    meta = json.loads(kv.get("meta", "{}"))
    engines = json.loads(kv.get("engines", "{}"))
    recs = []
    for acct, _et, data in c.execute("SELECT account, exit_time, data FROM trades"):
        x = json.loads(data)
        x.pop("context", None)
        x["account"] = acct
        recs.append(x)
    c.close()
    return pd.DataFrame(recs), meta, engines


def split_league_id(a: str):
    pool, rest = a.split("-", 1)
    body, kind = rest.rsplit("-", 1)
    strat, tf, rank = body.rsplit("-", 2)
    return pool, strat, tf, int(rank), kind, f"{pool}-{strat}-{tf}-{rank}"


def norm_league(t: pd.DataFrame) -> pd.DataFrame:
    parts = t.account.map(split_league_id)
    n = pd.DataFrame({
        "bot": "league", "account": t.account, "pick": parts.map(lambda p: p[5]), "strategy": t.strategy_id,
        "tf": t.timeframe, "kind": parts.map(lambda p: p[4]), "exits": parts.map(lambda p: p[4]), "coin": t.symbol,
        "side": t.side.astype(int), "signal_ts": t.signal_ts, "entry_time": t.entry_time, "exit_time": t.exit_time,
        "entry_price": t.entry_price, "exit_price": t.exit_price, "exit_reason": t.exit_reason,
        "leverage": t.leverage, "tier": t.tier, "margin": t.margin, "notional": t.qty * t.entry_price,
        "pnl": t.pnl, "fees": t.fees, "funding": t.funding, "roe": t.roe, "equity_after": t.equity_after,
    })
    n["pool"] = parts.map(lambda p: p[0])
    n["is_coin"] = n.kind.isin(["ldc", "fqc"])
    return n


def finish(n: pd.DataFrame) -> pd.DataFrame:
    n = n.sort_values(["bot", "account", "exit_time"]).reset_index(drop=True)
    n["eq_before"] = n.equity_after - n.pnl
    n["wallet_ret"] = n.pnl / n.eq_before
    n["ret_not"] = n.pnl / n.notional
    n["hold_h"] = (n.exit_time - n.entry_time) / 3.6e6
    n["margin_frac"] = n.margin / n.eq_before.where(n.eq_before > 0)
    return n


def replay_signals(o: pd.DataFrame, sl: pd.DataFrame, strength: dict, bars: L.Bars, acc: pd.DataFrame):
    settings, levrule, sizing, br, specs = L.repo_imports()
    kind = acc.set_index("account_id")["kind"]
    sub = sl[sl.status == "SUBMITTED"][["id", "bar_close", "timeframe", "strategy", "symbol", "side"]]
    sub = sub.rename(columns={"id": "sig_id"})
    o = o.copy()
    o["bar_close"] = o.sig_ts + 1
    m = o.merge(sub, left_on=["bar_close", "sig_symbol", "sig_timeframe", "sig_strategy_id", "sig_side"],
                right_on=["bar_close", "symbol", "timeframe", "strategy", "side"], how="left", suffixes=("", "_sl"))
    m = m.drop_duplicates("id")
    m = m[m.sig_timeframe.isin(["15m", "30m", "1h", "4h"])].copy()
    out = []
    t0 = time.time()
    for r in m.itertuples(index=False):
        sym = r.sig_symbol
        if sym not in bars.d or not np.isfinite(r.ref_price):
            continue
        side = int(r.sig_side)
        stop_dist = r.stop_dist if np.isfinite(r.stop_dist) else abs(r.ref_price - r.sig_stop_price)
        st = strength.get(int(r.sig_id)) if np.isfinite(r.sig_id) else None
        sigd = {"strategy_id": r.sig_strategy_id, "timeframe": r.sig_timeframe, "symbol": sym, "ts": int(r.sig_ts),
                "meta": {"ctx": {"strength": st} if st else {}}}
        grp = levrule.signal_group(sigd)["group"]
        row = {"sig_id": int(r.id), "account": r.account_id, "strategy": r.sig_strategy_id, "tf": r.sig_timeframe,
               "kind": kind.get(r.account_id, ""), "coin": sym, "side": side, "bar_close": int(r.bar_close),
               "ref_price": float(r.ref_price), "atr": float(r.sig_atr), "stop_dist": float(stop_dist),
               "group": grp, "status": r.status, "reason": r.reason}
        for tag, sd in (("", side), ("f_", -side)):
            fill = r.ref_price * (1 + sd * L.SLIP)
            stop = r.ref_price - sd * stop_dist
            dec = sizing.size_position(settings, 5000.0, sd, fill, stop, grp, br[sym], atr=float(r.sig_atr),
                                       qty_step=specs[sym].get("qty_step", 0.0),
                                       min_notional=specs[sym].get("min_notional", 0.0))
            if not dec.ok:
                row.update({tag + "lev": np.nan, tag + "exit_time": np.nan, tag + "exit_price": np.nan,
                            tag + "exit_reason": "REJ", tag + "ret_not": np.nan, tag + "roe": np.nan})
                continue
            res = L.sim_house(bars, sym, int(r.bar_close), sd, fill, stop, dec.leverage)
            if res is None:
                row.update({tag + "lev": dec.leverage, tag + "exit_time": np.nan, tag + "exit_price": np.nan,
                            tag + "exit_reason": "NOBAR", tag + "ret_not": np.nan, tag + "roe": np.nan})
                continue
            et, ep, why, rn, roe = res
            row.update({tag + "lev": dec.leverage, tag + "exit_time": et, tag + "exit_price": ep,
                        tag + "exit_reason": why, tag + "ret_not": rn, tag + "roe": roe})
        out.append(row)
    s = pd.DataFrame(out)
    # wallet return at the house margin (margin share = leverage %, quality_v1 tiers 50/40/30/20)
    s["wallet_ret"] = s.roe * s.lev / 100.0
    s["f_wallet_ret"] = s.f_roe * s.f_lev / 100.0
    print(f"replayed {len(s)} signals in {time.time() - t0:.0f}s", flush=True)
    return s


def check_replay(s: pd.DataFrame, rt: pd.DataFrame) -> dict:
    """Compare the replay with the real closed trades of the same signals (house-exit accounts, 15m-4h)."""
    real = rt[(rt.exits == "house") & rt.tf.isin(["15m", "30m", "1h", "4h"])]
    j = s[s.status == "ENTERED"].merge(real, left_on=["account", "coin", "bar_close"],
                                         right_on=["account", "coin", "entry_time"], how="inner",
                                         suffixes=("", "_real"))
    j = j[j.exit_reason != "END"]
    same_lev = (j.lev == j.leverage).mean()
    same_exit = (np.abs(j.exit_time - j.exit_time_real) <= 60_000).mean()
    d_roe = (j.roe - j.roe_real)
    return {"matched_trades": int(len(j)), "real_closed_house_trades": int(len(real)),
            "same_leverage": float(same_lev), "same_exit_minute": float(same_exit),
            "roe_diff_median": float(d_roe.median()), "roe_diff_mean": float(d_roe.mean()),
            "roe_abs_diff_p90": float(d_roe.abs().quantile(0.9)),
            "share_abs_roe_diff_below_0.5pct": float((d_roe.abs() < 0.005).mean()),
            "real_mean_roe": float(j.roe_real.mean()), "replay_mean_roe": float(j.roe.mean()),
            "funding_mean_roe": float((j.funding / j.margin).mean())}


def main():
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    rule_zip, league_zip, work = sys.argv[1], sys.argv[2], sys.argv[3].rstrip("/")
    out = (sys.argv[4] if len(sys.argv) > 4 else L.HERE).rstrip("/")
    os.makedirs(out, exist_ok=True)
    rdir, ldir = work + "/rule", work + "/league"
    hashes = {}
    if not os.path.exists(rdir + "/current/trades.csv"):
        hashes["rule"] = L.safe_extract(rule_zip, rdir, RULE_MEMBERS)
    if not os.path.exists(ldir + "/db/league_exits.db"):
        hashes["league"] = L.safe_extract(league_zip, ldir, LEAGUE_MEMBERS)
    acc, rt, o, sl, bars_df, runs, strength = load_rule(rdir)
    lt, lmeta, engines = load_league(ldir)
    lstart = json.load(open(ldir + "/db/league_exits_start.json"))["start_ms"]

    trades = finish(pd.concat([norm_rule(acc, rt), norm_league(lt)], ignore_index=True))
    trades.to_csv(out + "/trades_all.csv", index=False, float_format="%.8g")

    # accounts (rule: accounts.csv; league: every engine in the DB, $1,000 each)
    ra = acc[["account_id", "strategy", "timeframe", "kind"]].rename(columns={"account_id": "account", "timeframe": "tf"})
    ra["bot"], ra["pick"], ra["start_wallet"], ra["is_coin"] = "rule", ra.account, 5000.0, ra.kind.eq("random")
    la = pd.DataFrame({"account": list(engines)})
    p = la.account.map(split_league_id)
    la["bot"], la["strategy"], la["tf"], la["kind"], la["pick"] = ("league", p.map(lambda x: x[1]), p.map(lambda x: x[2]),
                                                                  p.map(lambda x: x[4]), p.map(lambda x: x[5]))
    la["start_wallet"], la["is_coin"] = 1000.0, la.kind.isin(["ldc", "fqc"])
    la["open_position"] = [engines[a].get("position") is not None for a in la.account]
    accounts = pd.concat([ra, la], ignore_index=True)
    g = trades.groupby("account")
    accounts["n_trades"] = accounts.account.map(g.size()).fillna(0).astype(int)
    accounts["end_wallet_realised"] = accounts.account.map(g.equity_after.last())
    accounts["end_wallet_realised"] = accounts.end_wallet_realised.fillna(accounts.start_wallet)
    accounts["growth"] = accounts.end_wallet_realised / accounts.start_wallet - 1
    accounts.to_csv(out + "/accounts_all.csv", index=False)

    bars = L.Bars(bars_df)
    sig = replay_signals(o, sl, strength, bars, acc)
    for c in ("exit_time", "f_exit_time"):
        sig[c] = sig[c].astype("Int64")
    sig.to_csv(out + "/signals_sim.csv", index=False, float_format="%.8g")
    chk = check_replay(sig, trades[trades.bot == "rule"])
    print(json.dumps(chk, indent=1))

    meta = {
        "rule_zip": os.path.basename(rule_zip), "league_zip": os.path.basename(league_zip),
        "rule_zip_sha256": L.sha256_file(rule_zip), "league_zip_sha256": L.sha256_file(league_zip),
        "member_sha256": hashes,
        "rule_first_entry": int(rt.entry_time.min()), "rule_bars_end": int(bars.end),
        "rule_run_started": int(runs.started_ts.min()),
        "league_start": int(lstart), "league_done": int(lmeta.get("done", 0)),
        "n_trades": {b: int((trades.bot == b).sum()) for b in ("rule", "league")},
        "n_accounts": {b: int((accounts.bot == b).sum()) for b in ("rule", "league")},
        "open_positions_excluded": {"rule": int((o.status == "ENTERED").sum() - len(rt)),
                                    "league": int(la.open_position.sum())},
        "n_signals_replayed": int(len(sig)), "replay_check": chk,
    }
    json.dump(meta, open(out + "/build_meta.json", "w"), indent=1)
    print("done", out)


if __name__ == "__main__":
    main()
