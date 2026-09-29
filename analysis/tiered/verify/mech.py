# Independent mechanics check: liquidation distance, fee drag in $ for $1,000 equity.
FEE, SLIP, MMR, FUND = 0.0005, 0.0002, 0.005, 0.0001
E = 1000.0
print("tier      L  margin$ notional$  liq_move(approx 1/L-MMR)  liq_move(exact iso: (1/L-MMR)/(1-MMR))  TP10%ROE_move  RT_cost$(TP exit)  RT_cost$(stop exit)  RT%eq(stop)  liq_loss$ (margin+entry fee)")
for name, L, m in [("normal", 20, .20), ("good", 30, .30), ("perfect", 50, .40), ("rec-cap", 10, 1.0)]:
    M = m * E; N = M * L
    la = 1 / L - MMR; le = (1 / L - MMR) / (1 - MMR)
    tp = 0.10 / L
    rt_tp = N * (FEE + SLIP) + N * FEE
    rt_st = N * 2 * (FEE + SLIP)
    liq = M + N * (FEE + SLIP)
    print(f"{name:8s} {L:3d} {M:7.0f} {N:9.0f}   {la*100:6.3f}%  {le*100:6.3f}%   {tp*100:.3f}%   {rt_tp:7.2f}  {rt_st:7.2f}  {rt_st/E*100:.2f}%  {liq:7.1f}")
# mix-average notional / cost for tier probabilities 70/20/10
w = [.7, .2, .1]; Nx = [4, 9, 20]
avgN = sum(a * b for a, b in zip(w, Nx))
print("avg notional x equity", avgN, " avg RT cost %eq (all market exits)", avgN * 2 * (FEE + SLIP) * 100,
      " (all TP exits)", avgN * (2 * FEE + SLIP) * 100)
# TP net ROE after fees
for L, m in [(20, .2), (30, .3), (50, .4)]:
    N = m * L
    gain = N * 0.10 / L  # equity fraction
    cost = N * (2 * FEE + SLIP)
    print(f"{L}x: TP gross +{gain*100:.2f}% eq, cost {cost*100:.2f}% eq, net {100*(gain-cost):.2f}% eq ; fee share of gross {cost/gain*100:.0f}%")
