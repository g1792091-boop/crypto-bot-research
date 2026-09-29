# PRE-REGISTRATION: Option B out-of-sample test (written before any out-of-sample data was fetched)

Written: 2026-09-29T08:05Z (UTC). No 5m bar before 2026-05-12 has been fetched by me or (checked by `find`
over the scratchpad: every *ohlcv*.csv there starts 2025-08-07 (15m) or 2026-05-12/13 (5m) or 2026-08-31 (1m))
by any other auditor in this session.

Frozen code (sha256):
- `work/prereg_b.py`   ad980f068d3a607097083ebe7183d10a159e94a4585c9480ac9a4e045b1898ac  (primary + secondary)
- `work/b_null_oos.py` 94915136adec690723802bb159c2f2284660a04fab27b77f91b9c57109e82bdb  (critic's b_null.py; only the data path
  and the hard-coded rolled length 39000 -> M were changed; reproduces critic IS output exactly)
- `work/stitch_check.py` 78188961ce8ddb80cdc7f436f32613a463414f926f89a572f0a4cf4905d31a3c (stitching + data gates)
- `work/power2.py` 37fd35284621289adc043ab429f82b3f646074b0cae00eb14cbf9c8803117a50

Validation on the in-sample (already-seen) data, `out/IS_validation_result.json`: primary 618 trades, +0.1046%/trade,
PF 1.290, 3/3 symbols, null z 2.03, p 0.020 (5/300 reps >= real), null pass-rate 2.7% -> the rule WOULD pass in-sample.
Secondaries reproduce critic/work/limit_fill2.csv exactly (taker 0.0570% PF 1.149; maker-at-open 0.1071% PF 1.2985;
6-ATR stop 621 trades 0.0875% PF 1.233); forward fwd64 reproduces results/forward_ALL_5m_v45.csv exactly
(BTC 563 +0.0902, ETH 550 +0.1403, SOL 528 +0.1781).

## Rule (primary; the ONLY configuration that decides)
- Signal: `strategies.v45_exact_amb(d5, d15)` (V4.5 exact AM+B = signalB and not signalC), 5m chart + confirmed 15m.
- Entry: maker limit at signal-bar close c[i]; valid bars i+1..i+3; fill only on trade-through; price = limit or
  better open (gap). Unfilled -> no trade.
- Exit: scheduled at o[i+65]; exit limit at that open valid 3 bars (trade-through); else taker at o[ex+3] (+0.02% slip).
- Stop: NONE (chosen now, before the run). The 6-ATR stop is a secondary, non-decisive.
- Costs: maker 0.02%/side, taker 0.05%/side, slippage 0.02% on taker fills, no funding (identical to the in-sample
  numbers being replicated; funding variant reported as secondary).
- Sequencing: one position per symbol; first 1000 5m bars = warm-up.
- PASS iff pooled PF >= 1.2 AND trades >= 100 AND pooled mean net > 0 AND 3/3 symbols positive AND
  p < 0.05 vs a common circular-shift null (300 reps, seed 20260929, shift ~ U{288..M-289}, p=(1+k)/301).
- Secondary / descriptive only: taker exit; maker exit at open; primary+6-ATR stop; primary+funding;
  per symbol / per month / per pull splits (computed from the primary trade file); cost-free fwd64;
  b_null_oos.py output (maker-at-open and taker, independent and common shifts).

## Data plan (Astral `astral_price_get`, read-only; never start+end)
- 5m BTCUSD/ETHUSD/SOLUSD: pull p1 `limit=40000, end=2026-05-12T00:00:00Z`; p2 `limit=40000, end=<first ts of p1>`;
  p3 `limit=40000, end=<first ts of p2>`. Planned ~3 x 138.9 days = ~13.9 months (~2025-03 .. 2026-05-12).
- 15m same symbols: q1 `limit=40000, end=2026-05-12T00:00:00Z`; q2 `limit=40000, end=<first ts of q1>` (warm-up for p3).
- PRIMARY SAMPLE = the union of all 5m pulls that succeed (planned p1..p3). If a pull fails (history/entitlement),
  the sample is whatever succeeded; the decision rule is unchanged. The first ~9.2 months (p1+p2) are ALSO reported
  as a secondary split (not decisive), since the task text planned ~9 months.
- Gates before the run (data validity only, no results looked at): sha256 of every file equals the Astral artifact sha;
  overlapping bars between pulls identical; 5m->15m open-labelled resample equals the 15m file OHLC on >= 98% of
  complete buckets (calibration: in-sample BTC is 98.35%); fetched 15m vs delivered 15m on the common range reported;
  all 5m bars strictly before 2026-05-12T00:00Z. No data cleaning (the in-sample run was not cleaned either).
- `prereg_b.py` is run on the stitched files EXACTLY ONCE; `b_null_oos.py` exactly once.

## Power (pre-fetch, `work/power2.py`: bootstrap of IS trades + clustering variance matched to the IS null SD)
| sample | trades | P(full rule) at IS effect | at 3/4 effect | at 1/2 effect | at zero effect (false pass) |
|---|---|---|---|---|---|
| 4.5 mo | 618 | 0.60 | 0.39 | 0.22 | 0.037 |
| 9.2 mo | 1260 | 0.70 | 0.43 | 0.19 | 0.008 |
| 13.9 mo | 1905 | 0.76 | 0.44 | 0.15 | 0.001 |
The null-test component alone has 0.66 / 0.90 / 0.97 power at the IS effect (matches the critic's 65% / 89%);
the binding constraint at larger samples is PF >= 1.2, i.e. the rule requires roughly >= +0.07%/trade net.

## Interpretation fixed in advance
- PASS: B survives one honest out-of-sample test -> next step is paper trading on Binance USDT-M with real maker
  fills (spot-vs-perp basis, queue position and post-only rejects are not modelled here); leverage <= ~2x notional.
- FAIL with pooled mean <= null mean + 1 SD: B's drift is not supported; close B.
- FAIL on PF only with p < 0.05: effect present but too small to trade at these costs; close B for trading.
