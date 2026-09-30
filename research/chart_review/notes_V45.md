# V4.5 (V45_AMB, 15m) blind chart notes
Written before opening key_V45.csv. Codes used for later tabulation:
- CTX: local chart trend vs trade side: WITH / AGAINST / RANGE
- MOVE: last ~3-8 bars before entry: FADE-SPIKE (entering against a sharp move of >=3 strong candles),
  DIP (small pullback), FLAT
- LOC: entry location in the visible 100-bar range for the trade side: EXTREME-FAVOURABLE (long near low /
  short near high), MID, EXTREME-CHASE (long near high / short near low)
- STOCH: OB (>80) / OS (<20) / MID
- TGT: target reaches beyond the obvious recent swing level (BEYOND) or stops at/before it (AT)
- VOL: LOW (tight candles, small range) / NORMAL / HIGH

| id | coin side | notes | CTX | MOVE | LOC | STOCH | TGT | VOL |
|---|---|---|---|---|---|---|---|---|
| V45-01 | LTC L | pullback after rally to 150; ST3 above, ST6 below; target at prior high 149.6 | WITH | DIP | MID | MID | AT | NORMAL |
| V45-02 | DOGE S | after strong spike up and pullback, short while price still well above earlier range | AGAINST | DIP | MID | MID | AT | HIGH |
| V45-03 | BCH L | long after sharp drop with volume spike, local downtrend | AGAINST | FADE-SPIKE | EXTREME-FAV | MID | BEYOND | HIGH |
| V45-04 | SOL S | short near top of a rising structure | AGAINST | DIP | EXTREME-FAV | MID | AT | NORMAL |
| V45-05 | BCH S | downtrend, short into sharp 4-candle bounce | WITH | FADE-SPIKE | MID | OB | AT | NORMAL |
| V45-06 | BCH L | tight sideways after big impulse up | RANGE | FLAT | MID | MID | AT | LOW |
| V45-07 | BCH S | downtrend, short into sharp 3-candle bounce | WITH | FADE-SPIKE | MID | OB | AT | NORMAL |
| V45-08 | BTC L | very low-vol range, long mid-range | RANGE | DIP | MID | MID | AT | LOW |
| V45-09 | XRP L | long after sharp 4-candle drop, near bottom | AGAINST | FADE-SPIKE | EXTREME-FAV | OS | AT | NORMAL |
| V45-10 | ETH S | range, short at range top | RANGE | DIP | EXTREME-FAV | MID | AT | NORMAL |
| V45-11 | DOGE L | after spike and full retrace, dip buy | RANGE | DIP | MID | OS | AT | HIGH |
| V45-12 | LTC L | slow decline after spike, small wick dip | AGAINST | DIP | MID | MID | AT | NORMAL |
| V45-13 | SOL S | range, short into upside breakout of 3 strong candles | RANGE | FADE-SPIKE | EXTREME-FAV | OB | AT | NORMAL |
| V45-14 | LTC L | choppy, long after pullback | RANGE | DIP | MID | OS | AT | NORMAL |
| V45-15 | XRP S | downtrend then long steady rally; short into the rally | AGAINST | FADE-SPIKE | EXTREME-FAV | OB | AT | NORMAL |
| V45-16 | SOL L | declining after spike, dip buy | AGAINST | DIP | MID | MID | AT | NORMAL |
| V45-17 | DOGE S | after crash, slow low-vol grind up; short near top of grind, tight stop | AGAINST | GRIND | EXTREME-FAV | OB | AT | LOW |
| V45-18 | XRP S | range, short into sharp 3-candle spike at range top | RANGE | FADE-SPIKE | EXTREME-FAV | OB | AT | NORMAL |
| V45-19 | ETH L | choppy decline, long after small bounce off low | AGAINST | DIP | EXTREME-FAV | MID | AT | NORMAL |
| V45-20 | ETH L | sharp drop with long wick and volume spike, long near bottom | AGAINST | FADE-SPIKE | EXTREME-FAV | MID | AT | HIGH |
| V45-21 | BTC L | slow low-vol drift down after spike; long near drift low | AGAINST | GRIND | EXTREME-FAV | MID | AT | LOW |
| V45-22 | DOGE L | uptrend then range at top; dip buy mid-range | WITH | DIP | MID | MID | AT | NORMAL |
| V45-23 | DOGE S | choppy range; short upper-mid after pullback from spike | RANGE | DIP | MID | MID | AT | NORMAL |
| V45-24 | LTC S | range; short after steady recovery rally | RANGE | GRIND | EXTREME-FAV | MID | AT | NORMAL |
| V45-25 | SOL L | slow low-vol decline after spike; long | AGAINST | GRIND | MID | MID | AT | LOW |
| V45-26 | BTC L | range; long after sharp wick down and recovery | RANGE | FADE-SPIKE | MID | MID | AT | NORMAL |
| V45-27 | XRP L | steady decline after spike; long at bottom | AGAINST | GRIND | EXTREME-FAV | OS | AT | NORMAL |
| V45-28 | DOGE S | downtrend; short into 5-6 candle rally | WITH | FADE-SPIKE | MID | OB | AT | NORMAL |
| V45-29 | DOGE S | crash then rebound rally; short into rally | WITH | FADE-SPIKE | MID | OB | AT | HIGH |
| V45-30 | BCH S | downtrend; short into multi-candle rally | WITH | FADE-SPIKE | MID | MID | AT | NORMAL |
| V45-31 | ETH S | downtrend-range; short into sharp 4-candle rally | WITH | FADE-SPIKE | MID | OB | AT | NORMAL |
| V45-32 | LTC S | crash then consolidation; short after small rally, wide stop | WITH | DIP | MID | MID | AT | HIGH |
| V45-33 | ETH S | tight low-vol range; short upper-mid after pullback | RANGE | DIP | MID | MID | AT | LOW |
| V45-34 | SOL S | downtrend consolidation; short after small rally faded | WITH | DIP | MID | MID | AT | NORMAL |
| V45-35 | ETH L | strong uptrend, tight flat consolidation near highs | WITH | FLAT | MID | MID | AT | LOW |
| V45-36 | SOL L | slow low-vol drift down; long at bottom | AGAINST | GRIND | EXTREME-FAV | OS | AT | LOW |
| V45-37 | DOGE S | downtrend; short into sharp 3-candle spike | WITH | FADE-SPIKE | MID | OB | AT | NORMAL |
| V45-38 | DOGE S | steady downtrend; short after small rally, price near bottom of range | WITH | FADE-SPIKE | EXTREME-CHASE | OB | AT | NORMAL |
| V45-39 | BCH S | rising structure; short near top | AGAINST | DIP | EXTREME-FAV | MID | AT | NORMAL |
| V45-40 | ETH S | range; sharp V recovery to range top; short | RANGE | FADE-SPIKE | EXTREME-FAV | OB | AT | NORMAL |
| V45-41 | XRP S | steady uptrend; short near top, tight stop | AGAINST | GRIND | EXTREME-FAV | OB | AT | NORMAL |
| V45-42 | SOL L | steady decline with rising volume; long near bottom | AGAINST | GRIND | EXTREME-FAV | MID | AT | NORMAL |
| V45-43 | ETH L | uptrend, drift down from top consolidation | WITH | DIP | MID | MID | AT | NORMAL |
| V45-44 | SOL S | choppy range; short after rally near top | RANGE | DIP | EXTREME-FAV | OB | AT | NORMAL |
| V45-45 | BCH L | decline after spike; long at bottom | AGAINST | GRIND | EXTREME-FAV | OS | AT | NORMAL |
| V45-46 | BTC L | tight range, spike up then drop; long mid | RANGE | FADE-SPIKE | MID | MID | AT | LOW |
| V45-47 | DOGE L | range; sharp high-volume drop; long | RANGE | FADE-SPIKE | MID | MID | AT | NORMAL |
| V45-48 | DOGE L | decline after spike; long near bottom | AGAINST | GRIND | EXTREME-FAV | OS | AT | NORMAL |
| V45-49 | SOL S | range; rally back up from low with several strong candles; short | RANGE | FADE-SPIKE | MID | OB | AT | NORMAL |
| V45-50 | XRP S | range; breakout spike to new high with volume; short into breakout | RANGE | FADE-SPIKE | EXTREME-FAV | OB | AT | NORMAL |
| V45-51 | LTC L | range; long mid after pullback | RANGE | DIP | MID | MID | AT | NORMAL |
| V45-52 | SOL L | choppy decline after spike; long near lower part | AGAINST | DIP | EXTREME-FAV | MID | AT | NORMAL |
| V45-53 | XRP S | after crash, slow steady grind up; short near top of grind | AGAINST | GRIND | MID | OB | AT | NORMAL |
| V45-54 | LTC L | choppy range; long after sharp drop with volume spike | RANGE | FADE-SPIKE | MID | OS | AT | NORMAL |
| V45-55 | XRP S | downtrend; short into steady multi-candle rally | WITH | GRIND | MID | OB | AT | NORMAL |
| V45-56 | XRP L | spike up then steady decline; long after drop | AGAINST | GRIND | MID | OS | AT | NORMAL |
| V45-57 | SOL L | breakout up then choppy consolidation; long after dip | WITH | DIP | MID | MID | AT | NORMAL |
| V45-58 | LTC S | after drop, slow grind up; short near grind top | AGAINST | GRIND | MID | OB | AT | LOW |
| V45-59 | BCH S | rebound up then range at top; short at top after wick spike | AGAINST | FADE-SPIKE | EXTREME-FAV | MID | AT | NORMAL |
| V45-60 | DOGE L | spike and range; long after decline back to mid | RANGE | DIP | MID | OS | AT | NORMAL |

Overall impression before unblinding: V4.5 is a counter-move (mean-reversion) entry by design: it
buys dips / sells rallies against the short-term move, usually with the 1h trend. Targets (3 ATR) almost
always stop at or before the obvious recent swing level; stops are often just beyond a recent wick.
Candidate patterns to check after unblinding: FADE-SPIKE vs DIP/GRIND, CTX AGAINST vs WITH, LOW volatility,
entries at EXTREME-FAV (range edge) vs MID, STOCH OB/OS at entry.
