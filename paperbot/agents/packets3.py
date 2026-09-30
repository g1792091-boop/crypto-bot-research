"""Data packets for the paper v3 agent team (roster3.py). Built by code only.

Agents never query the databases: every number they may cite is in their packet, and each
claim must cite the packet path it came from (roles.check_output). The packet is computed
from paper3.db (live runner, read-only) and daily3.db (nightly checks, read-only).

Sections
- meta            rules version, units, minimum sample, day count since the start
- league          per timeframe: strategy accounts vs the three coin-flip accounts
- pass_check      the docs/paper-v3-rules.md criteria applied to every strategy account
- by_strategy     one strategy across its five timeframes (for the timeframe comparison)
- by_coin         trades and net ROE per coin, and per strategy x coin for accounts with >= min_n
- execution       signal-to-fill delay, signal statuses, fees and funding share of losses
- exits           how trades ended: stop / lock level / liquidation, leverage mix
- today           trades closed in the last 24 hours, busts, alerts
- nightly         latest nightly report: replay parity, shadows, data quality

``specialist_packet(packet, strategy)`` narrows a packet to one strategy for its specialist
and adds that strategy's profile card (5-year character under the v3 rules, built by
research/strategy_profiles/report.py): trend-following or mean-reverting, holding length,
whether the profit lock cut winners early, per timeframe.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import statistics
from collections import Counter, defaultdict
from typing import Optional

DAY_MS = 86_400_000
INITIAL = 1000.0
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CARDS = os.path.join(ROOT, "research", "strategy_profiles", "out", "cards.json")
TRADE_TFS = ("5m", "15m", "30m", "1h", "4h")


def _ro(path: str) -> Optional[sqlite3.Connection]:
    if not path or not os.path.exists(path):
        return None
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def _r(x, n=4):
    return None if x is None else round(float(x), n)


def _median(xs):
    return statistics.median(xs) if xs else None


def build(paper_db: str, daily_db: Optional[str], now_ms: int, min_n: int = 30) -> dict:
    c = _ro(paper_db)
    if c is None:
        raise FileNotFoundError(paper_db)
    accts = {r["account_id"]: dict(r) for r in c.execute("SELECT * FROM accounts")}
    st = c.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()
    eng = json.loads(st["data"])["engines"] if st else {}
    run = c.execute("SELECT data FROM state WHERE k = 'run'").fetchone()
    run = json.loads(run["data"]) if run else {}
    trades = [dict(r) for r in c.execute(
        "SELECT account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, equity_after, data "
        "FROM trades ORDER BY id")]
    for t in trades:
        d = json.loads(t.pop("data"))
        t.update(side=d["side"], fees=d["fees"], funding=d["funding"], lock_roe=d.get("lock_roe"),
                 margin=d["margin"], price_move=d["price_move"])
    start = min((a["created_ts"] for a in accts.values()), default=now_ms)
    days = (now_ms - start) / DAY_MS

    def wallet(aid):
        return float(eng.get(aid, {}).get("wallet", INITIAL))

    by_acct = defaultdict(list)
    for t in trades:
        by_acct[t["account_id"]].append(t)

    # ------------------------------------------------ league and pass check
    league, pass_check = {}, {}
    for tf in TRADE_TFS:
        ids = [a for a, v in accts.items() if v["timeframe"] == tf]
        rnd = {a: wallet(a) for a in ids if accts[a]["kind"] == "random"}
        strat = [a for a in ids if accts[a]["kind"] == "strategy"]
        best_rnd = max(rnd.values()) if rnd else None
        ws = [wallet(a) for a in strat]
        league[tf] = {
            "strategy_accounts": len(strat), "coin_flip_wallets": {k: _r(v, 2) for k, v in rnd.items()},
            "median_wallet": _r(_median(ws), 2), "above_start": sum(w > INITIAL for w in ws),
            "beat_all_coin_flips": sum(best_rnd is not None and wallet(a) > best_rnd and not eng.get(a, {}).get("bust")
                                       for a in strat),
            "bust": sum(bool(eng.get(a, {}).get("bust")) for a in strat),
            "open_positions": sum(bool(eng.get(a, {}).get("position")) for a in ids),
        }
        for a in strat:
            n = len(by_acct[a])
            w = wallet(a)
            ok = n >= min_n and w > INITIAL and best_rnd is not None and w > best_rnd and not eng.get(a, {}).get("bust")
            pass_check[a] = {"trades": n, "wallet": _r(w, 2),
                             "beats_coin_flips": best_rnd is not None and w > best_rnd and not eng.get(a, {}).get("bust"),
                             "bust": bool(eng.get(a, {}).get("bust")),
                             "status": "undecided_small_sample" if n < min_n else ("first_pass" if ok else "fail")}

    # ------------------------------------------------ one strategy across timeframes
    by_strategy = defaultdict(dict)
    for a, v in accts.items():
        if v["kind"] != "strategy":
            continue
        ts = by_acct[a]
        by_strategy[v["strategy"]][v["timeframe"]] = {
            "wallet": _r(wallet(a), 2), "trades": len(ts),
            "mean_roe": _r(statistics.fmean([t["roe"] for t in ts])) if ts else None,
            "win_rate": _r(sum(t["pnl"] > 0 for t in ts) / len(ts)) if ts else None,
        }

    # ------------------------------------------------ coins
    by_coin = {}
    for sym in sorted({t["symbol"] for t in trades}):
        ts = [t for t in trades if t["symbol"] == sym and accts[t["account_id"]]["kind"] == "strategy"]
        rs = [t for t in trades if t["symbol"] == sym and accts[t["account_id"]]["kind"] == "random"]
        by_coin[sym] = {"strategy_trades": len(ts), "strategy_mean_roe": _r(statistics.fmean([t["roe"] for t in ts])) if ts else None,
                        "coin_flip_trades": len(rs), "coin_flip_mean_roe": _r(statistics.fmean([t["roe"] for t in rs])) if rs else None}

    # ------------------------------------------------ execution and costs
    sig = [dict(r) for r in c.execute("SELECT timeframe, status, COUNT(*) AS n, AVG(delay_ms) AS avg_delay, "
                                      "MAX(delay_ms) AS max_delay FROM signal_log GROUP BY timeframe, status")]
    losses = [t for t in trades if t["pnl"] < 0]
    execution = {
        "signals": [{k: (_r(v, 1) if k.endswith("delay") else v) for k, v in s.items()} for s in sig],
        "fees_total": _r(sum(t["fees"] for t in trades), 2), "funding_total": _r(sum(t["funding"] for t in trades), 2),
        "net_pnl_total": _r(sum(t["pnl"] for t in trades), 2),
        "cost_share_of_losses": _r(sum(t["fees"] + t["funding"] for t in losses) / abs(sum(t["pnl"] for t in losses)))
        if losses and sum(t["pnl"] for t in losses) else None,
    }
    outcomes = Counter()
    for r in c.execute("SELECT status, reason, COUNT(*) AS n FROM outcomes GROUP BY status, reason"):
        outcomes[f"{r['status']}:{re.sub(r'[-+]?[0-9][0-9.]*', '#', r['reason'])[:40]}"] += r["n"]
    execution["signal_outcomes"] = dict(outcomes.most_common(12))

    # ------------------------------------------------ exits
    reasons = Counter(t["exit_reason"] for t in trades)
    locks = Counter(f"+{round(t['lock_roe'] * 100)}%" for t in trades if t["exit_reason"] == "LOCK" and t["lock_roe"])
    exits = {"reasons": dict(reasons), "lock_levels": dict(locks), "leverage": dict(Counter(t["leverage"] for t in trades)),
             "mean_roe_by_reason": {k: _r(statistics.fmean([t["roe"] for t in trades if t["exit_reason"] == k]))
                                    for k in reasons},
             "win_rate": _r(sum(t["pnl"] > 0 for t in trades) / len(trades)) if trades else None}

    # ------------------------------------------------ last 24 hours
    since = now_ms - DAY_MS
    today = [t for t in trades if t["exit_time"] >= since]
    alerts = [dict(r) for r in c.execute("SELECT ts, level, text FROM alerts WHERE ts >= ? AND level != 'INFO' "
                                         "ORDER BY rowid DESC LIMIT 40", (since,))]
    today_sec = {"trades": len(today), "net_pnl": _r(sum(t["pnl"] for t in today), 2),
                 "wins": sum(t["pnl"] > 0 for t in today),
                 "busts_total": sum(bool(e.get("bust")) for e in eng.values()),
                 "biggest_losses": [{k: t[k] for k in ("account_id", "symbol", "leverage", "exit_reason", "roe", "pnl")}
                                    for t in sorted(today, key=lambda t: t["pnl"])[:5]],
                 "alerts": alerts}
    c.close()

    # ------------------------------------------------ nightly checks
    nightly = None
    d = _ro(daily_db)
    if d is not None:
        r = d.execute("SELECT day, data FROM reports ORDER BY day DESC LIMIT 1").fetchone()
        if r:
            nightly = json.loads(r["data"])
            nightly["mismatched_accounts"] = [m["account_id"] for m in d.execute(
                "SELECT account_id FROM mismatches WHERE day = ?", (r["day"],))]
        d.close()

    return {
        "meta": {"rules": "docs/paper-v3-rules.md", "settings_version": run.get("settings"), "min_n": min_n,
                 "days_running": _r(days, 2), "units": {"roe": "net return on isolated margin (0.10 = +10%)",
                                                        "wallet": "USDT, each account starts at 1000"},
                 "accounts": len(accts)},
        "league": league, "pass_check": pass_check, "by_strategy": dict(by_strategy), "by_coin": by_coin,
        "execution": execution, "exits": exits, "today": today_sec, "nightly": nightly,
    }


def profile_card(strategy: str, path: str = CARDS) -> Optional[dict]:
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        for c in json.load(fh)["cards"]:
            if c["strategy"] == strategy:
                return {**c, "rows": [{k: (_r(v) if isinstance(v, float) else v) for k, v in r.items()}
                                      for r in c["rows"]],
                        "trend_share": _r(c["trend_share"], 3),
                        "note": "5-year backtest character, same rules; describes style, not proven skill"}
    return None


def specialist_packet(packet: dict, strategy: str, cards_path: str = CARDS) -> dict:
    """What one strategy's specialist sees: its five accounts, their pass status, the
    coin-flip league of each timeframe, and the strategy's profile card."""
    pc = {a: v for a, v in (packet.get("pass_check") or {}).items() if a.split("@")[0] == strategy}
    return {"meta": packet.get("meta"), "strategy": strategy,
            "by_strategy": (packet.get("by_strategy") or {}).get(strategy), "pass_check": pc,
            "league": packet.get("league"), "profile": profile_card(strategy, cards_path)}
