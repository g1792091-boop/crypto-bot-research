# 규칙봇 15: everything worth checking on the rule bot's last weeks before the live start, in one run (owners 10-20:
# "실거래봇 돌리기 전에 싹 확인"). Read-only on paper3.db: the 15 strategies' real entries, weekdays only, B with the chase
# block, replayed one position at a time with the live rules (each exchange's net stop, the new ladder, the own-reverse
# fast stop before the first lock, 40% margin) and each exchange's measured costs.
#   python3 research/live15/precheck.py      (P=/path/to/paper3.db to read another copy)
# 1. Limit entry: each strategy on its own, then the whole bot (a limit counts as filled only when price trades 0.02%
#    through it; while it waits it holds the one position slot; the strategy's reverse signal cancels it)
# 2. Other whole-bot variants: the chase block on all 15, the fast stop off
# 3. The current rule's record by strategy, coin, side and time of day; hold time and funding times crossed
# Every whole-bot line also shows the first and the second half of the period: a change worth making wins in both.
import sqlite3, json, os, collections, bisect, statistics, datetime as D
P = os.environ.get("P", "/var/lib/paperbot/paper3.db")
A = ["V39_ALL@1h", "S3_CMO_SANDWICH@30m", "N20_EMA9_CHOP@30m", "N05_PSAR_POC@30m", "S3_CMO_SANDWICH@1h", "N06_MACD_ORB@30m",
     "OBV_S@30m", "F9_IFVG@1h", "S6_EMA_DMI_ADX@1h", "F15_ORB@30m", "N08_ICHI_WR@30m"]
Bg = ["F3_BOS@30m", "F7_RF_ONLY@1h", "F9_FVG@1h", "N12_ICHI_AO@30m"]
ORDER = {a: i for i, a in enumerate(A + Bg)}
MARGIN = 0.4
# measured on the accounts (10-20) and the exchanges' API fee pages: Bybit maker 0.02%, MEXC API maker 0.06%
EX = {"바이비트": dict(stop=0.50, taker=0.00044, maker=0.0002, slip=0.0002),
      "MEXC": dict(stop=0.35, taker=0.0008, maker=0.0006, slip=0.0002)}
THROUGH = 0.0002
LIMITS = [(0.001, 30), (0.002, 30), (0.003, 60)]
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
kst = lambda ms: D.datetime.fromtimestamp(ms / 1000, D.timezone(D.timedelta(hours=9)))
lev_of = lambda sym: 40 if sym.startswith("BTC") else 30
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
def next_opp(acct, sym, side, t_sig):
    ops = opp.get((acct, sym, -side), [])
    j = bisect.bisect_right(ops, t_sig)
    return ops[j] if j < len(ops) else None
def fill(sym, side, limit, t0, wait, through):
    # the first minute within `wait` minutes whose low (long) / high (short) goes `through` past the limit
    t, o, h, l = bars[sym]
    for i in range(bisect.bisect_left(t, t0), len(t)):
        if t[i] >= t0 + wait * 60000:
            return None
        if (side > 0 and l[i] < limit * (1 - through)) or (side < 0 and h[i] > limit * (1 + through)):
            return t[i]
    return None
def enter(acct, sym, side, px, t0, mode, c):
    # (fill price, fill minute, round-trip cost) or (None, the minute the slot is free again, None)
    if mode is None:
        return px, t0, 2 * (c["taker"] + c["slip"])
    k, wait, through = mode
    lim = px * (1 - side * k); ft = fill(sym, side, lim, t0, wait, through); nxt = next_opp(acct, sym, side, t0)
    if ft is None or (nxt is not None and nxt <= ft):
        return None, min(t0 + wait * 60000, nxt or t0 + wait * 60000), None
    return lim, ft, c["maker"] + c["taker"] + c["slip"]
def run(acct, sym, side, px, t_sig, t_in, stop_roe, rt, fast=True, limit=False):
    # net stop, ladder 11->10, 15->12, then +5% steps (reached - 3%), own reverse signal before the first lock;
    # a limit fill's own minute counts only against it (its high/low may have come before the fill)
    t, o, h, l = bars[sym]; lev = lev_of(sym)
    roe = lambda p: lev * (side * (p / px - 1) - rt)
    stop = px * (1 - side * (stop_roe / lev - rt)); best = -1.0; lock = None
    nxt = next_opp(acct, sym, side, t_sig) if fast else None
    i0 = bisect.bisect_left(t, t_in)
    for i in range(i0, len(t)):
        if lock is None and nxt is not None and t[i] > t_sig and t[i] >= nxt:
            return roe(o[i]), "F", t[i]
        bad, good = (l[i], h[i]) if side > 0 else (h[i], l[i])
        if side * (bad - stop) <= 0:
            return (lock, "W", t[i] + 60000) if lock is not None else (roe(stop), "L", t[i] + 60000)
        if limit and i == i0:
            continue
        best = max(best, roe(good))
        lk = 0.12 + 0.05 * int((best - 0.15) / 0.05 + 1e-9) if best >= 0.15 else (0.10 if best >= 0.11 else None)
        if lk is not None and (lock is None or lk > lock):
            lock = lk; stop = px * (1 + side * (lk / lev + rt))
    return None, None, None
raw = []
for a, d in pc.execute("SELECT account_id, data FROM trades ORDER BY entry_time"):
    if a not in ORDER:
        continue
    t = json.loads(d); sym = t["symbol"]
    if sym not in bars or not bars[sym][0] or t["entry_time"] < bars[sym][0][0] or kst(t["entry_time"]).weekday() >= 5:
        continue
    raw.append((t["entry_time"] // 60000 * 60000, ORDER[a], a, sym, t["side"], t["entry_price"],
                chase(sym, t["side"], t["entry_price"], t["entry_time"])))
raw.sort()
if not raw:
    raise SystemExit("15개 매매법의 평일 진입 기록이 없습니다 (P 경로를 확인하세요)")
lo = min(v[0][0] for v in bars.values() if v[0]); hi = max(v[0][-1] for v in bars.values() if v[0]); mid = (lo + hi) // 2
wd = len({kst(x).date() for x in range(lo, hi, 3600000) if kst(x).weekday() < 5})
def replay(ex, mode=None, chase_all=False, fast=True):
    c = EX[ex]; free = 0; taken = []; still = 0
    for t0, _, a, sym, side, px, ch in raw:
        if t0 < free or ((a in Bg or chase_all) and ch is not False):
            continue
        p_in, t_in, rt = enter(a, sym, side, px, t0, mode, c)
        if p_in is None:
            free = t_in
            continue
        r, kind, t_out = run(a, sym, side, p_in, t0, t_in, c["stop"], rt, fast, mode is not None)
        if r is None:
            still += 1; free = float("inf")
            continue
        free = t_out; taken.append(dict(t0=t0, a=a, sym=sym, side=side, r=r, kind=kind, t_in=t_in, t_out=t_out))
    return taken, still
def stats(tk):
    eq = peak = 1.0; mdd = 0.0; s = ws = 0; e1 = e2 = 1.0
    for x in tk:
        eq *= 1 + MARGIN * x["r"]; peak = max(peak, eq); mdd = max(mdd, 1 - eq / peak)
        s = s + 1 if x["r"] <= 0 else 0; ws = max(ws, s)
        if x["t0"] < mid:
            e1 *= 1 + MARGIN * x["r"]
        else:
            e2 *= 1 + MARGIN * x["r"]
    return eq, mdd, ws, e1, e2
def line(name, tk, still):
    n = len(tk); w = sum(x["r"] > 0 for x in tk); L = sum(x["kind"] == "L" for x in tk)
    eq, mdd, ws, e1, e2 = stats(tk)
    return (f"  {name:30s} 진입 {n:3d}번 {w}승 {n - w}패(손절 {L}) {w / max(n, 1):4.0%} | 계좌 ×{eq:.2f} · 최대 낙폭 {mdd:3.0%}"
            f" · 연속 손실 {ws} | 앞 절반 ×{e1:.2f} · 뒤 절반 ×{e2:.2f}" + (f" · 끝에 열림 {still}" if still else ""))
print(f"15개 매매법 평일 진입 후보 {len(raw)}개 (B는 추격 막기 전), 평일 {wd}일, 1포지션, 증거금 {MARGIN:.0%} 복리, "
      f"앞·뒤 절반 경계 {kst(mid):%m-%d %H:%M}")
print("비용(편도): 바이비트 테이커 0.044% · 메이커 0.02%, MEXC 테이커 0.08% · 메이커 0.06%(API), 시장가 체결은 슬리피지 0.02% 더")
print("미국 지표·나스닥 개장 쉬는 시간은 넣지 않았습니다(두 경우 모두 같음).\n")

print("== 1. 지정가 진입: 매매법마다 따로 (그 매매법 계정의 진입 전부, 단순 판정: 순ROE +11% 먼저면 이김, 손절 먼저면 짐) ==")
print("   바이비트 비용·-50% 손절. 칸 = 승-패 대략손익(이김 +10, 짐 -50). 지정가 칸의 '놓침'은 안 닿아서 못 들어간 거래가")
print("   원래 이겼는지(이) 졌는지(짐). 지정가는 진입가보다 k% 유리하게, 0.02% 더 뚫려야 체결\n")
def simple(sym, side, px, t_in, rt, stop_roe, limit=False):
    t, o, h, l = bars[sym]; lev = lev_of(sym)
    stop = px * (1 - side * (stop_roe / lev - rt)); tgt = px * (1 + side * (0.11 / lev + rt))
    i0 = bisect.bisect_left(t, t_in)
    for i in range(i0, len(t)):
        bad, good = (l[i], h[i]) if side > 0 else (h[i], l[i])
        if side * (bad - stop) <= 0:
            return "L"
        if side * (good - tgt) >= 0 and not (limit and i == i0):
            return "W"
    return "O"
cb = EX["바이비트"]
heads = ["지금(시장가)"] + [f"{k * 100:.1f}%·{w}분" for k, w in LIMITS]
print(f"  {'매매법':22s} " + " | ".join(f"{h:24s}" for h in heads))
for a in A + Bg:
    es = [x for x in raw if x[2] == a and (a not in Bg or x[6] is False)]
    if not es:
        print(f"  {a:22s} 진입 없음")
        continue
    base = [simple(sym, side, px, t0, 2 * (cb["taker"] + cb["slip"]), cb["stop"]) for t0, _, _, sym, side, px, _ in es]
    cells = []
    w, l = base.count("W"), base.count("L")
    cells.append(f"{w}-{l} {w * 10 - l * 50:+d}")
    for k, wait in LIMITS:
        w = l = mw = ml = 0
        for (t0, _, _, sym, side, px, _), b0 in zip(es, base):
            p_in, t_in, rt = enter(a, sym, side, px, t0, (k, wait, THROUGH), cb)
            if p_in is None:
                mw += b0 == "W"; ml += b0 == "L"
                continue
            res = simple(sym, side, p_in, t_in, rt, cb["stop"], True)
            w += res == "W"; l += res == "L"
        cells.append(f"{w}-{l} {w * 10 - l * 50:+d} 놓침 이{mw}·짐{ml}")
    print(f"  {a:22s} " + " | ".join(f"{c:24s}" for c in cells))

base_tk = {}
for ex in EX:
    print(f"\n== 2. 봇 전체: {ex} (손절 순ROE -{EX[ex]['stop'] * 100:.0f}%) ==")
    tk, st = replay(ex); base_tk[ex] = tk
    print(line("지금 규칙 (시장가)", tk, st))
    for k, wait in LIMITS:
        print(line(f"지정가 {k * 100:.1f}% 유리 · {wait}분 대기", *replay(ex, (k, wait, THROUGH))))
    print(line("지정가 0.2%·30분 (닿기만 해도 체결)", *replay(ex, (0.002, 30, 0.0))))
    print(line("추격 막기를 15개 전부에", *replay(ex, chase_all=True)))
    print(line("빠른 청산(반대 신호) 없음", *replay(ex, fast=False)))

tk = base_tk["바이비트"]
print("\n== 3. 지금 규칙의 거래 나눠 보기 (바이비트 -50%, 시장가) ==")
def grp(key, label, order=None):
    g = collections.defaultdict(list)
    for x in tk:
        g[key(x)].append(x["r"])
    ks = order or sorted(g)
    out = []
    for k in ks:
        if k in g:
            v = g[k]; w = sum(r > 0 for r in v)
            out.append(f"{k} {w}-{len(v) - w} ({sum(v) * 100:+.0f}%)")
    print(f"  {label}: " + " · ".join(out))
print("  매매법별 (봇이 실제로 탄 거래, 승-패, 순ROE 합):")
g = collections.defaultdict(list)
for x in tk:
    g[x["a"]].append(x)
for a in A + Bg:
    v = g.get(a, [])
    if v:
        w = sum(x["r"] > 0 for x in v); F = sum(x["kind"] == "F" for x in v)
        print(f"    {a:22s} {w}-{len(v) - w}" + (f" (빠른 청산 {F})" if F else "") + f" 순ROE 합 {sum(x['r'] for x in v) * 100:+.0f}%")
    else:
        print(f"    {a:22s} 탄 거래 없음")
grp(lambda x: x["sym"].replace("USDT", ""), "코인별")
grp(lambda x: "롱" if x["side"] > 0 else "숏", "방향별", ["롱", "숏"])
band = lambda h: "09-15시" if 9 <= h < 15 else "15-21시" if 15 <= h < 21 else "21-03시" if h >= 21 or h < 3 else "03-09시"
grp(lambda x: band(kst(x["t0"]).hour), "진입 시각(한국)별", ["09-15시", "15-21시", "21-03시", "03-09시"])
if tk:
    hold = sorted((x["t_out"] - x["t_in"]) / 3600000 for x in tk)
    print(f"  보유 시간: 가운데 {statistics.median(hold):.1f}시간 · 10번 중 9번은 {hold[int(0.9 * (len(hold) - 1))]:.1f}시간 안 · "
          f"가장 길게 {hold[-1]:.1f}시간")
    fund = [sum(1 for f in range(x["t_in"] // 28800000 + 1, x["t_out"] // 28800000 + 1)) for x in tk]
    print(f"  펀딩 시각(한국 01·09·17시)을 넘긴 거래 {sum(f > 0 for f in fund)}번 / {len(tk)}번, 합계 {sum(fund)}번. "
          f"펀딩 0.01%면 한 번에 30배 순ROE 약 0.3%p(보통 롱이 내고 숏이 받음)")
print("\n읽는 법: 바꿀 만한 것은 두 거래소 모두, 앞·뒤 절반 모두에서 '지금 규칙'보다 나은 것뿐입니다. 한두 거래 차이는 운입니다.")
print("이 기간은 15개를 고른 바로 그 기간이라 모든 숫자가 낙관적입니다. 여러 가지를 같이 볼수록 우연히 좋아 보이는 것이 하나쯤 나옵니다.")
