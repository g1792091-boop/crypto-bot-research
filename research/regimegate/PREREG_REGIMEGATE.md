# 장세 문지기 (regime gate): pre-registration

Written 2026-10-11 (KST), before any result of this gate was computed. To be pinned, together with `gate.py`,
`style_map.json` and the label, bracket and sizing files they read (section 10), by `PREREG_REGIMEGATE.sha256`;
`gate.py` refuses to run `history` or `forward` without a matching pin. Any later change goes to `DEVIATIONS.md` in this
folder with its reason, never into this file.

Owners' words. Friend: "추세장 횡보장 매매법을 찾아서 ... 추세장이면 추세장 매매법을 사용 ... 횡보장이면 진입 금지".
Owner: "횡보장에서도 발라먹고 추세장에서도 발라먹는 매매법"; the goal is to grow a small account fast. On 2026-10-11 both
agreed to (A) a pre-registered backtest of seven new-information strategies and (B) this regime gate, judged on the data
available by 2026-10-31.

## 0. The question, and what was already seen

**Question.** If each strategy only enters in the market it is built for (trend strategies in a trending market,
reversion strategies in a ranging market, nothing in the wrong market), are the signals the gate lets through better than
the ones it blocks, and do the let-through signals make money after costs?

**Not blind in history.** Before this file, the following existed and some were read by the owners and the main session:

* `research/fullgrid/ANALYSIS_KO.md` 5-5: a different idea (per timeframe and state, the best 3 strategies of the
  select period, run in that state only). Its summary table was read by the author of this file.
* `research/fullgrid/STRATEGIES_KO.md`: per strategy and timeframe, the default numbers' mean per trade in each 장세 /
  큰 흐름 / 변동성 state over 2021-2026 (rule bot with money, DeepSeek without). The author of this file saw one of those
  tables (N03_ADX_GC) while checking how the labels are reported, and no other.
* `research/fullgrid/diag/regime_explore.json` (per-state sums of the 36's default numbers at both reads used here) and
  `docs/regime5y.md` with its dashboard data (장세 스위치: per-cell regime rules chosen on a pick period). Not opened by
  the author of this file.
* `ANALYSIS_KO.md` 5-4: the rule bot's entries show almost no direction skill (the opposite side at the same entries,
  or entries on any bar, did about as well).
* `analysis/rulebot_1007/workflow/section_context_filters.md` (2026-10-07, read by the main session and quoted in the
  AI design, `docs/aibot/design_v3_work/spec_decision.md`: "장세 맞추기(추세장/횡보장): 5년 0.04R 이하"): a close
  relative of this question, with other labels (signal_ctx regime and ER, R units) and other style classes. Over five
  years "trend strategies in high ER" was +0.04 / +0.02 R and "revert strategies in low ER" about 0; live (paper runs
  v3a, v3b and v4 up to 10-07) no context replicated, and v4 had no higher-timeframe trend signal at all. The dashboard's
  장세 스위치 result (`docs/regime5y.md`: 0 of 92 cells) is likewise quoted in the AI design documents.
* **Part of the forward window has already happened.** The window starts at the v4 run's start (2026-10-05 18:35
  UTC); by this file's date about 6 of its 24 days are past. The rule bot's live results for those days were read per
  strategy and timeframe (`research/live_interim`), and its first 1.5 days were cut by market context (above), but not
  by this gate's labels and classes. The gate rules come from the owners' words, not from those days.

So the history part can be roughly reconstructed from published per-strategy tables; it is a check, not a blind test.
The gate rules below come from the owners' words, and the classes from the catalog's style column (which describes the
entries, not their results). G2 (volatility) was proposed after ANALYSIS 5-5 had noted a weak hint for a volatility
split under the 4 ATR + 3R exit. **The forward part (section 5.2) is the blind test, and no gate becomes a candidate
without it (section 8).**

**Smoke runs before pinning** (no result): synthetic tables only (`tests/test_regimegate.py`), and one plumbing run on
2020-01-10 .. 2020-01-12 (BTC 15m, three cells) that checked array shapes and that the forward recomputation equals the
full grid's outcome table for the same signals (largest difference 1.2e-8, float32 rounding). Every market state in that
slice is 모름 (not enough history); no outcome number was looked at.

## 1. Data and unit

* Prices: the full grid's 1m archive (Binance USD-M public data, 2020-01 .. 2026-09; last price, mark price, funding;
  `research/fullgrid/data.py`), BTC ETH SOL DOGE LTC BCH. Chart bars as `run.frame`.
* Strategies: the rule bot's 36 (`research/entry_study/param_defs`, hash-checked) and DeepSeek's 44
  (`research/fullgrid/ds_defs.py`), **default numbers only** (`run.default_combo`), on 15m, 30m, 1h and 4h (the five
  F15 session strategies have no 4h): 315 strategy x timeframe cells.
* **Unit: every signal is its own trade** from a fixed $5,000 wallet, at the live sizing (rule bot: the live leverage
  group from the signal bar's entry strength, `run.best_flags`; DeepSeek: always "normal"), with fees, slippage,
  funding, isolated-margin liquidation on mark price, through the full grid's kernel (`research/fullgrid/kernel.py`,
  validated against the paper engine). The number is the trade's P&L / $5,000, all costs included. A signal the entry
  check refuses (no size), one still open at the data end, or one without ATR is not a trade and is left out
  (`run.per_trade`). History reads the full grid's per-signal outcome tables (`run.trade_table`); forward recomputes
  them with the same kernel (section 5.2).
* **Reads.** Primary: the live exit `ladder|2` (2 ATR stop, 10% stepped lock; exit index 0). Second, labelled
  everywhere: `tp3R|4` (4 ATR stop, fixed take-profit at 3 R; exit index 80), the exit ANALYSIS 5-1 found least bad.
  Each read is judged on its own; a result names its read.

## 2. Market-state labels (exactly `research/fullgrid/regimes.py` `coin_states` and `tag`)

* **장세**, on the strategy's own chart at the signal bar (`paperbot.dash.tools.regime5y`, data up to that bar's close):
  급변장 = ATR14% in the top 20% of the trailing 365 days (at least 180 days of history); else 추세장 = ADX14 >= 25 and
  |EMA50 slope over 10 bars| >= 0.5 ATR; else 횡보장 = ADX14 < 20; else 보통; 모름 when not known.
* **변동성** (`demobot.regime`): the 15m bar the entry falls in, its ATR14% (from the bar before) against the previous
  90 days: 큼 above the 70th percentile, 작음 below the 30th, else 보통; 모름 when not known.
* **큰 흐름** (above / below the daily EMA200) is not used: it says up or down, not trending or ranging.
* A signal whose 장세 or 변동성 is 모름 is left out of every line of both gates (one common set; counted in the output).

## 3. Strategy classes (`style_map.json`)

From `docs/aibot/STRATEGY_CATALOG_KO.md`, table 한눈에 보기, column 성격, taken as written. For the 36 it is measured
(trend ratio = share of entries in the direction of the previous 20 bars' move: >= 0.6 추세형, <= 0.4 되돌림형, else
섞임); for DeepSeek's 44 it is the catalog's estimate from the rule's shape (*). Three classes:

| catalog label | class | why |
|---|---|---|
| 추세형, 추세형(모멘텀), 추세형(돌파 뒤 지속) | trend | enters with the move |
| 추세형 눌림, 추세형 눌림 + 위치 필터 | trend | waits for a dip but enters with the trend; built for trending markets |
| 반전 뒤 지속 (F9_IFVG, F9_BREAKER) | trend | enters on the pullback after a break, in the direction of the break |
| 되돌림형, 되돌림형 + 위치 필터 | reversion | enters against the move (fades, range ends, divergences) |
| 섞임, 섞임(상대 강약) | other | measured between the two |
| 반전형 (F10_M2022, F12_MSS, F12_MSS_DISP) | other | buys the break that ends the old structure: neither a with-trend entry nor a fade at a range edge, so the friend's split names no market for it |
| 신호 부족 (N14_ICHI_RSI, N21_ST_RSI_ADX) | other | no measured ratio; the rule joins a trend condition to an oversold / overbought one |

Counts: rule bot 19 trend / 5 reversion / 12 other; DeepSeek 26 / 14 / 4; together 45 / 19 / 16. The label wins over
a strategy's name (OBV_S, "OBV 추세형", measured 섞임 0.55: other).

## 4. The gates (at most three)

| gate | trend class enters only when | reversion class only when | other class only when |
|---|---|---|---|
| **G1** 장세 문지기 | 장세 = 추세장 | 장세 = 횡보장 | 장세 = 추세장 |
| **G2** 변동성 문지기 | 변동성 = 큼 | 변동성 = 작음 | 변동성 = 큼 |
| **G3** none blocked | always | always | always |

* **G1** is the friend's rule for the trend and other classes (trend strategies in 추세장, nothing in 횡보장) and the
  owner's addition for the reversion class (발라먹기 in 횡보장). The class lines keep the two apart: the trend and other
  lines test the friend's rule, the reversion line the owner's.
* **급변장 is not allowed for the trend class.** The friend named 추세장 only; in these labels 급변장 is decided first
  (the top 20% of ATR% in a year) and holds violent two-way days as well as trending crashes; at 4h most 급변장 signals
  are refused by the live entry check anyway (`research/fullgrid/DEVIATIONS.md`: S2_ST_ROC 4h BTC, 67 signals, 0
  trades). Adding it later would be a gate chosen after the data, so it stays out. 보통 (the in-between state) is
  blocked for every class: nobody named it.
* **Other class follows the trend class** in both gates: the friend allows nothing in 횡보장, and these strategies are
  not range strategies, so the only market his rule leaves them is 추세장 (in G2, 큼).
* **G2** is G1 in volatility terms: trend strategies need moving markets, reversion strategies quiet ones.
* **G3** is the baseline: each line also reports the mean of all its signals.

## 5. Two evaluations

### 5.1 HISTORY

All 315 cells (80 strategies), six coins, signal bars closing in [2021-01-01 00:00, 2026-10-01 00:00) UTC (the full
grid's select and test periods, same edges; 2020 is left out: too little history for the labels). This exact gate was
never run.
Bootstrap blocks: UTC weeks from Monday (`run.MONDAY0`).

### 5.2 FORWARD

* The rule bot's 36 strategies, default numbers, 15m 30m 1h 4h, six coins: every signal whose bar closes in
  **[2026-10-05 18:35 UTC (the paper v4 run's start), 2026-10-30 00:00 UTC)**, each its own trade as in section 1.
* 1m data: the full archive plus Binance's daily 1m and mark-price klines 2026-10-01 .. **2026-10-30** from
  data.binance.vision (checksum-verified), so every signal has at least one day to finish; a trade still open at
  2026-10-30 24:00 UTC is left out and counted. The whole archive is kept in front, so the labels have their full
  history and are computed exactly as in history. October funding is not in the public archive yet (only a monthly
  file, published in November): it is 0 (as `research/live_interim/replay/live_bt.py`). This touches allowed and
  blocked signals alike in conditions 2, 4 and 5; in condition 3 (allowed mean > 0) the funding a trade would have
  paid or received is missing (usually small for trades of hours), and the result says so.
* The trades are recomputed with the same kernel and the same `research/fullgrid/exchange.json` brackets (pinned; there
  is no option to pass another file), for the window's bars only. The rule bot's own accounts (one position at a time)
  are not the unit; the replay of its rules is (the interim replay matched the live bot's daily results closely,
  `research/live_interim/README_KO.md`).
* Run on or after 2026-10-31 KST, once Binance has published the 2026-10-30 daily files (a day's file appears the
  next UTC day, so from about 10-31 09:00 KST at the earliest; the run stops with "not published yet" before that and is
  simply repeated later). The window does not depend on the day it runs. A run with another `--last-day` is a look,
  marked as such, never the verdict.
* Bootstrap blocks: **UTC days** (about 25). History uses weeks, as the full grid does; with about 3.5 weeks here, four
  blocks cannot give a usable p, so the forward part uses days (market states last hours to days; this is the one
  departure from the brief's week blocks, fixed now).

## 6. Verdict rules (each verdict line, each evaluation, each read)

Verdict lines: G1 and G2, each for **pooled** (all classes) and for **trend**, **reversion**, **other**, timeframes
pooled, on the evaluation's universe (history: all 80; forward: the 36). A line passes when all hold:

1. at least 100 allowed and 100 blocked trades (forward: 30 and 30);
2. allowed mean - blocked mean > 0, with a one-sided block bootstrap p < 0.05: 2,000 resamples of whole blocks
   (section 5), a resample without an allowed or a blocked trade counting against; seed `run._seed("regimegate",
   evaluation, read, gate, universe, group, timeframe)`;
3. allowed mean > 0 (all costs are in the unit);
4. **coin-flip control**: 1,000 draws that each block, in every strategy x timeframe cell, exactly as many signals as
   the gate blocked there, chosen at random (seed `run._seed("regimegate|flip", evaluation, read)`); the gate's
   difference must beat them: (1 + draws with a difference >= the gate's) / 1,001 < 0.05. Because the same number is
   blocked in every cell, the control removes any gain from simply blocking more of a bad strategy or timeframe; what is
   left is the timing the gate adds.
5. **above the coin-flip average, with time clustering**: the gate's difference minus the control's expected
   difference, which is (1/NA + 1/NB) x the sum over cells of (nb x SA - na x SB) / n (na, nb, n: the cell's allowed,
   blocked and all trades; SA, SB: their sums; NA, NB: the line's totals), i.e. the within-cell allowed - blocked
   differences weighted by na x nb / n, must be > 0 with a one-sided block bootstrap p < 0.05: 2,000 resamples of
   whole blocks as in condition 2, a resample without an allowed or a blocked trade counting against; seed
   `run._seed("regimegate|within", evaluation, read, gate, universe, group, timeframe)`.

Why 5 (added in review, before pinning and before any result): random draws are spread evenly in time while market
states last hours to days, so condition 4 alone lets clustered luck through; condition 2 alone lets a mix effect
through (a gate that blocks more of a worse strategy or timeframe). A gate with a mix effect and no timing skill could
pass 2 and 4 together far more often than 5% (a synthetic check with day-long common shocks: condition 4 alone passed
37% of null runs, condition 5 2.5%; `tests/test_regimegate.py`). Condition 5 holds the mix fixed per cell, as the
control does, and keeps the clustering by resampling whole blocks.

Reported, never verdicts: every line per timeframe; in history the rule bot only and DeepSeek only; each gate with the
trend and reversion markets swapped (G1s, G2s: if the swapped gate also "works", the state helps every strategy and the
style match is not the reason); per class and state the trades, win rate and mean; per year the sign of allowed -
blocked. G3 appears as each line's all-signal mean.

## 7. Multiple lines

Each evaluation has 8 verdict lines per read (16 with both reads). Some history lines can pass by chance; that is why a
candidate needs the same line to pass in history **and** forward (independent data): for a gate with no timing effect,
condition 5 alone passes about 5% of the time in each evaluation, so about 0.05 x 0.05 per line, about 0.04 false
candidates over the 16 lines (the lines share data, so this is a rough figure).

## 8. What a result means

| HISTORY line | FORWARD line | result |
|---|---|---|
| pass | pass | **candidate filter**: offered to the AI bot / team design as a market filter for that class (pooled: for every class), **paper only**, under the read it passed with |
| pass | fail | not confirmed; recorded. A second forward look needs its own pre-registration written before its data |
| fail | pass | one month only; recorded, not a candidate |
| fail | fail | fail; recorded |

* A candidate changes nothing by itself: the rule bot's 36, its accounts and its day-30 verdict are untouched, and no
  real money follows from this test. Putting a candidate filter into a paper design is the owners' decision.
* A forward fail with about 25 days of data does not prove the gate useless; it means this test could not show it.
  The power is low: the context study above estimated that live signals of all 36 need about 26-36 days to confirm a
  0.10 R filter and about 165-224 days for a 0.04 R one (its five-year size), so only a large effect can pass forward.
  A line that fails for too few trades (condition 1) is marked so in `decision.json` and the summary ("건수 부족"):
  it was not testable in that evaluation, and it is still not a candidate.
* Per-timeframe numbers can suggest where a filter works, but a timeframe-specific filter would need its own forward
  test.
* Every result, pass or fail, goes into the results file and the owners' summary.

## 9. DeepSeek money

Owners' D11: means, sums and differences of any line holding a DeepSeek trade stay out of every output file (counts, win
rates, p-values and pass flags only), unless `FULLGRID_DS_MONEY=1`. The pooled history line holds DeepSeek trades, so its
money figures are hidden by default; the rule-bot-only lines and the whole forward part show money.

## 10. Code and running

`gate.py` (this folder), reusing `research/fullgrid/run.py`, `regimes.py` and `kernel.py` read-only; its pure parts
(style map coverage, gates, bootstraps, control, verdicts, decision, DeepSeek hiding, the pin check) are checked on
hand-made numbers by `tests/test_regimegate.py`.

The pin, `PREREG_REGIMEGATE.sha256` (paths from this folder, so `sha256sum -c PREREG_REGIMEGATE.sha256` works here),
lists exactly: `PREREG_REGIMEGATE.md`, `gate.py`, `style_map.json`, the label code `../fullgrid/regimes.py`,
`../../paperbot/dash/tools/regime5y.py` and `../../demobot/regime.py`, the brackets `../fullgrid/exchange.json`, and
the leverage-group edges `../../paperbot/quality_edges.json`. `gate.py` refuses `history` and `forward` unless the pin
lists exactly these and every hash matches, and unless the full grid's own preflight passes (`run.preflight`: its
`PREREG.sha256`, the hash-locked strategy and strength definitions, so a refused strength definition cannot silently
size every signal "normal"). Each output also records the commit and the hashes (`code`).

    python3 research/regimegate/gate.py history --data <fg1m> --work <fgwork> --out <OUT> [--procs N]
    python3 research/regimegate/gate.py forward --data <fg1m> --fwd <FWD> --out <OUT> [--procs N]
    python3 research/regimegate/gate.py report  --out <OUT>

Outputs: `OUT/history.json`, `OUT/forward.json`, `OUT/decision.json` (when both exist and the forward window is the
registered one) and `OUT/RESULTS_KO.md`. History reads the full grid's outcome tables and recomputes only the default
signals and the labels; forward downloads 360 daily files into `FWD/raw`, keeps each window's data in
`FWD/<last day>/` (1m, frames, outcomes; the 1m data ends exactly on that day) and recomputes the window's trades. A
part made for another window is refused, so a look and the verdict never mix. Neither run is timed yet; both work per
coin and timeframe in a worker pool, and history is started only when the machine is otherwise free.
