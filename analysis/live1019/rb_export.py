import sqlite3, json, csv, glob, os, io, time, zipfile

# Read-only: every database is opened with mode=ro, nothing on the server is changed.
ROOT = os.environ.get("PB_ROOT", "/var/lib/paperbot")
OUT = os.environ.get("PB_OUT", f"/root/paperbot_export_{time.strftime('%Y%m%d_%H%M')}.zip")
SRC = sorted(glob.glob(f"{ROOT}/archive/run-*/")) + [f"{ROOT}/"]
TR_KEYS = ["strategy_id", "symbol", "timeframe", "side", "signal_ts", "entry_time", "entry_price", "exit_time",
           "exit_price", "exit_reason", "qty", "leverage", "tier", "margin", "stop_price", "tp_price", "liq_price",
           "fees", "funding", "pnl", "roe", "price_move", "mae_price", "mfe_price", "equity_after", "score",
           "strategy_style", "stop_initial", "lock_roe"]
SIG_KEYS = ["ts", "symbol", "timeframe", "strategy_id", "side", "stop_price", "tier", "score", "atr"]
META_KEYS = ["stop_dist", "ref_price", "ref_time", "delay_ms"]
log = []


def ro(p):
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True)


def tables(c):
    return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def put(z, name, header, rows):
    n = 0
    with z.open(name, "w", force_zip64=True) as f:
        t = io.TextIOWrapper(f, encoding="utf-8", newline="")
        w = csv.writer(t)
        w.writerow(header)
        for r in rows:
            w.writerow(r)
            n += 1
        t.flush()
        t.detach()
    log.append(f"{name}: {n}")


def put_lines(z, name, lines):
    n = 0
    with z.open(name, "w", force_zip64=True) as f:
        for s in lines:
            f.write((s + "\n").encode("utf-8"))
            n += 1
    log.append(f"{name}: {n}")


def jl(s):
    try:
        return json.loads(s or "{}")
    except Exception:
        return {}


def g_trades(c):
    for r in c.execute("SELECT id, account_id, data FROM trades ORDER BY id"):
        d = jl(r[2])
        yield [r[0], r[1]] + [d.get(k) for k in TR_KEYS] + [json.dumps(d.get("context") or {}, separators=(",", ":"))]


def g_outcomes(c):
    for r in c.execute("SELECT id, account_id, step_ts, status, reason, symbol, data FROM outcomes ORDER BY id"):
        d = jl(r[6])
        s, det = d.get("signal") or {}, d.get("detail") or {}
        m = s.get("meta") or {}
        yield list(r[:6]) + [s.get(k) for k in SIG_KEYS] + [m.get(k) for k in META_KEYS] + \
            [json.dumps(det, separators=(",", ":"), default=str)]


def g_ctx(c):
    for r in c.execute("SELECT id, data FROM signal_log WHERE status = 'SUBMITTED' ORDER BY id"):
        d = jl(r[1])
        yield json.dumps({"id": r[0], "close": d.get("close"), "ctx": d.get("ctx")}, separators=(",", ":"))


def one(z, src, tag):
    p3 = os.path.join(src, "paper3.db")
    if os.path.exists(p3):
        c = ro(p3)
        t = tables(c)
        put(z, f"{tag}/accounts.csv", ["account_id", "strategy", "timeframe", "kind", "created_ts", "settings_version",
                                       "parent", "data"],
            c.execute("SELECT account_id, strategy, timeframe, kind, created_ts, settings_version, parent, data "
                      "FROM accounts"))
        put(z, f"{tag}/trades.csv", ["id", "account_id"] + TR_KEYS + ["context"], g_trades(c))
        put(z, f"{tag}/outcomes.csv", ["id", "account_id", "step_ts", "status", "reason", "symbol"] +
            ["sig_" + k for k in SIG_KEYS] + META_KEYS + ["detail"], g_outcomes(c))
        if "signal_log" in t:
            put(z, f"{tag}/signal_log.csv", ["id", "bar_close", "timeframe", "strategy", "symbol", "side", "atr",
                                             "ref_price", "ref_time", "delay_ms", "status"],
                c.execute("SELECT id, bar_close, timeframe, strategy, symbol, side, atr, ref_price, ref_time, "
                          "delay_ms, status FROM signal_log ORDER BY id"))
            put_lines(z, f"{tag}/signal_ctx.jsonl", g_ctx(c))
        if "live_bars" in t:
            put(z, f"{tag}/live_bars.csv", ["ts", "symbol", "open", "high", "low", "close", "volume", "mark_open",
                                            "mark_high", "mark_low", "mark_close", "close_time", "processed_at"],
                c.execute("SELECT ts, symbol, open, high, low, close, volume, mark_open, mark_high, mark_low, "
                          "mark_close, close_time, processed_at FROM live_bars ORDER BY ts, symbol"))
        if "fill_costs" in t:
            put(z, f"{tag}/fill_costs.csv", ["id", "ts", "account_id", "symbol", "event", "status", "notional",
                                             "slip_best"],
                c.execute("SELECT id, ts, account_id, symbol, event, status, notional, slip_best FROM fill_costs"))
        if "equity" in t:
            put(z, f"{tag}/equity_hourly.csv", ["account_id", "hour_ts", "eq_min", "eq_max", "dd_max", "n"],
                c.execute("SELECT account_id, (ts / 3600000) * 3600000, MIN(equity), MAX(equity), MAX(drawdown), "
                          "COUNT(*) FROM equity GROUP BY account_id, ts / 3600000"))
        if "runs" in t:
            put(z, f"{tag}/runs.csv", ["id", "started_ts", "data"], c.execute("SELECT id, started_ts, data FROM runs"))
        if "alerts" in t:
            put(z, f"{tag}/alerts.csv", ["ts", "level", "text"], c.execute("SELECT ts, level, text FROM alerts"))
        c.close()
    else:
        log.append(f"{tag}: paper3.db 없음")
    pd = os.path.join(src, "daily3.db")
    if os.path.exists(pd):
        c = ro(pd)
        t = tables(c)
        if "shadows" in t:
            put(z, f"{tag}/d3_shadows.csv", ["key", "day", "kind", "account_id", "symbol", "timeframe", "side",
                                             "filled", "roe", "exit_reason", "resolved", "data"],
                c.execute("SELECT key, day, kind, account_id, symbol, timeframe, side, filled, roe, exit_reason, "
                          "resolved, data FROM shadows"))
        if "reports" in t:
            put(z, f"{tag}/d3_reports.csv", ["day", "ts", "data"], c.execute("SELECT day, ts, data FROM reports"))
        if "stop_slips" in t:
            put(z, f"{tag}/d3_stop_slips.csv", ["key", "day", "account_id", "strategy", "timeframe", "symbol",
                                                "exit_reason", "exit_time", "status", "paper_bps", "real_bps",
                                                "diff_usd"],
                c.execute("SELECT key, day, account_id, strategy, timeframe, symbol, exit_reason, exit_time, status, "
                          "paper_bps, real_bps, diff_usd FROM stop_slips"))
        c.close()


with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for src in SRC:
        tag = os.path.basename(src.rstrip("/")) if "/archive/" in src else "current"
        try:
            one(z, src, tag)
        except Exception as e:
            log.append(f"{tag}: 실패 {type(e).__name__}: {e}")
    z.writestr("manifest.txt", "\n".join([time.strftime("%Y-%m-%d %H:%M:%S %Z")] + SRC + log) + "\n")
print("\n".join(log))
print(f"\n완료: {OUT}  ({os.path.getsize(OUT) / 1e6:.1f} MB)")
