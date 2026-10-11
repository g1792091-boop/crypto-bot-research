#!/usr/bin/env python3
"""Write coins30/UNIVERSE.md from universe_scan.json + universe.json (no price outcomes used)."""
import json, os, hashlib

OUT = "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad/coins30"
scan = json.load(open(os.path.join(OUT, "universe_scan.json")))
uni = json.load(open(os.path.join(OUT, "universe.json")))
S = scan["symbols"]
R = uni["ranking"]
sel = uni["universe"]

n_all, n_usdt = scan["n_symbols_all"], scan["n_usdt"]
early = [r for r in S if r["first_5m_month"] and r["first_5m_month"] <= "2021-01"]
excl_early = [r for r in early if r["excluded"]]
excl_all = [r for r in S if r["excluded"]]
elig = [r for r in S if r["eligible"]]
zero = [r for r in R if r["qv2023_usdt"] == 0]
prefixed = [r for r in S if r["symbol"].startswith("1000")]
prefixed_early = [r for r in prefixed if r["first_5m_month"] <= "2021-01"]

L = []
L.append("# coins30 universe (fixed before any result)")
L.append("")
L.append(f"Fixed: {uni['generated']} (container clock, UTC). Scan: {scan['generated']}. "
         "No price outcome, return or trade result was computed on any period before or while fixing this list. "
         "The only market number used is 2023 quote volume.")
L.append("")
L.append("## Rule, with the exact numbers used")
L.append("")
L.append(f"1. Source listing: `data/futures/um/monthly/klines/` on data.binance.vision (S3 listing). "
         f"{n_all} symbol folders; {n_usdt} end in `USDT` and have no `_` (the `_` ones are dated delivery contracts, not perpetuals).")
L.append(f"2. 5m history test: a symbol qualifies if its first monthly 5m kline file (`<SYM>/5m/<SYM>-5m-YYYY-MM.zip`) is 2021-01 or earlier. "
         f"{len(early)} USDT symbols pass.")
L.append("3. Exclusions, fixed in code before any volume was read:")
L.append("   - stablecoin or fiat base asset: USDC, BUSD, TUSD, FDUSD, USDP, PAX, DAI, UST, USTC, USDD, PYUSD, USDE, USD1, RLUSD, EUR, AEUR, EURI, GBP, SUSD, GUSD")
L.append("   - index products: DEFIUSDT, BTCDOMUSDT, FOOTBALLUSDT, BLUEBIRDUSDT")
L.append(f"   - symbols hit by an exclusion anywhere in the listing: "
         + ", ".join(f"{r['symbol']} ({r['excluded']}, 5m from {r['first_5m_month']})" for r in excl_all))
L.append(f"   - of those, only {', '.join(r['symbol'] for r in excl_early) or 'none'} also passed step 2, so the exclusions removed "
         f"{len(excl_early)} symbol(s). Eligible after exclusions: {len(elig)}.")
L.append(f"4. 1000-prefixed symbols are treated as ordinary symbols. {len(prefixed)} exist in the listing; "
         f"the earliest is 1000SHIBUSDT (5m from 2021-05), so none pass step 2 ({len(prefixed_early)} qualify).")
L.append("5. Ranking: for each eligible symbol, the 12 monthly 1d kline files of 2023 (`<SYM>/1d/<SYM>-1d-2023-MM.zip`) were downloaded, "
         "each checked against its `.CHECKSUM` (sha256; every 2023 file that exists had one and it matched), and the quote asset volume column "
         "(8th CSV column, `quote_volume`) was summed over every daily bar of 2023. Missing months count as zero. "
         f"{len(zero)} eligible symbols have zero 2023 volume (no 2023 files, or 2023 files with only zero-volume bars, as for CVCUSDT and SRMUSDT): {', '.join(r['symbol'] for r in zero)}.")
L.append("6. Selection: take the top 30 by that sum. The 6 current coins (BTC ETH SOL DOGE LTC BCH) must be included; "
         "if any is outside the top 30, the set is the 6 plus the next 24 by rank.")
L.append(f"   - Outcome: {uni['rule_note']}.")
L.append("")
L.append("## The 30 coins")
L.append("")
L.append("| rank | symbol | 2023 quote volume (bn USDT) | first 5m month | last 5m month listed | note |")
L.append("|---:|---|---:|---|---|---|")
notes = {
    "MATICUSDT": "renamed to POL in 2024; MATICUSDT files stop 2024-09",
    "TOMOUSDT": "renamed to VIC in 2024; TOMOUSDT files stop 2024-05",
    "EOSUSDT": "renamed (Vaulta) in 2025; EOSUSDT files stop 2025-05",
    "FTMUSDT": "migrated to S (Sonic) around 2025-01; files continue, see manifest for the last bar with volume",
    "WAVESUSDT": "files continue but shrink sharply from 2024-07 (likely flat, no-trade bars); see manifest",
    "BLZUSDT": "files continue but shrink sharply from 2025-01; see manifest",
}
for r in R:
    if not r["selected"]:
        continue
    tag = "current coin" if r["forced"] else ""
    note = notes.get(r["symbol"], "")
    L.append(f"| {r['rank']} | {r['symbol']} | {r['qv2023_usdt']/1e9:,.1f} | {r['first_5m_month']} | {r['last_5m_month']} | "
             + "; ".join(x for x in (tag, note) if x) + " |")
L.append("")
L.append("Next 10 by rank (not selected, listed only to show where the cut fell):")
L.append("")
L.append("| rank | symbol | 2023 quote volume (bn USDT) | first 5m month | last 5m month listed |")
L.append("|---:|---|---:|---|---|")
for r in R[30:40]:
    L.append(f"| {r['rank']} | {r['symbol']} | {r['qv2023_usdt']/1e9:,.1f} | {r['first_5m_month']} | {r['last_5m_month']} |")
L.append("")
L.append("## Known limits of this rule (stated before any result)")
L.append("")
L.append("- The rule ranks on 2023 volume and does not require the coin to still trade in 2026. "
         "So the set includes coins that were renamed, migrated or delisted later (MATIC, TOMO, EOS stop early; "
         "FTM, WAVES, BLZ and possibly MKR have archive files that keep going after real trading appears to stop). "
         "That is deliberate under the rule and it avoids survivorship bias, but it means fewer than 30 coins are live in 2025-2026.")
L.append("- Successor tickers (POL, VIC, S, A, SKY ...) are NOT spliced in. They are different contracts with their own listing dates.")
L.append("- Proposed handling for the test (a proposal, not decided from data): a coin can be scanned and entered only up to its "
         "`last_nonzero_volume_bar` in manifest.json; any open position is closed at that bar; flat zero-volume bars after it are ignored.")
L.append("- 2023 was a single year; the volume rank is a liquidity filter, not a forecast.")
L.append("")
L.append("## Files")
L.append("")
L.append("- `universe_scan.json`: every USDT symbol in the listing with first/last 5m month and exclusion flag.")
L.append("- `universe.json`: the ranking of all eligible symbols with 2023 quote volume, months found, checksum status, and the selected 30.")
L.append("- `manifest.json`: per-coin coverage of the downloaded 5m, mark price and funding data.")
L.append("- builder script: `../coins30_scripts/c30.py` (scan, rank, download); this file: `../coins30_scripts/write_universe_md.py`.")
L.append("")
h = hashlib.sha256(open(os.path.join(OUT, "universe.json"), "rb").read()).hexdigest()
L.append(f"sha256 of universe.json at the time of writing: `{h}`")
L.append("")
L.append("Universe (copy-paste): " + " ".join(sel))
open(os.path.join(OUT, "UNIVERSE.md"), "w").write("\n".join(L) + "\n")
print("written", len(L), "lines")
