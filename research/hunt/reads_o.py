"""Trend hunt, Phase-B autopsy reads O1-O5 (PREREG_HUNT_WIDE W 7.4a, owners 2026-10-11 about 23:20-23:50 KST).
Reported, never a pass: nothing here changes a pick, a batch, P0-P4, p, BH, PASS, WIDE PASS, the lineup or what
goes to the paper bot; no read chooses a system; ``run(ctx)`` writes no file (the reads hook writes ``ctx["out"]``
and ``ctx["private"]``). Reads interface api 1 (the same ``run(ctx)`` as reads_a.py).

What it computes, on the fixed ROWS (tested picks, the v1 pick, the baskets), select and test side by side:

* O1 weekend version: the same machine with every first-unit entry whose signal bar closes (UTC) at or after
  Saturday 00:00 and before Monday 00:00 skipped (counted as "weekend", never queued); adds, stops, chandelier and
  exits unchanged; every timeframe of every row. O1b: only long first-unit entries skipped. Per row, period and
  variant: mean and median monthly ln M, win share, positions, max drawdown, cost x2 mean ln M, controls (a) and (b)
  seeds 1-200 (the pinned W 6 draws, filtered by the same rule on each draw's own signal-bar close and side) with
  pick-minus-control mean d_m, and the R1 headline shares (end and touch >= x2 and >= x5, bust) of fresh $1,000
  accounts over UTC calendar months at the size fixed on select (reads_a's rule on the tested machine), with the
  controls' pooled shares on the same board (seeds 1-200). The weekend-included machine ("base") is rerun with the
  same seeds so that every difference is like for like.
* O1 select-only map: the W 5 walk (eligibility, order, one per strategy name, batches of 10) rerun on the select
  period with the weekend-skip machine over the 686 candidate systems (F1-F3, F5), on the select data cut at the
  select end exactly as the select step loads it (no 5m bar at or after the select end is used, not even for
  indicators). Lists what it would have picked. Those systems are never run on the test period here.
* O2 macro blackout: as O1, skipping first-unit entries whose signal bar closes in [T - 120 min, T] (the bar closing
  at T included), T = an FOMC statement time or a US nonfarm payrolls (Employment Situation) release time; variant
  FOMC only. Dates and times from research/hunt/macro_calendar.json, read only when that file's line is in the pin
  with its current sha256 and every event that can touch a read period is marked verified from an official page.
* O3 same-side risk cap: NOT computed. It needs the engine to block an entry or add by the open risk of all
  same-side positions and a per-5m-close stress ledger; neither exists in the pinned engine (``O3_NEEDS``).
* O4 momentum control (f): the row's gated signal times and coins with side = sign(close of the signal bar - close
  20 bars before on the same series) (0 or fewer than 20 earlier bars: no entry, counted), one deterministic run of
  the tested machine; pick minus (f) monthly ln M and the share of the pick's sides equal to (f)'s. R6 (e)
  momentum-side random times (control (a)'s draw procedure with control name "e" in the W 6 seed parts, side = the
  drawn bar's momentum sign, 0 dropped and counted; 1,000 seeds in test, 200 in select) with mean d_m, its
  month-block bootstrap p and its seed rank. Label (pre-registered): a pick whose test mean d_m against (e) or
  against (f) is <= 0 is "momentum only: a plain momentum entry did as well".
* O5: N17_KC_RSI systems and rows carry "anti-momentum entry (select period; also on the 5-year anti-edge list,
  which saw test months)"; no flipped system is added.

D11: every money figure of a row that contains a DeepSeek pick, and every DeepSeek (F3) row of the select map, goes
to ``ctx["private"]`` only; the public copy keeps labels and counts.

``python -m research.hunt.reads_o --study wide --data DIR [--procs N] [--private DIR]`` runs this module through
hunt.py's own reads hook (``run_reads_hooks(..., names=("reads_o",))``, the read guard and the D11 check included)
after test.json exists; it refuses unless research/hunt/reads_o.py is listed in the study's pin file with its
current sha256 (hunt.py's READS_MODULES lists reads_a only, and hunt.py is pinned, so it is not edited).

The pure functions (weekend and blackout masks, ET -> UTC with US daylight saving, the calendar schema check,
momentum sides, D11 redaction) are tested alone on synthetic values (tests/test_hunt_reads_o.py); the engine glue on
synthetic coins.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import sys
import time

import numpy as np

from research.hunt import hunt as H
from research.hunt import reads_a as RA

# ------------------------------------------------------------------ fixed numbers (W 7.4a, R6 (e), W 7.1)
MODULE_NAME = "reads_o"
MODULE_REL = "research/hunt/reads_o.py"
CALENDAR_REL = "research/hunt/macro_calendar.json"
O_PERIODS = ("select", "test")
PERIOD_LABEL = {"select": "select period (chosen here)", "test": "test period"}
VARIANTS = ("base", "O1", "O1b", "O2", "O2_fomc")
VARIANT_LABEL = {
    "base": "tested machine, weekends included (rerun with the same control seeds)",
    "O1": "O1 weekend version: first-unit entries with a signal bar closing Sat 00:00 .. Mon 00:00 UTC skipped",
    "O1b": "O1b: only long first-unit entries with a weekend signal-bar close skipped",
    "O2": "O2 macro blackout: first-unit entries with a signal bar closing in [T - 120 min, T], T = FOMC statement "
          "or US nonfarm payrolls release, skipped",
    "O2_fomc": "O2 variant FOMC only: [T - 120 min, T], T = FOMC statement",
}
CTL_SEEDS = 200                         # W 7.4a: controls (a) / (b) seeds 1-200 through the changed machine
E_SEEDS = {"test": 1000, "select": 200}  # R6: 1,000 seeds in test, 200 in select
MOM_BARS = 20                           # R6 (e), O4 (f): close[t] - close[t - 20]
BLACKOUT_MIN = 120                      # O2: [T - 120 min, T]
HEAD_COLS = ("end_ge_x2", "end_ge_x5", "touch_x2", "touch_x5", "bust")
CTL_TASK_SEEDS = 25                     # control seeds per worker task
E_TASK_SEEDS = 100
DAY = H.DAY_MS
FIVE = H.FIVE
EPOCH_WEEKDAY = 3                       # 1970-01-01 was a Thursday (Monday = 0)
MOMENTUM_ONLY_LABEL = "momentum only: a plain momentum entry did as well"
O5_NAME = "N17_KC_RSI"
O5_LABEL = "anti-momentum entry (select period; also on the 5-year anti-edge list, which saw test months)"
DS_NOTE = "DeepSeek row: figures in the private file (D11)"
CAL_KINDS = ("FOMC", "NFP")
CAL_TIME = {"FOMC": "14:00", "NFP": "08:30"}      # the usual release times (ET); exceptions are written per event
CAL_HOSTS = {"FOMC": "https://www.federalreserve.gov/", "NFP": "https://www.bls.gov/"}
CAL_YEARS = tuple(range(2020, 2027))

O3_NEEDS = [
    "Engine parameter PR_SIDECAP (fraction of equity; 0 = off, the default, so the tested machine stays bit-identical):"
    " before a first unit or an add is taken, sum the open risk (_risk: quantity x distance from the fill to the "
    "current stop, the same quantity the 4% total cap uses) of every open position on the same side, across all "
    "coins, plus the new unit's risk; skip when the sum would exceed PR_SIDECAP x equity at the previous 5m close. "
    "Machine A at r = 0.5%: PR_SIDECAP = 0.02 (half of the 4% cap); machine B: min(2r, 0.30).",
    "Skip counters: SKIP_NAMES += 'side_cap' (first units) and ADD_SKIP_NAMES += 'side_cap' (adds), exported in "
    "metrics like the other reasons, so O3 can report what the cap removed.",
    "Stress ledger (decision path untouched; a test asserts equity and trades bit-identical with it on and off): at "
    "every 5m close, per side, S_g = sum over open same-side positions of q x (close - stop x (1 - g)) for longs and "
    "q x (stop x (1 + g) - close) for shorts, g = 0, 0.05, 0.10 (the loss to the current stop, plus a 5% and a 10% "
    "gap through it); export the maximum of S_g / equity per side and g with its 5m step (date). The trade list "
    "cannot give it: it has no stop path, no add fill times and no add quantities (adds can be cut by the margin "
    "budget or the free wallet), so any reconstruction would be a second engine.",
    "Then O3 = O1's summary on the changed machine (both periods, controls seeds 1-200 through the same cap, the R1 "
    "headline shares at the size fixed on select) plus the stress line for the base and the capped machine.",
]

CHOICES = [
    "Weekend (O1): the signal bar's close in UTC with weekday Saturday or Sunday, i.e. close >= Saturday 00:00 and "
    "< Monday 00:00 (a bar closing Saturday 00:00 is a weekend bar; one closing Monday 00:00 is not). The rule is "
    "applied to the system's gated signals before the run (a skipped signal is never queued; a later signal on the "
    "same coin can then be taken, as when the engine skips one).",
    "'weekend' / 'blackout' counts = gated signals removed (by side); 'base_positions_removed' = positions of the base "
    "run whose signal is removed (matched on coin and fill bar).",
    "Controls: the pinned W 6 draws (ctx control_signals, seed parts with r = 0.5%), seeds 1-200, each draw filtered "
    "by the same rule on its own signal-bar close and side; a basket's control = each member's draw with the same "
    "seed in one wallet (src = pick number). d_m = ln M_m(row) - mean over seeds; the base machine is rerun with the "
    "same seeds 1-200 (the pass's 1,000-seed d_m stays in test.json).",
    "Headline shares: fresh $1,000 per UTC calendar month, positions open at the month end closed at the last 5m "
    "close (headline convention of reads_a), touch = the engine's 5m peak; at the size fixed on select, chosen per "
    "row by reads_a's rule (ctx size_fixed_on_select over the 9 machine A / B cells) on the tested machine's select "
    "calendar months; the same cell for every variant; Clopper-Pearson 95%; controls pooled over seeds 1-200.",
    "O2: T = the release time of the FOMC's post-meeting policy statement (scheduled or unscheduled meeting, or a "
    "notation vote that issued a policy statement) and of the Employment Situation news release; times in ET "
    "converted to UTC with the US daylight-saving rule (second Sunday of March to the first Sunday of November); the "
    "statement on longer-run goals (2025-08-22 notation vote) is not a policy statement and is listed as excluded. "
    "O2 runs only when research/hunt/macro_calendar.json is in the pin with its current sha256, passes the schema "
    "check and every event that can touch a read period is marked verified_official.",
    "O4 (f) and R6 (e): momentum = sign(close[j] - close[j - 20]) on the signal bar's own series (bars of the "
    "coin's series, as every lookback); fewer than 20 earlier bars = undefined; 0 and undefined give no entry and are "
    "counted. (e) seed parts = W 6's with control 'e' (v1 rows: H 12's), p = hunt.boot_p with the 'boot' parts, "
    "seed rank = (1 + seeds with mean ln M >= the row's) / (n + 1). Label rule applied to pick and v1 rows.",
    "Select-only map: the select step's data cut (every coin's 5m bars and funding before the select end; the coin "
    "end as load_coin sets it), hunt's own system_signals / run_signals / wide_eligible / wide_choose, base cost and "
    "cost x2 at r = 0.5% with the weekend rule; F4 never; the map's picks are compared with picks.json's members.",
    "D11: rows that contain a DeepSeek pick and F3 rows of the map keep labels and counts in public (floats dropped); "
    "all figures in the private file.",
]


# ------------------------------------------------------------------ small helpers
def _f(x):
    if x is None:
        return None
    x = float(x)
    return x if math.isfinite(x) else None


def _mean(x):
    x = np.asarray(x, float)
    return _f(x.mean()) if len(x) else None


def utc_weekday(ms) -> np.ndarray:
    """UTC weekday of epoch-ms times (Monday = 0 .. Sunday = 6)."""
    d = np.floor_divide(np.asarray(ms, np.int64), DAY)
    return (d + EPOCH_WEEKDAY) % 7


def is_weekend_close(close_ms) -> np.ndarray:
    """O1: the signal bar closes at or after Saturday 00:00 UTC and before Monday 00:00 UTC."""
    return utc_weekday(close_ms) >= 5


def in_blackout(close_ms, event_ms, minutes: int = BLACKOUT_MIN) -> np.ndarray:
    """O2: close in [T - minutes, T] (both ends included) for some event time T."""
    c = np.asarray(close_ms, np.int64)
    ev = np.sort(np.asarray(event_ms, np.int64))
    if not len(ev) or not len(c):
        return np.zeros(len(c), bool)
    i = np.searchsorted(ev, c, "left")                      # first T >= close
    ok = i < len(ev)
    nxt = ev[np.minimum(i, len(ev) - 1)]
    return ok & (nxt - c <= int(minutes) * 60_000)


def skip_mask(variant: str, close_ms, side, events: dict | None = None) -> np.ndarray:
    """True = the first-unit entry of this signal is skipped by the variant's machine."""
    c = np.asarray(close_ms, np.int64)
    s = np.asarray(side, np.int64)
    if variant == "base":
        return np.zeros(len(c), bool)
    if variant == "O1":
        return is_weekend_close(c)
    if variant == "O1b":
        return is_weekend_close(c) & (s > 0)
    if variant in ("O2", "O2_fomc"):
        if events is None:
            raise ValueError("O2 needs the macro calendar")
        ev = events["fomc"] if variant == "O2_fomc" else np.r_[events["fomc"], events["nfp"]]
        return in_blackout(c, ev)
    raise ValueError(f"variant {variant!r}")


def subset(sig: dict, keep, side=None) -> dict:
    """The signals of ``sig`` where ``keep`` (optionally with new sides); keeps ``syms`` when present."""
    keep = np.asarray(keep, bool)
    out = {"tf": sig["tf"], "k": np.asarray(sig["k"])[keep], "j": np.asarray(sig["j"])[keep],
           "side": (np.asarray(sig["side"]) if side is None else np.asarray(side))[keep].astype(np.int64)}
    if sig.get("syms") is not None:
        out["syms"] = list(sig["syms"])
    return out


def momentum_from_closes(c, j, n: int = MOM_BARS) -> tuple:
    """(side, defined) per bar index j of a close series: sign(c[j] - c[j - n]); undefined (side 0) for j < n."""
    c = np.asarray(c, np.float64)
    j = np.asarray(j, np.int64)
    ok = j >= n
    prev = c[np.maximum(j - n, 0)]
    side = np.where(ok, np.sign(c[j] - prev), 0.0)
    side = np.where(np.isfinite(side), side, 0.0)
    return side.astype(np.int64), ok


def momentum_sides(live, syms: list, sig: dict, n: int = MOM_BARS) -> tuple:
    """Momentum side of every signal of ``sig`` on its own series (coin, timeframe)."""
    k = np.asarray(sig["k"], np.int64)
    j = np.asarray(sig["j"], np.int64)
    side = np.zeros(len(k), np.int64)
    ok = np.zeros(len(k), bool)
    names = sig.get("syms") or syms
    for kk in np.unique(k):
        sel = k == kk
        ser = live.series(names[int(kk)], sig["tf"])
        s_, o_ = momentum_from_closes(ser.bars.c, j[sel], n)
        side[sel], ok[sel] = s_, o_
    return side, ok


def close_ms_of(live, syms: list, sig: dict) -> np.ndarray:
    k = np.asarray(sig["k"], np.int64)
    j = np.asarray(sig["j"], np.int64)
    out = np.zeros(len(k), np.int64)
    names = sig.get("syms") or syms
    for kk in np.unique(k):
        sel = k == kk
        out[sel] = np.asarray(live.series(names[int(kk)], sig["tf"]).bars.close_ms, np.int64)[j[sel]]
    return out


# ------------------------------------------------------------------ ET -> UTC (US daylight saving since 2007)
def _nth_sunday(y: int, m: int, n: int) -> dt.date:
    d = dt.date(y, m, 1)
    first = d + dt.timedelta(days=(6 - d.weekday()) % 7)
    return first + dt.timedelta(days=7 * (n - 1))


def us_dst(day: dt.date) -> bool:
    """US Eastern daylight time is in force at the given local date after 02:00 (second Sunday of March to the first
    Sunday of November, the rule since 2007). Every calendar time used here is after 02:00 local."""
    return _nth_sunday(day.year, 3, 2) <= day < _nth_sunday(day.year, 11, 1)


def et_to_utc_ms(date_et: str, time_et: str) -> int:
    """'YYYY-MM-DD', 'HH:MM' New York local time -> epoch ms UTC (EDT = UTC-4, EST = UTC-5)."""
    d = dt.date.fromisoformat(date_et)
    hh, mm = (int(x) for x in time_et.split(":"))
    off = 4 if us_dst(d) else 5
    t = dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=dt.timezone.utc) + dt.timedelta(hours=off)
    return int(t.timestamp() * 1000)


def utc_iso(ms: int) -> str:
    return dt.datetime.fromtimestamp(int(ms) / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def tz_name(date_et: str) -> str:
    return "EDT" if us_dst(dt.date.fromisoformat(date_et)) else "EST"


# ------------------------------------------------------------------ the macro calendar (O2)
def calendar_counts(events: list) -> dict:
    """{kind: {year: n}} of the listed events (by the ET release date)."""
    out = {k: {} for k in CAL_KINDS}
    for e in events:
        y = e["date_et"][:4]
        out[e["kind"]][y] = out[e["kind"]].get(y, 0) + 1
    return out


def validate_calendar(doc: dict) -> list:
    """Schema and consistency of research/hunt/macro_calendar.json; [] when it is sound. Checked: the fields of every
    event, the ET -> UTC conversion (t_ms, utc, tz), the official host of every source URL, order and duplicates,
    the counts written in the file, and the yearly counts (8 scheduled FOMC meetings, 12 Employment Situation
    releases) unless the year is listed under count_exceptions with a reason."""
    bad = []
    if not isinstance(doc, dict):
        return ["not a JSON object"]
    for k in ("what", "sources", "events", "counts", "count_exceptions", "excluded", "dst_rule"):
        if k not in doc:
            bad.append(f"missing key {k}")
    ev = doc.get("events") or []
    if not isinstance(ev, list) or not ev:
        return bad + ["no events"]
    last = None
    seen = set()
    for i, e in enumerate(ev):
        tag = f"events[{i}]"
        for k in ("kind", "label", "date_et", "time_et", "tz", "utc", "t_ms", "source_urls", "evidence",
                  "verified_official"):
            if k not in e:
                bad.append(f"{tag}: missing {k}")
        if any(k not in e for k in ("kind", "date_et", "time_et", "t_ms")):
            continue
        if e["kind"] not in CAL_KINDS:
            bad.append(f"{tag}: kind {e['kind']!r}")
            continue
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(e["date_et"])) or not re.fullmatch(r"\d{2}:\d{2}",
                                                                                           str(e["time_et"])):
            bad.append(f"{tag}: date/time format")
            continue
        if e["kind"] == "FOMC" and e.get("meeting_type") not in ("scheduled", "unscheduled", "notation_vote"):
            bad.append(f"{tag}: meeting_type {e.get('meeting_type')!r}")
        want = et_to_utc_ms(e["date_et"], e["time_et"])
        if int(e["t_ms"]) != want:
            bad.append(f"{tag}: t_ms {e['t_ms']} != {want} ({e['date_et']} {e['time_et']} ET)")
        if e.get("utc") != utc_iso(want):
            bad.append(f"{tag}: utc {e.get('utc')} != {utc_iso(want)}")
        if e.get("tz") != tz_name(e["date_et"]):
            bad.append(f"{tag}: tz {e.get('tz')} != {tz_name(e['date_et'])}")
        urls = e.get("source_urls") or []
        if not urls or any(not str(u).startswith(CAL_HOSTS[e["kind"]]) for u in urls):
            bad.append(f"{tag}: source_urls must be official {CAL_HOSTS[e['kind']]} pages")
        if not isinstance(e.get("verified_official"), bool):
            bad.append(f"{tag}: verified_official must be true or false")
        key = (e["kind"], int(e["t_ms"]))
        if key in seen:
            bad.append(f"{tag}: duplicate {key}")
        seen.add(key)
        if last is not None and int(e["t_ms"]) < last:
            bad.append(f"{tag}: events not in time order")
        last = int(e["t_ms"])
    if bad:
        return bad
    cnt = calendar_counts(ev)
    if doc.get("counts") != cnt:
        bad.append(f"counts in the file {doc.get('counts')} != the events' {cnt}")
    exc = doc.get("count_exceptions") or {}
    for y in CAL_YEARS:
        ys = str(y)
        sched = sum(1 for e in ev if e["kind"] == "FOMC" and e["date_et"][:4] == ys
                    and e.get("meeting_type") == "scheduled")
        if sched != 8 and f"FOMC:{ys}" not in exc:
            bad.append(f"FOMC {ys}: {sched} scheduled meetings, not 8, and no count_exceptions entry")
        n = cnt["NFP"].get(ys, 0)
        if n != 12 and f"NFP:{ys}" not in exc:
            bad.append(f"NFP {ys}: {n} releases, not 12, and no count_exceptions entry")
    for k, why in exc.items():
        if not isinstance(why, str) or not why.strip():
            bad.append(f"count_exceptions {k}: a reason is needed")
    return bad


def calendar_status(study: str, periods: dict | None = None) -> dict:
    """Whether O2 may run: the calendar file exists, its line is in the study's pin with its current sha256, it passes
    the schema check and every event that can touch a read period ([start, end + 120 min)) is verified_official."""
    full = os.path.join(H.ROOT, CALENDAR_REL)
    st = {"file": CALENDAR_REL, "exists": os.path.exists(full), "pinned": False, "problems": [],
          "unverified_in_periods": None, "run": False}
    if not st["exists"]:
        st["reason"] = f"{CALENDAR_REL} does not exist"
        return st
    sha = H.sha256_file(full)
    st["sha256"] = sha
    try:
        listed = {p: h for h, p in H.read_pin(study)}
    except H.PinError:
        listed = {}
    st["pinned"] = listed.get(CALENDAR_REL) == sha
    try:
        with open(full) as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as e:
        st["problems"] = [f"unreadable: {e}"]
        st["reason"] = "the calendar file is not valid JSON"
        return st
    st["problems"] = validate_calendar(doc)
    ev = doc.get("events") or []
    rel = []
    if not st["problems"]:
        spans = [(int(a), int(b) + BLACKOUT_MIN * 60_000) for a, b in (periods or {}).values()]
        rel = [e for e in ev if not spans or any(a <= int(e["t_ms"]) < b for a, b in spans)]
        unv = [f"{e['kind']} {e['date_et']}" for e in rel if e.get("verified_official") is not True]
        st["unverified_in_periods"] = len(unv)
        st["unverified_examples"] = unv[:10]
    if not st["pinned"]:
        st["reason"] = (f"{CALENDAR_REL} is not in {H.PIN[study]} with its current sha256 (W 7.4a: its line is "
                        "appended to the pin before the read runs)")
    elif st["problems"]:
        st["reason"] = "the calendar fails the schema check: " + "; ".join(st["problems"][:5])
    elif st["unverified_in_periods"]:
        st["reason"] = (f"{st['unverified_in_periods']} calendar events inside the read periods are not verified "
                        "from an official page (verified_official false)")
    else:
        st["run"] = True
        st["reason"] = "pinned, schema sound, every event inside the read periods verified"
        st["events"] = {"fomc": np.asarray(sorted(int(e["t_ms"]) for e in ev if e["kind"] == "FOMC"), np.int64),
                        "nfp": np.asarray(sorted(int(e["t_ms"]) for e in ev if e["kind"] == "NFP"), np.int64)}
        st["counts_in_periods"] = {k: sum(1 for e in rel if e["kind"] == k) for k in CAL_KINDS}
    return st


# ------------------------------------------------------------------ D11
def redact(obj):
    """Labels and counts only: strings, bools, ints and None kept (numpy ints as int), every float dropped,
    recursively (lists keep their non-float items)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(v, (float, np.floating)):
                continue
            r = redact(v)
            if isinstance(v, (dict, list, tuple)) or r is not None or v is None:
                out[k] = r
        return out
    if isinstance(obj, (list, tuple)):
        return [redact(v) for v in obj if not isinstance(v, (float, np.floating))]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if obj is None or isinstance(obj, str):
        return obj
    if isinstance(obj, np.ndarray):
        return [redact(v) for v in obj.tolist() if not isinstance(v, float)]
    return str(obj)


def plain(obj):
    """JSON-safe copy (numpy -> Python, NaN -> None)."""
    if isinstance(obj, dict):
        return {str(k): plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [plain(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [plain(v) for v in obj.tolist()]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return _f(obj)
    return obj


def split_ds(section: dict, ds_of: dict) -> tuple:
    """(public, private) of {row id: read}: a DeepSeek row goes to private whole and to public redacted."""
    pub, priv = {}, {}
    for rid, v in section.items():
        if ds_of.get(rid):
            r = redact(v)
            r["note"] = DS_NOTE
            pub[rid], priv[rid] = r, v
        else:
            pub[rid] = v
    return pub, priv


# ------------------------------------------------------------------ headline shares
def headline_shares(bits, ctl_bits: dict | None = None) -> dict:
    """R1 headline columns of one board (UTC calendar months at one cell): shares ending >= x2, x5, touching x2, x5
    and bust, Clopper-Pearson 95%, and the controls' pooled shares (seeds pooled)."""
    bits = np.asarray(bits, np.int64)
    n = len(bits)
    out = {"n_windows": int(n)}
    if not n:
        return out
    cols = RA.cols_from_bits(bits)
    out["shares"] = {c: float(cols[c].mean()) for c in HEAD_COLS}
    out["counts"] = {c: int(round(cols[c].sum())) for c in HEAD_COLS}
    out["ci"] = {c: list(RA.clopper_pearson(out["counts"][c], n)) for c in HEAD_COLS}
    if ctl_bits:
        out["controls"] = {}
        for cn, mat in ctl_bits.items():
            mat = np.asarray(mat, np.int64)
            if mat.size == 0:
                continue
            cc = RA.cols_from_bits(mat)
            out["controls"][cn] = {"n_seeds": int(mat.shape[0]),
                                   "pooled": {c: float(cc[c].mean()) for c in HEAD_COLS}}
    return out


def seed_rank_p(row_mean: float, seed_means) -> float:
    s = np.asarray(seed_means, float)
    return float((1 + int((s >= row_mean).sum())) / (len(s) + 1))


# ------------------------------------------------------------------ engine glue (reads interface api 1)
_S: dict = {}          # state shared with forked workers


def _study_of(spec: dict) -> str:
    return "v1" if str(spec.get("id", "")).startswith("v1:") else "wide"


def _row_id(row: dict) -> str:
    return row["row"]


def _row_meta(row: dict) -> dict:
    return {"row": row["row"], "kind": row["kind"], "label": row["label"], "candidate": bool(row.get("candidate")),
            "members": [m["id"] for m in row["members"]], "tfs": sorted({m["tf"] for m in row["members"]},
                                                                        key=H.TF_ORDER.index)}


def _variant_parts(parts: list, metas: list, variant: str, events) -> tuple:
    """(filtered parts, filtered metas, skipped masks) of one variant."""
    vp, vm, masks = [], [], []
    for (sig, src), meta in zip(parts, metas):
        sk = skip_mask(variant, meta["close"], meta["side"], events)
        keep = ~sk
        vp.append((subset(sig, keep), src))
        vm.append({k: (v[keep] if isinstance(v, np.ndarray) and len(v) == len(keep) else v) for k, v in meta.items()})
        masks.append(sk)
    return vp, vm, masks


def _meta(live, syms: list, sig: dict) -> dict:
    """close, fill (ms) and side of every signal (reads_a.sig_info) for masks and window slicing."""
    inf = RA.sig_info(live, syms, sig)
    return {"close": inf["close"], "fill": inf["fill"], "side": inf["side"], "k": inf["k"]}


def _window_parts(parts: list, metas: list, a: int, b: int) -> list:
    out = []
    for (sig, src), m in zip(parts, metas):
        keep = (m["close"] >= a) & (m["close"] < b) & (m["fill"] >= a) & (m["fill"] < b)
        out.append((subset(sig, keep), src))
    return out


def _cell_run(run, parts: list, metas: list, a: int, b: int, cell: tuple) -> dict:
    r, ov = RA.cell_overrides(*cell)
    return run(_window_parts(parts, metas, a, b), a, b, r=r, start_wallet=RA.GOAL_START, overrides=ov,
               close_end=True)


def _bits(res: dict) -> int:
    return RA.bits_of(res["end"] / RA.GOAL_START, res["peak"] / RA.GOAL_START, res["bust"])


def _sizefix_task(task) -> tuple:
    """Worker: the tested machine's select calendar months of one row at the 9 machine A / B cells (base, weekends
    included): mean ln(window multiple) and bust share per cell, for the size fixed on select."""
    ri = task
    ctx = _S["ctx"]
    parts, metas = _S["parts"][(ri, "select")], _S["metas"][(ri, "select")]
    wins = _S["wins"]["select"]
    out = {}
    for cell in RA.board_cells():
        m, bust = [], []
        for a, b in wins:
            res = _cell_run(ctx["run"], parts, metas, a, b, cell)
            m.append(res["end"] / RA.GOAL_START)
            bust.append(bool(res["bust"]))
        out[cell] = {"mean_ln_multiple": _mean(np.log(np.maximum(np.asarray(m, float), 1e-12))),
                     "bust_share": _mean(np.asarray(bust, float)), "n_windows": len(wins)}
    return ri, out


def _pick_task(task) -> tuple:
    """Worker: one row, period and variant: the tested account ($5,000, r = 0.5%) at base cost and cost x2 and the
    headline board at the row's fixed cell."""
    ri, p, v = task
    ctx = _S["ctx"]
    a, b = _S["periods"][p]
    parts, metas = _S["vparts"][(ri, p, v)], _S["vmetas"][(ri, p, v)]
    base = ctx["run"](parts, a, b, r=H.R_BASE, cost="base")
    c2 = ctx["run"](parts, a, b, r=H.R_BASE, cost="x2")
    m, mc = base["metrics"], c2["metrics"]
    tr = base.get("trades") or {}
    coin = np.asarray(tr.get("coin", []), np.int64)
    fill = a + np.asarray(tr.get("t_in", []), np.int64) * int(base.get("step_ms", FIVE))
    out = {"metrics": {k: m.get(k) for k in ("mean_lnM", "median_lnM", "median_M", "win_share", "n_positions",
                                              "max_dd", "bust", "end_multiple", "months", "share_M_lt_0_9",
                                              "worst_month")},
           "lnM": list(m["lnM"]), "cost2": {k: mc.get(k) for k in ("mean_lnM", "median_M", "bust")},
           "taken": (coin, fill), "skipped_engine": dict(m.get("skipped") or {})}
    cell = _S["fixed"].get(ri)
    if cell is not None:
        out["bits"] = np.asarray([_bits(_cell_run(ctx["run"], parts, metas, wa, wb, cell))
                                  for wa, wb in _S["wins"][p]], np.int64)
    return ri, p, v, out


def _ctl_task(task) -> tuple:
    """Worker: one row, period, control and seed chunk: every variant's continuous account (monthly ln M) and the
    headline board bits at the row's fixed cell, from the same pinned draws."""
    ri, p, ctl, seeds = task
    ctx = _S["ctx"]
    row = ctx["rows"][ri]
    a, b = _S["periods"][p]
    syms, live, variants = _S["syms"], _S["live"], _S["variants"]
    cell = _S["fixed"].get(ri)
    vp = {}
    lnm = {v: [] for v in variants}
    for s in seeds:
        draws = [(ctx["control_signals"](m, ctl, p, H.R_BASE, s), src) for m, src in zip(row["members"], row["src"])]
        metas = [_meta(live, syms, sig) for sig, _ in draws]
        for v in variants:
            parts_v, metas_v, _ = _variant_parts(draws, metas, v, _S["events"])
            vp[(s, v)] = (parts_v, metas_v)
            lnm[v].append(ctx["run"](parts_v, a, b, r=H.R_BASE)["metrics"]["lnM"])
    bits = {v: np.zeros((len(seeds), len(_S["wins"][p])), np.int16) for v in variants}
    if cell is not None:
        for wj, (wa, wb) in enumerate(_S["wins"][p]):
            for si, s in enumerate(seeds):
                for v in variants:
                    pv, mv = vp[(s, v)]
                    bits[v][si, wj] = _bits(_cell_run(ctx["run"], pv, mv, wa, wb, cell))
    return ri, p, ctl, tuple(seeds), {v: np.asarray(lnm[v], float) for v in variants}, bits


def _e_task(task) -> tuple:
    """Worker: R6 (e) momentum-side random times for one row, period and seed chunk: monthly ln M per seed and the
    counts of draws without a momentum side."""
    ri, p, seeds = task
    ctx = _S["ctx"]
    row = ctx["rows"][ri]
    live, syms = _S["live"], _S["syms"]
    a, b = _S["periods"][p]
    mk = _S["mks"][p]
    rng_of = ctx["helpers"]["rng_of"]
    parts_fn = ctx["seeds"]["seed_parts"]
    lnm, zero, undef, drawn = [], 0, 0, 0
    for s in seeds:
        parts = []
        for m, src in zip(row["members"], row["src"]):
            sig = ctx["signals"](m, mk)
            d = live.control_a(mk, sig, rng_of(*parts_fn(_study_of(m), m, "e", p, H.R_BASE, s)))
            side, ok = momentum_sides(live, syms, d)
            drawn += len(side)
            undef += int((~ok).sum())
            zero += int((ok & (side == 0)).sum())
            parts.append((subset(d, side != 0, side), src))
        lnm.append(ctx["run"](parts, a, b, r=H.R_BASE)["metrics"]["lnM"])
    return ri, p, tuple(seeds), np.asarray(lnm, float), {"drawn": drawn, "no_side_zero_move": zero,
                                                          "no_side_undefined": undef}


def _f_task(task) -> tuple:
    """Worker: O4 (f) for one row and period: the row's gated signals with momentum sides, one run."""
    ri, p = task
    ctx = _S["ctx"]
    a, b = _S["periods"][p]
    parts = _S["parts"][(ri, p)]
    live, syms = _S["live"], _S["syms"]
    fparts, n, same, zero, undef = [], 0, 0, 0, 0
    for sig, src in parts:
        side, ok = momentum_sides(live, syms, sig)
        own = np.asarray(sig["side"], np.int64)
        n += len(side)
        same += int((side == own).sum())
        undef += int((~ok).sum())
        zero += int((ok & (side == 0)).sum())
        fparts.append((subset(sig, side != 0, side), src))
    res = ctx["run"](fparts, a, b, r=H.R_BASE)
    return ri, p, {"lnM": list(res["metrics"]["lnM"]), "mean_lnM": res["metrics"]["mean_lnM"],
                   "n_positions": int(res["metrics"]["n_positions"]), "signals": n, "same_side": same,
                   "no_side_zero_move": zero, "no_side_undefined": undef}


# ------------------------------------------------------------------ the select-only weekend map (O1)
_CACHES = ("_COINS", "_FUND", "_SERIES", "_EVENTS", "_SIGS", "_BANKS", "_POOLS", "_LARGE", "_BRK", "_MARKETS",
           "_FILLS")


def _snapshot(live) -> dict:
    snap = {n: dict(getattr(live, n)) for n in _CACHES}
    snap["_G.mk"] = dict(live._G["mk"])
    return snap


def _restore(live, snap: dict) -> None:
    for n in _CACHES:
        d = getattr(live, n)
        d.clear()
        d.update(snap[n])
    live._G["mk"].clear()
    live._G["mk"].update(snap["_G.mk"])


def truncated_data(live, syms: list, end_ms: int) -> tuple:
    """Every coin's loaded 5m bars and funding with open (calc time) before ``end_ms``, as the select step loads them
    (load_coin / load_funding cut the arrays at the end before anything else uses them): views of the loaded arrays,
    the coin end kept only when it lies before end - 5 min (load_coin's rule), funding months before the end."""
    end = int(end_ms)
    coins, fund = {}, {}
    end_month = H.month_key(end)
    for s in syms:
        c = live._COINS[s]
        n = int(np.searchsorted(c.ts, end, "left"))
        last = c.last_ms if (c.last_ms is not None and c.last_ms < end - FIVE) else 2 ** 62
        counts = dict(c.counts)
        if "missing_months_funding" in counts:
            counts["missing_months_funding"] = [m for m in counts["missing_months_funding"] if m < end_month]
        coins[s] = live.Coin(s, c.ts[:n], c.o[:n], c.h[:n], c.l[:n], c.c[:n], c.v[:n], c.qv[:n], last_ms=last,
                             counts=counts)
        fts, rate = live._FUND.get(s, (np.zeros(0, np.int64), np.zeros(0)))
        keep = np.asarray(fts, np.int64) < end
        fund[s] = (np.asarray(fts, np.int64)[keep], np.asarray(rate, np.float64)[keep])
    return coins, fund


def map_systems(live) -> list:
    """The candidate systems of the W 5 walk (F1-F3 and F5; F4 never)."""
    return [s for s in live.wide_systems() if s["family"] in live.PICK_FAMILIES]


def _map_task(task) -> list:
    """Worker: one entry cell (both gates) on the truncated select market with the weekend rule, base cost and cost
    x2 (W 5's runs)."""
    mkey, specs = task
    live = _S["live"]
    mk = live._G["mk"][mkey]
    live._EVENTS.clear()                       # one entry cell per task (as the select step)
    live._SIGS.clear()
    rows = []
    for spec in specs:
        sig = live.system_signals(mk, spec)
        close = close_ms_of(live, mk.syms, sig)
        wk = is_weekend_close(close)
        f = subset(sig, ~wk)
        base = live.run_signals(mk, [(f, 0)], H.R_BASE, "base")
        c2 = live.run_signals(mk, [(f, 0)], H.R_BASE, "x2")
        ok, why = live.wide_eligible(base, c2)
        rows.append({**{k: spec.get(k) for k in ("id", "family", "name", "strategy", "kind", "tf", "gate", "rank")},
                     "eligible": bool(ok), "fail": list(why), "score": float(base["mean_lnM"]),
                     "median_M": float(base["median_M"]), "cost2_mean_lnM": float(c2["mean_lnM"]),
                     "n_positions": int(base["n_positions"]), "bust": bool(base["bust"]),
                     "win_share": base.get("win_share"), "max_dd": float(base["max_dd"]),
                     "gated": int(len(sig["k"])), "weekend_skipped": int(wk.sum()),
                     "weekend_skipped_long": int((wk & (np.asarray(sig["side"]) > 0)).sum())})
    return rows


def select_weekend_map(ctx: dict, live, official: list) -> tuple:
    """O1's select-only map: (public, private). The data are cut at the select end in this process (and the forked
    workers) for the map only and restored afterwards; nothing of the map is run on the test period."""
    a, b = (int(x) for x in ctx["periods"]["select"])
    syms = list(ctx["syms"])
    systems = map_systems(live)
    t0 = time.time()
    _S["live"] = live
    snap = _snapshot(live)
    try:
        coins, fund = truncated_data(live, syms, b)
        live.install(coins, fund)
        mk = live.Market(syms, (a, b), name="select-weekend-map")
        live._G["mk"][mk.key] = mk
        live.prepare_series(syms, sorted({s["tf"] for s in systems}, key=H.TF_ORDER.index))
        groups = live._group_cells(systems)
        res = ctx["pmap"](_map_task, [(mk.key, g) for g in groups], int(ctx.get("procs") or 1),
                          "reads_o select weekend map")
        data_end = max((int(c.ts[-1]) for c in coins.values() if len(c.ts)), default=None)
    finally:
        _restore(live, snap)
    rows = [r for g in res for r in g]
    ch = live.wide_choose(rows)
    pos = {i: n + 1 for n, i in enumerate(ch["picks"])}
    bno = {i: bi + 1 for bi, ids in enumerate(ch["batches"]) for i in ids}
    for r in rows:
        r["map_pick"] = r["id"] in pos
        r["map_pick_no"] = pos.get(r["id"])
        r["map_batch"] = bno.get(r["id"])
    off = set(official)
    head = {"what": "O1 select-only map (W 7.4a): the W 5 walk rerun with the weekend-skip machine on the select "
                    "period; chooses nothing; never run on the test period here; a later round confirms any such "
                    "pick once (section 14, program ledger)",
            "period": [H.ms_str(a), H.ms_str(b)], "data_cut_at": H.ms_str(b),
            "last_5m_bar_used": None if data_end is None else H.ms_str(data_end),
            "machine": VARIANT_LABEL["O1"], "n_systems": len(rows),
            "n_eligible": sum(1 for r in rows if r["eligible"]),
            "n_names_eligible": len({r["strategy"] for r in rows if r["eligible"]}),
            "label": ch["label"], "picks": list(ch["picks"]),
            "batches": [[pos[i] for i in ids] for ids in ch["batches"]],
            "official_members": list(official), "in_both": [i for i in ch["picks"] if i in off],
            "map_only": [i for i in ch["picks"] if i not in off],
            "official_only": [i for i in official if i not in pos],
            "weekend_skipped_total": int(sum(r["weekend_skipped"] for r in rows)),
            "run_on_test": False, "seconds": round(time.time() - t0, 1)}
    pub_rows, priv_rows = {}, {}
    for r in rows:
        priv_rows[r["id"]] = r                                 # private: every row with its figures
        if r.get("kind") == "ds":
            red = redact(r)
            red["note"] = DS_NOTE
            pub_rows[r["id"]] = red
        else:
            pub_rows[r["id"]] = r
    return {**head, "rows": pub_rows}, {**head, "rows": priv_rows}


# ------------------------------------------------------------------ assembly helpers
def _summary(o: dict, ctl_lnm: dict, base_taken, skipped: dict, ctl_bits: dict | None, cell, period: str) -> dict:
    m = o["metrics"]
    lnm = np.asarray(o["lnM"], float)
    s = {k: (_f(v) if isinstance(v, (float, np.floating)) else v) for k, v in m.items()}
    s["cost2_mean_lnM"] = _f(o["cost2"]["mean_lnM"])
    s["cost2_median_M"] = _f(o["cost2"]["median_M"])
    s["signals"] = skipped
    if base_taken is not None:
        s["base_positions_removed"] = base_taken
    ctl = {}
    for cn, mat in ctl_lnm.items():
        mat = np.asarray(mat, float)
        if mat.size == 0 or mat.shape[1] != len(lnm):
            continue
        d = lnm - mat.mean(axis=0)
        ctl[cn] = {"n_seeds": int(mat.shape[0]), "control_mean_lnM": _f(mat.mean()), "mean_d": _f(d.mean()),
                   "share_seeds_with_mean_lnM_ge_row": _f((mat.mean(axis=1) >= lnm.mean()).mean())}
    s["controls"] = ctl
    if cell is not None and "bits" in o:
        h = headline_shares(o["bits"], ctl_bits)
        h["cell"] = RA.cell_key(*cell)
        h["size_label"] = "size fixed before the test" if period == "test" else "size fixed here (select)"
        s["headline_at_size_fixed_on_select"] = h
    else:
        s["headline_at_size_fixed_on_select"] = {"cell": None, "note": "no size fixed on select (no cell with bust "
                                                                      "share <= 5%)"}
    return s


def _minus_base(v: dict, base: dict) -> dict:
    out = {}
    for k in ("mean_lnM", "median_lnM", "win_share", "max_dd", "cost2_mean_lnM"):
        a_, b_ = v.get(k), base.get(k)
        out[k] = None if a_ is None or b_ is None else _f(a_ - b_)
    out["n_positions"] = (None if v.get("n_positions") is None or base.get("n_positions") is None
                          else int(v["n_positions"]) - int(base["n_positions"]))
    for cn in ("a", "b"):
        x, y = (v.get("controls") or {}).get(cn), (base.get("controls") or {}).get(cn)
        out[f"mean_d_{cn}"] = None if not x or not y or x["mean_d"] is None or y["mean_d"] is None else \
            _f(x["mean_d"] - y["mean_d"])
    return out


def _official_members(ctx: dict) -> list:
    ids = [p["id"] for p in ctx["picks"]]
    for u in ctx.get("untested") or []:
        ids.append(u["id"] if isinstance(u, dict) else str(u))
    return ids


def _check_pin_status(ctx: dict) -> None:
    rp = ctx.get("reads_pin")
    if not isinstance(rp, dict) or rp.get("module") != MODULE_REL or rp.get("listed_in_pin") is not True:
        raise RuntimeError(f"reads_o runs only through the reads hook with its own pinned line ({MODULE_REL} listed "
                           f"in the pin with its current sha256); ctx reads_pin = {rp!r}")


# ------------------------------------------------------------------ the entry point
def run(ctx: dict) -> None:
    """Fill ctx['out'] (public) and ctx['private'] (D11 and money of DeepSeek rows). Writes no file."""
    t_all = time.time()
    _check_pin_status(ctx)
    live = RA._live(ctx)
    log = ctx.get("log") or (lambda m: print(m, flush=True))
    study = ctx["study"]
    rows = ctx["rows"]
    syms = list(ctx["syms"])
    pmap, procs = ctx["pmap"], int(ctx.get("procs") or 1)
    periods = {p: (int(ctx["periods"][p][0]), int(ctx["periods"][p][1])) for p in O_PERIODS}
    cal = calendar_status(study, periods)
    variants = ["base", "O1", "O1b"] + (["O2", "O2_fomc"] if cal["run"] else [])
    events = cal.get("events")
    mks = {p: ctx["market"](*periods[p]) for p in O_PERIODS}
    _S.clear()
    _S.update(ctx=ctx, live=live, syms=syms, periods=periods, mks=mks, variants=variants, events=events,
              wins={p: RA.calendar_windows(*periods[p]) for p in O_PERIODS})
    ds_of = {_row_id(r): bool(r.get("is_ds") or any(ctx["is_ds"](m) for m in r["members"])) for r in rows}
    parts, metas, vparts, vmetas, vmasks = {}, {}, {}, {}, {}
    for ri, row in enumerate(rows):
        for p in O_PERIODS:
            parts[(ri, p)] = [(ctx["signals"](m, mks[p]), src) for m, src in zip(row["members"], row["src"])]
            metas[(ri, p)] = [_meta(live, syms, sig) for sig, _ in parts[(ri, p)]]
            for v in variants:
                vp, vm, msk = _variant_parts(parts[(ri, p)], metas[(ri, p)], v, events)
                vparts[(ri, p, v)], vmetas[(ri, p, v)], vmasks[(ri, p, v)] = vp, vm, msk
    _S.update(parts=parts, metas=metas, vparts=vparts, vmetas=vmetas)
    log(f"reads_o: {len(rows)} rows; variants {variants}; O2: {cal['reason']}")

    # ---------------------------------------------------------------- size fixed on select (reads_a's rule)
    fixed, fixed_cells = {}, {}
    for ri, cells in pmap(_sizefix_task, list(range(len(rows))), procs, "reads_o size fixed on select"):
        inputs = [{"machine": c[0], "r": float(c[1]), "mean_ln_multiple": v["mean_ln_multiple"],
                   "bust_share": v["bust_share"]} for c, v in cells.items() if v["n_windows"]]
        ch = ctx["size_fixed_on_select"](inputs) if inputs else None
        fixed[ri] = None if ch is None else (ch["machine"], float(ch["r"]))
        fixed_cells[ri] = {RA.cell_key(*c): v for c, v in cells.items()}
    _S["fixed"] = fixed

    # ---------------------------------------------------------------- the rows through every variant
    ptasks = [(ri, p, v) for ri in range(len(rows)) for p in O_PERIODS for v in variants]
    pres = {(ri, p, v): o for ri, p, v, o in pmap(_pick_task, ptasks, procs, "reads_o rows")}
    ctasks = [(ri, p, c, tuple(ch)) for ri in range(len(rows)) for p in O_PERIODS for c in ("a", "b")
              for ch in RA._chunks(range(1, CTL_SEEDS + 1), CTL_TASK_SEEDS)]
    clnm, cbits = {}, {}
    for ri, p, c, seeds, lnm, bits in pmap(_ctl_task, ctasks, procs, "reads_o controls"):
        for v in variants:
            clnm.setdefault((ri, p, c, v), []).append((seeds, lnm[v]))
            cbits.setdefault((ri, p, c, v), []).append((seeds, bits[v]))
    log(f"reads_o: rows and controls done ({time.time() - t_all:.0f}s)")

    # ---------------------------------------------------------------- O4 (f) and R6 (e)
    fres = {(ri, p): o for ri, p, o in pmap(_f_task, [(ri, p) for ri in range(len(rows)) for p in O_PERIODS],
                                             procs, "reads_o momentum (f)")}
    etasks = [(ri, p, tuple(ch)) for ri in range(len(rows)) for p in O_PERIODS
              for ch in RA._chunks(range(1, E_SEEDS[p] + 1), E_TASK_SEEDS)]
    eres = {}
    for ri, p, seeds, lnm, cnt in pmap(_e_task, etasks, procs, "reads_o R6 (e)"):
        eres.setdefault((ri, p), []).append((seeds, lnm, cnt))

    # ---------------------------------------------------------------- assemble per row
    def stack(chunks):
        chunks = sorted(chunks, key=lambda x: x[0][0])
        return np.concatenate([x[1] for x in chunks], axis=0) if chunks else np.zeros((0, 0))

    tag = H.SEED_TAG["wide" if study == "wide" else "v1"]
    out_rows = {}
    for ri, row in enumerate(rows):
        rid = _row_id(row)
        per = {}
        for p in O_PERIODS:
            base_o = pres[(ri, p, "base")]
            coin_b, fill_b = base_o["taken"]
            taken = set(zip(coin_b.tolist(), fill_b.tolist()))
            pv = {}
            for v in variants:
                o = pres[(ri, p, v)]
                ms = vmasks[(ri, p, v)]
                allm = metas[(ri, p)]
                sk = np.concatenate(ms) if ms else np.zeros(0, bool)
                side = np.concatenate([m["side"] for m in allm]) if allm else np.zeros(0, np.int64)
                kk = np.concatenate([m["k"] for m in allm]) if allm else np.zeros(0, np.int64)
                fl = np.concatenate([m["fill"] for m in allm]) if allm else np.zeros(0, np.int64)
                removed = sum(1 for x in zip(kk[sk].tolist(), fl[sk].tolist()) if x in taken)
                counts = {"gated": int(len(sk)), "skipped": int(sk.sum()), "kept": int((~sk).sum()),
                          "skipped_long": int((sk & (side > 0)).sum()), "skipped_short": int((sk & (side < 0)).sum())}
                ctl_l = {c: stack(clnm.get((ri, p, c, v), [])) for c in ("a", "b")}
                ctl_b = {c: stack(cbits.get((ri, p, c, v), [])) for c in ("a", "b")} if fixed[ri] else None
                pv[v] = _summary(o, ctl_l, removed if v != "base" else 0, counts, ctl_b, fixed[ri], p)
                pv[v]["what"] = VARIANT_LABEL[v]
            for v in variants:
                if v != "base":
                    pv[v]["minus_base"] = _minus_base(pv[v], pv["base"])
            if not cal["run"]:
                pv["O2"] = pv["O2_fomc"] = {"what": VARIANT_LABEL["O2"], "not_run": cal["reason"]}
            # O4 (f) and R6 (e)
            lnm_row = np.asarray(pres[(ri, p, "base")]["lnM"], float)
            fo = fres[(ri, p)]
            flnm = np.asarray(fo["lnM"], float)
            ch = sorted(eres.get((ri, p), []), key=lambda x: x[0][0])
            emat = np.concatenate([x[1] for x in ch], axis=0) if ch else np.zeros((0, len(lnm_row)))
            ecnt = {k: int(sum(x[2][k] for x in ch)) for k in ("drawn", "no_side_zero_move", "no_side_undefined")}
            o4 = {"f": {"what": "the row's gated signals with side = sign(close - close 20 bars before), one run of "
                                "the tested machine",
                        "mean_lnM": _f(fo["mean_lnM"]), "mean_d": _f((lnm_row - flnm).mean()) if len(flnm) else None,
                        "n_positions": fo["n_positions"], "signals": fo["signals"], "same_side": fo["same_side"],
                        "share_same_side": _f(fo["same_side"] / fo["signals"]) if fo["signals"] else None,
                        "no_side_zero_move": fo["no_side_zero_move"], "no_side_undefined": fo["no_side_undefined"]}}
            if emat.size:
                d = lnm_row - emat.mean(axis=0)
                if len(row["members"]) == 1:
                    bparts = ctx["seeds"]["seed_parts"](_study_of(row["members"][0]), row["members"][0], "e", p,
                                                        H.R_BASE, "boot")
                else:
                    bparts = (tag, rid, "e", p, float(H.R_BASE), "boot")
                o4["e"] = {"what": "R6 (e) momentum-side random times (control (a)'s draws, control name 'e')",
                           "n_seeds": int(emat.shape[0]), "control_mean_lnM": _f(emat.mean()),
                           "mean_d": _f(d.mean()), "p_boot": _f(ctx["helpers"]["boot_p"](
                               d, ctx["helpers"]["seed_int"](*bparts))),
                           "seed_rank_p": seed_rank_p(float(lnm_row.mean()), emat.mean(axis=1)), **ecnt}
            pv["O4"] = o4
            per[p] = pv
        labels = []
        if row["kind"] in ("pick", "v1"):
            t4 = per["test"]["O4"]
            de, df_ = (t4.get("e") or {}).get("mean_d"), t4["f"]["mean_d"]
            mo = None if de is None and df_ is None else bool((de is not None and de <= 0)
                                                             or (df_ is not None and df_ <= 0))
            if mo:
                labels.append(MOMENTUM_ONLY_LABEL)
        else:
            mo = None
        o5m = [m["id"] for m in row["members"] if O5_NAME in (m.get("name"), m.get("strategy"))]
        if o5m:
            labels.append(O5_LABEL if row["kind"] in ("pick", "v1") else f"contains {', '.join(o5m)}: {O5_LABEL}")
        out_rows[rid] = {**_row_meta(row), "size_fixed_on_select": None if fixed[ri] is None else
                         RA.cell_key(*fixed[ri]), "size_fix_inputs_select": fixed_cells[ri], "periods": per,
                         "momentum_only": mo, "labels": labels}

    # ---------------------------------------------------------------- by timeframe (counts; public: no DeepSeek row)
    by_tf = {"public_rows": {}, "all_rows": {}}
    for which in ("public_rows", "all_rows"):
        for v in variants[1:]:
            for p in O_PERIODS:
                for tf in H.TF_ORDER:
                    sel = [(rid, r) for rid, r in out_rows.items() if r["kind"] in ("pick", "v1") and r["tfs"] == [tf]
                           and (which == "all_rows" or not ds_of[rid])]
                    if not sel:
                        continue
                    diffs = [r["periods"][p][v]["minus_base"]["mean_lnM"] for _, r in sel]
                    by_tf[which].setdefault(v, {}).setdefault(p, {})[tf] = {
                        "rows": len(sel), "higher_mean_lnM": sum(1 for x in diffs if x is not None and x > 0),
                        "lower_mean_lnM": sum(1 for x in diffs if x is not None and x < 0),
                        "equal_mean_lnM": sum(1 for x in diffs if x is not None and x == 0)}

    # ---------------------------------------------------------------- O5 and the select-only map
    o5 = {"label": O5_LABEL, "name": O5_NAME,
          "rows": [rid for rid, r in out_rows.items() if O5_LABEL in r["labels"]], "flipped_system_added": False}
    try:
        o5["select_table_systems"] = [s["id"] for s in live.wide_systems() if s.get("name") == O5_NAME]
    except Exception as e:                                      # the system list needs the pinned full-grid files
        o5["select_table_systems"] = None
        o5["note"] = f"system list unavailable: {type(e).__name__}"
    if study == "wide":
        map_pub, map_priv = select_weekend_map(ctx, live, _official_members(ctx))
    else:
        map_pub = map_priv = {"not_run": "the select-only map is the wide study's W 5 walk"}

    # ---------------------------------------------------------------- D11 split and output
    pub_rows, priv_rows = split_ds(plain(out_rows), ds_of)
    cal_pub = {k: v for k, v in cal.items() if k != "events"}
    out, priv = ctx["out"], ctx["private"]
    out.update(plain({
        "what": "Phase-B autopsy reads O1-O5 (W 7.4a): reported, never a pass; computed after the verdict on the "
                "fixed rows; each of O1-O4 counts as one confirm look in the program-wide ledger",
        "api": 1, "module": MODULE_REL, "reads_pin": ctx.get("reads_pin"),
        "reads_line_before_test_json": (ctx.get("reads_pin") or {}).get("listed_before_test_json"),
        "reads_a_sha256": H.sha256_file(RA.__file__), "choices": CHOICES,
        "constants": {"control_seeds": CTL_SEEDS, "e_seeds": dict(E_SEEDS), "momentum_bars": MOM_BARS,
                      "blackout_minutes": BLACKOUT_MIN, "r": H.R_BASE, "start_wallet": H.START_WALLET,
                      "headline_start": RA.GOAL_START, "variants": variants},
        "variants": {v: VARIANT_LABEL[v] for v in VARIANTS}, "calendar": cal_pub,
        "rows": pub_rows, "by_timeframe": by_tf["public_rows"],
        "O1_select_map": map_pub,
        "O3": {"status": "not computed in this round: the pinned engine cannot block entries or adds by the open "
                         "risk of same-side positions and exports no per-5m stop path", "needs": O3_NEEDS},
        "O4_label_rule": "a pick whose test mean d_m against R6 (e) or against (f) is <= 0: " + MOMENTUM_ONLY_LABEL,
        "O5": o5, "seconds": round(time.time() - t_all, 1)}))
    priv.update(plain({"what": "reads_o private part (D11): DeepSeek rows and map rows, all figures",
                       "rows": priv_rows, "by_timeframe_all_rows": by_tf["all_rows"], "O1_select_map": map_priv}))
    log(f"reads_o: done in {time.time() - t_all:.0f}s")


# ------------------------------------------------------------------ standalone runner (hunt.py lists reads_a only)
def pin_refusal(study: str) -> str | None:
    """None when research/hunt/reads_o.py is listed in the study's pin with its current sha256; else why not."""
    rp = H.reads_pin_status(study, MODULE_NAME, None)
    if not rp["sha256"]:
        return f"{MODULE_REL} does not exist"
    if not rp["listed_in_pin"]:
        return (f"{MODULE_REL} is not in {H.PIN[study]} with its current sha256 {rp['sha256']}: refused (append its "
                f"line to the pin first; read guard 3)")
    return None


def main(argv=None) -> int:
    """``python -m research.hunt.reads_o --study wide --data DIR``: hunt.py's ``reads`` command for this module only
    (cmd_reads with names=('reads_o',)): test.json must exist, the pin must match (check_pin 'test'), the data
    identity is checked, the context is built by hunt.reads_context inside hunt.run_reads_hooks, and the hook writes
    out/<study>/reads_o.json and the private file after the read guard and the D11 check."""
    ap = argparse.ArgumentParser(prog="python -m research.hunt.reads_o")
    ap.add_argument("--study", choices=("wide", "v1"), default="wide")
    ap.add_argument("--data", default=None)
    ap.add_argument("--procs", type=int, default=1)
    ap.add_argument("--private", default=None)
    ap.add_argument("--judge-usd-per-call", dest="judge_usd_per_call", type=float, default=None)
    args = ap.parse_args(argv)
    why = pin_refusal(args.study)
    if why:
        print(f"[reads_o] {why}", file=sys.stderr, flush=True)
        return 2
    study = args.study
    try:
        test_doc = H._load_test_doc(study)
        H.check_pin(study, "test")
        full = None
        if study == "wide":
            pp = os.path.join(H.private_dir(args), "wide_test_private.json")
            if os.path.exists(pp):
                with open(pp) as fh:
                    full = json.load(fh)
        H._compile_probe()
        if study == "wide":
            H._ew().fullgrid_pins()
        data, syms, counts = H._universe_and_data(args, "test")
        mks = H._test_markets(syms)
        st = H.run_reads_hooks(args, study, test_doc.get("pin"), mks, syms, test_doc, full, names=(MODULE_NAME,))
    except (H.PinError, H.ReadGuardError) as e:
        print(f"[reads_o] refused: {e}", file=sys.stderr, flush=True)
        return 2
    print(json.dumps(st))
    return 0 if st.get(MODULE_NAME) in ("written", "exists") else 2


if __name__ == "__main__":
    sys.exit(main())
