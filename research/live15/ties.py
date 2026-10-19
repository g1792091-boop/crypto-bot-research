# 규칙봇 15: when several signals come at the same minute, does the pick order matter? Read-only on paper3.db
# (the rule bot's last weeks of real entries, replayed one position at a time with the new rule). Run on the server:
#   python3 research/live15/ties.py      (P=/path/to/paper3.db to read another copy)
import sqlite3, json, os, collections, bisect, random, datetime as D
P = os.environ.get("P", "/var/lib/paperbot/paper3.db")
A = ["V39_ALL@1h", "S3_CMO_SANDWICH@30m", "N20_EMA9_CHOP@30m", "N05_PSAR_POC@30m", "S3_CMO_SANDWICH@1h", "N06_MACD_ORB@30m",
     "OBV_S@30m", "F9_IFVG@1h", "S6_EMA_DMI_ADX@1h", "F15_ORB@30m", "N08_ICHI_WR@30m"]
Bg = ["F3_BOS@30m", "F7_RF_ONLY@1h", "F9_FVG@1h", "N12_ICHI_AO@30m"]
ORDER = {a: i for i, a in enumerate(A + Bg)}
MARGIN = 0.3
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
def where(sym, side, px, t0):
    # 0 = the cheap end for this side (long near the 7-day low), 1 = the chase end; None = too little data
    r7 = rng(sym, t0 // 3600000, 168)
    if not (r7 and r7[2] >= 150):
        return None
    p = (px - r7[1]) / max(r7[0] - r7[1], 1e-12)
    return p if side > 0 else 1 - p
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
def run(acct, sym, side, px, t0):
    # the new rule: net -50% stop, ladder 11->10, 15->12, then +5% steps (reached - 3%), own reverse signal before the first lock
    t, o, h, l = bars[sym]
    lev = 40 if sym.startswith("BTC") else 30; rt = 0.0015
    roe = lambda p: lev * (side * (p / px - 1) - rt)
    stop = px * (1 - side * (0.5 / lev - rt)); best = -1.0; lock = None
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
cands = []
for a, d in pc.execute("SELECT account_id, data FROM trades ORDER BY entry_time"):
    if a not in ORDER:
        continue
    t = json.loads(d); sym = t["symbol"]
    if sym not in bars or t["entry_time"] < bars[sym][0][0] or kst(t["entry_time"]).weekday() >= 5:
        continue
    if a in Bg and chase(sym, t["side"], t["entry_price"], t["entry_time"]) is not False:
        continue
    r, kind, ex = run(a, sym, t["side"], t["entry_price"], t["entry_time"])
    if r is None:
        continue
    cands.append(dict(t0=t["entry_time"] // 60000 * 60000, a=a, sym=sym, side=t["side"], r=r, kind=kind, ex=ex,
                      tf=a.split("@")[1], pos=where(sym, t["side"], t["entry_price"], t["entry_time"])))
moments = collections.OrderedDict()
for c in sorted(cands, key=lambda c: c["t0"]):
    moments.setdefault(c["t0"], []).append(c)
def agree(g, c):
    return sum(1 for x in g if x["sym"] == c["sym"] and x["side"] == c["side"])
def clash(g, c):
    return any(x["sym"] == c["sym"] and x["side"] != c["side"] for x in g)
RULES = [
    ("지금 규칙: 승률 순(목록 순서)", lambda g: min(g, key=lambda c: ORDER[c["a"]])),
    ("긴 봉(1시간) 먼저, 그다음 승률 순", lambda g: min(g, key=lambda c: (c["tf"] != "1h", ORDER[c["a"]]))),
    ("같은 코인·같은 방향 신호가 많은 쪽 먼저", lambda g: min(g, key=lambda c: (-agree(g, c), ORDER[c["a"]]))),
    ("같은 코인에 롱·숏이 같이 나오면 그 코인은 안 탐", lambda g: min([c for c in g if not clash(g, c)] or [None],
                                                              key=lambda c: ORDER[c["a"]] if c else 0)),
    ("덜 추격한 자리 먼저 (7일 범위에서 싼 쪽)", lambda g: min(g, key=lambda c: (c["pos"] if c["pos"] is not None else 0.5, ORDER[c["a"]]))),
    ("거꾸로: 승률 낮은 순 (비교용)", lambda g: max(g, key=lambda c: ORDER[c["a"]])),
]
def replay(pick, log=None):
    free, eq, peak, mdd, n, w, L, F, streak, worst, held, held_res, clashes = 0, 1.0, 1.0, 0.0, 0, 0, 0, 0, 0, 0, 0, [0, 0, 0], 0
    for t0, g in moments.items():
        if t0 < free:
            held += len(g)
            for c in g:
                held_res["WLF".index(c["kind"])] += 1
            continue
        c = pick(g)
        if len(g) >= 2 and log is not None:
            log.append((t0, g, c))
        if c is None:
            clashes += 1; continue
        free = c["ex"]; eq *= 1 + MARGIN * c["r"]; peak = max(peak, eq); mdd = max(mdd, 1 - eq / peak)
        n += 1; w += c["kind"] == "W"; L += c["kind"] == "L"; F += c["kind"] == "F"
        streak = streak + 1 if c["r"] <= 0 else 0; worst = max(worst, streak)
    return n, w, L, F, eq, mdd, worst, held, held_res, clashes
lo = min(v[0][0] for v in bars.values()); hi = max(v[0][-1] for v in bars.values())
wd = len({kst(x).date() for x in range(lo, hi, 3600000) if kst(x).weekday() < 5})
print(f"후보 진입 {len(cands)}개 (15개 매매법, B는 추격 막기 적용, 평일만), 평일 {wd}일, 1포지션, 증거금 {MARGIN:.0%} 복리\n")
log = []
base = replay(RULES[0][1], log)
both = [x for x in log]
print(f"== 동시에 2개 이상 나온 순간 (포지션이 비어 있을 때): {len(both)}번 / 실제 진입 {base[0]}번 중 ==")
for t0, g, c in both[:40]:
    s = "  ".join(f"{'▶' if x is c else ' '}{x['a'].split('@')[0][:14]}@{x['tf']} {x['sym'][:4]} {'롱' if x['side'] > 0 else '숏'} {x['kind']}"
                  for x in sorted(g, key=lambda x: ORDER[x["a"]]))
    print(f"  {kst(t0).strftime('%m-%d %H:%M')} | {s}")
diff = sum(1 for t0, g, c in both if len({x['kind'] for x in g}) > 1)
print(f"  → 이 중 고르는 신호에 따라 결과(W 이김 / L −50% / F 빠른 손절)가 달라졌을 순간: {diff}번\n")
print("== 동시 신호 고르는 규칙별 결과 (같은 2주, 같은 진입 후보) ==")
for name, pick in RULES:
    n, w, L, F, eq, mdd, worst, held, hres, cl = replay(pick)
    extra = f" | 롱·숏 충돌로 쉼 {cl}번" if cl else ""
    print(f"{name:40s} 진입 {n:3d}번 {w}승 {L}패 빠른손절 {F} | 승률 {w/max(n,1):.0%} | 계좌 {eq:.2f}배 | 최대 낙폭 {mdd:.0%} | 최대 연속 손실 {worst}{extra}")
random.seed(7)
eqs = sorted(replay(lambda g: random.choice(g))[4] for _ in range(300))
print(f"{'무작위로 고르기 (300번 평균)':40s} 계좌 평균 {sum(eqs)/len(eqs):.2f}배, 10~90% 범위 {eqs[30]:.2f}~{eqs[270]:.2f}배")
n, w, L, F, eq, mdd, worst, held, hres, cl = base
print(f"\n== 들고 있는 동안 못 탄 신호 (지금 규칙) ==\n{held}개: 들어갔다면 {hres[0]}개 이김, {hres[1]}개 −50%, {hres[2]}개 빠른 손절")
per = collections.defaultdict(list)
for c in cands:
    per[c["a"]].append((c["ex"] - c["t0"]) / 60000)
print("\n== 매매법별 평균 보유 시간 (자리 차지) ==")
for a in A + Bg:
    v = per.get(a, [])
    if v:
        v.sort()
        print(f"  {a:22s} {len(v):3d}번  평균 {sum(v)/len(v)/60:5.1f}시간  가운데값 {v[len(v)//2]/60:5.1f}시간")
