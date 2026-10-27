"""Owners 10-27: "롱을 진입했는데 거래소 화면 12.4%에 닿고 10.4%까지 내려오면 7% 익절이고 그 위로 계단식 익절은 간격을 어떻게
하는게 좋을까?", then "화면 13.4%에 닿으면 손절선을 11.4%(순 8%) 자리로 하자 대신 그 위로 계단식 익절 간격 제일 좋은 간격으로
추천해줘". The friend bot as it runs (both rules, the friend's first, stop ATR(14, 30m) x 3 for both, its coins, leverage,
margin 40 %, entry blocks, fees, one position) with only the ladder changed (net ROE %: trigger -> lock, then +step a step,
each later lock 2 % under its trigger): the first rung fixed by the owners at 10 -> 8 (40x screen +13.4 % -> +11.4 %) with
the spacing 2 / 3 / 4 / 5 / 7 / 10, and 12-10-5 (the ladder until 10-27) for reference.
Selection (fixed before the results, as grid.py): among the 10 -> 8 arms, the highest median month of 2021-10 .. 2024-09
(each month from $50, the 70 % floor off; geometric mean on a tie); 2024-10 .. 2026-09 and the 20 days 2026-10-05 .. 10-25
only check it (reported, not used to choose).
    python3 research/mixchop_st/ladder9.py  ->  research/mixchop_st/ladder9.json"""
import json, os, sys
sys.path[:0] = ["/home/user/crypto-bot-research/research/mixchop_st"]
import grid as Gd
S, R, M = Gd.S, Gd.R, Gd.M
import ladder20 as L
LADDERS = [(12, 10, 5)] + [(10, 8, step) for step in (2, 3, 4, 5, 7, 10)]
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
specs = [(f"둘 다 x3 계단 {t}→{k} 간격 {s}", "both", 3.0, 3.0, (t, k, s), None) for t, k, s in LADDERS]
S.G.update(coins=coins, bars30=a30, m1=m1); Gd.plan(coins, new, friend, specs)
five = Gd.run_names([n for n, *_ in specs], S.month_bounds(), 3)
S.G.update(bars30=b30, m1=b1m); Gd.plan(coins, new20, friend20, specs)
d20 = Gd.run_names([n for n, *_ in specs], [(L.T0, L.T1)], 3)
out = {}
for n, *_ in specs:
    st = Gd.split_stats(five[n]); s20 = S.summarize(d20[n]); s20.pop("by_month", None)
    out[n] = {"five": st, "d20": s20}
    print(Gd.line(n, st, s20), flush=True)
cands = [n for n in out if "10→8" in n]
best = max(cands, key=lambda n: (out[n]["five"]["choose"]["median_x"], out[n]["five"]["choose"]["geo_x"]))
out["_chosen_on_2021_2024"] = best
print("chosen on the choosing months:", best, flush=True)
json.dump(out, open("/home/user/crypto-bot-research/research/mixchop_st/ladder9.json", "w"), ensure_ascii=False, indent=1)
