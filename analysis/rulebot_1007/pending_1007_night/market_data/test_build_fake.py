"""Build a fake /var/lib/paperbot with the repo's own schema code (LiqStore, FlowArchive, MarketArchive, Store3) at
realistic per-day volumes, for testing rb_export_market.py. Usage: python3 -I -B test_build_fake.py REPO FAKEROOT DAYS"""
import json, os, random, sys

repo, root, days = sys.argv[1], sys.argv[2], float(sys.argv[3])
sys.path.insert(0, repo)
from paperbot.liqstream import LiqStore, parse          # noqa: E402
from paperbot.flow import FlowArchive, STATS, PREMIUM_COLS  # noqa: E402
from paperbot.archive import MarketArchive              # noqa: E402
from paperbot.store3 import Store3                      # noqa: E402

random.seed(7)
T0 = 1791417600000                                      # 2026-10-08 00:00 UTC
END = T0 + int(days * 86_400_000)
COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LTCUSDT", "BCHUSDT", "DOGEUSDT", "XRPUSDT"]
PX = dict(zip(COINS, [85000, 2700, 120, 70, 315, 0.096, 2.1]))
OTHERS = [f"ALT{i}USDT" for i in range(300)]
LIQ7, LIQO = int(os.environ.get("LIQ7", 5000)), int(os.environ.get("LIQO", 15000))   # events per day (assumed)
os.makedirs(os.path.join(root, "archive", "run-20261005T183457Z"), exist_ok=True)
clock = lambda: END                                     # noqa: E731

# liq.db: a few rows before the window (9/30), then LIQ7 + LIQO events a day
ls = LiqStore(os.path.join(root, "liq.db"), clock_ms=clock)
def ev(sym, t):
    p = PX.get(sym, 1.0) * (1 + random.uniform(-0.01, 0.01))
    q = round(random.expovariate(1 / (3000 / p)), 6)
    return {"e": "forceOrder", "E": t + 5, "o": {"s": sym, "S": random.choice(["BUY", "SELL"]), "o": "LIMIT", "f": "IOC", "q": str(q), "p": str(p), "ap": str(p),
            "X": "FILLED", "l": str(q), "z": str(q), "T": t}}
ls.add(parse([ev("BTCUSDT", 1790726400000 + i * 60000) for i in range(50)]))
msgs = [ev(random.choice(COINS), random.randrange(T0, END)) for _ in range(int(LIQ7 * days))]
msgs += [ev(random.choice(OTHERS), random.randrange(T0, END)) for _ in range(int(LIQO * days))]
ls.add(parse(msgs))
for k in range(int(days * 144)):                        # silent-socket style reconnects every 10 min
    ls.log("connected", {"attempt": k}); ls.log("disconnected", {"error": "WebSocketTimeoutException: timed out"})
ls.close()

# flow.db: 5-minute stats for 7 coins, plus a revision and a gap row
fa = FlowArchive(os.path.join(root, "flow.db"), clock_ms=clock)
ts = list(range(T0 - 86_400_000, END, 300_000))
for sym in COINS:
    for _ds, (table, fields) in STATS.items():
        fa.insert(table, tuple(c for c, _ in fields), sym, [(t, tuple(random.random() * 3 for _ in fields)) for t in ts])
    fa.insert("premium5m", PREMIUM_COLS, sym, [(t, tuple(random.gauss(0, 3e-4) for _ in range(4))) for t in ts])
fa.insert("oi5m", ("sum_oi", "sum_oi_value"), "BTCUSDT", [(ts[5], (1.0, 2.0))])
fa.log("gaps", (END, "BTCUSDT", "oi", T0 - 40 * 86_400_000, T0 - 30 * 86_400_000))
fa.log("sync_log", (END, "BTCUSDT", "oi", 12, 0, ts[-1], 1))
fa.log("system_log", (END, "sync", json.dumps({"gaps": []})))
fa.close()

# market.db (legacy recorder): bars that stopped on 10/01, funding through then
ma = MarketArchive(os.path.join(root, "market.db"), clock_ms=clock)
stop = 1790812800000                                    # 2026-10-01 00:00 UTC
for sym in COINS:
    ma.insert_klines(sym, [[t, 1, 2, 0.5, 1.5, 10, t + 299_999, 15, 3, 4] for t in range(stop - 3 * 86_400_000, stop, 300_000)], END)
    ma.insert_funding(sym, [{"fundingTime": t, "fundingRate": "0.0001", "markPrice": "1"} for t in
                            range(stop - 10 * 86_400_000, stop, 8 * 3_600_000)])
ma.close()

# paper3.db (current + one archive): fill_costs with walked book levels, live_bars 1m for 6 coins
def paper(path, t0, t1, fc_per_day):
    st = Store3(path)
    rows = []
    for _ in range(int(fc_per_day * (t1 - t0) / 86_400_000)):
        sym = random.choice(COINS[:6]); best = PX[sym]; side = random.choice([1, -1])
        bk = [[round(best * (1 + side * 1e-4 * i), 6), round(random.uniform(1, 50) * 1000 / best, 6)] for i in range(random.randint(2, 30))]
        rows.append({"ts": random.randrange(t0, t1) // 60000 * 60000, "account_id": f"A{random.randint(1, 331)}", "symbol": sym,
                     "event": random.choice(["entry", "exit"]), "order_side": side, "qty": 1.0, "notional": 45000.0,
                     "status": "ok", "assumed_slip": 0.0002, "vwap": best, "slip_best": 1e-5, "slip_mid": 3e-5,
                     "levels": 2, "enough": True, "filled_notional": 45000.0, "best": best, "spread": 2e-5,
                     "book_ts": t0, "book": bk})
    st.fill_costs(rows)
    bars = [{"ts": t, "symbol": s, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.05, "volume": 123.4, "mark_open": 1.0,
             "mark_high": 1.1, "mark_low": 0.9, "mark_close": 1.05, "close_time": t + 59_999, "processed_at": t + 61_000}
            for t in range(t0, t1, 60_000) for s in COINS[:6]]
    st.live_bars(bars)
    st.conn.commit(); st.conn.close()

paper(os.path.join(root, "paper3.db"), T0, END, 1500)
paper(os.path.join(root, "archive", "run-20261005T183457Z", "paper3.db"), 1791100800000, 1791100800000 + 86_400_000, 800)
print("built", root, {f: os.path.getsize(os.path.join(root, f)) for f in os.listdir(root) if f.endswith(".db")})
