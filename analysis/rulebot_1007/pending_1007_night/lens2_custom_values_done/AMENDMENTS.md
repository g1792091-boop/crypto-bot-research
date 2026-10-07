# Amendments to PREREG.md (PREREG.md itself is unchanged, hash checked by every script)

## A1 (2026-10-07, after the first full run, written after seeing R results)
Observation: the pre-registered metric R is measured in units of the chosen stop. A wider stop (2.5 ATR) makes the
same money loss a smaller number of R, so a search on R is pulled toward wide stops mechanically, and the R gain
did not show up in net % per trade (delta_netpct_per_trade <= 0 for the R-selected streams). I had expected this
("wide stops lower cost in R mechanically", PREREG section 8) but did not fix the unit in advance.
Added, reported side by side, NOT replacing the R results:
- Metric R2 = net P&L / (qty x 2.0 x ATR14 distance) = R x k/2 for stop k (1.5 -> x0.75, 2.0 -> x1.0, 2.5 -> x1.25).
  R2 is the net money result in units of the DEFAULT stop distance, so every combination is in the same unit.
- The whole pipeline (selection on the training window, gates with the same R-unit thresholds, OOS evaluation,
  day-cluster bootstrap) is re-run with R2 in place of R. Same code, same seed. Outputs in work/wf_R2 and out_R2.
- Verdict rules of PREREG section 8 are applied to both metrics; the money-relevant verdict is the R2 one.
## A2 planted-improvement check (power / gate behaviour), stage5_planted.py: not in the PREREG, an added check.
## A3 one-position trades per week and pick composition (descriptive), stage4_extra.py.
