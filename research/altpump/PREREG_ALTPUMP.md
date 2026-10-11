# Alt pump and new-listing study (알트 급등·신규 상장): pre-registration

(한국어 설명: `README_KO.md`. 이 파일은 계산 전에 고정하는 규칙입니다. 결과를 본 뒤에는 바꾸지 않고, 바꿀 일이 생기면
`DEVIATIONS.md`에 따로 적습니다.)

**Status: DRAFT, written 2026-10-11 (KST), before any code for this study existed. No rule below has been run on these
data (no entry, exit, size, P&L or multiple of any variant, in any period). But before the rules were written, gross
forward returns close to three of them were computed on period 1 (section 21 b, c: the 7-day return after +30% days,
about the gross outcome of P1 / P2_X30_H7, and the 30-day return from a listing's day-1 open, about P3L / P3S_K1_H28,
with which side looked better), and long-side 30-day highs on all periods (21 a). Revised the same day after two code
and bias reviews (section 22 lists every change; still no rule run on these data).** The open questions of section 20 are closed by the
owners (or by the default written next to each) before the file is pinned. Pinning = `PREREG_ALTPUMP.sha256` over
this file and the code of section 18; the code refuses the `select`, `test`, `board` and `pass2` steps without a
matching pin. After the pin nothing here changes; a change goes to `research/altpump/DEVIATIONS.md` with its reason
and date.

Owners (2026-10-11): the goal is "1000달러로 1달만에 5000달러, 10000달러, 2만달러 ... 10만달러", and today: "규칙봇
매매법 36개 + 딥시크 44개 + 커스텀봇 후보 38개 + 새 신호 3개 매매법들 이렇게만 테스트하면 될까? 더 많은 매매법을
테스트해야하지 않을까? 욕심인가?" About 6,000 pre-registered strategy settings and over 1,000,000 custom-value
combinations on the big six coins found nothing that beats costs out of sample. More rules of the same kind
(price indicators on the same coins) mostly add lottery tickets. This study is a **different kind**: events (a pump
day, a listing, a cross-sectional breakout) on **every** USDT-M perpetual, delisted ones included, because the goal-50x
review (`angles.md` of the goal-50x study, section 6, idea 1) found that alts are the only place in 2020-2026 where a
x50-in-30-days tail exists at all (4 of 864 symbols went x50 or more within 30 days, 55 went x10 or more; long side,
measured at the highs, so an upper bound, not an outcome).

## 1. Question

On a point-in-time, survivorship-free universe of Binance USDT-M crypto perpetuals, does any of 28 fixed event rules
(pump-follow, pump-fade, new-listing, cross-sectional breakout), traded through one trend-hunt machine adapted to daily
bars or held for a fixed number of days, grow one wallet after all costs on two periods its choice never saw, by more
than the same machine fed with coin-flip sides and with random days? And, reported but never a pass: how often would
such a rule turn $1,000 into x5 to x100 within one calendar month?

## 2. Data

* `data/universe/klines_1d.csv.gz` (sha256 `ef52161f91188f53a39d0642c6857254816264e7cd3ae901e2b15d9730d38eb0`, checked
  at load against this value, which the pinned code holds as a constant, and against `data/universe/MANIFEST.json`;
  either mismatch stops the run, so a rebuilt file with a regenerated MANIFEST does not run). Daily (1d) klines of the 864 USDT-M
  perpetual symbols in the public archive (data.binance.vision), delisted and renamed ones included, 2020-01-01 to
  2026-08-31, columns `symbol, open_time, open, high, low, close, volume, quote_volume, count, taker_buy_quote_volume`.
  Day = the UTC day of `open_time`.
* A row with `volume = 0` is **no bar** (the archive pads delisted symbols with flat zero-volume rows: 52,713 rows).
  Volume in every rule = `quote_volume` (USDT).
* No funding, mark price, order book or intraday data in the first pass (costs: section 8; the second pass, section
  15, adds 5m bars, 5m mark price and funding for the symbols that matter).
* Nothing is downloaded for the first pass. Disk use under 100 MB (outputs only).

## 3. Universe

### 3.1 Symbol lives
* The **traded-day calendar** of a symbol = the UTC days on which it has a bar (`volume > 0`). It is structure, not
  price, and the code may read it for every day of the file at any time.
* A **life** starts at a symbol's first bar, or at a bar that follows **7 or more consecutive days without a bar**. A
  life ends at its last bar before such a stretch or before the end of the file. Indicators never cross lives: a new
  life starts its history from zero.
  * After **30 or more** days without a bar the new life is a **relisting** (9 symbols: CVC, CVX, SLP, CTK, LIT, TLM,
    ICP, MAVIA, AIA).
  * After **7 to 29** days it is a **pause restart** (3 symbols, from the calendar: AERGO from 2025-03-28 for 19 days,
    BNX from 2023-02-01 for 21 days, PUMP from 2025-06-14 for 26 days). A perpetual does not stop trading for weeks
    with positions left open: the exchange settles them (a delisting, a token swap or migration), so the life before
    the pause ends like a delisting (6.8). PUMP restarts in July 2025 and is probably a different token under the
    same ticker; the archive cannot tell, so the rule is the same for all three. Any threshold from 4 to 19 days gives
    the same lives on this file (the other stretches are 1 to 3 days).
* A stretch of **1 to 6 days without a bar inside a life** is a **gap** (103 in the file before this rule, 100 after
  it: 97 of them are the two archive holes below; the other 3 are one-day and three-day gaps of BNX in 2022). The days
  of a gap are unknown, not quiet: a position never holds through one (6.8), and no return or true range reads across
  one (4).
* **Partial days (archive holes).** A day on which at least 10 lives that cover it, and at least 10% of them, have no
  bar is a partial day. On this file (traded-day calendar, structure only): 2022-02-26 .. 28 (48 of 136 lives lack a
  bar, an alphabetical block FIL .. MKR ..) and 2022-04-01 .. 02 (49 of 140); every other day lacks at most about 1%.
  These are holes in the archive, not days without trading. P4 does not rank on a partial day (5).
* **Listing** (for P3) = the first bar of a symbol's first life or of a relisting life (day 0), except:
  * a life starting on 2020-01-01 (the archive's first day: BTC, ETH, BCH were listed before it);
  * a pause restart (above): the same ticker back within 30 days, the analogue of a rename successor;
  * a **rename successor**: the new symbol of a rename or token swap whose first bar comes within 60 days after the
    old symbol's last bar. Fixed list (old -> new): BTT -> 1000BTTC, LEND -> AAVE, COCOS -> COMBO, RNDR -> RENDER,
    GAL -> G, MATIC -> POL, KLAY -> KAIA, FTM -> S, DAR -> D, LIT -> HEI, EOS -> A, MKR -> SKY, FXS -> FRAX,
    OM -> MANTRA (14). A successor is a normal symbol in every other respect (its own life, tradable when section 3.3
    allows); it is just not a P3 event. Renames that came more than 60 days later (e.g. LUNA -> LUNA2 / 1000LUNC,
    TOMO -> VIC, KEEP and NU -> T, DODO -> DODOX, RAY -> RAYSOL) are listings of a new contract and count.
* **Delisting** = the end of a life before 2026-08-31, including the life before a pause (section 6.8: open
  positions close at that bar's close). No delisting announcement is known to the rules (the archive has none).

### 3.2 Excluded products (never tradable, never ranked)
Fixed list, 191 symbols, written here before any price was read (all with suffix USDT):
* **Index products (6)**: BTCDOM, DEFI, BLUEBIRD, FOOTBALL, DOTECO, ALL (ALL as in `research/universe/xs.py`).
* **Stable vs stable (1)**: USDC. Also, mechanically, any symbol-day of section 3.3 (d).
* **TradFi-referenced perpetuals (184)**: stocks, ETFs, commodities, pre-IPO contracts and gold-backed tokens. They are
  not crypto alts, they track outside markets and sessions, and all but PAXG (2025-03-27) appear only from 2025-12-11
  (inside period 2), so keeping them would change the universe between periods and would put stock listings into P3.
  Reason for going beyond the brief (which named stable-vs-stable and index products only): the question is about
  crypto alts.
  * Commodities and commodity-pegged (10): XAU, XAG, XPT, XPD, COPPER, NATGAS, BZ, CL, PAXG, XAUT.
  * ETFs, leveraged ETFs and equity indices (31): QQQ, SPY, IWM, SMH, XLE, XBI, GDX, URNM, EWJ, EWY, EWZ, EWT, SLX,
    SOXL, SOXS, TQQQ, SQQQ, TZA, UVXY, TBT, TMF, KORU, BITO, DRAM, KODEX200, CSOPSAMSUNG2L, CSOPSKHYNIX2L, MUU, SNXX,
    STXX, SKUU.
  * US-listed stocks (103): AAPL, MSFT, NVDA, GOOGL, AMZN, META, TSLA, AMD, INTC, MU, SNDK, AVGO, TSM, ASML, AMAT, LRCX,
    KLAC, QCOM, TXN, MRVL, SMCI, DELL, HPE, IBM, CSCO, ORCL, CRM, ADBE, NOW, SNOW, NET, CRWD, PANW, SHOP, UBER, PYPL,
    EBAY, WMT, COST, HD, KO, V, JPM, GS, BX, BRKB, DIS, NFLX, TTWO, RDDT, ZM, APP, LLY, MRK, MRNA, NVO, HIMS, TEM, COIN,
    HOOD, MSTR, STRC, CRCL, PLTR, MARA, IREN, BMNR, FWDI, CRWV, NBIS, ARM, COHR, WDC, CIEN, ALAB, CRDO, AAOI, AXTI, GLW,
    LITE, ONDS, ASTS, RKLB, IONQ, SOFI, RIVN, DKNG, GME, DJT, GEV, VRT, VST, BE, FLNC, CAT, TER, FLEX, NOK, USAR, PDD,
    BABA, SONY, CBRS.
  * Korean, Hong Kong and Chinese stocks (17): SAMSUNG, SAMSUNGEM, SKHYNIX, SKHY, HYUNDAI, NAVER, HANMI,
    LGELECTRONICS, HK0700, HK1810, TENCENT, MEITUAN, KUAISHOU, POPMART, ZHONGJI, GIGADEV, CXMT.
  * Pre-IPO contracts (6): ANTHROPIC, OPENAI, SPCX, MINIMAX, ZHIPU, UNITREE.
  * **Listing-batch rule (17)**: a symbol first listed on or after 2025-12-11 whose name was not recognised, and whose
    first bar falls on the same day as a TradFi symbol above, is treated as TradFi: BBX, BNC, BOT, BSP, DOS, EDGE,
    GRAM, INTW, INX, KSTR, LYTE, MVLL, PENG, PRL, RAM, SHAZ, SKDD. Recognised crypto tokens on such days are kept:
    CFG, MEGA, WEN. Unrecognised names on days without a TradFi listing are kept (e.g. O, ROBO, PAYP, BILL, CHIP). This
    rule may misclassify a few symbols of period 2's last nine months; section 20, Q2.
* The list lives in the code as constants (pinned). 673 symbols remain.

### 3.3 Tradable on day d (point in time)
A symbol is tradable on day d when all hold, each computed from bars up to and including day d:
(a) it is not excluded (3.2); (b) it has a bar on day d; (c) the **median quote volume of its bars among days d-6..d
(at least one bar, inside the current life) >= $5,000,000**; (d) the standard deviation of its last 30 daily log
close-to-close returns inside the life is >= 0.005 (a stable / pegged filter, the value of `research/universe/xs.py`;
skipped while the life has fewer than 31 bars).

**Why $5M** (fixed before this study read any volume value of this file; but see (iii)): (i) the unit cap of section
6.2 is 0.1% of this median, so a $5M name allows a $5,000 unit; with a stop 25% away the cap starts to bind at about
$62,000 of equity at r = 2%, $25,000 at r = 5% and $6,000 at r = 20% (section 14), all above the owners' $1,000 start;
(ii) the 0.10% slippage assumption (section 8) is plausible only for orders around 0.1% of a day's volume in names
trading several million dollars a day; (iii) a lower floor would put most fills in books too thin for the cost model,
and a higher one removes more small caps. **(iii) is not blind to the test periods:** the goal-50x look (section 21 a)
split its all-period long-side ceiling at $20M of start-day quote volume, periods 2 and 3 included, and the designer
knew from it that the long-side tail at the highs is thinner above that cut. The floor was not tuned on any outcome,
but its "keep the small caps" reason was informed by that look. The number of tradable symbols per day is reported by
`select` and `test` (section 16); the floor does not change after the pin.

## 4. Daily bars, indicators, timing

* One bar per symbol per UTC day. All indicators are computed per life, causally: the value on day d uses bars up to d.
* **True range**: TR on a life's first bar = high - low; afterwards max(high, previous close) - min(low, previous close).
  **ATR14**: the simple mean of the TRs so far while the life has fewer than 14 bars; on the 14th bar the mean of the
  first 14 TRs; afterwards Wilder's (13 x previous ATR + TR) / 14.
* **Daily return** r_d = close_d / close of the previous bar of the life - 1. **7-day return** = close_d / close of the
  bar 7 bars earlier in the life - 1. **Neither reads across a gap (3.1)**: on the first bar after a gap the daily
  return is not defined (a 2- to 7-day move is not a day's move, so P1 / P2 cannot fire on it), and the 7-day return
  is defined only when its 8 bars lie on 8 consecutive days (for the 7 bars after a gap a symbol is not ranked by P4,
  rather than ranking a 10-day return against 7-day ones). On the first bar after a gap the TR = high - low, as on a
  life's first bar (a TR spanning the gap would inflate ATR and D0 for weeks), and the stable filter's returns of 3.3
  (d) skip the return over the gap. All 100 gaps of the file lie in 2022 (period 1). **20-day mean volume** = mean quote volume of the 20 bars before day d (d
  excluded). **30-day high / low** = highest high / lowest low of the 30 bars before day d (d excluded).
* **A signal on day d is known at d's close (00:00 UTC of d+1). Its entry fills at the open of the next bar.** No
  rule on day d reads any value of day d+1 or later. Two closes use the traded-day calendar (structure) of the next
  day and are not decisions: the exchange's forced close at a delisting or before a pause, and the close before a day
  without a bar inside a life, whose prices are unknown (both 6.8). Neither depends on a price after day d.

## 5. Entries: 28 variants

Every variant is run as its own account (section 9); variants are never combined. A symbol holding a position ignores
new signals of the same variant, whichever side. Exit **M** = the trend-hunt machine (sections 6.4-6.5); exit **H** =
fixed hold (6.6), H = 7 days for P1 and P2 (a pump is a one-day event; a week is the natural "after" horizon) and
H = 28 days for P3 and P4 (listing and momentum are month-scale; 28 = four whole weeks).

| family | side | signal on day d (symbol tradable on d) | numbers | exits | variants |
|---|---|---|---|---|---|
| **P1 pump-follow** | long | r_d >= X and quote volume_d >= 3 x its 20-day mean; the life has >= 21 bars | X = 20%, 30%, 50% | M, H7 | 6 |
| **P2 pump-fade** | short | the same day as P1 | X = 20%, 30%, 50% | M, H7 | 6 |
| **P3 new listing** | long or short | d = day k-1 of a listing life (day 0 = the listing bar), so the entry fills at the open of day k | k = 1, 7 | M, H28 | 8 |
| **P4 cross-sectional breakout** | long | the symbol is among the top N of the tradable universe by 7-day return and close_d > its 30-day high, and this joint condition was false on the previous bar; the life has >= 31 bars; at least 3N tradable symbols have a 7-day return on d | N = 5, 10 | M, H28 | 4 |
| | short | mirror: bottom N by 7-day return and close_d < its 30-day low, false on the previous bar | N = 5, 10 | M, H28 | 4 |

**Total: 28 variants** (P1 6, P2 6, P3 8, P4 8). IDs: `P1_X{20,30,50}_{M,H7}`, `P2_X{20,30,50}_{M,H7}`,
`P3{L,S}_K{1,7}_{M,H28}`, `P4{L,S}_N{5,10}_{M,H28}`.

* The numbers are round brief / textbook values (a "+20% / +30% / +50% day", "3x volume", "the first full day / the
  first week after listing", "top 5 / top 10", "30-day high", "a week / four weeks"), not values chosen on any run.
* P1 and P2 use the same days, so each P2 variant is the exact opposite entry of its P1 variant; they still differ
  after costs and through the asymmetric exit.
* P3 on day k-1 = 0 or 6 uses the young ATR of section 4 and the young volume median of 3.3 (c). Ranking ties in P4:
  symbol name order.
* P4 is not ranked on a partial day (3.1): a third of the universe has no bar there, so "top N" would be wrong. Such a
  day never carries a P4 signal, and the "false on the previous bar" check looks past it (and past a gap) to the
  symbol's previous bar on a day that is not partial.

## 6. One position: size, leverage, pyramiding, exits (daily bars)

### 6.1 Entry fill
Market order at the open of the bar after the signal day. If the symbol has no bar on day d+1, the signal lapses
(counted). Reference price P0 = that open; fill price = P0 x (1 + 0.0010) long, P0 x (1 - 0.0010) short; taker 0.05%
of the fill notional.

### 6.2 First stop and unit
* R distance **D0 = min(2 x ATR14 of day d, 0.5 x P0)**; first stop S0 = P0 - D0 (long), P0 + D0 (short). The 50% cap
  keeps a long stop above zero after a huge listing-day range; it is counted when it binds.
* Unit risk **U = r x equity**, equity = wallet balance plus open positions marked at day d's closes. Unit quantity
  q = U / D0. Risk is price distance from reference prices; fees, slippage, funding and gaps are extra.
* Cuts, each counted: **liquidity** q x P0 <= 0.1% of the symbol's 7-day median quote volume (3.3 c); **margin** (6.3).
  A unit below $5 notional after a cut is not placed. The realised first-unit risk / intended U is reported.

### 6.3 Leverage and isolated margin
Leverage only reaches the size; it never sets it. Margin budget per position **B = equity / n_max** (n_max of section
7). Leverage L (an integer, set at the first entry, kept) = the smallest L in 1..10 with: (i) L allowed by the bracket
at the planned full notional N4 = 4 x q x P0; (ii) N4 / L <= B; (iii) **1/L - mmr >= 1.5 x D0 / P0** (liquidation at
least 1.5 times as far as the first stop; mmr = the bracket's maintenance margin rate at N4). If no L meets all three,
L = the largest L <= 10 meeting (i) and (iii); the first unit is cut only if it alone does not fit B at L, and each add
takes q or what is left of B at L. An entry or add whose margin exceeds the free wallet balance is cut to fit or
skipped. **Bracket table** (no historical brackets exist for 864 symbols; one conservative alt table for all):
notional <= $25,000: 10x, mmr 5%; <= $100,000: 5x, mmr 10%; <= $250,000: 3x, mmr 15%; above: 1x, mmr 25%. Liquidation
price (isolated, fees ignored): long = average entry x (1 - 1/L + mmr), short = average entry x (1 + 1/L - mmr).

### 6.4 Pyramiding (불타기), exit M only
As `research/hunt/PREREG_HUNT.md` 7.4, on daily bars:
* Three add levels, each tried once, in order. Long: level 1 = P0 + D0; level n+1 = the reference price of add n (its
  level, or the gapped open it filled at; a skipped add counts as filled at its level) + D0. Short mirror.
* An add is a stop-market order of quantity q; reference = the day's open when the open is already beyond the level,
  else the level moved f of the way to the bar's extreme beyond it (level + f x (high - level), long; the fill
  haircut of 6.7); slippage 0.10% and taker 0.05% as 6.1.
* On each add the one stop of the position moves to the tighter of the current stop and
  **S_req = (sum q_i x ref_i - U) / sum q_i** (long; short: (sum q_i x ref_i + U) / sum q_i), so the open risk
  sum q_i x (ref_i - stop) stays <= U. With full units filled at their levels (f = 0): after add 1 the stop is at P0,
  after add 2 at P0 + 0.667 D0, after add 3 at P0 + 1.25 D0; a hair-cut fill raises ref and so the stop. Stops never
  loosen.
* An add is skipped (counted) when the portfolio risk cap (section 7) would be exceeded after it, when margin, liquidity
  or the $5 minimum does not allow it, or when the liquidation price after it would not lie beyond the moved stop.

### 6.5 Exit M: chandelier trailing stop, nothing else
At each daily close from the entry day on: chandelier = highest high since the entry (the entry day included) - 3 x
ATR14 of that day (long); lowest low + 3 x ATR14 (short). The stop becomes the tighter of the current stop and the
chandelier, from the next bar. No take-profit, no time stop, no exit on another signal. The whole position exits at
the stop (stop-market: the stop price, or the open when the open is beyond it; slippage 0.10% against, taker 0.05%).

### 6.6 Exit H: fixed hold
Same entry, unit, leverage and first stop S0; no adds, no trailing. The position exits at the close of its H-th bar
(the entry day is bar 1), market: close x (1 - 0.0010) long / (1 + 0.0010) short, taker 0.05%, unless S0 or a forced
close (6.8) ends it first.

### 6.7 Worst order inside one daily bar (long; short mirror)
The order of prices inside a day is unknown; the worse order is always taken.
1. Open beyond the liquidation price: liquidated; the position's whole isolated margin is lost.
2. Open at or beyond the stop: exit at the open (a gap through the stop fills at the open).
3. The high does not reach the next untried add level and the low touches the stop: exit at the stop (hair-cut fill,
   below).
4. **The high reaches the next untried add level: every add level the bar reaches fills first, in order** (at the open
   if the open is already beyond it, else hair-cut as in 6.4), each moving the stop (6.4) and the liquidation price,
   **also when the low had already reached the old stop**. Then, if the day's low reaches the (moved) stop, the
   position exits there the same day. Filling first and exiting at the moved stop never loses less than exiting at the
   old stop without the adds (more units, a stop no looser, the haircut on every unit), so it is the worse order; this
   is `PREREG_HUNT.md` 7.6 step 4, corrected there for the same reason (its change 6). The entry day is treated the
   same way from its open on.
5. Exit H at the close (6.6), the forced closes of 6.8, then the chandelier update (6.5) and funding (section 8) at the
   close.

**Stop-fill haircut.** The daily file cannot show how far a fast day ran through a stop, and those days (squeezes,
crashes, pumps) are exactly the risk of P2, P3S, P4S and P1. A stop touched inside a bar therefore fills **f = 0.25 of
the way from the stop to the bar's extreme beyond it**: long fill = stop - f x (stop - low), short = stop + f x (high -
stop), then slippage 0.10% and taker as usual; a buy-stop add mirrors it (6.4). **A hair-cut fill at or beyond the
liquidation price is a liquidation** (the whole isolated margin is lost). f = 0.25 is a judgment, not a fitted number
(f = 0 is the most optimistic fill, f = 1 the bar's extreme); f = 0 and f = 0.5 are reported beside it (section 16) and
the owners may change it before the pin (section 20, Q13). The same f applies inside each 5m bar in the second pass.
**Liquidations on daily bars come only from an open beyond the liquidation price or from a hair-cut fill beyond it**:
they are a rough model, labelled so on every output; the 5m pass (section 15) measures them on the mark price. The
"worst order" above is about the order of stop and adds inside a bar; the haircut is the only allowance for how far a
stop is overrun.

### 6.8 Delisting, gaps, period end
* **Delisting**: a position on a symbol whose life ends (3.1, a pause included) closes at the close of the life's
  last bar, market, with slippage and taker (the exchange settles delisted contracts near that time).
* **Day without a bar inside a life** (a gap of 1 to 6 days, 3.1): the path through it is unknown (97 of the 100 gaps
  are archive holes on days the market traded), so no position holds through it: a position open at the close of the
  bar before such a day closes at that close, market, with slippage and taker ("close before a day without a bar").
  This censors positions at times set by the archive, not by price. A signal whose fill day has no bar lapses (6.1).
* **Period end**: a position still open at the last close of a period is marked at that close and flagged; no later
  price is read. A signal counts only if both its signal day and its fill day lie inside the period.

## 7. Portfolio: one wallet per account

* One wallet, compounding, one position per symbol (one-way mode).
* **n_max** open positions and a **total open risk cap**, where open risk of a position = max(0, sum q_i x (ref_i -
  stop)) (long; short mirror):
  * r <= 2%: n_max = 6, total open risk <= 4 x r (8% at r = 2%).
  * r >= 5% (goal board only): total open risk <= min(4 x r, 60%), n_max = floor(that cap / r): r = 5% -> 20% and 4
    positions; r = 10% -> 40% and 4; r = 20% -> 60% and 3.
  An entry or add is taken only if the total after it stays within the cap; otherwise it is skipped (counted).
* Several signals on the same day: taken in order of the 7-day median quote volume, largest first (ties: symbol name);
  a signal blocked by a limit is dropped, never queued.

## 8. Costs

* **Taker 0.05%** on every fill (entries, adds, exits, forced closes) and **slippage 0.10% against** on every fill (alt
  books are thin; the hunt study used 0.02% on large coins).
* **Funding: a fixed 0.03% per 8 hours of the position's notional, charged against every position, long or short.**
  A position open at a daily close pays one day there (3 x 8h: 08:00 and 16:00 of the day and 00:00 of the next, at
  the close); a position that exits during the day or at its close pays 2 x 8h for that day (08:00 and 16:00: the worse
  case, since the exit time inside a daily bar is unknown) at the exit price; an exit at the open pays nothing more
  (its 00:00 was in the previous close's charge). A month-end or bust close at the close has already paid the full
  day (one 8h period too many, conservative). The daily file has no funding; the real alt rate is often far larger and
  of either sign (-2% to +2% per 8 hours around pumps and listings). **Flag: this is an assumption, not data.** Every
  output carries the line "funding assumed 0.03%/8h"; the second pass uses the archived funding.
* **Cost x2** read: taker 0.10%, slippage 0.20%, funding 0.06% per 8 hours.

## 9. Accounts and metrics

* One continuous account per variant, risk size r and period: **$1,000** at the period start (the owners' figure),
  flat, compounding. Main size **r = 2%** (selection and test).
* **Monthly multiple** M_m = equity at the last daily close of UTC calendar month m / equity at the previous month's
  last close (the period start for the first month), equity marked at daily closes. A month without positions has
  M = 1.0.
* **Bust** = marked equity < $100 (10% of the start) at any daily close; the account stops there (positions closed at
  that close) and the remaining months count as bust (ln M of the bust month as realised, later months excluded from
  means and reported as bust).
* Reported per run: mean, median and quartiles of ln M; share of months with M >= 2, >= 5, >= 10 and < 0.9; worst
  month; max drawdown at daily closes; end multiple; bust; positions per month; adds per position and the share
  reaching each add level; per position P&L in U, win share, share of total profit from the top 10% of positions;
  gaps through stops, liquidations (with the daily-bar label of 6.7), delisting closes, closes before a day without a
  bar, D0 caps, lapsed signals, cuts and skips by reason; funding paid as a share of gross P&L; per year and per
  side.

## 10. Periods and data access

| period | dates (signal day, UTC) | months | role |
|---|---|---|---|
| **1 select** | 2021-08-01 .. 2024-07-01 | 35 (2021-08 .. 2024-06) | choice |
| **2 test** | 2024-07-01 .. 2026-09-01 | 26 (2024-07 .. 2026-08) | judged once |
| **3 test** | 2020-01-01 .. 2021-08-01 | 19 (2020-01 .. 2021-07) | judged once |

* Each step keeps price and quote-volume values only from 60 days before its period's start (period 3: from
  2020-01-01) to its end: `select` the window of period 1; `test` and `pass2` those of periods 2 and 3; `board` all
  three (it shows period 1 too, labelled). The file is one gzip CSV, so it is parsed whole, but the loader discards
  every value outside the step's windows chunk by chunk while reading (`volume` keeps only whether it is > 0), and a
  market built outside them refuses to run (tests: the select table is identical whether or not the other values are
  loaded). `select` therefore holds the last 60 days of period 3 (2021-06-02 .. 2021-07-31) as indicator warm-up
  only: no signal, fill, position or outcome uses them. The traded-day calendar (3.1) is read for the whole file.
* Period 3 starts at the archive's first day: no warm-up, so its first 30 days have few or no P1, P2 and P4 signals.

## 11. Selection (period 1 only)

11.1 **Runs**: all 28 variants at r = 2%, normal costs and cost x2.

11.2 **Eligible**: at r = 2%: at least **35 positions** opened (one a month), **mean monthly ln M > 0**, **no bust**;
and at cost x2 mean monthly ln M > 0 and no bust.

11.3 **Picks**: the eligible variants ranked by mean monthly ln M (ties: higher median monthly ln M, then the order of
section 5); walk down the ranking and take a variant unless its **group** already has a pick; stop at **K = 5**. The
six groups are P1, P2, P3 long, P3 short, P4 long, P4 short. (The brief said "at most one per family"; with four
families that would cap K at 4, so (family, side) is the unit; P1 and P2 are one side each.) Fewer than five
groups with an eligible variant: fewer picks, K = their number. **None eligible**: the study fails at selection; the
single variant with the highest mean monthly ln M is still run on both test periods, labelled "no pick, fail".

11.4 The picks are written to `research/altpump/out/pick.json`, and its sha256 is appended to `PREREG_ALTPUMP.sha256`
before any value of period 2, or of period 3 outside the warm-up of section 10, is loaded (`select` never loads
them). Each test period is run **once**. **The other variants are not run on the test periods.**

## 12. Controls (2,000 seeds each, same machine)

Both controls use sections 6 to 9 exactly (sizing, leverage, pyramiding, exits, portfolio, costs), the pick's exit
type, r = 2% and the test period. Seed = sha256 of ("altpump", control, variant id, period, r, seed number).
* **(a) Coin-flip sides**: the pick's signals (every signal, taken or not) at the same symbols and days, each side
  drawn by a fair coin. **What it measures: side, including the market's direction.** Every pick is one-sided (all
  long or all short); a one-sided account carries the market factor while random sides cancel it. In a trending test
  period (period 3 was an alt bull market) a no-skill long rule beats most coin-flip seeds, and in a flat one both
  tails of the rank are wider than the coin flip's (synthetic check: P(p_rank < 0.05) = 0.10 and P(p_rank > 0.95) =
  0.21 for a no-skill long rule in zero-drift worlds with a common factor). So (a) does not test timing.
* **(b) Random days, same pattern**: the timing control. For each symbol, the **pool** = the days on which the variant
  could have fired apart from its event: tradable (3.3), in the period with the next day in it and holding a bar, and
  the variant's own non-event conditions (P1 and P2: the life has >= 21 bars and the daily return is defined, i.e. not
  the first bar after a gap (4); P4: >= 31 bars, a defined 7-day return, at least 3N ranked symbols, not a partial
  day; P3: none). **The whole signal calendar is moved by common random offsets**: per seed, offsets k_1, k_2, ...
  (uniform on 0 .. D-1, D = the period's signal days; 1,000 of them) are drawn once and are **the same for every
  symbol**; each pick signal that lies in its symbol's pool (a signal whose next day has no bar lapsed and is left out)
  goes from signal day d to p0 + (d - p0 + k_j) mod D for the first j that lands it on a pool day of its symbol. Sides
  stay. So the signals of different symbols on one day stay together as long as they land in their pools (a
  market-wide pump day, a P4 breakout day or a listing batch stays one busy day, and the n_max and risk-cap cuts of that
  day hit the control as they hit the pick), each symbol keeps its signal count and the spacing of its signals (a
  multi-day pump fires P1 / P2 on consecutive days and the repeats are skipped because the symbol already holds a
  position; P4 can re-fire inside a hold), and a signal whose symbol cannot trade on its k_1 day (not listed yet,
  delisted, too young, under the volume floor) takes the next common offset instead of being dropped. Days the rule
  could never trade (a listing's first 20-30 days, which the period-1 look found falling on average) are not in the
  pool. **Validity check (reported beside the verdict, never a rule):** each comparison reports the pick's positions,
  the control's mean positions and their ratio, flagged "not comparable" outside 0.8 .. 1.2, and the share of control
  signals that moved with k_1 (kept their same-day company) and that no offset placed (dropped).

For each control and test month m: **d_m = ln M_m(pick) - mean over the 2,000 seeds of ln M_m(control seed)**.
Synthetic checks of (b). The first review replaced a uniform-day draw with one circular offset per symbol over its
pool (zero-edge random walks, 100 repetitions x 200 seeds: a pick firing in 3-day clusters on one symbol had 81
positions against 81.3 for that control, 191 for the uniform draw). The second review found that a per-symbol offset
spreads signals that fire on many symbols on the same day: with n_max and the risk cap cutting the pick's busy days,
that control opened 2.4 to 3.6 times the pick's positions and its bias changed sign with the market's drift (zero-edge
GBM alts with a common factor, a pick firing on half the symbols on 20 days: long H7, zero drift, mean d +0.016 per
month and P(p_boot < 0.05) 0.27; exit M, P(p_boot < 0.05) up to 0.69). With the common offsets: positions ratio 1.00
and P(p_boot < 0.05) 0.05, P(p_rank < 0.05) 0.04 over 100 such worlds (the test in `tests/test_altpump.py`); in worlds
where 60% of the symbols list and 40% delist inside the period, ratio 1.0 for signals spread over the days and about
1.3 for the same-day clustered pick (some signals of a busy day take a later offset), with null rejections of
p_boot and p_rank at 2 to 8% in every setting tried (long and short, zero and +-0.2% daily drift, exits M and H). On a
synthetic universe with listings and delistings, a single common offset that dropped every signal landing outside its
pool lost half of the P3 signals (ratio about 0.4); the offset sequence keeps them (ratio 0.9 to 1.0).

## 13. Pass rule (each pick, r = 2%, all must hold)

* **T0 activity**: at least 26 positions in period 2 and at least 19 in period 3 (one a month), no bust in either.
* **T1 positive**: mean monthly ln M > 0 after all costs **in period 2 and in period 3**.
* **T2 better than both controls in both periods**: for each period p in {2, 3} and control c in {a, b}:
  **p_boot = the larger of** (i) a studentized month bootstrap (bootstrap-t: resample the period's months with
  replacement 10,000 times; t* = (mean* - mean d) / se*; p = (1 + #{t* >= t}) / 10,001 with t = mean d / se) and (ii)
  a sign-flip test (each month's d times a random sign, 10,000 times; p = (1 + #{mean* >= mean d}) / 10,001); one seed
  stream as section 12 with "boot". p_rank = (1 + seeds whose mean monthly ln M >= the pick's) / 2,001. **p_pick =
  the largest of these eight numbers** (the pick must win every comparison). A pick failing T0 or T1 gets p_pick = 1
  and stays in the family.
  * Why not the plain percentile bootstrap (the share of resampled means <= 0): with 19 or 26 months it rejects too
    often, most for left-skewed monthly d, the shape of the short-side picks (many small wins, rare squeezes):
    synthetic nulls at nominal 5%, n = 19: normal 6.3%, left-skewed (a mirrored lognormal, sigma 1) 16.9%. The
    bootstrap-t corrects most of the skew and the sign flip is exact for a symmetric null; the larger of the two
    rejects 4.3% (normal), 9.9% (left-skewed), 7.5% (mildly left-skewed, sigma 0.5), 5.3% (t, 3 df) and 0.9%
    (right-skewed) under the same nulls (n = 26: 3.7%, 9.5%, 6.5%, 5.1%, 1.3%). It is still somewhat liberal under
    strong left skew; the rank comparisons and the eight-way maximum add to it.
  * What T2 protects: control (a) protects against a rule whose gain is only its side (12 a); **control (b) is the
    timing control** (12 b; its positions validity check is reported beside each comparison). A pick must beat both.
  * **What T2 cannot see: risk that did not happen in the test months.** A short-side pick with no edge whose losses
    come as rare squeezes ("many small wins, rare squeezes") passes every test on 19 or 26 months whenever no squeeze
    lands in them, and the larger of the two p's does not help (synthetic, mean-zero monthly d: squeezes in 3-5% of
    months pass at nominal 5% in 20-50% of single periods, 5-26% of both). The control seeds do run into squeezes, so
    a pick that missed them by luck also ranks high. The second pass (15) uses the same months and cannot fix this.
    Therefore each test also reports a **squeeze stress read** (never a pass rule): the pick's worst single position in
    U and its number of stop overruns (positions that lost more than 1.5 U: a gap, a fast day or a liquidation),
    against the overrun rate of the control seeds' positions (a and b pooled) on the same symbols and side, the count
    expected at that rate and the Poisson chance of seeing as few as the pick did.
* **T3 multiple testing**: Benjamini-Hochberg at **q = 0.10** over the K picks' p_pick; the pick's p_pick must be
  rejected.

**PASS (first pass) = T0 to T3.** A pass goes to the second pass (section 15); only a second-pass pass is a result
the owners can act on (section 17). Cost x2 on the test periods is reported as a label ("survives cost x2": yes / no),
not a rule.

## 14. Goal board (reported, never a pass)

The owners' own measure. For each pick, period 2 and period 3 (period 1 also shown, labelled "chosen here"), and
**r = 0.5%, 2%, 5%, 10%, 20%** (caps of section 7):
* **Each UTC calendar month starts a fresh wallet of $1,000**, flat, takes the pick's signals whose fill day lies in
  the month, and ends at the month's last daily close, open positions closed there with slippage and taker (no price
  of the next month is read). A month busts when marked equity < $100 at any daily close; it stops there.
* Reported per pick, period and r: the share of months ending **>= x5, x10, x20, x30, x50, x100** ($5,000 ..
  $100,000), the share busted, the median month and the **worst month**; the number of months; and how the machine
  actually ran at that size: the realised first-unit risk / intended, adds per position, the share of positions
  reaching each add level, add skips by reason and entry cuts by reason (the pick, and each control pooled).
* **At high r the margin budget usually leaves no room for adds.** B = equity / n_max (6.3) and the 1.5x liquidation
  rule keeps alt leverage low (often 1x or 2x), so at r = 10% and 20% the first unit uses up B and the three adds are
  skipped (synthetic trend: 3 adds per position at r = 0.5%, 2 at 2%, 1 at 5%, 0 at 10% and 20%, with the first unit
  cut to two thirds of U at 20%). Those rows show a one-unit trailing stop, not the pyramiding machine.
* Beside it, pooled over the 2,000 seeds each: **the luck reference**, the same table for control (b), the pick's own
  signals on random days with the pick's side (12 b) ("luck gives this much": every pick is one-sided, and a no-skill
  one-sided rule in a trending month reaches high multiples about this often); and the coin-flip control (a), labelled
  **"luck without the market side"** (random sides cancel the market's direction, so in a trending period it
  understates what luck gives a one-sided pick: synthetic bull world, r = 20%, a no-skill long pick reached x2 in 9.9%
  of months, coin flip 2.5%, the same signals on random days with the long side 11.4%).
* The goal-50x baseline (coin flip on the big four at 1-minute fills: about 1% of months reach x50) is quoted for
  scale. Nothing on this board is a pass rule, and no variant or size is chosen from it.

## 15. Second pass: 5m fills (written now, run only for picks that PASS section 13)

* **Data**: for every symbol that a passing pick or its controls traded in a test period: 5m klines, 5m mark-price
  klines and funding rates from data.binance.vision (monthly files, `.CHECKSUM`-verified), the test periods plus one
  month before each. Converted to compact per-symbol arrays, each zip deleted after conversion. **On the rented compute
  server** if the local free disk would fall under 1 GB at any time (3.3 GB free on 2026-10-11); at most 2 downloads
  at a time.
* **Missing or incomplete 5m data**: a day of the period with a daily bar and no 5m bars, or whose 5m bars do not
  reach the daily high and low (a hole inside the day), runs on its daily bar with the order and haircut of 6.7. No
  position is closed early because data will be missing (that would escape a move the daily file shows). Before the
  run, the symbol-months with daily bars and no 5m klines file are listed from the calendar; `pass2 run` refuses while
  any is missing unless each is written in `DEVIATIONS.md` (as listed, e.g. `p2 SYMUSDT 2024-07`; the code checks
  every one and names those not written) and the run is started with `--accept-missing`. Mark price
  missing: the 5m price bars stand in. A symbol-day without an archived funding event (file missing) pays the fixed
  charge of section 8. All of these are counted in `pass2.json`.
* **Run once**: `pass2 run` refuses while `out/pass2.json` exists, `pass2 fetch` refuses after the run, and `pass2.json`
  carries the sha256 of the sorted cache file list (name, size, sha256 of each file), so the cache a verdict ran on is
  fixed. `test`, `board` and `pass2 run` append the sha256 of their output (`test.json`, `board.json`, `pass2.json`) to
  `PREREG_ALTPUMP.sha256` when they write it; every later step checks those files against their lines, `pass2`
  refuses without a pinned `test.json`, and a step whose output line is there refuses to run again (moving the file
  aside does not help) unless `DEVIATIONS.md` names that sha256 (a rerun after a bug fix, 17). The superseded line stays
  in the pin file.
* **Run**: signals, universe and sizing exactly as the first pass (daily). Fills, stops, adds, chandelier updates
  (still at daily closes) and liquidation run on the 5m bars in time order with the order of `PREREG_HUNT.md` 7.6
  and 6.7 here (open beyond liquidation, open beyond the stop; a bar reaching the next add level fills every add level
  it reaches first and then checks the moved stop; a bar reaching no add level checks the stop); **liquidation on 5m
  mark price**; the stop-fill haircut of 6.7 inside each 5m bar; **funding = each archived funding event** at its time on
  every open position (sign as paid or received; on a day run on its daily bar, all of the day's events are charged
  before the bar). Taker 0.05% and slippage 0.10% as before. The closes of 6.8 stay.
* **Rule**: T0 to T3 recomputed on the 5m run for the passing picks (controls re-run on 5m too; BH over the same K
  picks, with the first-pass failures at p = 1). **A pick that fails here is labelled "failed (5m)"**, whatever its
  first pass said. The goal board is redone on 5m and replaces the daily one.

## 16. Other reads (reported, never a pass)

* The select table of all 28 variants (period 1, both cost levels) and the daily tradable-universe size per period
  (min, median, max).
* For each pick on the test periods: the r = 0.5% account, cost x2, per year, per side, long-only and short-only
  halves of the coin-flip control, the share of P&L from the single best position, and the same pick without the
  TradFi exclusion (period 2 only, to show what 3.2 changed).
* Funding sensitivity on the test periods: 0% and 0.10% per 8 hours.
* Stop-fill haircut sensitivity (6.7): f = 0 and f = 0.5, for all 28 variants on period 1 (beside the select table;
  the choice uses f = 0.25 only) and for each pick on the test periods.
* For each pick and test period: the squeeze stress read (13) and the positions validity check of both controls
  (12 b).

## 17. What a result means, and after

| result | then |
|---|---|
| PASS on 5m (section 15) | a **forward paper shadow** of the pick(s) exactly as here, on the paper bot server, only after the owners' go. **No real money** from this study without the owners' separate decision after at least 30 days of forward data |
| PASS on daily, fail on 5m | "failed (5m)": recorded with every number; not a candidate |
| fail (any T) | recorded as a fail with every number. No tuning on the test periods |
| no pick | as fail |

* **Nothing is tuned after a test period is seen.** A bug found after a test run is written in `DEVIATIONS.md`, fixed,
  the test rerun once, and both results shown. Any changed rule (families, numbers, exits, universe, costs) is a v2: it
  needs its own pre-registration and can be judged only on data after its fixing date (all three periods are spent).
* Even a pass shows an edge on two past periods. It does not make x50 in a month likely; the goal board says how
  often it happened, and the random-day board with the pick's side (14) says how often luck did the same.
* Every result, pass or fail, goes into `research/altpump/RESULTS_KO.md` and the owners' summary.

## 18. Code, compute, reproducibility

* Code (to be written after this draft, before the pin): `research/altpump/altpump.py` (load and checksum, lives and
  listings, exclusions, point-in-time universe, indicators, the 28 entries, the position machine of section 6, the
  portfolio, controls, bootstrap and BH, goal board, the second-pass runner; CLI `select`, `test`, `board`, `report`,
  `pass2`; pin check against `PREREG_ALTPUMP.sha256` like `research/fullgrid/run.py`).
  `tests/test_altpump.py` on **synthetic data only**: worst-order fills (gap through the stop at the open; a bar
  reaching an add level and the stop: every reached add first, a second reached add too, then the moved stop; a bar
  reaching no add level: the stop at once); the stop-fill haircut (long, short, adds, a fill beyond
  liquidation liquidates); no look-ahead (an entry decided on day d never reads day d+1: changing every value of d+1
  onward leaves the day-d signal and size unchanged); listing day 0, archive-start and rename-successor handling,
  relisting after 30 days, a 7-29-day pause (new life, no listing, the position closed at the last bar); the close
  before a day without a bar; partial days (P4 not ranked, the event check looks past them); no daily or 7-day return
  and no TR across a gap; delisting closes at the last bar's close; the universe floor point in time (a later volume spike does not make an earlier day tradable);
  values outside a step's window never loaded; the pyramiding stop formula (P0, P0 + 0.667 D0, P0 + 1.25 D0 with full
  units); leverage choice and the 1.5x liquidation rule; caps; funding (the exit day included); control (b)'s pools
  and common offsets (same-day signals of different symbols stay together, the count is kept), a zero-edge pick
  clustered within or across symbols not favoured by it (about the pick's positions, null rejections near 5%); the
  positions validity check and the squeeze stress read; bootstrap p (size under a skewed null) and BH on known inputs;
  goal-board arithmetic (fresh $1,000, thresholds, bust), its add counts and the luck reference (random days, the
  pick's side); the pin (the running code must be the pinned code; the data file must be the one of section 2);
  run-once guards (outputs pinned when written, a rerun only with a DEVIATIONS entry naming the old sha256, pass2 only
  on a pinned test.json, each missing 5m month written in DEVIATIONS); the second pass (5m order, mark-price
  liquidation, funding events and the fixed fallback, a day without 5m data run on its daily bar).
* Pin: `PREREG_ALTPUMP.sha256` lists the sha256 of this file and `altpump.py`; `pick.json` is appended after
  selection, and `test.json`, `board.json` and `pass2.json` when they are written (15). The steps refuse unless the
  code that is running (not only the copy under `--root`) has the pinned sha256, and every output carries that sha256.
* Outputs: `research/altpump/out/` (`select.json`, `pick.json`, `test.json`, `board.json`, `pass2.json`,
  `RESULTS_KO.md` later), each with the git commit, the pin it ran under and the value windows it loaded. Under 100 MB.
* Compute: one process at a time (4 shared cores). Select = 112 accounts (28 variants x 2 cost levels + 2 haircut
  sensitivities); test = K picks x 2 periods x (1 + 6 sensitivities + 4,000 controls); board = K x 3 periods x 5
  sizes x (1 + 2,000 random-day + 2,000 coin-flip seeds) monthly wallets. Light on daily bars.
* This study touches nothing of the rule bot, its trading path or deploy files, the candidate league, the full grid's
  pinned files, the hunt, newinfo or regime-gate studies, or any account.

## 19. Not in this study

* Dump-follow and dump-bounce (the mirrors of P1 and P2 after a -X% day), funding-extreme entries, order-flow or
  open-interest signals, liquidation cascades, macro releases: other angles of the goal-50x review, each needing its
  own file.
* Intraday entries (the first pass is daily by design; the second pass only re-fills daily signals).
* Per-symbol numbers, combinations of variants, maker orders, partial take-profits, a regime gate, an AI judgment
  layer.
* Delisting announcements (not in any archive).

## 20. Open questions (closed before the pin; default in brackets)

1. **Volume floor** $5M on the 7-day median (3.3); its third reason is not blind to periods 2 and 3 (3.3, 21 a).
   [Keep]
2. **TradFi exclusion** by a fixed list and the listing-batch rule (3.2). A Binance `exchangeInfo` snapshot fetched on
   the paper bot server (the machine there reaches fapi) could confirm the product type of every symbol still listed;
   if the owners supply it before the pin, it decides the symbols it covers and every disagreement is listed in
   `DEVIATIONS.md` before `select`. [Fixed list and batch rule as written]
3. **Funding** fixed at 0.03%/8h against every position (section 8). [Keep; real funding in the second pass;
   sensitivity in 16]
4. **K = 5 with six (family, side) groups** instead of "one per family" (11.3). [As written]
5. **Main size r = 2%** for selection and test (the brief fixed the board sizes, not this one). [Keep]
6. **One bracket table** for every symbol (6.3); real alt brackets are often tighter. [Keep; the second pass keeps it
   too]
7. **Rename list, the 30-day relisting rule, and the 7-day pause rule** (3.1): a 7-29-day stop ends the life and the
   restart is not a P3 listing (AERGO, BNX, PUMP; PUMP may be a new token). [As written]
8. **Period 1 is not blind** (section 21). It is the selection period, so this weakens only the selection, not the
   test. [Accept, disclosed]
9. **Power**: period 3 has 19 months and a thin universe in 2020; T2 requires winning eight comparisons. A real but
   small edge may fail. [Accept]
10. **Cost x2 is a label on the test periods**, not a rule (the brief's test rule is "positive and significant in both
    periods"). [Keep]
11. **Goal board months close open positions at the month end** (section 14), which cuts long holds. [Keep; the
    continuous account of section 9 is the judged one]
12. **Additions not in the brief**: the D0 cap at 50% of P0; the young ATR and young volume median; the stable filter
    (3.3 d); the TradFi exclusion; lives, renames and relistings; the margin budget B and n_max; the 0.1% liquidity cap;
    the add skip when liquidation would not lie beyond the moved stop; same-day order by liquidity; P4's "false on the
    previous bar" and the 3N universe minimum; H = 7 / 28; the 60-day warm-up read window; the stop-fill haircut; the
    closes before a pause and before a day without a bar; partial days. [Keep]
13. **Stop-fill haircut f = 0.25** (6.7) in the rule, for both passes and every control; f = 0 and 0.5 reported
    (16). f = 0 was the draft's choice and is the most optimistic fill on fast days. [f = 0.25]
14. **Squeeze risk on the short side** (13): a short pick can pass with no edge when no squeeze fell in its test
    months; the stress read is reported, not a rule. **Control (b)'s positions check** (12 b) is reported, not a rule.
    [Accept, reported]

## 21. Before this file was fixed

* **No rule of this study was run.** No code existed, and no entry, exit, size, P&L or multiple of any variant above
  was computed on the daily file for any period. **But gross forward returns close to three of the rules were**: on
  period 1, the 7-day close-to-close return after +30% days (about the gross outcome of P1 / P2_X30_H7) and the
  30-day return from a listing's day-1 open (about P3L / P3S_K1_H28), with which side looked better (b, c below); on
  all periods, long-side 30-day highs (a).
* **Structure read for this file** (2026-10-11): `MANIFEST.json` (symbol list, per-symbol first, last and last-traded
  dates, row counts) and, from the data file, only `symbol`, `open_time` and whether `volume > 0` (the traded-day
  calendar). No price, return or quote-volume value was read. Facts used above: 864 symbols, first day 2020-01-01,
  last 2026-08-31; first-bar counts per period (all symbols / after the 3.2 exclusions): period 3: 120 / 117, period 1:
  185 / 182, period 2: 559 / 374 (symbols with any bar in the period: 120 / 117, 302 / 297, 827 / 639); 9 symbols
  with a stretch of >= 30 days without a bar and about 50 with short ones (mostly 1 to 3 days, e.g. LTC 2022-02-26 ..
  2022-02-28); the TradFi symbols' first bars all on or after 2025-12-11 (PAXG excepted), in batches on the same days
  (which gave the batch rule). The exclusion lists were written from symbol names and these dates. The review of
  section 22 read the same calendar only (no value): the 103 stretches of 1 to 29 days without a bar split into 97
  on the archive-hole days 2022-02-26 .. 28 and 2022-04-01 .. 02, 3 short gaps of BNX, and the 3 pauses of 3.1.
* **The period-1 descriptive look (disclosed).** On 2026-10-11 the goal-50x review (scratchpad
  `goal50/scripts/universe_base.py`, numbers in its `angles.md`, section 6, idea 1; not in this repository) computed on
  the same daily file:
  * (a) **all periods, periods 2 and 3 included**: 30-day forward highest high / open for every symbol-day (counts of
    windows and symbols reaching x2 .. x50, the 15 symbols with the largest 30-day rise and their dates, the share of
    windows rising enough for x50 at 10x, 20x and 50x, and of those the share whose 30-day low stayed above the
    liquidation price), **and the same ceiling split by liquidity: windows whose start-day quote volume was >= $20M**
    (share of windows and number of symbols reaching x2, x5, x10, x50). This is a long-side ceiling at the highs, not
    the outcome of any rule; it does reveal that periods 2 and 3 contain large long-side tails, some of the largest
    names, and how the tail thins among liquid names (which informed reason (iii) of the volume floor, 3.3).
  * (b) **period 1 only**, symbols with previous-day quote volume >= $20M: the 444 days with a close-to-close rise
    >= +30% and the days with a fall <= -25%: next-day and 7-day close-to-close mean, median, share positive, 5% and
    95% quantiles. Read: after +30% days the next-day and 7-day medians were negative (fade side) while the 7-day upper
    tail was large (follow side).
  * (c) **period 1 only**: the 185 symbols first listed in period 1: listing-day return, 30-day return from the day-0
    and day-1 opens, the share reaching x2 and x5 within 30 days, falling to half, and rising +50% at some point.
    Read: the 30-day median from the day-1 open was negative (short side), and about a quarter squeezed +50% or more
    (danger for shorts).
  The main session and probably the owners have read these numbers. Consequences: period 1 cannot be a blind
  selection period (it is used only for selection, as section 11 requires); the variant list holds both sides of every
  event family and was written from the brief, but several of its numbers match the look: H = 7 and H = 28 match its
  7-day and 30-day horizons; P1 / P2's X = 30% matches its +30% day; P3's K = 1 (entry at the day-1 open, held about
  a month) is its "day-1 open -> 30 days" statistic, whose median was negative (short side); and the D0 cap at 50% of
  P0 puts a young P3 short's first stop exactly at its "+50% squeeze" threshold, which about a quarter of period-1
  listings reached. No rule was judged by these numbers. **Periods 2 and 3 were not used to choose anything, but they
  are not untouched**: their long-side 30-day highs, the names and dates of the largest risers, and the liquid-$20M
  split (a) were computed and seen.
* **Earlier related tests whose results are known** (they overlap the test periods): `research/universe/xs.py` (daily
  cross-sectional momentum top-K, long-short and 1-day reversal on the same file; failed), `research/maker` round 2 B
  (the strongest coin of the top 20, long; failed in its test), `research/famous` (strongest coin, 28 days; failed),
  `research/library` (4h volume x3 surge; failed). P4 is in the same spirit as the first two, with a different entry
  (an event with a 30-day breakout) and the stop machine. Their outcomes were known to the designer; no number here was
  set from them.
* The machine (stop 2 ATR, three adds at +1 D0 with open risk held at one unit, chandelier 3 ATR, no take-profit) is
  `PREREG_HUNT.md` sections 7.4-7.6 adapted to daily bars, from the owners' trend-hunt brief, not from any run on
  these data.

## 22. Changes after the reviews (2026-10-11, before the pin; no rule run on these data)

A code and bias review of the draft and its code (synthetic data only) found the following; each is now part of the
sections above, with a synthetic regression test in `tests/test_altpump.py`.

| # | change | sections |
|---|---|---|
| 1 | Control (b) moves the pick's own signal pattern in time (one circular offset per symbol over its pool) instead of drawing the same count of uniform days: clustered signals had made (b) open more positions and pay more costs, biasing T2 toward the pick (replaced by common offsets for all symbols, change 17) | 12 |
| 2 | Control (b)'s pool keeps only days the variant could trade apart from its event (life >= 21 / 31 bars, 3N ranked, not partial): young-listing days had dragged long controls down and helped short ones | 12 |
| 3 | p_boot = the larger of a bootstrap-t and a sign-flip p, not the percentile bootstrap (too many rejections with 19-26 months and left-skewed d) | 13 |
| 4 | Control (a) stated as a side-and-market control, not a timing control; (b) is the timing control | 12, 13, README_KO |
| 5 | Second pass: a day without (complete) 5m data runs on its daily bar instead of closing at the previous close (that escaped moves the daily file shows); `pass2 run` refuses missing 5m months without a DEVIATIONS entry; run-once guards and a cache digest | 15 |
| 6 | Disclosure of the all-period look completed (liquid-$20M split; K = 1 and the 50% D0 cap overlaps); "untouched" removed | 3.3, 21, README_KO |
| 7 | Values outside a step's window are discarded at load, and a market outside them refuses to build | 10, 11.4 |
| 8 | Stop-fill haircut f = 0.25 on stops and adds (a fill beyond liquidation liquidates); f = 0 and 0.5 reported | 6.4, 6.7, 16, 20 |
| 9 | README_KO: test periods not "untouched"; the x50 / x10 counts labelled as a ceiling at the highs incl. the test periods; the 10-20% figure labelled a guess | README_KO |
| 10 | Days without a bar inside a life (97 of 100 are archive holes): no position holds through them; partial days are not ranked by P4 | 3.1, 5, 6.8 |
| 11 | A 7-29-day stop ends the life (forced close, fresh indicators, not a P3 listing): AERGO, BNX, PUMP | 3.1, 6.8 |
| 12 | Funding on the exit day (2 x 8h for an exit during or at the end of the day); pass 2: a symbol-day without archived events pays the fixed charge | 8, 15 |
| 13 | `test`, `board` and `pass2 run` / `fetch` refuse a second run | 15, 18 |
| 14 | The goal board reports adds per position, the share reaching each add, add skips and entry cuts by reason; at high r the machine is a one-unit trailing stop | 14 |

A second code and bias review (synthetic data, and the traded-day calendar only; no value of the file read) found the
following; each is now part of the sections above, with a synthetic regression test.

| # | change | sections |
|---|---|---|
| 15 | A bar reaching both the next add level and the stop fills every add level it reaches first and then checks the moved stop (the draft took the stop first, and after an add exited before a second reached add): with the haircut the draft's order was the more favourable one, against "the worse order is always taken"; the hunt study had made the same correction (`PREREG_HUNT.md` change 6), and section 15's quote of its 7.6 is corrected | 6.7, 15, 18, README_KO |
| 16 | No daily return, 7-day return or true range reads across a gap of 1 to 6 days (all 100 in 2022, period 1): P1 / P2 no longer fire on a multi-day move, P4 no longer ranks a 10-day return against 7-day ones, ATR is not inflated by the gap; control (b)'s pools follow | 3.1, 4, 12 |
| 17 | Control (b) moves the whole signal calendar by common offsets instead of one offset per symbol: same-day signals of different symbols (pump days, breakouts, listing batches) had been spread, so the control opened 2.4-3.6x the pick's positions and its bias changed sign with the market's drift. Positions validity check reported | 12, 13, 16, README_KO |
| 18 | Goal board: the luck reference is the pick's signals on random days with its own side; the coin flip is "luck without the market side" (it cancels the market's direction and understated luck for a one-sided pick) | 14, 17, README_KO |
| 19 | T2 cannot see a squeeze that did not happen in the test months (a no-edge short pick passes in 20-56% of single periods at 3-5% squeeze months): disclosed, with a reported squeeze stress read | 13, 16, 20, README_KO |
| 20 | The pin covers the code that runs (its own sha256 against the pinned line), not only the copy under `--root`; every output carries it | 18 |
| 21 | The daily file must also match the sha256 of section 2 (a constant of the pinned code), not only the unpinned MANIFEST | 2 |
| 22 | `test.json`, `board.json` and `pass2.json` are pinned when written; a rerun needs a DEVIATIONS entry naming the old sha256; pass2 needs a pinned `test.json`; `--accept-missing` needs every missing 5m month written in DEVIATIONS | 15, 18 |
| 23 | Status line and section 21: gross forward returns close to P1 / P2_X30_H7 and P3_K1_H28 were computed on period 1 (21 b, c), so "no forward return of any rule computed" was wrong; README_KO says which side that look favoured | status, 21, README_KO |
