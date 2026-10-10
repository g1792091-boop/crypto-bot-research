"""Data packets for the paper v3 agent team (roster3.py). Built by code only.

Agents never query the databases: every number they may cite is in their packet, and each
claim must cite the packet path it came from (roles.check_output). The packet is computed
from paper3.db (live runner, read-only) and daily3.db (nightly checks, read-only).

Sections
- meta            rules version, units, minimum sample, day count since the start
- league          per timeframe: strategy accounts vs the three coin-flip accounts
- pass_check      reference only: each strategy account's wallet against the best of its timeframe's three
                  coin-flip accounts (the pre-addendum rule); the verdict is the checkpoint's
                  (``checkpoint_section``: the v4 verdict, ``facts()["method_ko"]``, read from checkpoint.db by the
                  rooms)
- by_strategy     one strategy across its timeframes (config.V3_TRADE_TFS; the 36 have no 5m account)
- by_coin         trades and net ROE per coin, and per strategy x coin for accounts with >= min_n
- execution       signal-to-fill delay, signal statuses, fees and funding share of losses
- exits           how trades ended: stop / lock level / liquidation, leverage mix
- today           trades closed in the last 24 hours, busts, alerts
- nightly         latest nightly report: replay parity, shadows, data quality
- groups          paper v4 (owners 2026-10-05): every original account group apart (core = the 36 + the 12 coin flips
                  of the core timeframes; ds200 = DeepSeek-200; reel = the 5m reel; flip = all 15 coin flips, 5m
                  included): accounts, trades, P&L, busts, open positions, per timeframe (DeepSeek also per family).
                  The sections above (league .. today) are the core group's alone, as in v3: a DeepSeek, reel or 5m
                  coin-flip trade never enters them (``BOARD_SCOPE_KO``).
- extras          the extra paper accounts (copies of a strategy with one rule changed, new strategies
                  from the lab): label, rule or spec, start, the runner's status, wallet, trades. Their
                  trades are kept OUT of every section above (the originals' numbers never include them);
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
from ..config import V3_INITIAL, V3_TRADE_TFS
from ..groups import GROUP_KO, family_of, group_of
from .facts import BOARD_SCOPE_KO, facts, five_m_ko

DAY_MS = 86_400_000
INITIAL = V3_INITIAL
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Strategy profile cards: built on Binance USDT-M futures bars (the venue the bot trades,
# research/binance_data/RESULTS_BINANCE.md); the original spot-aggregate cards are the fallback.
CARDS_BINANCE = os.path.join(ROOT, "research", "strategy_profiles", "out_binance", "cards.json")
CARDS_SPOT = os.path.join(ROOT, "research", "strategy_profiles", "out", "cards.json")
CARDS = CARDS_BINANCE if os.path.exists(CARDS_BINANCE) else CARDS_SPOT
TRADE_TFS = V3_TRADE_TFS
# Said wherever the staff see the 5-year research, which still has 5m rows (historical, unchanged): who trades 5m in
# this run and that the 36's 5m rows are history (agents/facts.py, built from config)
NO_5M_KO = five_m_ko()


def is_core(row: dict) -> bool:
    """Is an accounts row in the board's own population: one of the 36 locked strategies, or a coin flip on a core
    timeframe (the 12 of v3; the 5m coin flips are the reel's comparison, in ``groups``)?"""
    return row.get("kind") == "strategy" or (row.get("kind") == "random" and row.get("timeframe") in TRADE_TFS)
# What the entry study already tested on the same five years (research/entry_study/agent_summary.py)
RESEARCH_PRIOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "research_prior.json")
_PRIOR: Optional[dict] = None


def _ro(path: str) -> Optional[sqlite3.Connection]:
    """A read-only connection, or None when the file is missing or cannot be read. ``mode=ro`` first; when that cannot
    read (a WAL file with no -shm next to it, in a directory this user cannot write: the debate service under
    ReadOnlyPaths=/var/lib/paperbot reading daily3.db between two nightly runs), ``immutable=1`` (debate_packet.open_ro's
    fallback). Where ``mode=ro`` works (the agents, the dashboard) nothing changes."""
    if not path or not os.path.exists(path):
        return None
    # quoted: a '?' or '#' in the path must never change the open mode
    base = f"file:{urllib.parse.quote(os.path.abspath(path))}"
    for flags in ("?mode=ro", "?mode=ro&immutable=1"):
        c = None
        try:
            c = sqlite3.connect(base + flags, uri=True, timeout=10)
            c.row_factory = sqlite3.Row
            c.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchall()
            return c
        except sqlite3.Error:
            if c is not None:
                c.close()
    return None


def _r(x, n=4):
    return None if x is None else round(float(x), n)


def _median(xs):
    return statistics.median(xs) if xs else None


def build(paper_db: str, daily_db: Optional[str], now_ms: int, min_n: int = 30) -> dict:
    c = _ro(paper_db)
    if c is None:
        raise FileNotFoundError(paper_db)
    allaccts = {r["account_id"]: dict(r) for r in c.execute("SELECT * FROM accounts")}
    # the extra accounts (copies, new strategies) are reported apart: every section below is the originals' own
    extra_ids = {a for a, v in allaccts.items() if v.get("kind") in EXTRA_KINDS}
    # paper v4: the sections below are the core group's (the 36 + the 12 coin flips of the core timeframes); DeepSeek,
    # the reel and the 5m coin flips are counted in ``groups`` only
    other_ids = {a for a, v in allaccts.items() if a not in extra_ids and not is_core(v)}
    accts = {a: v for a, v in allaccts.items() if a not in extra_ids and a not in other_ids}
    st = c.execute("SELECT data FROM state WHERE k = 'accounts'").fetchone()
    alleng = json.loads(st["data"])["engines"] if st else {}
    eng = {a: e for a, e in alleng.items() if a not in extra_ids and a not in other_ids}
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
    trades = [t for t in alltrades if t["account_id"] not in extra_ids and t["account_id"] not in other_ids]
    start = min((a["created_ts"] for a in list(accts.values()) + [allaccts[a] for a in other_ids]), default=now_ms)
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
            # reference only: the verdict is the checkpoint's (facts()["method_ko"], ``checkpoint_section``)
            pass_check[a] = {"trades": n, "wallet": _r(w, 2),
                             "beats_coin_flips": best_rnd is not None and w > best_rnd and not eng.get(a, {}).get("bust"),
                             "bust": bool(eng.get(a, {}).get("bust")),
                             "status": "small_sample" if n < min_n else ("above_3_coin_flips" if ok else "below")}

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
    # the new strategies' own signal rows (strategy 'NL<n>') are not the originals'
    # the core group's own signal rows: not the new strategies' ('NL<n>'), nor a DeepSeek / reel / 5m coin-flip row
    other_keys = {(allaccts[a]["strategy"], allaccts[a]["timeframe"]) for a in other_ids}
    agg: dict = {}
    for r in c.execute("SELECT timeframe, status, strategy, COUNT(*) AS n, SUM(delay_ms) AS sum_delay, "
                       "COUNT(delay_ms) AS n_delay, MAX(delay_ms) AS max_delay FROM signal_log "
                       "WHERE strategy NOT GLOB 'NL[0-9]*' GROUP BY timeframe, status, strategy"):
        if (r["strategy"], r["timeframe"]) in other_keys:
            continue
        a = agg.setdefault((r["timeframe"], r["status"]), {"n": 0, "sum": 0.0, "n_delay": 0, "max": None})
        a["n"] += r["n"]
        a["sum"] += float(r["sum_delay"] or 0)
        a["n_delay"] += r["n_delay"]
        if r["max_delay"] is not None:
            a["max"] = r["max_delay"] if a["max"] is None else max(a["max"], r["max_delay"])
    sig = [{"timeframe": tf, "status": stt, "n": a["n"], "avg_delay": a["sum"] / a["n_delay"] if a["n_delay"] else None,
            "max_delay": a["max"]} for (tf, stt), a in sorted(agg.items())]
    losses = [t for t in trades if t["pnl"] < 0]
    execution = {
        "signals": [{k: (_r(v, 1) if k.endswith("delay") else v) for k, v in s.items()} for s in sig],
        "fees_total": _r(sum(t["fees"] for t in trades), 2), "funding_total": _r(sum(t["funding"] for t in trades), 2),
        "net_pnl_total": _r(sum(t["pnl"] for t in trades), 2),
        "cost_share_of_losses": _r(sum(t["fees"] + t["funding"] for t in losses) / abs(sum(t["pnl"] for t in losses)))
        if losses and sum(t["pnl"] for t in losses) else None,
    }
    outcomes = Counter()
    tfq = ",".join("?" * len(TRADE_TFS))
    for r in c.execute("SELECT status, reason, COUNT(*) AS n FROM outcomes WHERE account_id NOT IN "
                       "(SELECT account_id FROM accounts WHERE kind IN ('copy', 'newlab') OR NOT (kind = 'strategy' OR "
                       f"(kind = 'random' AND timeframe IN ({tfq})))) GROUP BY status, reason", TRADE_TFS):
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
    # the core group's alerts (an alert names its account as '[<account>] ...'): 171 DeepSeek accounts at 30x must
    # not push the 36's busts and liquidations out of the 40 lines
    alerts = []
    for r in c.execute("SELECT ts, level, text FROM alerts WHERE ts >= ? AND level != 'INFO' ORDER BY rowid DESC "
                       "LIMIT 400", (since,)):
        text = r["text"] or ""
        aid = text[1:text.find("]")] if text.startswith("[") and "]" in text else None
        if aid is not None and aid in other_ids:
            continue
        alerts.append(dict(r))
        if len(alerts) >= 40:
            break
    today_sec = {"trades": len(today), "net_pnl": _r(sum(t["pnl"] for t in today), 2),
                 "wins": sum(t["pnl"] > 0 for t in today),
                 "busts_total": sum(bool(e.get("bust")) for e in eng.values()),
                 "biggest_losses": [{k: t[k] for k in ("account_id", "symbol", "leverage", "exit_reason", "roe", "pnl")}
                                    for t in sorted(today, key=lambda t: t["pnl"])[:5]],
                 "alerts": alerts}
    c.close()

    # ------------------------------------------------ v4 groups (every original account, each group apart)
    groups = _groups(allaccts, extra_ids, alleng, alltrades, since)

    # ------------------------------------------------ extra accounts (apart from everything above)
    extras = _extras(allaccts, extra_ids, alleng, alltrades, xstate, since)

    # ------------------------------------------------ nightly checks
    nightly = None
    d = _ro(daily_db)
    if d is not None:
        r = d.execute("SELECT day, data FROM reports ORDER BY day DESC LIMIT 1").fetchone()
        if r:
            nightly = json.loads(r["data"])
            mm = d.execute("SELECT account_id, data FROM mismatches WHERE day = ?", (r["day"],)).fetchall()
            nightly["mismatched_accounts"] = [m["account_id"] for m in mm]
            labels = {}
            for m in mm:
                try:
                    lab = json.loads(m["data"] or "{}").get("label")
                except (TypeError, ValueError, AttributeError):
                    lab = None
                if lab:
                    labels[m["account_id"]] = lab     # e.g. early_kline: proven, not an engine problem
            if labels:
                nightly["mismatch_labels"] = labels
        d.close()

    # where the 144 strategy accounts make or lose money: by coin (best strategies of each coin), weekday/weekend x session,
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

    f = facts()
    return {
        # the v4 documents (G19): the run's rules, the verdict, rule B's evaluation; the v3 documents they carry over
        # are cited inside docs/paper-v4-rules.md by sha256
        "meta": {"rules": f["rules"], "rules_change": f["rules"], "verdict": f["verdict"], "levrule": f["levrule"],
                 "method_ko": f["method_ko"],
                 "timeframes": list(TRADE_TFS), "original_accounts": f["accounts"], "no_5m": NO_5M_KO,
                 "board_scope": BOARD_SCOPE_KO, "version": f["version"],
                 "groups": {g: v["accounts"] for g, v in f["groups"].items()},
                 "settings_version": run.get("settings"), "min_n": min_n, "run_start_ms": int(start),
                 "days_running": _r(days, 2), "units": {"roe": "net return on isolated margin (0.10 = +10%)",
                                                        "wallet": f"USDT, each account starts at {INITIAL:,.0f}"},
                 "accounts": len(accts), "extra_accounts": len(extra_ids), "pass_check_note": PASS_CHECK_NOTE},
        "league": league, "pass_check": pass_check, "by_strategy": dict(by_strategy), "by_coin": by_coin,
        "execution": execution, "exits": exits, "today": today_sec, "nightly": nightly, "extras": extras,
        "breakdown": breakdown, "groups": groups,
    }


def _stat(rows: list, ts: list, eng: dict, since: int) -> dict:
    """Accounts, trades, P&L, busts and open positions of a set of accounts (``rows``: (account_id, row))."""
    ws = [float(eng.get(a, {}).get("wallet", INITIAL)) for a, _v in rows]
    return {"accounts": len(rows), "trades": len(ts), "wins": sum(t["pnl"] > 0 for t in ts),
            "net_pnl": _r(sum(t["pnl"] for t in ts), 2), "trades_24h": sum(t["exit_time"] >= since for t in ts),
            "wins_24h": sum(t["pnl"] > 0 and t["exit_time"] >= since for t in ts),
            "net_pnl_24h": _r(sum(t["pnl"] for t in ts if t["exit_time"] >= since), 2),
            "busts": sum(bool(eng.get(a, {}).get("bust")) for a, _v in rows),
            "open_positions": sum(bool(eng.get(a, {}).get("position")) for a, _v in rows),
            "median_wallet": _r(_median(ws), 2)}


def _groups(accts: dict, extra_ids: set, eng: dict, trades: list, since: int) -> dict:
    """Paper v4: each original group apart (code only): core, ds200, reel, flip (the coin flips, 5m included), with a
    per-timeframe split (DeepSeek also per family; the reel next to its 5m coin flips). The staff read the groups
    side by side; no group's numbers enter another's."""
    by_acct = defaultdict(list)
    for t in trades:
        by_acct[t["account_id"]].append(t)
    members: dict = defaultdict(list)
    for a, v in accts.items():
        if a in extra_ids:
            continue
        members[group_of(v)].append((a, v))
    out: dict = {"note": BOARD_SCOPE_KO}
    for g in ("core", "ds200", "reel", "flip", *sorted(k for k in members if k not in ("core", "ds200", "reel", "flip"))):
        rows = members.get(g) or []
        if not rows:
            continue
        ts = [t for a, _v in rows for t in by_acct[a]]
        e = {"name_ko": GROUP_KO.get(g, g), **_stat(rows, ts, eng, since), "by_timeframe": {}}
        for tf in sorted({v["timeframe"] for _a, v in rows}, key=lambda x: (len(x), x)):
            sub = [(a, v) for a, v in rows if v["timeframe"] == tf]
            e["by_timeframe"][tf] = _stat(sub, [t for a, _v in sub for t in by_acct[a]], eng, since)
        if g == "ds200":
            fams = defaultdict(list)
            for a, v in rows:
                fams[family_of(v) or "?"].append((a, v))
            e["by_family"] = {f: _stat(sub, [t for a, _v in sub for t in by_acct[a]], eng, since)
                              for f, sub in sorted(fams.items(), key=lambda kv: (len(kv[0]), kv[0]))}
        out[g] = e
    return out


EXTRA_KINDS = ("copy", "newlab")
RESTART_MARKER = "run:restarted"           # resetrun.MARKER (resetrun is not imported here; a test checks the name)


def run_restarted(agents_conn: Optional[sqlite3.Connection]) -> Optional[str]:
    """One line for ``meta.run_restarted`` from the cursor resetrun writes when the run restarts from scratch
    (``run:restarted``: {ts, day_kst, text_ko, archive, ...}); None when there is no marker or it cannot be read."""
    if agents_conn is None:
        return None
    try:
        r = agents_conn.execute("SELECT v FROM cursors WHERE k = ?", (RESTART_MARKER,)).fetchone()
        m = json.loads(r[0]) if r else None
    except (sqlite3.Error, TypeError, ValueError):
        return None
    if not isinstance(m, dict) or not m.get("day_kst"):
        return None
    what = str(m.get("text_ko") or f"실험을 {m['day_kst']}에 처음부터 다시 시작함")[:160]
    return (f"{what}. {m['day_kst']} 전의 거래·손익·계좌 숫자는 이전 실행(보관됨) 것이고 새 실행과 섞지 않음 "
            f"({facts()['rules']})")


PASS_CHECK_NOTE = ("참고용: 같은 봉 동전 봇 3개 중 최고보다 잔고가 높은지만 봄. 합격·불합격 판정은 체크포인트"
                   f"({facts()['method_ko']})가 함")
CHECKPOINT_ROWS = 30         # verdict rows a team packet carries (tokens)
CHECKPOINT_P = 0.10          # ... the passes plus the accounts with p at most this


def checkpoint_section(view: dict, strategy: Optional[str] = None, max_rows: int = CHECKPOINT_ROWS) -> dict:
    """The newest 30-day checkpoint verdict for the agents. ``view``: ``paperbot.checkpoint.dashboard_view``
    (checkpoint.db, read-only) plus ``next`` (the next checkpoint date). Rows: 1차 합격 / 2차 통과 and the
    accounts with p <= 0.10 (at most ``max_rows``); for one strategy's specialist, all of that strategy's rows."""
    if not view.get("ready"):
        return {"ready": False, "next": view.get("next"),
                "note": "체크포인트 판정 전: 합격·불합격을 말하지 않음 (판정은 그날 09:00 KST 뒤 코드가 냄)"}
    from ..checkpoint import PASS1, PASS2
    rows = view.get("rows") or []
    if strategy is not None:
        keep = [r for r in rows if str(r.get("account_id", "")).split("@")[0] == strategy]
    else:
        keep = [r for r in rows if r.get("status") in (PASS1, PASS2)
                or (r.get("p") is not None and r["p"] <= CHECKPOINT_P)]
    out = {"ready": True, **{k: view.get(k) for k in ("date", "day", "next", "counts", "tested", "luck_passed",
                                                      "lucky_expected", "warnings")}}
    out["rows"] = [{k: (_r(v) if isinstance(v, float) else v) for k, v in r.items()} for r in keep[:max_rows]]
    out["rows_left_out"] = len(rows) - len(out["rows"])
    out["note"] = (f"공식 판정(코드, {facts()['verdict']}): {facts()['method_ko']}. "
                   "p·q와 상태를 그대로 전함. rows는 " + ("이 매매법 계좌만" if strategy is not None else
                                                       f"1차 합격·2차 통과와 p ≤ {CHECKPOINT_P:.2f}인 계좌만"))
    return out


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
                        "note": "5-year backtest character, same rules; describes style, not proven skill",
                        "note_5m": NO_5M_KO}
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
    parameters): tests already run on the same five years, what passed (no edge), parameter shapes. A DeepSeek
    definition or the reel (not in the entry study) falls back to ``agents/ds_prior.json`` (G6: the DeepSeek-200 and
    reel research outputs; never counted in ``research_counts``)."""
    doc = research_doc(path)
    if not doc or strategy not in doc.get("strategies", {}):
        if path != RESEARCH_PRIOR:
            return None
        from . import ds_prior
        try:
            p = ds_prior.prior(strategy)
        except (OSError, ValueError, TypeError):
            return None
        return {**p, "note_5m": NO_5M_KO} if p else None
    return {**doc["strategies"][strategy], "conclusion_ko": doc.get("conclusion_ko"),
            "note": "already tested, pre-registered, same 5-year data: descriptive, not a rule; "
                    "testing the same thing again is not new evidence", "note_5m": NO_5M_KO}


def research_counts(strategy: Optional[str] = None, path: str = RESEARCH_PRIOR) -> dict:
    """{'support_resistance': n, 'entry_strength': n, 'parameters': n, 'trendline': n, 'total': n} of the entry studies,
    for one strategy or all. Shown next to the room ledger; not in a room's gate divisor (a separate,
    pre-registered family that found nothing, docs/agent-rooms.md)."""
    doc = research_doc(path) or {"strategies": {}}
    rows = [doc["strategies"][strategy]] if strategy in doc["strategies"] else \
        ([] if strategy else list(doc["strategies"].values()))
    out = {"support_resistance": sum(r["support_resistance"]["tests"] for r in rows),
           "entry_strength": sum(r["entry_strength"]["tests"] for r in rows),
           "parameters": sum(r["parameters"]["variants"] for r in rows),
           "trendline": sum((r.get("trendline") or {}).get("tests", 0) for r in rows)}
    out["total"] = sum(out.values())
    return out


def v4_card(strategy: str) -> Optional[dict]:
    """The 5-year card of a DeepSeek definition or the reel (paperbot/ds_profiles.py: ``card`` when it has one, else
    ``profile``); None for any other name or when the research files cannot be read (G3)."""
    try:
        from .. import ds_profiles as DP
    except Exception:  # noqa: BLE001  (a description only)
        return None
    fn = getattr(DP, "card", None) or getattr(DP, "profile", None)
    if fn is None:
        return None
    try:
        return fn(strategy)
    except Exception:  # noqa: BLE001  (a description must never stop the packet)
        return None


PARAMSHADOW_DIR = os.environ.get("PAPERBOT_PARAMSHADOW_DIR", "/var/lib/paperbot/paramshadow")
_PS_CACHE: dict = {}
LIVE_PARAMS_TOP = 3
LIVE_PARAMS_NOTE = ("참고용 그림자: v4 시작부터 같은 기간을 숫자 하나(x0.5·x0.75·x1.25·x1.5) 또는 두 숫자를 함께"
                    "(각각 x0.75·x1.25) 바꿔 실제와 같은 규칙으로 다시 계산한 계좌. 실제 계좌·규칙은 그대로이고 숫자는 저절로 바뀌지 않음. ★ 없는 차이는 우연으로 봄(5년 파라미터 "
                    "시험 1,680개에서도 숫자 변경의 근거는 없었음). 숫자를 바꾸자는 제안은 30일 판정 뒤 5년 시험과 새 계좌로만.")


def _paramshadow_doc(path: str) -> Optional[dict]:
    """paperbot/paramshadow.py's last.json, re-read only when its mtime changes; None when missing or unreadable."""
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None
    hit = _PS_CACHE.get(path)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    _PS_CACHE[path] = (mt, doc)
    return doc


def live_params(strategy: str, path: Optional[str] = None, run_start: Optional[int] = None) -> Optional[dict]:
    """커스텀값 그림자 of one of the 36 (paperbot/paramshadow.py): per timeframe the recomputed default, the real
    account, the share of entries both have, how many variants beat the default, and the variants that beat it most
    (at most LIVE_PARAMS_TOP, with their star and luck ratio). None when there is no summary, no such strategy, or the
    summary is of another run (``run_start``: the board's run start; a reset leaves the old summary until 10:00)."""
    doc = _paramshadow_doc(path or os.path.join(PARAMSHADOW_DIR, "last.json"))
    if not doc or doc.get("status") == "no_run":
        return None
    if run_start is not None and doc.get("run_start_ms") is not None and int(doc["run_start_ms"]) != int(run_start):
        return None
    cells = [c for c in doc.get("cells") or [] if c.get("strategy") == strategy]
    if not cells:
        return None
    tfs = []
    for c in cells:
        vs = [v for v in c.get("variants") or [] if not v.get("same_as_base")]
        vs.sort(key=lambda v: v.get("diff_pnl") or 0.0, reverse=True)
        top = [{"variant": v.get("key"), "combo": v.get("combo"),
                "changes": [{"param": x.get("param"), "default": x.get("default"), "value": x.get("value")}
                            for x in v.get("parts") or []],
                "trades": v.get("trades"), "diff_pnl": v.get("diff_pnl"),
                "star": bool(v.get("star")), "luck_ratio": (v.get("luck") or {}).get("ratio"),
                "small": bool((v.get("luck") or {}).get("small"))} for v in vs[:LIVE_PARAMS_TOP] if (v.get("diff_pnl") or 0) > 0]
        b, r = c.get("base") or {}, c.get("real") or {}
        def brief(x):
            return {"trades": x.get("trades"), "pnl": x.get("pnl"),
                    "win_rate": None if x.get("win_rate") is None else round(x["win_rate"], 3)}
        tfs.append({"tf": c.get("tf"), "base": brief(b), "real": brief(r),
                    "parity": (c.get("parity") or {}).get("share"), "variants": c.get("k"),
                    "better": c.get("better"), "stars": c.get("stars"), "top": top})
    return {"through_day": doc.get("through_day"), "days": doc.get("days"), "status": doc.get("status"),
            "min_trades": doc.get("min_trades"), "timeframes": tfs, "note": LIVE_PARAMS_NOTE}


def specialist_packet(packet: dict, strategy: str, cards_path: str = CARDS) -> dict:
    """What one strategy's specialist sees: its four accounts, their wallets against the three coin-flip
    accounts (reference only; the rooms add the checkpoint verdict), the coin-flip league of each timeframe,
    the strategy's profile card and what the entry study already tested for it, and the custom-value shadow
    (``live_params``: the same period replayed with one number changed; None before its first night). A DeepSeek
    definition or the reel gets its card from paperbot/ds_profiles.py (``v4_card``) and its earlier tests from
    agents/ds_prior.json."""
    pc = {a: v for a, v in (packet.get("pass_check") or {}).items() if a.split("@")[0] == strategy}
    copies = [e for e in packet.get("extras") or [] if e.get("kind") == "copy" and e.get("strategy") == strategy]
    return {"meta": packet.get("meta"), "strategy": strategy,
            "by_strategy": (packet.get("by_strategy") or {}).get(strategy), "pass_check": pc,
            "league": packet.get("league"), "profile": profile_card(strategy, cards_path) or v4_card(strategy),
            "research": research_prior(strategy),
            # 커스텀값 그림자 (paperbot/paramshadow.py, owners' "2번"): one number changed, same period, reference only
            "live_params": live_params(strategy, run_start=(packet.get("meta") or {}).get("run_start_ms")),
            # its copy accounts, labelled 'copy: <account>, rule ...': never part of the numbers above
            "copies": copies}
