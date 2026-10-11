#!/usr/bin/env python3
"""coins30 data builder (universe fix + download + npz build). No trading outcomes computed.

Usage (run with python3 -I):
  c30.py scan       # list UM USDT perps, 5m first/last month -> coins30/universe_scan.json
  c30.py rank       # 2023 quote volume from monthly 1d klines -> UNIVERSE.md, universe.json
  c30.py download   # 5m klines + 5m mark klines + funding for the universe -> npz + manifest.json
"""
import hashlib, io, json, os, re, shutil, ssl, sys, time, zipfile
import urllib.request, urllib.error, urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

SP = "/tmp/claude-0/-home-user-crypto-bot-research/e767230a-7665-5629-9ef1-f23e97e5705f/scratchpad"
OUT = os.path.join(SP, "coins30")
RAW = os.path.join(OUT, "raw")
RANKRAW = os.path.join(OUT, "rank_raw")
LOG = os.path.join(OUT, "download.log")
S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
DL = "https://data.binance.vision/"
CTX = ssl.create_default_context(cafile="/root/.ccr/ca-bundle.crt")
NTHREADS = 2                      # hard limit: at most 2 parallel downloads
MIN_FREE = 1 * 1024**3            # stop if free disk < 1 GB
RANGE_START, RANGE_END = "2020-01", "2026-09"
ELIG_FIRST_MONTH_MAX = "2021-01"
RANK_YEAR = "2023"
FORCED = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT"]
TOPN = 30
# Fixed before any volume is looked at.
STABLE_BASES = {"USDC", "BUSD", "TUSD", "FDUSD", "USDP", "PAX", "DAI", "UST", "USTC", "USDD",
                "PYUSD", "USDE", "USD1", "RLUSD", "EUR", "AEUR", "EURI", "GBP", "SUSD", "GUSD"}
INDEX_SYMBOLS = {"DEFIUSDT", "BTCDOMUSDT", "FOOTBALLUSDT", "BLUEBIRDUSDT", "ALTUSDT_INDEX"}


def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def http_get(url, tries=6):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, context=CTX, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = e
        except Exception as e:  # network hiccup
            last = e
        time.sleep(min(30, 2 * (i + 1)))
    raise RuntimeError(f"GET failed {url}: {last}")


def s3_list(prefix, delimiter="/"):
    """Return (common_prefixes, keys) for a prefix, following pagination."""
    prefixes, keys, marker = [], [], ""
    ns = "{http://s3.amazonaws.com/doc/2006-03-01/}"
    while True:
        q = {"prefix": prefix, "delimiter": delimiter}
        if marker:
            q["marker"] = marker
        body = http_get(S3 + "?" + urllib.parse.urlencode(q))
        root = ET.fromstring(body)
        for cp in root.findall(ns + "CommonPrefixes"):
            prefixes.append(cp.find(ns + "Prefix").text)
        for c in root.findall(ns + "Contents"):
            keys.append(c.find(ns + "Key").text)
        trunc = root.find(ns + "IsTruncated").text == "true"
        if not trunc:
            break
        nm = root.find(ns + "NextMarker")
        marker = nm.text if nm is not None else (keys[-1] if keys else prefixes[-1])
    return prefixes, keys


def months_from_keys(keys, sym, stem):
    """stem e.g. '5m' or 'fundingRate'. Returns {month: has_checksum}."""
    pat = re.compile(re.escape(f"{sym}-{stem}-") + r"(\d{4}-\d{2})\.zip$")
    zips, cks = set(), set()
    for k in keys:
        base = k.rsplit("/", 1)[-1]
        m = pat.match(base)
        if m:
            zips.add(m.group(1))
        elif base.endswith(".zip.CHECKSUM"):
            m2 = pat.match(base[: -len(".CHECKSUM")])
            if m2:
                cks.add(m2.group(1))
    return {m: (m in cks) for m in sorted(zips)}


def month_range(a, b):
    y, m = map(int, a.split("-"))
    y2, m2 = map(int, b.split("-"))
    out = []
    while (y, m) <= (y2, m2):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def free_bytes():
    return shutil.disk_usage(OUT).free


def fetch_verified(key, dest, has_ck):
    """Download key to dest, verify against .CHECKSUM if present. Resume: skip if dest+'.ok' exists."""
    ok = dest + ".ok"
    if os.path.exists(dest) and os.path.exists(ok):
        return open(ok).read().strip()
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    for attempt in range(4):
        data = http_get(DL + key)
        if data is None:
            return "404"
        status = "nock"
        if has_ck:
            ck = http_get(DL + key + ".CHECKSUM")
            if ck is not None:
                want = ck.decode().split()[0].strip().lower()
                got = hashlib.sha256(data).hexdigest()
                if want != got:
                    log(f"CHECKSUM MISMATCH {key} attempt {attempt}")
                    time.sleep(3)
                    continue
                status = "ok"
        tmp = dest + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, dest)
        with open(ok, "w") as f:
            f.write(status)
        return status
    return "mismatch"


# ---------------------------------------------------------------- scan
def cmd_scan():
    log("scan: listing UM monthly klines symbols")
    prefixes, _ = s3_list("data/futures/um/monthly/klines/")
    allsyms = [p.rstrip("/").rsplit("/", 1)[-1] for p in prefixes]
    usdt = [s for s in allsyms if s.endswith("USDT") and "_" not in s]
    log(f"scan: {len(allsyms)} symbols total, {len(usdt)} USDT perps (no underscore)")

    def one(sym):
        _, keys = s3_list(f"data/futures/um/monthly/klines/{sym}/5m/")
        ms = months_from_keys(keys, sym, "5m")
        return sym, (min(ms) if ms else None), (max(ms) if ms else None), len(ms)

    rows = []
    with ThreadPoolExecutor(NTHREADS) as ex:
        for i, r in enumerate(ex.map(one, usdt)):
            rows.append(r)
            if (i + 1) % 50 == 0:
                log(f"scan: {i+1}/{len(usdt)}")
    scan = []
    for sym, first, last, n in rows:
        base = sym[:-4]
        excl = None
        if base in STABLE_BASES:
            excl = "stablecoin/fiat base"
        elif sym in INDEX_SYMBOLS:
            excl = "index product"
        scan.append({"symbol": sym, "first_5m_month": first, "last_5m_month": last,
                     "n_5m_months": n, "excluded": excl,
                     "eligible": bool(first and first <= ELIG_FIRST_MONTH_MAX and not excl)})
    json.dump({"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "n_symbols_all": len(allsyms),
               "n_usdt": len(usdt), "symbols": scan},
              open(os.path.join(OUT, "universe_scan.json"), "w"), indent=1)
    el = [r["symbol"] for r in scan if r["eligible"]]
    log(f"scan: eligible {len(el)}: {' '.join(el)}")
    early_excl = [r for r in scan if r["excluded"] and r["first_5m_month"] and r["first_5m_month"] <= ELIG_FIRST_MONTH_MAX]
    log(f"scan: excluded-by-rule with early data: {[(r['symbol'], r['excluded']) for r in early_excl]}")


# ---------------------------------------------------------------- rank
def read_kline_zip(path, usecols):
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.endswith(".csv")]
        frames = []
        for n in names:
            raw = z.read(n)
            if not raw.strip():
                continue
            first = raw[:64].lstrip()
            skip = 0 if first[:1].isdigit() else 1
            df = pd.read_csv(io.BytesIO(raw), header=None, skiprows=skip, usecols=usecols)
            frames.append(df)
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)


def cmd_rank():
    scan = json.load(open(os.path.join(OUT, "universe_scan.json")))
    el = [r for r in scan["symbols"] if r["eligible"]]
    months = [f"{RANK_YEAR}-{m:02d}" for m in range(1, 13)]
    jobs = [(r["symbol"], m) for r in el for m in months]
    log(f"rank: {len(el)} eligible symbols, {len(jobs)} 1d monthly files")

    def one(job):
        sym, m = job
        key = f"data/futures/um/monthly/klines/{sym}/1d/{sym}-1d-{m}.zip"
        dest = os.path.join(RANKRAW, sym, f"{sym}-1d-{m}.zip")
        st = fetch_verified(key, dest, True)
        if st in ("404", "mismatch"):
            return sym, m, st, 0.0
        df = read_kline_zip(dest, [0, 7])
        qv = float(df[7].astype(float).sum()) if df is not None else 0.0
        return sym, m, st, qv

    res = {}
    with ThreadPoolExecutor(NTHREADS) as ex:
        for i, (sym, m, st, qv) in enumerate(ex.map(one, jobs)):
            d = res.setdefault(sym, {"qv": 0.0, "months": [], "missing": [], "ck": []})
            if st in ("404", "mismatch"):
                d["missing"].append(m + ("" if st == "404" else "(ckfail)"))
            else:
                d["qv"] += qv
                d["months"].append(m)
                d["ck"].append(st)
            if (i + 1) % 200 == 0:
                log(f"rank: {i+1}/{len(jobs)}")
    ranked = sorted(res.items(), key=lambda kv: -kv[1]["qv"])
    order = [s for s, _ in ranked]
    top = order[:TOPN]
    if all(f in top for f in FORCED):
        chosen = top
        rule_note = "all 6 current coins are inside the plain top 30 -> universe = plain top 30"
    else:
        rest = [s for s in order if s not in FORCED][: TOPN - len(FORCED)]
        chosen = [s for s in order if s in FORCED or s in rest]
        rule_note = "some current coins outside top 30 -> universe = 6 current coins + next 24 by rank"
    scanmap = {r["symbol"]: r for r in scan["symbols"]}
    uni = []
    for i, (s, d) in enumerate(ranked):
        uni.append({"rank": i + 1, "symbol": s, "qv2023_usdt": d["qv"], "n_1d_months_2023": len(d["months"]),
                    "missing_2023_months": d["missing"], "checksums": sorted(set(d["ck"])),
                    "first_5m_month": scanmap[s]["first_5m_month"], "last_5m_month": scanmap[s]["last_5m_month"],
                    "selected": s in chosen, "forced": s in FORCED})
    json.dump({"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "rule_note": rule_note,
               "universe": chosen, "ranking": uni}, open(os.path.join(OUT, "universe.json"), "w"), indent=1)
    shutil.rmtree(RANKRAW, ignore_errors=True)
    os.makedirs(RANKRAW, exist_ok=True)
    log(f"rank: {rule_note}")
    log(f"rank: universe ({len(chosen)}): {' '.join(chosen)}")


# ---------------------------------------------------------------- download / build
def load_state():
    p = os.path.join(OUT, "state.json")
    return json.load(open(p)) if os.path.exists(p) else {}


def save_state(st):
    p = os.path.join(OUT, "state.json")
    json.dump(st, open(p + ".tmp", "w"), indent=1)
    os.replace(p + ".tmp", p)


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def to_ms(ts):
    ts = ts.astype(np.int64)
    us = ts > 10**14            # microsecond timestamps -> ms
    ts[us] //= 1000
    return ts


def build_symbol(sym):
    t0 = time.time()
    kinds = {
        "kl": (f"data/futures/um/monthly/klines/{sym}/5m/", "5m"),
        "mk": (f"data/futures/um/monthly/markPriceKlines/{sym}/5m/", "5m"),
        "fr": (f"data/futures/um/monthly/fundingRate/{sym}/", "fundingRate"),
    }
    avail = {}
    for k, (pfx, stem) in kinds.items():
        _, keys = s3_list(pfx)
        ms = months_from_keys(keys, sym, stem)
        avail[k] = {m: c for m, c in ms.items() if RANGE_START <= m <= RANGE_END}
    if not avail["kl"]:
        raise RuntimeError(f"{sym}: no 5m kline months in range")
    kl_first, kl_last = min(avail["kl"]), max(avail["kl"])
    span = month_range(kl_first, kl_last)
    jobs = []
    for k, (pfx, stem) in kinds.items():
        for m, has_ck in avail[k].items():
            if m < kl_first:
                continue
            key = f"{pfx}{sym}-{stem}-{m}.zip"
            jobs.append((k, m, key, os.path.join(RAW, sym, k, f"{sym}-{stem}-{m}.zip"), has_ck))
    log(f"{sym}: {len(jobs)} files (kl {len(avail['kl'])}, mk {len(avail['mk'])}, fr {len(avail['fr'])}) span {kl_first}..{kl_last}")
    status = {}

    def one(j):
        k, m, key, dest, has_ck = j
        return k, m, fetch_verified(key, dest, has_ck)

    with ThreadPoolExecutor(NTHREADS) as ex:
        for i, (k, m, st) in enumerate(ex.map(one, jobs)):
            status[(k, m)] = st
            if (i + 1) % 60 == 0:
                log(f"{sym}: {i+1}/{len(jobs)} files, free {free_bytes()/1e9:.2f} GB")
                if free_bytes() < MIN_FREE:
                    raise SystemExit(f"ABORT: free disk below 1 GB while downloading {sym}")
    bad = {f"{k}:{m}": st for (k, m), st in status.items() if st in ("404", "mismatch")}
    ck_counts = {}
    for st in status.values():
        ck_counts[st] = ck_counts.get(st, 0) + 1

    # --- klines
    def load_kind(k, cols):
        frames = []
        for m in sorted(avail[k]):
            if m < kl_first or status.get((k, m)) in ("404", "mismatch"):
                continue
            stem = "fundingRate" if k == "fr" else "5m"
            df = read_kline_zip(os.path.join(RAW, sym, k, f"{sym}-{stem}-{m}.zip"), cols)
            if df is not None:
                frames.append(df)
        return pd.concat(frames, ignore_index=True) if frames else None

    kl = load_kind("kl", [0, 1, 2, 3, 4, 5, 7])
    kl.columns = ["ts", "o", "h", "l", "c", "v", "qv"]
    kl = kl[pd.to_numeric(kl["ts"], errors="coerce").notna()]
    kl["ts"] = to_ms(kl["ts"].astype(np.int64).values)
    n_read = len(kl)
    kl = kl.drop_duplicates("ts", keep="last").sort_values("ts").reset_index(drop=True)
    n_dup = n_read - len(kl)
    mk = load_kind("mk", [0, 1, 2, 3, 4])
    if mk is not None:
        mk.columns = ["ts", "mo", "mh", "ml", "mc"]
        mk = mk[pd.to_numeric(mk["ts"], errors="coerce").notna()]
        mk["ts"] = to_ms(mk["ts"].astype(np.int64).values)
        mk = mk.drop_duplicates("ts", keep="last")
        merged = kl.merge(mk, on="ts", how="left")
    else:
        merged = kl.assign(mo=np.nan, mh=np.nan, ml=np.nan, mc=np.nan)
    ts = merged["ts"].values.astype(np.int64)
    arrs = {"ts": ts}
    for c in ["o", "h", "l", "c", "v", "qv", "mo", "mh", "ml", "mc"]:
        arrs[c] = merged[c].values.astype(np.float64)   # as parsed (the exchange's decimal)
    # bar-level coverage (data quality only, no trading quantities)
    step = 300_000
    d = np.diff(ts)
    missing_bars = int(((d // step) - 1)[d > step].sum())
    gaps_over_1h = int((d > 3_600_000).sum())
    largest_gap_h = float(d.max() / 3_600_000) if len(d) else 0.0
    off_grid = int((ts % step != 0).sum())
    mark_nan = int(np.isnan(arrs["mc"]).sum())
    zero_vol = int((arrs["v"] == 0).sum())
    nz = np.flatnonzero(arrs["v"] > 0)
    last_traded_ts = int(ts[nz[-1]]) if len(nz) else None
    trailing_zero = int(len(ts) - 1 - nz[-1]) if len(nz) else int(len(ts))
    out5 = os.path.join(OUT, "5m", f"{sym}.npz")
    tmp = out5 + ".tmp.npz"
    np.savez_compressed(tmp, **arrs)
    os.replace(tmp, out5)

    # --- funding
    fr = load_kind("fr", None)
    fr_rows = 0
    outf = os.path.join(OUT, "funding", f"{sym}.npz")
    if fr is not None:
        # columns: calc_time, funding_interval_hours, last_funding_rate
        fr = fr[pd.to_numeric(fr[0], errors="coerce").notna()]
        fts = to_ms(fr[0].astype(np.int64).values)
        rate = fr[fr.columns[-1]].astype(np.float64).values
        o = np.argsort(fts, kind="stable")
        fts, rate = fts[o], rate[o]
        keep = np.ones(len(fts), bool)
        keep[1:] = fts[1:] != fts[:-1]
        fts, rate = fts[keep], rate[keep]
        fr_rows = int(len(fts))
        tmp = outf + ".tmp.npz"
        np.savez_compressed(tmp, ts=fts, rate=rate)
        os.replace(tmp, outf)

    def miss(k):
        return [m for m in span if m not in avail[k] or status.get((k, m)) in ("404", "mismatch")]

    def ym(t):
        return time.strftime("%Y-%m-%d %H:%M", time.gmtime(t / 1000))

    info = {
        "symbol": sym,
        "first_month": kl_first, "last_month": kl_last,
        "ends_before_range_end": kl_last < RANGE_END,
        "rows": int(len(ts)), "first_bar": ym(ts[0]), "last_bar": ym(ts[-1]),
        "missing_months_klines": miss("kl"),
        "missing_months_mark": miss("mk"),
        "missing_months_funding": miss("fr"),
        "missing_5m_bars_inside_span": missing_bars,
        "gaps_over_1h": gaps_over_1h, "largest_gap_hours": round(largest_gap_h, 2),
        "off_grid_ts": off_grid, "duplicate_rows_dropped": int(n_dup),
        "bars_without_mark": mark_nan, "zero_volume_bars": zero_vol,
        "last_nonzero_volume_bar": ym(last_traded_ts) if last_traded_ts is not None else None,
        "trailing_zero_volume_bars": trailing_zero,
        "trailing_zero_volume_days": round(trailing_zero * 5 / 1440, 1),
        "funding_rows": fr_rows,
        "funding_first": ym(int(np.load(outf)["ts"][0])) if fr_rows else None,
        "funding_last": ym(int(np.load(outf)["ts"][-1])) if fr_rows else None,
        "download_problems": bad,
        "checksum_status_counts": ck_counts,
        "npz_5m": os.path.relpath(out5, OUT), "npz_5m_bytes": os.path.getsize(out5),
        "sha256_5m": sha256_file(out5),
        "npz_funding": os.path.relpath(outf, OUT) if fr_rows else None,
        "npz_funding_bytes": os.path.getsize(outf) if fr_rows else 0,
        "sha256_funding": sha256_file(outf) if fr_rows else None,
        "build_seconds": round(time.time() - t0, 1),
    }
    shutil.rmtree(os.path.join(RAW, sym), ignore_errors=True)   # delete zips after conversion
    return info


def write_manifest(state, universe):
    syms = [state[s] for s in universe if s in state]
    tot = sum(r["npz_5m_bytes"] + r["npz_funding_bytes"] for r in syms)
    man = {
        "generated": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "source": "https://data.binance.vision (Binance USD-M futures monthly archives)",
        "range": [RANGE_START, RANGE_END],
        "format": {"5m": "np.savez_compressed; keys ts(int64 ms open time UTC),o,h,l,c,v(base vol),qv(quote vol),"
                         "mo,mh,ml,mc (mark price OHLC, NaN where no mark bar); all float64 except ts",
                   "funding": "np.savez_compressed; keys ts(int64 ms calc_time UTC), rate(float64 last_funding_rate)"},
        "notes": ["rows are raw exchange bars: nothing forward-filled or synthesized, zero-volume bars kept",
                  "ts converted to ms if source used microseconds",
                  "every monthly and daily zip was checked against its .CHECKSUM (sha256); see checksum_status_counts and daily_fill.daily_status",
                  "monthly archives miss whole days for some coins (klines 2022-02-26..28 and 2022-04-01..02 on 11 coins; mark price on "
                  "2021-07-01, 2021-07-24..27, 2022-07-31, 2022-10-02, 2023-02-24, 2026-06-29 and others); these were filled from the "
                  "official daily archives (daily_fill), inserting only absent bars / NaN mark values",
                  "after a coin stops trading the archive can keep producing flat zero-volume bars and fixed funding rows: "
                  "use last_nonzero_volume_bar as the end of the tradable period; trailing_zero_volume_days and "
                  "funding_rows_after_last_traded_bar measure that tail",
                  "the *_while_trading fields count gaps only up to last_nonzero_volume_bar"],
        "n_symbols_done": len(syms), "n_symbols_universe": len(universe),
        "total_npz_bytes": tot,
        "symbols": syms,
    }
    json.dump(man, open(os.path.join(OUT, "manifest.json"), "w"), indent=1)


def cmd_download():
    uni = json.load(open(os.path.join(OUT, "universe.json")))["universe"]
    state = load_state()
    log(f"download: start, universe {len(uni)}, already done {sum(1 for s in uni if s in state)}, free {free_bytes()/1e9:.2f} GB")
    for sym in uni:
        if sym in state and os.path.exists(os.path.join(OUT, state[sym]["npz_5m"])) \
                and sha256_file(os.path.join(OUT, state[sym]["npz_5m"])) == state[sym]["sha256_5m"]:
            continue
        if free_bytes() < MIN_FREE:
            log(f"ABORT: free disk {free_bytes()/1e9:.2f} GB < 1 GB before {sym}")
            sys.exit(2)
        try:
            info = build_symbol(sym)
        except SystemExit as e:
            log(str(e))
            sys.exit(2)
        except Exception as e:
            log(f"ERROR {sym}: {e!r} (will continue; rerun to resume)")
            continue
        state[sym] = info
        save_state(state)
        write_manifest(state, uni)
        log(f"{sym}: done rows {info['rows']} {info['first_bar']}..{info['last_bar']} "
            f"5m {info['npz_5m_bytes']/1e6:.1f} MB, miss kl {info['missing_months_klines']} mk {info['missing_months_mark']} "
            f"fr {info['missing_months_funding']}, {info['build_seconds']}s, free {free_bytes()/1e9:.2f} GB")
    write_manifest(state, uni)
    done = sum(1 for s in uni if s in state)
    log(f"download: finished {done}/{len(uni)}")


if __name__ == "__main__":
    {"scan": cmd_scan, "rank": cmd_rank, "download": cmd_download}[sys.argv[1]]()
