"""W8 parity of the WIDE study's entry adapter (research/hunt/entries_wide.py) against the full grid's own signals.
Signals only: no fill, no exit, no P&L, no outcome of any kind is computed.

    python -m research.hunt.parity_wide --fg1m DIR --out FILE [--procs 2] [--syms BTCUSDT,..] [--tfs 15m,..]

For each of the old six coins and each timeframe: the full grid's path (research/fullgrid/run.signals on run.frame,
the 1m archive DIR/1m/<SYM>.npz binned the full grid's way) against the adapter's path (the same 1m bars binned to 5m
by entries_wide.resample_1m_to_5m, then entries_wide.build_bars and events_on), for every F2 (36 core) and F3 (44
DeepSeek, on their timeframes) entry at its default numbers and every F4 watch pick on its timeframe. Compared on
the bars both series have (same close time): the raw signal arrays and the events (rising edges), per side.

Output (JSON): per strategy x timeframe, pooled over the coins: events of each path, events in one path only, the
mismatch share = events in one path only / events in either path, raw-array bars that differ, and the full grid
arrays' continuation share (event vs state, entries_wide.classify); per coin x timeframe: bars only in one series and
common bars whose OHLC or volume differ. A strategy x timeframe over 1% mismatch fails W8.
"""

from __future__ import annotations

import argparse
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


def cells_for(tf: str) -> list[dict]:
    return [c for c in EW.entry_cells() if c["tf"] == tf and c["family"] in ("F2", "F3", "F4")]


def cell_key(c: dict) -> str:
    return f"{c['family']}:{c['name']}" + (f":r{c['rank']}" if c.get("rank") is not None else "")


def five_of(R, fg1m: str, sym: str) -> tuple:
    d = R.minute_data(fg1m, sym)
    return EW.resample_1m_to_5m(d["ts"], d["o"], d["h"], d["l"], d["c"], d["v"])


def coin_job(args) -> dict:
    fg1m, sym, tfs = args
    os.nice(5)
    R = EW.fullgrid_run()
    t0 = time.time()
    # every frame and 5m array first (the full grid keeps one coin's minutes at a time)
    fr, five = {}, {}
    for s in dict.fromkeys((sym, "BTCUSDT")):
        for tf in tfs:
            fr[s, tf] = R.frame(fg1m, s, tf)
        five[s] = five_of(R, fg1m, s)
        R.minute_data.cache_clear()
    out = {"sym": sym, "bars": {}, "cells": {}}
    for tf in tfs:
        df, close_fg = fr[sym, tf]
        b = EW.build_bars(*five[sym], tf)
        btc = EW.build_bars(*five["BTCUSDT"], tf)
        common, i_fg, i_ad = np.intersect1d(close_fg, b.close_ms, return_indices=True)
        mine = b.df
        diff_px = 0
        for k in ("open", "high", "low", "close"):
            diff_px = np.maximum(diff_px, mine[k].to_numpy()[i_ad] != df[k].to_numpy()[i_fg])
        vf, va = df["volume"].to_numpy()[i_fg], mine["volume"].to_numpy()[i_ad]
        with np.errstate(invalid="ignore", divide="ignore"):
            vrel = np.abs(va - vf) / np.maximum(np.abs(vf), 1e-300)
        out["bars"][tf] = {"fg": int(len(close_fg)), "adapter": int(len(b)), "common": int(len(common)),
                           "only_fg": int(len(close_fg) - len(common)), "only_adapter": int(len(b) - len(common)),
                           "ohlc_differ": int(np.sum(diff_px)), "vol_max_rel": float(np.nanmax(vrel)) if len(vrel) else 0.0,
                           "vol_differ_1e9": int(np.sum(vrel > 1e-9))}
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
                fev = EW.rising(fraw)
                fe, ae = fev[i_fg], aev[i_ad]
                row[side] = {"fg_events": int(fe.sum()), "ad_events": int(ae.sum()), "only_fg": int((fe & ~ae).sum()),
                             "only_ad": int((ae & ~fe).sum()), "raw_differ": int((fraw[i_fg] != araw[i_ad]).sum()),
                             "fg_true": int(fraw.sum()), "fg_cont": int((fraw[1:] & fraw[:-1]).sum())}
                bad = np.flatnonzero(fe != ae)
                if len(bad):
                    row[side]["first_mismatch_close"] = str(np.datetime64(int(common[bad[0]]), "ms"))
            out["cells"][f"{cell_key(c)}|{tf}"] = row
        print(f"[{sym}] {tf} done ({time.time() - t0:.0f}s)", flush=True)
    return out


def summarize(per_coin: list[dict]) -> dict:
    cells: dict = {}
    for pc in per_coin:
        for key, row in pc["cells"].items():
            a = cells.setdefault(key, {"fg_events": 0, "ad_events": 0, "only_fg": 0, "only_ad": 0, "raw_differ": 0,
                                       "fg_true": 0, "fg_cont": 0, "sec": 0.0, "coins_with_mismatch": []})
            a["sec"] += row["sec"]
            mism = 0
            for side in ("long", "short"):
                for k in ("fg_events", "ad_events", "only_fg", "only_ad", "raw_differ", "fg_true", "fg_cont"):
                    a[k] += row[side][k]
                mism += row[side]["only_fg"] + row[side]["only_ad"]
            if mism:
                a["coins_with_mismatch"].append(pc["sym"])
    for a in cells.values():
        union = a["fg_events"] + a["ad_events"] - (a["fg_events"] - a["only_fg"])   # |A u B| = |A| + |B| - |A n B|
        a["union"] = int(union)
        a["mismatch_share"] = (a["only_fg"] + a["only_ad"]) / union if union else 0.0
        share = a["fg_cont"] / a["fg_true"] if a["fg_true"] else 0.0
        a["continuation_share"] = share
        a["array_kind"] = "event" if a["fg_cont"] == 0 else ("state" if share >= 0.5 else "mixed")
        a["sec"] = round(a["sec"], 1)
    worst = max(cells.items(), key=lambda kv: kv[1]["mismatch_share"]) if cells else (None, {"mismatch_share": 0.0})
    over = sorted(k for k, a in cells.items() if a["mismatch_share"] > FAIL_SHARE)
    return {"cells": dict(sorted(cells.items())), "max_mismatch": {"cell": worst[0], "share": worst[1]["mismatch_share"]},
            "over_1pct": over, "pass": not over,
            "bars": {pc["sym"]: pc["bars"] for pc in per_coin}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fg1m", required=True, help="the full grid's data folder (holds 1m/<SYM>.npz)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--procs", type=int, default=2)
    ap.add_argument("--syms", default=",".join(OLD_SIX))
    ap.add_argument("--tfs", default=",".join(EW.TFS))
    a = ap.parse_args(argv)
    syms, tfs = a.syms.split(","), tuple(a.tfs.split(","))
    t0 = time.time()
    R = EW.fullgrid_run()
    R.core_names()
    jobs = [(a.fg1m, s, tfs) for s in syms]
    if a.procs > 1:
        import multiprocessing as mp
        with mp.get_context("fork").Pool(min(a.procs, len(jobs))) as pool:
            per = pool.map(coin_job, jobs, chunksize=1)
    else:
        per = [coin_job(j) for j in jobs]
    doc = summarize(per)
    doc.update({"what": "W8 parity: full grid signals (1m archive, run.frame / run.signals) vs the WIDE adapter (the same "
                        "1m bars -> 5m -> entries_wide); signals only, no outcome",
                "syms": syms, "tfs": list(tfs), "seconds": round(time.time() - t0, 1),
                "code": {f: EW.fullgrid_run()._sha(os.path.join(HERE, f)) for f in ("entries_wide.py", "parity_wide.py")}})
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as fh:
        json.dump(doc, fh, indent=1)
    print(f"max mismatch {doc['max_mismatch']}; over 1%: {doc['over_1pct']}; {doc['seconds']}s")
    return 0 if doc["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
