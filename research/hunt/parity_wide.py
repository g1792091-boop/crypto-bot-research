"""W8 parity of the WIDE study's entry adapter (research/hunt/entries_wide.py) against the full grid's own signals.
Signals only: no fill, no exit, no P&L, no outcome of any kind is computed.

    python -m research.hunt.parity_wide --fg1m DIR --out FILE [--five DIR] [--procs 2] [--syms ..] [--tfs ..]

For each of the old six coins and each timeframe: the full grid's path (research/fullgrid/run.signals on run.frame,
the 1m archive DIR/1m/<SYM>.npz binned the full grid's way) against the adapter's path (entries_wide.build_bars and
events_on on 5m bars), for every F2 (36 core) and F3 (44 DeepSeek, on their timeframes) entry at its default numbers
and every F4 watch pick on its timeframe. The adapter's 5m bars: by default the same 1m archive binned to 5m
(entries_wide.resample_1m_to_5m: the comparison isolates the adapter); with --five, the hunt data's 5m files
(<five>/5m/<SYM>.npz read as select / test read it: hunt.clean_5m drops duplicate, zero-volume, off-grid and
non-finite rows, float32 cast to float64; PREREG_HUNT_WIDE 8 as written, data differences included; the dropped
counts are reported per coin). The output's ``code`` holds the sha256 of entries_wide.py, parity_wide.py and hunt.py:
the wide pin accepts parity.json only when they equal the pinned files and it says pass on the hunt 5m files.

Compared (PREREG_HUNT_WIDE 8) on the bars both series have (same bin), after both series' first run.WARMUP_BARS bars,
per strategy x timeframe x side, for the raw arrays and for the events (entries_wide.rising, the full grid's arrays
taken through the same edge rule): mismatch share = bars where the two differ / bars where either is True, pooled over
the coins. A mismatch at bar t is excused when the two bar series differ beyond PREREG_HUNT 2's tolerance (OHLC 1e-6
relative, volume 0.1%; a bar missing from one series counts as differing) on any bar t-299 .. t of the union of both
series. Fail = an unexcused share above 1% on any strategy x timeframe (either side, raw or event).

Output (JSON, counts and shares only): per strategy x timeframe the pooled counts and shares, the full grid arrays'
continuation share (event / mixed / state, entries_wide.classify), the coins with a mismatch and the first mismatched
bar; per coin x timeframe the bar comparison (bars only in one series, bars beyond tolerance).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.hunt import entries_wide as EW  # noqa: E402

OLD_SIX = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")
FAIL_SHARE = 0.01
TOL_PX, TOL_VOL, EXCUSE_BARS = 1e-6, 1e-3, 300
KEYS = ("raw", "ev")


def cells_for(tf: str) -> list[dict]:
    return [c for c in EW.entry_cells() if c["tf"] == tf and c["family"] in ("F2", "F3", "F4")]


def cell_key(c: dict) -> str:
    return f"{c['family']}:{c['name']}" + (f":r{c['rank']}" if c.get("rank") is not None else "")


def five_of(R, fg1m: str, sym: str, five_dir: str | None = None) -> tuple:
    """(ts, o, h, l, c, v) 5m bars and their H 2 counts. With ``five_dir``: the hunt data's file read exactly as the
    select and test steps read it (hunt.clean_5m: duplicates, zero-quote-volume, off-grid and non-finite rows
    dropped), so the parity checks the bars the run computes its signals on."""
    if five_dir:
        from research.hunt import hunt as H
        with np.load(os.path.join(five_dir, "5m", f"{sym}.npz")) as z:
            cols = {k: z[k] for k in ("ts", "o", "h", "l", "c", "v", "qv")}
        (ts, o, h, lo, c, v, _qv), counts = H.clean_5m(cols["ts"], cols["o"], cols["h"], cols["l"], cols["c"],
                                                       cols["v"], cols["qv"])
        return (np.asarray(ts, np.int64), *(np.asarray(x, np.float64) for x in (o, h, lo, c, v))), counts
    d = R.minute_data(fg1m, sym)
    return EW.resample_1m_to_5m(d["ts"], d["o"], d["h"], d["l"], d["c"], d["v"]), {"source": "1m archive -> 5m"}


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


def bar_compare(df, close_fg: np.ndarray, b) -> tuple[dict, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(summary, common close times, index into the full grid's bars, index into the adapter's bars, excused flag per
    common bar)."""
    common, i_fg, i_ad = np.intersect1d(close_fg, b.close_ms, return_indices=True)
    mine = b.df
    with np.errstate(invalid="ignore", divide="ignore"):
        px = np.zeros(len(common), bool)
        for k in ("open", "high", "low", "close"):
            x, y = df[k].to_numpy()[i_fg], mine[k].to_numpy()[i_ad]
            px |= np.abs(x - y) > TOL_PX * np.abs(x)
        vf, va = df["volume"].to_numpy()[i_fg], mine["volume"].to_numpy()[i_ad]
        vrel = np.abs(va - vf) / np.maximum(np.abs(vf), 1e-300)
    bad_common = px | (vrel > TOL_VOL)
    union = np.union1d(close_fg, b.close_ms)
    bad_union = ~np.isin(union, common)                       # a bar in one series only
    bad_union[np.searchsorted(union, common)] = bad_common
    # excused: any bad bar among the union's bars t-299 .. t
    cs = np.r_[0, np.cumsum(bad_union)]
    pos = np.searchsorted(union, common)
    excused = (cs[pos + 1] - cs[np.maximum(pos + 1 - EXCUSE_BARS, 0)]) > 0
    summary = {"fg": int(len(close_fg)), "adapter": int(len(b)), "common": int(len(common)),
               "only_fg": int(len(close_fg) - len(common)), "only_adapter": int(len(b) - len(common)),
               "beyond_tol": int(bad_common.sum()), "excused_bars": int(excused.sum()),
               "ohlc_not_identical": int(sum(int((df[k].to_numpy()[i_fg] != mine[k].to_numpy()[i_ad]).sum())
                                                 for k in ("open", "high", "low", "close"))),
               "vol_max_rel": float(np.nanmax(vrel)) if len(vrel) else 0.0}
    return summary, common, i_fg, i_ad, excused


def coin_job(args) -> dict:
    fg1m, sym, tfs, five_dir = args
    os.nice(5)
    R = EW.fullgrid_run()
    t0 = time.time()
    # every frame and 5m array first (the full grid keeps one coin's minutes at a time)
    fr, five, five_counts = {}, {}, {}
    for s in dict.fromkeys((sym, "BTCUSDT")):
        for tf in tfs:
            fr[s, tf] = R.frame(fg1m, s, tf)
        five[s], five_counts[s] = five_of(R, fg1m, s, five_dir)
        R.minute_data.cache_clear()
    out = {"sym": sym, "bars": {}, "cells": {}, "five_counts": five_counts[sym]}
    for tf in tfs:
        df, close_fg = fr[sym, tf]
        b = EW.build_bars(*five[sym], tf)
        btc = EW.build_bars(*five["BTCUSDT"], tf)
        out["bars"][tf], common, i_fg, i_ad, excused = bar_compare(df, close_fg, b)
        w = R.WARMUP_BARS
        after = (i_fg >= w) & (i_ad >= w)                     # PREREG_HUNT_WIDE 8: after both series' first 300 bars
        common, i_fg, i_ad, excused = common[after], i_fg[after], i_ad[after], excused[after]
        out["bars"][tf]["compared"] = int(len(common))
        for c in cells_for(tf):
            ts = time.time()
            combo = EW._combo_args(c["combo"])
            R._LAST_SERIES[0] = None
            fl, fs = R.signals(fg1m, c["kind"], c["name"], sym, tf, combo)
            spec = dict(c, id="parity", gate="NONE")
            ev = EW.events_on(spec, b, sym, btc)
            row = {"sec": round(time.time() - ts, 2)}
            for side, fraw, araw, aev in (("long", fl, ev["raw_long"], ev["long"]),
                                          ("short", fs, ev["raw_short"], ev["short"])):
                r = {"fg_true": int(fraw.sum()), "fg_cont": int((fraw[1:] & fraw[:-1]).sum())}
                for key, x, y in (("raw", fraw[i_fg], araw[i_ad]), ("ev", EW.rising(fraw)[i_fg], aev[i_ad])):
                    diff = x != y
                    r[key] = {"fg": int(x.sum()), "ad": int(y.sum()), "either": int((x | y).sum()),
                              "differ": int(diff.sum()), "unexcused": int((diff & ~excused).sum())}
                    if diff.any():
                        r[key]["first_differ_close"] = str(np.datetime64(int(common[np.flatnonzero(diff)[0]]), "ms"))
                row[side] = r
            out["cells"][f"{cell_key(c)}|{tf}"] = row
        print(f"[{sym}] {tf} done ({time.time() - t0:.0f}s)", flush=True)
    return out


def summarize(per_coin: list[dict]) -> dict:
    cells: dict = {}
    for pc in per_coin:
        for key, row in pc["cells"].items():
            a = cells.setdefault(key, {"sec": 0.0, "fg_true": 0, "fg_cont": 0, "coins_with_mismatch": [],
                                       **{f"{side}_{k}": {"fg": 0, "ad": 0, "either": 0, "differ": 0, "unexcused": 0}
                                          for side in ("long", "short") for k in KEYS}})
            a["sec"] += row["sec"]
            mism = False
            for side in ("long", "short"):
                a["fg_true"] += row[side]["fg_true"]
                a["fg_cont"] += row[side]["fg_cont"]
                for k in KEYS:
                    t = a[f"{side}_{k}"]
                    for f in ("fg", "ad", "either", "differ", "unexcused"):
                        t[f] += row[side][k][f]
                    if row[side][k]["differ"]:
                        mism = True
                        t.setdefault("first_differ", {})[pc["sym"]] = row[side][k]["first_differ_close"]
            if mism:
                a["coins_with_mismatch"].append(pc["sym"])
    worst = (None, -1.0, -1.0)
    for key, a in cells.items():
        shares, unexc = [], []
        for side in ("long", "short"):
            for k in KEYS:
                t = a[f"{side}_{k}"]
                t["share"] = t["differ"] / t["either"] if t["either"] else 0.0
                t["unexcused_share"] = t["unexcused"] / t["either"] if t["either"] else 0.0
                shares.append(t["share"])
                unexc.append(t["unexcused_share"])
        a["max_share"], a["max_unexcused_share"] = max(shares), max(unexc)
        share = a["fg_cont"] / a["fg_true"] if a["fg_true"] else 0.0
        a["continuation_share"] = share
        a["array_kind"] = "event" if a["fg_cont"] == 0 else ("state" if share >= 0.5 else "mixed")
        a["sec"] = round(a["sec"], 1)
        if a["max_share"] > worst[1]:
            worst = (key, a["max_share"], a["max_unexcused_share"])
    over = sorted(k for k, a in cells.items() if a["max_unexcused_share"] > FAIL_SHARE)
    over_raw = sorted(k for k, a in cells.items() if a["max_share"] > FAIL_SHARE)
    kinds: dict = {}
    for key, a in cells.items():
        kinds.setdefault(a["array_kind"], []).append(key)
    return {"pass": not over, "over_1pct_unexcused": over, "over_1pct_any": over_raw,
            "max_mismatch": {"cell": worst[0], "share": worst[1], "unexcused_share": worst[2]},
            "array_kinds": {k: sorted(v) for k, v in sorted(kinds.items())},
            "bars": {pc["sym"]: pc["bars"] for pc in per_coin},
            "five_counts": {pc["sym"]: pc.get("five_counts") for pc in per_coin}, "cells": dict(sorted(cells.items()))}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fg1m", required=True, help="the full grid's data folder (holds 1m/<SYM>.npz)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--five", help="the hunt data folder (5m/<SYM>.npz); default: the 1m archive binned to 5m")
    ap.add_argument("--procs", type=int, default=2)
    ap.add_argument("--syms", default=",".join(OLD_SIX))
    ap.add_argument("--tfs", default=",".join(EW.TFS))
    a = ap.parse_args(argv)
    syms, tfs = a.syms.split(","), tuple(a.tfs.split(","))
    t0 = time.time()
    R = EW.fullgrid_run()
    R.core_names()
    jobs = [(a.fg1m, s, tfs, a.five) for s in syms]
    if a.procs > 1:
        import multiprocessing as mp
        with mp.get_context("fork").Pool(min(a.procs, len(jobs))) as pool:
            per = pool.map(coin_job, jobs, chunksize=1)
    else:
        per = [coin_job(j) for j in jobs]
    doc = summarize(per)
    doc.update({"what": "W8 parity: full grid signals (1m archive, run.frame / run.signals) vs the WIDE adapter ("
                        + ("the hunt data's 5m bars" if a.five else "the same 1m bars -> 5m") + " -> entries_wide); "
                        "signals only, no outcome", "adapter_5m": "hunt 5m files" if a.five else "1m archive -> 5m",
                "syms": syms, "tfs": list(tfs), "seconds": round(time.time() - t0, 1),
                "code": {f: _sha(os.path.join(HERE, f)) for f in ("entries_wide.py", "parity_wide.py", "hunt.py")}})
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as fh:
        json.dump(doc, fh, indent=1)
    print(f"max mismatch {doc['max_mismatch']}; over 1% unexcused: {doc['over_1pct_unexcused']}; "
          f"over 1% any: {doc['over_1pct_any']}; {doc['seconds']}s")
    return 0 if doc["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
