# Net-of-fees take-profit rerun (handoff v2.2)

**Why.** On 2026-09-30 (KST) the user confirmed that the +10% take-profit is **net ROE after fees**, not gross ROE.
The 3.2 (sizing), 3.3 (tiered) and zero-edge bracket simulations had used a gross 10% ROE target (price distance
10%/L, e.g. 0.5% at 20x). This folder reruns them with the net definition.

**What changed (only this).** TP price distance = 10%/L + 0.14% (round trip: taker 0.05% + slippage 0.02% per side).
20x 0.64%, 30x 0.473%, 40x 0.39%, 50x 0.34%. Same data (IS bars only, < 2024-07-01), same seeds, same edges,
same edge horizons (tiered h_e forced to the original 10/6/3/2 bars), same costs. The simulators charge the TP exit
as maker 0.02% (sizing) or taker 0.05% (tiered), so the realised net ROE on a TP is 10% or slightly above.
Policies without a TP (P6/P6h) are unaffected. Nothing here selects a strategy or uses OOS/FINAL data.

**Patches.** `patches/*.diff` against the committed code (`analysis/sizing/sim/run_sim.py`, `killswitch.py`,
`analysis/sizing/math/work/common.py`, `analysis/tiered/sim/run.py`, `analysis/tiered/verify/vsim.py`).
The run scripts (`chainA/B/C.sh`) use the analysis session's temp paths, like the other scripts in this repo.

## Key results (net vs gross)

| Item | Gross 10% (v2.1) | Net 10% (v2.2) | Source |
|---|---|---|---|
| Zero-edge P(TP first), 20x / 50x (5m) | 0.900 / 0.884 | 0.875 / 0.817 | out/math/bracket_zero_edge.csv |
| Zero-edge E[ROE] per trade, 20x / 50x | -3.2~-3.8% / -7.8~-9.4% | -3.5~-4.2% / -9.1~-10.9% | same |
| Break-even P(TP first) | 93.5% (20x) / 97.2% (50x) | ~91.2% at every L | same |
| Min edge, user minimum 20x x 20% (no stop / half-liq stop) | 5m 0.19, 15m 0.28-0.29, 1h 0.69-0.71, 4h 0.62-0.67% | 5m 0.19, 15m 0.27-0.28, 1h 0.59-0.60, 4h 0.55-0.56% | out/sizing_net/min_edge_table.txt |
| Same, 1.5 ATR stop | 0.29 / 0.43 / 0.86 / 0.58% | 0.29 / 0.37 / 0.70 / 0.50% | same |
| 50x x 40%, TP 10% | fails at every edge and TF | 5m only, 0.39-0.40% (no stop / half-liq stop); 15m+ fails | same |
| 1d trap example, 50x x 40%, zero edge (5m sub-bars) | win 90%, 30d median x1.07, 1y x0.094 | win 85%, 30d median x0.78, 1y x0.046 | out/sizing_netsub/1d_metrics.csv |
| 1d, 20x x 20%, zero edge (5m sub-bars) | win 91%, 30d x1.05, 1y x0.70 | win 89%, 30d x1.02, 1y x0.67, P(<50%) 0.46 | same |
| Kill-switch equity at -20% from peak, 50x x 40% | 0.60-0.65 | 0.62-0.67 | out/sizing_net/killswitch_net.csv |
| Tiered rule 12m median (adverse / favourable, S0-S4) | 1h $8-35, 4h $237-302 | 1h $4-31, 4h $173-246 | out/tiered/tables.md |
| Tiered, independent verifier (1h / 4h, S0-S4) | 1h $8-32, 4h $180-290 (4 seed sets) | 1h $4.5-34, 4h $137-263 (2 seed sets) | ../../tiered/verify/v_*_adv*.csv vs out/verify/v_*_net.csv |
| Tiered, perfect foresight on the top decile (verifier) | 1h $63-78, 4h $369-403 | 1h $131-133, 4h $335-430 | same |
| Tiered P(12m end < $500) | ~70-100% | ~72-100% | tables.md + verifier |
| Tiered: share of losses that are fees (S0) | 89-98% | 74-96% | tables.md |
| Tiered: liquidation rate of "perfect" (50x) trades, 1h / 4h | main S0 6% / 9%; verifier S0-S4 5-6% / 8-11% | main S0 11% / 16%; verifier S0-S4 8-10% / 13-16% | tables.md + verifier |
| Tiered min edge (h_e drift) for 12m median > $1,000 and P(<$500) < 20% | 5m none, 15m 0.40, 1h 0.50, 4h 0.80% | 5m 0.30 (top of grid), 15m 0.30, 1h 0.50, 4h 0.80% | tables.md |
| Flat 20x x 20%, same criterion | 0.25 / 0.25 / 0.30 / 0.50% | 0.25 / 0.25 / 0.30 / 0.40% | tables.md |
| Comparison baseline (risk 1%/2%, <=10x), zero edge 12m median 1h / 4h | $669 / $955 | $662 / $957 | tables.md |

**Conclusion unchanged.** The user's rules lose at zero edge and at every edge seen so far on every timeframe. A net TP
makes each win larger but is reached less often and adds liquidations; the zero-edge expected loss per trade stays
at or slightly above the round-trip cost times leverage (20x: -3.5 to -4.2% ROE vs 2.8% cost; the extra is the
maintenance margin lost on liquidations plus funding). The tiered rule still fails even with perfect foresight on the top decile.
