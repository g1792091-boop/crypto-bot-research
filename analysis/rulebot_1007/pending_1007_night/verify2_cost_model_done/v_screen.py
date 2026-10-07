"""Rebuild a market bundle from real 15m Binance bars (last bar of the 5y set) and estimate tokens with an
independent heuristic tokenizer; also re-measure the analyst's screens with the same heuristic.
python3 -I v_screen.py <sig15_dir> <analyst_outscreens_dir> <out_dir>
Heuristic (no tokenizer offline): digit runs -> ceil(len/3) tokens; ASCII letter runs -> 1 token per <=6 chars;
each ASCII punctuation/symbol -> 1; each newline -> 1; space runs -> 0 (merged) except runs >1 -> 1;
Hangul syllables -> factor per char (low 0.7 / mid 1.0 / high 1.3); other non-ASCII symbols (·, ※, →) -> 1.5.
ASCII part scaled 0.85 / 1.0 / 1.2 for low / mid / high."""
import sys, os, re, json, math
sys.path.insert(0, "/root/.local/lib/python3.11/site-packages")
import numpy as np
SIG, AN, OUT = sys.argv[1:4]
def tok(s):
    a = h = o = 0.0
    for m in re.finditer(r"\d+|[A-Za-z]+|[가-힣]|\n| {2,}| |[\x21-\x2f\x3a-\x40\x5b-\x60\x7b-\x7e]|.", s, re.S):
        g = m.group()
        if g[0].isdigit(): a += math.ceil(len(g) / 3)
        elif g[0].isascii() and g[0].isalpha(): a += math.ceil(len(g) / 6)
        elif "가" <= g[0] <= "힣": h += 1
        elif g == "\n": a += 1
        elif g.startswith("  "): a += 1
        elif g == " ": pass
        elif g[0].isascii(): a += 1
        else: o += 1.5
    return {"low": round(0.85 * a + 0.7 * h + o), "mid": round(a + h + o), "high": round(1.2 * a + 1.3 * h + o), "chars": len(s)}
# ---- real-data market bundle
def ema(x, n):
    a = 2 / (n + 1); out = np.empty_like(x); out[0] = x[0]
    for i in range(1, len(x)): out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out
def rma(x, n):
    out = np.empty_like(x); out[:n] = np.nan; out[n - 1] = x[:n].mean()
    for i in range(n, len(x)): out[i] = (out[i - 1] * (n - 1) + x[i]) / n
    return out
def agg(ts, o, h, l, c, v, mins):
    k = (ts // (mins * 60 * 10**9)); u, idx = np.unique(k, return_index=True)
    ends = np.r_[idx[1:], len(k)]
    return (np.array([o[i] for i in idx]), np.maximum.reduceat(h, idx), np.minimum.reduceat(l, idx), np.array([c[j - 1] for j in ends]), np.add.reduceat(v, idx))
def ind(o, h, l, c, v):
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc))); atr = rma(tr, 14)
    d = np.diff(c, prepend=c[0]); rs = rma(np.maximum(d, 0), 14) / np.maximum(rma(np.maximum(-d, 0), 14), 1e-12); rsi = 100 - 100 / (1 + rs)
    up = np.r_[0, np.diff(h)]; dn = np.r_[0, -np.diff(l)]; pdm = np.where((up > dn) & (up > 0), up, 0); mdm = np.where((dn > up) & (dn > 0), dn, 0)
    pdi = 100 * rma(pdm, 14) / atr; mdi = 100 * rma(mdm, 14) / atr; dx = 100 * abs(pdi - mdi) / np.maximum(pdi + mdi, 1e-12); adx = rma(np.nan_to_num(dx), 14)
    e20, e50 = ema(c, 20), ema(c, 50)
    return atr, rsi, adx, pdi, mdi, e20, e50
def fmt(p): return f"{p:,.2f}" if p < 1000 else f"{p:,.1f}"
lines = []
NAMES = {"15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}
t_last = None
for coin in ["BTCUSD", "ETHUSD", "SOLUSD", "BCHUSD", "LTCUSD", "DOGEUSD"]:
    z = np.load(os.path.join(SIG, f"sig_15m_{coin}.npz")); n = 96 * 400
    ts, o, h, l, c, v = (z[k][-n:] for k in ("ts", "o", "h", "l", "c", "v")); t_last = ts[-1]
    lines.append(f"{coin[:-3]} {fmt(c[-1])}")
    for tf, mins in (("15m", 15), ("30m", 30), ("1h", 60), ("4h", 240)):
        O, H, L, Cc, V = agg(ts, o, h, l, c, v, mins)
        atr, rsi, adx, pdi, mdi, e20, e50 = ind(O, H, L, Cc, V)
        chg = 100 * (Cc[-8:] / np.r_[Cc[-9], Cc[-8:-1]] - 1); rng = (H[-8:] - L[-8:]) / atr[-8:]; vr = V[-8:] / V[-28:-8].mean()
        hh, ll = H[-50:].max(), L[-50:].min(); box = (Cc[-1] - ll) / (hh - ll)
        # volume profile over last 100 bars, 40 bins
        lo_, hi_ = L[-100:].min(), H[-100:].max(); bins = np.linspace(lo_, hi_, 41); mid = (Cc[-100:] + H[-100:] + L[-100:]) / 3
        hist = np.histogram(mid, bins, weights=V[-100:])[0]; poc = (bins[hist.argmax()] + bins[hist.argmax() + 1]) / 2
        va = np.argsort(hist)[::-1]; cum = np.cumsum(hist[va]) / hist.sum(); sel = va[: np.searchsorted(cum, 0.7) + 1]
        lines.append(f" {NAMES[tf]}: 변화% " + " ".join(f"{x:+.2f}" for x in chg) + " | 폭/ATR " + " ".join(f"{x:.1f}" for x in rng) + " | 거래량배 " + " ".join(f"{x:.1f}" for x in vr))
        lines.append(f"  ATR {100*atr[-1]/Cc[-1]:.2f}% · EMA20 {(Cc[-1]-e20[-1])/atr[-1]:+.1f}ATR · EMA50 {(Cc[-1]-e50[-1])/atr[-1]:+.1f}ATR · RSI {rsi[-1]:.0f} · ADX {adx[-1]:.0f} (+DI {pdi[-1]:.0f} / -DI {mdi[-1]:.0f}) · 장 {'추세' if adx[-1] > 25 else '박스'} · 박스 위치 {box:.2f} · 매물대 위 {fmt(bins[sel.max()+1])} / 아래 {fmt(bins[sel.min()])} / 최다 {fmt(poc)}")
    O, H, L, Cc, V = agg(ts, o, h, l, c, v, 1440)
    atr = rma(np.maximum(H - L, np.maximum(abs(H - np.r_[Cc[0], Cc[:-1]]), abs(L - np.r_[Cc[0], Cc[:-1]]))), 14)
    e50, e200 = ema(Cc, 50), ema(Cc, 200)
    lines.append(f" 일봉: 20일 흐름 {100*(Cc[-1]/Cc[-21]-1):+.1f}% · 종가 vs EMA50 {100*(Cc[-1]/e50[-1]-1):+.1f}% / EMA200 {100*(Cc[-1]/e200[-1]-1):+.1f}% · 일ATR {100*atr[-1]/Cc[-1]:.1f}% · 전일 고 {fmt(H[-2])} 저 {fmt(L[-2])} · 주 시가 {fmt(O[-7])} · 지난주 고 {fmt(H[-14:-7].max())} 저 {fmt(L[-14:-7].min())} · 오늘 폭/14일 {(H[-1]-L[-1])/atr[-1]:.1f} · 전일고까지 {(H[-2]-Cc[-1])/atr[-1]:+.1f}ATR · 지난주저까지 {(L[-14:-7].min()-Cc[-1])/atr[-1]:+.1f}ATR")
    lines.append(" 시장: 펀딩 +0.0100% (정산 3시간 05분 뒤) · 미결제 24h -2.3% · 롱숏 1.31 · 강제청산 1h 롱 $0.8M / 숏 $2.1M ※5년 시험: 단독 예측력 없음")
    lines.append(" 분석가: 기울기 중립 · 장 박스 · 변동성 낮음 · 확신 1 · 유효 2시간 · 그 뒤 변화 +0.21% / 0.3ATR")
lines.append("일정: 미국 CPI 2일 4시간 뒤 · FOMC 의사록 6일 뒤 · 충격 표시 없음")
lines.append("분석가 글: BTC·ETH 박스 하단 근처에서 거래량 줄어듦. 알트는 BTC보다 약함. 큰 일정 전까지 변동성 낮음 예상.")
market = "\n".join(lines)
# journal: 20 lines per design 6-4 (reuse the analyst's 10-line format, doubled)
an = open(os.path.join(AN, "S1_entry_S2_ST_ROC_15m_ko.txt")).read()
def part(txt, a, b):
    i = txt.index(a); j = txt.index(b, i + 1) if b else len(txt); return txt[i:j]
instr = part(an, "[공통 지시문", "[시장 묶음")
card = part(an, "[매매법 카드", "[최근 판단")
jr = part(an, "[최근 판단", "[이번 깨움")
jl = jr.strip().split("\n"); journal20 = "\n".join([jl[0].replace("10개", "20개")] + jl[1:] + jl[1:])
wake = part(an, "[이번 깨움", None)
amk = part(an, "[시장 묶음", "[매매법 카드")
res = {"method": __doc__.split("Heuristic")[1].strip(), "bar_time_utc": str(np.datetime64(int(t_last), "ns")),
       "mine": {"instructions(analyst text)": tok(instr), "market(real bars, rebuilt)": tok(market), "card(analyst text)": tok(card),
                "journal 20 lines (design 6-4)": tok(journal20), "wake 2 signals (analyst text)": tok(wake)},
       "analyst_text_my_heuristic": {"instructions": tok(instr), "market": tok(amk), "card": tok(card), "journal10": tok(jr), "wake": tok(wake)}}
for k in ("mine", "analyst_text_my_heuristic"):
    tot = {q: sum(v[q] for v in res[k].values()) for q in ("low", "mid", "high", "chars")}; res[k]["TOTAL"] = tot
open(os.path.join(OUT, "screen_market_rebuilt_ko.txt"), "w").write(market)
for f in sorted(os.listdir(AN)):
    if f.endswith(".txt"): res.setdefault("analyst_full_files_my_heuristic", {})[f] = tok(open(os.path.join(AN, f)).read())
json.dump(res, open(os.path.join(OUT, "screen_tokens.json"), "w"), indent=1, ensure_ascii=False)
print(json.dumps(res, ensure_ascii=False, indent=0)[:3500])
