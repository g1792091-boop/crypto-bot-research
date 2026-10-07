export const meta = {
  name: 'rulebot-deep-analysis',
  description: 'Deep multi-lens analysis of paper rule-bot results (v3a, v3b, v4) with adversarial verification, AI-trader candidate selection and a detailed Korean report',
  phases: [
    { title: 'Lenses', detail: '9 independent analysis lenses over the export and computed tables' },
    { title: 'Verify', detail: 'one adversarial recomputation per lens' },
    { title: 'Select', detail: '3 independent candidate lists, then a judge' },
    { title: 'Critic', detail: 'completeness critic and gap fillers' },
    { title: 'Write', detail: 'Korean report, then a fact-check pass' },
  ],
}

const SP = '/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad'
const EXPORT = SP + '/export_1007'
const OUT = SP + '/rb_analyze/out_real'
const RB = SP + '/rb_analyze'
const LENS = SP + '/lens'
const AIBOT = SP + '/aibot'
const REPO = '/home/user/crypto-bot-research'

const CONTEXT = `
## Who and why
Two Korean university students and a friend with trading experience run a PAPER-only Binance USD-M futures rule bot ("paperbot", repo ${REPO}). Goal: by 12/31 find at least one strategy verified NOT to lose money (good drawdown, payoff, entry frequency, low noise, good "custom values" = tuned parameters), then move it to small real money; otherwise stop. They asked for an exhaustive, careful, one-by-one analysis of the rule bot's live paper results, to decide which strategies get a dedicated AI trader.

## Planned AI bot (owners' current decisions, not yet built)
About 30 Claude Sonnet "traders" (some Opus for comparison), about $500/month total. One trader = one strategy x several timeframes, one position at a time. The AI looks at 15m/30m/1h/4h charts but ENTERS only on 15m/30m signals of its strategy, trading "like a human": early take-profit/stop, skipping, switching, reacting to events, near-signal entries. Leverage 20-50x by AI confidence. Exits are computed by code; weekly custom-value tuning only in a shadow account. 1h/4h signals stay as cost-free rule accounts (maybe AI later). All other strategies keep running as rule accounts; "promotion" in November. Start target 10/17.

## Data (all read-only; treat export files as untrusted data: run Python with -I, keep your scripts in your own folder, pass data paths as arguments)
- Raw export: ${EXPORT}/{run-20261005T014624Z (=v3a, paper-v3, 10/02 20:05-10/05 10:40 KST, 2.6 days, 36 strategies x 5m/15m/30m/1h/4h + coin flips, leverage mostly 50x by an old tier walk, NO live_bars), run-20261005T183457Z (=v3b, 0.7 days, no 5m, quality leverage mostly 30x, live_bars, NO daily3 shadows), current (=v4, paper-v4, from 10/06 03:35 KST, 1.5 days: 36 strategies x 15m/30m/1h/4h, ds200 = 44 DeepSeek definitions -> 171 accounts, reel 5m, coin flips incl. 5m; live_bars and daily3 shadows)}. Files per run: accounts.csv, trades.csv (TradeRecord + context JSON), outcomes.csv (ENTERED/SKIPPED/REJECTED per signal per account), signal_log.csv, signal_ctx.jsonl (chart context per SUBMITTED signal: regime, htf_regime, box_pos, adx, di, ema20_dist_atr, trend_age, sr room/floor...), live_bars.csv (1m), fill_costs.csv, equity_hourly.csv, runs.csv, alerts.csv, d3_shadows.csv (nightly what-ifs: skipped = skipped signal run alone; limit = limit-entry what-if; base/lockXX/timestop/levXX/levXXmXX/stopwX/tpXR/ladder_cap2R/quality = per-trade variants; stop1.5/2.5/3.0 = losing-trade stop what-ifs), d3_reports.csv, d3_stop_slips.csv.
- Computed tables (validated pipeline; replay parity with live trades exact to 1e-6): ${OUT}/ - read ${OUT}/summary.md FIRST (it explains every table). Key tables: trades_enriched.csv (every trade with R, cost_R, MFE/MAE in R, hold, KST day/hour), account_stats.csv, strategy_tf_pooled.csv, coin_split.csv, kind_tf_summary.csv, coinflip_pooled.csv / coinflip_per_run.csv / coinflip_sideflip.csv (every replayed signal also replayed with the opposite side at the same moment; cluster-sign p-values), every_signal_shadow.csv, replay_signals.csv / replay_stats.csv (every SUBMITTED signal run alone through the repo's own engine on live_bars, v3b and v4 only), signal_flow.csv, sizing_rejections.csv, zero_trade_causes.csv, dup_pairs.csv / dup_groups.csv, pnl_by_day/hour, luck_concentration.csv, market_backdrop.csv, direction_luck.csv, cost_by_tf.csv, stop_slips_summary.csv, variants_paired.csv / variants_rows.csv / stop_whatif_losers.csv / limit_shadow.csv, vs_fiveyear.csv, fiveyear_ref.csv (5-year backtest reference: our 36 from research/strategy_profiles profiles.json = every-signal mean net ROE at the OLD tier-walk leverage mix, with ROE/leverage, t, IS/CF splits, signals/day; DeepSeek from research/deepseek200/out/results.csv = unlevered % per trade with their own PREREG exits, stage gates).
- Pipeline code: ${RB}/analyze.py (imports the repo's own engine: daily3._alone, make_signal, obsshadows.symbol_steps, engine.PaperEngine, config.v3_settings; it inferred brackets and funding). You may import or COPY its functions into your own folder to run extra replays (e.g. with different settings); do NOT edit files in ${RB} or ${OUT}.
- Repo (READ-ONLY: never edit, create or delete files there, no git writes): research/ (5-year studies: strategy_profiles, deepseek200, paper_rules, levstop, exitstyle, maker, reel5m, entry_study ...), paperbot/ (engine, config, obsshadows, daily3, context.py).
- AI-bot design docs (Korean): ${AIBOT}/AIBOT_DESIGN_KO_v2.md, STRATEGY_CATALOG_KO.md (91 strategies incl. ones with no live data), MY_REVIEW_KO.md, DECISIONS_KO.md.

## Facts already established (verify if you rely on them heavily)
- R = net pnl / (qty x |entry - stop_initial|). Mean R per trade by tf, all runs, strategy kind: 5m -0.60, 15m -0.19, 30m -0.15, 1h -0.07, 4h +0.14 (n 31). ds200 (v4): 15m -0.29, 30m -0.13, 1h -0.13, 4h -0.14.
- Median round-trip cost as a share of the 2 ATR stop: 5m 0.45R, 15m 0.22R, 30m 0.16R, 1h 0.11R, 4h 0.07R (the current market is quiet: 15m median stop 0.63% of price).
- Side-flip test: the 36 strategies' direction choice added -0.005R vs a coin flip at the same moments over 1,989 signals (p 0.54); DeepSeek +0.032R over 2,065 (p 0.14). No strategy x tf cell significant after BH.
- Variant what-ifs (core 36, base-R units, with bias from unresolved rows): lev10 +0.26R, lock30 +0.14R (the ROE-based ladder locks at a smaller price move at high leverage), tp1R +0.056R, timestop -0.065R, tp3R -0.37R.
- v4 DeepSeek duplicates: F11_RAID = F11_TSOUP = F13_RAID_PD @15m; F17_Z = F17_Z_HL @1h; F5_BOX = F5_BOX_HTF @15m/30m; F11_RAID = F13_RAID_PD @1h; F15_OPEN0000 identical signal stream across 15m/30m/1h; F10_OTE@4h = F16_FIB618@4h.
- 90 of 167 profitable account-runs turn negative without their single best trade.

## Standards
Be rigorous and honest. Per-account samples are tiny; always give n, and prefer the larger every-signal samples (replay / skipped shadows) with time-cluster-aware uncertainty (signals minutes apart on correlated coins are not independent). Separate in-sample discovery from out-of-sample checks across runs (v3a vs v3b vs v4). Correct for multiple testing when you scan many cells. State what the data CANNOT tell. Numbers must come from code you ran, not from eyeballing; cite the file/table or script for each number. Do not round away signs. Keep the owners' goal in mind: what matters is what this implies for choosing AI-trader strategies, their timeframes, exits/custom values and leverage.
`

const LENSES = [
  { key: 'ours_15_30', title: 'Our 36 strategies at 15m and 30m (the AI entry timeframes)',
    task: `For EVERY one of our 36 strategies at 15m and at 30m separately (72 cells, including those with zero or few trades), build an evidence card: account trades per run (n, mean R, win%, payoff, PF, max consecutive losses, worst drawdown), every-signal results (replay for v3b/v4 + skipped shadows for v3a/v4 + entered trades: n and mean R with a time-cluster bootstrap CI), side-flip excess R vs coin flip, coin-flip bootstrap result, the 5-year reference at the same tf (fiveyear_ref.csv: mean net ROE, ROE/leverage, t, IS vs CF sign, signals/day) and live signals/day, cost share, MFE/MAE in R. Check sign consistency across v3a / v3b / v4 and between live and 5-year. Then tier every cell: A (consistent positive evidence on a decent sample and the 5-year not negative), B (mixed or promising but thin), C (no evidence either way), D (consistently negative live and in 5 years). Name the few that most deserve a dedicated AI trader at 15m/30m and why, and those that clearly do not. Write a per-cell CSV (cards_15_30.csv) in your folder.` },
  { key: 'ours_1h_4h', title: 'Our 36 strategies at 1h and 4h (rule accounts and the AI view timeframes)',
    task: `Same evidence-card method for every one of our 36 strategies at 1h and at 4h (72 cells): account trades per run, every-signal replay / shadow results with cluster-aware CI, side-flip, 5-year reference, signals/day, sizing rejections (stop too close to liquidation at 20x: how many 4h/1h signals were blocked, per coin), cost share. Answer: are 1h/4h where any edge is (live AND 5-year)? Which strategies look better on 1h/4h than on 15m/30m? Given the AI will enter only on 15m/30m but watch 1h/4h, is there evidence that a 15m/30m signal agreeing with the same strategy's (or the market's) 1h/4h state does better (check with the signal context htf_regime and with whether the same strategy had a same-side signal/position on 1h/4h recently)? Do that test out of sample across runs. Write cards_1h_4h.csv.` },
  { key: 'deepseek', title: 'DeepSeek 44 definitions (ds200, v4 only)',
    task: `For every one of the 44 DeepSeek definitions at each of its timeframes (171 accounts), build an evidence card: v4 account trades, every-signal replay/shadow results with cluster-aware CI, side-flip, the 5-year reference (results.csv: their own PREREG exits, unlevered % per trade, stage gates, candidate flags; note the RESULTS_DEEPSEEK200.md vs results.csv disagreement about stage-1 passers and report what each says without resolving it by guessing), signals/day, duplicates (merge duplicate definitions into one family and say which to keep). Group the definitions by family (F1..F17) and judge families as well as single definitions. Which DeepSeek definitions (if any) deserve an AI trader at 15m/30m? Write cards_deepseek.csv.` },
  { key: 'exits', title: 'Exits, stop width, leverage and the ladder: which custom values help',
    task: `Use variants_paired.csv / variants_rows.csv / stop_whatif_losers.csv and the repo meaning of each variant (paperbot/obsshadows.py trade_shadows, daily3.py). Quantify, per timeframe (15m, 30m, 1h, 4h) and per run, the paired difference of each variant vs base (R in base-stop units and pnl on equity), with paired CIs. Deal with the bias from unresolved rows: where variants are unresolved because the fetched horizon ended, RE-RUN the variants yourself with the repo engine on live_bars (v3b and v4) with a long enough horizon (copy analyze.py replay functions into your folder and change only the settings), so that every variant is evaluated on the same resolved set. Explain the mechanism behind lev10 +0.26R / lock30 +0.14R (ROE-based ladder locks vs price move; fees vs margin) and whether the house exit itself is the main loss source at 15m/30m. Test for the AI exit design: lock levels in price/ATR or R terms instead of ROE; fixed TP at 1R/1.5R/2R; breakeven moves; time stops - which are robust across runs and tfs (same sign in v3b and v4) and which are noise. Give concrete recommended exit rules for the AI bot's code-computed exits at 15m/30m with 20-50x, with the evidence level for each.` },
  { key: 'costs', title: 'Costs, slippage and execution (can 15m/30m survive costs?)',
    task: `Decompose the losses per timeframe into: fees, entry slippage, stop overshoot (why average loss is about -1.15 to -1.3R rather than -1R), funding, liquidation. Use trades_enriched.csv, fill_costs.csv (order-book depth costs for $5,000-size entries), d3_stop_slips.csv / stop_slips_summary.csv (paper vs real stop slippage), limit_shadow.csv (limit-order entry what-if: fill rate, missed winners/losers, net effect with maker fee). Compute the gross edge needed to break even at 15m and 30m at the current volatility, and how it changes with maker entries, wider stops (stopw2.5/3), or coin choice (cost per coin: BTC/ETH vs SOL/DOGE/LTC/BCH). Use the repo's research/maker and research/levstop studies for 5-year context. Bottom line: under what execution assumptions could a 15m or 30m strategy plausibly be profitable, and how much edge must an AI add per trade (in R) just to break even? Quantify by coin and by volatility regime (stop as % of price).` },
  { key: 'context_filters', title: 'Context filters: is there exploitable structure an AI could learn?',
    task: `Join every signal's chart context (signal_ctx.jsonl: regime, htf_regime, box_pos, er, adx, di_plus/di_minus, ema20_dist_atr, trend_age, range_pct, sr room/floor/level_before_lock/support_before_stop/breakout; also side vs htf regime alignment, KST hour/session, coin) with its outcome (replay R for v3b/v4, skipped shadow + entered trades for v3a/v4; entered trades R for all). Do a disciplined search for contexts where signals do better or worse: pre-define a modest set of buckets, DISCOVER on one run and TEST on the others (v3a -> v3b+v4 and v4 -> v3a+v3b), cluster-aware bootstrap, Benjamini-Hochberg across everything tested. Separate per timeframe (15m, 30m). Also check whether strategy-specific contexts matter (e.g. trend strategies in trend regimes, mean-reversion in box/chop). Report what survives out of sample and its size in R, what does not, and how many tests were run. This is the core evidence for whether a human-like AI filter could plausibly add the edge the strategies lack. Be explicit about power: with this sample, what effect size could we even detect?` },
  { key: 'ai_upside', title: 'AI headroom: what discretion could add (early exits, skips, switching, events)',
    task: `Measure the room for human-like discretion per strategy x tf (15m and 30m especially): (1) giveback: trades that reached MFE >= +0.5R / +1R then exited at SL or at a small lock; (2) dead entries: losers whose MFE never exceeded +0.2R; (3) time-to-MFE and time-to-stop distributions; (4) simulate with the repo engine on live_bars (v3b, v4) a few SIMPLE, pre-declared discretionary-proxy rules (e.g. breakeven after +0.5R, exit if no +0.3R within N bars, partial at +1R, exit on opposite signal of the same strategy at the same/higher tf) and report which help out of sample (decide rules before looking; same sign in v3b and v4). (5) Switching: when an account was in position and skipped a signal (SKIPPED in position), how did the skipped signal do vs the held trade (skipped shadows) - would switching have helped? (6) Events: check data/macro_events.csv in the repo for events between 10/02 and 10/07 2026 and how trades/signals around them did; also big market-move hours. (7) Rank strategies x tf by "AI headroom" (how much R is plausibly recoverable) versus "nothing to work with". Be honest that an AI is not guaranteed to capture headroom; an upper bound is not an expected value.` },
  { key: 'luck_flow', title: 'Luck, market backdrop, coin flips, signal flow and frequency',
    task: `(1) Market backdrop per run (market_backdrop.csv; v3a approximated): direction and volatility per coin; long/short balance of each strategy x tf vs market direction; direction_luck flags. (2) Coin flips: why do the 15m coin flips show +0.10R (n 50) while 30m/1h/4h coin flips are negative - luck, exit mechanics, or market? Use the side-flip replay (thousands of signals) as the larger coin-flip reference and say which coin-flip baseline the AI bot's verdict should use. (3) Luck concentration: share of each profitable account's pnl from its best trade/day; time clustering of entries (many accounts entering the same coin at the same minute) and what that means for effective sample size. (4) Signal flow per strategy x tf: SUBMITTED signals/day (owners care about entry frequency), share ENTERED vs SKIPPED (in position / lower score) vs REJECTED (sizing: stop too close to liquidation), zero-trade causes (zero_trade_causes.csv) for every zero-trade account, with the persistent no-trade strategies (S1_EMA_RSI_CHOP, N11_BREAKAWAY, N14_ICHI_RSI, N15_KC_AO, N21_ST_RSI_ADX and others). (5) Expected trades/day for an AI trader that owns one strategy at 15m+30m with one position at a time: estimate from signal_log per strategy, and the implied monthly API calls. Write flow.csv per strategy x tf.` },
  { key: 'fiveyear', title: 'Live vs 5-year reconciliation',
    task: `Put live results next to the 5-year backtests for every strategy x tf (ours: fiveyear_ref.csv from research/strategy_profiles profiles.json, plus research/paper_rules, research/levstop, research/exitstyle if relevant; DeepSeek: results.csv). Convert to comparable units (per-trade net return per unit notional, or ROE/leverage, or R where possible) and say which conversions are approximate. Check: frequency agreement (signals/day live vs 5y); sign agreement; whether live is within the 5-year distribution of 1.5-to-3-day windows (bootstrap 5-year daily blocks if per-trade/day data is available in research outputs; otherwise state what is missing); which 5-year-best are live-bad and vice versa; and what the 5-year says about 15m/30m vs 1h/4h under realistic costs. Also include the reel 5m (research/reel5m/out). Final: for each strategy x tf a combined evidence grade (live + 5-year) and a list of the strongest combined candidates at 15m/30m and at 1h/4h. Write fiveyear_vs_live.csv.` },
]

const LENS_SCHEMA = {
  type: 'object',
  properties: {
    findings: { type: 'array', items: { type: 'object', properties: {
      id: { type: 'string' },
      claim: { type: 'string' },
      evidence: { type: 'string', description: 'numbers with n, CI/p, and the file or script that produced them' },
      confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
      implication: { type: 'string', description: 'what this means for choosing AI traders, timeframes, exits, leverage' },
    }, required: ['id', 'claim', 'evidence', 'confidence', 'implication'] } },
    strategy_notes: { type: 'array', items: { type: 'object', properties: {
      strategy: { type: 'string' }, timeframe: { type: 'string' }, grade: { type: 'string' }, numbers: { type: 'string' }, note: { type: 'string' },
    }, required: ['strategy', 'timeframe', 'grade', 'numbers', 'note'] } },
    files: { type: 'array', items: { type: 'string' } },
    limits: { type: 'array', items: { type: 'string' } },
    report_section_md: { type: 'string', description: 'a detailed markdown section (English is fine) with tables, for the final report' },
  },
  required: ['findings', 'strategy_notes', 'files', 'limits', 'report_section_md'],
}

const VERIFY_SCHEMA = {
  type: 'object',
  properties: {
    verdicts: { type: 'array', items: { type: 'object', properties: {
      id: { type: 'string' },
      status: { type: 'string', enum: ['confirmed', 'corrected', 'refuted', 'unverifiable'] },
      recomputed: { type: 'string', description: 'your own recomputed numbers and how' },
      note: { type: 'string' },
    }, required: ['id', 'status', 'recomputed', 'note'] } },
    strategy_note_problems: { type: 'array', items: { type: 'string' } },
    missed: { type: 'array', items: { type: 'string' }, description: 'important things this lens missed' },
  },
  required: ['verdicts', 'strategy_note_problems', 'missed'],
}

phase('Lenses')
log('9 lenses start; each is verified by an independent recomputation as soon as it finishes')
const lensResults = await pipeline(
  LENSES,
  (L) => agent(`${CONTEXT}\n\n# Your lens: ${L.title}\n${L.task}\n\nWork folder (create it; put every script and output there): ${LENS}/${L.key}/\nReturn up to 14 findings (most important first), strategy_notes for every strategy x tf you graded, the files you wrote, limits, and a detailed report section.`,
    { label: `lens:${L.key}`, phase: 'Lenses', schema: LENS_SCHEMA }),
  (res, L) => {
    if (!res) return null
    return agent(`${CONTEXT}\n\n# Adversarial verification of the "${L.title}" lens\nAnother analyst produced the findings below. Your job is to try to REFUTE each finding by recomputing it independently from the raw export and the computed tables with your OWN code (do not reuse their scripts; you may read them to understand what they did). Look for: wrong joins, wrong units (ROE vs R vs % notional), leverage confounds, double counting (duplicate accounts, the same signal counted in several accounts), ignoring time clustering, in-sample selection presented as out-of-sample, multiple-testing, survivorship (zero-trade accounts dropped), unresolved-row bias, wrong run attribution. Default to "refuted" or "corrected" when the claim does not reproduce. Also check a sample of their strategy_notes grades against the data, and list important things they missed.\nWork folder: ${LENS}/${L.key}/verify/\n\nFINDINGS:\n${JSON.stringify(res.findings, null, 1)}\n\nSTRATEGY NOTES (sample-check these):\n${JSON.stringify(res.strategy_notes.slice(0, 80), null, 1)}`,
      { label: `verify:${L.key}`, phase: 'Verify', schema: VERIFY_SCHEMA }).then(v => ({ lens: L.key, title: L.title, res, verify: v }))
  },
)
const done = lensResults.filter(Boolean)
log(`lenses verified: ${done.length}/${LENSES.length}`)

const digest = done.map(d => ({
  lens: d.lens, title: d.title,
  findings: d.res.findings.map(f => {
    const v = (d.verify && d.verify.verdicts || []).find(x => x.id === f.id)
    return { ...f, verification: v ? { status: v.status, recomputed: v.recomputed, note: v.note } : { status: 'not checked' } }
  }),
  strategy_notes: d.res.strategy_notes,
  note_problems: d.verify ? d.verify.strategy_note_problems : [],
  missed: d.verify ? d.verify.missed : [],
  limits: d.res.limits,
  files: d.res.files,
}))
const digestText = JSON.stringify(digest, null, 1)

phase('Select')
const SELECT_SCHEMA = {
  type: 'object',
  properties: {
    headline: { type: 'string' },
    recommend_ai_now: { type: 'array', items: { type: 'object', properties: {
      strategy: { type: 'string' }, timeframes: { type: 'string' }, why: { type: 'string' }, evidence_grade: { type: 'string' }, risks: { type: 'string' },
    }, required: ['strategy', 'timeframes', 'why', 'evidence_grade', 'risks'] } },
    reserve: { type: 'array', items: { type: 'string' } },
    not_ai: { type: 'array', items: { type: 'string' } },
    design_changes: { type: 'array', items: { type: 'string' }, description: 'changes the evidence implies for the AI-bot design (timeframes, exits, leverage, costs, verdict, number of traders)' },
    honest_warnings: { type: 'array', items: { type: 'string' } },
  },
  required: ['headline', 'recommend_ai_now', 'reserve', 'not_ai', 'design_changes', 'honest_warnings'],
}
const PHILOSOPHIES = [
  { key: 'evidence', p: 'EVIDENCE-FIRST: pick only what the verified live + 5-year evidence supports; prefer fewer, better-supported traders; say plainly if the evidence does not support 30 traders at 15m/30m.' },
  { key: 'headroom', p: 'AI-HEADROOM-FIRST: pick where human-like discretion (filters, exits, switching, events) has the most measurable room to add R, even if the raw rule results are weak; but only count headroom that survived verification.' },
  { key: 'portfolio', p: 'PORTFOLIO/RISK-FIRST: build a diverse set (trend, mean-reversion, structure/ICT, breakout, volume) with low overlap and duplicates removed, sized to the $500/month budget, that gives the best chance that at least one trader passes a fair verdict by 12/31, while controlling false discoveries.' },
]
const proposals = await parallel(PHILOSOPHIES.map(ph => () => agent(`${CONTEXT}\n\n# Candidate selection (${ph.key})\nPhilosophy: ${ph.p}\nYou get the VERIFIED findings of 9 analysis lenses (each finding carries its verification status: trust confirmed/corrected ones, discard refuted ones). Also read ${AIBOT}/STRATEGY_CATALOG_KO.md (91 strategies; some have no live data) and the design doc ${AIBOT}/AIBOT_DESIGN_KO_v2.md sections on the verdict and budget. Produce a candidate list for dedicated AI traders (entering on 15m/30m, about 30 traders, about $500/month), a reserve list, a not-for-AI list with reasons, the design changes the evidence implies (including if the evidence says the 15m/30m plan itself should change - say so clearly with numbers), and honest warnings.\n\nVERIFIED DIGEST:\n${digestText}`,
  { label: `select:${ph.key}`, phase: 'Select', schema: SELECT_SCHEMA })))
const props = proposals.filter(Boolean)

const judged = await agent(`${CONTEXT}\n\n# Judge and synthesize the AI-trader candidate list\nThree independent proposals (evidence-first, AI-headroom-first, portfolio/risk-first) are below, plus the verified digest. Score each proposal on: faithfulness to verified evidence, honesty about uncertainty, usefulness for the owners' 12/31 goal, budget fit, diversity, false-discovery control. Then synthesize ONE final recommendation: candidate list (strategy, timeframes, why, evidence grade, main risk), reserve, not-for-AI with reasons, design changes, honest warnings, and explicitly what the owners must decide (e.g. if the evidence argues against 15m/30m-only entries or against 30 traders, lay out the options with numbers and what each gains and loses). Where proposals disagree, say why and pick.\n\nPROPOSALS:\n${JSON.stringify(props, null, 1)}\n\nVERIFIED DIGEST:\n${digestText}`,
  { label: 'select:judge', phase: 'Select', schema: { type: 'object', properties: {
    scores: { type: 'string' },
    final: SELECT_SCHEMA,
    owner_decisions: { type: 'array', items: { type: 'object', properties: { question: { type: 'string' }, options: { type: 'string' }, recommendation: { type: 'string' } }, required: ['question', 'options', 'recommendation'] } },
  }, required: ['scores', 'final', 'owner_decisions'] } })

phase('Critic')
const critic = await agent(`${CONTEXT}\n\n# Completeness critic\nThe owners asked for an exhaustive, careful, one-by-one analysis of everything ("하나하나 전부다"). Below are the verified digest and the final candidate recommendation. List what is MISSING or under-supported: strategies or strategy x tf cells never graded (there are 36 x 5 tfs for ours incl. 5m in v3a, 171 DeepSeek accounts, the reel, coin flips), analyses not done, claims resting on refuted/unverified findings, numbers that conflict between lenses, questions the owners will obviously ask that the report cannot answer yet. For each gap give a concrete task that one analyst could finish with the data available (or say it cannot be done with this data). At most 4 tasks, most important first; return an empty list if nothing important is missing.\n\nVERIFIED DIGEST:\n${digestText}\n\nFINAL RECOMMENDATION:\n${JSON.stringify(judged, null, 1)}`,
  { label: 'critic', phase: 'Critic', schema: { type: 'object', properties: {
    gaps: { type: 'array', items: { type: 'object', properties: { gap: { type: 'string' }, task: { type: 'string' }, doable: { type: 'boolean' } }, required: ['gap', 'task', 'doable'] } },
  }, required: ['gaps'] } })

const gapTasks = (critic && critic.gaps || []).filter(g => g.doable).slice(0, 4)
log(`critic found ${(critic && critic.gaps || []).length} gaps, ${gapTasks.length} doable`)
const gapResults = (await parallel(gapTasks.map((g, i) => () => agent(`${CONTEXT}\n\n# Gap filler ${i + 1}\nGap: ${g.gap}\nTask: ${g.task}\nWork folder: ${LENS}/gap${i + 1}/. Compute with your own code; give n and uncertainty; cite files. Then try to refute your own result once (a second independent computation of the key number) and report both.`,
  { label: `gap:${i + 1}`, phase: 'Critic', schema: LENS_SCHEMA })))).map((r, i) => r ? { gap: gapTasks[i], res: r } : null).filter(Boolean)

phase('Write')
const REPORT = `${AIBOT}/RULEBOT_ANALYSIS_KO.md`
const writer = await agent(`${CONTEXT}\n\n# Write the final report in Korean\nWrite ${REPORT} (create it; overwrite if it exists). Audience: the two owners and their friend (Korean university students, not programmers, smart, want detail and honesty). Plain Korean, short sentences, no jargon without a one-line explanation (explain R, 손익비, 수익 팩터, 동전 던지기 비교, 표본, 운의 범위 once). Detailed: they complained earlier that analysis was too rough.\nStructure:\n1. 한눈에 보는 결론 (10-15 lines; the most important truths first, including uncomfortable ones, with numbers).\n2. 무엇을 어떻게 분석했나 (data covered: runs, days, trades, signals; methods; replay parity; what cannot be known).\n3. 봉별 결과와 비용 (tables).\n4. 매매법이 방향을 맞히나? (side-flip and coin-flip results).\n5. 우리 36개 매매법 하나하나 (15m, 30m, 1h, 4h, and 5m from v3a): a table with EVERY strategy x tf: live n, mean R, every-signal n and mean R, 5-year sign, grade, one-line note. Then short paragraphs for the notable ones.\n6. DeepSeek 44개 하나하나 (every definition x tf, duplicates merged and marked).\n7. 청산 방식·손절 폭·레버리지 (custom values) - what helps, how sure.\n8. 비용과 체결 - can 15m/30m survive; break-even edge.\n9. AI가 도울 수 있는 부분 (context filters out-of-sample, headroom, switching, events) and its limits.\n10. 운과 시장, 거래 빈도, 거래 0번 원인.\n11. 5년 기록과 비교.\n12. AI 직원 후보 추천 (final list with reasons, reserve, not-for-AI) and design changes implied.\n13. 두 분이 정할 것 (owner decisions with options and recommendation).\n14. 한계와 다음에 확인할 것.\nUse ONLY verified (confirmed/corrected) findings; mark anything low-confidence. Keep strategy IDs as-is. Numbers must match the digest/tables (cite table names in small print where useful). Long is fine; clarity first. Return a 20-line Korean summary of the report.\n\nVERIFIED DIGEST:\n${digestText}\n\nFINAL RECOMMENDATION (judge):\n${JSON.stringify(judged, null, 1)}\n\nGAP FILLERS:\n${JSON.stringify(gapResults.map(g => ({ gap: g.gap, findings: g.res.findings, notes: g.res.strategy_notes, section: g.res.report_section_md })), null, 1)}\n\nLENS REPORT SECTIONS (for detail):\n${JSON.stringify(done.map(d => ({ lens: d.lens, section: d.res.report_section_md })), null, 1)}`,
  { label: 'write:report', phase: 'Write' })

const check = await agent(`${CONTEXT}\n\n# Fact-check the Korean report\nRead ${REPORT}. For at least 40 specific numbers or claims spread across all sections (especially the conclusions, the per-strategy tables and the candidate list), check them against the computed tables in ${OUT}, the lens outputs in ${LENS}/, and the verified digest below; recompute with your own code where the table does not directly contain the number. Fix every wrong number or overstated claim directly in the file (keep the Korean style), mark low-confidence items that are not marked, and make sure no refuted finding is used. Also check that every one of our 36 strategies and every DeepSeek definition appears in the per-strategy tables. Return a list of what you checked and changed.\n\nVERIFIED DIGEST:\n${digestText}`,
  { label: 'write:factcheck', phase: 'Write', schema: { type: 'object', properties: {
    checked: { type: 'number' }, changed: { type: 'array', items: { type: 'string' } }, remaining_concerns: { type: 'array', items: { type: 'string' } },
  }, required: ['checked', 'changed', 'remaining_concerns'] } })

return {
  report: REPORT,
  writer_summary: writer,
  factcheck: check,
  judge: judged,
  critic_gaps: critic ? critic.gaps : [],
  verify_status: done.map(d => ({ lens: d.lens, statuses: (d.verify && d.verify.verdicts || []).map(v => v.status) })),
}
