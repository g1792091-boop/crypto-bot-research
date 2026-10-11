# Planned post-verdict reads (written 2026-10-12 KST night, before any select or test of either study)

This file is committed before the server computes anything. It fixes what the next reads module(s) will compute,
so that these reads are not shaped by tonight's results. It is not in the pin. Each module that computes these reads
gets its own pin line in `PREREG_HUNT_WIDE.sha256` when it is built. Its pin line will come after `test.json`, so its
output carries the label "post-test look; definition committed before the test (this file, commit date)". None of
these reads chooses a system or changes picks, P0-P4, p, BH, PASS or the lineup. DeepSeek rows go to the private file
only (D11).

Rows: the fixed ROWS of PREREG_HUNT_WIDE 7.1 (tested picks, the v1 pick, the baskets). Periods: select and test side
by side (2020 extra where 7.1 has it). Controls: (a) random entry and (b) coin-flip side, seeds 1-200, split the same
way, with pick minus control and month-block 95% intervals.

## P1. Weekday/weekend and session splits (owners 2026-10-11: "주말장 평일장 코인별 등등 그런부분도 다 분석")

- **Weekend:** the signal-bar close is from Saturday 00:00 up to, but not including, Monday 00:00 UTC. This is the same
  definition as O1.
- **Sessions:** keyed on the signal-bar close, in UTC: Asia 00-08, Europe 08-16, US 16-24. These are the same bounds
  as `docs/newlab-prereg.md`.
- **Per row and per period, longs and shorts separately, for weekday vs weekend and for each session:**
  - positions
  - win share
  - mean and median R
  - share of the row's P&L
  - the same for controls (a) and (b), and pick minus control
- Descriptive only. A weekend or session rule can only come from a later pre-registered round.

## P2. Risk at the sizes the owners want (20/30/40x and the goal sizes)

1. **Spread of 30-day multiples:** for every R1 board cell and every R24 cell, report p10, p25, p75 and p90 of the
   window multiple, and the share of windows ending below x0.5 and below x1. Today the board keeps only the median,
   worst and best.
2. **Chance of falling to half:** from daily equity of the continuous accounts, the share of start days from which
   equity first touches x0.5 within 3, 6 and 12 months. It is path based, not a bootstrap of monthly ln M alone.
3. **Continuous accounts at L = 20, 30, 40** (rule-bot sizing, as R24), $1,000 start, over each period. For each,
   report:
   - the end multiple and geometric monthly return
   - max DD
   - the bust date, if any
   - liquidations and skips by reason
   - the equity at which the bracket or fallback table first blocks an entry
4. **R24 at cost x2 and at funding x2:** the R24 board again with both cost stresses.
5. **R24 on 1m last price with mark-price liquidation:** on the coins and months the fidelity step already
   downloads.

Label every output "rule-bot sizing read, not the tested machine".

## P3. The owners' own limits as labels (no new run)

For each row, at every size already computed (r 0.5%, r 1%, the size fixed on select, and the R24 cells), give two
in/out labels:
- win share >= 70%
- max DD within 15m 15%, 30m 20%, 1h 30%, 4h 30% (for a basket, its strictest member's limit)

Add a column for the O1 weekend-excluded version. Print with it:
- these picks use the chandelier exit with no take-profit;
- a DD label holds only at the size it was measured;
- the labels are reference only and change nothing.

## P4. O3 (same-side cap) and O2 (macro blackout)

- **O3:** computed as `O3_NEEDS` in `reads_o.py` specifies, by a separate engine copy (`reads_o3.py`) that refuses to
  run if `hunt.py`'s sha256 differs. If it is never built, it goes in DEVIATIONS.md.
- **O2:** runs only after every event in `macro_calendar.json` is checked on the official pages and the file's pin
  line is appended.
