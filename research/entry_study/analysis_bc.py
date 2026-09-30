"""Entry study parts B (entry strength) and C (parameter sensitivity): PREREG_ENTRY.md sections 1, 3 and 4
(fixed, hash in PREREG_ENTRY.sha256). The per-strategy definitions are locked in strength_defs/<NAME>.py and
param_defs/<NAME>.py, hashes in DEFS_BC.sha256: every hash is checked before anything runs, and each definition
file again (the exact bytes that are executed) when it is loaded. Any difference refuses the run.

    python3 research/entry_study/analysis_bc.py run B|C|all [procs] [--only NAME,...] [--tfs 5m,15m,...]
    python3 research/entry_study/analysis_bc.py jobs B|C|all [procs] [...]        # stage 1 only (checkpoints)
    python3 research/entry_study/analysis_bc.py aggregate B|C|all [procs] [...]   # stage 2 only (from checkpoints)

procs defaults to 3. --only / --tfs restrict the run (a pilot); the outputs of a restricted run go to the scratch
directory (RUN_DIR/out_subset), never to out/, because its BH family is not the pre-registered one.

Shared machinery is part A's (analysis_sr.py, imported, behaviour unchanged): the series (paper_rules signal cache
+ volume joined by ts for periods 1 / 2, the pre2021 cache for period 3), period windows (period_bounds: open time
in the period, i >= warm-up, a next bar exists), the random-entry bars (random_bars: min(20,000, eligible) bars,
seed [20260930, tf minutes, coin index, period]), the paper v3 outcome per (bar, side) (outcomes: profiles._sizer /
profiles._scan, look-ahead passes 64 / 512 / 4096 / 32,768; a trade counts only if sized and closed), the
Monday-UTC week blocks (sr.period_key), the week-block bootstrap draws (boot_counts, 2,000 resamples) and BH.

Stage 0, bases (one per timeframe x coin x source, cached in RUN_DIR/base): the bars (ts, o, h, l, c, v, atr), the
36 locked signals, the period windows, the random-entry bars and sides, and the outcome of every distinct
(bar, side) pair among the 36 strategies' signals and the random entries (the 'default outcomes').
Stage 1, jobs (one per strategy x timeframe x coin and part, checkpointed in RUN_DIR/ckpt/<part>; a killed run
resumes from the finished checkpoints):
  B  strength(df, tf) of strength_defs/<NAME>.py on the series the signal came from; per signal the value of the
     side it trades (long array for side +1, short array for side -1) and its outcome; the same for the random
     entries (value of the random side).
  C  (15m / 1h / 4h; strategies with EXCLUDED_REASON are skipped) the locked signal as the default, each variant's
     signals() computed once per series (one parameter at a time, x0.5 / x0.75 / x1.25 / x1.5 from variants());
     default signals() is compared with the locked signal (post warm-up) on every series and any mismatch
     excludes the strategy from C on every timeframe (PREREG 4). Outcomes of variant pairs that are not default
     pairs are computed with the same outcome machinery.
Stage 2, aggregation (pooled over coins, per strategy x timeframe):
  B  cell = strategy x timeframe, tested if >= 300 period-1 signal bars pooled over coins (as part A); per
     feature: Spearman rho(signed feature, ROE), the feature multiplied by -1 when higher_is_stronger is False so
     that 'stronger' = higher; one-sided p (H1: rho > 0) by week-block bootstrap: the W weeks with >= 1 trade
     (finite value) are resampled W times with replacement, rho recomputed exactly on the resampled trades
     (mid-ranks with multiplicities), p = (1 + #{rho_b <= 0 or undefined}) / (2,000 + 1); 'insufficient' when
     < 30 trades have a finite value in the period (period 1: p = 1 in BH). BH at FDR 10% over all B tests.
     Period 2: rho > 0 and p < 0.05. Period 3: rho > 0 when >= 30 trades with a finite value there, else
     'no data' (part A's period-3 rule: >= 30 trades).
     Candidate = passes all three. Random null: the same test on the random entries; 'random shows the same
     effect' when its period-1 rho has the strategy's sign with one-sided p < 0.05 in that direction.
     Descriptive: quintiles of the signed feature with period-1 edges applied to all periods.
  C  per variant and period: signals, trades, mean ROE per trade, week-block bootstrap SE (2,000); per parameter
     the period-1 shape ('flat': all four variants within +-1 SE of the default; 'spike': the default beats both
     neighbours x0.75 and x1.25 by > 2 SE; else 'smooth'); variants with mean ROE > 0 in all three periods and,
     for every variant with trades in all three periods, the probability that random entries with the same trade
     counts (per period and coin) show mean ROE > 0 in all three periods (2,000 draws from the random-entry
     trades), their sum (expected number by chance) next to the count, and a descriptive no-edge probability with
     the variant's own week clustering (its weeks resampled, centred on the random-entry mean). No variant is
     adopted.
Outputs (out/): bc_B_cells.csv, bc_B_quintiles.csv, bc_B_random.csv, bc_C_variants.csv, bc_C_shapes.csv,
bc_candidates.json, bc_trials.csv (one row per B test and per C variant), bc_run_meta.json.

Staleness guards: CODE_HASH (sha256 of this file, analysis_sr, sr, profiles, rules_bt, the paperbot modules they run,
the sweep lock manifest and DEFS_BC.sha256, plus numpy / pandas versions; taken once at import, inherited by the
forked workers) is stored in every base and enters every checkpoint signature together with the current source-file
fingerprints, so a code or data change recomputes what it touches. DEFS_BC.sha256 itself is pinned to the version
committed in 520dad0. 'aggregate' refuses when a base is stale, and the other part's saved aggregation is merged
into the outputs only when its code hash, checkpoint signatures and selection match this invocation.
"""

from __future__ import annotations

import os

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):   # one BLAS thread per process:
    os.environ.setdefault(_v, "1")                                           # Pool(procs) = procs cores

import hashlib  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import pickle  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import warnings  # noqa: E402
from multiprocessing import Pool  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import analysis_sr as A  # noqa: E402  (sets SWEEP_DATA and sys.path; imports sr, profiles, rules_bt, sweepsig)

warnings.filterwarnings("ignore")

sr, PR, RB, sweepsig = A.sr, A.PR, A.RB, A.sweepsig
bh, boot_counts, period_bounds, random_bars = A.bh, A.boot_counts, A.period_bounds, A.random_bars
PERIODS, SOURCES, COINS, TFS = A.PERIODS, A.SOURCES, A.COINS, A.TFS
BOOT_B, BOOT_SEED, RANDOM_N, RANDOM_SEED = A.BOOT_B, A.BOOT_SEED, A.RANDOM_N, A.RANDOM_SEED
MIN_SIGNALS, FDR_Q, CONFIRM_ALPHA = A.MIN_SIGNALS, A.FDR_Q, A.CONFIRM_ALPHA

# ------------------------------------------------------------------ fixed by the PREREG / task
ROOT = A.ROOT
RUN_DIR = f"{A.SCR}/entry_study/bc_run"
BASE_DIR = os.path.join(RUN_DIR, "base")
CKPT_DIR = os.path.join(RUN_DIR, "ckpt")
AGG_DIR = os.path.join(RUN_DIR, "agg")
SUBSET_OUT = os.path.join(RUN_DIR, "out_subset")
OUT = os.path.join(HERE, "out")          # fixed here: analysis_sr.OUT can be redirected ($SR_OUT) for its re-runs
DEFS_SHA = os.path.join(HERE, "DEFS_BC.sha256")
TFS_B = TFS
TFS_C = ("15m", "1h", "4h")
PARTS = ("B", "C")
MULTS = (0.5, 0.75, 1.25, 1.5)
NEIGHBOURS = (0.75, 1.25)
MIN_TRADES = 30           # trades with a finite value needed for a p-value / a period-3 verdict in a period
RANDOM_ALPHA = 0.05       # 'random shows the same effect'
FLAT_SE, SPIKE_SE = 1.0, 2.0
QUANTS = (0.2, 0.4, 0.6, 0.8)
MIN_QUINTILE_TRADES = 5
RANDOM_CODE = 1000        # bootstrap unit code of a strategy's random null = 1000 + strategy index
SEED_PART = {"B": 2, "C_se": 3, "C_random": 4, "C_noedge": 5}
CHUNK_ELEMS = 4_000_000   # (resamples x trades) per vectorised bootstrap chunk
VERSION = "analysis_bc v2"
BASE_VERSION = "bc base v2"
DEFS_BC_COMMIT = "520dad0"
# DEFS_BC.sha256 as committed in 520dad0 (the manifest itself is pinned: re-hashing a line in it is refused)
DEFS_BC_MANIFEST_SHA256 = "185dbcf858e93f694d0775e12925c1904373d0db002a4df7bf3cfcefa3d56044"
OC_COLS = ("ok", "lev", "sized", "done", "roe", "held", "reason", "mfe")
AMBIGUITIES = (
    "Minimum sample (PREREG 1) as in part A: '>= 300 period-1 signals' = signal bars of the strategy x timeframe "
    "pooled over coins, counted before sizing. A p-value in a period needs >= 30 trades with a finite feature value; "
    "fewer -> 'insufficient' (a period-1 'insufficient' test enters the BH family with p = 1).",
    "Spearman rho = Pearson correlation of mid-ranks (ties averaged). The feature is multiplied by -1 when "
    "higher_is_stronger is False, so every test is one-sided H1: rho > 0. Bootstrap: the W weeks (Monday 00:00 UTC, "
    "sr.period_key of the signal bar) with >= 1 trade with a finite value, pooled over coins, are drawn W times with "
    "replacement (analysis_sr.boot_counts); rho is recomputed exactly on the resampled trades (a trade drawn k times "
    "counts k times in the ranks); p = (1 + #{rho_b <= 0 or undefined}) / 2001.",
    "A trade enters B and C only if it was sized and closed before the data end (part A's rule). Signals whose "
    "feature value is NaN (indicator warm-up or undefined, as the locked definition returns it) are left out of "
    "that feature's test and counted in n_signals_nan.",
    "Period 3 (PREREG 1: 'same direction'): judged only when >= 30 trades with a finite feature value, pooled over "
    "coins, fall in period 3 (part A's period-3 rule of >= 30 trades, and B's own period-2 minimum); fewer, or an "
    "undefined rho, is 'no data'. The verdict uses the sign of rho only. (A first draft gated on >= 100 period-3 "
    "signal bars, which is not in the PREREG and let 9 tested 4h cells with 2 to 25 period-3 trades get a verdict; "
    "replaced before any full-run result was computed.)",
    "B random null: part A's random entries (same bars and sides, same seed rule) with the value of the random side "
    "from the same strength() arrays (for DOGE the locked long array holds the short-rule value on short-rule bars) "
    "and the same test pooled over coins. 'Random shows the same effect' = the random period-1 rho has the "
    "strategy's period-1 sign with one-sided p < 0.05 in that direction (unadjusted), as part A.",
    "B quintiles (descriptive): edges = numpy linear 20/40/60/80 % quantiles of the signed feature over period-1 "
    "trades pooled over coins (>= 5 trades), applied to all periods; a value equal to an edge goes to the upper "
    "quintile, so discrete features can leave quintiles empty. Quintile 5 = strongest.",
    "C unit = strategy x timeframe x variant pooled over coins (the PREREG's cell 'strategy x timeframe'); mean ROE "
    "per trade over sized and closed trades; SE = standard deviation (ddof 1) of 2,000 week-block bootstrap means "
    "(weeks with >= 1 trade of that variant and period, pooled over coins).",
    "C shape: '+-1 SE' and '2 SE' use the default's period-1 SE. 'flat' needs all four variants to have period-1 "
    "trades; 'spike' = default mean - mean(x0.75) > 2 SE and default mean - mean(x1.25) > 2 SE; a shape is given only "
    "when the cell meets the PREREG 1 minimum (>= 300 default period-1 signals) and the default SE is defined, "
    "else 'insufficient'.",
    "C 'variants with mean ROE > 0 in all three periods' counts the 4 variants per parameter (not the default); a "
    "period without trades counts as not > 0. The random probability (prob_random_all3) is computed for every "
    "variant and default with >= 1 trade in each period, passing or not: each of 2,000 draws takes, per period and "
    "coin, as many trades as the variant had, with replacement, from that coin's random-entry trades of the period "
    "(same timeframe); probability = share of draws whose pooled mean is > 0 in all three periods "
    "(prob_random_all3_k = the number of such draws; when it is 0 the probability is reported as '< 1/2000' with "
    "prob_random_all3_upper = 1/2001, the draw resolution, not a confidence bound). The sum of these probabilities "
    "over the variants is the expected number of variants positive in all three periods by chance, reported next "
    "to the observed count (all cells, and cells meeting the PREREG 1 minimum).",
    "The random-entry probability treats the trades as independent (random entries have random sides, so random "
    "trades are nearly independent; week-matched random draws agree: review check on the pilot with its own seeds, "
    "N17_KC_RSI 4h rsi_level x1.5 iid 0.0045, week-matched 0.0035). A strategy's own trades are week-clustered "
    "(review check on the pilot: week-block SE 1.4 to 2.6 x the iid SE), so it is a lower bound on the chance that a "
    "no-edge variant with the strategy's clustering is positive in all three periods. Descriptive "
    "prob_noedge_block_all3 adds that case: per period the variant's own weeks are resampled "
    "(analysis_sr.boot_counts, 2,000) on roe - mean(roe) + mu0, mu0 = the random-entry mean of the period weighted "
    "by the variant's trades per coin; share of draws with pooled mean > 0 in all three periods "
    "(pilot outputs, N17_KC_RSI 4h rsi_level x1.5: prob_noedge_block_all3 0.0265 against prob_random_all3 0.004 = "
    "8/2000; summed over the pilot's 128 variants 0.132 against 0.005). Neither is a test and neither adopts "
    "anything.",
    "C variants use the same warm-up (sweep_lib.warmup_bars) and period windows as the locked signals; a variant "
    "with a longer look-back gets no extra warm-up. Variants equal to the default (a length that rounds to the same "
    "value) are kept as trials; changed_signal_bars shows it. A variant with no signal is kept with zero trades.",
    "C default = the cached locked signal. param_defs signals() with no override is compared with it on every "
    "series after warm-up; a mismatch on any coin or timeframe excludes the strategy from C on every timeframe, "
    "with the reason (PREREG 4: 'that strategy is removed from C'). A restricted run (--tfs) only sees the "
    "timeframes it selects, so its exclusions can miss a mismatch on another timeframe; the full run checks all "
    "three.",
    "The PREREG's trial ledger is out/trials.csv; parts B and C write out/bc_trials.csv (one row per B test of a "
    "tested cell and per C variant).",
    "Locks and staleness: DEFS_BC.sha256 must hash to the version committed in 520dad0 (pinned in the code and "
    "compared with git when git is available), and every definition file to its manifest line. Bases and "
    "checkpoints carry CODE_HASH (the analysis and outcome code, see the module docstring) and the current source "
    "fingerprints (name, size, mtime); anything built under another hash or on other data is recomputed, "
    "'aggregate' refuses stale bases, outputs are not written when a source file changed during the run, and a part "
    "not recomputed in this invocation enters the outputs only from a saved aggregation with the same code hash, "
    "checkpoint signatures and selection (else its bc_B_* / bc_C_* files are removed and the run meta says so).",
)

# ------------------------------------------------------------------ the code that runs (staleness guard)
_DEP_FILES = (os.path.abspath(__file__), A.__file__, sr.__file__, PR.__file__, RB.__file__, sweepsig.__file__,
              *(os.path.join(ROOT, "paperbot", f) for f in ("sizing.py", "ladder.py", "margin.py", "config.py",
                                                            "sigservice.py")),
              os.path.join(sweepsig.ROOT, "PREREG.sha256"), DEFS_SHA)


def _hash_code(files=_DEP_FILES) -> tuple[str, dict]:
    """(sha256 over the bytes of the analysis and outcome code, the two lock manifests, which pin the locked signal
    code and the B / C definitions, and the numpy / pandas versions; {relative path: sha256} of the same bytes)."""
    h, per = hashlib.sha256(), {}
    for p in files:
        rel = os.path.relpath(os.path.abspath(p), ROOT)
        with open(p, "rb") as fh:
            data = fh.read()
        h.update(rel.encode() + b"\0" + data + b"\0")
        per[rel] = hashlib.sha256(data).hexdigest()
    h.update(f"numpy {np.__version__} pandas {pd.__version__}".encode())
    return h.hexdigest(), per


def _code_hash(files=_DEP_FILES) -> str:
    return _hash_code(files)[0]


CODE_HASH, CODE_FILES = _hash_code()   # read once at import: forked Pool workers inherit it, so a file edited during
                                       # a run leaves its outputs tagged with the old hash and the next run recomputes


def _lib():
    return A._lib()


def strategy_names(L=None) -> list[str]:
    return A.strategy_names(L or _lib())


# ------------------------------------------------------------------ locked definitions (hash-checked)
def read_manifest(path: str = DEFS_SHA) -> dict[str, str]:
    """{relative path: sha256} from a sha256sum-style file."""
    out = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            h, rel = line.split(None, 1)
            out[rel.strip().lstrip("*")] = h.lower()
    return out


def verify_defs(names=None, manifest: str = DEFS_SHA, base_dir: str = HERE,
                manifest_sha: str | None = DEFS_BC_MANIFEST_SHA256) -> dict:
    """Check the manifest itself against the pinned hash (the version committed in 520dad0; None skips it, for tests
    on temporary manifests), every file of the manifest against its locked hash and that each of `names` has both
    files listed."""
    man_act = A._sha256(manifest) if os.path.exists(manifest) else None
    man_ok = manifest_sha is None or man_act == manifest_sha
    exp = read_manifest(manifest) if man_act is not None else {}
    files = []
    for rel, h in sorted(exp.items()):
        p = os.path.join(base_dir, rel)
        act = A._sha256(p) if os.path.exists(p) else None
        files.append(dict(path=rel, expected=h, actual=act, ok=act == h))
    missing = [f"{kind}/{nm}.py" for nm in (names or []) for kind in ("strength_defs", "param_defs")
               if f"{kind}/{nm}.py" not in exp]
    ok = man_ok and bool(files) and all(f["ok"] for f in files) and not missing
    return dict(manifest=os.path.relpath(manifest, ROOT) if manifest.startswith(ROOT) else manifest,
                manifest_sha256=man_act, manifest_sha256_pinned=manifest_sha, manifest_ok=man_ok,
                files_checked=len(files), ok=ok, mismatched=[f for f in files if not f["ok"]],
                not_in_manifest=missing)


def require_defs(names=None, manifest: str = DEFS_SHA, base_dir: str = HERE,
                 manifest_sha: str | None = DEFS_BC_MANIFEST_SHA256) -> dict:
    r = verify_defs(names, manifest, base_dir, manifest_sha)
    if not r["ok"]:
        bad = ([f"manifest {r['manifest']}: {r['manifest_sha256']} != pinned {manifest_sha} (the version committed "
                f"in {DEFS_BC_COMMIT}; the manifest must not be edited or re-hashed)"] if not r["manifest_ok"] else [])
        bad += [f"{f['path']}: {f['actual']} != locked {f['expected']}" for f in r["mismatched"]]
        raise SystemExit("refusing to run: the B / C definitions differ from the locked DEFS_BC.sha256:\n  "
                         + "\n  ".join(bad + [f"{m}: not in the manifest" for m in r["not_in_manifest"]]))
    return r


def manifest_git_check(commit: str = DEFS_BC_COMMIT, rel: str = "research/entry_study/DEFS_BC.sha256") -> dict:
    """sha256 of DEFS_BC.sha256 as committed in `commit` (git show), next to the pinned value; refuses when git
    answers with other bytes. Without git (or the commit) the pinned constant alone guards the manifest."""
    try:
        data = subprocess.run(["git", "-C", ROOT, "show", f"{commit}:{rel}"], capture_output=True, check=True,
                              timeout=30).stdout
    except Exception as e:
        return dict(commit=commit, git_sha256=None, pinned_sha256=DEFS_BC_MANIFEST_SHA256,
                    note=f"git unavailable ({type(e).__name__}); the pinned hash alone was checked")
    got = hashlib.sha256(data).hexdigest()
    if got != DEFS_BC_MANIFEST_SHA256:
        raise SystemExit(f"refusing to run: DEFS_BC.sha256 in {commit} hashes to {got}, not the pinned "
                         f"{DEFS_BC_MANIFEST_SHA256}")
    return dict(commit=commit, git_sha256=got, pinned_sha256=DEFS_BC_MANIFEST_SHA256, ok=True)


def check_prereg() -> dict:
    sha_file = open(A.PREREG_SHA).read().split()[0]
    sha_now = A._sha256(A.PREREG)
    if sha_file != sha_now:
        raise SystemExit("refusing to run: PREREG_ENTRY.md does not match PREREG_ENTRY.sha256")
    return dict(prereg_sha256_file=sha_file, prereg_sha256_now=sha_now, prereg_hash_ok=True)


_MODS: dict = {}


def load_def(kind: str, name: str, manifest: str = DEFS_SHA, base_dir: str = HERE,
             manifest_sha: str | None = DEFS_BC_MANIFEST_SHA256):
    """Import strength_defs/<name>.py or param_defs/<name>.py after checking the manifest against its pinned hash
    and the exact bytes executed against the locked hash; refuses (SystemExit) on any difference. The worker
    processes call this without require_defs, so the manifest pin is checked here too."""
    key = (kind, name, os.path.abspath(manifest), os.path.abspath(base_dir), manifest_sha)
    if key in _MODS:
        return _MODS[key]
    rel = f"{kind}/{name}.py"
    path = os.path.join(base_dir, rel)
    man_act = A._sha256(manifest) if os.path.exists(manifest) else None
    if manifest_sha is not None and man_act != manifest_sha:
        raise SystemExit(f"refusing to load {rel}: manifest {manifest} sha256 {man_act} != pinned {manifest_sha}")
    exp = read_manifest(manifest).get(rel)
    data = open(path, "rb").read() if os.path.exists(path) else b""
    act = hashlib.sha256(data).hexdigest() if data else None
    if exp is None or act != exp:
        raise SystemExit(f"refusing to load {rel}: sha256 {act} != locked {exp}")
    mod_name = f"_bc_{kind}_{name}_{exp[:8]}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    exec(compile(data, path, "exec"), mod.__dict__)
    _MODS[key] = mod
    return mod


# ------------------------------------------------------------------ small helpers
def pair_key(idx, side) -> np.ndarray:
    return np.asarray(idx, np.int64) * 2 + (np.asarray(side) > 0)


def side_values(long_v, short_v, idx, side) -> np.ndarray:
    """Feature value of the side each entry trades: the long array where side > 0, the short array where side < 0."""
    idx = np.asarray(idx, np.int64)
    side = np.asarray(side)
    if np.any(side == 0):
        raise ValueError("side 0 has no feature value")
    return np.where(side > 0, np.asarray(long_v, float)[idx], np.asarray(short_v, float)[idx])


def signed(values, higher_is_stronger: bool) -> np.ndarray:
    """Sign the feature so that 'stronger' = higher."""
    return np.asarray(values, float) * (1.0 if higher_is_stronger else -1.0)


def to_signal(long, short) -> np.ndarray:
    long = np.asarray(long, bool)
    return long.astype(np.int8) - (np.asarray(short, bool) & ~long).astype(np.int8)


def _stack(cols: list, m: int) -> np.ndarray:
    return np.column_stack(cols) if cols and m else np.zeros((m, len(cols)))


def _atomic_write(path: str, write) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "wb") as fh:
        write(fh)
    os.replace(tmp, path)


def _json_val(v):
    if isinstance(v, (list, tuple)):
        return json.dumps([_json_val(x) for x in v])
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    return v


# ------------------------------------------------------------------ statistics
def _ties(v: np.ndarray):
    """Sort order, start of each tie group in sorted order, tie-group id of every element."""
    o = np.argsort(v, kind="mergesort")
    vs = v[o]
    new = np.ones(len(v), bool)
    if len(v) > 1:
        new[1:] = vs[1:] != vs[:-1]
    gid = np.empty(len(v), np.int64)
    gid[o] = np.cumsum(new) - 1
    return o, np.flatnonzero(new), gid


def _wspearman(W: np.ndarray, tx, ty) -> np.ndarray:
    """Spearman rho per row of W (k, n): the sample in which element i appears W[r, i] times."""
    W = np.asarray(W, float)
    rks = []
    for o, starts, gid in (tx, ty):
        G = np.add.reduceat(W[:, o], starts, axis=1)
        mid = np.cumsum(G, axis=1) - (G - 1.0) / 2.0          # mid-rank of each tie group
        rks.append(mid[:, gid])
    m = (W.sum(axis=1, keepdims=True) + 1.0) / 2.0             # weighted mean of mid-ranks = (N + 1) / 2
    cx, cy = rks[0] - m, rks[1] - m
    sxy = (W * cx * cy).sum(axis=1)
    sxx = (W * cx * cx).sum(axis=1)
    syy = (W * cy * cy).sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        rho = sxy / np.sqrt(sxx * syy)
    rho[~((sxx > 0) & (syy > 0))] = np.nan
    return rho


def spearman(x, y) -> float:
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 2:
        return np.nan
    return float(_wspearman(np.ones((1, len(x))), _ties(x), _ties(y))[0])


def _week_D(v: np.ndarray, inv: np.ndarray, W: int, order: np.ndarray) -> np.ndarray:
    """(n, W), rows in week order: D[i, w] = (#{j in week w: v_j < v_i} - #{j in week w: v_j > v_i}) / 2.
    With week multiplicities c, the centred mid-rank of trade i in the resampled sample is D[i] @ c."""
    n = len(v)
    o, starts, gid = _ties(v)
    cum = np.zeros((n + 1, W), np.int32)
    cum[np.arange(1, n + 1), inv[o]] = 1
    np.cumsum(cum, axis=0, out=cum)                            # cum[k, w] = week-w trades among sorted 0..k-1
    Dg = (cum[starts] + cum[np.r_[starts[1:], n]] - cum[-1]).astype(float) * 0.5   # below + (below or tied) - n_w
    del cum
    return Dg[gid[order]]


def _week_tensor(Da: np.ndarray, Db: np.ndarray, bounds: np.ndarray) -> np.ndarray:
    """(W, W * W) with [v, u * W + w] = sum over trades i of week u of Da[i, v] * Db[i, w]."""
    W = len(bounds) - 1
    T = np.empty((W, W, W))
    for u in range(W):
        a, b = bounds[u], bounds[u + 1]
        T[u] = Da[a:b].T @ Db[a:b]
    return np.ascontiguousarray(T.transpose(1, 0, 2).reshape(W, W * W))


def _contract(C: np.ndarray, Tv: np.ndarray) -> np.ndarray:
    """sum_{u,v,w} c_u c_v c_w T[u, v, w] per row c of C."""
    W = C.shape[1]
    Y = (C @ Tv).reshape(len(C), W, W)                         # [b, u, w] = sum_v c_v T[u, v, w]
    return np.einsum("buw,bw,bu->b", Y, C, C)


def _boot_rho_tensor(x, y, inv, W: int, C: np.ndarray, chunk_elems: int = CHUNK_ELEMS) -> np.ndarray:
    """Exact resampled Spearman rho through the week tensors: cost ~ n W^2 once + B W^3, not B n."""
    order = np.argsort(inv, kind="stable")
    bounds = np.searchsorted(inv[order], np.arange(W + 1))
    Dx, Dy = _week_D(x, inv, W, order), _week_D(y, inv, W, order)
    Txy, Txx, Tyy = _week_tensor(Dx, Dy, bounds), _week_tensor(Dx, Dx, bounds), _week_tensor(Dy, Dy, bounds)
    del Dx, Dy
    k = max(1, int(chunk_elems // (W * W)))
    rb = np.empty(len(C))
    for c0 in range(0, len(C), k):
        Cc = C[c0:c0 + k]
        sxy, sxx, syy = _contract(Cc, Txy), _contract(Cc, Txx), _contract(Cc, Tyy)
        with np.errstate(divide="ignore", invalid="ignore"):
            r = sxy / np.sqrt(sxx * syy)
        r[~((sxx > 0) & (syy > 0))] = np.nan
        rb[c0:c0 + k] = r
    return rb


def _boot_rho_direct(x, y, inv, C: np.ndarray, chunk_elems: int = CHUNK_ELEMS) -> np.ndarray:
    """Exact resampled Spearman rho with per-trade multiplicities: cost ~ B n."""
    tx, ty = _ties(x), _ties(y)
    k = max(1, int(chunk_elems // len(x)))
    rb = np.empty(len(C))
    for c0 in range(0, len(C), k):
        rb[c0:c0 + k] = _wspearman(C[c0:c0 + k][:, inv], tx, ty)
    return rb


def use_tensor(n: int, W: int) -> bool:
    """Both methods give the same rho_b; pick the cheaper (measured: direct ~2e-4 s x n, tensor ~3e-7 s x W^3
    per 2,000 resamples, single BLAS thread)."""
    return n > 1.5e-3 * W ** 3


def spearman_boot(x, y, week, seed=None, B: int = BOOT_B, chunk_elems: int = CHUNK_ELEMS, method: str = "auto") -> dict:
    """Observed Spearman rho and one-sided week-block bootstrap p-values (p_pos: H1 rho > 0; p_neg: H1 rho < 0).
    seed None -> rho only. rho_b is rounded to 12 decimals before counting (both exact methods agree to ~1e-15)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = len(x)
    out = dict(n=int(n), weeks=0, rho=np.nan, p_pos=np.nan, p_neg=np.nan, undefined_resamples=0)
    if n < 2:
        return out
    out["rho"] = float(_wspearman(np.ones((1, n)), _ties(x), _ties(y))[0])
    if seed is None:
        return out
    uw, inv = np.unique(np.asarray(week), return_inverse=True)
    W = len(uw)
    C = boot_counts(W, B, seed)
    tensor = use_tensor(n, W) if method == "auto" else method == "tensor"
    rb = _boot_rho_tensor(x, y, inv, W, C, chunk_elems) if tensor else _boot_rho_direct(x, y, inv, C, chunk_elems)
    rb = np.round(rb, 12)
    und = ~np.isfinite(rb)
    out.update(weeks=int(len(uw)), undefined_resamples=int(und.sum()),
               p_pos=(1 + int(((rb <= 0) | und).sum())) / (B + 1),
               p_neg=(1 + int(((rb >= 0) | und).sum())) / (B + 1))
    return out


def mean_se_boot(roe, week, seed, B: int = BOOT_B) -> dict:
    """Mean ROE per trade and its week-block bootstrap SE (sd of the resampled means)."""
    roe = np.asarray(roe, float)
    out = dict(n=int(len(roe)), mean=np.nan, se=np.nan, weeks=0)
    if not len(roe):
        return out
    out["mean"] = float(roe.mean())
    uw, inv = np.unique(np.asarray(week), return_inverse=True)
    out["weeks"] = int(len(uw))
    if len(uw) < 2:
        return out
    s_w = np.bincount(inv, weights=roe, minlength=len(uw))
    n_w = np.bincount(inv, minlength=len(uw)).astype(float)
    C = boot_counts(len(uw), B, seed)
    bm = (C @ s_w) / (C @ n_w)
    bm = bm[np.isfinite(bm)]
    out["se"] = float(bm.std(ddof=1)) if len(bm) > 1 else np.nan
    return out


def classify_shape(d_mean: float, d_se: float, var_means: dict, min_ok: bool = True) -> tuple[str, str]:
    """PREREG 4 shape of one parameter from period 1: 'flat' if every variant is within +-1 SE of the default,
    'spike' if the default beats both neighbours (x0.75, x1.25) by > 2 SE, else 'smooth'."""
    if not min_ok:
        return "insufficient", f"default period-1 signals < {MIN_SIGNALS}"
    if not (np.isfinite(d_mean) and np.isfinite(d_se) and d_se > 0):
        return "insufficient", "default period-1 mean or SE undefined"
    vals = [var_means.get(m, np.nan) for m in MULTS]
    fin = [np.isfinite(v) for v in vals]
    if all(fin) and all(abs(v - d_mean) <= FLAT_SE * d_se for v in vals):
        return "flat", ""
    nb = [var_means.get(m, np.nan) for m in NEIGHBOURS]
    if all(np.isfinite(v) for v in nb) and all(d_mean - v > SPIKE_SE * d_se for v in nb):
        return "spike", ""
    missing = [f"x{m}" for m, f in zip(MULTS, fin) if not f]
    return "smooth", (f"no period-1 trades: {', '.join(missing)}" if missing else "")


def random_all(counts: dict, pools: dict, seed, B: int = BOOT_B) -> dict:
    """Random entries with the same trade counts (counts[period][coin]) drawn with replacement from pools[period]
    [coin] (random-entry ROEs): k = number of the B draws whose pooled mean ROE is > 0 in every period, prob = k / B.
    Periods in sorted order; once no draw is left, the later periods cannot change k (= 0) and are not drawn."""
    rng = np.random.default_rng(seed)
    nan = dict(prob=np.nan, k=None, draws=int(B))
    if any(int(sum(counts[p].values())) == 0 for p in counts) or any(
            int(n) > 0 and not len(pools.get(p, {}).get(c, ())) for p in counts for c, n in counts[p].items()):
        return nan
    ok = np.ones(B, bool)
    for p in sorted(counts):
        if not ok.any():
            break
        n_tot = int(sum(counts[p].values()))
        tot = np.zeros(B)
        for coin in sorted(counts[p], key=lambda c: (COINS.index(c) if c in COINS else 99, str(c))):
            n_c = int(counts[p][coin])
            if n_c == 0:
                continue
            pool = np.asarray(pools[p][coin], float)
            step = max(1, CHUNK_ELEMS // n_c)
            for c0 in range(0, B, step):
                kk = min(step, B - c0)
                tot[c0:c0 + kk] += pool[rng.integers(0, len(pool), size=(kk, n_c))].sum(axis=1)
        ok &= tot / n_tot > 0
    k = int(ok.sum())
    return dict(prob=k / B, k=k, draws=int(B))


def prob_random_all(counts: dict, pools: dict, seed, B: int = BOOT_B) -> float:
    """Share of B draws in which random entries with the same trade counts (counts[period][coin]) drawn with
    replacement from pools[period][coin] (random-entry ROEs) have a pooled mean ROE > 0 in every period."""
    return float(random_all(counts, pools, seed, B)["prob"])


def prob_text(k, B: int = BOOT_B) -> str:
    """Report text of a draw share: 'k/B', or '< 1/B' when no draw qualified (0 is not a probability estimate)."""
    if k is None:
        return ""
    return f"< 1/{B}" if int(k) == 0 else f"{int(k)}/{B}"


def noedge_block_all(units: dict, mu0: dict, seeds: dict, B: int = BOOT_B) -> float:
    """Share of B draws in which a no-edge version of the variant has pooled mean ROE > 0 in every period.
    units[p] = (roe, week) of the variant's trades in period p (pooled over coins), mu0[p] = the random-entry mean
    it is centred on; per period the variant's own weeks are resampled (boot_counts(W, B, seeds[p])) on
    roe - mean(roe) + mu0[p], so the draws keep the variant's week clustering and have no edge over random entries."""
    ok = np.ones(B, bool)
    for p in sorted(units):
        roe, week = (np.asarray(x) for x in units[p])
        if not len(roe) or not np.isfinite(mu0[p]):
            return np.nan
        uw, inv = np.unique(week, return_inverse=True)
        y = roe.astype(float) - float(roe.mean()) + float(mu0[p])
        s_w = np.bincount(inv, weights=y, minlength=len(uw))
        n_w = np.bincount(inv, minlength=len(uw)).astype(float)
        C = boot_counts(len(uw), B, seeds[p])
        with np.errstate(divide="ignore", invalid="ignore"):
            bm = (C @ s_w) / (C @ n_w)
        ok &= bm > 0
    return float(ok.mean())


# ------------------------------------------------------------------ stage 0: bases
def base_path(tf: str, coin: str, src: str, base_dir: str = BASE_DIR) -> str:
    return os.path.join(base_dir, f"base_{tf}_{coin}_{src}.npz")


def _source_files(tf: str, coin: str, src: str) -> list[str]:
    if src == "p12":
        return [os.path.join(A.SIG12, f"sig_{tf}_{coin}.npz"), os.path.join(A.SWEEP, "full", f"{coin.lower()}-{tf}.csv")]
    return [os.path.join(A.SIG3, f"sig_{tf}_{coin}.npz")]


def source_fingerprint(tf: str, coin: str, src: str) -> list:
    """[absolute path, size, mtime_ns] of each source file of (tf, coin, src)."""
    return [[os.path.abspath(p), os.path.getsize(p), os.stat(p).st_mtime_ns] for p in _source_files(tf, coin, src)]


def require_default_data() -> dict:
    """Parts B and C run only on the pre-registered data: refuse when analysis_sr's robustness-re-run data
    overrides ($SR_SIG12 / $SR_VOLUME12) are active in this process."""
    ov = A.overrides() if hasattr(A, "overrides") else {}
    bad = {k: v for k, v in ov.items() if k in ("sig12", "volume12")}
    if bad:
        raise SystemExit(f"refusing to run: analysis_sr data overrides are set ({bad}); parts B and C use only the "
                         f"pre-registered data (unset SR_SIG12 / SR_VOLUME12)")
    return dict(sig12=A.SIG12, volume12=getattr(A, "VOLUME12", "sweep_csv"), sig3=A.SIG3, overrides_ignored=ov)


def read_base_meta(path: str) -> dict | None:
    try:
        with np.load(path) as z:
            return json.loads(str(z["meta"]))
    except Exception:
        return None


def base_ok(tf: str, coin: str, src: str) -> bool:
    """The base exists, was built by this code (CODE_HASH) and from the current source files."""
    m = read_base_meta(base_path(tf, coin, src))
    return (bool(m) and m.get("version") == BASE_VERSION and m.get("code") == CODE_HASH
            and m.get("fingerprint") == source_fingerprint(tf, coin, src))


def stale_bases(tfs) -> list:
    return [(tf, c, s) for tf in tfs for c in COINS for s, _ in SOURCES if not base_ok(tf, c, s)]


def source_fingerprints(tfs) -> dict:
    """{'tf coin src': fingerprint} of the current source files."""
    return {f"{tf} {c} {s}": source_fingerprint(tf, c, s) for tf in tfs for c in COINS for s, _ in SOURCES}


def build_base(args) -> dict:
    """Bars, locked signals, period windows, random entries and the outcomes of every default / random pair."""
    tf, coin, src = args
    t0 = time.time()
    L = _lib()
    names = strategy_names(L)
    periods = dict(SOURCES)[src]
    df, b, sigs, vol_missing = A.load_series(tf, coin, src)
    missing = [nm for nm in names if nm not in sigs]
    if missing:
        raise KeyError(f"{tf} {coin} {src}: strategies missing from the cache: {missing}")
    warm, tf_min, ci = int(L.warmup_bars(tf)), int(L.tf_minutes(tf)), COINS.index(coin)
    store = dict(ts=b["ts"].astype(np.int64), o=b["o"], h=b["h"], l=b["l"], c=b["c"],
                 v=df["volume"].to_numpy(float), atr=b["atr"])
    for nm in names:
        store[f"s__{nm}"] = np.asarray(sigs[nm]).astype(np.int8)
    keys = [np.zeros(0, np.int64)]
    for p in periods:
        lo, hi = period_bounds(b["ts"], p, warm)
        store[f"bounds_p{p}"] = np.array([lo, hi], np.int64)
        for nm in names:
            sg = store[f"s__{nm}"]
            idx = np.flatnonzero(sg[lo:hi]).astype(np.int64) + lo
            keys.append(pair_key(idx, sg[idx]))
        ridx, rside = random_bars(lo, hi, tf_min, ci, p)
        store[f"r_idx_p{p}"], store[f"r_side_p{p}"] = ridx, rside
        keys.append(pair_key(ridx, rside))
    keys = np.unique(np.concatenate(keys))
    t1 = time.time()
    oc = A.outcomes(b, keys // 2, np.where(keys % 2 == 1, 1, -1).astype(np.int8), tf, PR._sizer())
    t2 = time.time()
    store["keys"] = keys
    for k in OC_COLS:
        store[f"oc_{k}"] = np.asarray(oc[k])
    tab = OutcomeTable(keys, {k: store[f"oc_{k}"] for k in OC_COLS})
    week = sr.period_key(store["ts"], "week")
    for p in periods:
        r = tab.get(store[f"r_idx_p{p}"], store[f"r_side_p{p}"])
        store[f"r_valid_p{p}"] = r["valid"]
        store[f"r_roe_p{p}"] = np.where(r["valid"], r["roe"], np.nan)
        store[f"r_week_p{p}"] = week[store[f"r_idx_p{p}"]]
    meta = dict(version=BASE_VERSION, code=CODE_HASH, tf=tf, coin=coin, src=src, periods=list(periods),
                bars=int(len(store["ts"])),
                first=str(pd.Timestamp(int(store["ts"][0]))), last=str(pd.Timestamp(int(store["ts"][-1]))),
                warmup_bars=warm, volume_missing=int(vol_missing), fingerprint=source_fingerprint(tf, coin, src),
                pairs=int(len(keys)), pairs_sized=int(np.asarray(oc["sized"]).sum()),
                pairs_open_at_end=int((np.asarray(oc["sized"]) & ~np.asarray(oc["done"])).sum()),
                random={str(p): dict(sampled=int(len(store[f"r_idx_p{p}"])), trades=int(store[f"r_valid_p{p}"].sum()),
                                     eligible_bars=int(store[f"bounds_p{p}"][1] - store[f"bounds_p{p}"][0]))
                        for p in periods},
                seconds=dict(load=round(t1 - t0, 2), outcomes=round(t2 - t1, 2), total=round(time.time() - t0, 2)))
    store["meta"] = np.array(json.dumps(meta))
    _atomic_write(base_path(tf, coin, src), lambda fh: np.savez(fh, **store))
    return meta


def load_base(tf: str, coin: str, src: str, keys=None) -> dict:
    with np.load(base_path(tf, coin, src)) as z:
        out = {k: z[k] for k in (keys or z.files)}
    if "meta" in out:
        out["meta"] = json.loads(str(out["meta"]))
    return out


def frame(base: dict, tf: str) -> pd.DataFrame:
    """Bars as the definitions were verified on: ts tz-aware UTC, open, high, low, close, volume; attrs tf."""
    df = pd.DataFrame({"ts": pd.to_datetime(base["ts"], utc=True), "open": base["o"], "high": base["h"],
                       "low": base["l"], "close": base["c"], "volume": base["v"]})
    df.attrs["tf"] = tf
    return df


class OutcomeTable:
    """Outcome per (bar, side) pair, keyed by bar * 2 + (side > 0), sorted."""

    def __init__(self, keys, cols: dict):
        self.keys = np.asarray(keys, np.int64)
        self.cols = {k: np.asarray(cols[k]) for k in OC_COLS}

    @classmethod
    def from_base(cls, base: dict) -> "OutcomeTable":
        return cls(base["keys"], {k: base[f"oc_{k}"] for k in OC_COLS})

    def _rows(self, q):
        if not len(self.keys):
            return np.zeros(len(q), np.int64), np.zeros(len(q), bool)
        r = np.minimum(np.searchsorted(self.keys, q), len(self.keys) - 1)
        return r, self.keys[r] == q

    def get(self, idx, side) -> dict:
        r, found = self._rows(pair_key(idx, side))
        if not found.all():
            raise KeyError(f"{int((~found).sum())} (bar, side) pairs have no outcome")
        out = {k: v[r] for k, v in self.cols.items()}
        out["valid"] = out["sized"].astype(bool) & out["done"].astype(bool) & np.isfinite(out["roe"])
        return out

    def ensure(self, b: dict, idx, side, tf: str, sizer) -> int:
        """Compute (with analysis_sr.outcomes) and add the pairs not in the table; returns how many."""
        q = np.unique(pair_key(idx, side))
        _, found = self._rows(q)
        miss = q[~found]
        if len(miss):
            oc = A.outcomes(b, miss // 2, np.where(miss % 2 == 1, 1, -1).astype(np.int8), tf, sizer)
            keys = np.concatenate([self.keys, miss])
            order = np.argsort(keys, kind="mergesort")
            self.keys = keys[order]
            self.cols = {k: np.concatenate([self.cols[k], np.asarray(oc[k]).astype(self.cols[k].dtype)])[order]
                         for k in OC_COLS}
        return int(len(miss))


def ensure_bases(tfs, procs: int, log=print) -> dict:
    jobs = [(tf, c, src) for tf in tfs for c in COINS for src, _ in SOURCES]
    todo = [j for j in jobs if not base_ok(*j)]
    t0 = time.time()
    metas = []
    if todo:
        log(f"bases: building {len(todo)} of {len(jobs)}", flush=True)
        for m in _map(build_base, todo, procs):
            metas.append(m)
            log(f"[{time.time() - t0:6.0f}s] base {m['tf']:>3} {m['coin']} {m['src']}: {m['bars']} bars, "
                f"{m['pairs']} pairs ({m['seconds']['total']}s)", flush=True)
    return dict(built=len(todo), reused=len(jobs) - len(todo), wall_s=round(time.time() - t0, 1),
                built_seconds=sum(m["seconds"]["total"] for m in metas))


def _map(fn, items, procs: int):
    if procs <= 1 or len(items) <= 1:
        for it in items:
            yield fn(it)
        return
    with Pool(min(procs, len(items)), maxtasksperchild=20) as pool:
        yield from pool.imap_unordered(fn, items)


# ------------------------------------------------------------------ stage 1: jobs + checkpoints
def ckpt_path(part: str, name: str, tf: str, coin: str, ckpt_dir: str = CKPT_DIR) -> str:
    return os.path.join(ckpt_dir, part, f"{name}__{tf}__{coin}.pkl")


def code_signature() -> str:
    """Changes when any byte of the code that ran changes (CODE_HASH, taken at import), including the locked
    definitions' manifest; stale bases and checkpoints recompute."""
    return CODE_HASH[:16]


def job_signature(tf: str, coin: str) -> str:
    """Code signature + the CURRENT source-file fingerprints of (tf, coin) + the code hash stored in each base, so
    a checkpoint made on other data, by other code or from a base built by other code is not reused."""
    fps = [source_fingerprint(tf, coin, src) for src, _ in SOURCES]
    codes = [(read_base_meta(base_path(tf, coin, src)) or {}).get("code") for src, _ in SOURCES]
    return code_signature() + ":" + hashlib.sha256(json.dumps([fps, codes]).encode()).hexdigest()[:12]


def load_ckpt(path: str, sig: str | None = None):
    """The checkpoint's data, or None when missing, unreadable or made with another signature."""
    try:
        with open(path, "rb") as fh:
            d = pickle.load(fh)
    except Exception:
        return None
    if not isinstance(d, dict) or (sig is not None and d.get("sig") != sig):
        return None
    return d.get("data")


def save_ckpt(path: str, data, sig: str) -> None:
    _atomic_write(path, lambda fh: pickle.dump(dict(sig=sig, data=data), fh, protocol=pickle.HIGHEST_PROTOCOL))


def _run_one(task):
    fn, job, path, sig = task
    t0 = time.time()
    data = fn(job)
    save_ckpt(path, data, sig)
    return job, round(time.time() - t0, 2)


def run_jobs(jobs: list, fn, path_of, sig_of, procs: int, log=print) -> dict:
    """Run fn(job) for every job without a valid checkpoint (path_of(job), sig_of(job)); each finished job is
    written at once (atomic), so a killed run resumes with the remaining ones."""
    todo = [(fn, j, path_of(j), sig_of(j)) for j in jobs if load_ckpt(path_of(j), sig_of(j)) is None]
    t0 = time.time()
    done = []
    for i, (job, sec) in enumerate(_map(_run_one, todo, procs)):
        done.append((job, sec))
        if log:
            log(f"[{time.time() - t0:6.0f}s] {i + 1}/{len(todo)} {job} {sec}s", flush=True)
    return dict(jobs=len(jobs), run=len(todo), resumed=len(jobs) - len(todo), wall_s=round(time.time() - t0, 1),
                job_seconds=done)


def job_B(job) -> dict:
    """Signals and random entries of one strategy x tf x coin with their strength values and outcomes."""
    name, tf, coin = job
    t0 = time.time()
    S = load_def("strength_defs", name)
    feats = [f["name"] for f in S.FEATURES]
    res = dict(part="B", name=name, tf=tf, coin=coin, features=[dict(f) for f in S.FEATURES], periods={},
               seconds={})
    for src, periods in SOURCES:
        ts0 = time.time()
        base = load_base(tf, coin, src)
        tab = OutcomeTable.from_base(base)
        df = frame(base, tf)
        t1 = time.time()
        st = S.strength(df, tf)
        t2 = time.time()
        if list(st) != feats:
            raise ValueError(f"{name}: strength() keys {list(st)} != FEATURES {feats}")
        for f in feats:
            if len(st[f]) != 2 or any(len(a) != len(df) for a in st[f]):
                raise ValueError(f"{name} {f}: strength() must return (long, short) arrays of len(df)")
        sig = base[f"s__{name}"]
        week_all = sr.period_key(base["ts"], "week")
        for p in periods:
            lo, hi = (int(x) for x in base[f"bounds_p{p}"])
            idx = np.flatnonzero(sig[lo:hi]).astype(np.int64) + lo
            side = sig[idx].astype(np.int8)
            oc = tab.get(idx, side)
            v = oc["valid"]
            X = _stack([side_values(st[f][0], st[f][1], idx, side) for f in feats], len(idx))
            ridx, rside, rv = base[f"r_idx_p{p}"], base[f"r_side_p{p}"], base[f"r_valid_p{p}"]
            RX = _stack([side_values(st[f][0], st[f][1], ridx[rv], rside[rv]) for f in feats], int(rv.sum()))
            res["periods"][p] = dict(
                src=src, n_signals=int(len(idx)), n_atr_ok=int(oc["ok"].sum()), n_sized=int(oc["sized"].sum()),
                n_open=int((oc["sized"].astype(bool) & ~oc["done"].astype(bool)).sum()), n_trades=int(v.sum()),
                n_long_trades=int((side[v] > 0).sum()), n_signals_nan=[int((~np.isfinite(X[:, j])).sum())
                                                                        for j in range(len(feats))],
                week=week_all[idx[v]].astype(np.int64), roe=oc["roe"][v].astype(float), X=X[v],
                r_sampled=int(len(ridx)), r_trades=int(rv.sum()), RX=RX)
        res["seconds"][src] = dict(load=round(t1 - ts0, 2), strength=round(t2 - t1, 2),
                                   rest=round(time.time() - t2, 2))
        del base, tab, df, st
    res["seconds"]["total"] = round(time.time() - t0, 2)
    return res


def variant_list(P) -> list[dict]:
    """[default] + one entry per (parameter, multiplier) in PARAMS / variants() order."""
    mults = tuple(getattr(P, "MULTIPLIERS", getattr(P, "MULTS", MULTS)))
    if mults != MULTS:
        raise ValueError(f"{P.NAME}: multipliers {mults} != {MULTS}")
    out = [dict(vid=0, param="default", param_idx=-1, kind="", default=None, mult=1.0, mult_idx=-1, value=None,
                overrides={})]
    for pi_, spec in enumerate(P.PARAMS):
        ovs = P.variants(spec)
        if len(ovs) != len(MULTS) or any(list(ov) != [spec["name"]] for ov in ovs):
            raise ValueError(f"{P.NAME} {spec['name']}: variants() must give one override per multiplier")
        for mi, ov in enumerate(ovs):
            out.append(dict(vid=len(out), param=spec["name"], param_idx=pi_, kind=spec["kind"],
                            default=spec["default"], mult=MULTS[mi], mult_idx=mi, value=ov[spec["name"]],
                            overrides=dict(ov)))
    return out


def job_C(job) -> dict:
    """Default (locked) signals and every variant of one strategy x tf x coin with outcomes per period."""
    name, tf, coin = job
    t0 = time.time()
    P = load_def("param_defs", name)
    res = dict(part="C", name=name, tf=tf, coin=coin, excluded=getattr(P, "EXCLUDED_REASON", None), variants=[],
               periods={}, default_check={}, seconds={})
    if res["excluded"]:
        res["seconds"]["total"] = round(time.time() - t0, 2)
        return res
    variants = variant_list(P)
    res["variants"] = [{k: v for k, v in x.items() if k != "overrides"} for x in variants]
    sizer = PR._sizer()
    for src, periods in SOURCES:
        ts0 = time.time()
        base = load_base(tf, coin, src)
        tab = OutcomeTable.from_base(base)
        df = frame(base, tf)
        b = {k: base[k] for k in ("ts", "o", "h", "l", "c", "atr")}
        ref = base[f"s__{name}"].astype(np.int8)
        warm = int(base["meta"]["warmup_bars"])
        post = np.arange(len(ref)) >= warm
        t1 = time.time()
        s_def = to_signal(*P.signals(df, tf))
        res["default_check"][src] = dict(mismatch_post_warmup=int(((s_def != ref) & post).sum()),
                                         mismatch_warmup=int(((s_def != ref) & ~post).sum()),
                                         signals_post_warmup=int(((ref != 0) & post).sum()))
        sigs = [ref] + [to_signal(*P.signals(df, tf, **v["overrides"])) for v in variants[1:]]
        t2 = time.time()
        units = {}
        for p in periods:
            lo, hi = (int(x) for x in base[f"bounds_p{p}"])
            for v, sg in zip(variants, sigs):
                idx = np.flatnonzero(sg[lo:hi]).astype(np.int64) + lo
                units[(v["vid"], p)] = (idx, sg[idx], int((sg[lo:hi] != ref[lo:hi]).sum()))
        allidx = np.concatenate([u[0] for u in units.values()] + [np.zeros(0, np.int64)])
        allside = np.concatenate([u[1] for u in units.values()] + [np.zeros(0, np.int8)])
        n_new = tab.ensure(b, allidx, allside, tf, sizer)
        t3 = time.time()
        week_all = sr.period_key(base["ts"], "week")
        for p in periods:
            res["periods"][p] = {}
            for v in variants:
                idx, side, changed = units[(v["vid"], p)]
                oc = tab.get(idx, side)
                ok = oc["valid"]
                res["periods"][p][v["vid"]] = dict(
                    n_signals=int(len(idx)), n_sized=int(oc["sized"].sum()),
                    n_open=int((oc["sized"].astype(bool) & ~oc["done"].astype(bool)).sum()), n_trades=int(ok.sum()),
                    changed_signal_bars=changed, week=week_all[idx[ok]].astype(np.int64),
                    roe=oc["roe"][ok].astype(float))
        res["seconds"][src] = dict(load=round(t1 - ts0, 2), signals=round(t2 - t1, 2), outcomes=round(t3 - t2, 2),
                                   new_pairs=n_new, rest=round(time.time() - t3, 2))
        del base, tab, df, sigs, units
    res["seconds"]["total"] = round(time.time() - t0, 2)
    return res


JOB_FN = {"B": job_B, "C": job_C}


def part_jobs(part: str, names, tfs) -> list:
    tf_all = TFS_B if part == "B" else TFS_C
    sel = [tf for tf in tf_all if tf in tfs]
    return [(nm, tf, c) for tf in sel for nm in names for c in COINS]   # 5m first: the longest jobs start first


# ------------------------------------------------------------------ stage 2: aggregation
def _seed(*parts) -> list[int]:
    return [BOOT_SEED] + [int(x) for x in parts]


def agg_B_cell(args) -> dict:
    """Tests, random null and quintiles of one strategy x tf (pooled over coins) from the B checkpoints."""
    name, tf, code, sig = args
    t0 = time.time()
    cps = []
    for c in COINS:
        d = load_ckpt(ckpt_path("B", name, tf, c), sig[c])
        if d is None:
            raise FileNotFoundError(f"B checkpoint missing or stale: {name} {tf} {c}")
        cps.append(d)
    feats = cps[0]["features"]
    rnd = {}
    for c in COINS:
        for src, periods in SOURCES:
            z = load_base(tf, c, src, keys=[f"r_{k}_p{p}" for p in periods for k in ("valid", "roe", "week")])
            for p in periods:
                v = z[f"r_valid_p{p}"]
                rnd[(c, p)] = (z[f"r_roe_p{p}"][v], z[f"r_week_p{p}"][v])
    ti = TFS.index(tf)
    n_sig = {p: sum(d["periods"][p]["n_signals"] for d in cps) for p in PERIODS}
    tested = n_sig[1] >= MIN_SIGNALS
    cells, rand_rows, qrows = [], [], []
    for j, f in enumerate(feats):
        hs = bool(f["higher_is_stronger"])
        r = dict(strategy=name, tf=tf, feature=f["name"], feature_index=j, label_ko=f.get("label_ko", ""),
                 unit=f.get("unit", ""), higher_is_stronger=hs, tested=tested,
                 not_tested_reason="" if tested else f"period-1 signals {n_sig[1]} < {MIN_SIGNALS}")
        xs = {}
        for p in PERIODS:
            P_ = [d["periods"][p] for d in cps]
            x = signed(np.concatenate([q["X"][:, j] for q in P_]), hs)
            y = np.concatenate([q["roe"] for q in P_])
            w = np.concatenate([q["week"] for q in P_])
            fin = np.isfinite(x)
            x, y, w = x[fin], y[fin], w[fin]
            xs[p] = (x, y)
            enough = tested and len(x) >= MIN_TRADES
            t = spearman_boot(x, y, w, seed=_seed(SEED_PART["B"], code, ti, j, p) if enough else None)
            r.update({f"n_signals_p{p}": n_sig[p], f"n_trades_p{p}": sum(q["n_trades"] for q in P_),
                      f"n_finite_p{p}": int(len(x)), f"n_signals_nan_p{p}": sum(q["n_signals_nan"][j] for q in P_),
                      f"mean_roe_p{p}": float(y.mean()) if len(y) else np.nan,
                      f"rho_p{p}": t["rho"], f"rho_raw_p{p}": t["rho"] * (1 if hs else -1), f"p_p{p}": t["p_pos"],
                      f"status_p{p}": "ok" if enough else ("not tested" if not tested else "insufficient"),
                      f"weeks_p{p}": t["weeks"], f"undefined_resamples_p{p}": t["undefined_resamples"]})
            # random-entry null: the same feature at the random entries (value of the random side)
            rx = signed(np.concatenate([d["periods"][p]["RX"][:, j] for d in cps]), hs)
            ry = np.concatenate([rnd[(c, p)][0] for c in COINS])
            rw = np.concatenate([rnd[(c, p)][1] for c in COINS])
            if len(rx) != len(ry):
                raise ValueError(f"{name} {tf} p{p}: random features / outcomes misaligned")
            rf = np.isfinite(rx)
            renough = tested and p == 1 and int(rf.sum()) >= MIN_TRADES
            rt = spearman_boot(rx[rf], ry[rf], rw[rf],
                               seed=_seed(SEED_PART["B"], RANDOM_CODE + code, ti, j, p) if renough else None)
            rand_rows.append(dict(strategy=name, tf=tf, feature=f["name"], higher_is_stronger=hs, period=p,
                                  n_sampled=sum(d["periods"][p]["r_sampled"] for d in cps), n_trades=int(len(rx)),
                                  n_finite=int(rf.sum()), rho=rt["rho"], rho_raw=rt["rho"] * (1 if hs else -1),
                                  p_pos=rt["p_pos"], p_neg=rt["p_neg"], weeks=rt["weeks"],
                                  status="ok" if renough else ("rho only" if p != 1 or not tested else "insufficient")))
            r[f"random_n_finite_p{p}"] = int(rf.sum())
            r[f"random_rho_p{p}"] = rt["rho"]
            if p == 1:
                r["random_p_pos_p1"], r["random_p_neg_p1"] = rt["p_pos"], rt["p_neg"]
        # quintiles: period-1 edges of the signed feature, applied to every period
        x1 = xs[1][0]
        if len(x1) >= MIN_QUINTILE_TRADES:
            edges = np.quantile(x1, QUANTS)
            lo_e, hi_e = np.r_[-np.inf, edges], np.r_[edges, np.inf]
            for p in PERIODS:
                x, y = xs[p]
                q = np.searchsorted(edges, x, side="right")
                for k in range(5):
                    yy = y[q == k]
                    qrows.append(dict(strategy=name, tf=tf, feature=f["name"], higher_is_stronger=hs, tested=tested,
                                      period=p, quintile=k + 1, edge_lo=lo_e[k], edge_hi=hi_e[k], n=int(len(yy)),
                                      mean_roe=float(yy.mean()) if len(yy) else np.nan,
                                      median_roe=float(np.median(yy)) if len(yy) else np.nan,
                                      win_rate=float((yy > 0).mean()) if len(yy) else np.nan))
        cells.append(r)
    job_s = [d["seconds"]["total"] for d in cps]
    return dict(name=name, tf=tf, cells=cells, random=rand_rows, quintiles=qrows,
                seconds=dict(jobs_sum=round(sum(job_s), 2), jobs_max=round(max(job_s), 2),
                             aggregate=round(time.time() - t0, 2)))


def agg_C_cell(args) -> dict:
    """Per variant x period pooled over coins: trades, mean, SE; shapes; positive-in-all-periods and random odds."""
    name, tf, code, sig = args
    t0 = time.time()
    cps = []
    for c in COINS:
        d = load_ckpt(ckpt_path("C", name, tf, c), sig[c])
        if d is None:
            raise FileNotFoundError(f"C checkpoint missing or stale: {name} {tf} {c}")
        cps.append(d)
    ti = TFS.index(tf)
    job_s = [d["seconds"]["total"] for d in cps]
    secs = dict(jobs_sum=round(sum(job_s), 2), jobs_max=round(max(job_s), 2))
    excluded = cps[0]["excluded"]
    checks = {f"{d['coin']}_{src}": x for d in cps for src, x in d["default_check"].items()}
    mism = {k: x["mismatch_post_warmup"] for k, x in checks.items() if x["mismatch_post_warmup"]}
    if not excluded and mism:
        excluded = f"default signals() differ from the locked signal after warm-up: {mism}"
    if excluded:
        secs["aggregate"] = round(time.time() - t0, 2)
        return dict(name=name, tf=tf, excluded=excluded, variants=[], shapes=[], default_check=checks, seconds=secs)
    variants = cps[0]["variants"]
    rows = []
    for v in variants:
        r = dict(strategy=name, tf=tf, vid=v["vid"], param=v["param"], param_index=v["param_idx"], kind=v["kind"],
                 default_value=_json_val(v["default"]), mult=v["mult"], value=_json_val(v["value"]),
                 is_default=v["vid"] == 0)
        counts, units = {}, {}
        for p in PERIODS:
            P_ = [d["periods"][p][v["vid"]] for d in cps]
            roe = np.concatenate([q["roe"] for q in P_])
            week = np.concatenate([q["week"] for q in P_])
            units[p] = (roe, week)
            m = mean_se_boot(roe, week, _seed(SEED_PART["C_se"], code, ti, v["param_idx"] + 1,
                                               max(v["mult_idx"], 0), p))
            counts[p] = {d["coin"]: d["periods"][p][v["vid"]]["n_trades"] for d in cps}
            r.update({f"n_signals_p{p}": sum(q["n_signals"] for q in P_), f"n_trades_p{p}": m["n"],
                      f"n_open_excluded_p{p}": sum(q["n_open"] for q in P_), f"mean_roe_p{p}": m["mean"],
                      f"se_roe_p{p}": m["se"], f"weeks_p{p}": m["weeks"],
                      f"changed_signal_bars_p{p}": sum(q["changed_signal_bars"] for q in P_)})
        r["positive_all3"] = bool(all(r[f"n_trades_p{p}"] > 0 and r[f"mean_roe_p{p}"] > 0 for p in PERIODS))
        r.update(prob_random_all3=np.nan, prob_random_all3_k=None, prob_random_all3_text="",
                 prob_random_all3_upper=np.nan, prob_noedge_block_all3=np.nan)
        r["_counts"], r["_units"] = counts, units
        rows.append(r)
    min_ok = rows[0]["n_signals_p1"] >= MIN_SIGNALS
    # chance of 'mean ROE > 0 in all three periods' for every row with trades in all three periods (passing or not):
    # iid random entries with the same trade counts, and a no-edge version of the row with its own week clustering
    need = [r for r in rows if all(r[f"n_trades_p{p}"] > 0 for p in PERIODS)]
    if need:
        pools = {p: {} for p in PERIODS}
        for c in COINS:
            for src, periods in SOURCES:
                z = load_base(tf, c, src, keys=[f"r_{k}_p{p}" for p in periods for k in ("valid", "roe")])
                for p in periods:
                    pools[p][c] = z[f"r_roe_p{p}"][z[f"r_valid_p{p}"]]
        pool_mean = {p: {c: float(x.mean()) if len(x) else np.nan for c, x in pools[p].items()} for p in PERIODS}
        for r in need:
            v = variants[r["vid"]]
            u = (v["param_idx"] + 1, max(v["mult_idx"], 0))
            ra = random_all(r["_counts"], pools, _seed(SEED_PART["C_random"], code, ti, *u))
            r["prob_random_all3"], r["prob_random_all3_k"] = ra["prob"], ra["k"]
            r["prob_random_all3_text"] = prob_text(ra["k"], ra["draws"])
            if ra["k"] == 0:
                r["prob_random_all3_upper"] = 1.0 / (ra["draws"] + 1)
            mu0 = {p: (sum(n * pool_mean[p][c] for c, n in r["_counts"][p].items() if n)
                       / sum(r["_counts"][p].values())) for p in PERIODS}
            r["prob_noedge_block_all3"] = noedge_block_all(
                r["_units"], mu0, {p: _seed(SEED_PART["C_noedge"], code, ti, *u, p) for p in PERIODS})
    d_row = rows[0]
    shapes = []
    by_param = {}
    for r in rows[1:]:
        by_param.setdefault(r["param"], []).append(r)
    for pname, prs in by_param.items():
        means = {r["mult"]: r["mean_roe_p1"] if r["n_trades_p1"] > 0 else np.nan for r in prs}
        shape, why = classify_shape(d_row["mean_roe_p1"], d_row["se_roe_p1"], means, min_ok)
        s = dict(strategy=name, tf=tf, param=pname, param_index=prs[0]["param_index"], kind=prs[0]["kind"],
                 default_value=prs[0]["default_value"], cell_meets_minimum=min_ok,
                 default_n_signals_p1=d_row["n_signals_p1"], default_n_trades_p1=d_row["n_trades_p1"],
                 default_mean_p1=d_row["mean_roe_p1"], default_se_p1=d_row["se_roe_p1"])
        for r in prs:
            lab = f"x{r['mult']:g}"
            s[f"value_{lab}"] = r["value"]
            s[f"n_trades_p1_{lab}"] = r["n_trades_p1"]
            s[f"mean_p1_{lab}"] = means[r["mult"]]
            s[f"diff_se_{lab}"] = ((means[r["mult"]] - d_row["mean_roe_p1"]) / d_row["se_roe_p1"]
                                   if np.isfinite(d_row["se_roe_p1"]) and d_row["se_roe_p1"] > 0 else np.nan)
        s["shape"], s["shape_note"] = shape, why
        s["n_variants_positive_all3"] = int(sum(r["positive_all3"] for r in prs))
        shapes.append(s)
        for r in prs:
            r["shape"] = shape
    for r in rows:
        r["cell_meets_minimum"] = min_ok
        r.pop("_counts")
        r.pop("_units")
    secs["aggregate"] = round(time.time() - t0, 2)
    return dict(name=name, tf=tf, excluded=None, variants=rows, shapes=shapes, default_check=checks, seconds=secs)


def aggregate_B(names, tfs, procs: int, log=print) -> dict:
    t0 = time.time()
    L = _lib()
    codes = {nm: i for i, nm in enumerate(strategy_names(L))}
    sel = [tf for tf in TFS_B if tf in tfs]
    ckpt_sigs = {f"{tf} {c}": job_signature(tf, c) for tf in sel for c in COINS}
    tasks = [(nm, tf, codes[nm], {c: ckpt_sigs[f"{tf} {c}"] for c in COINS}) for tf in sel for nm in names]
    res = []
    for i, r in enumerate(_map(agg_B_cell, tasks, procs)):
        res.append(r)
        if log:
            log(f"[{time.time() - t0:6.0f}s] B aggregate {i + 1}/{len(tasks)} {r['name']} {r['tf']} "
                f"{r['seconds']['aggregate']}s", flush=True)
    order = {(nm, tf): (TFS.index(tf), codes[nm]) for nm in names for tf in sel}
    res.sort(key=lambda r: order[(r["name"], r["tf"])])
    cells = pd.DataFrame([c for r in res for c in r["cells"]])
    rnd = pd.DataFrame([c for r in res for c in r["random"]])
    quint = pd.DataFrame([c for r in res for c in r["quintiles"]])
    per_cell = [dict(strategy=r["name"], tf=r["tf"], part="B", **r["seconds"]) for r in res]
    selection = dict(strategies=list(names), tfs=sel)
    if not cells.empty:
        cells = decide_B(cells)
    return dict(cells=cells, random=rnd, quintiles=quint, per_cell=per_cell, selection=selection,
                ckpt_sigs=ckpt_sigs, wall_s=round(time.time() - t0, 1))


B_DECISION_COLS = ("p_for_bh", "bh_rank", "bh_threshold", "bh_qvalue", "pass_p1_bh", "pass_p2", "verdict_p3",
                   "pass_p3", "candidate", "random_p_same_dir_p1", "random_same_effect_p1", "label")


def decide_B(cells: pd.DataFrame) -> pd.DataFrame:
    """BH over all B tests (tested cells x features) in period 1, then the period-2 and period-3 rules, the
    candidate flag and the random-null label (PREREG 1 / 3)."""
    t = cells[cells["tested"]].copy()
    if len(t):
        t["p_for_bh"] = np.where(t["status_p1"] == "ok", t["p_p1"], 1.0)
        rej, rank, adj = bh(t["p_for_bh"].to_numpy(float), FDR_Q)
        t["bh_rank"], t["bh_threshold"], t["bh_qvalue"] = rank, FDR_Q * rank / len(t), adj
        t["pass_p1_bh"] = rej & (t["rho_p1"] > 0)
        t["pass_p2"] = t["pass_p1_bh"] & (t["status_p2"] == "ok") & (t["rho_p2"] > 0) & (t["p_p2"] < CONFIRM_ALPHA)
        # period 3 is judged only with >= MIN_TRADES trades with a finite value there (status 'ok'; part A's rule)
        p3_ok = (t["status_p3"] == "ok") & np.isfinite(t["rho_p3"].astype(float))
        t["verdict_p3"] = np.where(~p3_ok, "no data", np.where(t["rho_p3"] > 0, "same sign", "opposite sign"))
        t["pass_p3"] = t["pass_p2"] & (t["verdict_p3"] == "same sign")
        t["candidate"] = t["pass_p3"]
        sgn = np.sign(t["rho_p1"].astype(float))
        rs = np.sign(t["random_rho_p1"].astype(float))
        p_dir = np.where(sgn > 0, t["random_p_pos_p1"], np.where(sgn < 0, t["random_p_neg_p1"], np.nan))
        t["random_p_same_dir_p1"] = p_dir
        t["random_same_effect_p1"] = (sgn != 0) & (rs == sgn) & (p_dir < RANDOM_ALPHA)
        t["label"] = np.where(t["candidate"] & t["random_same_effect_p1"],
                              "candidate, but the random null shows the same effect: market-wide, not the strategy",
                              np.where(t["candidate"], "candidate", ""))
        cells = cells.merge(t[["strategy", "tf", "feature"] + list(B_DECISION_COLS)],
                            on=["strategy", "tf", "feature"], how="left")
    else:
        for c in B_DECISION_COLS:
            cells[c] = None
    cells["note"] = cells["strategy"].map(A.STRATEGY_NOTES).fillna("")
    return cells


def exclude_strategy_wide(res: list) -> dict:
    """PREREG 4: a strategy whose default re-implementation differs from the locked signal on any coin or timeframe
    is removed from C, so its other timeframes are excluded too (variants and shapes dropped, reason recorded)."""
    bad = {}
    for r in res:
        if r["excluded"]:
            bad.setdefault(r["name"], []).append(f"{r['tf']}: {r['excluded']}")
    for r in res:
        if r["name"] in bad and not r["excluded"]:
            r["excluded"] = "strategy excluded from C (PREREG 4): " + "; ".join(bad[r["name"]])
            r["variants"], r["shapes"] = [], []
    return bad


def aggregate_C(names, tfs, procs: int, log=print) -> dict:
    t0 = time.time()
    L = _lib()
    codes = {nm: i for i, nm in enumerate(strategy_names(L))}
    sel = [tf for tf in TFS_C if tf in tfs]
    ckpt_sigs = {f"{tf} {c}": job_signature(tf, c) for tf in sel for c in COINS}
    tasks = [(nm, tf, codes[nm], {c: ckpt_sigs[f"{tf} {c}"] for c in COINS}) for tf in sel for nm in names]
    res = []
    for i, r in enumerate(_map(agg_C_cell, tasks, procs)):
        res.append(r)
        if log:
            log(f"[{time.time() - t0:6.0f}s] C aggregate {i + 1}/{len(tasks)} {r['name']} {r['tf']} "
                f"{r['seconds']['aggregate']}s", flush=True)
    order = {(nm, tf): (TFS.index(tf), codes[nm]) for nm in names for tf in sel}
    res.sort(key=lambda r: order[(r["name"], r["tf"])])
    exclude_strategy_wide(res)
    variants = pd.DataFrame([v for r in res for v in r["variants"]])
    shapes = pd.DataFrame([s for r in res for s in r["shapes"]])
    if len(variants):
        variants["note"] = variants["strategy"].map(A.STRATEGY_NOTES).fillna("")
    excluded = [dict(strategy=r["name"], tf=r["tf"], reason=r["excluded"]) for r in res if r["excluded"]]
    checks = [dict(strategy=r["name"], tf=r["tf"], series=k, **x) for r in res for k, x in r["default_check"].items()]
    per_cell = [dict(strategy=r["name"], tf=r["tf"], part="C", **r["seconds"]) for r in res]
    return dict(variants=variants, shapes=shapes, excluded=excluded, default_checks=checks, per_cell=per_cell,
                selection=dict(strategies=list(names), tfs=sel), ckpt_sigs=ckpt_sigs,
                wall_s=round(time.time() - t0, 1))


# ------------------------------------------------------------------ outputs
def _records(df: pd.DataFrame) -> list:
    return [{k: A._num(v) for k, v in r.items()} for r in df.to_dict("records")] if len(df) else []


def trials_table(agg: dict) -> pd.DataFrame:
    rows = []
    B = agg.get("B")
    if B is not None and len(B["cells"]):
        for r in B["cells"][B["cells"]["tested"]].to_dict("records"):
            rows.append(dict(
                trial_id=f"B-{r['strategy']}-{r['tf']}-{r['feature']}", part="B", strategy=r["strategy"], tf=r["tf"],
                feature=r["feature"], higher_is_stronger=r["higher_is_stronger"],
                hypothesis=f"Spearman rho({'' if r['higher_is_stronger'] else '-'}{r['feature']}, ROE) > 0",
                **{f"{k}_p{p}": r[f"{s}_p{p}"] for p in PERIODS
                   for k, s in (("n", "n_finite"), ("stat", "rho"), ("p", "p"), ("status", "status"))},
                bh_rank=r["bh_rank"], bh_qvalue=r["bh_qvalue"], pass_p1_bh=r["pass_p1_bh"], pass_p2=r["pass_p2"],
                verdict_p3=r["verdict_p3"], candidate=r["candidate"],
                random_same_effect_p1=r["random_same_effect_p1"], label=r["label"], note=r["note"]))
    C = agg.get("C")
    if C is not None and len(C["variants"]):
        for r in C["variants"][~C["variants"]["is_default"]].to_dict("records"):
            rows.append(dict(
                trial_id=f"C-{r['strategy']}-{r['tf']}-{r['param']}-x{r['mult']:g}", part="C", strategy=r["strategy"],
                tf=r["tf"], param=r["param"], mult=r["mult"], value=r["value"],
                hypothesis="variant (one parameter changed) mean ROE per trade, periods 1-3; never adopted",
                **{f"{k}_p{p}": r[f"{s}_p{p}"] for p in PERIODS
                   for k, s in (("n", "n_trades"), ("stat", "mean_roe"), ("se", "se_roe"))},
                shape=r["shape"], positive_all3=r["positive_all3"], prob_random_all3=r.get("prob_random_all3"),
                prob_random_all3_k=r.get("prob_random_all3_k"), prob_random_all3_text=r.get("prob_random_all3_text"),
                prob_noedge_block_all3=r.get("prob_noedge_block_all3"),
                cell_meets_minimum=r["cell_meets_minimum"], note=r["note"]))
    return pd.DataFrame(rows)


def candidates_doc(agg: dict) -> dict:
    doc = dict(note="A candidate is not a rule change; it can only go to a Q7 copy-account proposal. Part C adopts no "
                    "variant (PREREG 4).")
    B = agg.get("B")
    if B is not None:
        c = B["cells"]
        t = c[c["tested"]] if len(c) else c
        doc["B"] = dict(
            definition="period-1 BH (FDR 10 %, all B tests: tested cells x features) with rho > 0 -> period 2 rho > 0 "
                       "and one-sided p < 0.05 -> period 3 rho > 0 (>= 30 trades with a finite value, else "
                       "'no data').",
            cells_total=int(c[["strategy", "tf"]].drop_duplicates().shape[0]) if len(c) else 0,
            cells_tested=int(t[["strategy", "tf"]].drop_duplicates().shape[0]) if len(t) else 0,
            tests=int(len(t)), insufficient_in_period1=int((t["status_p1"] != "ok").sum()) if len(t) else 0,
            bh_survivors_period1=int(t["pass_p1_bh"].fillna(False).astype(bool).sum()) if len(t) else 0,
            passing_period2=int(t["pass_p2"].fillna(False).astype(bool).sum()) if len(t) else 0,
            passing_period3=int(t["pass_p3"].fillna(False).astype(bool).sum()) if len(t) else 0,
            period3_no_data_among_period2_passers=int((t["pass_p2"].fillna(False).astype(bool)
                                                       & (t["verdict_p3"] == "no data")).sum()) if len(t) else 0,
            random_same_effect_among_bh_survivors=int((t["pass_p1_bh"].fillna(False).astype(bool)
                                                       & t["random_same_effect_p1"].fillna(False).astype(bool)).sum())
            if len(t) else 0,
            candidates=_records(t[t["candidate"].fillna(False).astype(bool)]) if len(t) else [],
            bh_survivors=_records(t[t["pass_p1_bh"].fillna(False).astype(bool)]) if len(t) else [])
    C = agg.get("C")
    if C is not None:
        v, s = C["variants"], C["shapes"]
        var = v[~v["is_default"]] if len(v) else v
        pos = var[var["positive_all3"]] if len(var) else var
        vmin = var[var["cell_meets_minimum"].astype(bool)] if len(var) else var

        def _sum(df, col):
            return float(df[col].astype(float).sum(skipna=True)) if len(df) else 0.0

        def _n(df, col):
            return int(df[col].astype(float).notna().sum()) if len(df) else 0
        doc["C"] = dict(
            definition="per strategy x timeframe (pooled coins): variants (one parameter x0.5 / x0.75 / x1.25 / x1.5) "
                       "with mean ROE per trade > 0 in periods 1, 2 and 3, and the probability that random entries "
                       "with the same trade counts show that (for every variant with trades in all three periods; "
                       "summed = expected number by chance); shapes from period 1.",
            variants=int(len(var)), variants_positive_all3=int(len(pos)),
            variants_positive_all3_in_cells_meeting_minimum=int(pos["cell_meets_minimum"].sum()) if len(pos) else 0,
            expected_positive_all3_under_random=_sum(var, "prob_random_all3"),
            expected_positive_all3_under_random_in_cells_meeting_minimum=_sum(vmin, "prob_random_all3"),
            expected_positive_all3_noedge_block=_sum(var, "prob_noedge_block_all3"),
            expected_positive_all3_noedge_block_in_cells_meeting_minimum=_sum(vmin, "prob_noedge_block_all3"),
            variants_with_chance_estimate=_n(var, "prob_random_all3"),
            variants_with_chance_estimate_in_cells_meeting_minimum=_n(vmin, "prob_random_all3"),
            chance_note="expected_* = sum over variants of the per-variant probability (variants without trades in "
                        "some period count 0). 'under_random' treats trades as independent random entries (a lower "
                        "bound); 'noedge_block' keeps each variant's own week clustering (descriptive). "
                        "prob_random_all3 = 0 means no draw of 2,000 qualified ('< 1/2000').",
            defaults_positive_all3=int(v[v["is_default"]]["positive_all3"].sum()) if len(v) else 0,
            shapes={k: int(n) for k, n in s["shape"].value_counts().items()} if len(s) else {},
            excluded=C["excluded"],
            positive_all3=_records(pos[["strategy", "tf", "param", "mult", "value", "cell_meets_minimum", "shape",
                                        "prob_random_all3", "prob_random_all3_k", "prob_random_all3_text",
                                        "prob_random_all3_upper", "prob_noedge_block_all3"]
                                       + [f"{k}_p{p}" for p in PERIODS
                                                               for k in ("n_trades", "mean_roe", "se_roe")]])
            if len(pos) else [])
    return doc


PART_FILES = {"B": ("bc_B_cells.csv", "bc_B_quintiles.csv", "bc_B_random.csv"),
              "C": ("bc_C_variants.csv", "bc_C_shapes.csv")}


def write_outputs(agg: dict, out_dir: str, meta: dict) -> list:
    """Write the outputs of the parts in agg; the files of a part not in agg are removed (never left from an
    earlier run next to this run's meta). Returns the removed paths."""
    os.makedirs(out_dir, exist_ok=True)
    removed = []
    for part, files in PART_FILES.items():
        if agg.get(part) is None:
            for f in files:
                path = os.path.join(out_dir, f)
                if os.path.exists(path):
                    os.remove(path)
                    removed.append(path)
    B, C = agg.get("B"), agg.get("C")
    if B is not None:
        B["cells"].to_csv(os.path.join(out_dir, "bc_B_cells.csv"), index=False)
        B["quintiles"].to_csv(os.path.join(out_dir, "bc_B_quintiles.csv"), index=False)
        B["random"].to_csv(os.path.join(out_dir, "bc_B_random.csv"), index=False)
    if C is not None:
        C["variants"].to_csv(os.path.join(out_dir, "bc_C_variants.csv"), index=False)
        C["shapes"].to_csv(os.path.join(out_dir, "bc_C_shapes.csv"), index=False)
    trials_table(agg).to_csv(os.path.join(out_dir, "bc_trials.csv"), index=False)
    with open(os.path.join(out_dir, "bc_candidates.json"), "w") as fh:
        json.dump(A._clean(candidates_doc(agg)), fh, indent=1)
    with open(os.path.join(out_dir, "bc_run_meta.json"), "w") as fh:
        json.dump(A._clean(dict(meta, removed_stale_outputs=removed)), fh, indent=1)
    return removed


# ------------------------------------------------------------------ saved aggregations (combining parts)
def agg_path(tag: str, part: str, agg_dir: str = AGG_DIR) -> str:
    return os.path.join(agg_dir, f"{tag}_{part}.pkl")


def save_agg(path: str, res: dict) -> None:
    rec = dict(code=CODE_HASH, ckpt_sigs=dict(res.get("ckpt_sigs", {})), selection=res.get("selection"), res=res)
    _atomic_write(path, lambda fh: pickle.dump(rec, fh, protocol=pickle.HIGHEST_PROTOCOL))


def load_agg_compatible(path: str, part: str, names, tfs) -> tuple:
    """(res, None) when the saved aggregation of `part` was made by this code (CODE_HASH), from checkpoints whose
    signatures are still current, and for the same strategies and timeframes as this invocation; else (None, why)."""
    if not os.path.exists(path):
        return None, "no saved aggregation"
    try:
        with open(path, "rb") as fh:
            rec = pickle.load(fh)
    except Exception as e:
        return None, f"unreadable ({type(e).__name__})"
    if not isinstance(rec, dict) or "res" not in rec or "code" not in rec:
        return None, "saved without a code hash (older format)"
    if rec["code"] != CODE_HASH:
        return None, f"made by other code ({str(rec['code'])[:16]} != {CODE_HASH[:16]})"
    want = dict(strategies=list(names), tfs=[tf for tf in (TFS_B if part == "B" else TFS_C) if tf in tfs])
    sel = rec.get("selection") or {}
    if list(sel.get("strategies", [])) != want["strategies"] or list(sel.get("tfs", [])) != want["tfs"]:
        return None, f"other selection ({sel} != {want})"
    sigs = rec.get("ckpt_sigs") or {}
    need = {f"{tf} {c}" for tf in want["tfs"] for c in COINS}
    if set(sigs) != need:
        return None, "checkpoint signatures missing"
    changed = [k for k, v in sigs.items() if job_signature(*k.split(" ")) != v]
    if changed:
        return None, f"checkpoints or data changed since it was made: {changed}"
    return rec["res"], None


def skipped_items(agg: dict) -> dict:
    out = {}
    B = agg.get("B")
    if B is not None and len(B["cells"]):
        c = B["cells"]
        out["B_cells_not_tested"] = _records(c.loc[~c["tested"], ["strategy", "tf", "feature", "n_signals_p1",
                                                                  "not_tested_reason"]])
        out["B_tests_insufficient"] = [dict(strategy=r["strategy"], tf=r["tf"], feature=r["feature"], period=p,
                                            n_finite=r[f"n_finite_p{p}"], reason=f"< {MIN_TRADES} trades with a finite value")
                                       for r in c[c["tested"]].to_dict("records") for p in PERIODS
                                       if r[f"status_p{p}"] == "insufficient"]
        out["B_signals_nan_feature"] = int(sum(c[f"n_signals_nan_p{p}"].sum() for p in PERIODS))
    C = agg.get("C")
    if C is not None:
        out["C_excluded"] = C["excluded"]
        v = C["variants"]
        if len(v):
            out["C_variants_without_period1_trades"] = _records(v.loc[(~v["is_default"]) & (v["n_trades_p1"] == 0),
                                                                     ["strategy", "tf", "param", "mult", "value"]])
            out["C_shapes_insufficient"] = _records(C["shapes"].loc[C["shapes"]["shape"] == "insufficient",
                                                                    ["strategy", "tf", "param", "shape_note"]])
        out["C_default_mismatches"] = [x for x in C["default_checks"] if x["mismatch_post_warmup"]]
    return out


# ------------------------------------------------------------------ CLI
def parse_args(argv: list[str]) -> dict:
    a = dict(cmd=None, part=None, procs=3, only=None, tfs=None)
    pos, i = [], 1
    while i < len(argv):
        tok = argv[i]
        if tok in ("--only", "--tfs"):
            vals = []
            i += 1
            while i < len(argv) and not argv[i].startswith("--"):
                vals += [x for x in argv[i].split(",") if x]
                i += 1
            a[tok[2:]] = vals
            continue
        pos.append(tok)
        i += 1
    if len(pos) < 2 or pos[0] not in ("run", "jobs", "aggregate") or pos[1] not in ("B", "C", "all"):
        raise SystemExit(__doc__)
    a["cmd"], a["part"] = pos[0], pos[1]
    if len(pos) > 2:
        a["procs"] = int(pos[2])
    return a


def _timings_path(tag: str) -> str:
    return os.path.join(RUN_DIR, f"timings_{tag}.json")


def main(argv: list[str]) -> None:
    a = parse_args(argv)
    t_start = time.time()
    prereg = check_prereg()
    data_src = require_default_data()
    L = _lib()                                    # sweepsig hash check of the locked signal code
    all_names = strategy_names(L)
    defs = require_defs(all_names)                # refuse before anything runs (manifest pinned, every file hashed)
    defs["manifest_git"] = manifest_git_check()   # the pinned manifest hash = the bytes committed in 520dad0
    names = all_names if a["only"] is None else a["only"]
    bad = [n for n in names if n not in all_names]
    if bad:
        raise SystemExit(f"unknown strategies: {bad}")
    names = [n for n in all_names if n in names]
    tfs = list(TFS) if a["tfs"] is None else a["tfs"]
    bad = [t for t in tfs if t not in TFS]
    if bad:
        raise SystemExit(f"unknown timeframes: {bad} (use {TFS})")
    parts = list(PARTS) if a["part"] == "all" else [a["part"]]
    full = a["only"] is None and a["tfs"] is None
    tag = "full" if full else "subset"
    out_dir = OUT if full else SUBSET_OUT
    tp = _timings_path(tag)
    timings = json.load(open(tp)) if os.path.exists(tp) else {}
    need_tfs = sorted({tf for p in parts for tf in (TFS_B if p == "B" else TFS_C) if tf in tfs}, key=TFS.index)
    fp_tfs = [tf for tf in TFS if tf in tfs]
    fp0 = source_fingerprints(fp_tfs)             # the data this invocation starts from

    if a["cmd"] in ("run", "jobs"):
        timings["bases"] = ensure_bases(need_tfs, a["procs"])
        for part in parts:
            jobs = part_jobs(part, names, tfs)
            jobs.sort(key=lambda j: TFS.index(j[1]))
            sigs = {(tf, c): job_signature(tf, c) for tf in need_tfs for c in COINS}
            print(f"part {part}: {len(jobs)} jobs", flush=True)
            r = run_jobs(jobs, JOB_FN[part], lambda j, part=part: ckpt_path(part, *j),
                         lambda j: sigs[(j[1], j[2])], a["procs"])
            timings[f"jobs_{part}"] = dict(jobs=r["jobs"], run=r["run"], resumed=r["resumed"], wall_s=r["wall_s"],
                                           procs=a["procs"])
            os.makedirs(RUN_DIR, exist_ok=True)
            json.dump(A._clean(timings), open(tp, "w"), indent=1)

    if a["cmd"] in ("run", "aggregate"):
        stale = stale_bases(need_tfs)             # the aggregation reads the bases (random pools) and checkpoints
        if stale:
            raise SystemExit(f"refusing to aggregate: bases missing, built by other code or on other source files: "
                             f"{stale}; rerun 'jobs' (or 'run')")
        agg, provenance, dropped = {}, {}, {}
        for part in parts:
            res = (aggregate_B if part == "B" else aggregate_C)(names, tfs, a["procs"])
            agg[part] = res
            save_agg(agg_path(tag, part), res)
            provenance[part] = dict(source="aggregated in this invocation", code=CODE_HASH,
                                    selection=res["selection"])
            timings[f"aggregate_{part}"] = dict(wall_s=res["wall_s"], procs=a["procs"])
        for part in PARTS:                        # combine with the other part's saved aggregation only if current
            if part in agg:
                continue
            res, why = load_agg_compatible(agg_path(tag, part), part, names, tfs)
            if res is None:
                dropped[part] = why
                print(f"part {part} left out of the outputs: {why} (run 'aggregate {part}' or 'aggregate all' with "
                      f"the same selection to include it)", flush=True)
                continue
            agg[part] = res
            provenance[part] = dict(source=f"saved aggregation {agg_path(tag, part)}", code=CODE_HASH,
                                    selection=res["selection"])
        json.dump(A._clean(timings), open(tp, "w"), indent=1)
        fp1 = source_fingerprints(fp_tfs)
        changed = sorted(k for k in fp0 if fp0[k] != fp1.get(k))
        if changed:
            raise SystemExit(f"refusing to write outputs: source files changed during this invocation: {changed}")
        per_cell = [x for p in PARTS if p in agg for x in agg[p]["per_cell"]]
        meta = dict(
            script="research/entry_study/analysis_bc.py", version=VERSION, git_head=A._git_head(),
            run=dict(tag=tag, restricted_to=dict(only=a["only"], tfs=a["tfs"]),
                     warning="" if full else "restricted run (pilot): not the pre-registered BH family; outputs are "
                                             "kept in the scratch directory, not in out/",
                     parts_in_outputs={p: agg[p].get("selection") for p in PARTS if p in agg},
                     parts_provenance=provenance, parts_left_out=dropped),
            **prereg, defs_bc=defs, signal_lock=sweepsig.verify()["prereg_sha256_file"],
            code=dict(code_hash=CODE_HASH, code_signature=code_signature(), version=VERSION,
                      base_version=BASE_VERSION, files=CODE_FILES,
                      changed_on_disk_since_import=sorted(k for k, v in _hash_code()[1].items()
                                                          if CODE_FILES.get(k) != v),
                      libraries=dict(numpy=np.__version__, pandas=pd.__version__, python=sys.version.split()[0])),
            seeds=dict(
                random_entries="analysis_sr.random_bars: np.random.default_rng([20260930, tf_minutes, coin_index "
                               "(BTC, ETH, SOL, DOGE, LTC, BCH = 0..5), period]); choice(eligible, min(20000, "
                               "eligible), replace=False), then random(k) < 0.5 -> long",
                B_bootstrap=f"np.random.default_rng([{BOOT_SEED}, 2, unit (strategy index 0..35; its random null "
                            f"1000 + index), tf_index (5m..4h = 0..4), feature_index, period]); "
                            f"analysis_sr.boot_counts(W, 2000)",
                C_se=f"np.random.default_rng([{BOOT_SEED}, 3, strategy_index, tf_index, param_index + 1 (0 = default), "
                     f"mult_index (0..3; default 0), period]); analysis_sr.boot_counts(W, 2000)",
                C_random=f"np.random.default_rng([{BOOT_SEED}, 4, strategy_index, tf_index, param_index + 1, "
                         f"mult_index]); integers(0, pool, (draws, n_trades)) per period and coin (coins in "
                         f"BTC..BCH order); periods 1, 2, 3 in order, stopping once no draw is left",
                C_noedge=f"np.random.default_rng([{BOOT_SEED}, 5, strategy_index, tf_index, param_index + 1, "
                         f"mult_index, period]); analysis_sr.boot_counts(W, 2000) on the variant's own weeks"),
            constants=dict(periods=PERIODS, tfs_B=TFS_B, tfs_C=TFS_C, random_n=RANDOM_N, bootstrap_resamples=BOOT_B,
                           min_signals=MIN_SIGNALS, min_trades_for_p=MIN_TRADES,
                           min_trades_for_p3_verdict=MIN_TRADES,
                           fdr_q=FDR_Q, confirm_alpha=CONFIRM_ALPHA, random_alpha=RANDOM_ALPHA, multipliers=MULTS,
                           flat_se=FLAT_SE, spike_se=SPIKE_SE, quintile_quantiles=QUANTS,
                           lookahead_passes=A.PASSES),
            data=dict(periods_1_2=A.SIG12, period_3=A.SIG3, volume_periods_1_2=os.path.join(A.SWEEP, "full"),
                      run_dir=RUN_DIR, out_dir=out_dir, source_fingerprints=fp1, data_settings=data_src,
                      checkpoint_signatures={p: agg[p].get("ckpt_sigs") for p in PARTS if p in agg}),
            timings=dict(stages=timings, per_strategy_tf=per_cell, this_invocation_s=round(time.time() - t_start, 1)),
            skipped=skipped_items(agg), ambiguities=list(AMBIGUITIES), strategy_notes=dict(A.STRATEGY_NOTES))
        write_outputs(agg, out_dir, meta)
        print(json.dumps(A._clean(dict(B=candidates_doc(agg).get("B", {}).get("tests"),
                                       C=candidates_doc(agg).get("C", {}).get("variants"), out=out_dir)), indent=1),
              flush=True)


if __name__ == "__main__":
    main(sys.argv)
