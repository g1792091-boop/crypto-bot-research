"""Hunt round 2 command line (PREREG_HUNT_R2.md section 11).

    python -m research.hunt_r2.hunt_r2 counts       (writes research/hunt_r2/counts.json; no data)
    python -m research.hunt_r2.hunt_r2 bench        (writes research/hunt_r2/bench_r2.json; synthetic bars only)
    python -m research.hunt_r2.hunt_r2 pinlist      (the code pin's lines, each file by its own sha256; problems on
                                                     stderr, exit 2 when an input differs from round 1's pin)
    python -m research.hunt_r2.hunt_r2 selfcheck    (round 2's tests and round 1's self-check list, pytest)
    python -m research.hunt_r2.hunt_r2 select  --data DIR [--private DIR] [--procs N]
    python -m research.hunt_r2.hunt_r2 pretest --data DIR [--private DIR] [--procs N]
    python -m research.hunt_r2.hunt_r2 test    --data DIR [--private DIR] [--procs N] [--no-reads]
                                               [--ledger-private DIR] [--ledger-public DIR] [--fullgrid-confirm FILE]
                                               [--ledger-extra FILE]
    python -m research.hunt_r2.hunt_r2 reads   --data DIR [--private DIR] [--procs N]
    python -m research.hunt_r2.hunt_r2 report  [--private DIR]
    python -m research.hunt_r2.hunt_r2 ledger  [--private DIR] [--ledger-private DIR] [--out FILE]

Guards (as the hunt): every step checks round 2's pin first (design hash first line, every listed file unchanged,
every file of the pin list listed, the read-only inputs equal round 1's pinned hashes). ``select`` reads no 5m bar at
or after 2024-01-01 (hunt.load_coin cuts every column at the select end before anything uses it), writes picks.json
and appends its sha256 to the pin before any test bar is read. ``pretest`` needs the picks line and reads select bars
only. ``test`` refuses without the picks line, refuses when test.json exists or is pinned (one look), reads test data
only after those checks, writes test.json (public) and the private file, and appends test.json's sha256. ``reads``
needs the test.json line. Long parts resume under the pin's hash.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from research.hunt import hunt as H  # noqa: E402
from research.hunt_r2 import bench_r2 as BR  # noqa: E402
from research.hunt_r2 import confirm_r2 as CF  # noqa: E402
from research.hunt_r2 import lattice as L  # noqa: E402
from research.hunt_r2 import ledger as LG  # noqa: E402
from research.hunt_r2 import pin_r2 as PN  # noqa: E402
from research.hunt_r2 import pretest_r2 as PT  # noqa: E402
from research.hunt_r2 import reads_r2 as RR  # noqa: E402
from research.hunt_r2 import report_r2 as RP  # noqa: E402
from research.hunt_r2 import select_r2 as SR  # noqa: E402

OUT_REL = "research/hunt_r2/out"
SELFCHECK_TESTS = ("tests/test_hunt_r2_core.py", "tests/test_hunt_r2_cli.py", "tests/test_hunt_r2_kit.py",
                   "tests/test_hunt.py", "tests/test_hunt_entries.py", "tests/test_data_hunt.py",
                   "tests/test_altpump.py")


class Refused(RuntimeError):
    pass


def rp(*parts) -> str:
    """A path under the repository root (tests point ``ROOT`` at a temporary tree)."""
    return os.path.join(ROOT, *parts)


def private_dir(args) -> str:
    base = args.private or os.path.join(args.data or os.environ.get("HUNT_DATA", "."), "hunt_r2_private")
    path = os.path.abspath(base)
    if os.path.commonpath([path, os.path.abspath(ROOT)]) == os.path.abspath(ROOT):
        raise SystemExit("--private must be outside the repository (D11)")
    return path


def check_pin(step: str) -> dict:
    try:
        return PN.check_pin(step, ROOT)
    except RuntimeError as e:
        raise Refused(str(e)) from e


def load_data(args, end_key: str) -> tuple:
    """H 2 before a step: the universe, the data up to the step's period end (nothing at or after it), the data
    identity against research/hunt/data_manifest.json."""
    data = args.data or os.environ.get("HUNT_DATA")
    if not data:
        raise SystemExit("--data <coins30 folder> (or $HUNT_DATA) is needed")
    H.disk_check(rp(OUT_REL), private_dir(args))
    syms = H.load_universe(data)
    end = H.day_ms(H.PERIODS[end_key][1])
    counts = H.load_study_data(data, syms, end)
    bad = H.data_identity_problems(counts, {s: c.get("funding_content_sha256") for s, c in counts.items()})
    if bad:
        raise SystemExit("stopped: the data differ from research/hunt/data_manifest.json (H 2): " + "; ".join(bad))
    return syms, counts, end


def stamp(pin) -> dict:
    return {"study": "hunt-r2 v1", "pin": pin, "git_commit": H.git_commit(),
            "written_utc": H.ms_str(int(time.time() * 1000))}


def names_order() -> list:
    return [n for _f, n in L.names()]


# ------------------------------------------------------------------ commands without data
def cmd_counts(args) -> int:
    print(L.write_counts())
    return 0


def cmd_pinlist(args) -> int:
    print("\n".join(PN.pinlist(ROOT)))
    bad = PN.pinlist_problems(ROOT)
    for b in bad:
        print(f"problem: {b}", file=sys.stderr)
    return 2 if bad else 0


def cmd_bench(args) -> int:
    out = args.out or rp(PN.BENCH)
    res = BR.bench(out, n_coins=args.coins, months=args.months, combos=args.combos)
    print(f"bench written to {out}: select about {res['extrapolation']['cpu_h']['select_total']} CPU-h; wall "
          f"{res['extrapolation']['select_wall_h_at_effective_cores']} h at 18 / 27 effective cores"
          + ("; ABOVE the 15 h line: tell the owners before renting" if res["extrapolation"]["above_the_line"] else ""))
    return 0


def cmd_selfcheck(args) -> int:
    tests = [t for t in SELFCHECK_TESTS if os.path.exists(rp(t))]
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *tests], cwd=ROOT)
    return r.returncode


# ------------------------------------------------------------------ select (4, 5)
def cmd_select(args) -> int:
    pin = check_pin("select")
    if os.path.exists(rp(PN.TEST)):
        raise Refused(f"{PN.TEST} exists: select does not run again")
    SR.ST.E.EW.fullgrid_pins()
    priv = private_dir(args)
    syms, counts, end = load_data(args, "select")
    mk = H.Market(syms, "select")
    if mk.end != end:
        raise Refused("the select market does not end where the data were cut")
    H.prepare_series(syms, H.TF_ORDER)
    tag = pin["pin_sha256"][:16]
    root = os.path.join(priv, "store")
    parts = os.path.join(priv, "parts", f"select_{tag}")
    t0 = time.time()
    order = names_order()
    res = SR.select_run(mk, root, parts, args.procs, names_order=order, n_rep=SR.N_REP)
    public, private = SR.picks_doc(order, res["real_units"], res["real"], res["hurdle"], res["box"], res["nulls"])
    psha = SR.write_json(os.path.join(priv, "picks_private.json"), private)
    public.update({**stamp(pin), "private_sha256": psha, "data_counts": counts, "n_rep": SR.N_REP,
                   "seconds": round(time.time() - t0, 1), "data_end_utc": H.ms_str(end)})
    SR.write_json(rp(PN.PICKS), public)
    h = PN.append_line(PN.PICKS, ROOT)
    print(f"round 2 select done in {time.time() - t0:.0f}s; picks.json sha256 {h} appended to {PN.R2_PIN} "
          f"({len(public['picks'])} picks; {public['label']})")
    return 0


def load_picks(priv: str | None = None) -> tuple:
    pk = CF.load_json(rp(PN.PICKS))
    ppriv = None
    if priv:
        p = os.path.join(priv, "picks_private.json")
        if os.path.exists(p) and H.sha256_file(p) == pk.get("private_sha256"):
            ppriv = CF.load_json(p)
    return pk, ppriv


# ------------------------------------------------------------------ pretest (6)
def cmd_pretest(args) -> int:
    pin = check_pin("pretest")
    post_hoc = os.path.exists(rp(PN.TEST))
    if os.path.exists(rp(PN.PRETEST)):
        raise Refused(f"{PN.PRETEST} exists (its line: {'in' if PN.is_pinned(PN.PRETEST, ROOT) else 'not in'} the "
                      "pin); delete it only to rerun before the test")
    priv = private_dir(args)
    pk, ppriv = load_picks(priv)
    if ppriv is None:
        raise Refused("picks_private.json is missing or its sha256 differs from picks.json's private_sha256")
    SR.ST.E.EW.fullgrid_pins()
    syms, counts, end = load_data(args, "select")
    mk = H.Market(syms, "select")
    H.prepare_series(syms, H.TF_ORDER)
    ctx = SR.Ctx(mk, os.path.join(priv, "store"))
    parts_sel = os.path.join(priv, "parts", f"select_{(pk.get('pin') or {}).get('pin_sha256', 'nopin')[:16]}")
    order = [r["name"] for r in pk["names"]]
    units = PT.load_real_units(parts_sel, order)
    if units is None:
        print("[pretest] the select step's real units are not in the parts folder: recomputing them from the store",
              flush=True)
        SR._RUN["ctx"] = ctx
        lst = H.pmap(SR._real_task, [(nm, None) for nm in order], args.procs, label="pretest real units")
        units = {u["name"]: u for u in lst}
    t0 = time.time()
    pub, prv = PT.pretest_run(ctx, units, pk, ppriv, parts_sel, args.procs, names_order=order,
                              n_rep=int(pk.get("n_rep") or SR.N_REP))
    psha = SR.write_json(os.path.join(priv, "pretest_private.json"), prv)
    pub.update({**stamp(pin), "what": "PREREG_HUNT_R2 6: select-only reads (2021-2023 bars only); choose nothing",
                "label": "computed after test.json: post hoc (6, DEVIATIONS.md)" if post_hoc else
                "computed before test.json (6)", "picks_sha256": H.sha256_file(rp(PN.PICKS)),
                "private_sha256": psha, "data_counts": counts, "seconds": round(time.time() - t0, 1)})
    bad = CF.d11_problems(pub, set(), "pretest")
    if bad:
        raise Refused(f"D11: DeepSeek figures in pretest_reads.json: {bad[:5]}")
    SR.write_json(rp(PN.PRETEST), pub)
    if not post_hoc:
        h = PN.append_line(PN.PRETEST, ROOT)
        print(f"pretest reads written; sha256 {h} appended to {PN.R2_PIN}")
    else:
        print("pretest reads written after test.json: post hoc, not appended to the pin")
    return 0


# ------------------------------------------------------------------ test (7, 8, 10)
def first_test_start(priv: str) -> dict:
    """Read guard 3: the reads lines of the pin and the pretest status at the FIRST test start for this picks file,
    written once to the private parts folder and never overwritten."""
    pk_sha = H.sha256_file(rp(PN.PICKS))
    path = os.path.join(priv, "parts", f"r2_test_start_{pk_sha[:16]}.json")
    if os.path.exists(path):
        d = CF.load_json(path)
        if d.get("picks_sha256") == pk_sha:
            return d
    now = PN.listed_now(ROOT)
    d = {"picks_sha256": pk_sha, "first_test_start_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
         "reads_lines": {m["rel"]: now.get(m["rel"]) for m in RR.MODULES.values() if now.get(m["rel"])},
         "pretest_reads": {"file": PN.PRETEST, "pinned_before_test": PN.is_pinned(PN.PRETEST, ROOT)}}
    H.disk_check(path)
    SR.write_json(path, d)
    return d


def ledger_snapshot(args, priv: str, full: dict | None) -> tuple:
    lp = args.ledger_private or os.path.join(priv, "ledger_inputs")
    snap = LG.snapshot(ROOT, lp, full, args.fullgrid_confirm, args.ledger_extra, public_root=args.ledger_public)
    return LG.public_of(snap), snap


def cmd_test(args) -> int:
    pin = check_pin("test")
    if os.path.exists(rp(PN.TEST)):
        raise Refused(f"{PN.TEST} exists but its line is not in the pin (the step stopped between writing and "
                      "pinning): delete it and run test again; every pick resumes from its part file (same results)")
    priv = private_dir(args)
    pk, _ = load_picks()
    marker = first_test_start(priv)
    t0 = time.time()
    batches = CF.batches_of(pk)
    if not batches:                               # 4.3 / 10.2: nothing runs on the test period
        full = CF.selection_failed_doc(pk)
        lpub, lfull = ledger_snapshot(args, priv, full)
        psha = SR.write_json(os.path.join(priv, "test_private.json"), {**full, "ledger": lfull})
        doc = {**stamp(pin), **full, "ledger": lpub, "test_data_read": False, "private_sha256": psha,
               "reads_pinned_at_test": marker["reads_lines"], "test_first_started_utc":
               marker["first_test_start_utc"], "pretest_reads": marker["pretest_reads"], "choices": CF.CHOICES,
               "seconds": round(time.time() - t0, 1)}
        SR.write_json(rp(PN.TEST), doc)
        h = PN.append_line(PN.TEST, ROOT)
        print(f"round 2 fails at selection: no test data read; test.json sha256 {h} appended to {PN.R2_PIN}")
        return 0
    SR.ST.E.EW.fullgrid_pins()
    syms, counts, end = load_data(args, "test")
    mks = RR.read_markets(syms)
    mk = mks["test"]
    if mk.end != end:
        raise Refused("the test market does not end where the data were cut")
    H.prepare_series(syms, sorted({p["tf"] for grp in batches for p in grp}, key=H.TF_ORDER.index))
    pdir = os.path.join(priv, "parts", f"r2_test_{pin['pin_sha256'][:16]}")

    def block_fn(sys_):
        part = os.path.join(pdir, CF.part_name(sys_))
        if os.path.exists(part):
            d = CF.load_json(part)
            if d.get("id") == sys_["id"]:
                return d["block"]
        t1 = time.time()
        blk = CF.pick_block(mk, sys_, args.procs)
        H.disk_check(part)
        SR.write_json(part, {"id": sys_["id"], "block": blk})
        print(f"round 2 test: pick {sys_.get('pick_no')} (batch {sys_.get('batch')}) {sys_['id']} done in "
              f"{time.time() - t1:.0f}s", flush=True)
        return CF.load_json(part)["block"]

    full = CF.test_walk(mk, pk, args.procs, block_fn)
    lpub, lfull = ledger_snapshot(args, priv, full)
    public = CF.redact_test(full)
    psha = SR.write_json(os.path.join(priv, "test_private.json"), {**full, "ledger": lfull})
    doc = {**stamp(pin), **public, "ledger": lpub, "test_data_read": True, "private_sha256": psha,
           "reads_pinned_at_test": marker["reads_lines"], "test_first_started_utc": marker["first_test_start_utc"],
           "pretest_reads": marker["pretest_reads"], "choices": CF.CHOICES, "data_counts": counts,
           "data_end_utc": H.ms_str(end), "seconds": round(time.time() - t0, 1)}
    ds_ids = {p["id"] for p in full["picks"] if CF.is_ds(p)}
    bad = CF.d11_problems(doc, ds_ids)
    if bad:
        raise Refused(f"D11: DeepSeek figures in the public test.json: {bad[:5]}")
    SR.write_json(rp(PN.TEST), doc)
    h = PN.append_line(PN.TEST, ROOT)
    v = full["verdict"]
    print(f"round 2 test done in {time.time() - t0:.0f}s: R2 PASS {'yes' if v['r2_pass'] else 'no'} "
          f"({len(v['passing'])}), TUNED BETTER {'yes' if v['tuning_beat_textbook'] else 'no'}; test.json sha256 {h} "
          f"appended to {PN.R2_PIN}")
    if not args.no_reads:
        try:                                     # the verdict stands whatever a read does
            st = RR.run_reads(args=args, pin=check_pin("reads"), mks=mks, syms=syms, test_doc=doc, full=full,
                              private_dir=priv, root=ROOT)
            print(f"[reads r2] {st}")
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            print(f"[reads r2] FAILED: {type(e).__name__}: {e}. test.json is written and unchanged; run "
                  "`python -m research.hunt_r2.hunt_r2 reads` after fixing (a read pinned after test.json is post hoc)",
                  flush=True)
    return 0


def load_test(priv: str) -> tuple:
    doc = CF.load_json(rp(PN.TEST))
    p = os.path.join(priv, "test_private.json")
    if not os.path.exists(p) or H.sha256_file(p) != doc.get("private_sha256"):
        raise Refused("test_private.json is missing or its sha256 differs from test.json's private_sha256")
    full = CF.load_json(p)
    full.pop("ledger", None)
    return doc, full


def cmd_reads(args) -> int:
    pin = check_pin("reads")
    priv = private_dir(args)
    doc, full = load_test(priv)
    if not full.get("picks"):
        print("[reads r2] no tested pick: section 9 has no rows (selection failed)")
        return 0
    SR.ST.E.EW.fullgrid_pins()
    syms, counts, end = load_data(args, "test")
    mks = RR.read_markets(syms)
    H.prepare_series(syms, sorted({p["tf"] for p in full["picks"]}, key=H.TF_ORDER.index))
    st = RR.run_reads(args=args, pin=pin, mks=mks, syms=syms, test_doc=doc, full=full, private_dir=priv, root=ROOT)
    print(f"[reads r2] {st}")
    return 0


def cmd_report(args) -> int:
    priv = private_dir(args) if (args.private or args.data or os.environ.get("HUNT_DATA")) else None
    print(RP.write(ROOT, priv))
    return 0


def cmd_ledger(args) -> int:
    """8: the three prints recomputed on a later decision date (round 2's own rows from its private test file)."""
    priv = private_dir(args) if (args.private or args.data or os.environ.get("HUNT_DATA")) else None
    full = None
    if os.path.exists(rp(PN.TEST)) and priv:
        _doc, full = load_test(priv)
    pub, snap = ledger_snapshot(args, priv or ".", full)
    out = args.out or rp(OUT_REL, f"ledger_{dt.datetime.now(dt.timezone.utc):%Y%m%d}.json")
    SR.write_json(out, pub)
    if priv:
        SR.write_json(os.path.join(priv, os.path.basename(out).replace(".json", "_private.json")), snap)
    print(f"ledger written to {out}: m = A {pub['prints']['A']['m']}, A+ {pub['prints']['A+']['m']}, "
          f"L {pub['prints']['L']['m']}")
    return 0


COMMANDS = {"counts": cmd_counts, "pinlist": cmd_pinlist, "bench": cmd_bench, "selfcheck": cmd_selfcheck,
            "select": cmd_select, "pretest": cmd_pretest, "test": cmd_test, "reads": cmd_reads, "report": cmd_report,
            "ledger": cmd_ledger}


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m research.hunt_r2.hunt_r2", description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=tuple(COMMANDS))
    ap.add_argument("--data", default=None)
    ap.add_argument("--private", default=None)
    ap.add_argument("--procs", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-reads", action="store_true", help="test: do not run the section-9 reads after test.json")
    ap.add_argument("--ledger-private", default=None, help="test / ledger: the folder the owners copied the other "
                                                           "studies' private files to (8)")
    ap.add_argument("--ledger-public", default=None, help="test / ledger: the folder holding the other studies' "
                                                          "public outputs under their repository paths (8; default: "
                                                          "the repository)")
    ap.add_argument("--fullgrid-confirm", default=None, help="test / ledger: the full grid's confirm.json (8, A+)")
    ap.add_argument("--ledger-extra", default=None, help="test / ledger: JSON list of further hypotheses (8)")
    ap.add_argument("--coins", type=int, default=30, help="bench: synthetic coins")
    ap.add_argument("--months", type=int, default=36, help="bench: synthetic select months")
    ap.add_argument("--combos", type=int, default=2, help="bench: combos timed per heavy name")
    return ap


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        return COMMANDS[args.cmd](args)
    except (Refused, H.PinError, H.ReadGuardError) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
