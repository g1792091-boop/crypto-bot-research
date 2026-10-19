# 규칙봇 15: the same entries with another stop (the owners' idea 10-19: run MEXC differently from Bybit so the two
# bots do not win and lose together). Read-only on paper3.db: the rule bot's real entries of the 15 strategies,
# replayed one position at a time per bot with the new ladder and the own-reverse fast stop before the first lock,
# each stop level its own bot; then -50% (Bybit) next to each other level (MEXC) as two halves of the money. Run:
#   python3 research/live15/stops.py      (P=/path/to/paper3.db to read another copy)
import sqlite3, json, os, collections, bisect, datetime as D
P = os.environ.get("P", "/var/lib/paperbot/paper3.db")
A = ["V39_ALL@1h", "S3_CMO_SANDWICH@30m", "N20_EMA9_CHOP@30m", "N05_PSAR_POC@30m", "S3_CMO_SANDWICH@1h", "N06_MACD_ORB@30m",
     "OBV_S@30m", "F9_IFVG@1h", "S6_EMA_DMI_ADX@1h", "F15_ORB@30m", "N08_ICHI_WR@30m"]
Bg = ["F3_BOS@30m", "F7_RF_ONLY@1h", "F9_FVG@1h", "N12_ICHI_AO@30m"]
ORDER = {a: i for i, a in enumerate(A + Bg)}
MARGIN = 0.3
STOPS = (0.20, 0.25, 0.30, 0.35, 0.40, 0.50)
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
def run(acct, sym, side, px, t0, stop_roe):
    # net stop_roe stop (fees and slippage included), ladder 11->10, 15->12, then +5% steps (reached - 3%),
    # own reverse signal before the first lock
    t, o, h, l = bars[sym]
    lev = 40 if sym.startswith("BTC") else 30; rt = 0.0015
    roe = lambda p: lev * (side * (p / px - 1) - rt)
    stop = px * (1 - side * (stop_roe / lev - rt)); best = -1.0; lock = None
    ops = opp.get((acct, sym, -side), [])
    j = bisect.bisect_right(ops, t0); nxt = ops[j] if j < len(ops) else None
    for i in range(bisect.bisect_left(t, t0 // 60000 * 60000), len(t)):
        if lock is None and nxt is not None and t[i] > t0 and t[i] >= nxt:
            return roe(o[i] * (1 - side * 0.0002)), "F", t[i]
        bad, good = (l[i], h[i]) if side > 0 else (h[i], l[i])
        if side * (bad - stop) <= 0:
            return (lock, "W", t[i] + 60000) if lock is not None else (roe(stop), "L", t[i] + 60000)
        best = max(best, roe(good))
        lk = 0.12 + 0.05 * int((best - 0.15) / 0.05 + 1e-9) if best >= 0.15 else (0.10 if best >= 0.11 else None)
        if lk is not None and (lock is None or lk > lock):
            lock = lk; stop = px * (1 + side * (lk / lev + rt))
    return None, None, None
kst = lambda ms: D.datetime.fromtimestamp(ms / 1000, D.timezone(D.timedelta(hours=9)))
raw = []
for a, d in pc.execute("SELECT account_id, data FROM trades ORDER BY entry_time"):
    if a not in ORDER:
        continue
    t = json.loads(d); sym = t["symbol"]
    if sym not in bars or t["entry_time"] < bars[sym][0][0] or kst(t["entry_time"]).weekday() >= 5:
        continue
    if a in Bg and chase(sym, t["side"], t["entry_price"], t["entry_time"]) is not False:
        continue
    raw.append((t["entry_time"] // 60000 * 60000, ORDER[a], a, sym, t["side"], t["entry_price"]))
raw.sort()
def replay(stop_roe):
    free, eq, curve, taken = 0, 1.0, [], {}
    for t0, _, a, sym, side, px in raw:
        if t0 < free:
            continue
        r, kind, ex = run(a, sym, side, px, t0, stop_roe)
        if r is None:
            continue
        free = ex; eq *= 1 + MARGIN * r; curve.append((ex, eq)); taken[(t0, a, sym)] = (r, kind)
    return curve, taken
def mdd_of(curve):
    peak, m = 1.0, 0.0
    for _, e in curve:
        peak = max(peak, e); m = max(m, 1 - e / peak)
    return m
def streak_of(taken):
    s = w = 0
    for k in sorted(taken):
        s = s + 1 if taken[k][0] <= 0 else 0; w = max(w, s)
    return w
lo = min(v[0][0] for v in bars.values()); hi = max(v[0][-1] for v in bars.values())
wd = len({kst(x).date() for x in range(lo, hi, 3600000) if kst(x).weekday() < 5})
print(f"후보 진입 {len(raw)}개 (15개 매매법, B는 추격 막기, 평일만), 평일 {wd}일, 봇마다 1포지션, 증거금 {MARGIN:.0%} 복리")
print("손절만 다르고 나머지(계단 익절, 빠른 손절, 진입)는 같습니다. 손절이 짧으면 일찍 끝나서 다음 신호를 더 탈 수도 있습니다.\n")
res = {s: replay(s) for s in STOPS}
print("== 손절별 (봇 하나) ==")
for s in STOPS:
    curve, taken = res[s]
    v = list(taken.values()); n = len(v)
    w = sum(k == "W" for _, k in v); L = sum(k == "L" for _, k in v); F = sum(k == "F" for _, k in v)
    wins = [r for r, k in v if r > 0]; losses = [-r for r, k in v if r <= 0]
    aw = sum(wins) / len(wins) if wins else 0.0; al = sum(losses) / len(losses) if losses else 0.0
    be = al / (al + aw) if aw + al > 0 else float("nan")
    eq = curve[-1][1] if curve else 1.0
    print(f"순ROE -{s*100:.0f}%: 진입 {n:3d}번 {w}승 {L}패 빠른손절 {F} | 승률 {sum(r > 0 for r, _ in v)/max(n,1):.0%} "
          f"(본전 약 {be:.0%}: 평균 이김 +{aw*100:.1f}% / 평균 짐 -{al*100:.1f}%) | 계좌 {eq:.2f}배 | 최대 낙폭 {mdd_of(curve):.0%} "
          f"| 최대 연속 손실 {streak_of(taken)}")
print("\n== 바이비트 -50% + MEXC 다른 손절 (돈을 반씩, 두 봇 합계) ==")
c50, t50 = res[0.50]
for s in STOPS[:-1]:
    cx, tx = res[s]
    pts = sorted(set(t for t, _ in c50) | set(t for t, _ in cx))
    i = j = 0; e1 = e2 = 1.0; both = []
    for t in pts:
        while i < len(c50) and c50[i][0] <= t:
            e1 = c50[i][1]; i += 1
        while j < len(cx) and cx[j][0] <= t:
            e2 = cx[j][1]; j += 1
        both.append((t, (e1 + e2) / 2))
    same = [k for k in t50 if k in tx]
    split = sum(1 for k in same if (t50[k][0] > 0) != (tx[k][0] > 0))
    print(f"MEXC -{s*100:.0f}%: 합계 {both[-1][1] if both else 1.0:.2f}배 | 합계 최대 낙폭 {mdd_of(both):.0%} "
          f"| 같은 진입 {len(same)}번 중 한쪽만 이긴 거래 {split}번")
print(f"(비교: 둘 다 -50%면 합계 {c50[-1][1] if c50 else 1.0:.2f}배, 최대 낙폭 {mdd_of(c50):.0%})")
print("\n이 2주는 15개를 고른 바로 그 기간입니다. 숫자는 낙관적이고, 손절 사이의 차이를 보는 용도입니다.")
