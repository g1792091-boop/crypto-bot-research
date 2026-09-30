# DOGE strategy (DOGE_L, 15m, long only) blind chart notes
Written before opening key_DOGE.csv. Same codes as notes_V45.md (MOVE may also be BREAK, as in
notes_V39.md). STOCH here is StochRSI K at entry. Two extra codes for the EMA-based rules:
- STACK: FULL (ema_short > ema_fast > ema_slow > ema_trend) / PARTIAL (some EMAs tangled or ema_trend above
  one of them) / NONE
- EXT: price distance above ema_trend as a share of the visible 100-bar range: FAR (>= ~0.45) / NEAR (0 to
  ~0.45) / BELOW (price under ema_trend)

| id | coin side | notes | CTX | MOVE | LOC | STOCH | TGT | VOL | STACK | EXT |
|---|---|---|---|---|---|---|---|---|---|---|
| DOGE-01 | SOL L | choppy range; long upper-mid just under ema_trend after dip (1h DOWN) | RANGE | DIP | MID | MID | BEYOND | NORMAL | PARTIAL | BELOW |
| DOGE-02 | BCH L | flat then strong rally; consolidation at highs; long after dip | WITH | DIP | EXTREME-CHASE | OS | AT | NORMAL | FULL | FAR |
| DOGE-03 | XRP L | spike, crash, then steady rally; long near top | WITH | DIP | EXTREME-CHASE | OS | BEYOND | LOW | FULL | FAR |
| DOGE-04 | BCH L | rally, peak, slow fade into long flat; long in the flat (1h DOWN) | RANGE | FLAT | EXTREME-CHASE | OS | AT | LOW | PARTIAL | NEAR |
| DOGE-05 | BCH L | drop, flat base, violent rally; consolidation at highs; long after dip | WITH | DIP | EXTREME-CHASE | OS | AT | HIGH | FULL | FAR |
| DOGE-06 | BTC L | decline, base, rally; consolidation at highs (1h DOWN) | WITH | DIP | EXTREME-CHASE | OS | BEYOND | NORMAL | PARTIAL | NEAR |
| DOGE-07 | BCH L | stepped uptrend; long after pullback from spike high | WITH | DIP | MID | OS | AT | NORMAL | FULL | NEAR |
| DOGE-08 | BCH L | range then rally; tight consolidation at highs (1h DOWN) | WITH | FLAT | EXTREME-CHASE | OS | AT | NORMAL | FULL | NEAR |
| DOGE-09 | LTC L | drop then rally; pullback from spike high; long on a big green candle | WITH | DIP | EXTREME-CHASE | OS | BEYOND | NORMAL | FULL | NEAR |
| DOGE-10 | XRP L | range then rally; consolidation at highs | WITH | DIP | EXTREME-CHASE | MID | AT | LOW | FULL | FAR |
| DOGE-11 | LTC L | drop, recovery, choppy near top; long near top | WITH | DIP | EXTREME-CHASE | MID | BEYOND | LOW | FULL | NEAR |
| DOGE-12 | BTC L | strong rally then long flat, fading top; long in the flat | RANGE | FLAT | EXTREME-CHASE | OS | BEYOND | LOW | PARTIAL | FAR |
| DOGE-13 | DOGE L | range; recovery; long near top on a big green candle | WITH | BREAK | EXTREME-CHASE | MID | BEYOND | NORMAL | FULL | NEAR |
| DOGE-14 | BCH L | choppy; sharp spike down then recovery; long upper-mid | RANGE | DIP | MID | MID | BEYOND | HIGH | PARTIAL | NEAR |
| DOGE-15 | ETH L | drop, recovery rally, consolidation near highs | WITH | DIP | MID | MID | AT | NORMAL | FULL | NEAR |
| DOGE-16 | SOL L | stepped uptrend; long near top after spike | WITH | DIP | EXTREME-CHASE | MID | BEYOND | NORMAL | FULL | NEAR |
| DOGE-17 | BCH L | rally then rolling top; long after dip below the short EMA | WITH | DIP | EXTREME-CHASE | OS | BEYOND | NORMAL | PARTIAL | FAR |
| DOGE-18 | XRP L | decline, crash, recovery; long on breakout candle near highs | WITH | BREAK | EXTREME-CHASE | MID | BEYOND | NORMAL | PARTIAL | NEAR |
| DOGE-19 | DOGE L | range, violent spike up and pullback, steady re-rally; long upper-mid | WITH | GRIND | MID | MID | BEYOND | HIGH | FULL | NEAR |
| DOGE-20 | BCH L | stepped uptrend; consolidation at highs | WITH | FLAT | EXTREME-CHASE | OS | BEYOND | NORMAL | FULL | FAR |
| DOGE-21 | BCH L | range, drop, recovery; long upper-mid after pullback, EMAs tangled | RANGE | DIP | MID | MID | AT | NORMAL | PARTIAL | NEAR |
| DOGE-22 | LTC L | stepped uptrend; spike high then pullback; long upper part (1h DOWN) | WITH | DIP | MID | MID | AT | NORMAL | FULL | FAR |
| DOGE-23 | SOL L | crash, recovery, range; long on big green candle at range top | RANGE | BREAK | MID | OS | BEYOND | NORMAL | PARTIAL | NEAR |
| DOGE-24 | SOL L | long steady uptrend; consolidation below spike high; long on green candle | WITH | BREAK | EXTREME-CHASE | OS | BEYOND | NORMAL | FULL | FAR |
| DOGE-25 | BTC L | early drop then steady grind up; consolidation near highs | WITH | DIP | EXTREME-CHASE | MID | BEYOND | LOW | FULL | FAR |
| DOGE-26 | BCH L | steady rise then big rally; consolidation at highs | WITH | DIP | EXTREME-CHASE | OS | BEYOND | NORMAL | FULL | FAR |
| DOGE-27 | BCH L | long uptrend; consolidation at highs | WITH | DIP | EXTREME-CHASE | OS | BEYOND | NORMAL | FULL | FAR |
| DOGE-28 | BCH L | range then rally; spike top, decline to ema_slow, long on bounce | WITH | DIP | MID | OS | AT | NORMAL | PARTIAL | NEAR |
| DOGE-29 | XRP L | choppy range; spike up then fade; long just above ema_trend (1h DOWN) | RANGE | DIP | MID | OS | AT | NORMAL | PARTIAL | NEAR |
| DOGE-30 | DOGE L | stepped uptrend; consolidation at highs | WITH | DIP | EXTREME-CHASE | OS | BEYOND | NORMAL | FULL | FAR |
| DOGE-31 | BCH L | stepped uptrend; consolidation near highs | WITH | DIP | EXTREME-CHASE | OS | BEYOND | NORMAL | FULL | FAR |
| DOGE-32 | XRP L | rally then slow fade from top toward ema_slow; long (1h DOWN) | WITH | GRIND | MID | OS | AT | NORMAL | PARTIAL | NEAR |
| DOGE-33 | SOL L | drop, recovery, spike high then pullback; long upper part (1h DOWN) | WITH | DIP | MID | MID | AT | NORMAL | FULL | NEAR |
| DOGE-34 | ETH L | flat then strong rally; drifting consolidation at highs | WITH | FLAT | EXTREME-CHASE | OS | AT | NORMAL | FULL | FAR |
| DOGE-35 | DOGE L | drop, flat base, violent rally; consolidation at highs | WITH | FLAT | EXTREME-CHASE | MID | BEYOND | NORMAL | FULL | FAR |
| DOGE-36 | LTC L | range then rally; consolidation at highs; long on big green candle (1h DOWN) | WITH | BREAK | EXTREME-CHASE | MID | BEYOND | NORMAL | FULL | NEAR |
| DOGE-37 | ETH L | drop, range, breakout rally; consolidation at highs (1h DOWN) | WITH | DIP | EXTREME-CHASE | MID | BEYOND | NORMAL | FULL | NEAR |
| DOGE-38 | DOGE L | spike down, slow recovery grind; long near top after dip (1h DOWN) | WITH | DIP | EXTREME-CHASE | OS | BEYOND | LOW | PARTIAL | NEAR |
| DOGE-39 | LTC L | decline, rally, consolidation near highs | WITH | DIP | EXTREME-CHASE | MID | BEYOND | NORMAL | FULL | NEAR |
| DOGE-40 | XRP L | choppy wide range with spikes; long upper part after dip | RANGE | DIP | MID | OS | AT | HIGH | FULL | FAR |
| DOGE-41 | LTC L | drop, V recovery, consolidation near top (1h DOWN) | WITH | DIP | EXTREME-CHASE | MID | BEYOND | NORMAL | FULL | NEAR |
| DOGE-42 | BTC L | decline, V rally, top, pullback to ema_slow; long on bounce (1h DOWN) | WITH | DIP | EXTREME-CHASE | OS | AT | NORMAL | PARTIAL | NEAR |
| DOGE-43 | XRP L | steady accelerating uptrend; consolidation near top | WITH | DIP | EXTREME-CHASE | MID | BEYOND | NORMAL | FULL | FAR |
| DOGE-44 | BTC L | range, rally, choppy top, pullback; long on green candle | WITH | DIP | MID | MID | BEYOND | NORMAL | FULL | FAR |
| DOGE-45 | BCH L | spike to top, crash back, recovery; long on big green candle | RANGE | BREAK | MID | MID | AT | HIGH | FULL | FAR |
| DOGE-46 | ETH L | flat, one huge spike up, then flat consolidation; long in the flat | WITH | FLAT | MID | OS | BEYOND | LOW | FULL | NEAR |
| DOGE-47 | DOGE L | stepped uptrend with spikes; dip to ema_slow then big green candle | WITH | BREAK | MID | OS | BEYOND | HIGH | PARTIAL | FAR |
| DOGE-48 | XRP L | range then rally; top, drop to ema_slow, recovery | WITH | DIP | MID | MID | AT | NORMAL | PARTIAL | NEAR |
| DOGE-49 | LTC L | decline, V rally, top, pullback then flat; long (1h DOWN) | WITH | FLAT | EXTREME-CHASE | OS | BEYOND | NORMAL | PARTIAL | NEAR |
| DOGE-50 | XRP L | choppy range; rally near top with spikes | RANGE | DIP | EXTREME-CHASE | OS | BEYOND | LOW | FULL | NEAR |
| DOGE-51 | DOGE L | range, spike up, crash, recovery; consolidation upper part | RANGE | DIP | MID | MID | AT | NORMAL | FULL | NEAR |
| DOGE-52 | ETH L | long flat, spike up, one big red candle then green; long | WITH | DIP | EXTREME-CHASE | MID | BEYOND | HIGH | PARTIAL | NEAR |
| DOGE-53 | BCH L | rally, crash, V recovery, choppy top; long near ema_trend (1h DOWN) | RANGE | DIP | MID | OS | BEYOND | NORMAL | PARTIAL | NEAR |
| DOGE-54 | LTC L | flat; one huge spike then flat; long on green candle | RANGE | BREAK | MID | MID | AT | LOW | FULL | NEAR |
| DOGE-55 | BCH L | choppy range; spike up then pullback; long on green candle (1h DOWN) | RANGE | BREAK | MID | OS | BEYOND | NORMAL | PARTIAL | NEAR |
| DOGE-56 | XRP L | flat then strong rally; spike top; consolidation below it | WITH | DIP | MID | OS | AT | NORMAL | FULL | FAR |
| DOGE-57 | SOL L | rally, range, new high, pullback | WITH | DIP | MID | MID | BEYOND | NORMAL | FULL | FAR |
| DOGE-58 | XRP L | flat, big rally, top, pullback to ema_slow, green candle (1h DOWN) | WITH | BREAK | EXTREME-CHASE | OS | BEYOND | NORMAL | PARTIAL | NEAR |
| DOGE-59 | LTC L | flat then strong rally; consolidation at highs with spike wick | WITH | DIP | EXTREME-CHASE | MID | AT | HIGH | FULL | FAR |
| DOGE-60 | DOGE L | range; huge spike wick then consolidation (1h DOWN) | RANGE | FLAT | MID | MID | BEYOND | NORMAL | PARTIAL | NEAR |

Overall impression before unblinding: the DOGE strategy is a long-only trend-continuation entry: EMAs
stacked up, StochRSI reset low and turning up, RSI above 52. That puts most entries in a consolidation or
pullback near the top of an established rally (long near highs), and the 3 ATR target usually needs a new
high (BEYOND). Candidate patterns to check after unblinding: EXTREME-CHASE, TGT BEYOND, EXT FAR (far above
ema_trend), STACK PARTIAL (EMAs tangled), BREAK entries on one big candle, LOW volatility, 1h DOWN label.
