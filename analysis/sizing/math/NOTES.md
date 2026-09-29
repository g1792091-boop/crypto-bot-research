# TASK A: constraint math per timeframe for the user's new money-management rules

The rules under test: margin M ≥ 20% of equity, leverage L ≥ 20x, take-profit ≥ +10% ROE. The user wants both M and L to be chosen "from the chart".

Every number below comes from the scripts in `work/`, and their outputs are in `out/`.

- **Data.** In-sample bars only: `sweep/data/is/<sym>-<tf>.csv`, all before 2024-07-01.
  - The 1d entries also use daily bars rebuilt from IS 1h bars, anchored at 00/06/12/18 UTC. The 00 UTC rebuild matches the official 1d file exactly (max relative difference 0.0).
  - Nothing under `sweep/data/oos` or `sweep/data/final` was read.
  - Nothing under `/home/user/crypto-bot-research` was modified.
  - No Astral calls were made.
  - I ran one Python process at a time.
- **Cost model**, as specified by the task:
  - Taker 0.05% and slippage 0.02% per market fill, so 0.14% of notional per round trip.
  - Funding 0.01%/8h, always charged as a cost.
  - Isolated margin with MMR 0.5%, so liquidation happens at an adverse move d_liq = 1/L − 0.5%.
  - A liquidation loses the whole margin (ROE −100%) plus the entry fee.
  - TP distance = 10%/L. The TP is gross ROE, the way Binance displays it.

## 한국어 요약 (사용자 전달용)

- **"익절 +10% ROE"를 쓰면, 레버리지를 올려도 이익은 커지지 않는다.**
  - 한 번 익절할 때 계좌 기준 총이익은 레버리지와 관계없이 **M×10%**다. 시드 20%면 +2%다.
  - 레버리지를 올리면 세 가지만 바뀐다.
    - 수수료가 커진다: 계좌의 M×L×0.14%. 20%×20배면 0.56%, 40%×50배면 2.8%다.
    - 청산가가 가까워진다: 20배 4.5%, 50배 1.5%.
    - 익절폭이 좁아진다: 20배 0.5%, 50배 0.2%.
  - 즉 "차트 보고 레버리지를 알아서 올리는" 규칙에는 올릴 이유가 되는 쪽이 없다.
- **무작위 진입(엣지 0)이어도 승률은 약 90%가 나온다.**
  - 익절 0.5% 대 청산 4.5%라는 구조에서 나오는 숫자다. 실력이 아니다.
  - 비용을 넣으면 거래당 기대 ROE는 **−3.2% ~ −3.8% (20배)**, **−7.8% ~ −9.4% (50배)**다.
  - 계좌 기준으로는 거래당 −0.76% (20%×20배) ~ −3.8% (40%×50배)다.
  - 엣지 0으로 100번 거래하면, 20%×20배의 중앙값이 계좌 **×0.36**, 40%×20배는 **×0.065**다.
- **본전에 필요한 조건**
  - 20배: 익절 먼저 도달 확률이 **93.5%**여야 한다. 공짜로 나오는 90.0%보다 3.5%p 높아야 한다.
  - 30배: 94.7%. 50배: **97.2%**.
  - 보유 시간 동안 가격이 유리하게 흘러야 하는 강도를 연 샤프(IR)로 바꾸면 20배 **약 3.7**, 30배 약 10, 50배 약 63이다. 수수료와 청산 손실만 메우는 데 필요한 수준이다.
  - 이 프로젝트에서 관측된 엣지는 전부 0 이하였다.
- **시간봉 호환성 (20배 이상 기준)**
  - **4시간봉과 일봉은 20배 이상과 양립하지 않는다.**
    - 일봉 20배: 청산 거리가 일봉 ATR의 0.73배다. BTC만 보면 약 1.0배다.
    - 일봉 20배: 첫 일봉 안에서 청산 거리에 닿을 확률이 22%다.
    - 일봉 20배: 거래의 93%가 진입한 봉 안에서 끝난다. 일봉 신호가 결과에 영향을 줄 틈이 없다.
  - **1시간봉**: 25배 이상은 불가하고, 20배는 경계선이다.
  - **30분봉**: 20배까지만 된다.
  - **5분·15분봉**: 형태상 20배는 가능하다. 다만 25배 이상은 수수료가 익절폭의 1/3을 넘는다.
- **결론**
  - 형태상 가능한 조합은 "5~30분봉, 약 20~24배" 한 칸뿐이다.
  - 거기서도 엣지가 없으면 기대값은 음수다. 위의 필요한 샤프(IR 약 3.7)를 채울 전략은 아직 없다.

## Bottom line

1. **Leverage does not raise the win under a ROE-defined TP; it only adds cost.**
   - The gross profit of a TP is M × 10% of equity at any L.
   - Raising L does three things, all bad:
     - It raises the fee drag: M·L·0.14% of equity per round trip.
     - It pulls liquidation in: d_liq = 1/L − 0.5%.
     - It shrinks the TP: 10%/L.
   - At zero edge, expected equity change per trade falls monotonically with L. At M = 20% on 5m paths:
     - 5x: −0.39%
     - 10x: −0.49%
     - 20x: −0.76%
     - 30x: −1.14%
     - 50x: −1.88%
   - An "adaptive leverage ≥ 20x" rule therefore has no upside dimension to adapt along.
2. **The bracket wins about 90% of the time with zero edge, and still loses money.**
   - Random entries, both directions, real paths, at 20x:
     - P(TP first) = 0.900 on 5m paths. The Brownian value ds/(tp+ds) is 0.900.
     - E[ROE] after costs = −3.81% (se 0.16%).
   - At 50x: 0.884 and −9.40%.
   - The high win rate is produced by the geometry: +0.5% vs −4.5% at 20x.
3. **Break-even edge.**
   - Required P(TP first):
     - 20x: 0.935 (+3.5 pp over the free 0.900)
     - 25x: 0.941
     - 30x: 0.947
     - 40x: 0.960
     - 50x: 0.972
   - Break-even drift injected into the real 5m paths, as an annualised IR (μ/σ during the holding period):
     - 20x: 3.7
     - 25x: 6.1
     - 30x: 10.3
     - 40x: 24.1
     - 50x: 62.8
   - These are the edges needed just to pay the costs.
4. **Sizing at M ≥ 20% (Kelly).**
   - For M = 20% at 20x to be full Kelly, the bot needs P(TP first) ≥ 0.948. For half Kelly it needs 0.962.
   - For M = 40% at 20x: 0.962 (full Kelly) and 0.988 (half Kelly).
   - At the free 0.900 the Kelly margin fraction is negative: −0.53 at 20x.
5. **Timeframes that cannot be used with L ≥ 20:**
   - **4h and 1d at every L ≥ 20.**
   - **1h at L ≥ 25.** 1h at 20x is borderline.
   - **30m at L ≥ 30.** 30m at 25x is borderline.
   - **15m at L ≥ 40.**
   - L ≥ 25 fails the fee test on every TF: fees are 35% or more of the TP distance.
   - What remains geometrically usable is 5m to 30m at roughly 20–24x. It is still negative-EV without a strong signal.

## 1. Fee drag and loss per liquidation (`out/fee_drag.csv`)

Round-trip fee drag, in % of equity, = M × L × 0.14%:

| M \ L | 5 | 10 | 20 | 25 | 30 | 40 | 50 |
|---|---|---|---|---|---|---|---|
| 20% | 0.14 | 0.28 | 0.56 | 0.70 | 0.84 | 1.12 | 1.40 |
| 25% | 0.18 | 0.35 | 0.70 | 0.88 | 1.05 | 1.40 | 1.75 |
| 30% | 0.21 | 0.42 | 0.84 | 1.05 | 1.26 | 1.68 | 2.10 |
| 40% | 0.28 | 0.56 | 1.12 | 1.40 | 1.68 | 2.24 | 2.80 |

- **Fees relative to the TP.** Fees as a share of the TP distance = 0.14%/(10%/L) = 0.014·L. That is 28% at 20x, 35% at 25x, 42% at 30x, 56% at 40x and 70% at 50x. This does not depend on the timeframe.
- **Net ROE of a TP.**
  - After taker costs and funding (5m paths), a TP nets +7.07% ROE at 20x and +2.94% at 50x.
  - A liquidation costs −101.9% at 20x and −103.7% at 50x.
- **Loss per liquidation in equity** = M·(1 + L·0.07%). That is 20.3% of equity at 20%×20x and 40.6% at 40%×20x.

## 2. Volatility per TF, pooled over 7 coins (`out/tf_vol_stats.csv`, `out/tf_atr_by_coin.csv`)

| TF | median ATR14 % | ATR14 p10–p90 % | abs close-to-close move, H=1 bar (median / p90 %) | H=4 | H=16 | H=64 |
|---|---|---|---|---|---|---|
| 5m | 0.303 | 0.16–0.60 | 0.10 / 0.37 | 0.20 / 0.72 | 0.39 / 1.45 | 0.80 / 2.98 |
| 15m | 0.533 | 0.29–1.02 | 0.18 / 0.63 | 0.34 / 1.26 | 0.68 / 2.57 | 1.49 / 5.25 |
| 30m | 0.763 | 0.41–1.43 | 0.25 / 0.89 | 0.48 / 1.78 | 0.99 / 3.69 | 2.20 / 7.47 |
| 1h | 1.101 | 0.60–2.00 | 0.35 / 1.25 | 0.69 / 2.57 | 1.50 / 5.25 | 3.22 / 10.59 |
| 4h | 2.329 | 1.31–4.03 | 0.70 / 2.60 | 1.50 / 5.25 | 3.21 / 10.59 | 7.15 / 21.97 |
| 1d | 6.129 | 3.71–9.74 | 1.99 / 6.52 | 4.15 / 12.76 | 9.10 / 27.26 | 18.71 / 54.92 |

- BTC alone has median ATR of 0.245% (5m), 0.820% (1h), 1.663% (4h) and 4.424% (1d).
- SOL, the most volatile coin here, has 0.416%, 1.519%, 3.162% and 8.110%.
- 20x liquidation distance (4.5%) versus daily ATR: about 1.0 ATR for BTC and about 0.55 ATR for SOL.

## 3. Compact table: TF × L (`out/compact_table.csv`, `out/compact_table_short.md`)

**How to read the columns**

- **Bracket.** TP at +10% ROE. The stop is liquidation, i.e. no stop: the worst case.
- **Entries.** Random bars, entered at the bar open, both long and short at every sampled bar. 80k entries per TF for 5m–1h, 83,028 for 4h and 55,310 for 1d.
- **P(liq) if held 16 bars.** Probability that the adverse excursion from the entry open reaches d_liq within 16 bars, ignoring TP.
- **ends in entry bar.** Share of trades resolved inside the bar they entered on, measured on the TF's own bars.
- **own-bar adv / fav.**
  - The bracket evaluated on the TF's own OHLC.
  - If TP and liquidation are both touched in the same bar, "adv" assumes the adverse one came first; "fav" assumes the favourable one did.
- **5m path.** The same entries re-simulated on 5m bars. These are the primary numbers.
  - 5m ambiguity is resolved adverse-first.
  - 5m ambiguity affects ≤ 0.32% of trades with the no-stop bracket, and ≤ 1.4% with the 0.5×d_liq stop.
- **E[ROE].** Net of fees, slippage and funding. Clustered se in parentheses, clustered by coin × week.
- **required P(TP first).** The win probability at which E[ROE] = 0, keeping the empirical win and loss sizes.
- **required drift, ann. IR.** The favourable drift injected into every trade's real 5m path at which E[ROE] crosses 0.
  - It is expressed as the annualised μ/σ of the price during the holding period (`out/drift_breakeven_5m.csv`).
  - It does not depend on TF, because the bracket is defined in price.

| TF | L | TP/ATR | liq/ATR | P(liq) if held 16 bars | ends in entry bar | P(TP first) own-bar adv / fav | P(TP first) 5m path | E[ROE] own-bar adv / fav | E[ROE] 5m path (se) | required P(TP first) | required drift, ann. IR |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 5m | 5x | 6.61 | 64.41 | 0.0% | 0% | 0.901 / 0.901 | **0.901** | -1.9% / -1.9% | **-1.93%** (0.38) | 0.919 (+1.7pp) | 0.6 |
| 5m | 10x | 3.30 | 31.38 | 0.1% | 1% | 0.902 / 0.902 | **0.902** | -2.4% / -2.4% | **-2.44%** (0.25) | 0.924 (+2.2pp) | 1.1 |
| 5m | 20x | 1.65 | 14.86 | 0.9% | 6% | 0.900 / 0.900 | **0.900** | -3.8% / -3.8% | **-3.81%** (0.16) | 0.935 (+3.5pp) | 3.7 |
| 5m | 25x | 1.32 | 11.56 | 1.7% | 10% | 0.897 / 0.898 | **0.897** | -4.7% / -4.7% | **-4.74%** (0.15) | 0.941 (+4.4pp) | 6.1 |
| 5m | 30x | 1.10 | 9.36 | 2.9% | 14% | 0.895 / 0.895 | **0.895** | -5.7% / -5.7% | **-5.70%** (0.14) | 0.947 (+5.3pp) | 10.3 |
| 5m | 40x | 0.83 | 6.61 | 6.3% | 21% | 0.890 / 0.891 | **0.890** | -7.5% / -7.4% | **-7.51%** (0.13) | 0.960 (+7.0pp) | 24.1 |
| 5m | 50x | 0.66 | 4.95 | 11.1% | 29% | 0.884 / 0.886 | **0.884** | -9.4% / -9.2% | **-9.40%** (0.13) | 0.972 (+8.8pp) | 62.8 |
| 15m | 5x | 3.75 | 36.55 | 0.1% | 1% | 0.900 / 0.900 | **0.900** | -2.1% / -2.1% | **-2.07%** (0.38) | 0.919 (+1.9pp) | 0.6 |
| 15m | 10x | 1.87 | 17.81 | 0.5% | 4% | 0.902 / 0.902 | **0.902** | -2.4% / -2.4% | **-2.39%** (0.25) | 0.924 (+2.2pp) | 1.1 |
| 15m | 20x | 0.94 | 8.44 | 3.6% | 17% | 0.900 / 0.901 | **0.901** | -3.8% / -3.7% | **-3.77%** (0.16) | 0.935 (+3.5pp) | 3.7 |
| 15m | 25x | 0.75 | 6.56 | 6.4% | 24% | 0.898 / 0.899 | **0.899** | -4.6% / -4.6% | **-4.59%** (0.15) | 0.941 (+4.2pp) | 6.1 |
| 15m | 30x | 0.62 | 5.31 | 9.9% | 30% | 0.896 / 0.897 | **0.897** | -5.5% / -5.4% | **-5.44%** (0.14) | 0.947 (+5.0pp) | 10.3 |
| 15m | 40x | 0.47 | 3.75 | 18.0% | 42% | 0.890 / 0.894 | **0.893** | -7.5% / -7.0% | **-7.16%** (0.13) | 0.960 (+6.7pp) | 24.1 |
| 15m | 50x | 0.37 | 2.81 | 26.9% | 51% | 0.880 / 0.889 | **0.886** | -9.8% / -8.9% | **-9.17%** (0.13) | 0.972 (+8.6pp) | 62.8 |
| 30m | 5x | 2.62 | 25.57 | 0.2% | 2% | 0.901 / 0.901 | **0.901** | -2.0% / -2.0% | **-2.02%** (0.38) | 0.919 (+1.8pp) | 0.6 |
| 30m | 10x | 1.31 | 12.46 | 1.2% | 9% | 0.903 / 0.903 | **0.903** | -2.3% / -2.3% | **-2.29%** (0.25) | 0.924 (+2.1pp) | 1.1 |
| 30m | 20x | 0.66 | 5.90 | 8.0% | 28% | 0.900 / 0.902 | **0.901** | -3.8% / -3.7% | **-3.71%** (0.16) | 0.935 (+3.4pp) | 3.7 |
| 30m | 25x | 0.52 | 4.59 | 13.1% | 36% | 0.898 / 0.900 | **0.899** | -4.7% / -4.5% | **-4.56%** (0.15) | 0.941 (+4.2pp) | 6.1 |
| 30m | 30x | 0.44 | 3.72 | 18.6% | 43% | 0.893 / 0.897 | **0.896** | -5.9% / -5.4% | **-5.54%** (0.13) | 0.947 (+5.1pp) | 10.3 |
| 30m | 40x | 0.33 | 2.62 | 30.0% | 55% | 0.882 / 0.894 | **0.892** | -8.3% / -7.1% | **-7.32%** (0.13) | 0.960 (+6.8pp) | 24.1 |
| 30m | 50x | 0.26 | 1.97 | 40.6% | 64% | 0.868 / 0.891 | **0.887** | -11.1% / -8.7% | **-9.14%** (0.12) | 0.972 (+8.6pp) | 62.8 |
| 1h | 5x | 1.82 | 17.71 | 0.4% | 5% | 0.901 / 0.901 | **0.901** | -1.9% / -1.9% | **-1.93%** (0.37) | 0.919 (+1.7pp) | 0.6 |
| 1h | 10x | 0.91 | 8.63 | 3.0% | 17% | 0.903 / 0.904 | **0.903** | -2.3% / -2.2% | **-2.26%** (0.25) | 0.924 (+2.1pp) | 1.1 |
| 1h | 20x | 0.45 | 4.09 | 15.9% | 41% | 0.897 / 0.901 | **0.900** | -4.1% / -3.7% | **-3.81%** (0.16) | 0.935 (+3.5pp) | 3.7 |
| 1h | 25x | 0.36 | 3.18 | 23.6% | 50% | 0.893 / 0.900 | **0.899** | -5.2% / -4.5% | **-4.59%** (0.15) | 0.941 (+4.2pp) | 6.1 |
| 1h | 30x | 0.30 | 2.57 | 31.1% | 57% | 0.886 / 0.899 | **0.897** | -6.6% / -5.3% | **-5.46%** (0.14) | 0.947 (+5.1pp) | 10.3 |
| 1h | 40x | 0.23 | 1.82 | 44.3% | 68% | 0.870 / 0.898 | **0.894** | -9.7% / -6.6% | **-7.03%** (0.13) | 0.960 (+6.5pp) | 24.1 |
| 1h | 50x | 0.18 | 1.36 | 54.9% | 76% | 0.841 / 0.897 | **0.889** | -14.0% / -8.1% | **-8.90%** (0.12) | 0.972 (+8.3pp) | 62.8 |
| 4h | 5x | 0.86 | 8.37 | 2.8% | 18% | 0.902 / 0.903 | **0.903** | -1.8% / -1.8% | **-1.80%** (0.36) | 0.919 (+1.6pp) | 0.6 |
| 4h | 10x | 0.43 | 4.08 | 14.8% | 43% | 0.903 / 0.906 | **0.905** | -2.3% / -2.0% | **-2.04%** (0.24) | 0.924 (+1.9pp) | 1.1 |
| 4h | 20x | 0.21 | 1.93 | 42.0% | 69% | 0.884 / 0.908 | **0.905** | -5.5% / -3.0% | **-3.24%** (0.14) | 0.935 (+3.0pp) | 3.7 |
| 4h | 25x | 0.17 | 1.50 | 51.8% | 76% | 0.865 / 0.909 | **0.905** | -8.2% / -3.5% | **-3.93%** (0.13) | 0.941 (+3.6pp) | 6.1 |
| 4h | 30x | 0.14 | 1.22 | 59.5% | 82% | 0.840 / 0.911 | **0.905** | -11.6% / -4.0% | **-4.59%** (0.12) | 0.947 (+4.2pp) | 10.3 |
| 4h | 40x | 0.11 | 0.86 | 70.8% | 89% | 0.775 / 0.916 | **0.903** | -19.9% / -4.8% | **-6.08%** (0.11) | 0.960 (+5.7pp) | 24.1 |
| 4h | 50x | 0.09 | 0.64 | 77.9% | 93% | 0.698 / 0.921 | **0.899** | -29.3% / -5.6% | **-7.81%** (0.11) | 0.972 (+7.3pp) | 62.8 |
| 1d | 5x | 0.33 | 3.18 | 23.1% | 54% | 0.898 / 0.902 | **0.901** | -2.3% / -1.9% | **-1.94%** (0.36) | 0.919 (+1.7pp) | 0.6 |
| 1d | 10x | 0.16 | 1.55 | 50.7% | 77% | 0.876 / 0.907 | **0.905** | -5.3% / -1.9% | **-2.08%** (0.24) | 0.924 (+1.9pp) | 1.1 |
| 1d | 20x | 0.08 | 0.73 | 74.8% | 93% | 0.743 / 0.918 | **0.904** | -21.1% / -2.1% | **-3.35%** (0.16) | 0.935 (+3.1pp) | 3.7 |
| 1d | 25x | 0.07 | 0.57 | 80.6% | 96% | 0.663 / 0.925 | **0.903** | -30.4% / -2.0% | **-4.10%** (0.15) | 0.941 (+3.8pp) | 6.1 |
| 1d | 30x | 0.05 | 0.46 | 84.2% | 98% | 0.590 / 0.933 | **0.902** | -38.9% / -1.9% | **-4.88%** (0.14) | 0.947 (+4.5pp) | 10.3 |
| 1d | 40x | 0.04 | 0.33 | 89.0% | 99% | 0.465 / 0.946 | **0.899** | -53.6% / -2.0% | **-6.56%** (0.14) | 0.960 (+6.1pp) | 24.1 |
| 1d | 50x | 0.03 | 0.24 | 91.7% | 100% | 0.370 / 0.956 | **0.893** | -64.8% / -2.5% | **-8.44%** (0.14) | 0.972 (+7.9pp) | 62.8 |

**What the table says**

- **Real paths behave like a driftless random walk.** The 5m-path P(TP first) is 0.884–0.905 at every TF and L. The Brownian value ds/(tp+ds) is 0.882–0.907.
  - The zero-edge loss is about the same on every TF: −3.2% to −3.8% ROE at 20x, −7.8% to −9.4% at 50x.
  - So the TF does not change the zero-edge expectation. It changes whether a signal on that TF can plausibly supply the missing edge.
- **Evaluating on the TF's own bars is unreliable for 4h and 1d.**
  - At 1d 20x, 17.5% of trades touch TP and liquidation in the same daily bar.
  - The adverse and favourable assumptions then bracket −21.1% to −2.1%. The 5m path gives −3.35%.
  - Any 4h/1d backtest of this bracket without intrabar data is meaningless.

## 4. Why 4h and 1d (and 1h/30m at higher L) are incompatible with L ≥ 20

This is shown two ways.

### Criteria check

I used five thresholds. They are judgement calls; the raw numbers are in the table above.

1. d_liq ≥ 3 ATR, so that normal noise does not liquidate.
2. TP ≥ 0.5 ATR, so that the TP is not sub-bar noise.
3. Fewer than 50% of trades resolved inside the entry bar, so that the TF's signal gets at least one bar to act.
4. P(liquidation if held 16 bars) < 10%.
5. Fees ≤ 1/3 of the TP distance, i.e. L ≤ 23.8.

The resulting verdict (`out/compat_verdict.csv`):

| TF | 20x | 25x | 30x | 40x | 50x |
|---|---|---|---|---|---|
| 5m | ok | fees | fees | fees | fees, P(liq16) 11% |
| 15m | ok | fees | fees | fees, TP 0.47 ATR, P(liq16) 18% | all five fail |
| 30m | ok | fees, P(liq16) 13% | fees, TP 0.44 ATR, P(liq16) 19% | all five fail | all five fail |
| 1h | TP 0.45 ATR, P(liq16) 16% | 4 fails | all five fail | all five fail | all five fail |
| 4h | 4 fails (fees ok) | all five fail | all five fail | all five fail | all five fail |
| 1d | 4 fails (fees ok) | all five fail | all five fail | all five fail | all five fail |

### The numbers behind "incompatible"

- **1d at 20x.**
  - Liquidation is 0.73 median daily ATR away. Liquidation within the first daily bar if held: 22.2% at 20x and 63.4% at 50x (`p_liq_hold1`).
  - The TP is 0.08 ATR. 92.9% of trades end inside the entry bar.
  - A daily signal therefore has no influence on what happens. The outcome is intraday noise at 90/10 odds with negative EV.
- **4h at 20x.**
  - Liquidation is 1.93 ATR away. Holding 16 bars (2.7 days) gives P(liq) 42%. The TP is 0.21 ATR, and 68.9% of trades end inside the entry bar.
  - Only 16% of 4h bars have an ATR small enough for 20x to keep liquidation ≥ 3 ATR away. For 1d it is 0%.
- **1h at 20x (borderline).**
  - TP 0.45 ATR, liquidation 4.1 ATR, P(liq if held 16 h) 16%, 41% of trades end inside the entry bar.
  - At 25x and above, more than half of trades end inside the entry bar.
- **ATR-adaptive leverage** (`out/adaptive_leverage_atr.csv`).
  - The rule L = 1/(3·ATR + 0.5%) keeps liquidation 3 ATR away. Its median value is 71x (5m), 48x (15m), 36x (30m), 26x (1h), 13x (4h) and 5.3x (1d).
  - This is only a noise-room ceiling, not a recommendation: the fee constraint caps L near 24 regardless, and the required edge grows steeply with L (section 5).

## 5. Required edge in detail (`out/bracket_zero_edge.csv`, `out/drift_breakeven_5m.csv`, `out/kelly_binary.csv`)

| L | free P(TP) | required P(TP) for E=0 | required drift IR (injected) | Wald first-order IR | P(TP) for M=20% full / half Kelly | P(TP) for M=40% full / half Kelly |
|---|---|---|---|---|---|---|
| 5 | 0.901 | 0.919 | 0.6 | 0.44 | 0.936 / 0.952 | 0.952 / 0.985 |
| 10 | 0.902 | 0.924 | 1.1 | 0.94 | 0.939 / 0.955 | 0.955 / 0.986 |
| 20 | 0.900 | 0.935 | 3.7 | 2.47 | 0.948 / 0.962 | 0.962 / 0.988 |
| 25 | 0.897 | 0.941 | 6.1 | 3.60 | 0.953 / 0.965 | 0.965 / 0.989 |
| 30 | 0.895 | 0.947 | 10.3 | 4.99 | 0.958 / 0.969 | 0.969 / 0.990 |
| 40 | 0.890 | 0.960 | 24.1 | 8.13 | 0.968 / 0.976 | 0.976 / 0.993 |
| 50 | 0.884 | 0.972 | 62.8 | 12.14 | 0.978 / 0.984 | 0.984 / 0.995 |

All rows use 5m paths with the liquidation (no-stop) bracket.

- **The injected-drift IR is the authoritative number.**
  - The Wald estimate μ = Δr/E[τ] understates it by 1.15–5.2x. A favourable drift shortens trades (mean hold at 20x: 6.8 h at zero edge, about 4.6 h at break-even), so less time is available to collect the drift.
  - At the injected break-even, P(TP first) equals the tilt-model requirement to 3 decimals: 0.9348 vs 0.9351 at 20x. The two methods agree.
- **Break-even is not enough for compounding.** For median equity not to shrink (E[log] ≥ 0), P(TP first) must be 0.942 at 20%×20x, 0.950 at 40%×20x and 0.979 at 40%×50x (`out/equity_100trades.csv`, `p_win_needed_log`).

## 6. What M ≥ 20% does to the account at zero edge (`out/equity_100trades.csv`)

The model: binomial over 100 i.i.d. trades using the empirical class means (5m paths, no stop).

Median final equity multiple:

| L \ M | 20% | 25% | 30% | 40% |
|---|---|---|---|---|
| 20x | 0.36 | 0.26 | 0.17 | 0.065 |
| 25x | 0.32 | 0.22 | 0.14 | 0.051 |
| 30x | 0.28 | 0.19 | 0.12 | 0.039 |
| 50x | 0.13 | 0.071 | 0.036 | 0.008 |

- P(equity < 50% after 100 trades) is 68% (20%×20x), 88% (40%×20x) and 98–99.8% at 50x.
- Even at exactly break-even edge (arithmetic E = 0), the median after 100 trades is 0.95 (20%×20x) and 0.59 (40%×20x). This is the volatility drag of losing 20–40% of equity in a single liquidation.

## 7. Sensitivities

All of these use 5m paths.

- **Stops instead of liquidation.** At 20x:
  - A stop at 1.0×d_liq gives E[ROE] −2.95%, versus −3.81% with liquidation.
  - A stop at 0.5×d_liq (2.25%) gives P(TP first) 0.819 and E[ROE] −2.85%.
  - The best of the three variants is still negative at every L. At 50x the three give −9.40% (liquidation), −6.92% (stop at 1.0×) and −7.13% (stop at 0.5×).
- **TP as a maker limit order** (0.02%, no slippage) improves E[ROE] by 0.9 pp at 20x (to −2.91%) and 2.2 pp at 50x (to −7.19%). It is still negative.
- **Larger TP, since the user said "at least 10%"** (`out/tp_size_sensitivity_5m.csv`). At 20x with TP 20/30/50/100% ROE:
  - Zero-edge E[ROE] is −4.7/−5.3/−6.6/−8.5% with no stop, and −2.9 to −4.0% with stops.
  - The liquidation share rises to 18/25/36/52% of trades.
  - A larger TP lowers the signal speed required: the Wald first-order IR goes from 2.5 at a 10% TP to 0.7 at a 100% TP. The injection check showed Wald understates this, though.
  - The trade-off is many more liquidations at 20%+ of equity each.
- **Bad prints.** Neutralising the 296 IS suspect bars listed in `sweep/data/suspects.csv` changes 5m E[ROE] by at most 0.04 pp (`out/suspect_sensitivity_5m.csv`).

## 8. Caveats

- **The bars are not Binance perp bars.** They are spot USD bars pulled through Astral.
  - Binance liquidates on mark price, a multi-venue index, so single-venue wicks may overstate liquidations slightly. The suspect-bar test says this effect is negligible here.
- **Simplified liquidation mechanics.**
  - MMR is fixed at 0.5% as specified. Real Binance tiers vary by symbol.
  - The exact isolated formula (1/L − MMR)/(1 ± MMR) differs from 1/L − MMR by < 0.01 pp.
  - Funding is always charged. In reality it varies and is sometimes received. At 20x it costs about 0.17% ROE per trade.
- **The zero-edge baseline is random entry, not a strategy.** A real strategy with adverse selection can do worse than this baseline.
- **Sampling.**
  - Entries overlap in time, so the se values are clustered by coin × week.
  - The four 1d day-anchors are strongly correlated, so the 1d se values are optimistic.
  - Maximum hold is 90 days. Timeouts are ≤ 0.15% of trades and occur only at 5x.
- **The injected-drift IR** assumes a constant drift during the holding period. It is a benchmark for signal strength, not a strategy.
- **Period.** The data run from 2021-07 to 2024-06. SOL starts 2021-10 and DOGE 2021-08. The period includes the 2022 bear market. Volatility regimes after that differ.

## Files

- `work/common.py`: loaders, ATR, sparse-table first-hit search (brute-force check: 0 mismatches in 3,000 cases, `work/test_first_hit.py`).
- `work/stats.py`: sections 1–2 and the distance table → `out/tf_vol_stats.csv`, `out/tf_L_distances.csv`, `out/fee_drag.csv`, `out/sd_1bar.json`.
- `work/sim.py`: zero-edge bracket, own-bar and 5m-path runs → `out/bracket_zero_edge.csv` (all TF × L × {liq, stop1.0, stop0.5} × {adv, fav}, plus maker-TP E[ROE], per-M E[Δequity] and E[log]) and `out/entries_<tf>.csv.gz`.
- `work/extra.py`: ATR-adaptive L, TP-size sensitivity, 100-trade equity, suspect-bar sensitivity.
- `work/drift_check.py`: drift injection → `out/drift_injection_5m.csv`, `out/drift_breakeven_5m.csv`.
- `work/kelly.py`: binary Kelly → `out/kelly_binary.csv`.
- `work/make_table.py` and `work/short_table.py`: compact table and verdict.
- Stdout of every run is in `out/*_stdout.txt`.
