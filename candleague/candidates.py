"""후보 리그 candidates: made from the full-grid study's results pack, checked, and read by the league.

    python -m candleague.candidates make --results DIR [--out candleague/data/candidates.json] [--all-picks]
    python -m candleague.candidates watch --results DIR --select FILE [--bands FILE] [--out ...]
    python -m candleague.candidates check [--file candleague/data/candidates.json]

A candidate is {id, kind, name, tf, combo, exit, source}: one paper account with the study's numbers (combo: every
parameter of the strategy) and exit rule (a name of candleague.exits.EXITS). ``make`` takes the picks that passed the
study's confirm stage (confirm.json; with --all-picks every pick, marked passed=false); ``check`` refuses a file whose
strategy, timeframe, parameters or exit the league could not run exactly as the study did. DeepSeek rows keep no money
figure (D11). The league adds, per cell, the default numbers with the live exit (``base``) and, per candidate, a coin
flip at the candidate's own signal times (accounts()).

``watch`` (owners 2026-10-11, research/fullgrid/WATCH_PREREG.md): no pick passed, so the league runs the watch list
instead (research/fullgrid/diag/watch_sel.json, one near-miss pick per cell of the 16 watch strategies), each marked
passed=false, watch=true, with two more comparison accounts: the same pick at 1/4 size (``quarter``) and the cell's
default numbers with the pick's exit (``exitonly``).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from typing import Optional

from . import exits as X

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_FILE = os.path.join(ROOT, "candleague", "data", "candidates.json")
DS_DEFS = os.path.join(ROOT, "research", "fullgrid", "ds_defs.py")
TFS = ("15m", "30m", "1h", "4h")
QUARTER = 0.25
VARIANTS = ("quarter", "exitonly")
ID_RE = re.compile(r"^[A-Za-z0-9_.-]{3,60}$")
_DS = []


def ds_defs():
    """research/fullgrid/ds_defs.py (the study's parameterized DeepSeek definitions)."""
    if not _DS:
        spec = importlib.util.spec_from_file_location("candleague_ds_defs", DS_DEFS)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _DS.append(mod)
    return _DS[0]


def params_of(kind: str, name: str) -> list[dict]:
    if kind == "core":
        from paperbot.paramshadow import param_module
        return list(param_module(name).PARAMS)
    if kind == "ds":
        return list(ds_defs().DEFS[name])
    raise ValueError(f"kind {kind!r}")


def default_combo(kind: str, name: str) -> dict:
    return {p["name"]: p["default"] for p in params_of(kind, name)}


def _plain(v):
    return list(v) if isinstance(v, tuple) else v


def from_results(confirm: dict, all_picks: bool = False, phase2: Optional[dict] = None) -> list[dict]:
    """The league's candidates from confirm.json rows (passed ones unless ``all_picks``); with ``phase2``
    (research/fullgrid/checks.py's phase2.json) each core candidate carries its forward band (PHASE2_PREREG 8;
    DeepSeek money stays out of the file, D11)."""
    bands = {c["id"]: c.get("band") for c in (phase2 or {}).get("candidates", [])}
    out = []
    for r in confirm["rows"]:
        if not (r.get("pass") or all_picks):
            continue
        src = {"rank": r.get("rank"), "row": r.get("row"), "passed": bool(r.get("pass")),
               "test_n": (r.get("test") or {}).get("n"), "select_n": r.get("select_n")}
        if r["kind"] == "core":
            src["test_mean"] = (r.get("test") or {}).get("mean")
            band = bands.get(f"{r['kind']}-{r['name']}-{r['tf']}-{r.get('rank')}")
            if band:
                src["band"] = band
        out.append({"id": f"{r['kind']}-{r['name']}-{r['tf']}-{r.get('rank')}", "kind": r["kind"], "name": r["name"],
                    "tf": r["tf"], "combo": {k: _plain(v) for k, v in r["combo"].items()}, "exit": r["exit"],
                    "source": src})
    return out


def from_watch(confirm: dict, select: list[dict], bands: Optional[dict] = None) -> list[dict]:
    """The watch list as candidates: each selected pick (kind, name, tf, rank) from confirm.json, passed=false,
    watch=true, with the quarter and exitonly variants; core picks carry their forward band when ``bands`` has one
    (DeepSeek never, D11)."""
    rows = {(r["kind"], r["name"], r["tf"], int(r.get("rank") or 0)): r for r in confirm["rows"]}
    out = []
    for s in select:
        key = (s["kind"], s["name"], s["tf"], int(s["rank"]))
        r = rows.get(key)
        if r is None:
            raise SystemExit(f"watch pick {key} not in confirm.json")
        cid = f"{r['kind']}-{r['name']}-{r['tf']}-{r.get('rank')}"
        src = {"rank": r.get("rank"), "row": r.get("row"), "passed": bool(r.get("pass")), "watch": True,
               "test_n": (r.get("test") or {}).get("n"), "select_n": r.get("select_n")}
        if r["kind"] == "core":
            src["test_mean"] = (r.get("test") or {}).get("mean")
            if bands and bands.get(cid):
                src["band"] = bands[cid]
        out.append({"id": cid, "kind": r["kind"], "name": r["name"], "tf": r["tf"],
                    "combo": {k: _plain(v) for k, v in r["combo"].items()}, "exit": r["exit"], "source": src,
                    "variants": list(VARIANTS)})
    return out


def check(cands: list[dict]) -> list[str]:
    """Problems that would make the league run a candidate differently from the study (empty = fine)."""
    bad, seen = [], set()
    for c in cands:
        cid = c.get("id", "?")
        if not ID_RE.match(str(cid)) or cid in seen:
            bad.append(f"{cid}: bad or repeated id")
        seen.add(cid)
        if c.get("kind") not in ("core", "ds"):
            bad.append(f"{cid}: kind {c.get('kind')!r}")
            continue
        try:
            ps = params_of(c["kind"], c["name"])
        except Exception as exc:  # noqa: BLE001
            bad.append(f"{cid}: strategy {c.get('name')!r} not runnable ({type(exc).__name__}: {exc})")
            continue
        tfs = TFS if c["kind"] == "core" else tuple(ds_defs().TFS_OF[c["name"]])
        if c.get("tf") not in tfs:
            bad.append(f"{cid}: timeframe {c.get('tf')!r} not in {tfs}")
        if c.get("exit") not in X.BY_NAME:
            bad.append(f"{cid}: exit {c.get('exit')!r} unknown")
        if not set(c.get("variants", [])) <= set(VARIANTS):
            bad.append(f"{cid}: variants {c.get('variants')!r} not in {VARIANTS}")
        names = [p["name"] for p in ps]
        if sorted(c.get("combo", {})) != sorted(names):
            bad.append(f"{cid}: parameters {sorted(c.get('combo', {}))} != {sorted(names)}")
            continue
        for p in ps:
            v, d = c["combo"][p["name"]], p["default"]
            if isinstance(d, (list, tuple)) != isinstance(v, (list, tuple)) or not (
                    isinstance(v, (int, float, list, tuple)) and not isinstance(v, bool)):
                bad.append(f"{cid}: {p['name']}={v!r} has another type than the default {d!r}")
    return bad


def accounts(cands: list[dict]) -> list[dict]:
    """Every league account: each candidate (role cand), its coin flip (role flip, same signals, seeded sides), one
    base per cell (the default numbers, the live exit) and, for a watch candidate, its ``quarter`` (same pick, 1/4
    size, id ``<id>-q``) and ``exitonly`` (the default numbers with the pick's exit, id ``<id>-x``)."""
    out, bases = [], {}
    for c in cands:
        out.append({**c, "role": "cand"})
        out.append({**c, "id": f"{c['id']}-flip", "role": "flip", "of": c["id"]})
        if "quarter" in c.get("variants", []):
            out.append({**c, "id": f"{c['id']}-q", "role": "quarter", "of": c["id"], "size": QUARTER})
        if "exitonly" in c.get("variants", []):
            out.append({**c, "id": f"{c['id']}-x", "role": "exitonly", "of": c["id"],
                        "combo": {k: _plain(v) for k, v in default_combo(c["kind"], c["name"]).items()},
                        "source": {"default": True, "exit_of": c["id"]}})
        key = (c["kind"], c["name"], c["tf"])
        if key not in bases:
            bases[key] = {"id": f"base-{c['kind']}-{c['name']}-{c['tf']}", "kind": c["kind"], "name": c["name"],
                          "tf": c["tf"], "combo": {k: _plain(v) for k, v in default_combo(*key[:2]).items()},
                          "exit": X.LIVE_EXIT, "source": {"default": True}, "role": "base"}
    return out + list(bases.values())


def load(path: str = DEFAULT_FILE) -> list[dict]:
    with open(path) as fh:
        cands = json.load(fh)["candidates"]
    bad = check(cands)
    if bad:
        raise SystemExit("candidates refused:\n  " + "\n  ".join(bad))
    return cands


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make")
    m.add_argument("--results", required=True)
    m.add_argument("--out", default=DEFAULT_FILE)
    m.add_argument("--all-picks", action="store_true")
    m.add_argument("--phase2", help="research/fullgrid/checks.py phase2.json (forward bands)")
    w = sub.add_parser("watch")
    w.add_argument("--results", required=True)
    w.add_argument("--select", required=True, help="research/fullgrid/diag/watch_sel.json")
    w.add_argument("--bands", help="{candidate id: band} for core picks")
    w.add_argument("--out", default=DEFAULT_FILE)
    c = sub.add_parser("check")
    c.add_argument("--file", default=DEFAULT_FILE)
    a = ap.parse_args(argv)
    if a.cmd == "watch":
        with open(os.path.join(a.results, "confirm.json")) as fh:
            confirm = json.load(fh)
        with open(a.select) as fh:
            select = json.load(fh)
        bands = None
        if a.bands:
            with open(a.bands) as fh:
                bands = json.load(fh)
        cands = from_watch(confirm, select, bands)
        bad = check(cands)
        if bad:
            print("refused:\n  " + "\n  ".join(bad), file=sys.stderr)
            return 2
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        with open(a.out, "w") as fh:
            json.dump({"candidates": cands}, fh, ensure_ascii=False, indent=1)
        print(f"{len(cands)} watch candidates, {len(accounts(cands))} accounts -> {a.out}")
        return 0
    if a.cmd == "make":
        with open(os.path.join(a.results, "confirm.json")) as fh:
            confirm = json.load(fh)
        phase2 = None
        if a.phase2:
            with open(a.phase2) as fh:
                phase2 = json.load(fh)
        cands = from_results(confirm, a.all_picks, phase2)
        bad = check(cands)
        if bad:
            print("refused:\n  " + "\n  ".join(bad), file=sys.stderr)
            return 2
        os.makedirs(os.path.dirname(a.out), exist_ok=True)
        with open(a.out, "w") as fh:
            json.dump({"candidates": cands}, fh, ensure_ascii=False, indent=1)
        print(f"{len(cands)} candidates, {len(accounts(cands))} accounts -> {a.out}")
        return 0
    cands = load(a.file)
    print(f"ok: {len(cands)} candidates, {len(accounts(cands))} accounts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
