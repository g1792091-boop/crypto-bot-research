"""Offline tests of kline_probe.py with a fake Binance (no network).

The fake exchange builds each minute's kline from fake trades. A trade becomes visible in the REST kline only
``delay`` ms after it happened; most delays are 30 ms, but each symbol has "hiccup" windows in which trades are
folded in 0.4-7 s late (and one trade is 30 s late, to exercise the +25 s vs +50 s check). Ground truth is
recomputed here, independently of the probe, from the exact server time of every request (the fake echoes it
in the kline's unused last field).
"""

import random
import sys
import threading
import time
import os
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research", "kline_probe"))
import kline_probe as kp  # noqa: E402

MIN = 60000


class FakeExchange:
    def __init__(self, seed, symbols, t0, gap=(20_000, 150_000)):
        self.rng = random.Random(seed)
        self.symbols = symbols
        self.t0 = t0
        self.trades = {}          # (sym, minute) -> [(t, price, qty, delay)]
        self.hiccups = {}         # sym -> [(start, end, delay)]
        self.lock = threading.Lock()
        for s in symbols:
            hs = []
            t = t0
            while t < t0 + 120 * MIN:
                t += self.rng.randint(*gap)
                hs.append((t, t + self.rng.randint(500, 4000), self.rng.choice([400, 900, 1500, 2500, 4000, 7000])))
            self.hiccups[s] = hs
        self.late_key = None

    def _gen(self, sym, minute):
        key = (sym, minute)
        with self.lock:
            if key in self.trades:
                return self.trades[key]
            rng = random.Random(hash((sym, minute)) & 0xFFFFFFFF)
            px = 100.0 + (minute // MIN) % 50
            out = []
            t = minute + 1
            for k in range(rng.randint(5, 120)):
                px = max(1.0, px + rng.choice([-0.01, 0.0, 0.01]) * rng.randint(1, 5))
                d = 30
                for a, b, dd in self.hiccups[sym]:
                    if a <= t < b:
                        d = dd
                out.append((t, round(px, 2), rng.randint(1, 50) / 10.0, d))
                t += rng.randint(1, max(2, (minute + MIN - t) // 3))
                if t >= minute + MIN:
                    break
            # trades in the last 300 ms of every minute (where truncation shows)
            for k in range(rng.randint(0, 4)):
                tt = minute + MIN - rng.randint(1, 300)
                if tt > out[-1][0]:
                    d = 30
                    for a, b, dd in self.hiccups[sym]:
                        if a <= tt < b:
                            d = dd
                    out.append((tt, round(px + rng.choice([-0.3, 0.3]), 2), 1.0, d))
            if self.late_key is None and sym == self.symbols[1] and minute >= self.t0 + 2 * MIN:
                t_last = minute + MIN - 2
                out.append((t_last, round(px + 5.0, 2), 1.0, 30_000))      # visible only after +30 s
                self.late_key = key
            out.sort()
            self.trades[key] = out
            return out

    def row(self, sym, minute, q):
        """The kline as the REST endpoint shows it at server time q (None if the minute has not started)."""
        if q < minute:
            return None
        vis = [tr for tr in self._gen(sym, minute) if tr[0] + tr[3] <= q and tr[0] <= q]
        if not vis:
            prev = self._gen(sym, minute - MIN)
            p = prev[-1][1]
            o = h = l = c = p
            v, n = 0.0, 0
        else:
            o, c = vis[0][1], vis[-1][1]
            h, l = max(t[1] for t in vis), min(t[1] for t in vis)
            v, n = sum(t[2] for t in vis), len(vis)
        return [minute, "%.2f" % o, "%.2f" % h, "%.2f" % l, "%.2f" % c, "%.1f" % v, minute + MIN - 1, "0", n,
                "0", "0", repr(q)]

    def klines(self, sym, start, q):
        out = []
        for m in (start, start + MIN):
            r = self.row(sym, m, q)
            if r is not None:
                out.append(r)
        return out


# ------------------------------------------------------------------ simulated time, inline execution
class Sim:
    def __init__(self, t0, local_off=-1234.0):
        self.T = float(t0)
        self.local_off = local_off

    def local(self):
        return self.T + self.local_off

    def sleep(self, s):
        self.T += s * 1000.0

    def server_time(self):
        self.T += 4
        st = int(self.T)
        self.T += 4
        return st


class Done:
    def __init__(self, fn, a):
        try:
            self.v, self.e = fn(*a), None
        except Exception as exc:  # noqa: BLE001
            self.v, self.e = None, exc

    def result(self, timeout=None):
        if self.e:
            raise self.e
        return self.v


class Inline:
    def submit(self, fn, *a):
        return Done(fn, a)


def truth(ex, reads):
    """Independent expected counts from the exact request times (q echoed in raw[11])."""
    final = {}
    for r in reads:
        if r["at"] == "final" and r["raw"] is not None and not r["error"]:
            final[(r["symbol"], r["minute"])] = r["raw"]
    exp = {L: {"compared": 0, "differ_any": 0, "differ_high_low": 0, "errors": 0, "missing": 0, "no_final": 0}
           for L in kp.EARLY_LABELS}
    nxt = [0, 0]
    for r in reads:
        if r["at"] not in exp:
            continue
        e = exp[r["at"]]
        if r["error"]:
            e["errors"] += 1
            continue
        if r["raw"] is None:
            e["missing"] += 1
            continue
        f = final.get((r["symbol"], r["minute"]))
        if f is None:
            e["no_final"] += 1
            continue
        q, qf = float(r["raw"][11]), float(f[11])
        early, fin = ex.row(r["symbol"], r["minute"], q), ex.row(r["symbol"], r["minute"], qf)
        assert early[1:9] == r["raw"][1:9]        # the probe stored what the exchange served
        e["compared"] += 1
        diff = early[1:6] + [early[8]] != fin[1:6] + [fin[8]]
        hl = (early[2], early[3]) != (fin[2], fin[3])
        e["differ_any"] += diff
        e["differ_high_low"] += hl
        n = ex.row(r["symbol"], r["minute"] + MIN, q)
        if n is not None and n[8] > 0:
            nxt[0] += 1
            nxt[1] += diff
    return exp, nxt


def check(ex, reads, s):
    exp, nxt = truth(ex, reads)
    for L in kp.EARLY_LABELS:
        got = {k: s["by_offset"][L][k] for k in exp[L]}
        assert got == exp[L], (L, got, exp[L])
    assert [s["next_rule"]["next_has_trades"], s["next_rule"]["still_differ"]] == nxt, (s["next_rule"], nxt)
    return exp


def test_clock():
    sim = Sim(1_790_000_000_000.0, local_off=-1234.0)
    c = kp.Clock(server_time=sim.server_time, local=sim.local)
    c.sync()
    assert abs(c.offset - 1234.0) <= 4.0, c.offset
    assert c.rtt == 8.0
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        raise OSError("down")
    c2 = kp.Clock(server_time=flaky, local=sim.local)
    try:
        c2.sync()
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass
    print("clock ok: offset %.1f rtt %.1f" % (c.offset, c.rtt))


def test_inline():
    t0 = 1_791_000_000_000 + 37_123          # starts mid-minute
    ex = FakeExchange(7, kp.SYMBOLS, t0 - 5 * MIN)
    sim = Sim(t0)
    calls = {"n": 0}

    def fetch(sym, start):
        calls["n"] += 1
        sim.T += 15                                  # request travels
        q = sim.T
        n = calls["n"]
        sim.T += 15                                  # answer travels
        if n % 23 == 0:
            raise OSError("simulated timeout")
        if n % 31 == 0:
            return []                                # an empty answer
        return ex.klines(sym, start, q)
    def fresh_time():                 # a new connection: ~3 round trips before the server stamps the time
        sim.T += 30
        st = int(sim.T)
        sim.T += 10
        return st
    clk = kp.Clock(server_time=sim.server_time, local=sim.local)
    reads = kp.run(8, kp.SYMBOLS, clk, fetch, sim.sleep, Inline(), log=print, live_time=fresh_time)
    assert len(clk.live_lead) == 5 and all(29 <= x <= 31 for x in clk.live_lead), clk.live_lead
    assert len(reads) == 8 * 6 * len(kp.SYMBOLS), len(reads)
    s = kp.summarize(reads)
    exp = check(ex, reads, s)
    # the scheduled offsets were respected (first symbol of each batch is sent within ~20 ms of its target)
    for r in reads:
        if r["symbol"] == kp.SYMBOLS[0] and r["at"] in kp.EARLY_LABELS:
            target = {"+0.2s": 200, "+1s": 1000, "+3s": 3000, "+6s": 6000}[r["at"]]
            assert 0 <= r["sent_ms"] - target <= 25, (r["at"], r["sent_ms"])
    tot = {k: sum(exp[L][k] for L in exp) for k in ("differ_any", "errors", "missing", "no_final")}
    assert tot["differ_any"] > 0 and tot["errors"] > 0 and tot["missing"] > 0, tot
    # earlier reads differ at least as often as later ones in this fake
    d = [s["by_offset"][L]["differ_any"] for L in kp.EARLY_LABELS]
    assert d[0] >= d[-1], d
    # the 30 s late trade shows up as a final-vs-check difference
    assert s["final_vs_check"][1] >= 1, s["final_vs_check"]
    print(kp.report(s, len(kp.SYMBOLS)))
    print("inline ok:", {L: (exp[L]["differ_any"], exp[L]["compared"]) for L in exp}, tot)


def test_heavy():
    """Hiccups every 5-25 s with delays up to 7 s, so +1 s, +3 s and +6 s reads differ too."""
    t0 = 1_794_000_000_000 + 12_345
    ex = FakeExchange(5, kp.SYMBOLS, t0 - 5 * MIN, gap=(5_000, 25_000))
    sim = Sim(t0, local_off=+777.0)

    def fetch(sym, start):
        sim.T += 40
        q = sim.T
        sim.T += 40
        return ex.klines(sym, start, q)
    reads = kp.run(10, kp.SYMBOLS, kp.Clock(server_time=sim.server_time, local=sim.local), fetch, sim.sleep, Inline())
    s = kp.summarize(reads)
    exp = check(ex, reads, s)
    d = [s["by_offset"][L]["differ_any"] for L in kp.EARLY_LABELS]
    assert d[0] > 0 and d[1] > 0 and d[2] > 0, d
    assert s["smallest_clean_offset"] == ("+6s" if d[3] == 0 else None), s["smallest_clean_offset"]
    print(kp.report(s, len(kp.SYMBOLS)))
    print("heavy ok:", {L: (exp[L]["differ_any"], exp[L]["differ_high_low"], exp[L]["compared"]) for L in exp},
          "next rule", s["next_rule"])


def test_threaded(scale=40.0, minutes=3):
    """Real threads and real sleeps on a time-scaled fake clock (1 real second = ``scale`` seconds)."""
    base = 1_792_000_000_000 + 41_000
    ex = FakeExchange(11, kp.SYMBOLS, base - 5 * MIN)
    r0 = time.monotonic()

    def server_now():
        return base + (time.monotonic() - r0) * scale * 1000.0

    def server_time():
        time.sleep(0.0002)
        st = int(server_now())
        time.sleep(0.0002)
        return st

    def fetch(sym, start):
        time.sleep(0.0005)
        q = server_now()
        time.sleep(0.0005)
        return ex.klines(sym, start, q)
    clock = kp.Clock(server_time=server_time, local=lambda: server_now() + 500.0)
    pool = ThreadPoolExecutor(max_workers=len(kp.SYMBOLS) * 4)
    t = time.monotonic()
    reads = kp.run(minutes, kp.SYMBOLS, clock, fetch, lambda s: time.sleep(s / scale), pool)
    pool.shutdown(wait=True)
    assert len(reads) == minutes * 6 * len(kp.SYMBOLS), len(reads)
    s = kp.summarize(reads)
    exp = check(ex, reads, s)
    print("threaded ok in %.1f s:" % (time.monotonic() - t), {L: (exp[L]["differ_any"], exp[L]["compared"]) for L in exp},
          "sent medians", {L: kp.median(s["sent_ms"][L]) for L in kp.EARLY_LABELS})


def test_main_offline(tmp_path):
    """main() end to end with the network functions swapped for the fake (no Binance access)."""
    tmp = str(tmp_path)
    base = 1_793_000_000_000 + 50_500
    ex = FakeExchange(3, kp.SYMBOLS, base - 5 * MIN)
    scale = 60.0
    r0 = time.monotonic()

    def server_now():
        return base + (time.monotonic() - r0) * scale * 1000.0
    kp.binance_time = lambda: int(server_now())
    kp.binance_time_fresh = lambda: int(server_now())
    kp.binance_klines = lambda sym, start: ex.klines(sym, start, server_now())
    kp.local_ms = lambda: server_now() - 250.0
    kp.Clock.__init__.__defaults__ = (kp.binance_time, kp.local_ms)
    real_sleep = time.sleep
    kp.time.sleep = lambda s: real_sleep(s / scale)
    try:
        out = os.path.join(tmp, "probe_out.jsonl")
        assert kp.main(["--minutes", "2", "--out", out]) == 0
        n = sum(1 for _ in open(out))
        assert n == 2 * 6 * len(kp.SYMBOLS), n
    finally:
        kp.time.sleep = real_sleep
    print("main ok:", out, n, "lines")


if __name__ == "__main__":
    test_clock()
    test_inline()
    test_heavy()
    test_threaded()
    import pathlib, tempfile
    test_main_offline(pathlib.Path(tempfile.mkdtemp()))
    print("ALL OK")
