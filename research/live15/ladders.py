# 규칙봇 15: the take-profit ladder judged on the exchange screen (before fees) vs the current one (after fees), per
# exchange (owners 10-20: "13% 도달 후 12%로 내려가면 익절, 그 위로 계단식"). Read-only on paper3.db: the rule bot's real
# entries of the 15 strategies, replayed one position at a time per bot with each exchange's own stop and fees.
#   python3 research/live15/ladders.py      (P=/path/to/paper3.db to read another copy)
import sqlite3, json, os, collections, bisect, datetime as D
P = os.environ.get("P", "/var/lib/paperbot/paper3.db")
A = ["V39_ALL@1h", "S3_CMO_SANDWICH@30m", "N20_EMA9_CHOP@30m", "N05_PSAR_POC@30m", "S3_CMO_SANDWICH@1h", "N06_MACD_ORB@30m",
     "OBV_S@30m", "F9_IFVG@1h", "S6_EMA_DMI_ADX@1h", "F15_ORB@30m", "N08_ICHI_WR@30m"]
Bg = ["F3_BOS@30m", "F7_RF_ONLY@1h", "F9_FVG@1h", "N12_ICHI_AO@30m"]
ORDER = {a: i for i, a in enumerate(A + Bg)}
MARGIN = 0.3
# per exchange: net stop, round-trip cost (taker fee + slippage, both sides) as a share of price
BOTS = [("바이비트", 0.50, 2 * (0.00055 + 0.0002)), ("MEXC", 0.35, 2 * (0.0008 + 0.0002))]
pc = sqlite3.connect(f"file:{P}?mode=ro", uri=True)
bars = collections.defaultdict(lambda: ([], [], [], []))
for ts, sym, o, h, l in pc.execute("SELECT ts, symbol, open, high, low FROM live_bars ORDER BY ts"):
    b = bars[sym]; b[0].append(ts); b[1].append(o); b[2].append(h); b[3].append(l)
hr = {}
for sym, (t, o, h, l) in bars.items():
    d = {}
    for i in range(len(t)):
        k = t[i] // 3600000; x = d.get(k)
        d[k] = (max(x[0], h[i]), min(x[1], l[i])) if x else (h[i], l[i])
    hr[sym] = d
opp = collections.defaultdict(list)
for bc, tf, st, sym, side in pc.execute("SELECT bar_close, timeframe, strategy, symbol, side FROM signal_log"):
    opp[(f"{st}@{tf}", sym, side)].append(bc)
for v in opp.values():
    v.sort()
def rng(sym, k, n):
    v = [hr[sym][j] for j in range(k - n, k) if j in hr[sym]]
    return (max(a for a, _ in v), min(b for _, b in v), len(v)) if v else None
def chase(sym, side, px, t0):
    k = t0 // 3600000; r24, r7 = rng(sym, k, 24), rng(sym, k, 168)
    if not (r24 and r24[2] >= 20):
        return None
    p24 = (px - r24[1]) / max(r24[0] - r24[1], 1e-12)
    c = (side > 0 and p24 >= 0.9) or (side < 0 and p24 <= 0.1)
    if r7 and r7[2] >= 150:
        p7 = (px - r7[1]) / max(r7[0] - r7[1], 1e-12)
        c = c or (side > 0 and p7 >= 0.8) or (side < 0 and p7 <= 0.2)
    return c
def lock_now(best):
    # the 규칙봇 15 shape on one ROE scale: 11 -> 10, 15 -> 12, then every +5% (reached - 3%)
    return 0.12 + 0.05 * int((best - 0.15) / 0.05 + 1e-9) if best >= 0.15 else (0.10 if best >= 0.11 else None)
def lock_screen(best):
    # proposal on the exchange screen (before fees): 13 -> 12, then every +5% from 18 (reached - 3%)
    return 0.15 + 0.05 * int((best - 0.18) / 0.05 + 1e-9) if best >= 0.18 else (0.12 if best >= 0.13 else None)
LADDERS = [("지금: 수수료 뺀 순ROE 11%→10%, 15→12, 그 뒤 5%마다", "net", lock_now),
           ("제안: 거래소 화면 13%→12%, 18→15, 그 뒤 5%마다", "gross", lock_screen)]
def run(acct, sym, side, px, t0, stop_roe, rt, basis, ladder):
    t, o, h, l = bars[sym]
    lev = 40 if sym.startswith("BTC") else 30
    gross = lambda p: lev * side * (p / px - 1)
    net = lambda p: gross(p) - lev * rt
    stop = px * (1 - side * (stop_roe / lev - rt)); best = -1.0; lock = None
    ops = opp.get((acct, sym, -side), [])
    j = bisect.bisect_right(ops, t0); nxt = ops[j] if j < len(ops) else None
    for i in range(bisect.bisect_left(t, t0 // 60000 * 60000), len(t)):
        if lock is None and nxt is not None and t[i] > t0 and t[i] >= nxt:
            return net(o[i] * (1 - side * 0.0002)), "F", t[i]
        bad, good = (l[i], h[i]) if side > 0 else (h[i], l[i])
        if side * (bad - stop) <= 0:
            return net(stop), ("W" if lock is not None else "L"), t[i] + 60000
        best = max(best, net(good) if basis == "net" else gross(good))
        lk = ladder(best)
        if lk is not None and (lock is None or lk > lock):
            lock = lk
            stop = px * (1 + side * (lk / lev + (rt if basis == "net" else 0.0)))
    return None, None, None
kst = lambda ms: D.datetime.fromtimestamp(ms / 1000, D.timezone(D.timedelta(hours=9)))
raw = []
for a, d in pc.execute("SELECT account_id, data FROM trades ORDER BY entry_time"):
    if a not in ORDER:
        continue
    tr = json.loads(d); sym = tr["symbol"]
    if sym not in bars or tr["entry_time"] < bars[sym][0][0] or kst(tr["entry_time"]).weekday() >= 5:
        continue
    if a in Bg and chase(sym, tr["side"], tr["entry_price"], tr["entry_time"]) is not False:
        continue
    raw.append((tr["entry_time"] // 60000 * 60000, ORDER[a], a, sym, tr["side"], tr["entry_price"]))
raw.sort()
print(f"후보 진입 {len(raw)}개 (15개 매매법, B는 추격 막기, 평일만), 봇마다 1포지션, 증거금 {MARGIN:.0%} 복리")
print("결과 %는 모두 수수료·미끄러짐을 뺀 실제 순ROE입니다 (거래소별 수수료로 계산).\n")
for name, stop_roe, rt in BOTS:
    print(f"== {name} (손절 순ROE -{stop_roe * 100:.0f}%, 왕복 비용 {rt * 100:.2f}%) ==")
    for lname, basis, ladder in LADDERS:
        free, eq, peak, mdd, rs = 0, 1.0, 1.0, 0.0, []
        for t0, _, a, sym, side, px in raw:
            if t0 < free:
                continue
            r, kind, ex = run(a, sym, side, px, t0, stop_roe, rt, basis, ladder)
            if r is None:
                continue
            free = ex; eq *= 1 + MARGIN * r; peak = max(peak, eq); mdd = max(mdd, 1 - eq / peak); rs.append((r, kind))
        n = len(rs); w = [r for r, _ in rs if r > 0]; ls = [-r for r, _ in rs if r <= 0]
        aw = sum(w) / len(w) if w else 0.0; al = sum(ls) / len(ls) if ls else 0.0
        be = al / (al + aw) if aw + al > 0 else float("nan")
        print(f"  {lname}")
        print(f"    진입 {n}번 · 이김 {len(w)} / 짐 {len(ls)} (그중 -손절 {sum(k == 'L' for _, k in rs)}, 빠른 손절 {sum(k == 'F' for _, k in rs)}) · "
              f"승률 {len(w) / max(n, 1):.0%} (본전 약 {be:.0%}) · 평균 이김 +{aw * 100:.1f}% / 평균 짐 -{al * 100:.1f}% · "
              f"계좌 {eq:.2f}배 · 최대 낙폭 {mdd:.0%}")
    print()
print("이 기간은 15개를 고른 바로 그 기간입니다. 숫자는 낙관적이고, 두 계단 사이의 차이를 보는 용도입니다.")
