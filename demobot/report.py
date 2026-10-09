"""Snapshots for the dashboard (CONTRACT section 4) and Telegram events (section 5) from one tick's results."""
from __future__ import annotations

import os
import resource
import shutil
import time
from typing import Optional

import numpy as np

from . import accounts as A
from . import grid as G
from . import store as ST

DAY_MS = 86400 * 1000
KIND_KO = {"fixed": "고정", "adaptive": "자동 교체", "friend": "친구 규칙", "flip": "동전 던지기"}
REASON_KO = {"stop": "손절", "lock": "잠금 익절", "liq": "강제청산", "tp": "익절", "time": "시간", "open": "보유 중"}
CURVE_MAX = 800
TRADES_MAX = 600


def downsample(points: list, limit: int = CURVE_MAX) -> list:
    if len(points) <= limit:
        return points
    step = len(points) / (limit - 1)
    idx = sorted({int(i * step) for i in range(limit - 1)} | {len(points) - 1})
    return [points[i] for i in idx]


def _pub_trade(t: dict) -> dict:
    keys = ("key", "L", "coin", "side", "signal_ms", "entry_ms", "entry", "stop", "exit_ms", "exit", "status", "reason",
            "pnl", "roe", "R", "margin", "funding", "setting_ko", "exit_ko")
    return {k: t.get(k) for k in keys}


def account_header(a: A.Acct, r: dict) -> dict:
    lines = {}
    for L, sim in r["lines"].items():
        ln = dict(sim["line"])
        sn = [s for s in r["settings_now"] if s.get("L") in (None, L)]
        ln["setting_ko"] = _setting_line(sn)
        lines[str(L)] = ln
    sw = r.get("switch_log", [])
    return dict(id=a.id, kind=a.kind, sub=a.sub, name=a.name, strategy=a.strat, short=a.short, tf=a.tf,
                rule_ko=a.rule_ko, setting_ko=_setting_line(r["settings_now"] if a.kind != "friend" else
                                                            [s for s in r["settings_now"] if s.get("L") == 20]),
                lines=lines, switches=len(sw), last_switch_ms=(sw[0]["t_ms"] if sw else None))


def _setting_line(settings: list) -> str:
    if not settings:
        return "-"
    if len(settings) == 1 and settings[0]["coin"] == "ALL":
        s = settings[0]
        return s["setting_ko"] if s["exit_ko"] == G.exit_ko(0) else f"{s['setting_ko']} · {s['exit_ko']}"
    parts = []
    for s in settings:
        tail = "" if s["exit_ko"] in (G.exit_ko(0), "-") else f" · {s['exit_ko']}"
        parts.append(f"{G.coin_ko(s['coin'])} {s['setting_ko']}{tail}")
    return f"코인별 {len(settings)}개 (" + ", ".join(parts) + ")"


def write_snapshots(eng, res: dict, judge: dict, snap: str, now_ms: int, tick_info: dict,
                    outbox_state: Optional[dict], phase: str = "live") -> dict:
    os.makedirs(os.path.join(snap, "acct"), exist_ok=True)
    live0 = eng.live_start
    rows = []
    all_trades = []
    for a in A.ACCOUNTS:
        r = res[a.id]
        r["switch_log"] = A.decision_log(eng.conn, a)
        head = account_header(a, r)
        rows.append(head)
        trades = []
        for L, sim in r["lines"].items():
            trades.extend(sim["trades"])
        trades.sort(key=lambda t: -(t["entry_ms"]))
        pub = [_pub_trade(t) for t in trades[:TRADES_MAX]]
        curves = {str(L): downsample([[int(t), float(v)] for t, v in sim["curve"]]) for L, sim in r["lines"].items()}
        detail = dict(head, curves=curves, trades=pub, decisions=r["switch_log"], settings_now=r["settings_now"],
                      positions=[p for p in pub if p["status"] == "open"])
        ST.write_json(os.path.join(snap, "acct", f"{a.id}.json"), detail)
        for t in trades[:300]:
            all_trades.append(dict(_pub_trade(t), account=a.id, name=a.name))
    ST.write_json(os.path.join(snap, "accounts.json"), dict(generated_ms=now_ms, live_start_ms=live0, accounts=rows))
    all_trades.sort(key=lambda t: -(t["exit_ms"] or t["entry_ms"]))
    ST.write_json(os.path.join(snap, "trades.json"), dict(generated_ms=now_ms, trades=all_trades[:300]))
    jd = dict(judge)
    jd.pop("passed", None)
    ST.write_json(os.path.join(snap, "judge.json"), jd)
    home = home_snapshot(eng, res, judge, snap, now_ms, rows, all_trades, phase)
    ST.write_json(os.path.join(snap, "home.json"), home)
    status = status_snapshot(eng, now_ms, tick_info, outbox_state, phase)
    ST.write_json(os.path.join(snap, "status.json"), status)
    return home


def home_snapshot(eng, res, judge, snap, now_ms, rows, all_trades, phase) -> dict:
    from . import rank as RK
    live0 = eng.live_start or now_ms
    lines = []
    for h in rows:
        for L, ln in h["lines"].items():
            lines.append(dict(id=h["id"], name=h["name"], kind=h["kind"], L=int(L), pnl_pct=ln["pnl_pct"],
                              equity=ln["equity"], trades=ln["trades"]))
    lines_t = [x for x in lines if x["trades"] > 0]
    best = sorted(lines_t, key=lambda x: -x["pnl_pct"])[:5]
    worst = sorted(lines_t, key=lambda x: x["pnl_pct"])[:5]
    by_kind = []
    for k, ko in KIND_KO.items():
        m = {}
        for L in G.LEVS:
            v = [x["pnl_pct"] for x in lines if x["kind"] == k and x["L"] == L]
            m[str(L)] = float(np.mean(v)) if v else None
        by_kind.append(dict(kind=k, kind_ko=ko, mean_pnl_pct=m))
    sw = []
    for a in A.ACCOUNTS:
        for s in res[a.id].get("switch_log", [])[:5]:
            sw.append(dict(s, id=a.id, name=a.name))
    sw.sort(key=lambda s: -s["t_ms"])
    return dict(generated_ms=now_ms, live_days=(now_ms - live0) / DAY_MS, phase=phase,
                totals=dict(accounts=len(A.ACCOUNTS), open_positions=sum(h["lines"]["20"]["open"] for h in rows),
                            trades=sum(int(ln["trades"]) for h in rows for ln in h["lines"].values()),
                            passed=len(judge.get("passed", []))),
                best=best, worst=worst, by_kind=by_kind, leaders=RK.leaders(snap), verdict_ko=judge["verdict_ko"],
                recent_switches=sw[:12], recent_trades=all_trades[:12])


def status_snapshot(eng, now_ms, tick_info, outbox_state, phase) -> dict:
    ru = resource.getrusage(resource.RUSAGE_SELF)
    snapd = ST.default_snap()
    try:
        du = shutil.disk_usage(os.path.dirname(os.path.abspath(ST.default_db())))
        free_mb = du.free / 1e6
    except OSError:
        free_mb = None
    ncell_open = sum(int((~b.done).sum()) for b in eng.books.values())
    ncell = sum(2 * len(b) for b in eng.books.values())
    sig24 = 0
    for (c, tf, s), buf in eng.sigs.items():
        ts = buf.arrays()[0]
        sig24 += int((ts >= now_ms - DAY_MS).sum())
    last = {tf: eng.last_bar(tf) for tf in G.TFS}
    nxt = ((now_ms // (15 * 60000)) + 1) * 15 * 60000 + 25_000
    return dict(generated_ms=now_ms, version="demobot-1", phase=phase, live_start_ms=eng.live_start,
                history_start_ms=eng.history_start, last_bar_ms=last, last_tick_ms=now_ms,
                tick_seconds=tick_info.get("seconds_total"), next_tick_ms=nxt,
                data_ok=not eng.issues, data_issues=list(eng.issues), errors=list(tick_info.get("errors", [])),
                coins=list(G.COINS), tfs=list(G.TFS), leverages=list(G.LEVS), seed=A.SEED,
                costs=dict(taker=0.0005, slippage=0.0002, funding_8h_ranking=0.0001, funding_accounts="real"),
                counts=dict(settings=sum(G.NCOMBO.values()), players=sum(G.NCOMBO.values()) * 14,
                            cells_open=ncell_open, cells_total=ncell, signals_24h=sig24),
                proc=dict(rss_mb=ru.ru_maxrss / 1024.0, cpu_s=ru.ru_utime + ru.ru_stime),
                db_mb=ST.db_mb(), disk_free_mb=free_mb,
                telegram=outbox_state or dict(configured=False, queued=0, last_ok_ms=None, last_error=None),
                snap_dir=snapd)


# ------------------------------------------------------------------ Telegram events
def tick_events(eng, res: dict, now_ms: int, bar_ms: int) -> tuple:
    """(tick payload or None, switch payloads, notified rows) for the accounts that notify."""
    opens, closes, mark = [], [], []
    for a in A.ACCOUNTS:
        if not a.notify:
            continue
        seen = ST.notified_keys(eng.conn, a.id)
        r = res[a.id]
        by_trade = {}
        for L, sim in r["lines"].items():
            for t in sim["trades"]:
                base = t["key"].rsplit("|", 1)[0]
                by_trade.setdefault(base, {})[L] = t
        for base, per in by_trade.items():
            t0 = per[min(per)]
            st_all = "closed" if all(t["status"] == "closed" for t in per.values()) else "open"
            old = seen.get(base)
            if old == st_all:
                continue
            if old is None and t0["entry_ms"] < now_ms - 3600 * 1000:
                mark.append((a.id, base, st_all))     # older than an hour and never sent (first run): record only
                continue
            item = dict(account=a.id, name=a.name, coin=t0["coin"], side=t0["side"], entry=t0["entry"],
                        exit=t0["exit"], reason=t0["reason"] if st_all == "closed" else None,
                        setting_ko=t0["setting_ko"], exit_ko=t0["exit_ko"],
                        pnl_by_L=({str(L): t["pnl"] for L, t in per.items()} if st_all == "closed" else None),
                        R=(t0["R"] if st_all == "closed" else None))
            if old is None:
                opens.append(item)
            if st_all == "closed":
                closes.append(item)
            mark.append((a.id, base, st_all))
    tick = dict(bar_ms=bar_ms, opens=opens, closes=closes) if (opens or closes) else None
    switches = []
    for a in A.ACCOUNTS:
        new = [s for s in (res[a.id].get("switches_new") or []) if s["t_ms"] >= now_ms - 2 * 3600 * 1000]
        if new and a.kind in ("adaptive", "friend"):
            switches.append(dict(account=a.id, name=a.name, items=new[:20]))
    return tick, switches, mark
