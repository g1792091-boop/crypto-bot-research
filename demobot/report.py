"""Snapshots for the dashboard (CONTRACT section 4) and Telegram events (section 5) from one tick's results."""
from __future__ import annotations

import math
import os
import resource
import shutil
import time
from typing import Optional

import numpy as np

from . import accounts as A
from . import costs as CO
from . import extra as EX
from . import grid as G
from . import regime as RG
from . import review as RV
from . import store as ST

DAY_MS = 86400 * 1000
KIND_KO = {"fixed": "고정", "adaptive": "자동 교체", "friend": "친구 규칙", "flip": "동전 던지기", "private": "비공개 매매법"}
REASON_KO = {"stop": "손절", "lock": "잠금 익절", "liq": "강제청산", "tp": "익절", "be": "본전", "time": "시간",
             "open": "보유 중"}
CURVE_MAX = 800
TRADES_MAX = 600
STOP_EVENTS_MAX = 200
BARS_BEFORE_MS = 7 * DAY_MS
DEADLINE_MS = 1798729200000          # 2026-12-31 24:00 KST (= 2026-12-31 15:00 UTC)
STAGES_KO = ["설치", "데모 진행", "우리 기준 통과", "확인 기간", "실전 후보"]
JUDGE_INTERNAL = ("passed", "confirm_started", "confirm_decided")


def downsample(points: list, limit: int = CURVE_MAX) -> list:
    if len(points) <= limit:
        return points
    step = len(points) / (limit - 1)
    idx = sorted({int(i * step) for i in range(limit - 1)} | {len(points) - 1})
    return [points[i] for i in idx]


def _pub_trade(t: dict) -> dict:
    keys = ("key", "L", "coin", "side", "signal_ms", "entry_ms", "entry", "stop", "exit_ms", "exit", "status", "reason",
            "pnl", "roe", "R", "margin", "funding", "fee", "notional", "cost_bps", "through_bps", "trend", "vol",
            "setting_ko", "exit_ko")
    return {k: t.get(k) for k in keys}


def account_header(a: A.Acct, r: dict) -> dict:
    lines = {}
    for L, sim in r["lines"].items():
        ln = dict(sim["line"])
        sn = [s for s in r["settings_now"] if s.get("L") in (None, L)]
        ln["setting_ko"] = _setting_line(sn)
        ssim = (r.get("lines_stop") or {}).get(L)
        if ssim is not None:
            sl = ssim["line"]
            ln["stops"] = dict(equity=sl["equity"], pnl=sl["pnl"], pnl_pct=sl["pnl_pct"], max_dd=sl["max_dd"],
                               trades=sl["trades"], mean_R=sl["mean_R"], **ssim["rules"].summary())
        lines[str(L)] = ln
    sw = r.get("switch_log", [])
    return dict(id=a.id, kind=a.kind, sub=a.sub, name=a.name, strategy=a.strat, short=a.short, tf=a.tf,
                combo=(a.combo if a.kind == "fixed" else None), exit_i=(0 if a.kind == "fixed" else None),
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


def write_bars(eng, snap: str) -> None:
    """snap/bars/<COIN>.npz: 15m bars from live start - 7 days, for the trade charts (CONTRACT 8.6)."""
    lo = (eng.live_start or 0) - BARS_BEFORE_MS
    for coin in G.COINS:
        b = eng.b15.get(coin)
        if b is None or not len(b["ts"]):
            continue
        i = int(np.searchsorted(b["ts"], lo))
        ST.write_npz(os.path.join(snap, "bars", f"{coin}.npz"), ts=np.asarray(b["ts"][i:], np.int64),
                     o=np.asarray(b["o"][i:], float), h=np.asarray(b["h"][i:], float),
                     l=np.asarray(b["l"][i:], float), c=np.asarray(b["c"][i:], float))


def write_snapshots(eng, res: dict, judge: dict, snap: str, now_ms: int, tick_info: dict,
                    outbox_state: Optional[dict], phase: str = "live") -> dict:
    os.makedirs(os.path.join(snap, "acct"), exist_ok=True)
    live0 = eng.live_start
    reg = RG.compute(eng)
    RG.annotate(reg, res)
    depth_rows = ST.load_depth(eng.conn, since_ms=live0 or 0)
    CO.annotate(eng, res, CO.depth_index(depth_rows))
    costs = CO.snapshot(eng, res, depth_rows, now_ms)
    ST.write_json(os.path.join(snap, "costs.json"), costs)
    regime = RG.snapshot(reg, res, live0, now_ms)
    ST.write_json(os.path.join(snap, "regime.json"), regime)
    write_bars(eng, snap)
    cal, daily_acct, eq_total, pnl_total = EX.calendar(res, now_ms)
    ST.write_json(os.path.join(snap, "calendar.json"), cal)
    ST.write_json(os.path.join(snap, "positions.json"), EX.positions(eng, res, now_ms))
    ST.write_json(os.path.join(snap, "signals_now.json"), EX.signals_now(eng, res, now_ms))
    ST.write_json(os.path.join(snap, "analysis.json"), EX.analysis(res, now_ms))
    ST.write_json(os.path.join(snap, "vs5y.json"), EX.vs5y(res, now_ms))
    ST.write_json(os.path.join(snap, "timeline.json"), EX.timeline(eng.conn, now_ms))
    ST.write_json(os.path.join(snap, "dataq.json"), EX.dataq(eng, now_ms, snap))
    hour = now_ms // 3_600_000
    if ST.get_meta(eng.conn, "export_hour") != hour or not os.path.exists(os.path.join(snap, "export", "index.json")):
        EX.write_exports(res, snap, now_ms)
        ST.set_meta(eng.conn, "export_hour", hour)
    rows = []
    all_trades = []
    for a in A.current_accounts():
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
        sl = r.get("lines_stop") or {}
        curves_stops = {str(L): downsample([[int(t), float(v)] for t, v in sim["curve"]]) for L, sim in sl.items()}
        stop_events = sorted((e for sim in sl.values() for e in sim["rules"].events), key=lambda e: -e["t_ms"])
        detail = dict(head, curves=curves, curves_stops=curves_stops, stop_events=stop_events[:STOP_EVENTS_MAX],
                      daily=daily_acct.get(a.id, {}),
                      trades=pub, decisions=r["switch_log"], settings_now=r["settings_now"],
                      positions=[p for p in pub if p["status"] == "open"])
        ST.write_json(os.path.join(snap, "acct", f"{a.id}.json"), detail)
        for t in trades[:300]:
            all_trades.append(dict(_pub_trade(t), account=a.id, name=a.name))
    ST.write_json(os.path.join(snap, "accounts.json"), dict(generated_ms=now_ms, live_start_ms=live0, accounts=rows))
    all_trades.sort(key=lambda t: -(t["exit_ms"] or t["entry_ms"]))
    ST.write_json(os.path.join(snap, "trades.json"), dict(generated_ms=now_ms, trades=all_trades[:300]))
    jd = {k: v for k, v in judge.items() if k not in JUDGE_INTERNAL}
    by_line = {(h["id"], int(L)): ln for h in rows for L, ln in h["lines"].items()}
    for c in jd.get("candidates", []):
        c["costs"] = CO.line_costs(costs, c["id"], c["L"])
        st = by_line.get((c["id"], c["L"]), {}).get("stops")
        c["stops"] = dict(pnl_pct=st["pnl_pct"], max_dd=st["max_dd"]) if st else None
    ST.write_json(os.path.join(snap, "judge.json"), jd)
    home = home_snapshot(eng, res, judge, snap, now_ms, rows, all_trades, phase)
    home["goal"] = goal_line(judge, rows, now_ms, phase)
    home["equity_total"] = eq_total
    home["pnl_total"] = pnl_total
    home["regime_now"] = regime["now"]
    home["costs_now"] = dict(median_entry_bps=CO.median_entry_bps(costs), assumed_bps=CO.ASSUMED_BPS)
    home["totals"]["confirming"] = sum(1 for c in judge.get("confirm", []) if c["status"] == "confirming")
    home["totals"]["candidates"] = len(judge.get("candidates", []))
    ST.write_json(os.path.join(snap, "home.json"), home)
    try:
        review, _finished = RV.update(eng.conn, res, judge, costs, reg, _read_json(os.path.join(snap, "views.json")),
                                      now_ms, backup=_read_json(os.path.join(snap, "backup.json")))
        ST.write_json(os.path.join(snap, "review.json"), review)
    except Exception as exc:          # the review never stops the snapshots
        tick_info.setdefault("errors", []).append(f"review: {type(exc).__name__}: {exc}")
    status = status_snapshot(eng, now_ms, tick_info, outbox_state, phase)
    status["deadman"] = tick_info.get("deadman") or dict(configured=False, last_ok_ms=None, last_error=None)
    ST.write_json(os.path.join(snap, "status.json"), status)
    return home


def _read_json(path):
    import json
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def goal_line(judge: dict, rows: list, now_ms: int, phase: str) -> dict:
    """The 12/31 goal line (CONTRACT 8.7)."""
    conf = judge.get("confirm", [])
    if any(c["status"] == "confirmed" for c in conf):
        stage = 4
    elif any(c["status"] == "confirming" for c in conf):
        stage = 3
    elif judge.get("passed"):
        stage = 2
    else:
        stage = 1 if phase == "live" else 0
    pnl = {(h["id"], int(L)): ln["pnl_pct"] for h in rows for L, ln in h["lines"].items()}
    best = None
    for r in judge.get("rows", []):
        if r["id"].startswith("cf-"):
            continue
        ok = sum(1 for c in r["ours"]["checks"] if c["ok"])
        key = (ok, pnl.get((r["id"], r["L"]), -1e9))
        if best is None or key > best[0]:
            best = (key, r, ok)
    closest = None
    if best is not None:
        _k, r, ok = best
        closest = dict(id=r["id"], name=r["name"], L=r["L"], ok=ok, of=len(r["ours"]["checks"]),
                       missing_ko=[c["name_ko"] for c in r["ours"]["checks"] if not c["ok"]])
    days = max(0, int(math.ceil((DEADLINE_MS - now_ms) / DAY_MS)))
    line = f"12/31까지 {days}일: {STAGES_KO[stage]} 단계"
    if closest:
        line += f", 가장 가까운 줄 {closest['name']} {closest['L']}배 ({closest['of']}개 중 {closest['ok']}개 통과)"
    return dict(deadline_ms=DEADLINE_MS, days_left=days, stage=stage, stages_ko=STAGES_KO, closest=closest,
                line_ko=line)


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
    for a in A.current_accounts():
        for s in res[a.id].get("switch_log", [])[:5]:
            sw.append(dict(s, id=a.id, name=a.name))
    sw.sort(key=lambda s: -s["t_ms"])
    return dict(generated_ms=now_ms, live_days=(now_ms - live0) / DAY_MS, phase=phase,
                totals=dict(accounts=len(A.current_accounts()), open_positions=sum(h["lines"]["20"]["open"] for h in rows),
                            trades=sum(int(ln["trades"]) for h in rows for ln in h["lines"].values()),
                            passed=len(judge.get("passed", []))),
                best=best, worst=worst, by_kind=by_kind, leaders=RK.leaders(snap), verdict_ko=judge["verdict_ko"],
                recent_switches=sw[:12], recent_trades=all_trades[:12])


RULE_BOT_UNITS = ("paperbot-live3.service", "paperbot-dash.service", "paperbot-executor.service")
_SERVER_CACHE: dict = {}


def server_state(now_ms: int) -> dict:
    """The shared server (CONTRACT 8.13): memory, load and the rule bot's main services (best effort, read-only;
    refreshed at most every 5 minutes)."""
    if "v" in _SERVER_CACHE and _SERVER_CACHE["t"] > now_ms - 300_000:
        return _SERVER_CACHE["v"]
    out = dict(mem_total_mb=None, mem_avail_mb=None, swap_used_mb=None, load=None, cpus=os.cpu_count(),
               rule_bot=[])
    try:
        mi = {}
        with open("/proc/meminfo") as fh:
            for ln in fh:
                k, v = ln.split(":", 1)
                mi[k] = int(v.split()[0]) / 1024.0
        out.update(mem_total_mb=mi.get("MemTotal"), mem_avail_mb=mi.get("MemAvailable"),
                   swap_used_mb=(mi.get("SwapTotal", 0) - mi.get("SwapFree", 0)))
    except (OSError, ValueError):
        pass
    try:
        out["load"] = list(os.getloadavg())
    except OSError:
        pass
    import subprocess
    for u in RULE_BOT_UNITS:
        try:
            r = subprocess.run(["systemctl", "show", "-p", "ActiveState", "-p", "MemoryCurrent", u],
                               capture_output=True, text=True, timeout=3)
            kv = dict(x.split("=", 1) for x in r.stdout.splitlines() if "=" in x)
            if kv.get("ActiveState") in (None, "", "inactive") and kv.get("MemoryCurrent") in (None, "", "[not set]"):
                continue
            mem = kv.get("MemoryCurrent", "")
            out["rule_bot"].append(dict(unit=u, active=kv.get("ActiveState"),
                                        mem_mb=(int(mem) / 1048576.0 if mem.isdigit() else None)))
        except Exception:
            continue
    _SERVER_CACHE.update(t=now_ms, v=out)
    return out


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
                snap_dir=snapd, server=server_state(now_ms))


# ------------------------------------------------------------------ Telegram events
def tick_events(eng, res: dict, now_ms: int, bar_ms: int) -> tuple:
    """(tick payload or None, switch payloads, notified rows) for the accounts that notify."""
    opens, closes, mark = [], [], []
    for a in A.current_accounts():
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
    for a in A.current_accounts():
        new = [s for s in (res[a.id].get("switches_new") or []) if s["t_ms"] >= now_ms - 2 * 3600 * 1000]
        if new and a.kind in ("adaptive", "friend"):
            switches.append(dict(account=a.id, name=a.name, items=new[:20]))
    return tick, switches, mark
