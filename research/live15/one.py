# 규칙봇 15: one strategy account's record under the new rule (net -50% stop; win = reaches net +11%, the first lock).
# Read-only on paper3.db: the rule bot's own default-number account, every real entry of the last weeks.
#   python3 research/live15/one.py N08_ICHI_WR@1h [N08_ICHI_WR@30m ...]      (P=/path/to/paper3.db for another copy)
#   --nochase: only the entries the chase block lets through (the B group's rule: none in the top 20% of the 7-day
#   range or the top 10% of the 24h range, shorts mirrored; an entry that cannot be judged is not taken either)
import sqlite3, json, os, sys, collections, bisect
P = os.environ.get("P", "/var/lib/paperbot/paper3.db")
NOCHASE = "--nochase" in sys.argv
WANT = [a for a in sys.argv[1:] if not a.startswith("--")] or ["N08_ICHI_WR@1h", "N08_ICHI_WR@30m"]
pc = sqlite3.connect(f"file:{P}?mode=ro", uri=True)
bars = collections.defaultdict(lambda: ([], [], []))
for ts, sym, h, l in pc.execute("SELECT ts, symbol, high, low FROM live_bars ORDER BY ts"):
    b = bars[sym]; b[0].append(ts); b[1].append(h); b[2].append(l)
hr = {}
for sym, (t, h, l) in bars.items():
    d = {}
    for i in range(len(t)):
        k = t[i] // 3600000; x = d.get(k)
        d[k] = (max(x[0], h[i]), min(x[1], l[i])) if x else (h[i], l[i])
    hr[sym] = d
def rng(sym, k, n):
    v = [hr[sym][j] for j in range(k - n, k) if j in hr[sym]]
    return (max(a for a, _ in v), min(b for _, b in v), len(v)) if v else None
def judge(t):
    sym, side, px, t0 = t["symbol"], t["side"], t["entry_price"], t["entry_time"]
    b = bars.get(sym)
    if not b or not b[0] or t0 < b[0][0]:
        return None
    lev = 40 if sym.startswith("BTC") else 30; rt = 0.0015
    stop = px * (1 - side * (0.5 / lev - rt)); tgt = px * (1 + side * (0.11 / lev + rt))
    k = t0 // 3600000; chase = None
    r24, r7 = rng(sym, k, 24), rng(sym, k, 168)
    if r24 and r24[2] >= 20:
        p24 = (px - r24[1]) / max(r24[0] - r24[1], 1e-12)
        chase = (side > 0 and p24 >= 0.9) or (side < 0 and p24 <= 0.1)
        if r7 and r7[2] >= 150:
            p7 = (px - r7[1]) / max(r7[0] - r7[1], 1e-12)
            chase = chase or (side > 0 and p7 >= 0.8) or (side < 0 and p7 <= 0.2)
    mae = 0.0
    for i in range(bisect.bisect_left(b[0], t0 // 60000 * 60000), len(b[0])):
        bad, good = (b[2][i], b[1][i]) if side > 0 else (b[1][i], b[2][i])
        mae = min(mae, lev * side * (bad / px - 1))
        if side * (bad - stop) <= 0:
            return "L", mae, chase
        if side * (good - tgt) >= 0:
            return "W", mae, chase
    return "O", mae, chase
print("새 규칙(손절 순ROE -50%, 순ROE +11% 닿으면 이김)으로 다시 본 규칙봇 기본값 계정의 실제 진입"
      + (" · 추격 막기를 통과한 진입만" if NOCHASE else "") + "\n")
for a in WANT:
    ts = [json.loads(d) for (d,) in pc.execute("SELECT data FROM trades WHERE account_id = ? ORDER BY entry_time", (a,))]
    r = [x for x in (judge(t) for t in ts) if x]
    if NOCHASE:
        r = [x for x in r if x[2] is False]
    w = sum(s == "W" for s, _, _ in r); l = sum(s == "L" for s, _, _ in r); o = sum(s == "O" for s, _, _ in r)
    c = [ch for _, _, ch in r if ch is not None]
    deep = sum(s == "W" and m <= -0.25 for s, m, _ in r)
    if not r:
        print(f"{a:22s} 진입 기록 없음 (계정 이름을 확인하세요, 예: N08_ICHI_WR@1h)")
        continue
    line = f"{a:22s} {w}승 {l}패" + (f" 진행 {o}" if o else "")
    line += f" | 승률 {w / max(w + l, 1):.0%} | 대략 손익 {w * 10 - l * 50:+d}%"
    line += f" | 추격 진입 {sum(c) / len(c):.0%}" if c else " | 추격 진입 -"
    print(line + f" | -25% 넘게 밀렸다가 이김 {deep}번")
