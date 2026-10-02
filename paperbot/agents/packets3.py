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
- extras          the extra paper accounts (copies of a strategy with one rule changed, new strategies
                  from the lab): label, rule or spec, start, the runner's status, wallet, trades. Their
                  trades are kept OUT of every section above (the 195's numbers never include them);
                  a copy's trades are labelled ``copy: <account>, rule ...`` in its parent's packet.

``specialist_packet(packet, strategy)`` narrows a packet to one strategy for its specialist
(with its copy accounts, apart from its own) and adds that strategy's profile card (5-year character under the v3 rules, built by
research/strategy_profiles/report.py): trend-following or mean-reverting, holding length,
whether the profit lock cut winners early, per timeframe.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import urllib.parse
import statistics
from collections import Counter, defaultdict
from typing import Optional

from .. import breakdown as BD
from ..config import V3_INITIAL

DAY_MS = 86_400_000
INITIAL = V3_INITIAL
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Strategy profile cards: built on Binance USDT-M futures bars (the venue the bot trades,
# research/binance_data/RESULTS_BINANCE.md); the original spot-aggregate cards are the fallback.
CARDS_BINANCE = os.path.join(ROOT, "research", "strategy_profiles", "out_binance", "cards.json")
CARDS_SPOT = os.path.join(ROOT, "research", "strategy_profiles", "out", "cards.json")
CARDS = CARDS_BINANCE if os.path.exists(CARDS_BINANCE) else CARDS_SPOT
TRADE_TFS = ("5m", "15m", "30m", "1h", "4h")
# What the entry study already tested on the same five years (research/entry_study/agent_summary.py)
RESEARCH_PRIOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "research_prior.json")
_PRIOR: Optional[dict] = None


def _ro(path: str) -> Optional[sqlite3.Connection]:
    if not path or not os.path.exists(path):
        return None
    # quoted: a '?' or '#' in the path must never change the open mode
    c = sqlite3.connect(f"file:{urllib.parse.quote(os.path.abspath(path))}?mode=ro", uri=True, timeout=10)
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
    allaccts = {r["account_id"]: dict(r) for r in c.execute("SELECT * FROM accounts")}
    # the extra accounts (copies, new strategies) are reported apart: every section below is the 195's own
    extra_ids = {a for a, v in allaccts.items() if v.get("kind") in EXTRA_KINDS}
    accts = {a: v for a, v in allaccts.items() if a not in extra_ids}
    st = c.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()
    alleng = json.loads(st["data"])["engines"] if st else {}
    eng = {a: e for a, e in alleng.items() if a not in extra_ids}
    run = c.execute("SELECT data FROM state WHERE k = 'run'").fetchone()
    run = json.loads(run["data"]) if run else {}
    xstate = c.execute("SELECT data FROM state WHERE k = 'extras'").fetchone()
    try:
        xstate = json.loads(xstate["data"]) if xstate else None
    except (TypeError, ValueError):
        xstate = None
    alltrades = [dict(r) for r in c.execute(
        "SELECT account_id, symbol, entry_time, exit_time, exit_reason, leverage, pnl, roe, equity_after, data "
        "FROM trades ORDER BY id")]
    for t in alltrades:
        d = json.loads(t.pop("data"))
        t.update(side=d["side"], fees=d["fees"], funding=d["funding"], lock_roe=d.get("lock_roe"),
                 margin=d["margin"], price_move=d["price_move"])
    trades = [t for t in alltrades if t["account_id"] not in extra_ids]
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
    # the new strategies' own signal rows (strategy 'NL<n>') are not the 195's
    sig = [dict(r) for r in c.execute("SELECT timeframe, status, COUNT(*) AS n, AVG(delay_ms) AS avg_delay, "
                                      "MAX(delay_ms) AS max_delay FROM signal_log WHERE strategy NOT GLOB 'NL[0-9]*' "
                                      "GROUP BY timeframe, status")]
    losses = [t for t in trades if t["pnl"] < 0]
    execution = {
        "signals": [{k: (_r(v, 1) if k.endswith("delay") else v) for k, v in s.items()} for s in sig],
        "fees_total": _r(sum(t["fees"] for t in trades), 2), "funding_total": _r(sum(t["funding"] for t in trades), 2),
        "net_pnl_total": _r(sum(t["pnl"] for t in trades), 2),
        "cost_share_of_losses": _r(sum(t["fees"] + t["funding"] for t in losses) / abs(sum(t["pnl"] for t in losses)))
        if losses and sum(t["pnl"] for t in losses) else None,
    }
    outcomes = Counter()
    for r in c.execute("SELECT status, reason, COUNT(*) AS n FROM outcomes WHERE account_id NOT IN "
                       "(SELECT account_id FROM accounts WHERE kind IN ('copy', 'newlab')) GROUP BY status, reason"):
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

    # ------------------------------------------------ extra accounts (apart from everything above)
    extras = _extras(allaccts, extra_ids, alleng, alltrades, xstate, since)

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

    # where the 180 make or lose money: by coin (best strategies of each coin), weekday/weekend x session,
    # funding / US-open / 08:30 windows, volatility spike at entry (paperbot/breakdown.py, descriptive only)
    try:
        cb = _ro(paper_db)
        try:
            breakdown = BD.brief(BD.report(cb, min_n=min_n)) if cb is not None else None
        finally:
            if cb is not None:
                cb.close()
    except Exception as exc:  # noqa: BLE001  (a description must never stop the packet)
        breakdown = {"error": f"{type(exc).__name__}: {exc}"[:200]}

    return {
        "meta": {"rules": "docs/paper-v3-rules.md", "settings_version": run.get("settings"), "min_n": min_n,
                 "days_running": _r(days, 2), "units": {"roe": "net return on isolated margin (0.10 = +10%)",
                                                        "wallet": f"USDT, each account starts at {INITIAL:,.0f}"},
                 "accounts": len(accts), "extra_accounts": len(extra_ids)},
        "league": league, "pass_check": pass_check, "by_strategy": dict(by_strategy), "by_coin": by_coin,
        "execution": execution, "exits": exits, "today": today_sec, "nightly": nightly, "extras": extras,
        "breakdown": breakdown,
    }


EXTRA_KINDS = ("copy", "newlab")


def _extras(accts: dict, ids: set, eng: dict, trades: list, xstate, since: int) -> list[dict]:
    """One row per extra account (code only): kind, label, parent and rule (copy) or spec (new strategy),
    start, the runner's status, wallet and its own trade numbers. A copy's rows carry ``label``
    'copy: <account>, rule ...' (how its trades are named in its parent's packet)."""
    from .extra_accounts import copy_label, extra_status, label_of, rule_ko
    state = xstate if isinstance(xstate, dict) and xstate.get("v") == 1 else None
    by = defaultdict(list)
    for t in trades:
        if t["account_id"] in ids:
            by[t["account_id"]].append(t)
    out = []
    for aid in [a for a in accts if a in ids]:
        v = accts[aid]
        try:
            d = json.loads(v.get("data") or "{}")
        except (TypeError, ValueError):
            d = {}
        d = d if isinstance(d, dict) else {}
        e = {"account_id": aid, "kind": v["kind"], "strategy": v["strategy"], "timeframe": v["timeframe"],
             "parent": v.get("parent"), "data": d}
        ts = by[aid]
        src = d.get("source") if isinstance(d.get("source"), dict) else {}
        row = {"account_id": aid, "kind": v["kind"], "strategy": v["strategy"], "timeframe": v["timeframe"],
               "parent": v.get("parent"), "created_ts": v.get("created_ts"), "label_ko": label_of(e),
               "proposal_id": src.get("proposal_id"), "status": extra_status(state, aid),
               "wallet": _r(float(eng.get(aid, {}).get("wallet", INITIAL)), 2), "bust": bool(eng.get(aid, {}).get("bust")),
               "trades": len(ts), "mean_roe": _r(statistics.fmean([t["roe"] for t in ts])) if ts else None,
               "win_rate": _r(sum(t["pnl"] > 0 for t in ts) / len(ts)) if ts else None,
               "trades_24h": sum(t["exit_time"] >= since for t in ts),
               "net_pnl_24h": _r(sum(t["pnl"] for t in ts if t["exit_time"] >= since), 2)}
        if v["kind"] == "copy":
            row.update(rule=d.get("rule"), rule_ko=rule_ko(d.get("rule")), label=copy_label(e))
        else:
            row.update(spec=d.get("spec"), description_ko=d.get("description_ko"))
        out.append(row)
    return out


def profile_card(strategy: str, path: str = CARDS) -> Optional[dict]:
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        for c in json.load(fh)["cards"]:
            if c["strategy"] == strategy:
                return {**c, "rows": [{k: (_r(v) if isinstance(v, float) else v) for k, v in r.items()}
                                      for r in c["rows"]],
                        "trend_share": _r(c["trend_share"], 3),
                        "data_source": "binance_futures" if "out_binance" in path else "spot_aggregate",
                        "note": "5-year backtest character, same rules; describes style, not proven skill"}
    return None


def research_doc(path: str = RESEARCH_PRIOR) -> Optional[dict]:
    global _PRIOR
    if path != RESEARCH_PRIOR:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    if _PRIOR is None and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            _PRIOR = json.load(fh)
    return _PRIOR


def research_prior(strategy: str, path: str = RESEARCH_PRIOR) -> Optional[dict]:
    """The entry study's summary for one strategy (support/resistance, its own entry numbers, its
    parameters): tests already run on the same five years, what passed (no edge), parameter shapes."""
    doc = research_doc(path)
    if not doc or strategy not in doc.get("strategies", {}):
        return None
    return {**doc["strategies"][strategy], "conclusion_ko": doc.get("conclusion_ko"),
            "note": "already tested, pre-registered, same 5-year data: descriptive, not a rule; "
                    "testing the same thing again is not new evidence"}


def research_counts(strategy: Optional[str] = None, path: str = RESEARCH_PRIOR) -> dict:
    """{'support_resistance': n, 'entry_strength': n, 'parameters': n, 'total': n} of the entry study,
    for one strategy or all. Shown next to the room ledger; not in a room's gate divisor (a separate,
    pre-registered family that found nothing, docs/agent-rooms.md)."""
    doc = research_doc(path) or {"strategies": {}}
    rows = [doc["strategies"][strategy]] if strategy in doc["strategies"] else \
        ([] if strategy else list(doc["strategies"].values()))
    out = {"support_resistance": sum(r["support_resistance"]["tests"] for r in rows),
           "entry_strength": sum(r["entry_strength"]["tests"] for r in rows),
           "parameters": sum(r["parameters"]["variants"] for r in rows)}
    out["total"] = sum(out.values())
    return out


def specialist_packet(packet: dict, strategy: str, cards_path: str = CARDS) -> dict:
    """What one strategy's specialist sees: its five accounts, their pass status, the
    coin-flip league of each timeframe, the strategy's profile card and what the entry study
    already tested for it."""
    pc = {a: v for a, v in (packet.get("pass_check") or {}).items() if a.split("@")[0] == strategy}
    copies = [e for e in packet.get("extras") or [] if e.get("kind") == "copy" and e.get("strategy") == strategy]
    return {"meta": packet.get("meta"), "strategy": strategy,
            "by_strategy": (packet.get("by_strategy") or {}).get(strategy), "pass_check": pc,
            "league": packet.get("league"), "profile": profile_card(strategy, cards_path),
            "research": research_prior(strategy),
            # its copy accounts, labelled 'copy: <account>, rule ...': never part of the numbers above
            "copies": copies}
