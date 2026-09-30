# Binance USD-M futures order-flow data

Source: the public Binance data archive at https://data.binance.vision (USD-M futures, `data/futures/um/`).
Symbols: BTC, ETH, SOL, LTC, BCH, DOGE and XRP (all USDT-margined perpetuals). Downloaded 2026-09-30.
Values are unchanged from the archive. Rows are sorted by time, and exact duplicate rows were removed.
Every file is a gzip CSV with a header row.

| File | Source dataset | Columns |
|---|---|---|
| `{sym}_funding.csv.gz` | monthly `fundingRate` | `calc_time` (ms epoch), `funding_interval_hours`, `last_funding_rate` |
| `{sym}_metrics_5m.csv.gz` | daily `metrics` (5-minute) | `create_time` (UTC string), `symbol`, `sum_open_interest`, `sum_open_interest_value`, `count_toptrader_long_short_ratio`, `sum_toptrader_long_short_ratio`, `count_long_short_ratio`, `sum_taker_long_short_vol_ratio` |
| `{sym}_premium_1h.csv.gz` | monthly `premiumIndexKlines/1h` | `open_time`, `open`, `high`, `low`, `close`, `volume`, `close_time`, `quote_volume`, `count`, `taker_buy_volume`, `taker_buy_quote_volume`, `ignore` (times in ms epoch) |

Coverage:
- Funding runs from 2020-01 (or from the symbol's listing) through 2026-08. The 2026-09 monthly file had not been published yet.
- Premium index covers the same months.
- BTC metrics start 2020-09-01. For the other symbols, metrics start 2021-12-01 because the archive has no earlier files. Metrics run through 2026-09-28.
- There is no liquidation-snapshot file: all monthly probes (the 15th of each month, 2020-01..2026-09) returned 404 for every symbol.

`MANIFEST.json` gives, for each symbol and dataset: the number of files downloaded, the missing (404) periods as ranges, the first and last timestamps, the row count and the SHA-256 of each file.
