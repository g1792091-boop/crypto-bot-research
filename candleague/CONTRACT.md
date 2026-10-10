# 후보 리그 (candidate league): component contract

Owners 2026-10-10: the full-grid study's candidates run as paper accounts in their own bot, with their own dashboard
and Telegram tag, apart from the rule bot and the demo lab. Owner summary: docs/candleague-ko.md.

## 1. What it runs

* **Candidates** (`candidates.json`, made by `python -m candleague.candidates` from the study's results pack): each
  `{id, kind (core|ds), name, tf, combo, exit, source}`; `exit` is a name of `candleague.exits.EXITS` (the study's 84
  rules), `combo` the full parameter set (research/entry_study/param_defs for core, research/fullgrid/ds_defs for
  DeepSeek), `source` the study row (rank, select/test trade counts; no money figure for DeepSeek, D11).
* **Accounts**, per candidate: `cand` (its numbers, its exit), `base` (the cell's default numbers, the live exit
  `ladder|2`; one per cell, shared by its candidates), `flip` (the candidate's own signal times, side from a seeded coin:
  sha256 of the account id and the signal close).
* **Engine**: paperbot.engine.PaperEngine through `candleague.exits.make_engine` (parity with the study's kernel is
  tests/test_candleague_exits.py): v3_settings (quality_v1 sizing, $5,000, taker 0.05%, slippage 0.02%, maker 0.02% on
  take-profits, funding, mark-price liquidation, bust below $10), one position at a time per account, six coins
  (config.V3_SYMBOLS), 15m / 30m / 1h / 4h.
* **Signals**: chart bars built from final 1m klines as the study built them (UTC bins); a signal is the bar's
  long/short from the strategy's `signals()` with the candidate's combo; it is submitted after the 1m step that ends at
  the bar's close and fills at the next minute's open plus slippage. Stop distance = the exit's k x ATR14 of the chart;
  a structure exit carries `tp_struct = exits.structure_level(...)` of the signal bar. Leverage group: core from the
  strategy's strength definition as the live service (entry_marks), DeepSeek "normal" (as the study).
* **Time**: from 2026-10-01 00:00 UTC (the first day after the study's data), caught up in day chunks on the first
  start, then every minute (the last closed minute, after a settle wait like the rule bot's feed).
* **Data**: Binance public REST only (klines, mark-price klines, funding history); no key, no order, ever.

## 2. Judging (fixed before any candidate runs)

* Under 30 closed trades: "아직 판단 이름".
* From 30: mean P&L per trade (fraction of the wallet before it) > 0, and > the cell's `base` over the same days, and >
  the candidate's `flip`. Shown with the trade count and the days run; no automatic action.

## 3. Server layout (like the demo lab, separate from it)

| what | where |
|---|---|
| code | `/opt/candleague/app` (copy of this repo's needed folders, read-only for the service) |
| venv | `/opt/candleague/venv` (numpy, pandas, fastapi, uvicorn; no numba) |
| state | `/var/lib/candleague/league.db` (SQLite WAL: engine states, trades, equity points, last minute done) |
| snapshots | `/var/lib/candleague/snap/` (engine writes, dashboard reads; atomic writes) |
| env | `/etc/candleague/candleague.env` (root:candleague 640): `CANDLEAGUE_TG_TOKEN`, `CANDLEAGUE_TG_CHAT`, `CANDLEAGUE_DASH_PASSWORD_HASH`, `CANDLEAGUE_DASH_SECRET`, `CANDLEAGUE_DASH_HOST`, `CANDLEAGUE_DASH_PORT` (8091) |
| user | system user `candleague` |
| services | `candleague-live.service` (engine; CPUQuota and MemoryMax set from the capacity check), `candleague-dash.service` |

Telegram: every message starts with `[후보 리그]`; a 09:00 KST summary and bust notices only.

## 4. Rules both sides keep

* Nothing here imports or writes the rule bot's or the demo lab's databases, services or folders.
* The dashboard only reads `snap/`; it never writes there and tolerates a missing file ("준비 중").
* Its 터미널 reads live market data through the dashboard server only (candleague/live.py, the demo lab's tested
  module: Binance USD-M public endpoints, no key, 5 s timeout, at most 4 requests a second, short in-memory caches, nothing
  written to disk); the page's CSP keeps `connect-src 'self'` and `script-src 'self'`. `CANDLEAGUE_DASH_LIVE` = on
  (default) | fake (tests, screenshots) | off.
* Candidates are paper only. Using one with real money is the owners' decision after this league's record.
