"""Owners 10-27: the second rule changed to "30분봉 진입 슈퍼트렌드 14/3, 14/6 같은 상승 추세이고 스톡RSI 14/11/4/6을 사용하고
골든 크로스를 하는데 RSI26이 50 위에 있고 MOM도 0선 위에 있고 그리고 1시간봉 RSI26도 50 위에 있으면 롱 진입, 1시간봉은
슈퍼트렌드 사용 안 함, 숏은 반대". Two changes against the rule running since 10-26: the Stoch RSI's last number 5 -> 6 (read in
the same order as before: RSI 14, stochastic 11, %K 4, %D 6) and MOM(10) of the 30m closes above 0 (below 0 for a short;
TradingView's Momentum, default length 10). The friend bot as it runs (both rules, the friend's first, stop ATR(14, 30m) x 3,
net ROE ladder 10 -> 8 then every 5 %, its coins, leverage, margin 40 %, entry blocks, fees, one position), only the second
rule's signals changed. Not a selection: the owners chose the rule; this reads what it changes.
  OLD    14/11/4/5, no MOM (the rule live since 10-26)
  NEW    14/11/4/6 + MOM(10) (the owners' 10-27 rule)
  D6     14/11/4/6 only;  MOM  14/11/4/5 + MOM(10) only  (which change does what)
  ALT    the other reading of the four numbers (TradingView's legend order K 14 / D 11 / RSI 4 / stochastic 6) + MOM(10)
each with both rules ("both") and the second rule alone ("new"). Months 2021-10 .. 2024-09 and 2024-10 .. 2026-09 (each
from $50, the 70 % floor off) and the 20 days 2026-10-05 .. 10-25.
    python3 research/mixchop_st/rule1027.py  ->  research/mixchop_st/rule1027.json"""
import json, os, sys
sys.path[:0] = ["/home/user/crypto-bot-research/research/mixchop_st"]
import numpy as np
import grid as Gd
S, R, M = Gd.S, Gd.R, Gd.M
import ladder20 as L

LADDER = (10, 8, 5)
VARIANTS = {"OLD": (dict(rsi=14, stoch=11, k=4, d=5), 0), "NEW": (dict(rsi=14, stoch=11, k=4, d=6), 10),
            "D6": (dict(rsi=14, stoch=11, k=4, d=6), 0), "MOM": (dict(rsi=14, stoch=11, k=4, d=5), 10),
            "ALT": (dict(rsi=4, stoch=6, k=14, d=11), 10)}


def signals(co, a30, a1h, p, mom_len, lo, hi):
    sig = S.new_signals(co, a30, a1h, p, lo, hi)
    if not mom_len:
        return sig
    ce = a30[:, 0].astype(np.int64) + M.MIN30
    m = M.mom(a30[:, 4], mom_len)
    keep = {}
    for t, e in sig.items():
        i = int(np.searchsorted(ce, t))
        if np.isfinite(m[i]) and m[i] * e["side"] > 0:
            e = dict(e)
            e["mom"] = round(float(m[i]), 6)
            keep[t] = e
    return keep


cfg = M.load_config(R.CONFIG); coins = list(cfg.coins)
a30 = {c.symbol: R.read_klines(R.DATA, c.symbol, "30m") for c in coins}
a1h = {c.symbol: R.read_klines(R.DATA, c.symbol, "1h") for c in coins}
mos = [m for m in R.months() if "2021-10" <= m <= "2026-09"]
m1 = {c.symbol: S.read_1m(R.DATA, c.symbol, mos) for c in coins}
friend, _ = S.friend_decisions(coins, a30, a1h, os.path.join(R.DATA, "npy", "friend_decisions_v2.pkl"))
lo, hi = R.T0 - 2 * 86_400_000, R.T1 + 30 * 86_400_000
D20 = os.path.join(R.SCRATCH, "mixchop20d_data")
b30 = {c.symbol: L.read(D20, c.symbol, "30m") for c in coins}; b1h = {c.symbol: L.read(D20, c.symbol, "1h") for c in coins}
b1m = {c.symbol: L.read(D20, c.symbol, "1m") for c in coins}
keep = R.T0, R.T1; R.T0, R.T1 = L.T0, L.T1
friend20 = {}
for c in coins:
    d, _ = R.decisions(c, b30[c.symbol], b1h[c.symbol], sample=10)
    for e in d.values(): e["rule"] = "friend"
    friend20[c.symbol] = d
R.T0, R.T1 = keep
out = {}
for vn, (p, ml) in VARIANTS.items():
    new = {c.symbol: signals(c, a30[c.symbol], a1h[c.symbol], p, ml, lo, hi) for c in coins}
    new20 = {c.symbol: signals(c, b30[c.symbol], b1h[c.symbol], p, ml, L.T0 - 86_400_000, L.T1) for c in coins}
    n_sig = sum(len(v) for v in new.values())
    for rules in ("both", "new"):
        name = f"{vn}|{rules}"
        spec = [(name, rules, 3.0, 3.0, LADDER, None)]
        S.G.update(coins=coins, bars30=a30, m1=m1); Gd.plan(coins, new, friend, spec)
        five = Gd.run_names([name], S.month_bounds(), 3)
        S.G.update(bars30=b30, m1=b1m); Gd.plan(coins, new20, friend20, spec)
        d20 = Gd.run_names([name], [(L.T0, L.T1)], 3)
        st = Gd.split_stats(five[name]); s20 = S.summarize(d20[name]); s20.pop("by_month", None)
        out[name] = {"five": st, "d20": s20, "new_signals_5y": n_sig,
                     "new_signals_20d": sum(len(v) for v in new20.values())}
        print(Gd.line(name, st, s20), "| 새 매매법 신호 5년", n_sig, "20일", out[name]["new_signals_20d"], flush=True)
json.dump(out, open("/home/user/crypto-bot-research/research/mixchop_st/rule1027.json", "w"), ensure_ascii=False, indent=1)
