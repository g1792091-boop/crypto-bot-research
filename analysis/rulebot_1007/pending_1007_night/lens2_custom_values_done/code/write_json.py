import sys, json, os
sys.path.insert(0,'/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens2/custom_values/code')
from show import *
W='/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/lens2/custom_values'
os.chdir(W)
mR=pd.read_csv('out/wf_methods.csv'); mM=pd.read_csv('out_R2/wf_methods.csv')
notes=json.load(open('out/strategy_notes.json'))
def row(m,sc,meth):
    return m[(m.scheme==sc)&(m.method==meth)].iloc[0]
def tab(m):
    L=["| re-tune | window | pooled OOS delta (R / trade) | 95% CI (day cluster) | half A / half B | cells > 0 of 36 (BH10 sig) | trades vs default | pick's training gain | worse-than-default share of switches |","|---|---|---|---|---|---|---|---|---|"]
    for st,nm in ((1,'weekly'),(4,'monthly')):
        for w in (1,4,13,26):
            r=row(m,f's{st}_w{w}','naive')
            L.append(f"| {nm} | {w} wk | {r.pooled_delta_R:+.4f} | [{r.ci_lo:+.4f}, {r.ci_hi:+.4f}] | {r.delta_halfA:+.4f} / {r.delta_halfB:+.4f} | {r.cells_positive} ({r.cells_bh_sig}) | {r.trade_ratio:.2f} | {r.mean_train_improvement_of_pick:+.3f} | {r.noise_rate:.2f} |")
    return '\n'.join(L)
def dimtab(m):
    L=["| searched dimension | re-tune/window | pooled OOS delta | 95% CI | half A / half B | cells > 0 | trades vs default | verdict (PREREG sec. 8) |","|---|---|---|---|---|---|---|---|"]
    for meth,nm in (('naive_P','indicator values P'),('naive_F','context filters F'),('naive_S','stop width S'),('naive_X','exit style X')):
        for sc in ('s4_w13','s4_w26'):
            r=row(m,sc,meth)
            L.append(f"| {nm} | {sc} | {r.pooled_delta_R:+.4f} | [{r.ci_lo:+.4f}, {r.ci_hi:+.4f}] | {r.delta_halfA:+.4f} / {r.delta_halfB:+.4f} | {r.cells_positive} | {r.trade_ratio:.2f} | {'beats default' if r.beats_default else 'no'} |")
    return '\n'.join(L)
pl=pd.read_csv('out_R2/planted_summary.csv')
def plt():
    L=["| gate (N_min, delta, z_min; both training halves > 0) | true gain planted | adopted share of weeks | captured share of the true gain | median week of first adoption | cells that never adopt |","|---|---|---|---|---|---|"]
    for g,nm in (('naive','no gate (naive best of 225)'),('gate_30_0.05_0.0','30, 0.05, 0'),('gate_100_0.05_2.0','100, 0.05, 2'),('gate_100_0.15_2.0','100, 0.15, 2'),('gate_100_0.3_2.0','100, 0.30, 2')):
        for dl in (0.1,0.2,0.3):
            r=pl[(pl.scheme=='s4_w26')&(pl.method==g)&(pl.delta==dl)].iloc[0]
            fa='never' if r.median_first_adopt_week>=9999 else int(r.median_first_adopt_week)
            L.append(f"| {nm} | +{dl:.2f} R | {r.adopt_share:.2f} | {r.captured_share:.2f} | {fa} | {r.cells_never_adopt} |")
    return '\n'.join(L)
def gatenull():
    L=["| gate | OOS delta, money units (R2), monthly / 26 wk | 95% CI | share of cell-weeks switched | trades vs default |","|---|---|---|---|---|"]
    for g in ('gate_30_0.05_0.0','gate_100_0.05_2.0','gate_300_0.05_2.0','gate_100_0.15_2.0','gate_300_0.15_2.0','gate_100_0.3_2.0'):
        r=row(mM,'s4_w26',g)
        L.append(f"| {g[5:]} | {r.pooled_delta_R:+.4f} | [{r.ci_lo:+.4f}, {r.ci_hi:+.4f}] | {r.switch_share_cellweeks:.2f} | {r.trade_ratio:.2f} |")
    return '\n'.join(L)
lv=pd.read_csv('out_R2/levels_summary.csv')
lvt=["| custom value (one at a time, others default) | cells | mean delta, half A (2021-08..2024-06) | mean delta, half B (2024-07..2026-09) | cells > 0 in A / B / both |","|---|---|---|---|---|"]
for _,r in lv.iterrows():
    lvt.append(f"| {r.dim}: {r.level} | {r.cells} | {r.mean_dA:+.4f} | {r.mean_dB:+.4f} | {r.cells_dA_pos} / {r.cells_dB_pos} / {r.cells_pos_both} |")
dd=pd.read_csv('out_R2/cell_desc.csv')
conf=["| tf | default net R/trade | gross | cost | weeks to detect +0.05 / +0.10 / +0.20 R, all-signal shadow (median over cells) | same for a one-position trader |","|---|---|---|---|---|---|","| 15m | -0.170 | -0.002 | 0.168 | 42 / 11 / 2.7 | 249 / 62 / 16 |","| 30m | -0.120 | -0.004 | 0.116 | 53 / 13 / 3.3 | 240 / 60 / 15 |","| 1h | -0.084 | -0.003 | 0.081 | 64 / 16 / 4.0 | 226 / 56 / 14 |"]
md=f"""# Does "keep searching for custom values" work? Walk-forward test on 5 years of Binance futures

**Short answer.** No, not in the way the plan assumes. Searching 225 custom-value combinations per strategy and applying the trailing winner to the next week or month did not beat default values out of sample once the result is measured in a comparable money unit (pooled difference between {mM[mM.method=='naive'].pooled_delta_R.min():+.4f} and {mM[mM.method=='naive'].pooled_delta_R.max():+.4f} R per trade over 8 re-tune/window schemes, every 95% CI includes 0, 0 of 36 cells survive BH). The training window always showed a large gain (0.14 to 0.49 R per trade); the next period showed none. Measured in stop-relative R (the pre-registered metric) the search looks like a +0.02 R win, but that is an artefact: the search drifts to the 2.5 ATR stop, which makes the same money loss a smaller number of R. The few kinds of custom values that carry a small, stable out-of-sample value (higher-timeframe agreement, ADX and box-position filters, a tighter 1.5 ATR stop) are worth 0.003 to 0.009 R per trade against a cost of 0.08 to 0.17 R per trade.

## 1. What was tested (PREREG.md, hash in PREREG.sha256, written before any outcome was computed)
- Data: Binance USDT-M 15m/30m/1h bars, BTC ETH SOL DOGE LTC BCH, 2021-02 to 2026-09-29 (the repo's cache `binance/signals/sig_<tf>_<COIN>.npz`). Out-of-sample (OOS) 2021-08-02 to 2026-09-28 (268 weeks).
- 12 strategies x 3 timeframes = 36 cells: S2_ST_ROC, N23_HA_ST, N24_DMI, N10_HA_PSAR, S4_BB_BBP, N06_MACD_ORB, OBV_B (trend/breakout/volume), F6_VWAP_CROSS (volume/VWAP), F9_FVG (ICT), N17_KC_RSI, N16_BBRSI (mean reversion), F5_BOX (structure/box edges).
- Signals: locked cache for defaults; custom indicator values come from the repo's hash-locked `research/entry_study/param_defs` (manifest hash pinned) for the 9 core strategies (0 signal mismatches vs the locked cache on all 6 coins x 3 tf) and from my parameterised copies of `research/deepseek200/lib_c.py` for F6/F5/F9 (0 mismatches vs `lib_c.entries` after fixing one ATR-NaN warm-up detail in my copy). F6 variants (weekly anchor, volume confirm, 0.10/0.25 ATR buffer) are my own definitions, not repo-locked.
- Custom-value space per cell = 225 combinations: 5 indicator sets (default + 4 changes at x0.75 / x1.25) x 5 filters (none, higher-timeframe EMA50 agreement, ADX (trend >= 20, mean-reversion < 25), box position, London+NY session) x 3 stops (1.5 / 2 / 2.5 ATR) x 3 exits (house ROE ladder at 20x geometry, R-ladder (+0.5R at 1R, then every 0.5R), fixed 1.5R take-profit with break-even at 1R).
- Costs: repo house values (taker 0.05% per side, slippage 0.02% per side, funding 0.01% per 8 h). My house-exit code reproduces `research/exitstyle/exitstyle.scan` (20x, 2 ATR) with identical hold times and ROE to 2e-15 (excluding the -100% clamp, which my code does not model: 2 to 5 of 3,000 sample trades).
- Every signal is a trade (no one-position limit), coins pooled. Default stream: 1,258,505 OOS trades in 36 cells, mean {-0.142:+.3f} R/trade (gross -0.003 R, cost 0.139 R).
- Walk-forward: decision at each Monday T; training = signals in the trailing window that exited before T; apply the choice to the next 1 week (weekly re-tune) or 4 weeks (monthly). Windows 1, 4, 13, 26 weeks. Naive rule = best training mean R among combinations with >= 10 training trades.
- Uncertainty: day-cluster paired bootstrap (1,000 resamples), BH 10% across the 36 cells.

**Amendment A1 (post hoc, disclosed in AMENDMENTS.md).** After the first run I saw that R depends on the stop chosen. I re-ran everything in R2 = net money result in units of the default 2 ATR stop (R2 = R x k/2). Both versions are reported; R2 is the one that stands for money. The code, seed and thresholds are identical.

## 2. Headline: walk-forward search vs defaults
Stop-relative R (pre-registered metric):
{tab(mR)}

Money units R2 (amendment A1):
{tab(mM)}

Reading:
- In R, six of eight schemes pass the pre-registered rule "beats defaults" (+0.02 to +0.025 R, CI above 0, both halves positive, 24 to 32 of 36 cells). In R2 none does. Net return per trade in % of notional moved by {mR[(mR.scheme=='s4_w26')&(mR.method=='naive')].delta_netpct_per_trade.iloc[0]:+.4f} percentage points (selected stream is slightly worse in money). The R gain is the stop width: the naive search chose the 2.5 ATR stop in 78% of weeks (26-week window) and only 8% the 1.5 ATR stop.
- The search never keeps the default: share of weeks on the default combination is 0.000 to 0.014; it changes combination on average 41 times (monthly, 26 wk) to 264 times (weekly, 1 wk) per cell over 5 years.
- Training improvement of the picked combination: +0.14 R (26 wk) to +0.49 R (1 wk) per trade; out-of-sample: about 0. The in-sample gap closes completely. In the half-A to half-B persistence test, the top 10 combinations of the first half gained +0.042 R in half A and +0.006 R in half B (mean over 36 cells; top-10 positive in half B in 22 of 36 cells; mean Spearman rank correlation of combination effects across halves +0.24).
- Switches that were worse than default in the applied period: 43% to 52% (a coin flip is 50%). The naive search "picks noise" about half the time and no more than coin flip better.
- Shorter windows are worse: weekly re-tune on a 1-week window: {row(mM,'s1_w1','naive').pooled_delta_R:+.4f} R2 [{row(mM,'s1_w1','naive').ci_lo:+.4f}, {row(mM,'s1_w1','naive').ci_hi:+.4f}]. Longer windows (13 to 26 wk) lower the swing but there is no gain to find. Weekly vs monthly re-tuning makes no difference at 13 to 26 weeks.
- By timeframe (monthly re-tune, 26-wk window, equal-weight mean of 12 cells, R2): 15m +0.0021, 30m +0.0005, 1h -0.0094; no cell passes BH. By strategy the 12-strategy means range from -0.023 (N16_BBRSI, N24_DMI) to +0.037 (F5_BOX); see strategy notes. F5_BOX is the only family positive in all three timeframes (+0.023, +0.064, +0.024 R2) but small samples (2k to 10k trades), no cell BH-significant, and its default is -0.20 / -0.14 / -0.05 R.
- Oracle check: the best of 225 combinations over the whole OOS period beats default by +0.007 to +0.164 R (mean +0.042, median +0.036; this is an in-sample maximum of 225 and is mostly selection); a random combination is +0.001 on average. Positive-mean combinations over 5 years: none in 34 of 36 cells (F5_BOX_30m: 2, F5_BOX_1h: 40 of 225, n = 2,199).

## 3. Which kinds of custom values carry out-of-sample value
Search restricted to one dimension (others at default), OOS (R2; P, F and X are unchanged from R because the stop stays 2.0):
{dimtab(mM)}

Static effect of each single custom value vs default, split in time (R2 units, only levels with >= 30 trades in both halves; cells where positive in both halves in last column):
{chr(10).join(lvt)}

Reading:
- Exit styles (R-ladder, fixed 1.5R + break-even): negative or zero, in line with `research/exitstyle` (house ladder remains the least bad). Searching exits adds nothing (0 of 8 schemes).
- Indicator values: +0.003 to +0.004 R in some schemes with CI above 0 but half B only +0.0003 to +0.0009 (26 wk); 4 of 36 cells BH-significant at most; not stable.
- Filters: the only consistent but small contribution: +0.006 to +0.008 R per trade (13 and 26 wk windows; CI above 0, both halves positive, 25 to 26 of 36 cells), at the price of keeping only 56% of the trades. Statically, higher-timeframe agreement (+0.005 / +0.009 in halves A / B, positive in 26 / 28 of 36 cells) and box position (+0.002 / +0.008) hold across halves; the session filter does not (-0.002 / -0.003). Per trade that is about 5% of the cost. Trading less also reduces the total loss, which is not an edge.
- Stop: tighter 1.5 ATR is +0.005 / +0.003 R2 in the two halves (32 and 26 of 36 cells), 2.5 ATR is -0.005 / -0.004. In stop-relative R the order is reversed (wide stops look better), which is the artefact above.
- The pre-registered per-dimension rule is passed by F (7 of 8 schemes), S (4 of 8) and P (3 of 8) in money units, X never. All gains are below 0.009 R.

## 4. Adoption gate
All gates use the training window only, require the candidate = best training mean with n >= N_min, training gain >= delta, gain > 0 in both halves of the window (each half with >= N_min/4 candidate trades), and a z-score >= z_min.

Gate behaviour when nothing real exists (the data as they are; money units R2, monthly re-tune on 26 weeks):
{gatenull()}

Gate behaviour when a real improvement exists (planted test, added check A2: one random combination is given a true gain in every week, naive search and gates run unchanged; money units; monthly re-tune, 26-week window; 36 cells):
{plt()}

Reading:
- Under the pre-registered R rule the gates with delta 0.05 "keep real improvements" (+0.024 R on switched weeks, CI above 0), but those switches are the wide-stop artefact. In money units no gate passes (0 of 144 gate x scheme combinations).
- A gate with N_min 100, delta 0.05 R, z >= 2 and the two-half test is harmless on real data (+0.0007 R2 [-0.0044, +0.0059], switches in 45% of cell-weeks) and captures 86% of a true +0.20 R improvement (96% of +0.30 R) within the first weeks, but only 42% of a true +0.10 R (median first adoption week 10).
- A strict gate (delta 0.15) does worse than doing nothing on this data (-0.0028 R2 [-0.0047, -0.0010]) and captures almost nothing of +0.10 R (2%). A very strict gate (delta 0.30) switches in only 1 to 5% of cell-weeks and is a no-op except for gains >= 0.30 R. The no-gate naive search captures more of a true gain but also chooses a wrong combination in 16% to 48% of weeks.
- Practical gate for the bot: N_min >= 100 training trades (all-signal shadow trades, not own trades), training gain >= 0.05 R in money units, z >= 2, positive in both halves of a 26-week window, and a shadow-account confirmation period before use. Re-tune monthly on a 26-week window; weekly search only as a candidate generator. Use money units (R at the default stop), never R of the changed stop.

## 5. How long until a real improvement could be confirmed
Per cell, pooled across six coins, with measured day-clustering (design effect ~3), one comparison, no multiple-testing correction, one-sided 5%, power 80%:
{chr(10).join(conf)}

A one-position trader has only 4 to 51 trades per week (mean 23), 2 to 11 times fewer than the all-signal stream. A +0.05 R custom value needs a median 56 weeks of all-signal shadow data per cell (range 11 to 350 weeks), and about 4.5 years (median 235 weeks) for a one-position trader; +0.10 R needs about 3 months to 1 year of all-signal shadow data per cell (11 to 87 weeks), +0.20 R from 1 week to 5 months (median 3.5 weeks), and these times are for a single pre-specified test. Searching 225 combinations needs more (the gate's z >= 2 and the two-half rule already raise the bar). The 12/31 deadline (about 12 weeks) can confirm only effects of >= +0.2 R in the high-frequency cells (F6_VWAP, N17_KC_RSI, S2, N23: 0.7 to 4 weeks for +0.2 R at the all-signal stream, 6 to 36 weeks for a one-position trader) and few in low-frequency cells (F5_BOX, N06_MACD_ORB, N16_BBRSI: 4.5 to 22 weeks).

## 6. What this means for the AI bot
1. Keep default values as the account's rule; run the custom-value search as a shadow, all-signal process only. The owners' hypothesis that custom values found over time convert to a real edge gets no support: the best value found in trailing data is, on average, zero out of sample, and the biggest searchable lever (stop width) moves money by at most 0.005 R.
2. The break-even gap is 0.08 to 0.17 R per trade (the cost), 15 to 30 times the largest stable custom-value effect measured here (0.003 to 0.009 R). The AI's value must come from somewhere else (trade selection, skipping, exits in real time), not from tuning.
3. If a search is run: monthly, 26-week window, N_min 100, delta 0.05 R in money units, z >= 2, two-half agreement, then 1 to 2 weeks of shadow tracking with all signals. Do not use 1-week windows.
4. Candidate filters worth keeping on the list as pre-registered tests, not as features: higher-timeframe EMA50 agreement and ADX/box position (each about +0.005 R), and a tighter stop; not session, not R-ladder or fixed-TP exits.

## 7. Limits
See the JSON `limits` field.
"""
findings=[
 dict(id='CV1',claim='Walk-forward custom-value search (225 combinations per cell, trailing window, applied to the next 1 or 4 weeks) does not beat default values out of sample once results are measured in a stop-independent money unit.',
  evidence='out_R2/wf_methods.csv, naive rows: pooled OOS delta -0.0040 to +0.0037 R2 per trade over 8 schemes (1,258,505 default trades, 36 cells, 268 OOS weeks), all 95% day-cluster CIs include 0 (e.g. monthly/26 wk -0.0009 [-0.0135, +0.0124]); 0 of 36 cells BH-significant in 7 of 8 schemes (1 in s4_w1); 12 to 17 of 36 cells positive (chance level).',
  confidence='high',implication='Do not let the bot adopt searched custom values without a gate and shadow check; the owners\' premise is not supported on 5-year data.'),
 dict(id='CV2',claim='In the pre-registered stop-relative R the same search looks like a +0.02 to +0.025 R win, but this is an artefact of stop width.',
  evidence='out/wf_methods.csv: pooled delta +0.0236..+0.0254 R (CI above 0 for 6 of 8 schemes; 24-32 of 36 cells positive), yet net return per trade in % moved -0.008 to -0.019 pct points; naive pick uses the 2.5 ATR stop in 78% of weeks (26 wk), static 2.5 ATR is -0.005 R2 in half A and -0.004 in half B (3 and 8 of 36 cells positive). out/pick_composition.csv.',
  confidence='high',implication='Any custom-value search must score candidates in money (or R at the default stop), never in R of the candidate stop; otherwise it will always find "wider stops are better".'),
 dict(id='CV3',claim='The in-sample gain of the picked combination vanishes out of sample.',
  evidence='mean training improvement of the pick over default 0.137 R (26 wk) to 0.491 R (1 wk) per trade (out_R2/wf_methods.csv); out-of-sample about 0; half-A top-10 combos +0.042 R in A and +0.006 R in B (out_R2/persistence.csv, 36 cells; positive in B in 22 of 36 cells; mean Spearman A vs B +0.24). Picks that lose to default in the applied period: 43-52% of switches.',
  confidence='high',implication='Show the owners the training-vs-next-period gap; a weekly "best value found" report is a noise report.'),
 dict(id='CV4',claim='Short windows are worse; at 13 to 26 weeks the search is stable but still at zero. Weekly versus monthly re-tuning does not matter at long windows.',
  evidence='out_R2/wf_methods.csv: s1_w1 -0.0040 [-0.0152, +0.0075], s4_w1 +0.0028; s4_w13 -0.0024 [-0.0151, +0.0104]; s4_w26 -0.0009 [-0.0135, +0.0124]. Per timeframe (monthly, 26 wk, equal-weight cells): 15m +0.0021, 30m +0.0005, 1h -0.0094; 0 BH hits.',
  confidence='medium',implication='If a search runs: monthly, trailing 26 weeks; never a 1-week window.'),
 dict(id='CV5',claim='Of the kinds of custom values, only context filters (and a tighter stop) show small, stable out-of-sample value; indicator values are weak, exit styles are negative.',
  evidence='out_R2/wf_methods.csv: filter-only search +0.0061 [+0.0013, +0.0109] (monthly/26wk), +0.0067 [+0.0017, +0.0111] (13 wk), half A/B +0.0095/+0.0018 and +0.0075/+0.0055, 25 of 36 cells positive, but only 56% of the trades kept. Stop-only +0.0026 [+0.0014, +0.0038] (half B +0.0004). Indicator-only +0.0031 [+0.0011, +0.0052] (half B +0.0003). Exit-only -0.0006..-0.0031 (CI includes 0). Static levels (out_R2/levels_summary.csv): HTF agreement +0.0048/+0.0086 (A/B), box +0.0024/+0.0075, session -0.0024/-0.0026, stop 1.5 +0.0049/+0.0030, R-ladder -0.0035/-0.0063.',
  confidence='medium',implication='Treat HTF/ADX/box filters and a 1.5 ATR stop as candidate tests worth 0.005 R each, not as a rescue: the cost is 0.08 to 0.17 R per trade.'),
 dict(id='CV6',claim='Nothing found is anywhere near the break-even gap. Default cost is 0.168 R (15m), 0.116 R (30m), 0.081 R (1h) per trade and gross edge is about 0 (-0.002, -0.004, -0.003 R).',
  evidence='out_R2/cell_desc.csv: default pooled net R/trade -0.170 / -0.120 / -0.084 at 15m / 30m / 1h (691,714 / 368,276 / 198,515 trades); 34 of 36 cells have 0 of 225 combinations with positive 5-year mean R (F5_BOX_30m: 2, F5_BOX_1h: 40 of 225, n=2,199).',
  confidence='high',implication='Custom values cannot be the source of the edge. The AI must beat the cost by trade selection or exits; budget the cost first.'),
 dict(id='CV7',claim='An adoption gate works only if it is permissive enough to see a real gain and strict enough to ignore noise; the 0.15 R gate is both too strict for +0.10 R and slightly harmful on the actual data; the best tested gate is N_min 100 / delta 0.05 R / z >= 2 / two halves.',
  evidence='out_R2/wf_methods.csv gates (monthly, 26 wk): 100/0.05/2: +0.0007 [-0.0044, +0.0059], switch share 0.45; 100/0.15/2: -0.0028 [-0.0047, -0.0010]; 100/0.30/2: switch share 0.04. Planted gain (out_R2/planted_summary.csv, 36 cells): +0.20 R captured 86% (gate 100/0.05/2), 76% (100/0.15/2), 1% (100/0.30/2); +0.10 R captured 42%, 2%, 0%; naive no gate 89% / 58% but wrong combination in 16% / 48% of weeks.',
  confidence='medium',implication='Use the 100 / 0.05 R2 / z2 / two-half gate on a 26-week window with an all-signal shadow confirmation; expect to see only effects >= 0.10 R.'),
 dict(id='CV8',claim='Confirming a real improvement takes months to years. With the all-signal shadow stream a +0.10 R custom value takes a median 14 weeks per cell (range 3 to 87), +0.20 R a median 3.5 weeks, +0.05 R a median 56 weeks; a one-position trader needs 2 to 11 times longer.',
  evidence='out_R2/cell_desc.csv (weeks_needed_*, design effect 1.4 to 12) and out/one_position.csv (one-position trades per week 3.8 to 51, mean 23 vs 130 for all signals); one-sided alpha 5%, power 80%, one comparison, no multiplicity.',
  confidence='medium',implication='By 12/31 (about 12 weeks) only gains >= 0.2 R in the high-frequency cells can be confirmed; always track all signals in the shadow account, not the AI\'s own trades.'),
 dict(id='CV9',claim='Pre-registered verdicts: literal rule gives "beats defaults" in R for 6 of 8 schemes and "gate keeps real" for the 0.05 R gates; in money units 0 of 8 and 0 of 144. The post-hoc amendment is disclosed.',
  evidence='out/wf_methods.csv vs out_R2/wf_methods.csv columns beats_default / gate_keeps_real; AMENDMENTS.md.',
  confidence='high',implication='Report both; decisions rest on the money-unit result.')]
J=dict(findings=findings,strategy_notes=notes,
 files=dict(prereg=W+'/PREREG.md',prereg_hash=W+'/PREREG.sha256',amendments=W+'/AMENDMENTS.md',code=W+'/code/ (cvlib.py, stage1.py, stage2.py, stage3.py, stage4_extra.py, stage5_planted.py, ds_parity.py, build_report.py, write_json.py)',
  results_R=W+'/out/ (wf_methods.csv, wf_cells.csv, cell_desc.csv, persistence.csv, levels_AB.csv, levels_summary.csv, planted.csv, planted_summary.csv, one_position.csv, pick_composition.csv, strategy_notes.json)',
  results_R2=W+'/out_R2/ (same tables, money units)',work=W+'/work/ (cells/*.npz every signal outcome, wf*/ walk-forward arrays, logs)',parity=W+'/work/ds_parity.json'),
 limits=[
  'Every signal is a trade, no one-position limit, no portfolio, no margin or liquidation model (the 20x house ladder geometry is used for the lock only; a bar gapping through the stop beyond -100% ROE is not clamped: 2 to 5 of 3,000 sample trades). Results are per-notional unit results, not account curves.',
  'The pre-registered metric (R) turned out to depend on the stop; the money-unit metric R2 was added after seeing the R results (amendment A1, disclosed). The R2 design (scale by k/2) is exact only for per-notional comparisons; it ignores that wider stops allow lower leverage at fixed risk.',
  'Search space is modest (225 combinations, one parameter at a time at x0.75 and x1.25, four filters, three stops, three exits). A larger space or smarter search (Bayesian, shrinkage, regime-conditional) is not tested; it would face more selection noise, not less. Only 3 timeframes (15m, 30m, 1h); no 4h.',
  'Day-cluster bootstrap treats days as independent. Week-to-week dependence, regime shifts and cross-strategy overlap (the 36 cells share coins and many signals, and the 12 strategies are not independent) are not modelled, so CIs are somewhat optimistic and the pooled-over-cells CI is narrower than a strategy-level one.',
  'F6_VWAP_CROSS variants (weekly VWAP anchor, volume confirm, ATR buffers) and the filter definitions (HTF EMA50, ADX 20/25, box 48 bars, UTC 07-20 session) are my own and fixed before looking at results; they are not the repo\'s locked definitions. F6/F5/F9 default signals match lib_c.entries bar for bar.',
  'Stop/take-profit ordering inside a bar is conservative (stop first); taker fills with fixed slippage; no maker fills, no real order book; funding is a constant 0.01%/8h.',
  'Weeks-to-confirm uses the default stream variance and measured design effect for an unpaired one-comparison test; a paired test of a filter that is a subset of the default trades needs fewer trades, a 225-way search needs more. One-position counts use a greedy first-come, first-served thinning on the default stream.',
  'The planted-improvement test plants a constant true gain in one random combination with >= 30% of the default trades; real improvements are likely time-varying and smaller, so the capture shares are optimistic.',
  'The 2021-2026 period contains one market history; "5 years" is not 5 independent samples. The current market (quiet, narrow stops) has higher cost in R than the 5-year mean.',
  'Not tested: AI discretion (skipping, early exit, switching), 4h, intraday-event filters, data after 2026-09-29, entry-quality tiers.'],
 report_section_md=md)
json.dump(J,open('/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/resume/lens2_custom_values.json','w'),indent=1)
print(md[:3000])
