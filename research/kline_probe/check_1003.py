import json, sqlite3, sys, time
db = sys.argv[1] if len(sys.argv) > 1 else "/var/lib/paperbot/paper3.db"
c = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
D = 1790985600000  # 2026-10-03 00:00 UTC
hm = lambda ms: time.strftime("%H:%M:%S", time.gmtime(ms / 1000.0)) + ".%03d" % (ms % 1000)
print("1) feed warnings on 2026-10-03 (data gap / no bars / clock / data error / no new bars):")
for ts, lvl, txt in c.execute("SELECT ts, level, text FROM alerts WHERE ts >= ? AND ts < ? ORDER BY ts", (D, D + 86400000)):
    if any(k in txt for k in ("data gap", "no bars", "clock", "data error", "no new closed bars")):
        print("  ", hm(ts), lvl, txt[:160])
print("2) suspect minutes: when live handled that step (order book read time, only if some account traded then):")
for name, m in (("BTC+ETH 01:17", 77), ("LTC 02:58", 178), ("BCH 20:42", 1242), ("SOL 20:51", 1251), ("SOL 22:11", 1331)):
    ts = D + m * 60000
    bts = sorted({json.loads(d).get("book_ts") for (d,) in c.execute("SELECT data FROM fill_costs WHERE ts = ?", (ts,))} - {None})
    print("   %-14s ms after close: %s" % (name, [b - (ts + 60000) for b in bts][:5] or "none (no trade in that step)"))
print("3) the live records of the 6 differing trades:")
for aid, entry in (("N01_ST_EMA@5m", 1791055500000), ("N10_HA_PSAR@5m", 1791061800000), ("N16_BBRSI@15m", 1790970300000),
                   ("OBV_B@15m", 1790972100000), ("N22_VORTEX_PSAR@5m", 1791057900000), ("N24_DMI@5m", 1790993100000)):
    for (d,) in c.execute("SELECT data FROM trades WHERE account_id = ? AND entry_time = ?", (aid, entry)):
        t = json.loads(d)
        print("   %-19s %s exit %s %-4s stop %s lock %s mfe %s mae %s" % (aid, t["symbol"], hm(t["exit_time"]),
              t["exit_reason"], t["stop_price"], t["lock_roe"], t["mfe_price"], t["mae_price"]))
