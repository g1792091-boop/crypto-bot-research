# Binance USD-M USDT perpetuals: daily klines (all symbols, incl. delisted)

Daily (1d) klines for every USDT-margined perpetual symbol found in the public Binance data archive
(`data.binance.vision`), including symbols that were later delisted or renamed, so that universe
backtests are not affected by survivorship bias.

- Source: `https://data.binance.vision/data/futures/um/monthly/klines/{SYM}/1d/{SYM}-1d-{YYYY-MM}.zip`
- Symbol list: S3 bucket listing of `data/futures/um/monthly/klines/`, kept symbols ending in `USDT`
  without `_` (dated quarterly contracts dropped). 864 symbols.
- Months requested: 2019-09 .. 2026-08 (the first data starts 2020-01-01).
- Downloaded: 2026-09-30.

## Files

- `klines_1d.csv.gz`: one table, columns
  `symbol,open_time,open,high,low,close,volume,quote_volume,count,taker_buy_quote_volume`.
  `open_time` is the UTC day open in epoch milliseconds. Values are copied unchanged from the archive.
  Rows are sorted by symbol, then open_time. Exact duplicates were dropped (there were no
  duplicate symbol/open_time pairs).
- `MANIFEST.json`: symbol count, per-symbol first/last date, row count and last traded date,
  delisted lists, total rows, sha256 of the data file, URL patterns and download date.

## Caveat: zero-volume padding after delisting

For many delisted symbols the archive keeps publishing flat rows (open=high=low=close,
volume=count=0) up to the end of the range. 52,713 rows are like this. Because of that,
`last_date` in the manifest (and `delisted_or_renamed`, 31 symbols) understates delistings.
Use `last_traded_date` per symbol, or the `no_trading_at_end` list (160 symbols with no volume
on 2026-08-31), and drop zero-volume rows before computing returns or liquidity filters.

## Load

```python
import pandas as pd
df = pd.read_csv("data/universe/klines_1d.csv.gz")
df["date"] = pd.to_datetime(df.open_time, unit="ms")
df = df[df.volume > 0]
```
