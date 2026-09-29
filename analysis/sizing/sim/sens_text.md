- **Intrabar order: 5m sub-bars (`sub`) are the reference.** Resolving every exit on the 5m bars inside the trade
  barely changes 15m-4h: P3's minimum edge is 0.29 % (base 0.29) on 15m, 0.64-0.84 % (base 0.69-0.86) on 1h and
  0.55-0.61 % (base 0.58-0.67) on 4h. On **1d** it matters, because a daily bar usually touches both a 0.2-0.5 % TP and
  the stop or liquidation level. The bar-colour rule was too pessimistic there. With sub-bars, P3 needs about **2.0 %**
  (base: not reached up to 3 %). P4's 1d liquidation share drops from 22.6 % to 9.8 %. The verdict does not change:
  - P3 at zero edge: 1-year median x0.70 (base x0.53), P(<50 % within 1 year) 0.40.
  - P4 at zero edge: 1-year median x0.094, P(<50 %) 0.94, P(ruin) 0.58.
  - Both look fine month to month. The 30-day median is x1.05 for P3 and x1.07 for P4, with a median 30-day max
    drawdown of 0 % and a 90 % win rate.
  - `adv` (adverse first in every bar) and `fav` (favourable first) bracket the answer. `fav` cannot happen on daily
    bars: it books a TP whenever a bar touches both levels. It is the only variant in which P3/P4 with a stop look
    profitable at zero edge on 1d.
- **Mark-price proxy for liquidation (`mark`).** Wick parts sticking out more than 0.5 ATR beyond the neighbouring bars
  are removed for the liquidation check only. This touches 3.5-6 % of bars.
  - Liquidation shares fall only slightly: P3 2.0 → 1.6 % (15m), 5.9 → 5.1 % (1h), 5.4 → 4.7 % (4h); P4 22.6 → 22.1 % (1d).
  - P3's minimum edge moves 0.69 → 0.53 % (1h) and 0.62 → 0.50 % (4h); 15m is unchanged (0.28 %). P4 still fails
    everywhere.
  - So the liquidations come from real moves, not from spikes in the spot data.
- **Front-loaded edge (`front`).** Here the whole planted drift arrives in the first quarter of the holding period
  (H/4 bars; 1 bar on 4h/1d). This is the case most favourable to a tight TP. Minimum planted drift:
  - P3: 0.14-0.32 % on 5m-4h, 1.9 % on 1d (bar-colour rule).
  - P5: 0.29 % on 15m with a stop (not reached without one), 0.36-0.46 % on 1h, 0.27-0.33 % on 4h; not reached on 5m.
  - P4: not reached anywhere.
  - In realised terms the requirement matches the base case. With its own exits, P3 must show a realised gross move of
    about +0.12-0.15 % and a net of +0.013-0.033 % per trade per unit notional.
- **Maker entries (`maker`, optimistic: every limit entry fills).** Cutting the entry cost from 0.07 % to 0.02 % lowers
  every requirement by 0.05-0.3 %:
  - P3: 0.12-0.13 % (5m), 0.16-0.18 % (15m), 0.38-0.43 % (1h), 0.30-0.40 % (4h).
  - P6: 0.16-0.19 %.
  - P4 becomes feasible only on 5m (0.30-0.39 %).
  - At D = 0.10 %, the 1x-2.5x no-stop policies on 5m/15m now grow slightly (1-year median x1.02-1.17). Nothing at 4x
    notional or more does.
  - All of these are still above every OOS-validated edge in this project; none of those is above 0.
