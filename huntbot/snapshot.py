"""The runner's outputs: the dashboard's snapshot files (atomic writes) and the private DeepSeek file.

Public (<snap>/, read by huntbot-dash, never written by it):
  status.json     feed and runner health, code identity, universe, lineup file state, ledger counts
  lineup.json     the lineup accounts in full (equity by the hour, open positions with the stop in force, trades)
  systems.json    one row per recorded system (counts, labels; money for core systems only)
  positions.json  every open position of every system and lineup account
  trades.json     per system its last 100 trades, and the newest 300 closed trades of all systems

D11: a DeepSeek system (kind "ds": F3, and F4 picks of DeepSeek strategies) and any lineup account holding one shows
counts, win shares, labels, coins, sides, times and add counts only: no equity, P&L, multiple, drawdown, price, stop or
R. Their full figures go to <private>/deepseek.json (outside the snapshot folder; the dashboard never reads it).
"""

from __future__ import annotations

import json
import math
import os
import resource
from typing import Optional

from . import config as CFG
from . import systems as S

KST = 9 * 3_600_000
TRADES_PER_SYSTEM = 100
RECENT = 300
DS_TRADE_KEYS = ("coin", "side", "in_ms", "out_ms", "open", "reason", "adds", "pick_no", "signal_close_ms")
MONEY_TRADE_KEYS = DS_TRADE_KEYS + ("stop_source", "p0", "fill", "first_stop", "d0", "lev", "exit_px", "pnl",
                                    "price_pnl", "r_mult", "fees", "funding", "u", "stop_now", "q1", "eq_entry")


def _clean(o):
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if hasattr(o, "item") and not isinstance(o, (str, bytes)):
        try:
            return _clean(o.item())
        except (ValueError, AttributeError):
            pass
    return o


def write_json(folder: str, name: str, doc) -> str:
    os.makedirs(folder, exist_ok=True)
    p = os.path.join(folder, name)
    tmp = os.path.join(folder, f".{name}.{os.getpid()}.tmp")
    with open(tmp, "w") as fh:
        json.dump(_clean(doc), fh, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    os.replace(tmp, p)
    return p


def kst_day_start(ms: int) -> int:
    return (ms + KST) // CFG.DAY * CFG.DAY - KST


def public_trade(t: dict, ds: bool) -> dict:
    keys = DS_TRADE_KEYS if ds else MONEY_TRADE_KEYS
    out = {k: t.get(k) for k in keys if k in t}
    out["win"] = None if t.get("open") else bool((t.get("pnl") or 0) > 0)
    return out


def _counts(trades: list) -> dict:
    closed = [t for t in trades if not t["open"]]
    wins = sum(1 for t in closed if (t.get("pnl") or 0) > 0)
    return {"n_positions": len(trades), "closed": len(closed), "open_n": len(trades) - len(closed), "wins": wins,
            "win_share": (wins / len(closed)) if closed else None,
            "last_trade_ms": max([t["out_ms"] if not t["open"] else t["in_ms"] for t in trades], default=None)}


def _money(res: dict) -> dict:
    s = res["summary"]
    months = list(zip(res.get("month_names") or [], s.get("M") or []))
    return {"equity_now": res["equity_now"], "multiple": res["equity_now"] / 5000.0,
            "months": [[m, x] for m, x in months], "month_M": months[-1][1] if months else None,
            "max_dd": s.get("max_dd"), "fees": s.get("fees"), "funding": s.get("funding"),
            "mean_pnl_U": s.get("mean_pnl_U")}


# ---------------------------------------------------------------- lineup
def lineup_doc(R, mk, complete_ms: int, lineup_res: dict) -> tuple:
    pub, priv = [], []
    today = kst_day_start(R.now_ms())
    for a in R.lineup["accounts"]:
        res = lineup_res.get(a["id"])
        spec0 = a["parts"][0][0]
        base = {"id": a["id"], "label": a["label"], "variant": a["variant"],
                "variant_ko": R.var[a["variant"]]["ko"], "read": R.var[a["variant"]]["read"],
                "system": a.get("system"), "alias": a.get("alias"), "basket": a.get("basket"),
                "pick_nos": a.get("pick_nos"), "name_ko": a.get("name") if a.get("basket") else S.label_ko(spec0),
                "family": spec0.get("family"), "kind": spec0.get("kind"), "tf": spec0.get("tf"),
                "gate": spec0.get("gate"), "ds": a["ds"], "money": not a["ds"], "pick_no": a.get("pick_no"),
                "study": a.get("study"), "note": a.get("note"), "ok": res is not None}
        if res is None:
            pub.append(base)
            continue
        trades = res["trades"]
        row = dict(base, **(res.get("counts") or _counts(trades)), bust=res["summary"].get("bust"),
                   bust_month=res["summary"].get("bust_month"), signal_counts=res["summary"].get("signal_counts"))
        tr = [public_trade(t, a["ds"]) for t in sorted(trades, key=lambda t: t["in_ms"], reverse=True)]
        row["positions"] = [t for t in tr if t["open"]]
        row["trades"] = tr
        row["today"] = [t for t in tr if (t["out_ms"] if not t["open"] else t["in_ms"]) >= today
                        or t["in_ms"] >= today]
        if not a["ds"]:
            row.update(_money(res))
            row["hourly"] = {"start_ms": mk.start, "step_ms": 3_600_000, "eq": res.get("hourly") or []}
        else:
            priv.append({**base, **_money(res), "trades": trades, "hourly": res.get("hourly")})
        pub.append(row)
    return pub, priv


def write_lineup(R, mk, complete_ms: int, lineup_res: dict) -> None:
    pub, priv = lineup_doc(R, mk, complete_ms, lineup_res)
    write_json(R.snap, "lineup.json", {"generated_ms": R.now_ms(), "complete_ms": complete_ms,
                                       "forward_start_ms": R.fwd, "accounts": pub,
                                       "lineup_error": R.lineup.get("error"), "lineup_note": R.lineup.get("note")})
    if priv:
        write_json(R.private, "deepseek_lineup.json", {"generated_ms": R.now_ms(), "complete_ms": complete_ms,
                                                       "accounts": priv})


# ---------------------------------------------------------------- every system
def write_all(R, mk, complete_ms: int, results: dict, lineup_res: dict) -> None:
    lab = {}
    for a in R.lineup["accounts"]:
        for spec, _ in a["parts"]:
            if lab.get(spec["id"]) != "정식":
                lab[spec["id"]] = a["label"]
    rows, positions, by_sys, recent, priv = [], [], {}, [], []
    for s in R.systems:
        res = results.get(s["id"])
        ds = S.is_ds(s)
        base = {"id": s["id"], "cell": R.cell_of_sys[s["id"]], "family": s.get("family"), "name": s["name"],
                "kind": s["kind"], "tf": s["tf"], "gate": s["gate"], "rank": s.get("rank"), "ds": ds,
                "label_ko": S.label_ko(s), "lineup": lab.get(s["id"]), "ok": res is not None}
        if res is None:
            rows.append(base)
            continue
        sm = res["summary"]
        sc = sm.get("signal_counts") or {}
        row = dict(base, **(res.get("counts") or _counts(res["trades"])), bust=sm.get("bust"), events=sc.get("events"),
                   gated=sc.get("gated"), gated_out=sc.get("gated_out"), both=sc.get("both"),
                   candidates=sm.get("candidates"), skipped=sm.get("skipped"))
        if not ds:
            row.update(_money(res))
            row["day_eq"] = [round(x, 2) for x in (sm.get("day_eq") or [])]
        else:
            priv.append({"id": s["id"], **_money(res), "summary": sm, "trades": res["trades"]})
        rows.append(row)
        tr = sorted(res["trades"], key=lambda t: t["in_ms"], reverse=True)
        pt = [public_trade(t, ds) for t in tr]
        by_sys[s["id"]] = pt[:TRADES_PER_SYSTEM]
        for t in pt:
            if t["open"]:
                positions.append({"account": s["id"], "system": s["id"], "lineup": lab.get(s["id"]), "ds": ds,
                                  "label_ko": base["label_ko"], **t})
            else:
                recent.append({"account": s["id"], "ds": ds, "label_ko": base["label_ko"], **t})
    recent.sort(key=lambda t: t["out_ms"], reverse=True)
    lu_pub, _ = lineup_doc(R, mk, complete_ms, lineup_res)
    lpos = []
    for a in lu_pub:
        for t in a.get("positions") or []:
            lpos.append({"account": a["id"], "system": a.get("system") or "+".join(a.get("basket") or []),
                         "lineup": a["label"], "variant": a["variant"], "ds": a["ds"], "label_ko": a["name_ko"],
                         "lineup_account": True, **t})
    now = R.now_ms()
    R.last_counts = {"systems": len(rows), "open": len(positions), "recent": len(recent)}
    write_json(R.snap, "systems.json", {"generated_ms": now, "complete_ms": complete_ms, "forward_start_ms": R.fwd,
                                        "months": list(mk.months), "rows": rows})
    write_json(R.snap, "positions.json", {"generated_ms": now, "complete_ms": complete_ms,
                                          "rows": lpos + positions})
    write_json(R.snap, "trades.json", {"generated_ms": now, "complete_ms": complete_ms, "by_system": by_sys,
                                       "recent": recent[:RECENT]})
    write_json(R.private, "deepseek.json", {"generated_ms": now, "complete_ms": complete_ms,
                                            "what": "DeepSeek systems' money (D11): never served, never sent",
                                            "systems": priv})


# ---------------------------------------------------------------- status
def server_info() -> dict:
    try:
        load = [round(x, 2) for x in os.getloadavg()]
    except OSError:
        load = None
    mem = None
    try:
        with open("/proc/meminfo") as fh:
            mi = {ln.split(":")[0]: int(ln.split()[1]) for ln in fh if ":" in ln}
        mem = {"total_mb": round(mi.get("MemTotal", 0) / 1024), "available_mb": round(mi.get("MemAvailable", 0) / 1024)}
    except (OSError, ValueError, IndexError):
        pass
    try:
        st = os.statvfs(CFG.data_dir())
        disk_free_gb = round(st.f_bavail * st.f_frsize / 1e9, 1)
    except OSError:
        disk_free_gb = None
    return {"load": load, "cpus": os.cpu_count(), "mem": mem, "disk_free_gb": disk_free_gb,
            "runner_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)}


def write_status(R, complete_ms: Optional[int], started_ms: int, info: Optional[dict],
                 extra: Optional[dict] = None) -> None:
    st = R.store
    try:
        coins = st.coins()
        cov = st.coverage(R.universe)
        hb = st.heartbeats()
        log = st.recent_log(20)
        stalled = st.get("stalled", [])
    except Exception as e:  # noqa: BLE001  a busy store never stops the status file
        coins, cov, hb, log, stalled = {}, {}, {}, [{"ts_ms": R.now_ms(), "level": "error", "msg": str(e)}], []
    rows = []
    for s in R.universe:
        c, v = coins.get(s) or {}, cov.get(s) or {}
        rows.append({"symbol": s, "status": c.get("status"), "trading": c.get("trading"), "end_ms": c.get("end_ms"),
                     "first_ms": v.get("first_ms"), "last_ms": v.get("last_ms"), "bars": v.get("bars"),
                     "in_market": s in R.syms, "next_funding_ms": c.get("next_funding_ms"),
                     "expect_funding_ms": c.get("expect_funding_ms")})
    now = R.now_ms()
    doc = {"generated_ms": now, "complete_ms": complete_ms, "forward_start_ms": R.fwd, "warmup_start_ms": R.warmup_ms,
           "lag_s": None if complete_ms is None else max(0, (now - complete_ms) // 1000),
           "run": dict(info or {}, started_ms=started_ms, finished_ms=now, cycles=R.cycles),
           "feed": {"heartbeat": hb.get("feed"), "stalled": stalled, "log": log, "coins": rows},
           "engine": R.engine, "universe": {k: v for k, v in R.universe_info.items() if k != "symbols"} |
           {"n": len(R.universe), "in_market": len(R.syms)},
           "lineup": {"path": R.lineup.get("path"), "sha256": R.lineup.get("sha256"), "error": R.lineup.get("error"),
                      "accounts": len(R.lineup.get("accounts") or []),
                      "labels": {lb: sum(1 for a in R.lineup.get("accounts") or [] if a["label"] == lb)
                                 for lb in S.LABELS}},
           "systems": {"n": len(R.systems), "cells": len(R.cells), "aliases": R.aliases},
           "events": R.ledger.counts(), "server": server_info(), "extra": extra}
    write_json(R.snap, "status.json", doc)
