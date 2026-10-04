#!/usr/bin/env python3
"""1m kline settle probe for Binance USD-M futures (public REST, no API key, Python 3 standard library only).

Question: when a bot reads a 1m kline right after the minute closes, is the kline already final?

For every minute boundary during the run it reads the minute that just closed, for 7 symbols at once,
at +0.2 s, +1 s, +3 s and +6 s after the close, then again at +25 s ("final") and +50 s ("check", to see
whether +25 s was itself final). It prints how often each early read differed from the final one
(high/low, close, volume/trade count), by symbol and by the real read delay, plus examples.

    python3 kline_probe.py                  # about 10 minutes (9 minute boundaries)
    python3 kline_probe.py --minutes 60     # firmer numbers, about an hour

Read-only: public GET requests to https://fapi.binance.com only (about 45 weight-1 requests a minute).
Raw reads are saved as JSON lines (--out, default /tmp/kline_probe_<UTC time>.jsonl).
"""

import argparse
import http.client
import json
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "https://fapi.binance.com"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT", "XRPUSDT")
EARLY = (0.2, 1.0, 3.0, 6.0)          # seconds after the close
FINAL = 25.0
CHECK = 50.0
MIN = 60000
FIELDS = ("open", "high", "low", "close", "volume", "trades")
BUCKETS = ((None, 0), (0, 500), (500, 1500), (1500, 4000), (4000, 8000), (8000, None))   # real read delay, ms


def label(off):
    if off == FINAL:
        return "final"
    if off == CHECK:
        return "check"
    return "+%gs" % off


EARLY_LABELS = tuple(label(o) for o in EARLY)


# ------------------------------------------------------------------ Binance (public, no key)
def http_json(path, params, timeout=5.0):
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(BASE + path + ("?" + q if q else ""), headers={"User-Agent": "kline-probe/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def binance_klines(symbol, start_ms):
    """The 1m kline that opens at start_ms and the one after it (if it has started)."""
    return http_json("/fapi/v1/klines", {"symbol": symbol, "interval": "1m", "startTime": int(start_ms), "limit": 2})


_time_conn = [None]


def binance_time():
    """Server time over one kept-alive connection, so a sample's round trip is one network round trip
    (the first sample after a reconnect is slow and Clock.sync drops it as the longest)."""
    for attempt in (0, 1):
        try:
            if _time_conn[0] is None:
                _time_conn[0] = http.client.HTTPSConnection("fapi.binance.com", timeout=5)
            _time_conn[0].request("GET", "/fapi/v1/time", headers={"User-Agent": "kline-probe/1.0"})
            resp = _time_conn[0].getresponse()
            body = resp.read()
            if resp.status != 200:
                raise RuntimeError("HTTP %d from /fapi/v1/time" % resp.status)
            return int(json.loads(body.decode("utf-8"))["serverTime"])
        except Exception:  # noqa: BLE001  (reconnect once)
            try:
                _time_conn[0].close()
            except Exception:  # noqa: BLE001
                pass
            _time_conn[0] = None
            if attempt:
                raise


def binance_time_fresh():
    """Server time over a fresh connection, the way the paper bot's feed reads it (urllib, one connection each)."""
    return int(http_json("/fapi/v1/time", {})["serverTime"])


def local_ms():
    return time.time() * 1000.0


def live_style_lead(clock, live_time, n=5):
    """How far a clock set the paper bot's way (Binance time minus the local time read BEFORE a fresh-connection
    /time call) runs ahead of Binance, in ms, per sample (positive = ahead)."""
    out = []
    for _ in range(n):
        t0 = clock.local()
        try:
            st = live_time()
        except Exception:  # noqa: BLE001
            continue
        out.append(int(round(st - t0 - clock.offset)))
    return out


class Clock:
    """Binance server time = local clock + offset. The offset comes from the /time call with the shortest
    round trip, taken at the middle of that call (so it is off by at most half that round trip)."""

    def __init__(self, server_time=binance_time, local=local_ms):
        self.server_time = server_time
        self.local = local
        self.offset = 0.0
        self.rtt = None

    def sync(self, n=5):
        best = None
        for _ in range(n):
            t0 = self.local()
            try:
                st = self.server_time()
            except Exception:  # noqa: BLE001  (try the next sample)
                continue
            t1 = self.local()
            if best is None or t1 - t0 < best[0]:
                best = (t1 - t0, st - (t0 + t1) / 2.0)
        if best is None:
            if self.rtt is None:
                raise RuntimeError("cannot reach Binance /fapi/v1/time")
            return                       # keep the previous offset
        self.rtt, self.offset = best

    def now(self):
        return self.local() + self.offset


# ------------------------------------------------------------------ reading
def parse_row(r):
    return {"open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5], "trades": int(r[8])}


def read_once(fetch, clock, symbol, minute, at):
    close = minute + MIN
    sent = clock.now()
    rows, err = None, None
    try:
        rows = fetch(symbol, minute)
    except Exception as exc:  # noqa: BLE001  (counted as an error, never as a difference)
        err = "%s: %s" % (type(exc).__name__, str(exc)[:120])
    recv = clock.now()
    row = nxt = None
    for r in rows or []:
        if int(r[0]) == minute:
            row = r
        elif int(r[0]) == minute + MIN:
            nxt = r
    return {"symbol": symbol, "minute": minute, "at": at, "sent_ms": int(round(sent - close)),
            "recv_ms": int(round(recv - close)), "row": parse_row(row) if row else None, "raw": row,
            "next_trades": int(nxt[8]) if nxt else None, "error": err}


def plan(first_close, minutes):
    """(server time to read, minute open time, label), in time order."""
    out = []
    for k in range(minutes):
        close = first_close + k * MIN
        for off in EARLY + (FINAL, CHECK):
            out.append((close + int(round(off * 1000)), close - MIN, label(off)))
    out.sort()
    return out


def run(minutes, symbols, clock, fetch, sleep, pool, log=None, live_time=None):
    """Read every symbol at every planned time (all symbols of one time at once, on the pool)."""
    clock.sync()
    clock.live_lead = live_style_lead(clock, live_time) if live_time is not None else []
    if log and clock.live_lead:
        log("paper-bot-style clock (local time read before a fresh /time call) runs ahead of Binance by "
            "median %d ms, max %d ms (%d samples)" % (median(clock.live_lead), max(clock.live_lead),
                                                     len(clock.live_lead)))
    now = clock.now()
    first_close = (int(now) // MIN + 1) * MIN
    if first_close - now < 2000:          # too close to schedule the +0.2 s read: take the next minute
        first_close += MIN
    if log:
        log("clock: Binance - local = %+.0f ms (round trip %.0f ms); first minute closes at %s UTC"
            % (clock.offset, clock.rtt or 0, hhmm(first_close)))
    futures = []
    done_minutes = 0
    try:
        for when, minute, at in plan(first_close, minutes):
            wait = when - clock.now()
            if wait > 0:
                sleep(wait / 1000.0)
            for s in symbols:
                futures.append(pool.submit(read_once, fetch, clock, s, minute, at))
            if at == "check":
                done_minutes += 1
                clock.sync(3)
                if log:
                    log("  minute %s done (%d/%d)" % (hhmm(minute), done_minutes, minutes))
    except KeyboardInterrupt:
        if log:
            log("stopped early: summarising what was read")
    out = []
    for f in futures:
        try:
            out.append(f.result(timeout=30))
        except Exception:  # noqa: BLE001
            pass
    return out


# ------------------------------------------------------------------ summary
def same(k, a, b):
    if k == "trades":
        return int(a) == int(b)
    return float(a) == float(b)


def hhmm(ms):
    return time.strftime("%H:%M", time.gmtime(ms / 1000.0))


def bucket_of(ms):
    for lo, hi in BUCKETS:
        if (lo is None or ms >= lo) and (hi is None or ms < hi):
            return (lo, hi)
    return BUCKETS[-1]


def summarize(reads):
    final, check = {}, {}
    for r in reads:
        if r["row"] is None or r["error"]:
            continue
        key = (r["symbol"], r["minute"])
        if r["at"] == "final":
            final[key] = r["row"]
        elif r["at"] == "check":
            check[key] = r["row"]
    zero = ("reads", "errors", "missing", "no_final", "compared", "before_close", "differ_any", "differ_high_low",
            "differ_close", "differ_open", "vol_trades_only")
    by_off = {L: dict.fromkeys(zero, 0) for L in EARLY_LABELS}
    sent = {L: [] for L in EARLY_LABELS}
    recv = {L: [] for L in EARLY_LABELS}
    syms = sorted({r["symbol"] for r in reads}, key=lambda s: SYMBOLS.index(s) if s in SYMBOLS else 99)
    by_sym = {s: {L: [0, 0] for L in EARLY_LABELS} for s in syms}
    by_bucket = {b: [0, 0, 0] for b in BUCKETS}          # compared, differ_any, differ_high_low
    nxt = {"next_has_trades": 0, "still_differ": 0, "still_differ_high_low": 0}
    examples = []
    for r in reads:
        L = r["at"]
        if L not in by_off:
            continue
        c = by_off[L]
        c["reads"] += 1
        if r["error"]:
            c["errors"] += 1
            continue
        if r["row"] is None:
            c["missing"] += 1
            continue
        f = final.get((r["symbol"], r["minute"]))
        if f is None:
            c["no_final"] += 1
            continue
        c["compared"] += 1
        sent[L].append(r["sent_ms"])
        recv[L].append(r["recv_ms"])
        if r["sent_ms"] < 0:
            c["before_close"] += 1
        d = [k for k in FIELDS if not same(k, r["row"][k], f[k])]
        hl = "high" in d or "low" in d
        b = by_bucket[bucket_of(r["sent_ms"])]
        b[0] += 1
        by_sym[r["symbol"]][L][1] += 1
        if d:
            c["differ_any"] += 1
            b[1] += 1
            by_sym[r["symbol"]][L][0] += 1
            if hl:
                c["differ_high_low"] += 1
                b[2] += 1
            if "close" in d:
                c["differ_close"] += 1
            if "open" in d:
                c["differ_open"] += 1
            if set(d) <= {"volume", "trades"}:
                c["vol_trades_only"] += 1
            examples.append((0 if hl else 1, r["sent_ms"], r, f, d))
        if r["next_trades"] is not None and r["next_trades"] > 0:
            nxt["next_has_trades"] += 1
            if d:
                nxt["still_differ"] += 1
                if hl:
                    nxt["still_differ_high_low"] += 1
    fc = [0, 0]
    fc_examples = []
    for key, row in check.items():
        f = final.get(key)
        if f is None:
            continue
        fc[0] += 1
        d = [k for k in FIELDS if not same(k, row[k], f[k])]
        if d:
            fc[1] += 1
            fc_examples.append((key, d))
    examples.sort(key=lambda e: (e[0], e[1]))
    safe = None
    for i, L in enumerate(EARLY_LABELS):
        if all(by_off[M]["compared"] > 0 and by_off[M]["differ_any"] == 0 for M in EARLY_LABELS[i:]):
            safe = L
            break
    return {"by_offset": by_off, "sent_ms": sent, "recv_ms": recv, "by_symbol": by_sym, "by_bucket": by_bucket, "next_rule": nxt,
            "final_vs_check": fc, "final_vs_check_examples": fc_examples[:5], "examples": examples[:12],
            "smallest_clean_offset": safe, "minutes": len({r["minute"] for r in reads})}


def median(xs):
    xs = sorted(xs)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2.0


def fmt_row(x):
    return "H %s L %s C %s V %s n %d" % (x["high"], x["low"], x["close"], x["volume"], x["trades"])


def report(s, symbols_n):
    lines = []
    w = lines.append
    w("minutes measured: %d, symbols: %d" % (s["minutes"], symbols_n))
    w("")
    w("read  sent/answered (median ms after close)  compared  differ_any  differ_high_low  differ_close  "
      "vol/trades_only  missing  errors  no_final")
    for L in EARLY_LABELS:
        c = s["by_offset"][L]
        m, a = median(s["sent_ms"][L]), median(s["recv_ms"][L])
        w("%-5s %22s %18d %11d %16d %13d %16d %8d %7d %9d" % (
            L, "-" if m is None else "%d/%d" % (m, a), c["compared"], c["differ_any"], c["differ_high_low"],
            c["differ_close"], c["vol_trades_only"], c["missing"], c["errors"], c["no_final"]))
    bad_open = sum(s["by_offset"][L]["differ_open"] for L in EARLY_LABELS)
    before = sum(s["by_offset"][L]["before_close"] for L in EARLY_LABELS)
    if bad_open or before:
        w("note: open differed %d times (should be 0); reads sent before the close: %d (should be 0)"
          % (bad_open, before))
    w("")
    w("by symbol (differ_any / compared):")
    w("%-9s " % "" + " ".join("%8s" % L for L in EARLY_LABELS))
    for sym, row in s["by_symbol"].items():
        w("%-9s " % sym + " ".join("%8s" % ("%d/%d" % tuple(row[L])) for L in EARLY_LABELS))
    w("")
    w("by real read delay (compared, differ_any, differ_high_low):")
    for (lo, hi), (n, d, hl) in s["by_bucket"].items():
        if n:
            name = ("< 0 ms" if lo is None else ">= %d ms" % lo if hi is None else "%d-%d ms" % (lo, hi))
            w("  %-14s %5d %5d %5d" % (name, n, d, hl))
    fc = s["final_vs_check"]
    w("")
    w("final (+25s) vs check (+50s): %d of %d differ (0 means the +25s read was final)" % (fc[1], fc[0]))
    for key, d in s["final_vs_check_examples"]:
        w("  %s %s changed after +25s: %s" % (key[0], hhmm(key[1]), ",".join(d)))
    n = s["next_rule"]
    w("next-minute rule: early reads where the next minute already had a trade: %d; of those still not final: %d "
      "(high/low: %d)" % (n["next_has_trades"], n["still_differ"], n["still_differ_high_low"]))
    w("smallest offset with no difference at it and every later offset in this sample: %s"
      % (s["smallest_clean_offset"] or "none"))
    if s["examples"]:
        w("")
        w("examples (high/low first):")
        for _, sent_ms, r, f, d in s["examples"]:
            w("  %s %s %s (sent %d ms after close): early %s | final %s  [%s]" % (
                r["symbol"], hhmm(r["minute"]), r["at"], sent_ms, fmt_row(r["row"]), fmt_row(f), ",".join(d)))
    w("")
    parts = []
    for L in EARLY_LABELS:
        c = s["by_offset"][L]
        parts.append("%s %d/%d (고가·저가 %d)" % (L, c["differ_any"], c["compared"], c["differ_high_low"]))
    w("요약: 마감 직후 읽은 1분봉이 25초 뒤 값과 다른 횟수 = " + ", ".join(parts))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--minutes", type=int, default=9, help="minute boundaries to measure (default 9, ~10 min)")
    ap.add_argument("--out", default=None, help="raw reads as JSON lines (default /tmp/kline_probe_<UTC>.jsonl)")
    args = ap.parse_args(argv)
    out = args.out or time.strftime("/tmp/kline_probe_%Y%m%dT%H%M%SZ.jsonl", time.gmtime())
    print("Binance USD-M 1m kline settle probe, %s UTC, %d minutes, %d symbols (Ctrl+C stops and summarises)"
          % (time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), args.minutes, len(SYMBOLS)))
    sys.stdout.flush()
    clock = Clock()
    pool = ThreadPoolExecutor(max_workers=len(SYMBOLS) * 4)

    def log(text):
        print(text)
        sys.stdout.flush()
    try:
        reads = run(args.minutes, SYMBOLS, clock, binance_klines, time.sleep, pool, log=log,
                    live_time=binance_time_fresh)
    finally:
        pool.shutdown(wait=False)
    with open(out, "w") as fh:
        for r in reads:
            fh.write(json.dumps(r) + "\n")
    print("")
    print(report(summarize(reads), len(SYMBOLS)))
    if getattr(clock, "live_lead", None):
        print("paper-bot-style clock lead (ms, positive = ahead of Binance): %s" % clock.live_lead)
    print("raw reads: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
