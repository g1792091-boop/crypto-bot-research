"""exitflex runner (research/exitflex/PREREG_EXITFLEX.md sections 5.3, 8, 9, 13, 14): the stages as command-line steps.

    python research/exitflex/runner_x.py make-pin  --data-dir DIR --work DIR        # writes data_pin.json (then pin it; refused once it is pinned)
    python research/exitflex/runner_x.py pin-lines                                   # the sha256 lines to put in the pin file
    python research/exitflex/runner_x.py make-cut                                    # the select cut data folder, in its own process (audit A5)
    python research/exitflex/runner_x.py timing                                      # seconds only -> out/timing.json
    python research/exitflex/runner_x.py select   [--procs N] [--rerun]              # step 1, step 2, select.json, SELECT_KO.md (once; --rerun = section 14)
    python research/exitflex/runner_x.py report                                      # READ-ONLY rewrite of select.json / SELECT_KO.md from the finished files
    python research/exitflex/runner_x.py choice   --input F [--now-utc T] [--rerun]    # out/choice.json from the owners' messages (8.3, 8.4)
    python research/exitflex/runner_x.py confirm  [--procs N]                        # once: confirm.json, REPORT_KO.md
    python research/exitflex/runner_x.py confirm-report [--extra-messages F]          # rewrite REPORT_KO.md from confirm.json
    python research/exitflex/runner_x.py check    [--which t1,t3,t5,t8]              # the real-data parts of T1, T3, T5, T8
    python research/exitflex/runner_x.py audit    --stage select|confirm             # A1-A9, pass / fail only
    python research/exitflex/runner_x.py audit-file --path F [--path F2 ...] [--after MARK]   # A8 + A9 on files before they are sent or committed

Every stage after make-pin REFUSES to run unless data_pin.json exists, every file listed in PREREG_EXITFLEX.sha256 still has
its hash, the required files are listed, and the previous stage's file is listed there with the hash it has now:
    timing  <- pin;   select <- pin + timing.json;   choice <- select.json + SELECT_KO.md + timing.json + sent.json;
    confirm <- all of those + choice.json (and, after a section 14 rerun, select_r2.json, SELECT_KO_r2.md, sent_r2.json, choice_r2.json).
A stage prints only progress (and, for the timing stage, seconds). Per-account result files are written atomically under
$WORK/<pin8>/results/<stage>/ (DeepSeek ones under $WORK/<pin8>/ds_private/, owners' rule D11: no DeepSeek money figure in
a committed file); a resume computes only the missing files. Nothing is read, summarised or printed until every file of the
stage exists; the summary then runs once. Select step 2 (placebos) starts only when every step-1 file exists and is passed
only the gate flags and the hazard tables of step 1.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import data_x as DX  # noqa: E402
import kernel_x as KX  # noqa: E402
import metrics as MT  # noqa: E402
import placebo as PL  # noqa: E402

K = KX.K
SIZES = (0.25, 1.0)
SIZE_TAG = {0.25: "q25", 1.0: "q100"}
SEED_BLOCK = 20
N_SEEDS_FULL, N_SEEDS_SHORT = 200, 100
TIMING_LIMIT_HOURS = 8.0
TIMING_PICK = "core-DOGE-15m-1"
CPUS_ASSUMED = 4
ELIGIBLE_ABORT = "none"

# files that must be listed in PREREG_EXITFLEX.sha256 (paths relative to the repo root)
REQUIRED_PINS = (
    "research/exitflex/PREREG_EXITFLEX.md", "research/exitflex/data_pin.json",
    "research/exitflex/data_x.py", "research/exitflex/kernel_x.py", "research/exitflex/placebo.py",
    "research/exitflex/metrics.py", "research/exitflex/runner_x.py", "research/exitflex/test_exitflex.py",
    "research/exitflex/native.py", "research/exitflex/native_ds.py",
    "paperbot/dash/tools/regime5y.py", "research/fullgrid/regimes.py",
    "research/fullgrid/kernel.py", "research/fullgrid/run.py", "research/fullgrid/sizing.py", "research/fullgrid/data.py",
    "research/fullgrid/ds_defs.py", "research/fullgrid/exchange.json", "research/fullgrid/diag/watch_sel.json",
    "candleague/data/candidates.json", "paperbot/quality_edges.json",
    "third_party/sweep/harness/vendor/fg_indicators.py", "third_party/sweep/harness/vendor/pine_indicators.py",
    "research/deepseek200/lib_c.py", "research/library/lib.py", "research/search/search.py",
    "research/entry_study/DEFS_BC.sha256",
    # the numbers that fix every account but live outside the files above (review): settings (config, ladder), brackets (margin),
    # the leverage group (levrule, entry_marks, sweepsig) and the grid code run.py loads (grid, memo)
    "paperbot/config.py", "paperbot/ladder.py", "paperbot/margin.py", "paperbot/levrule.py", "paperbot/entry_marks.py",
    "paperbot/sweepsig.py", "research/fullgrid/grid.py", "research/fullgrid/memo.py")
MODULE_DIRS = ("research/library", "research/search", "third_party/sweep/harness/vendor")


class StageRefused(SystemExit):
    """The runner refuses to run this stage (pin or previous stage's file does not match)."""


def refuse(msg: str):
    raise StageRefused(f"[refused] {msg}")


def progress(msg: str) -> None:
    print(msg, flush=True)


# ------------------------------------------------------------------ layout, pin and chain checks
class Layout:
    """Where everything lives; tests point it at a temporary folder."""

    def __init__(self, base: str = HERE, root: str = ROOT, out: str | None = None, sha_file: str | None = None,
                 pin_file: str | None = None, required: tuple | None = None):
        self.base, self.root = base, root
        self.out = out or os.path.join(base, "out")
        self.sha_file = sha_file or os.path.join(base, "PREREG_EXITFLEX.sha256")
        self.pin_file = pin_file or os.path.join(base, "data_pin.json")
        self.required = tuple(os.path.normpath(os.path.join(root, p)) for p in (REQUIRED_PINS if required is None else required))

    def out_file(self, name: str) -> str:
        return os.path.join(self.out, name)


def sha256_file(path: str) -> str:
    return DX.sha256_file(path)


def read_sha_file(lay: Layout) -> dict:
    """{absolute path: hash} of the pin file's lines ('<sha256>  <path>', the path relative to the pin file's folder, else
    to the repo root)."""
    if not os.path.exists(lay.sha_file):
        refuse(f"pin file missing: {lay.sha_file}")
    out = {}
    for line in open(lay.sha_file):
        if not line.strip():
            continue
        h, name = line.split(None, 1)
        name = name.strip()
        cands = [os.path.normpath(os.path.join(os.path.dirname(lay.sha_file), name)), os.path.normpath(os.path.join(lay.root, name))]
        path = next((c for c in cands if os.path.exists(c)), cands[0])
        out[path] = h
    return out


def git_head(root: str = ROOT) -> str:
    try:
        return subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def gate_pin(lay: Layout, verify_data: bool = True) -> tuple:
    """Refuse unless data_pin.json exists, every pinned file matches, the required files are pinned, and (optionally) the
    data files match the pin. Returns (pin dict, pin hash)."""
    if not os.path.exists(lay.pin_file):
        refuse(f"data_pin.json missing: {lay.pin_file}")
    pins = read_sha_file(lay)
    bad = [p for p, h in pins.items() if not os.path.exists(p) or sha256_file(p) != h]
    if bad:
        refuse("hash mismatch: " + ", ".join(os.path.relpath(p, lay.root) for p in bad[:6]))
    missing = [os.path.relpath(r, lay.root) for r in lay.required if r not in pins]
    if missing:
        refuse("not pinned: " + ", ".join(missing[:6]))
    code = [os.path.normpath(os.path.join(lay.base, f)) for f in sorted(os.listdir(lay.base)) if f.endswith(".py")]
    loose = [os.path.relpath(c, lay.root) for c in code if c not in pins]           # prereg 13: every .py file of this folder is pinned
    if loose:
        refuse("not pinned (code of this folder): " + ", ".join(loose[:6]))
    pin = DX.load_pin(lay.pin_file)
    ph = DX.pin_sha(lay.pin_file)
    if verify_data:
        try:
            DX.verify_data(pin)
        except DX.PinError as exc:
            refuse(str(exc))
    progress(f"[pin ok] commit {git_head(lay.root)[:10]} pin {DX.pin8(ph)}")
    return pin, ph


def require_pinned_file(lay: Layout, path: str, what: str) -> str:
    """The previous stage's file must exist and be listed in the pin file with its present hash. Returns its hash."""
    if not os.path.exists(path):
        refuse(f"{what} missing: {path}")
    pins = read_sha_file(lay)
    h = sha256_file(path)
    if pins.get(os.path.normpath(path)) != h:
        refuse(f"{what} is not pinned with its present hash (append its sha256 to {os.path.basename(lay.sha_file)})")
    return h


def write_json(path: str, doc) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False, sort_keys=False, default=_json_default)
    os.replace(path + ".tmp", path)


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.bool_,)):
        return bool(o)
    raise TypeError(type(o))


def pin_lines(lay: Layout) -> list:
    """The lines to put in PREREG_EXITFLEX.sha256 for the required files (and every .py file of this folder), relative to
    the repo root. Printing hashes of code and inputs shows no performance figure."""
    names = list(REQUIRED_PINS) if lay.required == Layout().required else [os.path.relpath(r, lay.root) for r in lay.required]
    extra = sorted(f"research/exitflex/{f}" for f in os.listdir(lay.base) if f.endswith(".py") and f"research/exitflex/{f}" not in names)
    out = []
    for n in names + extra:
        p = os.path.join(lay.root, n)
        if os.path.exists(p):
            out.append(f"{sha256_file(p)}  {n}")
    return out


def loaded_module_hashes(root: str = ROOT, dirs: tuple = MODULE_DIRS) -> dict:
    """sha256 of every .py file in research/library, research/search and the vendor folder: a superset of the module files
    the run loads (the select run records it, the confirm stage refuses on any difference)."""
    out = {}
    for d in dirs:
        for dp, _dn, fns in os.walk(os.path.join(root, d)):
            for f in sorted(fns):
                if f.endswith(".py"):
                    p = os.path.join(dp, f)
                    out[os.path.relpath(p, root)] = sha256_file(p)
    return dict(sorted(out.items()))


# ------------------------------------------------------------------ per-account result files
class Store:
    """Result files of one stage: $WORK/<pin8>/results/<stage>/<pick id>/<arm>__<tag>.npz; DeepSeek picks under
    $WORK/<pin8>/ds_private/results/<stage>/ (D11)."""

    def __init__(self, work: str, pin_hash: str, stage: str):
        self.work, self.pin8, self.stage = work, DX.pin8(pin_hash), stage

    def dir(self, pick: dict) -> str:
        sub = "ds_private/results" if pick["pool"] == "ds" else "results"
        return os.path.join(self.work, self.pin8, sub, self.stage, pick["id"])

    def path(self, pick: dict, arm: str, tag: str) -> str:
        return os.path.join(self.dir(pick), f"{arm}__{tag}.npz")

    def has(self, pick: dict, arm: str, tag: str) -> bool:
        return os.path.exists(self.path(pick, arm, tag))

    def save(self, pick: dict, arm: str, tag: str, doc: dict) -> None:
        path = self.path(pick, arm, tag)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".part.npz"
        np.savez_compressed(tmp, **{k: np.asarray(v) for k, v in doc.items()})
        os.replace(tmp, path)

    def load(self, pick: dict, arm: str, tag: str) -> dict:
        with np.load(self.path(pick, arm, tag)) as z:
            return {k: z[k] for k in z.files}

    def private_dir(self) -> str:
        return os.path.join(self.work, self.pin8, "ds_private")

    def files(self, pick: dict) -> list:
        d = self.dir(pick)
        return sorted(os.listdir(d)) if os.path.isdir(d) else []


def seed_blocks(n_seeds: int) -> list:
    return [(s0, min(n_seeds, s0 + SEED_BLOCK)) for s0 in range(0, n_seeds, SEED_BLOCK)]


def plc_tag(s0: int, s1: int) -> str:
    return f"plc{s0:03d}-{s1:03d}"


def _scalar(x):
    return x.item() if isinstance(x, np.ndarray) and x.ndim == 0 else x


# ------------------------------------------------------------------ configuration of a stage
class Config:
    """Everything a stage needs. ``make_pickdata(pick)`` builds a pick's chart data (real: signals on the pinned param_defs;
    tests: a synthetic provider)."""

    def __init__(self, lay, pin, pin_hash, stage, period, market, picks, variants, make_pickdata, n_seeds=N_SEEDS_FULL, procs=1):
        self.lay, self.pin, self.pin_hash, self.stage, self.period = lay, pin, pin_hash, stage, period
        self.market, self.picks, self.variants, self.make_pickdata = market, picks, list(variants), make_pickdata
        self.n_seeds, self.procs = n_seeds, procs
        self.edges = MT.month_edges(period)
        self.store = Store(pin["work"], pin_hash, stage)
        self.pools = {p["id"]: p["pool"] for p in picks}
        self.tfs = {p["id"]: p["tf"] for p in picks}
        self.by_id = {p["id"]: p for p in picks}

    def pool_picks(self, pool: str) -> list:
        return [p for p in self.picks if p["pool"] == pool]

    def pool_names(self) -> list:
        return [x for x in ("core", "ds") if any(p["pool"] == x for p in self.picks)]


def f11_provider_from_modules(rprov, native=None, native_ds=None):
    """Glue from the F11 modules of Appendix A to ``kernel_x.register_f11``: ``native.native_arrays(name, df, tf, combo)``
    (core) and ``native_ds.native(df, tf, name, combo, ctx, coin)`` (DeepSeek: lx, sx, inv_l, inv_s, tgt_l, tgt_s; one state
    component per side and the invalidation level). Returns None when the modules are absent."""
    if native is None or native_ds is None:
        return None

    def prov(pick, sym, df, close_ms, sl, ss):
        if pick["kind"] == "core":
            r = native.native_arrays(pick["name"], df, pick["tf"], pick["combo"])
            return {k: r.get(k) for k in ("comp_long", "comp_short", "lvl_long", "lvl_short", "tgt_long", "tgt_short")}
        ctx = None if sym == "BTCUSDT" else {"BTCUSD": rprov.frame("BTCUSDT", pick["tf"])[0]}
        r = native_ds.native(df, pick["tf"], pick["name"], pick["combo"], ctx, sym[:-1])
        if isinstance(r, dict):
            lx, sx, inv_l, inv_s, tgt_l, tgt_s = (r[k] for k in ("lx", "sx", "inv_l", "inv_s", "tgt_l", "tgt_s"))
        else:
            lx, sx, inv_l, inv_s, tgt_l, tgt_s = r
        return {"comp_long": [("state", lx)], "comp_short": [("state", sx)], "lvl_long": inv_l, "lvl_short": inv_s,
                "tgt_long": tgt_l, "tgt_short": tgt_s}
    return prov


def try_load_native():
    try:
        import native  # noqa: F401
        import native_ds  # noqa: F401
        return sys.modules["native"], sys.modules["native_ds"]
    except ImportError:
        return None, None


STAGE_PERIOD = {"timing": "select", "select": "select", "select_r2": "select", "check": "select",
                "confirm": "confirm", "confirm_r2": "confirm"}


def stage_make_cut(lay: Layout) -> str:
    """The select cut data folder ($WORK/<pin8>/cut-<cut time>/1m/, prereg 2 and 13), made in its own process: this is the one place that
    reads the full arrays for the select period. The select process only opens and verifies the folder (audit A5)."""
    pin, ph = gate_pin(lay)
    out = DX.write_cut(pin["data_dir"], pin["work"], ph, DX.SELECT_CUT_MS)
    if not DX.verify_cut(out):
        refuse("the cut data folder does not match its digests")
    progress(f"[make-cut] {os.path.basename(out)} ready, digests verified, no minute at or after the cut")
    return out


def ensure_cut(lay: Layout, pin: dict, pin_hash: str) -> str:
    """The verified cut folder of the pin; when it does not exist yet it is made by a separate ``make-cut`` process (the select process
    itself never loads the full arrays)."""
    try:
        return DX.open_cut(pin["work"], pin_hash, DX.SELECT_CUT_MS)
    except DX.CutMissing:
        r = subprocess.run([sys.executable, os.path.join(HERE, "runner_x.py"), "make-cut"], capture_output=True, text=True)
        if r.returncode != 0:
            refuse("make-cut failed: " + (r.stdout + r.stderr)[-300:])
        return DX.open_cut(pin["work"], pin_hash, DX.SELECT_CUT_MS)


def real_config(lay: Layout, stage: str, pin: dict, pin_hash: str, procs: int, n_seeds: int, allow_no_f11: bool = False,
                variants=None) -> Config:
    """The real data of a stage: select -> the pinned arrays cut at 2024-01-01 (their own folder, made by ``make-cut``), confirm -> the
    full pinned arrays. The stage's cache folder is deleted first. An unknown stage name is refused (it would silently load the
    confirm arrays)."""
    if stage not in STAGE_PERIOD:
        raise ValueError(f"unknown stage {stage!r}: {sorted(STAGE_PERIOD)}")
    period = STAGE_PERIOD[stage]
    cache = DX.fresh_stage(pin["work"], pin_hash, stage)
    if period == "select":
        data_dir = ensure_cut(lay, pin, pin_hash)
    else:
        data_dir = pin["data_dir"]
    rprov = DX.RealProvider(data_dir, cache)
    market = DX.Market(data_dir)
    if period == "select":                                   # audit A5: no minute at or after 2024-01-01 is loaded
        DX.assert_no_minute_at_or_after({s: {"ts": market.ts(i)} for i, s in enumerate(market.symbols)}, DX.SELECT_CUT_MS)
    prov11 = f11_provider_from_modules(rprov, *try_load_native())
    if prov11 is not None:
        KX.register_f11(prov11)
    elif not allow_no_f11:
        refuse("native.py / native_ds.py (families F11 and F12) are not available: the pre-registered menu has 88 variants")
    vs = KX.variants() if variants is None else variants
    KX.warm_up(market)                                       # compile before the workers fork
    return Config(lay, pin, pin_hash, stage, period, market, DX.picks(), vs,
                  lambda pick: DX.PickData(market, pick, rprov, f11=KX.F11_REGISTRY["provider"]), n_seeds, procs)


def report_config(lay: Layout, stage: str, pin: dict, pin_hash: str, n_seeds: int) -> Config:
    """A read-only configuration for the 'report' command: the picks, the variants and the result store, no market data, no cache folder
    and no way to compute a pick (``make_pickdata`` raises)."""
    prov11 = f11_provider_from_modules(None, *try_load_native())
    if prov11 is None:
        refuse("native.py / native_ds.py (families F11 and F12) are not available: the pre-registered menu has 88 variants")
    KX.register_f11(prov11)

    def no_compute(_pick):
        raise RuntimeError("report is read-only: it computes nothing")
    return Config(lay, pin, pin_hash, stage, STAGE_PERIOD[stage], None, DX.picks(), KX.variants(), no_compute, n_seeds, 1)


# ------------------------------------------------------------------ workers
_CFG: dict = {}


def run_pick_step1(cfg: Config, pick: dict, vids: list | None = None) -> int:
    """E0 and every variant (or the variants in ``vids``) of one pick, both sizes: one result file each (missing ones only)."""
    pdata, made = None, 0
    for v in [KX.E0] + [x for x in cfg.variants if vids is None or x.id in vids]:
        for scale in SIZES:
            tag = SIZE_TAG[scale]
            if cfg.store.has(pick, v.id, tag):
                continue
            pdata = pdata or cfg.make_pickdata(pick)
            res = KX.simulate(cfg.market, pdata, v, scale, cfg.period)
            cfg.store.save(pick, v.id, tag, {**MT.summarize(res, cfg.edges), "scale": scale})
            made += 1
    return made


def run_pick_step2(cfg: Config, pick: dict, vids: list) -> int:
    """The placebo blocks of the given variants on one pick (quarter size), from the hazard table of the variant's own
    quarter-size account."""
    pdata, made = None, 0
    for vid in vids:
        v = KX.variant_by_id(vid)
        hz = None
        for s0, s1 in seed_blocks(cfg.n_seeds):
            tag = plc_tag(s0, s1)
            if cfg.store.has(pick, vid, tag):
                continue
            if hz is None:
                own = cfg.store.load(pick, vid, SIZE_TAG[0.25])
                hz = PL.hazard(own["num"], own["den"])
            pdata = pdata or cfg.make_pickdata(pick)
            items = PL.run_block(cfg.market, pdata, v, hz, cfg.period, s0, s1, lambda r: MT.summarize_light(r, cfg.edges))
            cfg.store.save(pick, vid, tag, {**MT.stack_light(items), "seeds": np.arange(s0, s1)})
            made += 1
    return made


def _worker(task):
    cfg = _CFG["cfg"]
    kind, pid, arg = task
    pick = cfg.by_id[pid]
    return pid, (run_pick_step1(cfg, pick, arg) if kind == 1 else run_pick_step2(cfg, pick, arg))


def run_tasks(cfg: Config, tasks: list, label: str) -> None:
    """Run (kind, pick id, arg) tasks on ``cfg.procs`` processes (forked: the loaded arrays are shared); progress lines only."""
    _CFG["cfg"] = cfg
    done = 0
    t0 = time.time()
    if cfg.procs <= 1 or len(tasks) <= 1:
        for t in tasks:
            pid, n = _worker(t)
            done += 1
            progress(f"[{label}] {done}/{len(tasks)} {pid} ({n} new files, {time.time() - t0:.0f}s)")
        return
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor, as_completed
    with ProcessPoolExecutor(cfg.procs, mp_context=mp.get_context("fork")) as ex:
        futs = [ex.submit(_worker, t) for t in tasks]
        for f in as_completed(futs):
            pid, n = f.result()
            done += 1
            progress(f"[{label}] {done}/{len(tasks)} {pid} ({n} new files, {time.time() - t0:.0f}s)")


# ------------------------------------------------------------------ select: gates of step 1 and the placebo pairs of step 2
def _light(cfg: Config, pick: dict, arm: str, tag: str, keys=("g", "counts")) -> dict:
    with np.load(cfg.store.path(pick, arm, tag)) as z:
        return {k: z[k] for k in keys}


def step1_gates(cfg: Config) -> dict:
    """{(variant id, pool): {"M", "Mp", "entered", "entered_e0", "g1", "g2", "g4"}} from the quarter-size files of step 1.
    Gate 1: M_P > 0. Gate 2: M_p > 0 on at least 60% of the pool's picks. Gate 4: trades entered >= E0's."""
    out = {}
    e0 = {p["id"]: _light(cfg, p, "E0", SIZE_TAG[0.25]) for p in cfg.picks}
    for pool in cfg.pool_names():
        picks = cfg.pool_picks(pool)
        for v in cfg.variants:
            mp, ent, ent0 = [], 0, 0
            for p in picks:
                s = _light(cfg, p, v.id, SIZE_TAG[0.25])
                mp.append(float(np.mean(s["g"] - e0[p["id"]]["g"])))
                ent += MT.count(s, "entered")
                ent0 += MT.count(e0[p["id"]], "entered")
            M = float(np.mean(mp))
            el = MT.eligibility(M, mp, ent, ent0, None, True)          # gates 1, 2, 4 (gate 3 needs the placebo)
            out[(v.id, pool)] = {"M": M, "Mp": mp, "entered": ent, "entered_e0": ent0, "g1": el["c1_M_positive"],
                                 "g2": el["c2_picks_positive"], "g4": el["c4_entries"]}
    return out


def step2_pairs(cfg: Config, gates: dict) -> list:
    """The (variant id, pool) pairs that get a placebo: outside F7, F7h and F13 and passing gates 1, 2 and 4 (prereg 6, two steps)."""
    return [(v.id, pool) for pool in cfg.pool_names() for v in cfg.variants
            if PL.has_placebo(v) and gates[(v.id, pool)]["g1"] and gates[(v.id, pool)]["g2"] and gates[(v.id, pool)]["g4"]]


def placebo_pooled(cfg: Config, vid: str, pool: str, e0_g: dict) -> tuple:
    """(pooled means (n_seeds,), per-pick M_p of the placebos (picks, n_seeds), stacked light summaries per pick)."""
    mp, stacks = [], {}
    for p in cfg.pool_picks(pool):
        parts = [cfg.store.load(p, vid, plc_tag(s0, s1)) for s0, s1 in seed_blocks(cfg.n_seeds)]
        g = np.concatenate([x["g"] for x in parts])                    # (n_seeds, months)
        mp.append((g - e0_g[p["id"]][None, :]).mean(axis=1))
        stacks[p["id"]] = {k: np.concatenate([x[k] for x in parts]) for k in ("counts", "hold", "w_end", "max_dd", "reasons")}
        stacks[p["id"]]["num"] = np.sum([x["num"] for x in parts], axis=0)
        stacks[p["id"]]["den"] = np.sum([x["den"] for x in parts], axis=0)
    mp = np.array(mp)
    return mp.mean(axis=0), mp, stacks


# ------------------------------------------------------------------ the select summary (select.json, SELECT_KO.md, ds_private)
FAMILY_KO = {"F1": "구조 무너짐", "F2": "이동평균 이탈", "F3": "반대 신호", "F4": "고점 대비 되돌림(샹들리에)", "F5": "수익 반납",
             "F6": "빠른 손절(손실 중 구조 무너짐)", "F7": "시간 제한(봉 개수)", "F7h": "시간 제한(시계 시간)", "F8": "수익 뒤 구조 무너짐",
             "F9": "두 분 규칙 그대로", "F10": "멈춤(새 고점 없음)", "F11": "매매법 자체 청산", "F12": "9가지 청산 동시 적용",
             "F13": "규칙봇 계단 잠금(12%→10%, 17%→15%, 22%→20%...)"}
LOSS_CLASS_KO = {"L0": "L0 손실은 못 끊음(수익이 난 뒤에만 / 수익 중일 때만)", "L1": "L1 손실 0.5R 이상일 때 구조 무너짐",
                 "L2": "L2 작은 손실에도 구조 무너짐(진입가 근처 손절 가능)", "L3": "L3 구조 말고 다른 이유로도(이동평균·반대 신호·고점 대비·시간·매매법 자체)"}
CLAIM_EN = {"rule": MT.claim_of("F1.w3.a"), "f11": MT.claim_of("F11.a"), "f12": MT.claim_of("F12.a"), "f7": MT.claim_of("F7.N12.a"),
            "f13": MT.claim_of("F13.a")}
# prereg 8.5 (F12): the fixed combination, the 7 / 8 legs, the 8-hour clock, and the three things it does not claim
CLAIM_KO = {"rule": "지금 청산(E0)과, 같은 패턴의 무작위 청산보다 낫다", "f11": "매매법 자체 청산이 지금 청산과 같은 패턴의 무작위 청산보다 낫다",
            "f12": ("아홉 가지 청산을 이 고정된 조합 그대로 쓰면(1시간·4시간 매매법에서는 아홉 중 최대 7개, 15분·30분 매매법에서는 최대 8개가 "
                    "매매를 끝낼 수 있음: F6은 청산 시점을 바꾸지 않고 F10은 15분·30분 매매법에서만 작동) 지금 청산(E0)과, 같은 8시간 시계와 "
                    "같은 패턴의 무작위 청산보다 낫다. 쌓으면 단일 규칙보다 낫다거나, 아홉 개가 모든 매매법에서 다 작동한다거나, "
                    "F12가 최고의 청산이라는 뜻은 아님"),
            "f7": "오래 안 들고 있는 것만으로 낫다(차트를 읽는다는 뜻은 아님)",
            "f13": ("규칙봇의 계단 잠금으로 나온다: 순수익률이 12%를 찍은 뒤에는 10% 아래로 내려오지 않게 잠그고, 17%면 15%, 22%면 20%로 올린다. "
                    "차트의 구조는 읽지 않고, 그 이상은 말하지 않는다")}
DS_ALLOWED = MT.DS_ALLOWED
GATE_KO = {"pass": "통과", "fail": "탈락", "not_run": "안 돌림", "n/a": "해당 없음"}


def claim_key(v) -> str:
    return ("f7" if v.fam in (KX.F7, KX.F7H) else "f13" if v.fam == KX.F13 else
            ("f11" if v.fam == KX.F11 else ("f12" if v.fam == KX.F12 else "rule")))


def no_placebo_gate(v) -> bool:
    """Gate 3 of 8.1 does not apply: the clock families F7 and F7h (they read only the clock) and F13 (the stepped lock, an
    intrabar price-level stop that reads no chart close; prereg 6)."""
    return v.fam in (KX.F7, KX.F7H, KX.F13)


def _pool_load(cfg: Config, pool: str, arm: str, tag: str) -> dict:
    return {p["id"]: cfg.store.load(p, arm, tag) for p in cfg.pool_picks(pool)}


def variant_row(cfg: Config, v, pool: str, e0q: dict, e0live: dict, gates: dict, pairs: set) -> tuple:
    """(row without money, money dict, placebo pooled means or None) of one variant in one pool. The row has the labels, counts,
    win share and hold times that may be committed; the money dict has every figure."""
    sv = _pool_load(cfg, pool, v.id, SIZE_TAG[0.25])
    ps = MT.pool_summary(sv, e0q, cfg.pools, cfg.tfs)[pool]
    live = MT.pool_summary(_pool_load(cfg, pool, v.id, SIZE_TAG[1.0]), e0live, cfg.pools)[pool]
    g = gates[(v.id, pool)]
    in2 = (v.id, pool) in pairs
    clock = no_placebo_gate(v)
    plc = pooled = None
    if in2:
        pooled, _mp_plc, stacks = placebo_pooled(cfg, v.id, pool, {i: e0q[i]["g"] for i in e0q})
        qs = PL.percentiles(pooled)
        ent_s = np.sum([stacks[i]["counts"][:, MT.COUNT_NAMES.index("entered")] for i in stacks], axis=0)
        plc = {"p05": qs[5], "p50": qs[50], "p95": qs[95], "share_pos": float((pooled > 0).mean()), "n_seeds": int(len(pooled)),
               "median_pooled_mean_vs_e0": qs[50], "entered_median": float(np.median(ent_s))}
    el = MT.eligibility(ps["M"], ps["Mp"], ps["entered"], ps["entered_e0"], pooled, clock)
    if PL.has_placebo(v) and not in2:                                  # never reached step 2: a gate failed before gate 3
        el["c3_beats_placebo_p95"], el["eligible"] = False, False
    pf = lambda b: "pass" if b else "fail"   # noqa: E731
    gate3 = "n/a" if clock else (pf(el["c3_beats_placebo_p95"]) if in2 else "not_run")
    cls = MT.loss_class(v)
    row = {"id": v.id, "name_ko": FAMILY_KO[v.famname], "family": v.famname, "group": v.group, "mode": v.mode, "q15": bool(v.q15),
           "nparams": v.nparams, "order": v.order, "loss_class": cls, "in_default_set": MT.in_default_set(v),
           "gates": {"g1": pf(g["g1"]), "g2": pf(g["g2"]), "g3": gate3, "g4": pf(g["g4"])}, "step2": in2, "eligible": bool(el["eligible"]),
           "label": "선택 가능" if el["eligible"] else "선택 불가", "hold": ps["hold"], "entered": ps["entered"], "entered_e0": ps["entered_e0"],
           "entered_change_pct": 100.0 * (ps["entered"] / ps["entered_e0"] - 1.0) if ps["entered_e0"] else 0.0,
           "skipped": ps["skipped"], "skipped_e0": ps["skipped_e0"], "rejected": ps["rejected"], "closed": ps["closed"],
           "win_share": ps["win_share"], "entries_at_rule_minute": ps["entries_at_rule_minute"],
           "reasons": dict(zip(MT.REASONS, ps["reasons"])), "changed": ps["changed"], "changed_share": ps["changed_share"],
           "both_touched": ps["both_touched"], "claim": CLAIM_EN[claim_key(v)], "claim_ko": CLAIM_KO[claim_key(v)], "n_picks": ps["n_picks"],
           "same_as_f3": ("F3." + v.mode) if (v.fam == KX.F11 and pool == "ds") else None,
           "hold_by_state": ps["hold_by_state"],
           # prereg 7, reported beside (counts and hold hours only, so a DeepSeek row may carry them): live size, the realised hazard table h
           "hold_live": live["hold"], "entered_live": live["entered"], "skipped_live": live["skipped"], "rejected_live": live["rejected"],
           "hazard": {"num": np.sum([sv[i]["num"] for i in sorted(sv)], axis=0).tolist(), "den": np.sum([sv[i]["den"] for i in sorted(sv)], axis=0).tolist()}}
    if v.fam == KX.F12:                                                  # exits by component: fired, and fired alone (counts)
        row["comp_fired"] = dict(zip(MT.COMP_LABELS, ps["comp_fired"]))
        row["comp_alone"] = dict(zip(MT.COMP_LABELS, ps["comp_alone"]))
        row["comp_by_tf"] = ps["comp_by_tf"]
    money = {"M": ps["M"], "M_pct_month": 100.0 * (math.exp(ps["M"]) - 1.0), "median_Mp": ps["median_Mp"], "n_pos": ps["n_pos"],
             "Mp": dict(zip(ps["ids"], ps["Mp"])), "D": ps["D"].tolist(), "p95_gate": el["p95"], "placebo": plc,
             "live": {"M": live["M"], "M_pct_month": 100.0 * (math.exp(live["M"]) - 1.0), "busts": live["busts"], "entered": live["entered"]},
             "max_dd_median": ps["max_dd_median"], "final_multiple_median": ps["final_multiple_median"]}
    return row, money, pooled


def build_select_summary(cfg: Config, gates: dict, pairs: list) -> tuple:
    """(pools doc for out/select.json, DeepSeek private doc, core money of the not-choosable rows). Core rows that are choosable
    carry the growth figures; every other row only labels, counts, win share and hold times (8.2, D11)."""
    pairs_set = set(pairs)
    doc_pools, private, core_hidden = {}, {}, {}
    for pool in cfg.pool_names():
        e0q = _pool_load(cfg, pool, "E0", SIZE_TAG[0.25])
        e0live = _pool_load(cfg, pool, "E0", SIZE_TAG[1.0])
        e0_ps = MT.pool_summary(e0q, e0q, cfg.pools)[pool]
        e0_row = {"hold": e0_ps["hold"], "entered": e0_ps["entered"], "skipped": e0_ps["skipped"], "win_share": e0_ps["win_share"],
                  "rejected": e0_ps["rejected"], "closed": e0_ps["closed"], "reasons": dict(zip(MT.REASONS, e0_ps["reasons"])),
                  "both_touched": e0_ps["both_touched"], "n_picks": e0_ps["n_picks"], "hold_by_state": e0_ps["hold_by_state"]}
        rows, money = [], {}
        for v in cfg.variants:
            row, mon, _pooled = variant_row(cfg, v, pool, e0q, e0live, gates, pairs_set)
            row["default_set"] = row["in_default_set"]
            rows.append(row)
            money[v.id] = mon
        default = MT.default_choice(rows)
        for r in rows:
            r.pop("default_set")
            r["mark_default"] = r["id"] in default
        ordered = [r for r in rows if r["eligible"]] + [r for r in rows if not r["eligible"]]       # choosable first, canonical order
        entry = {"n_picks": len(cfg.pool_picks(pool)), "e0": e0_row, "variants": ordered, "eligible_ids": [r["id"] for r in rows if r["eligible"]],
                 "default_ids": default, "gate_fail_counts": MT.gate_failure_counts(rows)}
        if pool == "core":
            for r in ordered:
                if r["eligible"]:
                    r.update({k: money[r["id"]][k] for k in ("M", "M_pct_month", "median_Mp", "n_pos", "live", "placebo", "p95_gate", "Mp")})
                else:
                    core_hidden[r["id"]] = money[r["id"]]
            entry["qa"] = [{"id": r["id"], "median_pooled_mean_vs_e0": money[r["id"]]["placebo"]["p50"],
                            "share_seeds_positive": money[r["id"]]["placebo"]["share_pos"], "n_seeds": money[r["id"]]["placebo"]["n_seeds"]}
                           for r in rows if money[r["id"]]["placebo"] is not None]
            entry["e0"]["max_dd_median"], entry["e0"]["final_multiple_median"] = e0_ps["max_dd_median"], e0_ps["final_multiple_median"]
        else:
            e0_live = MT.pool_summary(e0live, e0live, cfg.pools)[pool]
            e0_m = float(np.mean([np.mean(e0q[i]["g"]) for i in e0q]))
            e0_ml = float(np.mean([np.mean(e0live[i]["g"]) for i in e0live]))
            private[pool] = {"e0": {"max_dd_median": e0_ps["max_dd_median"], "final_multiple_median": e0_ps["final_multiple_median"],
                                    "growth_per_month_log": e0_m, "growth_pct_month": 100.0 * (math.exp(e0_m) - 1.0),
                                    "live_growth_pct_month": 100.0 * (math.exp(e0_ml) - 1.0), "live_busts": e0_live["busts"]},
                             "variants": money, "order": [r["id"] for r in ordered], "eligible_ids": [r["id"] for r in rows if r["eligible"]],
                             "default_ids": default}
        doc_pools[pool] = entry
    return doc_pools, private, core_hidden


def _hold_cells(h: dict) -> list:
    return [f"{h['median']:.1f}", f"{100 * h['share_gt4']:.0f}%", f"{100 * h['share_gt8']:.0f}%", f"{100 * h['share_gt18']:.0f}%"]


def state_table_ko(P: dict) -> list:
    """The second table of 8.2 / the confirm report: hold hours by market state at entry, E0 and every variant of the pool, same
    order as the first table; no growth column. A cell under 100 trades is marked 건수 적음 (shown, not hidden)."""
    states = [DX.STATE_KO[c] for c in DX.STATE_ORDER]
    head = ["방식"] + [f"{st}: 건수 / 중앙값(시간) / >4 / >8 / >18" for st in states]

    def cells(hbs):
        out = []
        for st in states:
            c = hbs[st]
            if c["n"] == 0:
                out.append("0")
                continue
            out.append(f"{c['n']} / {c['median']:.1f} / {100 * c['share_gt4']:.0f}% / {100 * c['share_gt8']:.0f}% / {100 * c['share_gt18']:.0f}%"
                       + (" 건수 적음" if c["few"] else ""))
        return out
    rows = [["E0"] + cells(P["e0"]["hold_by_state"])] + [[r["id"]] + cells(r["hold_by_state"]) for r in P["variants"]]
    return ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(x) + " |" for x in rows] + [""]


def comp_table_ko(P: dict) -> list:
    rows = [r for r in P["variants"] if "comp_fired" in r]
    if not rows:
        return []
    names = list(MT.COMP_LABELS)
    out = ["F12(아홉 가지 동시)의 청산 이유별 횟수: 그 요소가 발동한 청산 수 / 그 요소 혼자 발동한 청산 수 (요소 이름은 비트 순서로 적었습니다)", "",
           "| 방식 | 봉 | " + " | ".join(names) + " |", "|" + "---|" * (len(names) + 2)]
    for r in rows:
        out.append(f"| {r['id']} | 전체 | " + " | ".join(f"{r['comp_fired'][n]} / {r['comp_alone'][n]}" for n in names) + " |")
        for tf, c in (r.get("comp_by_tf") or {}).items():
            out.append(f"| {r['id']} | {tf} ({c['n_picks']}개) | " + " | ".join(f"{c['fired'][n]} / {c['alone'][n]}" for n in names) + " |")
    return out + [""]


# prereg 17 item 4a, section 15 (the dated addendum) and Known limit 1: a fixed line of the select report and of the confirm report. The
# main session read the round-1 hunt results (with test-period outcomes of chandelier-exit trend systems) before this file was hashed;
# the owners are told so in the report itself. It carries no number of any result.
HUNT_READ_KO = ("**미리 밝혀 둘 점 (고르시기 전에 읽어 주세요)**: 이 시험의 규칙을 잠그기 전인 2026-10-12 약 06:38 UTC(한국 시각 15:38)에 "
                "메인 세션이 사냥 시험 1차 결과(넓은 시험의 판정표, 결과 요약 문서, 실행 기록의 끝부분)를 열어 봤고, 검증을 맡은 보조 에이전트들이 "
                "나머지 결과 파일을 약 06:40~07:30 UTC에 읽어 그 요약을 메인 세션이 봤습니다. 그 결과에는 샹들리에 청산을 쓰는 추세 시스템의 "
                "2024-01~2026-09 기간 결과가 들어 있습니다. 그래서 4번(샹들리에)과 12번 안의 샹들리에 부분을 2024~2026으로 확인하는 것은 "
                "저희에게 이미 한 번 본 종류의 청산을 다시 보는 셈입니다(영문 사전 등록 15절의 날짜 붙은 추가 기록과 한계 1). 사냥 시험의 숫자는 "
                "이 시험의 어떤 선택에도 쓰지 않았고, 샹들리에를 포함한 청산 후보 목록은 그 결과가 나오기 약 4시간 전(2026-10-12 01:48 UTC)에 "
                "이미 깃에 올라가 있었습니다. 가장 깨끗한 확인은 새 리그의 앞으로 쌓이는 기록입니다.")


def select_report_ko(doc: dict) -> str:
    """The Korean report of prereg 8.2: per pool E0's row, then all 88 variants (choosable first, then '선택 불가'), hold time and
    entries first, then the second table (hold hours by market state). DeepSeek rows carry no money figure; non-choosable core
    rows no growth figure."""
    L = ["# 유연한 청산 시험: 고르기 결과 (2021~2023, 1/4 크기 계좌)", "", HUNT_READ_KO, "",
         "표의 순서: 보유시간과 진입 횟수가 먼저입니다. 시장가로 한 번 사고 파는 데 드는 비용은 포지션 금액의 약 0.14%입니다 (30배면 증거금의 4.2%).",
         "더 짧게 들면 진입이 늘지만, 늘어난 진입이 이 비용보다 더 벌어야 계좌가 커집니다. 선택 가능은 관문 4개(성장 > 0, 60% 이상의 매매법에서 나음,",
         f"같은 패턴의 무작위 청산 {doc['n_seeds']}번의 상위 5% 초과, 진입 횟수 유지)를 모두 넘은 방식입니다(시간 제한 F7·F7h와 계단 잠금 F13은 3번 관문이 없음). "
         "풀마다 서로 다른 그룹에서 최대 2개, 또는 \"없음\"을 골라 주세요.", ""]
    for pool, name in (("core", "코어 23개"), ("ds", "딥시크 15개")):
        if pool not in doc["pools"]:
            continue
        P = doc["pools"][pool]
        e0 = P["e0"]
        L += [f"## {name}", "", f"지금 청산(E0): 보유시간 중앙값 {e0['hold']['median']:.1f}시간, 4시간 넘게 든 비율 {100 * e0['hold']['share_gt4']:.0f}%, "
              f"8시간 {100 * e0['hold']['share_gt8']:.0f}%, 18시간 {100 * e0['hold']['share_gt18']:.0f}%; 진입 {e0['entered']}번, "
              f"들고 있어서 놓친 신호 {e0['skipped']}개, 승률 {100 * e0['win_share']:.0f}%.", ""]
        head = ["방식", "이름", "그룹", "숫자 수", "보유 중앙값(시간)", ">4시간", ">8시간", ">18시간", "진입(E0 대비)", "놓친 신호(E0)", "손실 끊기",
                "기본 후보", "관문 1/2/3/4", "선택", "성장" if pool == "core" else "결과", "승률", "말할 수 있는 것", "표시"]
        rows = []
        for r in P["variants"]:
            gm = "/".join(GATE_KO[r["gates"][k]] for k in ("g1", "g2", "g3", "g4"))
            if pool == "core":
                gr = (f"월 {r['M_pct_month']:+.2f}% (로그 {r['M']:+.4f}); 참고: 지금 크기 월 {r['live']['M_pct_month']:+.2f}%"
                      + (f"; 무작위 청산 5/50/95% (월 로그) {r['placebo']['p05']:+.4f}/{r['placebo']['p50']:+.4f}/{r['placebo']['p95']:+.4f}"
                         if r.get("placebo") else "") if r["eligible"] else "")
            else:
                gr = "통과" if r["eligible"] else ""
            marks = [m for m, on in (("기본값이 고르는 방식", r["mark_default"]),
                                     (f"= {r['same_as_f3']} (F7_RF_ONLY 3개 매매법에서)", bool(r["same_as_f3"]))) if on]
            rows.append([r["id"], r["name_ko"], r["group"], r["nparams"]] + _hold_cells(r["hold"]) + [
                f"{r['entered']} / {r['entered_e0']} ({r['entered_change_pct']:+.0f}%)", f"{r['skipped']} ({r['skipped_e0']})",
                LOSS_CLASS_KO[r["loss_class"]], "예" if r["in_default_set"] else "아니오", gm, r["label"], gr,
                f"{100 * r['win_share']:.0f}%", r["claim_ko"] if r["eligible"] else "", ", ".join(marks)])
        L += ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(str(c) for c in x) + " |" for x in rows] + [""]
        if not P["eligible_ids"]:
            L += ["선택 가능한 방식이 없습니다(\"없음\"). 위 표에서 각 방식이 어느 관문에서 부족했는지 볼 수 있습니다.", ""]
        f = P["gate_fail_counts"]
        L += [f"관문을 못 넘은 방식 수(순서대로 셈): 1번 {f['gate1']}, 2번(1번 통과 중) {f['gate2']}, 4번(1·2번 통과 중) {f['gate4']}, "
              f"3번(무작위 비교까지 간 것 중) {f['gate3']}.", ""]
        L += comp_table_ko(P)
        L += [f"### {name}: 장세별 보유시간 (참고용 정보입니다. 관문·기본값·고르기에는 쓰이지 않습니다)", "",
              "진입한 신호 봉의 장세(추세장·횡보장·급변장·보통, 자료가 모자라면 모름)별로 본 2021~2023 매매의 보유시간입니다. 건수 100 미만 칸은 건수 적음으로 표시했습니다.", ""]
        L += state_table_ko(P)
        if pool == "core" and P.get("qa"):
            L += ["무작위 청산 자체가 지금 청산보다 나았는지(참고, 무작위 비교까지 간 방식):", "", "| 방식 | 무작위 청산 합산 평균 중앙값(월 로그성장 차이) | 0보다 큰 시드 비율 |", "|---|---|---|"]
            L += [f"| {q['id']} | {q['median_pooled_mean_vs_e0']:+.5f} | {100 * q['share_seeds_positive']:.0f}% |" for q in P["qa"]] + [""]
    L += ["고르지 않은 풀은 마감(보낸 뒤 48시간, 질문을 드리면 질문 뒤 24시간까지 연장)에 기본값이 적용됩니다. 기본값은 기본 후보(L0·L1) 중 보유시간이 가장 짧은 방식입니다. \"없음\"이라고 하면 없음으로 둡니다.", ""]
    return "\n".join(L)


OWNER_REPORT_LAST_LINE = ("답하실 때는 방식을 id로 적어 주세요(예: F9.a). 딥시크 금액 숫자는 따라 적지 말아 주세요. "
                          "보내 주신 글에 그 숫자가 있으면 저장하기 전에 [딥시크 금액 삭제]로 바꿉니다.")


def owner_report_md(stage: str, private: dict, order: dict, labels: dict | None = None) -> str:
    """The private owner report of prereg 3 (select or confirm): the DeepSeek money figures, shown to the owners in the conversation
    and never committed. Rows follow the committed table's order; nothing is ranked by money; no p value. ``private`` is the
    stage's ds_private document."""
    L = [f"# 딥시크 금액 보고서 ({'고르기' if stage == 'select' else '확인'}), 비공개: 저장소에 올리지 않음", "",
         "이 파일은 소유자 두 분께 대화로만 보여 주는 파일입니다. 금액 기준 순위는 매기지 않았고, 검정 수치는 넣지 않았습니다.", ""]
    if stage == "select":
        for pool, P in private.items():
            e0 = P["e0"]
            L += [f"## {pool}", "", f"지금 청산(E0): 월 로그성장 {e0['growth_per_month_log']:+.5f} (월 {e0['growth_pct_month']:+.2f}%), 지금 크기 월 "
                  f"{e0['live_growth_pct_month']:+.2f}%, 계좌 최종 배수 중앙값 {e0['final_multiple_median']:.2f}, 최대 낙폭 중앙값 {100 * e0['max_dd_median']:.0f}%, "
                  f"지금 크기 파산 {e0['live_busts']}개.", "",
                  "| 방식 | 선택 | 풀 합산 월 로그성장 차이 | 월 % | 지금 크기 월 % | 최종 배수 중앙값 | 최대 낙폭 중앙값 | 파산(지금 크기) |", "|---|---|---|---|---|---|---|---|"]
            for vid in P["order"]:
                m = P["variants"][vid]
                if vid in P["eligible_ids"]:
                    L.append(f"| {vid} | 선택 가능 | {m['M']:+.5f} | {m['M_pct_month']:+.2f}% | {m['live']['M_pct_month']:+.2f}% | "
                             f"{m['final_multiple_median']:.2f} | {100 * m['max_dd_median']:.0f}% | {m['live']['busts']} |")
                else:
                    L.append(f"| {vid} | 선택 불가 | | | | | | |")
            L.append("")
    else:
        for pool, e0 in (private.get("e0") or {}).items():             # prereg 3: the same for E0 as for the chosen variants
            L += [f"## 지금 청산(E0), {pool}", "", f"월 로그성장 {e0['growth_per_month_log']:+.5f} (월 {e0['growth_pct_month']:+.2f}%), 지금 크기 월 "
                  f"{e0['live_growth_pct_month']:+.2f}%, 계좌 최종 배수 중앙값 {e0['final_multiple_median']:.2f}, 최대 낙폭 중앙값 "
                  f"{100 * e0['max_dd_median']:.0f}%, 지금 크기 파산 {e0['live_busts']}개.", ""]
        for key, m in private.get("pairs", {}).items():
            L += [f"## {key}", "", f"풀 합산 월 로그성장 차이 {m['M']:+.5f} (월 {m['M_pct_month']:+.2f}%), 95% 구간 [{m['interval95'][0]:+.5f}, {m['interval95'][1]:+.5f}], "
                  f"지금 크기 월 로그 {m['live']['M']:+.5f}, 파산(지금 크기) {m['live']['busts']}, 최종 배수 중앙값 {m['final_multiple_median']:.2f}, "
                  f"최대 낙폭 중앙값 {100 * m['max_dd_median']:.0f}%.", ""]
    L += [OWNER_REPORT_LAST_LINE]
    return "\n".join(L) + "\n"


def select_table_csv(doc: dict) -> str:
    cols = ["pool", "id", "family", "group", "mode", "q15", "nparams", "loss_class", "in_default_set", "eligible", "g1", "g2", "g3", "g4",
            "step2", "hold_median_h", "share_gt4h", "share_gt8h", "share_gt18h", "entered", "entered_e0", "entered_change_pct", "skipped",
            "skipped_e0", "win_share", "changed_share", "entries_at_rule_minute", "M", "M_pct_month", "median_Mp", "n_pos",
            "live_M_pct_month", "same_as_f3", "mark_default"]
    out = [",".join(cols)]
    for pool, P in doc["pools"].items():
        for r in P["variants"]:
            h = r["hold"]
            vals = [pool, r["id"], r["family"], r["group"], r["mode"], r["q15"], r["nparams"], r["loss_class"], r["in_default_set"], r["eligible"],
                    r["gates"]["g1"], r["gates"]["g2"], r["gates"]["g3"], r["gates"]["g4"], r["step2"], h["median"], h["share_gt4"],
                    h["share_gt8"], h["share_gt18"], r["entered"], r["entered_e0"], r["entered_change_pct"], r["skipped"], r["skipped_e0"],
                    r["win_share"], r["changed_share"], r["entries_at_rule_minute"], r.get("M", ""), r.get("M_pct_month", ""),
                    r.get("median_Mp", ""), r.get("n_pos", ""), r["live"]["M_pct_month"] if "live" in r else "", r["same_as_f3"] or "",
                    r["mark_default"]]
            out.append(",".join("" if x is None else str(x) for x in vals))
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------ stages: timing, select, report
def versions() -> dict:
    import numba
    import pandas
    return {"python": sys.version.split()[0], "numpy": np.__version__, "pandas": pandas.__version__, "numba": numba.__version__}


def expected_files(cfg: Config, picks_vids: dict, step2: dict | None = None) -> list:
    """(pick, arm, tag) of every result file a stage must have: picks_vids = {pick id: [variant ids]}."""
    out = []
    for pid, vids in picks_vids.items():
        p = cfg.by_id[pid]
        for arm in ["E0"] + list(vids):
            out += [(p, arm, SIZE_TAG[s]) for s in SIZES]
        for vid in (step2 or {}).get(pid, []):
            out += [(p, vid, plc_tag(s0, s1)) for s0, s1 in seed_blocks(cfg.n_seeds)]
    return out


def all_present(cfg: Config, files: list) -> bool:
    return all(cfg.store.has(p, a, t) for p, a, t in files)


def cost_order(picks: list) -> list:
    """Costliest first (15m picks hold the most checks), so that the pool is busy to the end."""
    rank = {"15m": 0, "30m": 1, "1h": 2, "4h": 3}
    return sorted(picks, key=lambda p: (rank[p["tf"]], p["id"]))


def write_owner_report(cfg: Config, stage: str, private: dict, suffix: str = "") -> str:
    """Write the private owner report of the stage under ds_private/ (never committed) and return its sha256."""
    path = os.path.join(cfg.store.private_dir(), f"owner_report_{stage}{suffix}.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(owner_report_md(stage, private, {}))
    return sha256_file(path)


def select_plan(cfg: Config, run: bool) -> tuple:
    """(picks, {pick: all variant ids}, gates, step-2 pairs, {pick: step-2 variant ids}). ``run`` True: compute what is missing (step 1,
    then step 2). ``run`` False: read-only, and a missing result file is a refusal (the 'report' command)."""
    picks = cost_order(cfg.picks)
    vids_all = [v.id for v in cfg.variants]
    pv = {p["id"]: vids_all for p in picks}
    if run:
        run_tasks(cfg, [(1, p["id"], None) for p in picks], "select step 1")
    if not all_present(cfg, expected_files(cfg, pv)):
        refuse("step 1 is incomplete")
    gates = step1_gates(cfg)
    pairs = step2_pairs(cfg, gates)
    s2 = {p["id"]: [vid for vid, pool in pairs if pool == p["pool"]] for p in picks}
    if run:
        run_tasks(cfg, [(2, pid, vids) for pid, vids in s2.items() if vids], "select step 2")
    if not all_present(cfg, expected_files(cfg, pv, s2)):
        refuse("step 2 is incomplete")
    return picks, pv, gates, pairs, s2


def write_select_outputs(cfg: Config, timing: dict | None, gates: dict, pairs: list) -> dict:
    """select.json, SELECT_KO.md, the private DeepSeek files and the table csv from the finished result files. The committed documents
    carry no run-dependent field (no commit hash, no time), so writing them again from the same files gives the same bytes."""
    vids_all = [v.id for v in cfg.variants]
    doc_pools, private, hidden = build_select_summary(cfg, gates, pairs)
    ds_path = os.path.join(cfg.store.private_dir(), "select_ds.json" if cfg.stage == "select" else "select_ds_r2.json")
    sfx = "_r2" if cfg.stage == "select_r2" else ""
    ds_sha = ds_report_sha = None
    if private:
        write_json(ds_path, {"note": "DeepSeek money figures (D11): read only by the runner", "pools": private})
        ds_sha = sha256_file(ds_path)
        ds_report_sha = write_owner_report(cfg, "select", private, sfx)
    if hidden:                                               # growth of the not-choosable core rows: kept out of the committed report
        write_json(os.path.join(cfg.store.work, cfg.store.pin8, "results", cfg.stage, "core_not_choosable.json"), hidden)
    doc = {"study": "exitflex v1", "stage": "select", "pin": cfg.pin_hash, "versions": versions(),
           "modules": loaded_module_hashes(cfg.lay.root), "engine": DX.engine_fingerprint(cfg.market), "n_seeds": cfg.n_seeds, "variants": vids_all,
           "f11": any(v.fam == KX.F11 for v in cfg.variants), "complete_menu": len(vids_all) == 88,
           "timing_sha256": sha256_file(cfg.lay.out_file("timing.json")) if os.path.exists(cfg.lay.out_file("timing.json")) else None,
           "ds_private_sha256": ds_sha, "ds_owner_report_sha256": ds_report_sha, "step2_pairs": {f"{vid}|{pool}": True for vid, pool in pairs}, "pools": doc_pools,
           "timing": timing}
    write_json(cfg.lay.out_file(f"select{sfx}.json"), doc)
    with open(cfg.lay.out_file(f"SELECT_KO{sfx}.md"), "w", encoding="utf-8") as fh:
        fh.write(select_report_ko(doc))
    os.makedirs(os.path.join(cfg.store.work, cfg.store.pin8, "results", cfg.stage), exist_ok=True)
    with open(os.path.join(cfg.store.work, cfg.store.pin8, "results", cfg.stage, "SELECT_TABLE.csv"), "w") as fh:
        fh.write(select_table_csv(doc))
    return doc


def finish_select(cfg: Config, timing: dict | None = None, quiet: bool = False) -> dict:
    """Run step 1 (every pick, every arm, both sizes), then step 2 (the placebos that passed gates 1, 2 and 4), then the
    summary once. Returns the select document. The commit of the run goes to a side file of the stage's results folder (not into the
    committed document)."""
    _picks, _pv, gates, pairs, _s2 = select_plan(cfg, True)
    doc = write_select_outputs(cfg, timing, gates, pairs)
    write_json(os.path.join(cfg.store.work, cfg.store.pin8, "results", cfg.stage, "run_info.json"),
               {"stage": cfg.stage, "commit": git_head(cfg.lay.root), "versions": versions()})
    return doc


def report_select(cfg: Config, timing: dict | None = None) -> dict:
    """Read-only: rewrite select.json and SELECT_KO.md from result files that all exist. It never computes a missing file (a missing one
    is a refusal)."""
    _picks, _pv, gates, pairs, _s2 = select_plan(cfg, False)
    return write_select_outputs(cfg, timing, gates, pairs)


def stage_timing(lay: Layout, procs: int = CPUS_ASSUMED) -> dict:
    """Seconds only. In one process on the select-period cut arrays: E0, and one placebo seed of every variant outside F7, F7h and F13 on
    one pick (the hazard table is that variant's own account on the pick, computed and discarded). The projected step-2
    wall time = (sum of the one-seed placebo times) x picks x 200 seeds / 4 CPUs; more than 8 h means 100 seeds."""
    pin, ph = gate_pin(lay)
    cfg = real_config(lay, "timing", pin, ph, 1, N_SEEDS_FULL)
    return run_timing(cfg)


def run_timing(cfg: Config) -> dict:
    pick = cfg.by_id[TIMING_PICK] if TIMING_PICK in cfg.by_id else cfg.picks[0]
    pdata = cfg.make_pickdata(pick)
    KX.simulate(cfg.market, pdata, KX.E0, 0.25, cfg.period)                    # compile (not timed)
    t = time.time()
    KX.simulate(cfg.market, pdata, KX.E0, 0.25, cfg.period)
    e0 = time.time() - t
    own, plc = {}, {}
    for v in cfg.variants:
        if not PL.has_placebo(v):
            continue
        t = time.time()
        res = KX.simulate(cfg.market, pdata, v, 0.25, cfg.period)
        own[v.id] = time.time() - t
        hz = PL.hazard(res.num, res.den)
        t = time.time()
        PL.run_block(cfg.market, pdata, v, hz, cfg.period, 0, 1, lambda r: None)
        plc[v.id] = time.time() - t
    proj = sum(plc.values()) * len(cfg.picks) * N_SEEDS_FULL / CPUS_ASSUMED / 3600.0
    n_seeds = N_SEEDS_SHORT if proj > TIMING_LIMIT_HOURS else N_SEEDS_FULL
    doc = {"stage": "timing", "pick": pick["id"], "pin": cfg.pin_hash, "commit": git_head(cfg.lay.root), "versions": versions(),
           "e0_account_seconds": e0, "variant_account_seconds": own, "placebo_one_seed_seconds": plc,
           "sum_placebo_one_seed_seconds": sum(plc.values()), "n_variants_timed": len(plc), "n_picks": len(cfg.picks),
           "cpus": CPUS_ASSUMED, "projected_step2_hours": proj, "limit_hours": TIMING_LIMIT_HOURS, "n_seeds": n_seeds,
           "f11_included": any(v.fam == KX.F11 for v in cfg.variants)}
    write_json(cfg.lay.out_file("timing.json"), doc)
    progress(f"[timing] E0 account {e0:.2f}s, sum of one-seed placebos {sum(plc.values()):.1f}s, projected step 2 {proj:.1f} h -> {n_seeds} seeds")
    return doc


def require_deviation_entry(lay: Layout, tag: str) -> None:
    """Prereg 14: a rerun is allowed once a bug is recorded in this folder's DEVIATIONS.md before the rerun's output is read. The entry
    must name the rerun by its stage name (``select_r2`` / ``confirm_r2``)."""
    path = os.path.join(lay.base, "DEVIATIONS.md")
    if not os.path.exists(path) or tag not in open(path, encoding="utf-8").read():
        refuse(f"a {tag} rerun needs an entry naming {tag} in {os.path.relpath(path, lay.root)} (section 14), written before the rerun")


def guard_select_outputs(lay: Layout, rerun: bool) -> None:
    """The select stage runs once: it refuses when select.json or SELECT_KO.md exists or is listed in the pin file (use 'report' to rewrite
    an unpinned one). A rerun (section 14, a bug found before any confirm) needs select.json, no select_r2.json, no confirm.json and a
    DEVIATIONS entry."""
    sfx = "_r2" if rerun else ""
    pins = read_sha_file(lay)
    for name in (f"select{sfx}.json", f"SELECT_KO{sfx}.md"):
        path = lay.out_file(name)
        if os.path.exists(path) or os.path.normpath(path) in pins:
            refuse(f"{name} already exists or is pinned: the select stage runs once (a section 14 rerun is 'select --rerun'; "
                   f"an unpinned file is rewritten by 'report')")
    if rerun:
        if not os.path.exists(lay.out_file("select.json")):
            refuse("select --rerun needs the first select.json (section 14)")
        if os.path.exists(lay.out_file("confirm.json")):
            refuse("a select rerun is allowed before any confirm only (section 14)")
        require_deviation_entry(lay, "select_r2")


def stage_select(lay: Layout, procs: int, rerun: bool = False) -> dict:
    """Select, step 1 then step 2 (writes select.json, SELECT_KO.md and the private DeepSeek files). ``rerun`` (section 14, a bug found
    before any confirm): a fresh stage 'select_r2' that writes select_r2.json / SELECT_KO_r2.md / *_r2 private files."""
    pin, ph = gate_pin(lay)
    tpath = lay.out_file("timing.json")
    require_pinned_file(lay, tpath, "timing.json")
    guard_select_outputs(lay, rerun)
    timing = json.load(open(tpath))
    cfg = real_config(lay, "select_r2" if rerun else "select", pin, ph, procs, int(timing["n_seeds"]))
    return finish_select(cfg, timing)


def stage_report(lay: Layout, procs: int = 1) -> dict:
    """Rewrite select.json and SELECT_KO.md from the existing result files. Read-only: it computes nothing (a missing result file is a
    refusal, never a second way to start the select run), it loads no market data, and it refuses once select.json or SELECT_KO.md is
    listed in the pin file (a pinned report is changed only by a section 14 rerun)."""
    pin, ph = gate_pin(lay, verify_data=False)
    tpath = lay.out_file("timing.json")
    require_pinned_file(lay, tpath, "timing.json")
    pins = read_sha_file(lay)
    for name in ("select.json", "SELECT_KO.md"):
        if os.path.normpath(lay.out_file(name)) in pins:
            refuse(f"{name} is already pinned: 'report' does not rewrite a pinned file (section 14: select --rerun)")
    timing = json.load(open(tpath))
    cfg = report_config(lay, "select", pin, ph, int(timing["n_seeds"]))
    return report_select(cfg, timing)


# ------------------------------------------------------------------ stage: choice (prereg 8.3, 8.4 and 14)
NONE_WORDS = ("없음", "none")
POOLS = ("core", "ds")


def _parse_utc(t: str) -> dt.datetime:
    d = dt.datetime.fromisoformat(str(t).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def _utc(d: dt.datetime) -> str:
    return d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _kst(d: dt.datetime) -> str:
    return (d.astimezone(dt.timezone.utc) + dt.timedelta(hours=9)).strftime("%Y-%m-%dT%H:%M:%S+09:00")


def parse_answer(a) -> list:
    """An owners' answer for one pool: a list of 1-2 ids, or '없음' / 'none' (-> []). Anything else is unclear."""
    if isinstance(a, str) and a.strip().lower() in NONE_WORDS:
        return []
    if isinstance(a, (list, tuple)) and 1 <= len(a) and all(isinstance(x, str) for x in a):
        return [x.strip() for x in a]
    raise ValueError(f"unclear answer {a!r}: ids or 없음")


def pool_deadline(sent: dt.datetime, questions: list, pool: str) -> dt.datetime:
    """8.3: 48 h after the report's sending time; each question the main session sent about the pool moves it to at least 24 h after
    the question (a question without a 'pools' field concerns both pools)."""
    d = sent + dt.timedelta(hours=48)
    for q in questions:
        if pool in (q.get("pools") or POOLS):
            d = max(d, _parse_utc(q["time_utc"]) + dt.timedelta(hours=24))
    return d


def build_choice(sel: dict, sent: dict, inp: dict, now: dt.datetime, prev: dict | None = None) -> dict:
    """The content of choice.json from select.json, sent.json and the input (messages, questions, material received). Per pool:
    the latest answer timed at or after the sending and before the deadline counts; with none, the pool takes the default of
    8.4 once the deadline has passed (before it: refused); an explicit 없음 stays none. ``prev`` = the first choice.json when
    this is a rerun's choice_r2 (section 14): ids that are still choosable stand, only voided ids are re-asked."""
    sent_t = _parse_utc(sent["sent_utc"])
    if sent.get("sent_kst") and sent["sent_kst"] != _kst(sent_t):
        refuse("sent.json: sent_kst is not sent_utc + 9 h")
    if (sel.get("pools") or {}).get("ds") is not None:                  # 8.3 / 8.7: the private report was shown at or before the sending
        shown = sent.get("ds_report_shown_utc")
        if not shown:
            refuse("sent.json: ds_report_shown_utc missing (the private DeepSeek report must be shown at or before the sending of SELECT_KO.md)")
        if _parse_utc(shown) > sent_t:
            refuse("sent.json: the private DeepSeek report was shown after SELECT_KO.md was sent")
        if sent.get("ds_report_shown_kst") and sent["ds_report_shown_kst"] != _kst(_parse_utc(shown)):
            refuse("sent.json: ds_report_shown_kst is not ds_report_shown_utc + 9 h")
    msgs, qs = list(inp.get("messages") or []), list(inp.get("questions") or [])
    out = {"core": [], "ds": [], "pools": {}}
    late = []
    for pool in POOLS:
        P = (sel.get("pools") or {}).get(pool)
        if P is None:
            continue
        choosable = set(P["eligible_ids"])
        standing, none_stays = [], False
        if prev is not None:
            pinfo = (prev.get("pools") or {}).get(pool, {})
            standing = [i for i in (prev.get(pool) or []) if i in choosable]
            none_stays = pinfo.get("answer") == "없음"
            voided = [i for i in (prev.get(pool) or []) if i not in choosable]
            need = bool(voided) and not none_stays
        else:
            need = True
        deadline = pool_deadline(sent_t, qs, pool)
        answers = []
        for m in msgs:
            a = (m.get("answers") or {}).get(pool)
            if a is None:
                continue
            t = _parse_utc(m["time_utc"])
            if t < sent_t:
                continue
            try:
                answers.append((t, parse_answer(a), "없음" if isinstance(a, str) else list(a)))
            except ValueError as exc:
                refuse(f"{pool}: {exc}")
        counting = [x for x in answers if x[0] < deadline]
        late += [{"pool": pool, "time_utc": _utc(x[0]), "answer": x[2]} for x in answers if x[0] >= deadline]
        info = {"deadline_utc": _utc(deadline), "answer_times_utc": [_utc(x[0]) for x in answers], "default_used": False,
                "default_ids": list(P.get("default_ids") or [])}
        if not need:
            ids = list(standing)
            info.update({"answer": "없음" if none_stays else "stands", "answer_time_utc": None})
        elif counting:
            t, ids_ans, shown = max(counting, key=lambda x: x[0])
            ids = standing + [i for i in ids_ans if i not in standing]
            info.update({"answer": "없음" if shown == "없음" else shown, "answer_time_utc": _utc(t)})
        elif now < deadline:
            refuse(f"{pool}: no answer yet and the deadline {_utc(deadline)} has not passed")
        else:
            ids = standing + MT.default_choice(P["variants"], standing)
            info.update({"answer": None, "answer_time_utc": None, "default_used": True})
        out[pool], out["pools"][pool] = ids, info
    out["late_messages"] = late
    return out


def redact_input(inp: dict, private_path: str) -> tuple:
    """Prereg 3 / 8.3: every DeepSeek money figure in an owner message, a main-session question, a freeze breach note or a material entry
    is replaced by the marker before it is written to a committed file; the rest stays verbatim. The sha256 of each unredacted text that
    changed goes to ``private_path`` (ds_private/owner_messages.json). Returns (the redacted input, the number of figures replaced)."""
    out = json.loads(json.dumps(inp))
    total, items = 0, []
    for kind in ("messages", "questions"):
        for i, m in enumerate(out.get(kind) or []):
            new, n = MT.redact_ds_money(m.get("text", ""))
            if n:
                items.append({"kind": kind, "index": i, "time_utc": m.get("time_utc"), "figures": n,
                              "sha256_unredacted": hashlib.sha256(m["text"].encode("utf-8")).hexdigest()})
                m["text"] = new
                total += n
    for kind in ("material_received", "freeze_breaches"):
        for i, t in enumerate(out.get(kind) or []):
            new, n = MT.redact_ds_money(t)
            if n:
                items.append({"kind": kind, "index": i, "figures": n, "sha256_unredacted": hashlib.sha256(t.encode("utf-8")).hexdigest()})
                out[kind][i] = new
                total += n
    if items:
        write_json(private_path, {"note": "sha256 of the unredacted owner texts (D11); never committed", "items": items})
    return out, total


def stage_choice(lay: Layout, inp: dict | str, now_utc: str | None = None, rerun: bool = False) -> dict:
    """Write out/choice.json (rerun: out/choice_r2.json) from the owners' messages (``inp``: a dict or the path of a JSON file with
    messages [{time_utc, text, answers: {core: ids | 없음, ds: ...}}], questions [{time_utc, text, pools}], material_received
    [text], freeze_breaches [text]). Needs select.json, SELECT_KO.md, timing.json and sent.json pinned."""
    pin, ph = gate_pin(lay, verify_data=False)
    sel_name, sent_name = ("select_r2.json", "sent_r2.json") if rerun else ("select.json", "sent.json")
    shas = {name: require_pinned_file(lay, lay.out_file(name), name) for name in (sel_name, "SELECT_KO.md" if not rerun else "SELECT_KO_r2.md",
                                                                                  "timing.json", sent_name)}
    sel = json.load(open(lay.out_file(sel_name)))
    sent = json.load(open(lay.out_file(sent_name)))
    if sel.get("pin") != ph:
        refuse("select.json was made under another pin")
    prev = None
    if rerun:
        require_pinned_file(lay, lay.out_file("choice.json"), "choice.json")
        prev = json.load(open(lay.out_file("choice.json")))
    if isinstance(inp, str):
        inp = json.load(open(inp, encoding="utf-8"))
    now = _parse_utc(now_utc) if now_utc else dt.datetime.now(dt.timezone.utc)
    body = build_choice(sel, sent, inp, now, prev)
    inp, redacted = redact_input(inp, os.path.join(pin["work"], DX.pin8(ph), "ds_private", "owner_messages.json" if not rerun else "owner_messages_r2.json"))
    doc = {"study": "exitflex v1", "stage": "choice_r2" if rerun else "choice", "pin": ph, "commit": git_head(lay.root),
           "select_sha256": shas[sel_name], "sent_sha256": shas[sent_name], "timing_sha256": shas["timing.json"],
           "sent_utc": sent["sent_utc"], "sent_kst": sent.get("sent_kst") or _kst(_parse_utc(sent["sent_utc"])),
           "channel": sent.get("channel"), "freeze_note": sent.get("freeze_note"),
           "ds_report_shown_utc": sent.get("ds_report_shown_utc"), "ds_report_shown_kst": sent.get("ds_report_shown_kst"),
           "messages": list(inp.get("messages") or []), "questions": list(inp.get("questions") or []),
           "material_received": list(inp.get("material_received") or []), "freeze_breaches": list(inp.get("freeze_breaches") or []),
           "redacted_figures": redacted, **body}
    bad_text = [ln for ln in MT.audit_text("\n".join(MT.json_strings(doc))) if True]
    if bad_text:
        refuse("choice text still holds a possible DeepSeek money figure (audit A8): " + bad_text[0][:60])
    bad = MT.validate_choice_doc(sel, doc, sent, prev) + MT.material_problems(doc)
    if bad:
        refuse("choice does not validate: " + "; ".join(bad))
    out_name = "choice_r2.json" if rerun else "choice.json"
    if os.path.normpath(lay.out_file(out_name)) in read_sha_file(lay):
        refuse(f"{out_name} is already pinned: a choice is final once hashed (8.3)")
    write_json(lay.out_file(out_name), doc)
    progress(f"[choice] core {doc['core']} ds {doc['ds']} default used: "
             + ", ".join(f"{p} {i['default_used']}" for p, i in doc["pools"].items()))
    return doc


# ------------------------------------------------------------------ stage: confirm (prereg 9)
def check_modules_unchanged(lay: Layout, sel: dict) -> None:
    """Prereg 13: the module files the select run recorded (research/library, research/search, the vendor folder) are the same now.
    Refuses before the confirm computes anything."""
    modules = loaded_module_hashes(lay.root)
    diff = [k for k, h in sel.get("modules", {}).items() if modules.get(k) != h]
    if diff:
        refuse("module files changed since the select run: " + ", ".join(diff[:5]))


def check_engine_unchanged(cfg: Config, sel: dict) -> None:
    """The settings vectors and the bracket digest the select run wrote into select.json equal the confirm run's (they come from
    paperbot/config.py, margin.py and exchange.json, outside the pinned arrays). A select.json without them is refused."""
    want = sel.get("engine")
    if not want:
        refuse("select.json has no engine fingerprint (settings vectors and bracket digest)")
    got = DX.engine_fingerprint(cfg.market)
    if got != want:
        refuse("engine inputs changed since the select run: " + ", ".join(k for k in ("S", "brackets_sha256") if got.get(k) != want.get(k)))


def e0_private_row(e0q: dict, e0l: dict, e0_ps: dict, e0_live: dict) -> dict:
    """E0's own DeepSeek money figures for the private confirm report (prereg 3): growth per month, live-size growth, median final
    multiple, median drawdown, busts at live size. Private only (ds_private/confirm_ds.json and the owner report)."""
    m = float(np.mean([np.mean(e0q[i]["g"]) for i in e0q]))
    ml = float(np.mean([np.mean(e0l[i]["g"]) for i in e0l]))
    return {"max_dd_median": e0_ps["max_dd_median"], "final_multiple_median": e0_ps["final_multiple_median"], "growth_per_month_log": m,
            "growth_pct_month": 100.0 * (math.exp(m) - 1.0), "live_growth_pct_month": 100.0 * (math.exp(ml) - 1.0), "live_busts": e0_live["busts"]}


def finish_confirm(cfg: Config, sel: dict, choice: dict) -> dict:
    pairs = [(vid, "core") for vid in choice["core"]] + [(vid, "ds") for vid in choice["ds"]]
    if not pairs:
        refuse("no variant was chosen: nothing runs on the confirm period (8.6)")
    check_modules_unchanged(cfg.lay, sel)                               # before any account is computed
    check_engine_unchanged(cfg, sel)
    chosen = {pool: [vid for vid, p in pairs if p == pool] for pool in POOLS}
    picks = cost_order([p for p in cfg.picks if chosen.get(p["pool"])])
    s2_vids = {p["id"]: [vid for vid in chosen[p["pool"]] if PL.has_placebo(KX.variant_by_id(vid))] for p in picks}
    run_tasks(cfg, [(1, p["id"], chosen[p["pool"]]) for p in picks], "confirm step 1")
    pv = {p["id"]: chosen[p["pool"]] for p in picks}
    if not all_present(cfg, expected_files(cfg, pv)):
        refuse("confirm step 1 is incomplete")
    run_tasks(cfg, [(2, pid, vids) for pid, vids in s2_vids.items() if vids], "confirm placebos")
    if not all_present(cfg, expected_files(cfg, pv, s2_vids)):
        refuse("confirm placebos are incomplete")
    out_p, ps, e0_ps = {}, {}, {}
    for pool in POOLS:
        if chosen[pool]:
            e0q = _pool_load(cfg, pool, "E0", SIZE_TAG[0.25])
            e0_ps[pool] = MT.pool_summary(e0q, e0q, cfg.pools)[pool]
    for vid, pool in pairs:
        v = KX.variant_by_id(vid)
        e0q = _pool_load(cfg, pool, "E0", SIZE_TAG[0.25])
        e0l = _pool_load(cfg, pool, "E0", SIZE_TAG[1.0])
        s = MT.pool_summary(_pool_load(cfg, pool, vid, SIZE_TAG[0.25]), e0q, cfg.pools, cfg.tfs)[pool]
        live = MT.pool_summary(_pool_load(cfg, pool, vid, SIZE_TAG[1.0]), e0l, cfg.pools)[pool]
        seed = DX.seed_of("exitflex", "confirm", vid, pool)
        D = s["D"]
        p_block, p_iid, ci = MT.block_bootstrap_p(D, seed), MT.iid_bootstrap_p(D, seed), MT.block_bootstrap_ci(D, seed)
        pooled = qa = None
        if PL.has_placebo(v):
            pooled, _mp, _stacks = placebo_pooled(cfg, vid, pool, {i: e0q[i]["g"] for i in e0q})
            g_all = {p["id"]: np.concatenate([cfg.store.load(p, vid, plc_tag(s0, s1))["g"] for s0, s1 in seed_blocks(cfg.n_seeds)])
                     for p in cfg.pool_picks(pool)}
            dm = np.mean([g_all[i].mean(axis=0) - e0q[i]["g"] for i in g_all], axis=0)
            qa = {"median_pooled_mean": float(np.median(pooled)), "share_seeds_positive": float((pooled > 0).mean()),
                  "p_block_of_seed_mean_D": MT.block_bootstrap_p(dm, DX.seed_of("exitflex", "confirm", vid, pool, "placebo")),
                  "p05": float(np.percentile(pooled, 5)), "p50": float(np.percentile(pooled, 50)), "p95": float(np.percentile(pooled, 95))}
        out_p[f"{vid}|{pool}"] = p_block
        ps[(vid, pool)] = {"s": s, "live": live, "pooled": pooled, "qa": qa, "p_iid": p_iid, "ci": ci, "v": v}
    holm = MT.holm(out_p, 0.05)                                       # over every chosen pair; DeepSeek p values enter from here only
    res, private = {}, {}
    for vid, pool in pairs:
        x = ps[(vid, pool)]
        s = x["s"]
        key = f"{vid}|{pool}"
        info = (choice.get("pools") or {}).get(pool, {})
        clock = no_placebo_gate(x["v"])
        verdict = MT.confirm_verdict(holm[key], s["M"], x["pooled"], clock, s["entered"], s["entered_e0"])
        row = {"id": vid, "pool": pool, "holm_significant": verdict["holm"], "beats_placebo_p95": verdict["beats_placebo_p95"],
               "entries_ok": verdict["entries"], "pass": verdict["pass"], "label": "PASS" if verdict["pass"] else "FAIL",
               "hold": s["hold"], "hold_e0": s["hold_e0"], "hold_by_state": s["hold_by_state"], "hold_by_state_e0": s["hold_by_state_e0"],
               "entered": s["entered"], "entered_e0": s["entered_e0"], "skipped": s["skipped"], "skipped_e0": s["skipped_e0"],
               "closed": s["closed"], "rejected": s["rejected"], "win_share": s["win_share"], "reasons": dict(zip(MT.REASONS, s["reasons"])),
               "claim": CLAIM_EN[claim_key(x["v"])], "chosen_by": "default" if info.get("default_used") else "owners",
               "default_would_take": vid in (((sel.get("pools") or {}).get(pool) or {}).get("default_ids") or [])}
        if x["v"].fam == KX.F12:
            row["comp_fired"] = dict(zip(MT.COMP_LABELS, s["comp_fired"]))
            row["comp_alone"] = dict(zip(MT.COMP_LABELS, s["comp_alone"]))
            row["comp_by_tf"] = s["comp_by_tf"]
        money = {"M": s["M"], "M_pct_month": 100.0 * (math.exp(s["M"]) - 1.0), "interval95": list(x["ci"]), "D": s["D"].tolist(),
                 "live": {"M": x["live"]["M"], "busts": x["live"]["busts"]}, "qa": x["qa"], "p95_gate": verdict["p95"],
                 "max_dd_median": s["max_dd_median"], "final_multiple_median": s["final_multiple_median"],
                 "p_block": out_p[key], "p_iid": x["p_iid"]}
        if pool == "core":
            row.update(money)
        else:
            private.setdefault("pairs", {})[key] = money
        res[key] = row
    modules = loaded_module_hashes(cfg.lay.root)
    check_modules_unchanged(cfg.lay, sel)                              # again after the run: nothing moved while it ran
    csfx = "_r2" if cfg.stage == "confirm_r2" else ""                      # a confirm rerun (section 14) writes the *_r2 names
    ds_sha = ds_report_sha = None
    if private:
        e0l_ds = _pool_load(cfg, "ds", "E0", SIZE_TAG[1.0])
        private["e0"] = {"ds": e0_private_row(_pool_load(cfg, "ds", "E0", SIZE_TAG[0.25]), e0l_ds, e0_ps["ds"],
                                              MT.pool_summary(e0l_ds, e0l_ds, cfg.pools)["ds"])}
        ds_path = os.path.join(cfg.store.private_dir(), f"confirm_ds{csfx}.json")
        write_json(ds_path, {"note": "DeepSeek money figures and p values (D11): read only by the runner", **private})
        ds_sha = sha256_file(ds_path)
        ds_report_sha = write_owner_report(cfg, "confirm", private, csfx)
    e0_rows = {pool: {"hold": e0_ps[pool]["hold"], "hold_by_state": e0_ps[pool]["hold_by_state"], "entered": e0_ps[pool]["entered"],
                      "skipped": e0_ps[pool]["skipped"], "closed": e0_ps[pool]["closed"], "win_share": e0_ps[pool]["win_share"],
                      "reasons": dict(zip(MT.REASONS, e0_ps[pool]["reasons"]))} for pool in e0_ps}
    doc = {"study": "exitflex v1", "stage": "confirm", "pin": cfg.pin_hash, "commit": git_head(cfg.lay.root), "versions": versions(),
           "modules": modules, "choice_sha256": sha256_file(cfg.lay.out_file("choice_r2.json" if os.path.exists(cfg.lay.out_file("choice_r2.json"))
                                                                          else "choice.json")),
           "select_sha256": sha256_file(cfg.lay.out_file("select_r2.json" if os.path.exists(cfg.lay.out_file("choice_r2.json")) else "select.json")),
           "n_seeds": cfg.n_seeds, "holm_alpha": 0.05,
           "e0": e0_rows, "pairs": res, "ds_private_sha256": ds_sha, "ds_owner_report_sha256": ds_report_sha,
           "freeze_breaches": list(choice.get("freeze_breaches") or []), "late_messages": list(choice.get("late_messages") or []),
           "line": "this confirm uses the same 33 months as the full grid, the hunt (v1, wide, round 2) and track 2"}
    write_json(cfg.lay.out_file(f"confirm{csfx}.json"), doc)
    with open(cfg.lay.out_file(f"REPORT_KO{csfx}.md"), "w", encoding="utf-8") as fh:
        fh.write(confirm_report_ko(doc))
    return doc


def confirm_report_ko(doc: dict, extra_messages: list | None = None) -> str:
    """out/REPORT_KO.md (prereg 9): per pool hold hours and entries against E0 first, then PASS or FAIL, then for core M, p and the
    95% interval; DeepSeek rows carry labels, counts, win share and hold hours only. Whether the owners or the default chose each
    pair and whether it is also what the default would have taken; freeze breaches and messages received after choice.json."""
    L = ["# 유연한 청산 시험: 확인 결과 (2024-01 ~ 2026-09, 한 번만 돌림)", "", HUNT_READ_KO, ""]
    for b in doc.get("freeze_breaches") or []:
        L += [f"**동결 위반**: {b}", ""]
    L += ["확인 결과는 PASS(성장이 구간 검정을 통과하고 무작위 청산 상위 5%를 넘고 진입 횟수를 유지) 또는 FAIL입니다. FAIL은 이번 검정에서 이득이 안 보였다는 뜻이지 이득이 없다는 증명이 아닙니다.", ""]
    for pool, name in (("core", "코어"), ("ds", "딥시크")):
        rows = [r for r in doc["pairs"].values() if r["pool"] == pool]
        if not rows:
            continue
        e0 = doc["e0"][pool]
        L += [f"## {name}", "", f"지금 청산(E0): 보유시간 중앙값 {e0['hold']['median']:.1f}시간, >4시간 {100 * e0['hold']['share_gt4']:.0f}%, "
              f">8시간 {100 * e0['hold']['share_gt8']:.0f}%, >18시간 {100 * e0['hold']['share_gt18']:.0f}%; 진입 {e0['entered']}번, 승률 {100 * e0['win_share']:.0f}%.", ""]
        for r in rows:
            h = r["hold"]
            L += [f"### {r['id']} ({'두 분이 고름' if r['chosen_by'] == 'owners' else '기본값이 고름'}; 기본값이 골랐을 방식과 같음: "
                  f"{'예' if r['default_would_take'] else '아니오'})", "",
                  f"보유시간 중앙값 {h['median']:.1f}시간, >4시간 {100 * h['share_gt4']:.0f}%, >8시간 {100 * h['share_gt8']:.0f}%, >18시간 {100 * h['share_gt18']:.0f}%; "
                  f"진입 {r['entered']}번 (E0 {r['entered_e0']}), 놓친 신호 {r['skipped']} (E0 {r['skipped_e0']}), 승률 {100 * r['win_share']:.0f}%.",
                  "", f"**{r['label']}** (홀름 {'유의' if r['holm_significant'] else '유의하지 않음'}, 무작위 청산 상위 5% 초과 "
                  f"{'예' if r['beats_placebo_p95'] else '아니오'}, 진입 유지 {'예' if r['entries_ok'] else '아니오'})", ""]
            if pool == "core":
                L += [f"풀 합산 월 로그성장 차이 {r['M']:+.5f} (월 {r['M_pct_month']:+.2f}%), 95% 구간 [{r['interval95'][0]:+.5f}, {r['interval95'][1]:+.5f}], "
                      f"블록 부트스트랩 p = {r['p_block']:.4f} (참고: iid p = {r['p_iid']:.4f}).", ""]
            if r["pass"]:
                L += [f"말할 수 있는 것: {r['claim']}", ""]
            if "comp_fired" in r:
                L += ["F12 요소별 청산 수(발동 / 혼자 발동, 비트 순서): " + ", ".join(f"{n} {r['comp_fired'][n]}/{r['comp_alone'][n]}" for n in MT.COMP_LABELS)]
                L += [f"  - {tf} 봉 {c['n_picks']}개: " + ", ".join(f"{n} {c['fired'][n]}/{c['alone'][n]}" for n in MT.COMP_LABELS)
                      for tf, c in (r.get("comp_by_tf") or {}).items()] + [""]
        L += [f"### {name}: 장세별 보유시간 (확인 기간 매매, 참고 정보이며 PASS/FAIL에 들어가지 않음)", ""]
        L += state_table_ko({"e0": e0, "variants": rows})
    if doc.get("late_messages") or extra_messages:
        L += ["## choice.json 해시 뒤에 받은 소유자 메시지 (아무것도 바꾸지 않음)", ""]
        L += [f"- {m}" for m in (doc.get("late_messages") or []) + list(extra_messages or [])] + [""]
    return "\n".join(L)


def stage_confirm(lay: Layout, procs: int, rerun: bool = False) -> dict:
    """The confirm run, once. A rerun (section 14, a bug found after a PASS) writes confirm_r2.json, REPORT_KO_r2.md and, privately,
    confirm_ds_r2.json and owner_report_confirm_r2.md; it needs confirm.json to exist. Needs select.json, SELECT_KO.md, timing.json,
    sent.json and choice.json (and choice_r2.json when it exists) pinned with their present hashes."""
    pin, ph = gate_pin(lay)
    for name in ("select.json", "SELECT_KO.md", "timing.json", "sent.json", "choice.json"):
        require_pinned_file(lay, lay.out_file(name), name)
    r2 = os.path.exists(lay.out_file("choice_r2.json"))
    if r2:
        for name in ("select_r2.json", "SELECT_KO_r2.md", "sent_r2.json", "choice_r2.json"):
            require_pinned_file(lay, lay.out_file(name), name)
    sel = json.load(open(lay.out_file("select_r2.json" if r2 else "select.json")))
    sent = json.load(open(lay.out_file("sent_r2.json" if r2 else "sent.json")))
    choice = json.load(open(lay.out_file("choice_r2.json" if r2 else "choice.json")))
    if choice.get("pin") != ph or sel.get("pin") != ph:
        refuse("select.json / choice.json were made under another pin")
    if not sel.get("complete_menu"):
        refuse("select.json was made without the complete menu of 88 variants")
    first = json.load(open(lay.out_file("choice.json")))
    bad = MT.validate_choice_doc(sel, choice, sent, first if r2 else None) + MT.material_problems(first)
    if bad:
        refuse("choice does not validate: " + "; ".join(bad))
    check_modules_unchanged(lay, sel)                                   # prereg 13: refuse before the confirm loads or computes anything
    if rerun:
        if not os.path.exists(lay.out_file("confirm.json")) or os.path.exists(lay.out_file("confirm_r2.json")):
            refuse("a confirm rerun needs confirm.json and runs once (confirm_r2.json exists or confirm.json is missing)")
        require_deviation_entry(lay, "confirm_r2")
    elif os.path.exists(lay.out_file("confirm.json")):
        refuse("confirm.json exists: the confirm runs once; a rerun is a section 14 matter (--rerun)")
    cfg = real_config(lay, "confirm_r2" if rerun else "confirm", pin, ph, procs, N_SEEDS_FULL)
    for vid in choice["core"] + choice["ds"]:
        KX.variant_by_id(vid)
    return finish_confirm(cfg, sel, choice)


# ------------------------------------------------------------------ real-data checks T1, T3, T5 (pass / fail and counts only)
MIDDLE_VARIANTS = ("F1.w3.a", "F1.w3.a.q15", "F2.n20.a", "F3.a", "F4.m2.a", "F4.m2.a.q15", "F5.P1.5.g25.a", "F6.w3.d0.5", "F7.N24.a",
                   "F7h.H8.a", "F8.w3.P1.a", "F9.a", "F9.a.q15", "F10.N6.a", "F11.a", "F11.b", "F12.a", "F12.b", "F13.a", "F13.b")
T3_CUTS = tuple(dt.datetime(y, m, 1, tzinfo=dt.timezone.utc) for y in (2021, 2022, 2023) for m in (2, 4, 6, 8, 10, 12)) + (
    dt.datetime(2022, 6, 15, 13, 37, tzinfo=dt.timezone.utc), dt.datetime(2023, 3, 17, 7, 5, tzinfo=dt.timezone.utc),
    dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc))


def kernel_account_for(cfg: Config, off: dict, pick: dict, scale: float) -> tuple:
    """research/fullgrid kernel.account on a pick's offered signals under its own exit (E0), the arrays to the data end."""
    m = cfg.market
    return K.account(m.S(scale), m.brs, m.cat["ts"], m.cat["o"], m.cat["h"], m.cat["l"], m.cat["mo"], m.cat["mh"], m.cat["ml"],
                     m.cat["fund"], m.starts, m.ends, off["coin"], off["close"], off["side"], off["atr"], off["best"],
                     m.qty_steps, m.min_notionals, *K.exit_args(pick["exit_index"]), np.full(len(off["coin"]), np.nan))


def check_t1(cfg: Config, picks: list | None = None) -> list:
    """T1 on the real cut arrays: for each pick, E0 through kernel_x (no rule, no forced close) equals kernel.account at both
    sizes - statuses, P&L, exit times, reasons, leverages, final wallet. Returns [(pick id, ok)]."""
    out = []
    for p in picks or cfg.picks:
        pdata = cfg.make_pickdata(p)
        off = pdata.offered(cfg.period)
        ok = True
        for scale in SIZES:
            st, pnl, ext, rs, lv, w = kernel_account_for(cfg, off, p, scale)
            r = KX.simulate(cfg.market, pdata, KX.E0, scale, cfg.period, force_end=False)
            ok &= bool(np.array_equal(st, r.status) and np.array_equal(pnl, r.pnl) and np.array_equal(ext, r.exit_ts)
                       and np.array_equal(rs, r.reason) and np.array_equal(lv, r.lev) and w == r.wallet)
        out.append((p["id"], ok))
        progress(f"[T1] {p['id']} {'pass' if ok else 'FAIL'}")
    return out


T3_CUT_PREFIX = "t3cut"


def t3_snapshot_side(pin_path: str, side: str, cut_ms: int, out_path: str) -> None:
    """One side of one T3 comparison, in its own process and with its own cache folder."""
    pin = DX.load_pin(pin_path)
    ph = DX.pin_sha(pin_path)
    name = f"t3-{DX.cut_name(cut_ms, T3_CUT_PREFIX)[len(T3_CUT_PREFIX) + 1:]}-{side}"
    cache = DX.fresh_stage(pin["work"], ph, name)
    if side == "cut":                                           # its own folder name (t3cut-...): never the select run's cut folder
        data_dir = DX.write_cut(pin["data_dir"], pin["work"], ph, cut_ms, prefix=T3_CUT_PREFIX)
    else:
        data_dir = pin["data_dir"]
    rprov = DX.RealProvider(data_dir, cache)
    prov11 = f11_provider_from_modules(rprov, *try_load_native())
    picks = DX.picks()
    snap = DX.snapshot(rprov, DX.SYMBOLS, cut_ms, picks, f11=prov11)
    if side == "cut":
        arrays = {s: {"ts": DX._load_npz(os.path.join(data_dir, "1m", f"{s}.npz"))["ts"]} for s in DX.SYMBOLS}
        DX.assert_no_minute_at_or_after(arrays, cut_ms)
        for k, v in snap.items():                               # the cut frames' last bar closes at or before the cut
            if k.endswith("|close_ms") and len(v) and int(v[-1]) > cut_ms:
                raise AssertionError(k)
    np.savez(out_path, **snap)
    import shutil
    shutil.rmtree(cache, ignore_errors=True)
    if side == "cut":
        assert os.path.basename(data_dir).startswith(T3_CUT_PREFIX + "-")
        shutil.rmtree(data_dir, ignore_errors=True)


def check_t3(lay: Layout, pin: dict, ph: str, cuts=T3_CUTS) -> list:
    """T3: at each cut time the cut arrays and the full arrays agree on the last 50 chart bars (21 cuts, each side in its own
    fresh process). Returns [(cut, ok)]."""
    out = []
    tmp = os.path.join(pin["work"], DX.pin8(ph), "t3-files")
    os.makedirs(tmp, exist_ok=True)
    for cut in cuts:
        cut_ms = int(cut.timestamp() * 1000)
        files = {}
        for side in ("cut", "full"):
            files[side] = os.path.join(tmp, f"{side}_{cut_ms}.npz")
            r = subprocess.run([sys.executable, os.path.join(HERE, "runner_x.py"), "t3-side", "--side", side, "--cut-ms", str(cut_ms),
                                "--out", files[side], "--pin", lay.pin_file], capture_output=True, text=True)
            if r.returncode != 0:
                progress(f"[T3] {cut:%Y-%m-%d %H:%M} {side} process failed")
                out.append((cut, False))
                break
        else:
            with np.load(files["cut"]) as a, np.load(files["full"]) as b:
                ka, kb = sorted(a.files), sorted(b.files)
                bad = ka != kb or any(not np.array_equal(a[k], b[k], equal_nan=True) for k in ka)
            out.append((cut, not bad))
            progress(f"[T3] {cut:%Y-%m-%d %H:%M} {'pass' if not bad else 'FAIL'}")
        for f in files.values():
            if os.path.exists(f):
                os.remove(f)
    return out


def perturbed_inputs(cfg: Config, pdata, v, off: dict, q: int, C: float, j: int, rng) -> tuple:
    """Kernel inputs of signal q with everything after the check changed: the coin's minute arrays from minute j on, the chart
    rows of bars closing after C, the swing flags that the bars after C would confirm, the components of those bars."""
    m = cfg.market
    c = int(off["coin"][q])
    a, b = int(m.starts[c]), int(m.period_end(cfg.period)[c])
    mins = {k: m.cat[k][a:b].copy() for k in ("o", "h", "l", "mo", "mh", "ml", "fund")}
    for k in ("o", "h", "l", "mo", "mh", "ml"):
        mins[k][j:] = mins[k][j:] * np.exp(rng.normal(0.0, 0.05, len(mins[k]) - j))
    mins["fund"][j:] = rng.normal(0.0, 5e-4, len(mins["fund"]) - j)         # step 0: nothing of minute j, its funding included, may enter the decision
    rp, PT, PF, QT, cst, cen, qst, qen = pdata.chart(v)
    PT_c, PF_c, QT_c = PT[cst[c]:cen[c]].copy(), PF[cst[c]:cen[c]].copy(), QT[qst[c]:qen[c]].copy()
    late = PT_c[:, KX.C_CMS] > C
    bi = int(np.argmax(late)) - 1 if late.any() else len(late) - 1
    n_late = int(late.sum())
    for col in (KX.C_CL, KX.C_ATR, KX.C_EMA, KX.C_LO, KX.C_HI, KX.C_SLO, KX.C_SHI):
        PT_c[late, col] = PT_c[late, col] * np.exp(rng.normal(0.0, 0.05, n_late))
    PF_c[late, KX.P_SIGL:] = rng.integers(0, 3, (n_late, KX.NPF - KX.P_SIGL)).astype(np.int8)
    wv = int(v.params.get("w", 0))
    unknown = np.arange(len(late)) > bi - wv if wv else np.zeros(len(late), bool)     # swings that the bars after C would confirm
    PF_c[unknown, KX.P_SWL:KX.P_SWH + 1] = rng.integers(0, 2, (int(unknown.sum()), 2)).astype(np.int8)
    PT_c[unknown, KX.C_LO] = PT_c[unknown, KX.C_LO] * np.exp(rng.normal(0.0, 0.05, int(unknown.sum())))
    PT_c[unknown, KX.C_HI] = PT_c[unknown, KX.C_HI] * np.exp(rng.normal(0.0, 0.05, int(unknown.sum())))
    if len(QT_c):
        ql = QT_c[:, KX.Q_CMS] > C
        QT_c[ql, KX.Q_CL] = QT_c[ql, KX.Q_CL] * np.exp(rng.normal(0.0, 0.05, int(ql.sum())))
    return mins, (PT_c, PF_c, QT_c)


def causality_pair(cfg: Config, pdata, v, off: dict, q: int, k: int | None, rng, plc: bool, hz) -> bool | None:
    """T5 on one (trade, check): the frozen decision state of every check up to and including the one at j is identical when
    everything from minute j on and everything closing after the check close is changed. None = the trade has no such check."""
    seed = int(rng.integers(0, 2 ** 31))
    out, _n, _d, tr = KX.simulate_trade(cfg.market, pdata, v, off, q, 0.25, cfg.period, True, plc, hz, seed, 8192)
    nchk = out[5]
    if nchk < 1:
        return None
    kk = nchk if k is None or k > nchk else k
    j, C = int(tr[kk - 1, 0]), float(tr[kk - 1, 1])
    mins, chart = perturbed_inputs(cfg, pdata, v, off, q, C, j, rng)
    out2, _n2, _d2, tr2 = KX.simulate_trade(cfg.market, pdata, v, off, q, 0.25, cfg.period, True, plc, hz, seed, 8192, minutes=mins, chart=chart)
    return bool(out2[5] >= kk and np.array_equal(tr[:kk], tr2[:kk], equal_nan=True))


def check_t5(cfg: Config, per_pool: int = 500, seed: int = 11) -> dict:
    """T5 on the real arrays: ``per_pool`` sampled (trade, check) pairs per pool over the families at their middle parameter
    and F11 in both modes. Returns {pool: (pairs checked, pairs failed)}."""
    rng = np.random.default_rng(seed)
    vs = [v for v in (KX.variant_by_id(i) for i in MIDDLE_VARIANTS if i in {x.id for x in cfg.variants})]
    res = {}
    for pool in cfg.pool_names():
        picks = cfg.pool_picks(pool)
        per = max(1, math.ceil(per_pool / (len(picks) * len(vs))))
        n = bad = 0
        for p in picks:
            pdata = cfg.make_pickdata(p)
            off = pdata.offered(cfg.period)
            if not len(off["coin"]):
                continue
            for v in vs:
                for _ in range(per):
                    q = int(rng.integers(0, len(off["coin"])))
                    for plc in ((False, True) if PL.has_placebo(v) else (False,)):
                        hz = np.where(rng.random((KX.N_AGE, 2, 2)) < 0.3, 0.0, rng.uniform(0.0, 0.2, (KX.N_AGE, 2, 2)))
                        kk = None if rng.random() < 0.3 else int(rng.integers(1, 40))
                        r = causality_pair(cfg, pdata, v, off, q, kk, rng, plc, hz)
                        if r is not None:
                            n += 1
                            bad += (not r)
        res[pool] = (n, bad)
        progress(f"[T5] {pool}: {n} pairs, {'pass' if bad == 0 and n >= per_pool else 'FAIL'}")
    return res


def label_causal_pair(reg, h: np.ndarray, l: np.ndarray, c: np.ndarray, i0: int, tf_min: int, label: int, rng) -> bool:
    """T8 causality on one signal bar: the label at bar ``i0`` is the same (a) from the arrays truncated at the signal bar, (b) when every
    bar after it is replaced by random values and (c) by extreme values. Booleans only."""
    n = len(c)
    ok = int(reg.regimes(h[:i0 + 1], l[:i0 + 1], c[:i0 + 1], tf_min)["code"][-1]) == label
    m = n - i0 - 1
    if m > 0:
        for kind in ("random", "extreme"):
            h2, l2, c2 = h.copy(), l.copy(), c.copy()
            if kind == "random":
                fac = np.exp(rng.normal(0.0, 0.3, m))
                c2[i0 + 1:] = c[i0 + 1:] * fac
                h2[i0 + 1:] = np.maximum(h[i0 + 1:] * fac, c2[i0 + 1:]) * (1 + np.abs(rng.normal(0.0, 0.05, m)))
                l2[i0 + 1:] = np.minimum(l[i0 + 1:] * fac, c2[i0 + 1:]) * (1 - np.abs(rng.normal(0.0, 0.05, m)))
            else:
                big = rng.random(m) < 0.5
                c2[i0 + 1:] = np.where(big, c[i0] * 50.0, c[i0] / 50.0)
                h2[i0 + 1:] = c2[i0 + 1:] * 1.5
                l2[i0 + 1:] = c2[i0 + 1:] / 1.5
            ok &= int(reg.regimes(h2, l2, c2, tf_min)["code"][i0]) == label
    return bool(ok)


def check_t8(cfg: Config, per_pool: int = 500, seed: int = 17) -> dict:
    """T8 (prereg 13) on the real arrays: ``per_pool`` sampled offered signals per pool; the market-state label of the signal does not change
    when every chart bar after the signal bar is replaced (random and extreme values), and the label from the arrays truncated at
    the signal bar equals the label from the full arrays. Returns {pool: (signals checked, signals failed)}; counts only."""
    rng = np.random.default_rng(seed)
    reg = DX.regime_module()
    res = {}
    for pool in cfg.pool_names():
        picks = cfg.pool_picks(pool)
        per = max(1, math.ceil(per_pool / len(picks)))
        n = bad = 0
        for p in picks:
            pdata = cfg.make_pickdata(p)
            off = pdata.offered(cfg.period)
            if not len(off["coin"]):
                continue
            for _ in range(per):
                q = int(rng.integers(0, len(off["coin"])))
                c, i0 = int(off["coin"][q]), int(off["i0"][q])
                df = pdata.frames[c][0]
                ok = label_causal_pair(reg, df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float), i0,
                                       DX.TF_MIN[pdata.tf], int(off["state"][q]), rng)
                n += 1
                bad += (not ok)
        res[pool] = (n, bad)
        progress(f"[T8] {pool}: {n} signals, {'pass' if bad == 0 and n > 0 else 'FAIL'}")
    return res


def stage_check(lay: Layout, which: list, picks_filter=None) -> bool:
    pin, ph = gate_pin(lay)
    ok = True
    cfg = None
    if any(x in which for x in ("t1", "t5", "t8")):
        cfg = real_config(lay, "check", pin, ph, 1, N_SEEDS_FULL, allow_no_f11=True)
    if "t1" in which:
        ok &= all(r for _p, r in check_t1(cfg, picks_filter))
    if "t5" in which:
        ok &= all(b == 0 and n > 0 for n, b in check_t5(cfg).values())
    if "t8" in which:
        ok &= all(b == 0 and n > 0 for n, b in check_t8(cfg).values())
    if "t3" in which:
        ok &= all(r for _c, r in check_t3(lay, pin, ph))
    progress(f"[check] {'pass' if ok else 'FAIL'}")
    return ok


# ------------------------------------------------------------------ audits A1-A8 (pass / fail only)
def audit_check_minutes(cfg: Config, pdata, v, res) -> bool:
    """A3: every RULE and RAND exit lies at the minute of one of the position's checks, at that minute's open with slippage."""
    m = cfg.market
    rp, PT, PF, QT, cst, cen, qst, qen = pdata.chart(v)
    q15 = bool(v.q15) and pdata.tf in ("1h", "4h")
    slip = m.S(res.scale)[1]
    for q in res.trades():
        if res.reason[q] not in (KX.R_RULE, KX.R_RAND):
            continue
        c = int(res.sig["coin"][q])
        tsc = m.ts(c)
        e = int(np.searchsorted(tsc, res.entry_ts[q]))
        j = int(np.searchsorted(tsc, res.exit_ts[q]))
        if not math.isclose(res.xpx[q], float(m.cat["o"][m.starts[c] + j]) * (1 - int(res.sig["side"][q]) * slip), rel_tol=1e-12):
            return False
        i0 = int(res.sig["i0"][q])
        if q15:
            rows = QT[qst[c]:qen[c]]
            mins = rows[rows[:, KX.Q_CMS] > PT[cst[c] + i0, KX.C_CMS], KX.Q_MIN]
        else:
            mins = PT[cst[c] + i0 + 1:cen[c], KX.C_MIN]
        mins = mins[mins >= 0]
        hi = int(np.searchsorted(mins, j, side="right"))
        ok = (hi > 0 and mins[0] <= e + 1) if j == e + 1 else (hi > 0 and int(mins[hi - 1]) == j)
        if not ok:
            return False
    return True


def audit_counts_and_wallet(cfg: Config, picks_vids: dict) -> tuple:
    """A2 and A4 over the step-1 files: signals offered = entered + skipped + rejected + no fill + after bust; the final wallet
    = $5,000 + the sum of the trades' wallet changes (1e-9 relative)."""
    a2 = a4 = True
    n = 0
    for pid, vids in picks_vids.items():
        p = cfg.by_id[pid]
        for arm in ["E0"] + list(vids):
            for s in SIZES:
                z = cfg.store.load(p, arm, SIZE_TAG[s])
                c = z["counts"]
                a2 &= int(c[0]) == int(c[1] + c[3] + c[4] + c[5] + c[6])
                w0, wend = float(z["w0"]), float(z["w_end"])
                a4 &= math.isclose(wend, w0 + float(np.sum(z["tr_pnl"])), rel_tol=1e-9)
                n += 1
    return a2, a4, n


def audit_f12_clock(market, pdata, res) -> bool:
    """A7 (F12): no F12 position is held past its clock check: the first pick-timeframe check at or after C0 + 8 hours (a check moves to e + 1
    when its minute is not after the fill). ``res`` = a rule or placebo account of an F12 variant."""
    hrs = KX.F12_PARAMS["H"] * 3_600_000
    for q in res.trades():
        c = int(res.sig["coin"][q])
        a, b = int(pdata.cst[c]), int(pdata.cen[c])
        closes = pdata.b_cms[a:b]
        k = int(np.searchsorted(closes, closes[int(res.sig["i0"][q])] + hrs, side="left"))
        if k >= len(closes) or pdata.b_min[a + k] < 0:
            continue                                                      # the clock check does not exist: the period end or the stops decide
        tsc = market.ts(c)
        e = int(np.searchsorted(tsc, res.entry_ts[q]))
        if int(np.searchsorted(tsc, res.exit_ts[q])) > max(int(pdata.b_min[a + k]), e + 1):
            return False
    return True


def audit_placebo_rates(cfg: Config, picks: list, vids: list) -> bool:
    """A7: each placebo's realised exit rate per stratum lies within a 99.9% binomial band around h (for F12 over the checks before its
    clock check: the kernel's counts leave the clock check out); no F12 placebo position is held past its clock check."""
    ok = True
    for p in picks:
        for vid in vids:
            if not cfg.store.has(p, vid, plc_tag(*seed_blocks(cfg.n_seeds)[0])):
                continue
            own = cfg.store.load(p, vid, SIZE_TAG[0.25])
            hz = PL.hazard(own["num"], own["den"])
            parts = [cfg.store.load(p, vid, plc_tag(s0, s1)) for s0, s1 in seed_blocks(cfg.n_seeds)]
            ok &= PL.audit_realised_rates(np.sum([x["num"] for x in parts], axis=0), np.sum([x["den"] for x in parts], axis=0), hz)
            v = KX.variant_by_id(vid)
            if v.fam == KX.F12:                                          # re-run two seeds of the placebo and look at the holds
                pdata = cfg.make_pickdata(p)
                for sd in range(2):
                    r = KX.simulate(cfg.market, pdata, v, 0.25, cfg.period, placebo=True, hz=hz, seed_base=PL.seed_base(vid, cfg.period, sd))
                    ok &= audit_f12_clock(cfg.market, pdata, r)
    return bool(ok)


def audit_e0_against_kernel(cfg: Config, picks: list) -> bool:
    """A6: E0 through kernel_x (with the forced period-end close) equals kernel.account on the same signals up to the position
    that the period end closes: every earlier trade is identical, and that one is the kernel's still-open trade."""
    ok = True
    for p in picks:
        pdata = cfg.make_pickdata(p)
        off = pdata.offered(cfg.period)
        for scale in SIZES:
            st, pnl, ext, rs, lv, w = kernel_account_for(cfg, off, p, scale)
            r = KX.simulate(cfg.market, pdata, KX.E0, scale, cfg.period, force_end=True)
            open_ = np.flatnonzero((st == 1) & (rs == K.R_OPEN))
            cut = int(open_[0]) if len(open_) else len(st)
            ok &= bool(np.array_equal(st, r.status) and np.array_equal(pnl[:cut], r.pnl[:cut]) and np.array_equal(ext[:cut], r.exit_ts[:cut]))
            if len(open_):
                ok &= bool(r.reason[cut] == KX.R_END)
    return bool(ok)


A8_SCOPE = ("select.json", "confirm.json", "sent.json", "choice.json", "SELECT_KO.md", "REPORT_KO.md", "select_r2.json", "SELECT_KO_r2.md",
            "sent_r2.json", "choice_r2.json", "confirm_r2.json", "REPORT_KO_r2.md")


def audit_a8_file(path: str, after: str | None = None) -> list:
    """A8 on one file before it is sent or committed (select, sent, choice, confirm, report, ledger print, rerun files, DEVIATIONS entries):
    the problems found, [] = pass. Tables: every DeepSeek row carries only the allowed fields; DeepSeek sections of the Korean reports show
    no money; free text (messages, questions, the freeze note, DEVIATIONS entries, prose): the tripwire of ``MT.audit_text``. ``after`` = a
    marker: only the text after its first occurrence is read (the entries of this study in a shared DEVIATIONS.md)."""
    name = os.path.basename(path)
    text = open(path, encoding="utf-8").read()
    if after and after in text:
        text = text.split(after, 1)[1]
    bad = []
    if name.endswith(".json"):
        doc = json.loads(text)
        if name.startswith("select"):
            bad += MT.d11_problems(select_doc=doc)
        elif name.startswith("confirm"):
            bad += MT.d11_problems(confirm_doc=doc)
        bad += ["free text: " + ln[:60] for ln in MT.audit_text("\n".join(MT.json_strings(doc)))]
    else:
        if name.startswith("SELECT_KO"):
            bad += MT.d11_problems(select_md=text)
        elif name.startswith("REPORT_KO"):
            bad += MT.d11_problems(report_md=text)
        bad += ["free text: " + ln[:60] for ln in MT.audit_text(text)]
    return bad


def audit_a9_file(path: str) -> list:
    """A9 on one file: the state counts of every row sum to its closed trades (select.json, confirm.json); the state tables printed in a Korean
    report equal its json's (SELECT_KO.md against select.json, REPORT_KO.md against confirm.json in the same folder)."""
    name, folder = os.path.basename(path), os.path.dirname(path)
    bad = []
    if name.endswith(".json") and name.startswith(("select", "confirm")):
        doc = json.load(open(path, encoding="utf-8"))
        rows = []
        for pool, P in (doc.get("pools") or {}).items():
            rows += [(f"{pool}/E0", P["e0"])] + [(f"{pool}/{r['id']}", r) for r in P["variants"]]
        rows += list((doc.get("pairs") or {}).items()) + [(f"{k}/E0", r) for k, r in (doc.get("e0") or {}).items()]
        for label, r in rows:
            if "hold_by_state" in r and "closed" in r and sum(c["n"] for c in r["hold_by_state"].values()) != r["closed"]:
                bad.append(f"{label}: state counts do not sum to the closed trades")
    elif name.endswith(".md") and name.startswith(("SELECT_KO", "REPORT_KO")):
        sfx = "_r2" if name.endswith("_r2.md") else ""
        md_lines = {ln.strip() for ln in open(path, encoding="utf-8").read().splitlines()}
        if name.startswith("SELECT_KO"):
            doc = json.load(open(os.path.join(folder, f"select{sfx}.json"), encoding="utf-8"))
            tables = [state_table_ko(P) for P in doc["pools"].values()]
        else:
            doc = json.load(open(os.path.join(folder, f"confirm{sfx}.json"), encoding="utf-8"))
            tables = [state_table_ko({"e0": doc["e0"][pool], "variants": [r for r in doc["pairs"].values() if r["pool"] == pool]}) for pool in doc["e0"]]
        for t in tables:
            if not all(ln.strip() in md_lines for ln in t if ln.strip()):
                bad.append(f"{name}: a state table differs from the json's counts")
    return bad


def audit_a8(lay: Layout, stage: str, work: str, pin_hash: str) -> bool:
    """A8 for a stage: every file of the scope that exists passes ``audit_a8_file``; and the stage's private owner report exists under
    $WORK/<pin8>/ds_private/ (``_r2`` for a rerun), its sha256 equals ``ds_owner_report_sha256`` in the stage's json, it lies outside the
    repository, git lists no owner_report file, no committed file contains a line of it, it holds no p value and its last line asks the
    owners to name variants by id."""
    import re
    jname = "select.json" if stage == "select" else "confirm.json"
    ok = True
    for name in A8_SCOPE:
        if os.path.exists(lay.out_file(name)):
            ok &= not audit_a8_file(lay.out_file(name))
    doc = json.load(open(lay.out_file(jname)))
    rp = os.path.join(work, DX.pin8(pin_hash), "ds_private", f"owner_report_{stage}.md")
    want = doc.get("ds_owner_report_sha256")
    if want is not None or os.path.exists(rp):
        ok &= os.path.exists(rp) and sha256_file(rp) == want
        ok &= os.path.commonpath([os.path.abspath(rp), os.path.abspath(lay.root)]) != os.path.abspath(lay.root)
        if os.path.exists(rp):
            text = open(rp, encoding="utf-8").read()
            ok &= re.search(r"\bp\s*[=<>]|p값|p-value", text, re.I) is None
            ok &= bool(text.strip()) and text.strip().splitlines()[-1].strip() == OWNER_REPORT_LAST_LINE
            lines = {ln.strip() for c in A8_SCOPE if os.path.exists(lay.out_file(c)) for ln in open(lay.out_file(c), encoding="utf-8").read().splitlines()}
            ok &= not any(len(ln.strip()) >= 20 and re.search(r"[0-9A-Za-z가-힣]", ln) and ln.strip() in lines for ln in text.splitlines())
    try:
        tracked = subprocess.run(["git", "-C", lay.root, "ls-files"], capture_output=True, text=True, timeout=60).stdout.split("\n")
        ok &= not any("owner_report_" in t for t in tracked)
    except Exception:  # noqa: BLE001
        pass
    return bool(ok)


def audit_a9(cfg: Config, picks_vids: dict) -> bool:
    """A9: the market-state columns are consistent. Every closed trade has exactly one state (a code 0-4); per arm the state counts sum
    to the closed trades; E0 and each variant give the same label to the same signal (same coin, side, fill minute); no label
    differs from a recomputation of regime5y.regimes on the stage's arrays at the signal bar."""
    ok = True
    reg = DX.regime_module()
    for pid, vids in picks_vids.items():
        p = cfg.by_id[pid]
        e0 = cfg.store.load(p, "E0", SIZE_TAG[0.25])
        key0 = {k: int(st) for k, st in zip(zip(e0["tr_coin"].tolist(), e0["tr_side"].tolist(), e0["tr_fill"].tolist()), e0["tr_state"].tolist())}
        for arm in ["E0"] + list(vids):
            z = cfg.store.load(p, arm, SIZE_TAG[0.25])
            st = z["tr_state"]
            ok &= bool(np.all((st >= 0) & (st <= 4))) and int(np.bincount(st, minlength=5).sum()) == len(st) == int(z["counts"][MT.COUNT_NAMES.index("entered")])
            for k, s_ in zip(zip(z["tr_coin"].tolist(), z["tr_side"].tolist(), z["tr_fill"].tolist()), st.tolist()):
                if k in key0 and key0[k] != int(s_):
                    ok = False
        pdata = cfg.make_pickdata(p)
        off = pdata.offered(cfg.period)
        for c in range(len(cfg.market.symbols)):
            df = pdata.frames[c][0]
            code = reg.regimes(df["high"].to_numpy(float), df["low"].to_numpy(float), df["close"].to_numpy(float), DX.TF_MIN[pdata.tf])["code"]
            sel = off["coin"] == c
            ok &= bool(np.array_equal(off["state"][sel], code[off["i0"][sel]].astype(np.int8)))
    return bool(ok)


def audit_a5(cfg: Config, pin: dict, pin_hash: str, stage: str) -> bool:
    """A5 (select only): no array the select process loaded holds a minute at or after 2024-01-01: the cut folder's digests match, none of
    its arrays holds such a minute, and the market loaded from it holds none (the cut folder is made by a separate process, ``make-cut``).
    Not applicable to the confirm."""
    if stage != "select":
        return True
    try:
        folder = DX.open_cut(pin["work"], pin_hash, DX.SELECT_CUT_MS)
        DX.assert_no_minute_at_or_after({s: {"ts": cfg.market.ts(i)} for i, s in enumerate(cfg.market.symbols)}, DX.SELECT_CUT_MS)
    except (DX.PinError, AssertionError):
        return False
    return os.path.abspath(cfg.market.data_dir or "") == os.path.abspath(folder)


def stage_audit(lay: Layout, stage: str, procs: int = 1) -> bool:
    """A1-A9 after a select or confirm run, pass or fail only."""
    pin, ph = gate_pin(lay)
    cfg = real_config(lay, "select" if stage == "select" else "confirm", pin, ph, procs, N_SEEDS_FULL)
    sel = json.load(open(lay.out_file("select.json")))
    cfg.n_seeds = int(sel["n_seeds"]) if stage == "select" else N_SEEDS_FULL
    res = {}
    if stage == "select":
        pv = {p["id"]: [v.id for v in cfg.variants] for p in cfg.picks}
    else:
        ch = json.load(open(lay.out_file("choice_r2.json" if os.path.exists(lay.out_file("choice_r2.json")) else "choice.json")))
        pv = {p["id"]: ch[p["pool"]] for p in cfg.picks if ch.get(p["pool"])}
    a2, a4, n = audit_counts_and_wallet(cfg, pv)
    res["A2"], res["A4"] = a2, a4
    res["A5"] = audit_a5(cfg, pin, ph, stage)
    res["A6"] = audit_e0_against_kernel(cfg, [p for p in cfg.picks if p["id"] in pv][:])
    res["A7"] = audit_placebo_rates(cfg, [p for p in cfg.picks if p["id"] in pv], sorted({v for vs in pv.values() for v in vs}))
    a3 = True
    for p in [p for p in cfg.picks if p["id"] in pv]:
        pdata = cfg.make_pickdata(p)
        for vid in pv[p["id"]]:
            v = KX.variant_by_id(vid)
            a3 &= audit_check_minutes(cfg, pdata, v, KX.simulate(cfg.market, pdata, v, 0.25, cfg.period))
    res["A3"] = bool(a3)
    res["A8"] = audit_a8(lay, stage, pin["work"], ph)
    res["A9"] = audit_a9(cfg, pv) and not any(audit_a9_file(lay.out_file(n)) for n in A8_SCOPE if os.path.exists(lay.out_file(n)))
    t = subprocess.run([sys.executable, "-m", "pytest", "-q", os.path.join(HERE, "test_exitflex.py")], capture_output=True, text=True)
    res["A1"] = t.returncode == 0
    for k in sorted(res):
        progress(f"[audit {stage}] {k} {'pass' if res[k] else 'FAIL'}")
    return all(res.values())


# ------------------------------------------------------------------ command line
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    mp = sub.add_parser("make-pin")
    mp.add_argument("--data-dir", required=True)
    mp.add_argument("--work", required=True)
    mp.add_argument("--out", default=None)
    sub.add_parser("pin-lines")
    sub.add_parser("make-cut", help="write the select cut data folder (in its own process; the select process only opens it)")
    sub.add_parser("timing")
    for name in ("select", "report", "confirm"):
        sp = sub.add_parser(name)
        sp.add_argument("--procs", type=int, default=max(1, (os.cpu_count() or 2)))
    sub.choices["confirm"].add_argument("--rerun", action="store_true", help="section 14: confirm_r2.json, REPORT_KO_r2.md")
    sub.choices["select"].add_argument("--rerun", action="store_true", help="section 14: a fresh stage select_r2 (select_r2.json, SELECT_KO_r2.md)")
    ch = sub.add_parser("choice")
    ch.add_argument("--input", required=True, help="JSON: messages [{time_utc, text, answers{core, ds}}], questions [{time_utc, text, pools}], "
                    "material_received [text], freeze_breaches [text]")
    ch.add_argument("--now-utc", default=None)
    ch.add_argument("--rerun", action="store_true", help="section 14: choice_r2.json against select_r2.json / sent_r2.json")
    cr = sub.add_parser("confirm-report", help="rewrite out/REPORT_KO.md from confirm.json (no recomputation)")
    cr.add_argument("--extra-messages", default=None, help="JSON list of owner messages received after choice.json was hashed")
    ck = sub.add_parser("check")
    ck.add_argument("--which", default="t1,t3,t5,t8")
    af = sub.add_parser("audit-file", help="A8 and A9 on files before they are sent or committed (pass / fail only)")
    af.add_argument("--path", action="append", required=True)
    af.add_argument("--after", default=None, help="read only the text after this marker (the entries of this study in a shared DEVIATIONS.md)")
    au = sub.add_parser("audit")
    au.add_argument("--stage", choices=("select", "confirm"), required=True)
    t3 = sub.add_parser("t3-side")
    t3.add_argument("--side", choices=("cut", "full"), required=True)
    t3.add_argument("--cut-ms", type=int, required=True)
    t3.add_argument("--out", required=True)
    t3.add_argument("--pin", default=None)
    a = ap.parse_args(argv)
    lay = Layout()
    if a.cmd == "make-pin":
        target = a.out or lay.pin_file
        if os.path.exists(lay.sha_file) and os.path.normpath(os.path.abspath(target)) in read_sha_file(lay):
            refuse(f"{os.path.basename(target)} is already listed in {os.path.basename(lay.sha_file)}: a pinned data pin is not overwritten")
        doc = DX.make_pin(a.data_dir, a.work)
        write_json(target, doc)
        progress(f"[make-pin] wrote {a.out or lay.pin_file}; build.json {doc['build_json_sha256'][:8]}, coins "
                 + ", ".join(f"{k[:3]} {v[:8]}" for k, v in doc["coins"].items()))
    elif a.cmd == "pin-lines":
        print("\n".join(pin_lines(lay)))
    elif a.cmd == "make-cut":
        stage_make_cut(lay)
    elif a.cmd == "timing":
        stage_timing(lay)
    elif a.cmd == "select":
        stage_select(lay, a.procs, a.rerun)
        progress("[select] done: out/select" + ("_r2" if a.rerun else "") + ".json and its Korean report")
    elif a.cmd == "report":
        stage_report(lay, a.procs)
    elif a.cmd == "choice":
        stage_choice(lay, a.input, a.now_utc, a.rerun)
    elif a.cmd == "confirm-report":
        extra = json.load(open(a.extra_messages, encoding="utf-8")) if a.extra_messages else None
        with open(lay.out_file("REPORT_KO.md"), "w", encoding="utf-8") as fh:
            fh.write(confirm_report_ko(json.load(open(lay.out_file("confirm.json"))), extra))
    elif a.cmd == "confirm":
        stage_confirm(lay, a.procs, a.rerun)
        progress("[confirm] done: out/confirm" + ("_r2" if a.rerun else "") + ".json and its report")
    elif a.cmd == "check":
        return 0 if stage_check(lay, a.which.split(",")) else 1
    elif a.cmd == "audit-file":
        ok = True
        for pth in a.path:
            b8, b9 = audit_a8_file(pth, a.after), audit_a9_file(pth)
            ok &= not b8 and not b9
            progress(f"[audit-file] {os.path.basename(pth)} A8 {'pass' if not b8 else 'FAIL'} A9 {'pass' if not b9 else 'FAIL'}")
        return 0 if ok else 1
    elif a.cmd == "audit":
        return 0 if stage_audit(lay, a.stage) else 1
    elif a.cmd == "t3-side":
        t3_snapshot_side(a.pin or lay.pin_file, a.side, a.cut_ms, a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
