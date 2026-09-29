"""Outputs of the recommended rule for typical chart states (R = 0.5 % and 1 %, stop 1.5 ATR, round trip 0.14 %)."""
import math
rows = [("5m, calm (ATR 0.25 %)", 0.0025), ("15m BTC typical (ATR 0.40 %)", 0.0040), ("15m SOL typical (ATR 0.74 %)", 0.0074),
        ("1h typical (ATR 1.0 %)", 0.010), ("4h typical / 15m in a crash (ATR 2.0 %)", 0.020), ("1d typical (ATR 5.0 %)", 0.050)]
print("| chart state | stop distance | N at R=0.5 % | N at R=1 % | max L (liq >= 2x stop, <= 10x) | L if M = 20 % (R=0.5 %) | 1-ATR adverse move costs (R=0.5 %) |")
print("|---|---|---|---|---|---|---|")
for lab, a in rows:
    stop = 1.5 * a
    n05 = min(0.005 / (stop + 0.0014), 2.0); n1 = min(0.01 / (stop + 0.0014), 2.0)
    lmax = min(10, math.floor(1 / (2 * stop + 0.005)))
    l20 = n05 / 0.20
    l20s = f"{l20:.1f}x" if l20 >= 1 else "1x with M = N"
    print(f"| {lab} | {100*stop:.2f} % | {n05:.2f}x | {n1:.2f}x | {lmax}x | {l20s} | {100*n05*a:.2f} % of equity |")
