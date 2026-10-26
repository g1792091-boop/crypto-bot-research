"""Fixed ladder 12/10/5 with the best stop (ATR x3): the combined bot and coin-flip controls (grid.py machinery)."""
import json, os, sys
sys.path[:0] = ["/home/user/crypto-bot-research/research/mixchop_st"]
import grid as Gd
S, R, M = Gd.S, Gd.R, Gd.M
import ladder20 as L
cfg = M.load_config(R.CONFIG); coins = list(cfg.coins)
a30 = {c.symbol: R.read_klines(R.DATA, c.symbol, "30m") for c in coins}
a1h = {c.symbol: R.read_klines(R.DATA, c.symbol, "1h") for c in coins}
mos = [m for m in R.months() if "2021-10" <= m <= "2026-09"]
m1 = {c.symbol: S.read_1m(R.DATA, c.symbol, mos) for c in coins}
friend, _ = S.friend_decisions(coins, a30, a1h, os.path.join(R.DATA, "npy", "friend_decisions_v2.pkl"))
lo, hi = R.T0 - 2 * 86_400_000, R.T1 + 30 * 86_400_000
new = {c.symbol: S.new_signals(c, a30[c.symbol], a1h[c.symbol], S.MAIN, lo, hi) for c in coins}
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
new20 = {c.symbol: S.new_signals(c, b30[c.symbol], b1h[c.symbol], S.MAIN, L.T0 - 86_400_000, L.T1) for c in coins}
lad = (12, 10, 5)
specs = [("B 12-10-5 x3", "new", 3.0, "own", lad, None)] + [(f"flip{s} 12-10-5 x3", "new", 3.0, "own", lad, s) for s in (1, 2, 3)] + [
    ("A 지금(친구손절)", "friend", 3.0, "own", lad, None), ("A 12-10-5 x3", "friend", 3.0, 3.0, lad, None),
    ("C 친구손절+새 x3", "both", 3.0, "own", lad, None), ("C 둘 다 x3", "both", 3.0, 3.0, lad, None)]
S.G.update(coins=coins, bars30=a30, m1=m1); Gd.plan(coins, new, friend, specs)
five = Gd.run_names([n for n, *_ in specs], S.month_bounds(), 2)
S.G.update(bars30=b30, m1=b1m); Gd.plan(coins, new20, friend20, specs)
d20 = Gd.run_names([n for n, *_ in specs], [(L.T0, L.T1)], 2)
out = {}
for n in five:
    st = Gd.split_stats(five[n]); s20 = S.summarize(d20[n]); s20.pop("by_month", None)
    out[n] = {"five": st, "d20": s20}
    print(Gd.line(n, st, s20), flush=True)
json.dump(out, open("/home/user/crypto-bot-research/research/mixchop_st/fixed12.json", "w"), ensure_ascii=False, indent=1)
