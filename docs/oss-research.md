# Open-source crypto/futures trading and LLM trading-agent projects: catalogue and ideas worth re-implementing

*Checked 2026-10-02.*

## How this was verified

- **Stars, license and last push** come from the GitHub repository-search API (GitHub MCP tool) on 2026-10-02. Direct `api.github.com` curl was blocked in this session, so the MCP search was used instead.
- **Features** come from WebFetch of each repo README or of raw `docs/*.md` on GitHub. `freqtrade.io` was blocked by the egress proxy, so freqtrade docs were read from `raw.githubusercontent.com/freqtrade/freqtrade/develop/docs/`.
- **Marked "(memory)"**: a few fine-grained details I could not re-fetch. Examples are Avellaneda-Stoikov in hummingbot, vectorbt's splitter API, backtrader analyzer names, and freqtrade `lookahead-analysis`. They are well-known, but this session did not verify them.
- **License rule for our codebase.** We only re-implement ideas and never copy code from GPL, AGPL or LGPL projects, or from vectorbt (Commons Clause) or mlfinlab (proprietary). MIT, Apache-2.0, ISC and Unlicense code can legally be reused with attribution. Even for those, re-implementing is cleaner.

## Context: the target app

The target is a Python FastAPI crypto-futures *analysis* app. It already has:

- an indicator backtester with a 70/30 walk-forward gate;
- Monte Carlo over trade PnLs;
- a 2-parameter sweep;
- a trailing stop;
- ML models (logreg, MLP, CNN);
- a multi-agent LLM debate office (analyst → strategist → devil's advocate → risk → CSO);
- a demo pipeline and a gated live executor.

The "port" column lists what would add value *on top of* that.

---

## A. Automated trading, backtesting and infrastructure

| Repo | Stars (2026-10-02) | License | What it is | Technique worth re-implementing |
|---|---|---|---|---|
| [freqtrade/freqtrade](https://github.com/freqtrade/freqtrade) | ~55.0k | **GPL-3.0** (ideas only) | The leading Python crypto bot (spot and futures) with backtesting, hyperopt, Telegram and web UI. | **Protections:** `StoplossGuard`, `MaxDrawdown`, `CooldownPeriod` and `LowProfitPairs` act as circuit breakers in front of the live executor. **Hyperopt loss functions** (Optuna, NSGA-III sampler): Sharpe, Sortino, Calmar, MaxDrawDown(Relative), ProfitDrawDown, MultiMetric; use them as selectable objectives for the 2-param sweep. **FreqAI:** periodic sliding-window retraining emulated inside the backtest, plus outlier rejection on prediction inputs. The docs say "a variety of outlier detection techniques"; Dissimilarity-Index, SVM and DBSCAN are from memory. Use it to gate ML signals when features are out-of-distribution. **Edge:** deprecated in 2023.9 and **removed in 2025.6**. Its idea (size positions from per-pair win rate, risk-reward and expectancy) is still a useful analytic. Hyperopt docs also advise rounding to 0.001 precision against overfitting. The `lookahead-analysis` / `recursive-analysis` commands are from memory; a lookahead-bias detector for indicators is well worth building. |
| [jesse-ai/jesse](https://github.com/jesse-ai/jesse) | ~8.6k | MIT | Python crypto bot and research framework with first-class leverage and short selling. | **Two-mode Monte Carlo:** (1) trade-order shuffle, which we already have, and (2) **candle-based** synthetic price paths that re-run the strategy, "to distinguish skill from luck". Optuna optimisation parallelised with Ray. Multi-symbol, multi-timeframe without look-ahead. Entries and exits split across several orders. Jesse also exposes an MCP server for LLM tooling. |
| [hummingbot/hummingbot](https://github.com/hummingbot/hummingbot) | ~20.3k | Apache-2.0 | Market-making and arbitrage framework for CEX and DEX, including Hyperliquid. | **`scripts/v2_funding_rate_arb.py`:** perp funding-rate arbitrage that goes long on the low-funding venue and short on the high one, and enters only if the funding spread net of fees clears a threshold. Port it as a **read-only funding-spread scanner** built on ccxt. Also `simple_pmm.py` (pure market making), `simple_xemm.py` (cross-exchange MM) and grid backtests. The V2 *PositionExecutor* "triple barrier" (stop-loss, take-profit, time-limit plus trailing) is from memory. Avellaneda-Stoikov MM (reservation price plus optimal spread) is also from memory. |
| [Drakkar-Software/OctoBot](https://github.com/Drakkar-Software/OctoBot) | ~6.7k | **GPL-3.0** (ideas only) | Bot with web, mobile and Telegram UI. Modes: grid, DCA, TradingView signals, crypto baskets, and AI mode (OpenAI or Ollama). Spot and futures on 15+ exchanges. | **Grid/DCA simulator** to show the user how many grid levels or safety orders a drawdown consumes. This is the honest way to show DCA/martingale risk. Its "AI evaluator" treats the LLM as *one vote among TA evaluators*, not as the decider. |
| [polakowo/vectorbt](https://github.com/polakowo/vectorbt) | ~9.3k | **Apache-2.0 + Commons Clause** (you may not sell a product whose value is substantially vectorbt) | Numba-vectorised backtesting of thousands of parameter combinations at once. | **Vectorised param grids and heatmaps** to extend the 2-param sweep into N-D at almost no cost. **Rolling or anchored walk-forward splits** (memory: `Splitter` / `rolling_split`) to generalise the single 70/30 gate into k folds. Report the distribution of out-of-sample (OOS) Sharpe, not a single number. |
| [mementum/backtrader](https://github.com/mementum/backtrader) | ~23.4k | **GPL-3.0** (ideas only) | Classic event-driven Python backtester. Last push 2024-08, effectively unmaintained. | Pluggable **Analyzers** (memory: SQN, DrawDown, TradeAnalyzer, SharpeRatio) and **commission/slippage schemes**, including a futures margin model. Port an SQN plus trade-stats analyzer layer. |
| [nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader) | ~29.6k | **LGPL-3.0** (ideas only, or use it as an unmodified library dependency) | Rust-core, deterministic, event-driven engine with nanosecond resolution. The same strategy code runs in backtest and live. Venues include Binance, Bybit, OKX and Hyperliquid. | **Backtest/live parity:** route demo and live through the *same* decision function and order model. **Contingent orders** (OCO/OTO brackets, reduce-only, post-only) in the gated executor, so protective stops always sit on the exchange. |
| [ccxt/ccxt](https://github.com/ccxt/ccxt) | ~44.2k | MIT | Unified API for 100+ exchanges (Py, JS, Go, and more). | Use it directly as a dependency. Of interest here: `fetchFundingRate(s)`, `fetchFundingRateHistory`, `fetchOpenInterest`, `fetchLeverageTiers` (needed for **correct liquidation-price and maintenance-margin math** in the backtester), and market precision and limits. |
| [Superalgos/Superalgos](https://github.com/Superalgos/Superalgos) | ~5.7k | Apache-2.0 | Visual node-based (JavaScript) bot designer with data mining, backtesting and paper trading. | Low priority. The visual strategy graph is overkill. Its "data-mining → indicators → strategy" layered pipeline is a reasonable UI mental model. |
| [ctubio/Krypto-trading-bot](https://github.com/ctubio/Krypto-trading-bot) | ~3.7k | ISC (permissive; GitHub reports "Other", but the LICENSE text is ISC) | Self-hosted C++ high-frequency market maker. Last push 2024-12. | Not relevant to a directional analysis app. Its quoting-safety ideas (memory: EWMA-based protection, ping-pong mode) only matter if MM is ever added. |
| [enarjord/passivbot](https://github.com/enarjord/passivbot) | ~2.1k | Unlicense (public domain) | Perpetual-futures **grid / trailing-martingale** bot. Covers Bybit, OKX, Bitget, Gate, Binance, Kucoin, Hyperliquid and others. Its Rust orchestrator is shared by backtest and live. | **Risk flag: martingale adds to losing positions.** Long periods of steady small gains are followed by occasional catastrophic drawdowns or liquidation. Worth porting: an **evolutionary optimizer** over thousands of backtests; the **"Forager"** market selection by volume and volatility; an **equity hard-stop**; and "unstucking" (realise small losses over time). The forager is a good *market-screener* feature. |
| [nkaz001/hftbacktest](https://github.com/nkaz001/hftbacktest) | ~4.8k | MIT | Tick-level and L2/L3 order-book backtester with **queue-position and latency models** (Rust/Python). | Only needed if limit-order strategies are evaluated. Otherwise, take the lesson: model fill probability and latency, or limit-order backtests will be optimistic. |
| [kernc/backtesting.py](https://github.com/kernc/backtesting.py) | ~9.0k | **AGPL-3.0** (ideas only) | Lightweight single-asset backtester with built-in optimisation heatmaps. | Interactive Bokeh result plot (equity, drawdown, trade markers). The `optimize()` + heatmap UX matches the 2-param sweep. |
| [microsoft/qlib](https://github.com/microsoft/qlib) | ~49.1k | MIT | AI quant platform (Alpha158/360 factors, rolling retraining, model zoo, RD-Agent). | **IC / Rank-IC and grouped-return analysis** of ML features and predictions: a far better ML diagnostic than accuracy. **Rolling retrain** evaluation. |
| [AI4Finance-Foundation/FinRL](https://github.com/AI4Finance-Foundation/FinRL) | ~16.5k | MIT | Deep-RL trading (PPO, A2C, DDPG, SAC, TD3) on Gym environments, with a train-test-trade pipeline. Includes crypto (Binance data). Production successor: FinRL-Trading/FinRL-X. | The **ensemble strategy**: in each rolling window, pick whichever agent had the best validation Sharpe. Port as **per-window model selection** among logreg, MLP and CNN instead of a fixed model. |
| [hudson-and-thames/mlfinlab](https://github.com/hudson-and-thames/mlfinlab) | ~4.9k | **Proprietary/"Other"** (do not use code) | Implementations from López de Prado, *Advances in Financial ML*. | Implement from the **book**: **triple-barrier labelling**, **meta-labelling** (an ML model decides *whether* to take the primary indicator signal and how to size it), and **purged k-fold CV with embargo**. These are probably the most valuable upgrades for the existing ML module. Plain k-fold or random splits leak on overlapping labels. |
| [freqtrade/freqtrade-strategies](https://github.com/freqtrade/freqtrade-strategies), [iterativv/NostalgiaForInfinity](https://github.com/iterativv/NostalgiaForInfinity) | ~5.5k / ~3.4k | GPL-3.0 | Community strategy collections. | Read-only inspiration for indicator combinations. Do not copy. Treat public strategies as heavily overfitted. |
| Other DCA/grid bots: [Open-Trader/opentrader](https://github.com/Open-Trader/opentrader) | ~2.9k | Apache-2.0 | TypeScript DCA and grid bot with UI (a "3Commas-like" open alternative). | DCA safety-order ladder parameters (step scale, volume scale). Use them for the drawdown-consumption simulator above. |
| [stefan-jansen/machine-learning-for-trading](https://github.com/stefan-jansen/machine-learning-for-trading) | ~21.2k | MIT | Notebooks for the ML-for-Trading book. | Reference material for feature engineering, alpha evaluation with alphalens-style IC, and CNN/RNN on time series. |

## B. LLM chatbots and multi-agent trading assistants

| Repo | Stars | License | What it is | Technique worth re-implementing |
|---|---|---|---|---|
| [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) | ~109.5k | Apache-2.0 | LangGraph multi-agent firm. An analyst team (fundamentals, sentiment, news, technical) runs in parallel. **Bull vs bear researcher debate** feeds a trader, then a **risk-management team debate**, then the portfolio manager approves or rejects. Supports many LLM providers. BTC-USD/ETH-USD tickers via yfinance. | (1) **Explicit bull/bear adversarial pair** with a configurable number of rounds. Our office has one devil's advocate; two symmetric advocates reduce anchoring. (2) **Risk team as a 3-way debate** (aggressive / neutral / conservative). (3) **Reflection memory**: after a trade is realised, store the lesson keyed to market context and retrieve it into future prompts. (4) Checkpoint and resume of the agent graph. |
| [virattt/ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) | ~63.8k | MIT | LangGraph team of investor-persona agents plus valuation, sentiment, fundamentals and technicals agents, a risk manager and a portfolio manager. Backtester. **Paper only; "does not actually make any trades"**. Equities; crypto is on the roadmap. | Each agent returns a **structured output (signal, confidence, reasoning)** that is aggregated numerically. Position limits are computed in the **risk manager deterministically, outside the LLM**, before the portfolio-manager LLM sees them. Port both patterns. |
| [HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading) | ~34.4k | MIT | "Personal trading agent": multi-agent, MCP tools, backtesting, skills, Electron desktop, Docker. Created 2026-04. | MCP-tool exposure of the backtester, so an LLM can call `run_backtest`, `sweep` and `monte_carlo` as tools. This is a natural next step for our office. |
| [hsliuping/TradingAgents-CN](https://github.com/hsliuping/TradingAgents-CN) | ~32.1k | (not checked) | Chinese-market enhanced fork of TradingAgents. | Same ideas as TradingAgents. Shows the pattern is widely adopted. |
| [NoFxAiOS/nofx](https://github.com/NoFxAiOS/nofx) | ~13.0k | **AGPL-3.0** (ideas only) | LLM agents trade **crypto perpetuals** on Binance, Bybit, OKX, Hyperliquid, Bitget and others. **Hard-coded risk limits override model decisions.** | Directly relevant to our gated executor. Leverage cap enforced *at order sizing*; max concurrent positions and notional caps; one position per symbol; **exchange-side SL/TP**; give-back (profit drawdown) auto-close; minimum hold time and re-entry cooldown; per-cycle entry limit; **"safe mode"** that blocks entries after repeated failures. |
| [HKUDS/AI-Trader](https://github.com/HKUDS/AI-Trader) | ~22.7k | README badge says MIT; **GitHub detects no LICENSE file** (treat as unlicensed until confirmed) | Agent-native trading arena with leaderboards, paper trading ($100k) and live mark-to-market scoring of agents. | **Leaderboard and live paper scoring of agent configurations.** Run several office configs (different LLMs or prompts) in parallel on the demo pipeline and rank them on forward OOS performance. |
| [virattt/dexter](https://github.com/virattt/dexter) | ~27.6k | README says MIT; GitHub detects no license file | TypeScript autonomous financial-research agent: task planning, tool execution, **self-validation**, loop detection and step limits, eval suite. | **Planner → executor → self-check loop with hard step and loop limits**, plus an **eval suite** for agent answers. Our office lacks automated evals. |
| [openbq-org/OpenBB](https://github.com/openbq-org/OpenBB) (formerly OpenBB-finance) | ~73.8k | Apache-2.0 | Open data platform for analysts, quants and AI agents. Ships **MCP servers** and a Workspace. | Use it as a data and tool layer, or copy the "connect once, consume everywhere" provider abstraction for our data feeds. |
| [AI4Finance-Foundation/FinGPT](https://github.com/AI4Finance-Foundation/FinGPT) | ~21.3k | MIT | Open financial LLMs: LoRA fine-tunes for financial sentiment and forecasting. | A cheap **sentiment-score feature** from a small fine-tuned model, fed into the ML model as a numeric feature rather than as prose. |
| [AI4Finance-Foundation/FinRobot](https://github.com/AI4Finance-Foundation/FinRobot) | ~8.1k | Apache-2.0 | Agent platform for financial analysis (Financial Chain-of-Thought, report generation). | Report-generation templates for the CSO summary. |
| [The-Swarm-Corporation/AutoHedge](https://github.com/The-Swarm-Corporation/AutoHedge) | ~6.2k | MIT | Swarm agents (director, quant, risk, execution) for an "autonomous hedge fund". | Low novelty compared with TradingAgents. |
| [pipiku915/FinMem-LLM-StockTrading](https://github.com/pipiku915/FinMem-LLM-StockTrading) | ~1.0k | MIT | Research LLM trader with **layered memory** (short, mid, long-term with decay) and a character profile. | **Memory decay/importance scoring** for the reflection memory proposed under TradingAgents. |
| [elizaOS/eliza](https://github.com/elizaOS/eliza) | ~19.5k | MIT | General agent OS widely used for crypto/Web3 agents and bots. | Plugin and connector architecture (Telegram, Discord). Only relevant if a chat front-end is wanted. |
| [Open-Finance-Lab/AgenticTrading](https://github.com/Open-Finance-Lab/AgenticTrading) | ~0.8k | "Other" (unclear) | Research framework for agentic trading. | Reference only. |
| LangChain/LangGraph and RAG patterns | n/a | n/a | TradingAgents and ai-hedge-fund are LangGraph reference designs. A separate crewAI-examples repo (now archived) had stock-analysis crews. | **RAG over our own artefacts**: index past backtest reports, agent debates and post-trade reflections, so the office cites prior evidence instead of re-hallucinating it. |

---

## C. Top recommendations for the existing app (ranked)

1. **Purged/embargoed walk-forward and k-fold CV, triple-barrier labels and meta-labelling** (López de Prado, implemented from the book). Today's 70/30 gate and plain ML splits leak and overstate edge.
2. **Rolling or anchored multi-fold walk-forward** (vectorbt idea). Report the *distribution* of OOS metrics. Add a **deflated Sharpe / multiple-testing** penalty for the sweep (memory: Bailey & López de Prado).
3. **freqtrade-style Protections plus NoFx-style hard limits** in the gated executor: StoplossGuard, MaxDrawdown, Cooldown, LowProfitPairs, leverage cap at sizing, exchange-side SL/TP via reduce-only or OCO (nautilus), safe mode after failures.
4. **Jesse-style candle-path Monte Carlo** (re-run the strategy on bootstrapped or synthetic price paths), in addition to the trade-shuffle MC we already have.
5. **Selectable sweep objectives** (Calmar, Sortino, ProfitDrawdown) and N-D vectorised grids with heatmaps.
6. **TradingAgents debate upgrades:** symmetric bull/bear, a 3-persona risk debate, a post-trade **reflection memory** (FinMem-style decay), and structured `{signal, confidence, reasoning}` outputs aggregated numerically (ai-hedge-fund).
7. **Deterministic risk manager outside the LLM:** the LLM can only *reduce* risk, never exceed caps.
8. **Funding-rate and OI analytics via ccxt** (hummingbot idea): a funding-spread scanner and liquidation price from `fetchLeverageTiers`.
9. **Lookahead-bias and recursive-indicator checks** (freqtrade idea): re-compute signals on truncated data and diff the results.
10. **Agent evaluation harness and paper-trading leaderboard** of office configurations (dexter, AI-Trader).
11. **Feature/prediction IC analysis** (qlib) and per-window model selection (FinRL ensemble).
12. **Grid/DCA/martingale drawdown simulator** (OctoBot, passivbot, opentrader) as an *educational risk tool*, not a recommended strategy.

---

## D. The claim "100,000 KRW → 100,000,000 KRW in one month with crypto futures"

### Math

The target multiple is 100,000,000 / 100,000 = **1,000×**. That is +99,900 % in a month.

**Required compound return per period:**

| Horizon | Required return per day |
|---|---|
| 30 calendar days (crypto trades 24/7) | 1000^(1/30) − 1 = **+25.89 % per day, every day, with no losing day** |
| 22 trading days | +36.9 % per day |
| 21 trading days | +38.9 % per day |

**Equivalent in doublings.** 1,000× is about 2^9.97, so roughly **10 consecutive doublings with no loss**. If each doubling is a fair 50/50 all-in bet, P(10 in a row) = 0.5^10 ≈ **0.098 %, about 1 in 1,024**. At a 55 % edge it is about 0.25 %; at 60 % it is about 0.6 %. That is *before* fees, funding and slippage. The other ~99.9 % of paths end at or near zero, because the account is liquidated.

**What it means in market terms.** At 10× leverage, the trader must capture a +2.6 % favourable underlying move every single day for 30 days with zero adverse days. At 20× the daily requirement falls to 1.3 %, but a single ~5 % adverse move liquidates the account.

**Volatility drag.** Log growth ≈ μ − σ²/2. Take a BTC daily vol of about 3 %:

| Leverage | Daily equity σ | Drag per day |
|---|---|---|
| 10× | ≈ 30 % | ≈ **4.5 %** |
| 20× | ≈ 60 % | ≈ **18 %** |

Higher leverage *lowers* expected compound growth once it passes the Kelly-optimal level, which for any realistic edge is low single-digit leverage at most.

**Costs.** One round trip per day at 0.05 % taker per side, on 10× notional, costs ≈ **1 % of equity per day** before funding (funding is typically ±0.01 % per 8h on notional, i.e. up to ~0.3 % of equity per day at 10×).

**Annualised.** 1,000× per month compounds to 10^36 per year. No fund, strategy or market in history has come anywhere close. The best-known track records, such as Renaissance Medallion, are widely reported at roughly 60–70 %/yr *gross*. That figure is from memory, not verified this session.

**Verdict.** The claim is not a strategy target; it describes a lottery ticket with a high chance of total loss. An analysis app should never present it as achievable. It should show the required daily return, the probability of ruin and the liquidation distance whenever a user enters such a goal.

### Evidence on retail leveraged and futures trader outcomes

- **Brazil mini-index futures** (Chague, De-Losso & Giovannetti, *"Day Trading for a Living?"*, SSRN 3423101). The study covers all 19,646 individuals who started day trading mini-Ibovespa futures in 2013–2015. **97 % of the 1,551 who persisted more than 300 days lost money** net of fees. Only **1.1 % earned more than the minimum wage** and 0.5 % more than a bank teller's starting salary. [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3423101)
- **Taiwan day traders** (Barber, Lee, Liu & Odean, *"Do Day Traders Rationally Learn About Their Ability?"*, 15 years of complete Taiwan market data). **Fewer than 1 %** of day traders predictably earn profits net of fees. Aggregate performance is negative, and a large share of day trading comes from traders with long histories of losses. [Paper (Berkeley)](https://faculty.haas.berkeley.edu/odean/papers/Day%20Traders/Day%20Trading%20and%20Learning%20110217.pdf), [Taiwan evidence (Yale)](http://www.econ.yale.edu/~shiller/behfin/2004-04-10/barber-lee-liu-odean.pdf)
- **EU leveraged CFDs** (ESMA product intervention, 2018). **74–89 % of retail CFD accounts lose money**, with average losses of €1,600–€29,000 per client. High leverage was identified as the main driver. ESMA responded with leverage caps, margin close-out, negative-balance protection and mandatory loss-rate disclosure. [ESMA press release](https://www.esma.europa.eu/press-news/esma-news/esma-agrees-prohibit-binary-options-and-restrict-cfds-protect-retail-investors)
- **Crypto retail** (BIS Bulletin No. 69, *"Crypto shocks and retail losses"*, Feb 2023). Across crypto-app users in 95 economies from Aug 2015 to Dec 2022, **a majority of retail users lost money on their bitcoin investments**. The average loss was about $431, or about 48 % of the ~$900 invested. Small holders bought after the Terra/Luna and FTX shocks while large holders sold. This study covers *unleveraged* spot BTC; leveraged futures are strictly riskier. [BIS](https://www.bis.org/publ/bisbull69.htm)
- **Secondary or industry claims (weaker evidence):** "84 % of retail crypto traders lose money in their first year" and "~80 % lose in crypto futures" circulate in media and exchange blogs. Their methodology is unclear, so cite them only with that caveat. [nftevening](https://nftevening.com/84-percent-of-retail-crypto-traders-lose-money-in-their-first-year/), [hedgefundalpha (74–89 % in volatility events)](https://hedgefundalpha.com/news/retail-traders-lost-volatility-event/)
- **Gap:** this session found no peer-reviewed study specific to *retail crypto perpetual-futures* PnL. The futures and CFD evidence above (same mechanics: leverage, margin calls, liquidation) is the closest rigorous proxy.

## Sources

- GitHub repository-search API results (stars, licenses, push dates), 2026-10-02.
- READMEs fetched: TradingAgents, ai-hedge-fund, Vibe-Trading, NoFx, AI-Trader, dexter, OpenBB, FinRL, jesse, nautilus_trader, OctoBot, passivbot, hummingbot `/scripts`.
- Licenses fetched: vectorbt `LICENSE.md` (Apache-2.0 + Commons Clause); Krypto-trading-bot `LICENSE` (ISC).
- freqtrade docs via raw GitHub: `docs/freqai.md`, `docs/hyperopt.md`, `docs/includes/protections.md`. Edge removal: [freqtrade deprecated features](https://docs.freqtrade.io/en/stable/deprecated/) ("deprecated in 2023.9 and removed in 2025.6").
- Literature: [Chague et al., SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3423101); [Barber et al.](https://faculty.haas.berkeley.edu/odean/papers/Day%20Traders/Day%20Trading%20and%20Learning%20110217.pdf); [ESMA 2018](https://www.esma.europa.eu/press-news/esma-news/esma-agrees-prohibit-binary-options-and-restrict-cfds-protect-retail-investors); [BIS Bulletin 69](https://www.bis.org/publ/bisbull69.htm).
