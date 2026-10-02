# Entry-bot research: open-source references (verified 2026-10-02)

Stars, license and last push come from the GitHub search API on 2026-10-02. The GitHub-reported license is shown;
"Other" means GitHub could not classify it, so read the LICENSE file before reusing anything.
Rule for us: **re-implement ideas only**. Do not copy code from GPL/AGPL repos (freqtrade, OctoBot, pypbo) or from
"Other"-licensed repos (mlfinlab, CryptoTrade). MIT/BSD/Apache code can be used as a dependency with attribution.
Doc sites (freqtrade.io, riverml.xyz) were blocked by the egress proxy. I checked those details through web search
snippets and the GitHub pages, but I could not read the full pages.

## Top 10 (what to build from each)

| # | Repo | Stars | License | Last push | Technique to re-implement |
|---|------|------:|---------|-----------|---------------------------|
| 1 | online-ml/river | 6.1k | BSD-3 | 2026-09 | Per-bar `learn_one/predict_one` meta-label model; `drift.ADWIN`/`PageHinkley` on the outcome stream to reset or shrink stats when the regime changes; `bandit.ThompsonSampling` and `LinUCBDisjoint` |
| 2 | skfolio/skfolio | 2.5k | BSD-3 | 2026-10 | `model_selection.CombinatorialPurgedCV(n_folds, n_test_folds, purged_size, embargo_size)` and `WalkForward(purged_size)` to validate policy changes without leakage |
| 3 | BlackArbsCEO/Adv_Fin_ML_Exercises | 2.0k | MIT | 2022-12 | Clean AFML ch.3 code: CUSUM event filter, vol-scaled triple barrier (`get_events`/`get_bins`), meta-label = side known, learn size/take-skip |
| 4 | freqtrade/freqtrade (FreqAI) | 55.0k | **GPL-3.0** | 2026-10 | Ideas only: sliding window `train_period_days`, retrain cadence `live_retrain_hours`, model expiry `expired_hours`, backtest re-slide `backtest_period_days`, Dissimilarity Index `DI_threshold` (refuse to predict far from training data) |
| 5 | microsoft/qlib | 49.1k | MIT | 2026-09 | Rolling retrain (full refit periodically plus incremental updates in between) and the online model manager; DDG-DA (AAAI'22) reweights training samples toward the predicted next distribution |
| 6 | david-cortes/contextualbandits | 840 | BSD-2 | 2026-06 | Contextual Thompson / bootstrapped TS over arms = scenario types, context = regime×TF features; includes off-policy evaluation utilities |
| 7 | st-tech/zr-obp (Open Bandit Pipeline) | 711 | Apache-2.0 | 2024-06 | Off-policy evaluation (IPS, Doubly Robust, SNIPS) of a *candidate* policy on *logged* bot decisions before adoption. Log the action propensity at decision time |
| 8 | ip200/venn-abers (+ sklearn `CalibratedClassifierCV`) | 207 | MIT | 2026-09 | Venn-ABERS / isotonic / Platt calibration of the meta-label probability; Venn-ABERS outputs an interval [p0,p1], and a wide interval is useful as a "small sample, skip" signal |
| 9 | asavinov/intelligent-trading-bot | 1.9k | MIT | 2026-08 | Crypto "signal score" design: several ML label models feed an aggregated score, then thresholds are tuned by `simulate`; `predict_rolling` = walk-forward retrain so every prediction is out-of-sample |
| 10 | TauricResearch/TradingAgents | 109.5k | Apache-2.0 | 2026-09 | Persistent decision log (v0.2.4+, `tradingagents.memory` since v0.5.2): each decision is stored as pending, later **settled with the realised return** plus a one-paragraph reflection, and retrieved on later runs. This replaced the earlier BM25 `FinancialSituationMemory` + `reflect_and_remember()` |

## By category

### 1. Meta-labeling and triple-barrier (mlfinlab is now closed-source)
- hudson-and-thames/mlfinlab: 4.9k stars, license "Other" (proprietary), last push 2023-10. **Do not use.**
- BlackArbsCEO/Adv_Fin_ML_Exercises (MIT, 2.0k), boyboi86/AFML (BSD-3, 876, 2024-09) and jjakimoto/finance_ml
  (MIT, 810, 2023-01): permissive notebook implementations of the triple barrier, meta-labeling, sample uniqueness
  weights, purged k-fold and bet sizing. They are good for checking our own code. They are unmaintained.
- Mapping to our engine: barriers already exist per scenario (stop = lower, target1/2 = upper, max-bars = vertical).
  Label = 1 if TP1 is hit before SL within N bars, else 0. Also record the outcome as an R multiple. Meta-model input:
  scenario type, heuristic prob, R:R, regime, TF, ATR%, funding/OI, time-of-day. Output: P(win). Take the trade if
  P(win)·R − (1−P(win)) − costs > 0.
- Pitfalls: overlapping labels (consecutive bars propose the same setup), so dedupe by setup id or weight by
  uniqueness. Same-bar SL/TP ambiguity: resolve conservatively (SL first) or use lower-TF data. Entry fills are not
  guaranteed: a limit entry that never fills is "no trade", not a loss.

### 2. Online and incremental learning
- online-ml/river (BSD-3, 6.1k, active): `linear_model.LogisticRegression`, `forest.ARFClassifier` (adaptive random
  forest), `drift.ADWIN/PageHinkley`, `bandit.*`, `metrics.Rolling`. Fits a FastAPI loop and needs no batch refits.
- VowpalWabbit/vowpal_wabbit (8.7k, BSD-3 per its LICENSE, GitHub shows "Other", C++ with Python bindings, active):
  `--cb_explore_adf` contextual bandits with built-in IPS/DR policy evaluation. It is heavier than we need at our
  data volume, so treat it as an option for later.
- Pitfall: online models forget slowly or too fast. Pair them with a drift detector and keep a frozen batch model
  as the champion.

### 3. Bandits for scenario/strategy selection
- david-cortes/contextualbandits (BSD-2, 840), fidelity/mabwiser (Apache-2.0, 294, 2024-09; TS, UCB1, LinTS,
  LinUCB, plus a `Neighborhood` policy), SMPyBandits (MIT, 425; includes discounted and sliding-window TS for
  non-stationary arms), river.bandit.
- Recommended core: Beta-Bernoulli Thompson sampling per (type × regime × TF) cell, with **discounting**
  (γ≈0.98/trade) or a sliding window so that old regimes fade. Use the reward in R units (Gaussian/NIG posterior)
  instead of hit/miss when R:R varies.
- Pitfalls: very sparse cells. Use hierarchical pooling (see §4). Delayed rewards: a trade resolves after many bars,
  so the bandit update has to wait for settlement. Selection bias: you only see outcomes for trades you took, so
  paper-trade *all* proposals in shadow mode to get unbiased labels.

### 4. Probability calibration and shrinkage
- scikit-learn `CalibratedClassifierCV` (isotonic needs about 1k+ samples, otherwise use Platt/sigmoid),
  ip200/venn-abers (MIT), scikit-learn-contrib/MAPIE (BSD-3, 1.6k; conformal risk control),
  henrikbostrom/crepes (BSD-3, 583; conformal / Mondrian calibration per category = per scenario type).
- Bayesian shrinkage (no repo needed): hit-rate per cell = (wins + α)/(n + α + β), with the prior (α, β) fitted
  by empirical-Bayes on the parent level (type → type×regime → type×regime×TF). Shrink toward the heuristic prob
  with a prior strength of about 20–50 pseudo-trades. Report Brier score, log-loss and a reliability curve per cell.
- Pitfalls: calibrating on the same data used to train the model (use a time-ordered holdout or cross-fitting);
  isotonic overfits small n; calibration drifts with the regime, so recalibrate on a rolling window.

### 5. Self-adapting, periodically retraining systems
- FreqAI (GPL-3.0, do not copy): sliding train window, retrain cadence, model expiry, DI outlier gating.
  Backtests re-slide the window every `backtest_period_days`, so the backtest reproduces live retraining.
- qlib (MIT): rolling retrain plus online serving; DDG-DA for predictable drift.
- skfolio CPCV/WalkForward (BSD-3): the validation harness for "adopt only if OOS improves".
- Policy auto-tune protocol: (a) candidate grid over min_prob, min_RR, allowed types and filters; (b) score on
  purged walk-forward folds with fees, slippage and funding; (c) adopt only if the candidate beats the champion on
  the **median** fold, the lower bootstrap CI exceeds 0, and n_trades ≥ a minimum; (d) shadow-run before going live;
  (e) cap parameter step size per update. Correct for multiple testing (deflated Sharpe / PBO). esvhd/pypbo
  computes PBO but is **AGPL-3.0**, so re-implement it from Bailey et al.

### 6. Trade-setup / signal scoring bots (crypto)
- asavinov/intelligent-trading-bot (MIT, 1.9k): closest analogue (ML scores, aggregate signal, tuned thresholds,
  rolling retrain).
- Drakkar-Software/OctoBot (GPL-3.0, 6.7k): evaluator architecture (TA, social and real-time evaluators each emit
  a −1…1 score; a strategy aggregates them). Ideas only.
- jesse-ai/jesse (MIT, 8.6k): clean strategy API, useful as a model for an entry/SL/TP/R:R object model and its
  Optuna-based optimize mode. hummingbot (Apache-2.0, 20.3k) is execution and market making, not scoring.
- CryptoSignal/Crypto-Signal (5.6k) is effectively dormant, so skip it.

### 7. LLM agent memory and reflection
- TradingAgents (Apache-2.0): the settled decision log is the pattern to copy. Store {context, decision,
  rationale}, then after resolution attach {realised R, MFE/MAE, a reflection}, and retrieve the k most similar
  past settled cases into the prompt.
- pipiku915/FinMem-LLM-StockTrading (MIT, 962, last push 2024-08): layered memory (shallow, intermediate, deep)
  with exponential decay and a score = recency + relevancy + importance, where reflections are promoted to the deep
  layer.
- Xtra-Computing/CryptoTrade (EMNLP'24, 166, license "Other", 2024-12): reflective LLM agent for crypto that
  reflects on the previous period's trade returns.
- virattt/ai-hedge-fund (MIT, 63.8k): multi-persona agents. It has no outcome learning, so it is low priority.
- Pitfalls: LLM memories leak the future in backtests (the model knows what happened in 2024), and reflections
  are narrative rather than statistics. Use LLM reflection only to *explain* results. Keep take/skip numeric.

## Cross-cutting pitfalls checklist
- **Look-ahead**: compute features at bar close t and enter at t+1 open. Regime labels must be causal (no
  centred smoothing or full-sample HMM). Do not use future-revised data such as OI or funding. Purge and embargo
  overlapping trades.
- **Overfitting**: many policy knobs × few trades. Keep the grid small, require min trades per fold, deflate for
  the number of trials, and use champion/challenger with a hysteresis margin.
- **Regime change**: discounted posteriors, drift detectors (ADWIN), model expiry, and a kill-switch on rolling
  drawdown or calibration error.
- **Small samples**: hierarchical shrinkage, Wilson/Beta credible intervals in the UI, and a "learning" status
  until n ≥ 30 per cell.
- **Costs and futures specifics**: fees, slippage, funding, liquidation distance and partial fills all belong in
  the label or reward, not only in reporting.
- **Live gating**: paper first. Go live only after OOS and shadow performance pass, with hard risk limits outside
  the learning loop.
