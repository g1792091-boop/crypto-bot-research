# Binance USD-M futures order-book depth, 5-minute features

Source: Binance public data archive, daily `bookDepth` files
(`https://data.binance.vision/data/futures/um/daily/bookDepth/{SYM}/{SYM}-bookDepth-{YYYY-MM-DD}.zip`).
Each raw snapshot gives, per signed percentage band around the current price
(-5..-1 bids, +1..+5 asks), the cumulative size (`depth`) and cumulative
quote value (`notional`) within that band. Raw files are not stored here.

## Reduction

Snapshots are bucketed by `floor(timestamp, 5 min)` in UTC. For each bucket,
only the **last** snapshot (latest timestamp in the bucket) is kept. Values
are copied unchanged from the raw `notional` column.

## Files

`{sym}_depth_5m.csv.gz` (sym = lowercase base asset, e.g. `btc`), sorted by
`ts`. A symbol is split into `{sym}_depth_5m_{YYYY}.csv.gz` only if a single
file would exceed 90 MB.

| column | meaning |
|---|---|
| `ts` | bucket start, epoch milliseconds, UTC |
| `snap_ts` | timestamp of the snapshot used, epoch milliseconds, UTC |
| `bid_1` .. `bid_5` | cumulative notional (USDT) within -1% .. -5% (percentage -1..-5) |
| `ask_1` .. `ask_5` | cumulative notional (USDT) within +1% .. +5% (percentage +1..+5) |

Missing bands are left empty. Buckets with no snapshot are absent (no rows are
forward-filled). `MANIFEST.json` lists per-symbol coverage, 404 dates,
row counts, typical snapshots per day and sha256 of each output file.

Notes: raw percentages appear both as integers (`-5`) and with decimals
(`-5.00`); both map to the same column. Some later raw files also contain a
±0.20 band, which is not included in these outputs (the set of bands seen per
symbol is listed in `MANIFEST.json` under `percentage_bands_seen`).
