# 규칙봇 15: what if a strategy's entries waited for a better price (a limit order) instead of entering at once?
# Read-only on paper3.db: the rule bot's own default-number account, every real entry of the last weeks, judged with
# the new rule (net -50% stop; win = net +11%, the first lock) on Binance 1m bars, Bybit's costs.
#   python3 research/live15/limit.py                       (V39_ALL@1h)
#   python3 research/live15/limit.py F9_IFVG@1h N05_PSAR_POC@30m    (P=/path/to/paper3.db for another copy)
# The limit sits k% better than the real entry price and waits W minutes; not touched in time = no trade (missed).
import sqlite3, json, os, sys, collections, bisect
P = os.environ.get("P", "/var/lib/paperbot/paper3.db")
WANT = [a for a in sys.argv[1:] if not a.startswith("--")] or ["V39_ALL@1h"]
OFFSETS = (0.0, 0.001, 0.002, 0.003, 0.005)          # 0 = today's market entry
WAITS = (30, 60)                                      # minutes the limit waits
TAKER, MAKER, SLIP = 0.00044, 0.0002, 0.0002          # Bybit, measured on the account (10-20); the maker rate is Bybit's
RT_MARKET = 2 * (TAKER + SLIP)                        # market in, market (stop) out
RT_LIMIT = MAKER + TAKER + SLIP                       # limit in (no slippage), market out
pc = sqlite3.connect(f"file:{P}?mode=ro", uri=True)
bars = collections.defaultdict(lambda: ([], [], []))
for ts, sym, h, l in pc.execute("SELECT ts, symbol, high, low FROM live_bars ORDER BY ts"):
    b = bars[sym]; b[0].append(ts); b[1].append(h); b[2].append(l)
def outcome(sym, side, px, t0, rt):
    # from minute t0 on: "L" at the net -50% stop, "W" at net +11%, "O" still open; and the worst net ROE on the way
    b = bars[sym]; lev = 40 if sym.startswith("BTC") else 30
    stop = px * (1 - side * (0.5 / lev - rt)); tgt = px * (1 + side * (0.11 / lev + rt)); mae = 0.0
    for i in range(bisect.bisect_left(b[0], t0), len(b[0])):
        bad, good = (b[2][i], b[1][i]) if side > 0 else (b[1][i], b[2][i])
        mae = min(mae, lev * (side * (bad / px - 1) - rt))
        if side * (bad - stop) <= 0:
            return "L", mae
        if side * (good - tgt) >= 0:
            return "W", mae
    return "O", mae
def filled(sym, side, limit, t0, wait):
    # the first minute (from the entry minute, within `wait` minutes) whose low (long) / high (short) reaches the limit
    b = bars[sym]
    for i in range(bisect.bisect_left(b[0], t0), len(b[0])):
        if b[0][i] >= t0 + wait * 60000:
            return None
        if side * (limit - (b[2][i] if side > 0 else b[1][i])) >= 0:
            return b[0][i]
    return None
print("새 규칙(순ROE -50% 손절, 순ROE +11% 이김)으로 본 실제 진입 · 바이비트 비용(시장가 테이커 0.044%, 지정가 메이커 0.02%)")
print("지정가 = 실제 진입가보다 k% 유리한 가격에 걸고 W분 기다림. 안 닿으면 그 거래는 없음(놓침).\n")
for a in WANT:
    ts = [json.loads(d) for (d,) in pc.execute("SELECT data FROM trades WHERE account_id = ? ORDER BY entry_time", (a,))]
    ts = [t for t in ts if t["symbol"] in bars and bars[t["symbol"]][0] and t["entry_time"] >= bars[t["symbol"]][0][0]]
    if not ts:
        print(f"{a}: 진입 기록 없음 (계정 이름을 확인하세요, 예: V39_ALL@1h)\n")
        continue
    base = {id(t): outcome(t["symbol"], t["side"], t["entry_price"], t["entry_time"] // 60000 * 60000, RT_MARKET) for t in ts}
    print(f"== {a} · 진입 {len(ts)}번 ==")
    for wait in WAITS:
        for k in OFFSETS:
            if k == 0 and wait != WAITS[0]:
                continue
            w = l = o = miss_w = miss_l = 0; maes = []
            for t in ts:
                side, px, t0 = t["side"], t["entry_price"], t["entry_time"] // 60000 * 60000
                if k == 0:
                    res, mae = base[id(t)]
                else:
                    limit = px * (1 - side * k)
                    ft = filled(t["symbol"], side, limit, t0, wait)
                    if ft is None:
                        miss_w += base[id(t)][0] == "W"; miss_l += base[id(t)][0] == "L"
                        continue
                    res, mae = outcome(t["symbol"], side, limit, ft, RT_LIMIT)
                w += res == "W"; l += res == "L"; o += res == "O"; maes.append(mae)
            name = "지금 (시장가 바로 진입)" if k == 0 else f"지정가 {k * 100:.1f}% 유리 · {wait}분 대기"
            miss = "" if k == 0 else f" | 놓침 {miss_w + miss_l}번(그중 원래 이김 {miss_w} · 원래 짐 {miss_l})"
            avg_mae = sum(maes) / len(maes) if maes else 0.0
            print(f"  {name:24s} 체결 {w + l + o:3d}번 {w}승 {l}패" + (f" 진행 {o}" if o else "")
                  + f" | 대략 손익 {w * 10 - l * 50:+d}%{miss} | 들어간 뒤 평균 최대 밀림 {avg_mae * 100:+.1f}%")
    print()
print("이 기간은 15개를 고른 바로 그 기간입니다. 지정가가 실제로 그 가격에 다 체결된다는 보장도 없습니다(줄 서 있는 순서).")
