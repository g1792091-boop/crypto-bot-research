PRE-DECLARED discretionary-proxy rules (written 2026-10-07 before running any of them)

What I had already seen before writing this (disclosed): the analyze.py summary, including the nightly d3 variants
(core 36: lock30 +0.14R, tp1R(no ladder) +0.056R, timestop(12/10 bars, lock not armed) -0.065R, stopw1.5 +0.016R,
lev10 +0.26R) and the replay tables. I have NOT seen any result of the rules below on the replay.

Engine: paperbot.engine.PaperEngine (house rules: 2 ATR stop from the reference price, ROE ladder lock), each
SUBMITTED signal alone on a fresh $5,000 account, the run's own leverage rule, inferred funding, live_bars 1m
(v3b = run-20261005T183457Z, v4 = current). Reel / 5m coin flips excluded (not replayable). R = net pnl /
(qty x |entry - initial stop|), exactly as analyze.py. Signals still open at the end: marked to the last close
net of exit costs (mark_R), included, and also reported without them.

Rules (each one alone on top of the house rules; nothing else changes):
  R0 base     house rules (control; must reproduce replay_signals.csv R to 1e-9)
  R1 BE05     once the best price reached +0.5R (1m high/low), the stop moves to the net-breakeven price
              (entry +/- round trip + funding so far) from the next 1m bar; it only tightens
  R2 BE10     same at +1.0R
  R3 NP4      if 4 bars of the signal's timeframe have passed since entry, the best price never reached +0.3R
              and the ladder lock has not armed: close at market at that 1m bar's close (repo timestop convention)
  R4 NP8      same with 8 bars
  R5 TP1      ladder kept + resting take-profit (maker, trade-through) at reference + 1R
  R6 PART1    half off at +1R = 0.5 x R0 + 0.5 x R5 (exact by linearity of pnl in qty, rounding ignored)
  R7 CUT05    hard stop at -0.5R (stop moved to reference - side x 0.5 x stop distance at entry)
  R8 OPP      close at the reference price (+slippage, taker) of the strategy's own next opposite-side signal on the
              same symbol and the same timeframe (signal_log, any status)
  R9 OPPH     same, opposite signal of the same strategy and symbol on the same or any higher timeframe

Test (decided now): paired diff = R_rule - R_base per signal. Group = kind (strategy / ds200) x timeframe.
A rule "helps out of sample" in a group only if the mean diff is > 0 in BOTH v3b and v4 AND the pooled
cluster sign-flip p (one sign per cluster = run x bar close floored to max(tf,1h); 10,000 draws) is < 0.05 after
Benjamini-Hochberg over all rule x group cells. Same-sign-but-not-significant = "consistent, unproven".
Strategy x tf cells (15m/30m) are reported for description only, with BH; none is a discovery on its own.

Switching (account-level, pre-declared): each account's own SUBMITTED signal stream re-simulated through the engine
(base must reproduce the account's real trades), then with a policy that, when a new signal arrives while in position,
closes the held position at market (that 1m bar's open of the held symbol, slippage + taker) and lets the new signal
enter:
  SW_ANY    always
  SW_UNDER  only when the held position's unrealized net pnl is < 0
  SW_STALE  only when the held position has been open >= 4 bars of its timeframe and its best price never reached +0.3R
  SW_OPP    only when the new signal is the same symbol and the opposite side
Outcome: final equity (open positions marked) minus base, per account; summed per kind x tf; v3b and v4 separately.

ADDENDUM (written after the rules/switching results above, before running these; descriptive, no selection):
  Late entry ("a missed signal taken k bars later", design D12): the same signal entered k = 1, 2, 4 bars of its
  timeframe after the original bar close, at that later 1m open (reference price), with a fresh 2 ATR stop from there
  (same ATR), house rules. Compared with the on-time entry of the same signal (paired).
  Leverage and the ROE ladder: the same signals with fixed leverage 20x / 30x / 40x / 50x (margin = leverage %, the
  owners' rule), house rules; the ladder locks a fixed ROE, so its price distance shrinks as leverage grows. Paired in R.

ADDENDUM 2 (before running; descriptive): skip headroom from signal agreement. For every replayed signal, count the
OTHER submitted signals (strategy + ds200, any timeframe) on the same coin whose bar closed within +-15 min:
same side n_same, opposite side n_opp. Groups: "alone" (both 0), "agree" (n_same > n_opp), "conflict" (n_opp >= n_same,
n_opp > 0). Mean R per group, per run, kind x tf; a skip rule "skip conflict" is judged only if same sign in v3b and v4.
  Correction (after the first run, before reading it as a result): +-15 min lets signals AFTER the entry vote
  (look-ahead; momentum signals fire after the move). The AI-visible version counts only signals whose bar closed in
  [entry bar close - 15 min, entry bar close]; both are kept, the +-15 one labelled leaky.
