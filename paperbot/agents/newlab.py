"""New-strategy lab: agents invent strategies in a fixed grammar, code tests them (no AI calls here).

Pre-registered in docs/newlab-prereg.md (sha256 in docs/newlab-prereg.sha256); this module follows it.

Grammar (``normalize_spec``; tables in paperbot/agents/newlab_signals.py):
  {"timeframe": "5m|15m|30m|1h|4h",
   "entry": {"family": <one of 30 library triggers>, "params": {...one allowed value set...}},
   "filters": [<0..2 of trend_ema, adx, htf_trend, vol_regime, session, distinct kinds>],
   "direction": "long|short|both"}            (+ free-text "name"/"idea", not part of the strategy)
  Exits are never part of a spec: always the paper v3 rules (next-bar-open entry, 2 x ATR14 stop,
  20-50x size_position, stepped profit lock, real costs), so a passing strategy runs as a paper
  account unchanged. ``spec_hash`` of the canonical form: the same strategy is never tested twice.

Outcomes: every signal on the six coins through ``labtests.signal_outcomes`` (profiles.py
_sizer/_scan, the lab's own machinery), periods = labtests.PERIODS. Coin-flip baseline: per coin and
period the same number of entries on random eligible bars, the strategy's own long/short mix,
same exits, ``COINFLIP_REPS`` replicates.

Gate (``gate(result, n_tests_so_far)``; n = new-strategy tests run before this one, all rooms,
kept by the caller's ledger): see GATE_HELP_KO / the prereg. P1 uses a 100,000-resample
week-block bootstrap so tests up to the 5,000th can still pass (``max_passable_n``).

Public for the room wiring: normalize_spec, spec_hash, describe_ko, grammar_help_ko, run_new_strategy,
gate, counts_as_test, ledger_row, proposal_of, max_passable_n, SpecError.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections import OrderedDict
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd

from .. import sweepsig
from . import labtests as LT
from . import newlab_signals as NS
from .newlab_signals import DIRECTIONS, FAMILIES, FILTERS, MAX_FILTERS, TFS

GRAMMAR_VERSION = "newlab-v1"
PREREG = "docs/newlab-prereg.md"
ALPHA = 0.05
N_BOOT_P1 = 100_000                  # P1 one-sample bootstrap (fine enough for 0.05 / (n + 1))
N_BOOT = 2_000                       # P2, P3 and the coin-flip comparison (as labtests)
P_FLOOR_P1 = 1 / (N_BOOT_P1 + 1)
MIN_TRADES_P1, MIN_TRADES_P2, MIN_TRADES_P3 = 300, 100, 30
COINFLIP_REPS = 10
PERIODS = LT.PERIODS                 # ("1", 2021-08-01, 2024-07-01, main), ("2", .., 2026-09-30), ("3", 2020-01-01, ..)
NOTE_KEYS = ("name", "idea")
EXIT_KEYS = ("exit", "exits", "stop", "stop_atr", "sl", "tp", "take_profit", "leverage", "lev", "ladder",
             "lock", "first_lock", "trailing", "size", "sizing")


class SpecError(ValueError):
    """A strategy outside the grammar (Korean message). Not run, not counted."""


def max_passable_n() -> int:
    """Largest n_tests_so_far at which gate (a) can still pass: 0.05 / (n + 1) > 1 / (N_BOOT_P1 + 1)."""
    n = int(ALPHA * (N_BOOT_P1 + 1)) - 1
    while ALPHA / (n + 2) > P_FLOOR_P1:
        n += 1
    while n >= 0 and not ALPHA / (n + 1) > P_FLOOR_P1:
        n -= 1
    return n


# ---------------------------------------------------------------------------------------------
# grammar
# ---------------------------------------------------------------------------------------------
def _word(x: Any) -> Optional[str]:
    return x.strip().lower() if isinstance(x, str) else None


def _match(v: Any, allowed: Iterable) -> Any:
    """The allowed value equal to v (numbers by value, words case-insensitively), else KeyError."""
    for a in allowed:
        if isinstance(a, str):
            if _word(v) == a:
                return a
        elif isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v)) \
                and abs(float(v) - float(a)) < 1e-9:
            return a
    raise KeyError(v)


def _fmt_allowed(vals) -> str:
    return ", ".join(str(v) for v in vals)


def normalize_spec(spec: Any) -> dict:
    """The canonical form of a strategy, or SpecError with a Korean message."""
    if isinstance(spec, str):
        try:
            spec = json.loads(spec)
        except ValueError:
            raise SpecError("매매법은 JSON 객체여야 합니다.") from None
    if not isinstance(spec, dict):
        raise SpecError("매매법은 JSON 객체여야 합니다.")
    keys = set(spec)
    bad_exit = sorted(k for k in keys if _word(k) in EXIT_KEYS)
    if bad_exit:
        raise SpecError("청산·손절·레버리지는 고를 수 없습니다. 항상 paper v3 규칙(2 ATR 손절, 20~50배 자동, "
                        f"계단식 익절)입니다. 빼 주세요: {', '.join(bad_exit)}.")
    unknown = sorted(keys - {"timeframe", "entry", "filters", "direction", "v", *NOTE_KEYS})
    if unknown:
        raise SpecError(f"모르는 칸입니다: {', '.join(map(str, unknown))}. 쓸 수 있는 칸: timeframe, entry, filters, "
                        "direction (설명용 name, idea).")
    if spec.get("v") not in (None, GRAMMAR_VERSION):
        raise SpecError(f"문법 버전은 {GRAMMAR_VERSION}만 됩니다.")
    tf = _word(spec.get("timeframe"))
    if tf not in TFS:
        raise SpecError(f"timeframe은 {', '.join(TFS)} 중 하나여야 합니다.")
    e = spec.get("entry")
    if isinstance(e, str):
        e = {"family": e}
    if not isinstance(e, dict) or set(e) - {"family", "params"}:
        raise SpecError('entry는 {"family": ..., "params": {...}} 형태여야 합니다.')
    fam = _word(e.get("family"))
    if fam not in FAMILIES:
        raise SpecError(f"없는 진입 신호입니다. 가능한 것: {', '.join(FAMILIES)}.")
    names, grid = FAMILIES[fam][0], FAMILIES[fam][1]
    params = e.get("params") if e.get("params") is not None else {}
    if not isinstance(params, dict):
        raise SpecError("entry.params는 객체여야 합니다.")
    want = set(names)
    if set(params) != want:
        if not names:
            raise SpecError(f"{fam}에는 값이 없습니다(params를 비워 두세요).")
        raise SpecError(f"{fam}의 params는 {', '.join(names)}을(를) 모두 정해야 합니다. 가능한 조합: "
                        + " / ".join(str(dict(zip(names, g))) for g in grid) + ".")
    hit = None
    for g in grid:
        try:
            if all(_match(params[k], (a,)) == a for k, a in zip(names, g)):
                hit = g
                break
        except KeyError:
            continue
    if hit is None:
        raise SpecError(f"{fam}의 params 조합이 허용 값이 아닙니다. 가능한 조합: "
                        + " / ".join(str(dict(zip(names, g))) for g in grid) + ".")
    entry = {"family": fam, "params": dict(zip(names, hit))}
    fl = spec.get("filters")
    fl = [] if fl is None else fl
    if isinstance(fl, dict):
        fl = [fl]
    if not isinstance(fl, list) or len(fl) > MAX_FILTERS:
        raise SpecError(f"filters는 0~{MAX_FILTERS}개의 목록이어야 합니다.")
    filters = []
    for f in fl:
        if not isinstance(f, dict):
            raise SpecError("필터는 {\"kind\": ...} 객체여야 합니다.")
        kind = _word(f.get("kind"))
        if kind not in FILTERS:
            raise SpecError(f"없는 필터입니다. 가능한 것: {', '.join(FILTERS)}.")
        allowed = FILTERS[kind][0]
        if set(f) - {"kind"} != set(allowed):
            raise SpecError(f"{kind} 필터는 {', '.join(allowed)}을(를) 정해야 합니다(다른 칸은 안 됨).")
        out = {"kind": kind}
        for p, vals in allowed.items():
            try:
                out[p] = _match(f[p], vals)
            except KeyError:
                raise SpecError(f"{kind}.{p}는 {_fmt_allowed(vals)} 중 하나여야 합니다.") from None
        filters.append(out)
    kinds = [f["kind"] for f in filters]
    if len(set(kinds)) != len(kinds):
        raise SpecError("같은 종류의 필터를 두 번 쓸 수 없습니다.")
    filters.sort(key=lambda f: f["kind"])
    d = _word(spec.get("direction")) or "both"
    if d not in DIRECTIONS:
        raise SpecError("direction은 long, short, both 중 하나여야 합니다.")
    return {"v": GRAMMAR_VERSION, "timeframe": tf, "entry": entry, "filters": filters, "direction": d}


def spec_hash(spec: dict) -> str:
    """sha256 of the canonical JSON (call on normalize_spec output; raw specs are normalised first)."""
    canon = spec if spec.get("v") == GRAMMAR_VERSION and "entry" in spec and set(spec) <= \
        {"v", "timeframe", "entry", "filters", "direction"} else normalize_spec(spec)
    s = json.dumps(canon, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def spec_notes(spec: Any) -> dict:
    if not isinstance(spec, dict):
        return {}
    return {k: str(spec[k])[:500] for k in NOTE_KEYS if isinstance(spec.get(k), str) and spec[k].strip()}


_DIR_KO = {"long": "롱만", "short": "숏만", "both": "롱·숏"}
_SESS_KO = {"asia": "아시아 시간(UTC 0~8시)", "europe": "유럽 시간(UTC 8~16시)", "us": "미국 시간(UTC 16~24시)"}


def _filter_ko(f: dict, tf: str) -> str:
    k = f["kind"]
    if k == "trend_ema":
        return f"EMA{f['length']} 추세 방향만"
    if k == "adx":
        return f"ADX {f['level']} {'이상(추세장)' if f['mode'] == 'above' else '미만(횡보장)'}만"
    if k == "htf_trend":
        from ..context import HTF
        return f"{HTF[tf]}봉 EMA{f['length']} 추세 방향만"
    if k == "vol_regime":
        return f"변동성 {'높을' if f['mode'] == 'high' else '낮을'} 때만(최근 {f['lookback']}봉 중앙값 대비)"
    if k == "session":
        return _SESS_KO[f["window"]] + "만"
    return k


def describe_ko(spec: dict) -> str:
    fam = spec["entry"]["family"]
    p = spec["entry"]["params"]
    ps = "(" + ", ".join(f"{v:g}" if isinstance(v, float) else str(v) for v in p.values()) + ")" if p else ""
    parts = [f"{spec['timeframe']} {fam}{ps} — {FAMILIES[fam][4]}", _DIR_KO[spec["direction"]]]
    parts += [_filter_ko(f, spec["timeframe"]) for f in spec.get("filters", [])]
    return ", ".join(parts)


def grammar_help_ko() -> str:
    """The grammar in plain Korean, for the prompts."""
    lines = [f"새 매매법 문법({GRAMMAR_VERSION}). JSON 하나: timeframe, entry{{family, params}}, filters(0~2개), "
             "direction. 청산은 고를 수 없음(항상 paper v3: 2 ATR 손절, 20~50배 자동, 계단식 익절).",
             f"timeframe: {', '.join(TFS)}", "direction: long, short, both", "entry.family (허용 params):"]
    for fam, (names, grid, vol, group, ko) in FAMILIES.items():
        opts = " / ".join(", ".join(f"{k}={v:g}" if isinstance(v, float) else f"{k}={v}" for k, v in zip(names, g))
                          for g in grid) if names else "값 없음"
        lines.append(f"  {fam}: {ko} [{opts}]")
    lines.append("filters (종류별 1개까지, 최대 2개):")
    for kind, (allowed, ko) in FILTERS.items():
        lines.append(f"  {kind}: {ko} [" + "; ".join(f"{p}={'|'.join(map(str, v))}" for p, v in allowed.items()) + "]")
    lines.append('예: {"timeframe": "1h", "entry": {"family": "ema_cross", "params": {"fast": 20, "slow": 50}}, '
                 '"filters": [{"kind": "trend_ema", "length": 200}], "direction": "both"}')
    return "\n".join(lines)


GATE_HELP_KO = (
    "관문(모두 통과): ① 1기간(2021-08~2024-06) 거래당 평균 ROE > 0, p < 0.05 ÷ (지금까지 새 매매법 시험 수 + 1) "
    "② 1기간 거래 300건 이상, 코인 과반 플러스 ③ 2기간(2024-07~2026-09) 플러스, p < 0.05, 100건 이상 "
    "④ 3기간(2020-01~2021-07) 자료가 있으면 30건 이상 플러스 ⑤ 자금 대비 손익 1·2기간 플러스 "
    "⑥ 1·2기간 모두 동전 던지기(같은 개수·같은 롱숏 비율의 무작위 진입)보다 나음(p < 0.05). "
    "통과해도 새 paper 계좌 제안일 뿐이며 두 분 OK가 필요합니다.")


# ---------------------------------------------------------------------------------------------
# data: bars (LabData) + volume (read here: LabData keeps only o, h, l, c, atr)
# ---------------------------------------------------------------------------------------------
_VOL: "OrderedDict[str, Optional[np.ndarray]]" = OrderedDict()


def _volume(data: LT.LabData, source: str, tf: str, coin: str) -> Optional[np.ndarray]:
    p = data.path(source, tf, coin)
    if not p or not os.path.exists(p):
        return None
    key = f"{p}|{os.path.getmtime(p)}"
    if key not in _VOL:
        with np.load(p) as z:
            _VOL[key] = np.asarray(z["v"], float) if "v" in z.files else None
        while len(_VOL) > 12:
            _VOL.popitem(last=False)
    return _VOL[key]


def strategy_signals(spec: dict, data: LT.LabData, source: str, coin: str) -> Optional[np.ndarray]:
    """int8 signals of a canonical spec on one cached series (None: no bars, or no volume when needed)."""
    b = data.bars(source, spec["timeframe"], coin)
    if b is None:
        return None
    v = _volume(data, source, spec["timeframe"], coin)
    if v is None and NS.needs_volume(spec):
        return None
    return NS.signals(spec, b["ts"], b["o"], b["h"], b["l"], b["c"], v, b["atr"])


# ---------------------------------------------------------------------------------------------
# statistics
# ---------------------------------------------------------------------------------------------
def boot_mean_p(week: np.ndarray, x: np.ndarray, n_boot: int, seed: int, chunk: int = 10_000) -> Optional[float]:
    """One-sided p that the mean per trade is <= 0: resample whole weeks (all coins' trades of a week
    together) with replacement; p = (1 + resamples with mean <= 0) / (n_boot + 1)."""
    x = np.asarray(x, float)
    if not len(x):
        return None
    weeks, inv = np.unique(np.asarray(week), return_inverse=True)
    W = len(weeks)
    s, c = np.bincount(inv, x, W), np.bincount(inv, None, W)
    rng = np.random.default_rng(seed)
    bad = 0
    done = 0
    while done < n_boot:
        m = min(chunk, n_boot - done)
        pick = rng.integers(0, W, size=(m, W))
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = s[pick].sum(1) / c[pick].sum(1)
        bad += int((~(mean > 0)).sum())
        done += m
    return (1 + bad) / (n_boot + 1)


def _seed(h: str, tag: str) -> int:
    return int(hashlib.sha256(f"{h}|{tag}".encode()).hexdigest()[:8], 16)


def _coinflip_signals(rng, b: dict, sg: np.ndarray, lo: int, n_end: int, bounds: list) -> np.ndarray:
    """One coin-flip replicate over this cache's range: per period the same number of entries as the
    strategy's valid signals there, on random eligible bars (no repeats), the strategy's sides shuffled."""
    n = len(b["ts"])
    out = np.zeros(n, np.int8)
    a = b["atr"]
    nxt_ok = np.isfinite(b["o"][np.minimum(np.arange(n) + 1, n - 1)])
    for s0, s1 in bounds:
        s0, s1 = max(s0, lo), min(s1, n_end - 1)
        if s1 <= s0:
            continue
        seg = np.arange(s0, s1)
        ok = np.isfinite(a[seg]) & (a[seg] > 0) & nxt_ok[seg]
        elig = seg[ok]
        sides = sg[elig][sg[elig] != 0]
        m = min(len(sides), len(elig))
        if not m:
            continue
        pick = rng.choice(elig, size=m, replace=False)
        out[pick] = rng.permutation(sides)[:m]
    return out


def _period_bounds(ts: np.ndarray, pers: list) -> list:
    return [(int(np.searchsorted(ts, pd.Timestamp(s).value, side="left")),
             int(np.searchsorted(ts, pd.Timestamp(e).value, side="left"))) for _pid, s, e, _src in pers]


def _collect(spec: dict, h: str, data: LT.LabData, reps: int) -> dict:
    """Per period: strategy trades and coin-flip trades over all coins."""
    L = sweepsig.lib()
    tf = spec["timeframe"]
    acc = {pid: {"s": [], "r": [], "coins": [], "per_coin": {}, "signals": 0, "start": s, "end": e, "source": src}
           for pid, s, e, src in PERIODS}
    sizer = data.sizer(LT.BASE_K)
    for source in dict.fromkeys(p[3] for p in PERIODS):
        pers = [p for p in PERIODS if p[3] == source]
        for coin in data.coins(source, tf):
            b = data.bars(source, tf, coin)
            sg = strategy_signals(spec, data, source, coin)
            if b is None or sg is None:
                continue
            lo, n_end = LT._source_range(L, b["ts"], tf, pers)
            if n_end - 1 <= lo:
                continue
            bounds = _period_bounds(b["ts"], pers)
            starts = np.array([pd.Timestamp(p[1]).value for p in pers[1:]], np.int64)

            def split(out):
                lab = np.searchsorted(starts, b["ts"][out["idx"]], side="right")
                return lab
            so = LT.signal_outcomes(b, sg, lo, n_end, tf, sizer=sizer)
            lab = split(so)
            rnd = []
            rng = np.random.default_rng(_seed(h, f"coinflip|{source}|{coin}"))
            for _ in range(reps):
                rs = _coinflip_signals(rng, b, sg, lo, n_end, bounds)
                ro = LT.signal_outcomes(b, rs, lo, n_end, tf, sizer=sizer)
                rnd.append((ro, split(ro)))
            for k, (pid, *_r) in enumerate(pers):
                a = acc[pid]
                a["coins"].append(coin)
                m = so["done"] & (lab == k)
                a["signals"] += int((lab == k).sum())
                a["s"].append((b["ts"][so["idx"][m]], so["roe"][m], so["reason"][m], so["held"][m], so["lev"][m],
                               so["side"][m]))
                a["per_coin"][coin] = so["roe"][m]
                for ro, rl in rnd:
                    mr = ro["done"] & (rl == k)
                    a["r"].append((b["ts"][ro["idx"][mr]], ro["roe"][mr], ro["reason"][mr], ro["held"][mr],
                                   ro["lev"][mr], ro["side"][mr]))
    return acc


def _cat(parts: list) -> tuple:
    if not parts:
        return tuple(np.zeros(0, np.int64 if j == 0 else float) for j in range(6))
    return tuple(np.concatenate([p[j] for p in parts]) for j in range(6))


def _num(x) -> Optional[float]:
    return float(x) if isinstance(x, (int, float, np.floating)) and math.isfinite(float(x)) else None


def _period_rows(h: str, acc: dict) -> dict:
    out = {}
    for pid, s, e, src in PERIODS:
        a = acc[pid]
        row: dict = {"start": s, "end": e, "cache": src, "available": bool(a["coins"]), "coins": a["coins"]}
        if not a["coins"]:
            row["why"] = "자료 없음" if src == "main" else "2021년 이전 자료가 없습니다"
            out[pid] = row
            continue
        ts, roe, reason, held, lev, side = _cat(a["s"])
        row.update(LT._arm(roe, reason, held, lev))
        row["signals"] = a["signals"]
        row["long_trades"] = int((side > 0).sum())
        row["mean_roe_long"] = _num(roe[side > 0].mean()) if (side > 0).any() else None
        row["mean_roe_short"] = _num(roe[side < 0].mean()) if (side < 0).any() else None
        nb = N_BOOT_P1 if pid == "1" else N_BOOT
        row["p"] = boot_mean_p(LT.week_of(ts), roe, nb, _seed(h, f"p|{pid}")) if len(roe) else None
        row["n_boot"] = nb
        pc = {c: {"trades": int(len(r)), "mean_roe": _num(r.mean()) if len(r) else None}
              for c, r in a["per_coin"].items()}
        row["per_coin"] = pc
        traded = [c for c, x in pc.items() if x["trades"]]
        row["coins_n"] = len(traded)
        row["coins_pos"] = sum(1 for c in traded if (pc[c]["mean_roe"] or 0) > 0)
        rts, rroe, rreason, rheld, rlev, _rs = _cat(a["r"])
        cf = LT._arm(rroe, rreason, rheld, rlev)
        cf["reps"] = COINFLIP_REPS
        bb = LT.block_bootstrap(LT.week_of(rts), rroe, LT.week_of(ts), roe, N_BOOT, _seed(h, f"cf|{pid}"))
        cf["diff"], cf["p"] = bb["diff"], bb["p"]
        row["coinflip"] = cf
        out[pid] = row
    return out


# ---------------------------------------------------------------------------------------------
# run + gate
# ---------------------------------------------------------------------------------------------
def _pct(x, signed=True):
    return LT._pct(x, signed)


def _pv(p) -> str:
    p = _num(p)
    return "없음" if p is None else (f"{p:.1e}" if p < 0.001 else f"{p:.4f}")


def _failed(status: str, message: str, spec: Any, t0: float, n: int, extra: Optional[dict] = None) -> dict:
    r = {"ok": False, "status": status, "error": message, "spec": spec, "n_tests_so_far": n,
         "counts_as_test": False, "runtime_s": round(time.time() - t0, 2), **(extra or {})}
    r["gate"] = gate(r, n)
    r["summary_ko"] = f"[새 매매법 시험] 하지 못했습니다: {message}"
    return r


def run_new_strategy(spec: Any, data: Optional[LT.LabData], n_tests_so_far: int, *,
                     tested_hashes: Optional[Iterable[str]] = None, reps: int = COINFLIP_REPS) -> dict:
    """Test one new strategy. Never raises for a bad spec or missing data (``ok: False`` + Korean
    ``error``). ``n_tests_so_far``: new-strategy tests already run (global ledger, before this one).
    ``tested_hashes``: hashes already in the ledger; a repeat returns status "duplicate" (not run, not
    counted). The caller stores ledger_row(result) when counts_as_test(result)."""
    t0 = time.time()
    n = max(0, int(n_tests_so_far or 0))
    try:
        sp = normalize_spec(spec)
    except SpecError as exc:
        return _failed("bad_spec", str(exc), spec, t0, n)
    h = spec_hash(sp)
    if tested_hashes is not None and h in set(tested_hashes):
        return _failed("duplicate", "이 매매법은 이미 시험했습니다(같은 해시). 예전 결과를 보세요.", sp, t0, n,
                       {"spec_hash": h})
    if data is None or not data.available():
        return _failed("no_data", "5년 시험 자료(캐시)가 이 서버에 없습니다.", sp, t0, n, {"spec_hash": h})
    if not data.coins("main", sp["timeframe"]):
        return _failed("no_data", f"{sp['timeframe']} 시험 자료가 없습니다.", sp, t0, n, {"spec_hash": h})
    if NS.needs_volume(sp) and not any(_volume(data, "main", sp["timeframe"], c) is not None
                                        for c in data.coins("main", sp["timeframe"])):
        return _failed("no_data", "이 진입 신호는 거래량이 필요한데 시험 자료에 거래량이 없습니다.", sp, t0, n,
                       {"spec_hash": h})
    acc = _collect(sp, h, data, max(1, int(reps)))
    result = {"ok": True, "status": "done", "spec": sp, "spec_hash": h, "notes": spec_notes(spec),
              "grammar": GRAMMAR_VERSION, "prereg": PREREG, "description_ko": describe_ko(sp),
              "timeframe": sp["timeframe"], "n_tests_so_far": n, "test_number": n + 1, "counts_as_test": True,
              "exits": "paper v3 (labtests.signal_outcomes: profiles.py _sizer/_scan, 2 ATR stop, stepped lock)",
              "block": "week (Monday 00:00 UTC)", "n_boot": {"1": N_BOOT_P1, "2": N_BOOT, "3": N_BOOT,
                                                              "coinflip": N_BOOT},
              "coinflip_reps": max(1, int(reps)),
              "data": {"main_dir": data.main_dir,
                       "pre2021": bool(data.pre2021_dir and data.available("pre2021")),
                       "matches_research": data.matches_research()}}
    result["periods"] = _period_rows(h, acc)
    result["gate"] = gate(result, n)
    result["runtime_s"] = round(time.time() - t0, 2)
    result["summary_ko"] = summary_ko(result)
    return result


def counts_as_test(result: Any) -> bool:
    """True when the run belongs in the global count (it ran on data, pass or fail)."""
    return isinstance(result, dict) and result.get("ok") is True and result.get("status") == "done"


def gate(result: dict, n_tests_so_far: int) -> dict:
    """The code gate (prereg section 5). Only code decides. Re-judging a stored result with a later
    count is allowed (the P1 p was computed with 100,000 resamples)."""
    n = max(0, int(n_tests_so_far or 0))
    alpha1 = ALPHA / (n + 1)
    mp = max_passable_n()
    base = {"pass": False, "n_tests_so_far": n, "test_number": n + 1, "alpha_period1": alpha1,
            "p_floor": P_FLOOR_P1, "max_passable_n": mp, "can_pass_at_this_n": n <= mp, "checks": {}}
    floor_note = (f"이제 어떤 새 시험도 통과할 수 없습니다: 기준 p < {alpha1:.3g}가 부트스트랩 {N_BOOT_P1:,}번의 "
                  f"가장 작은 p({P_FLOOR_P1:.3g}) 이하입니다(시험 {mp + 1:,}번째까지만 통과 가능).")
    if not isinstance(result, dict) or not result.get("ok") or "periods" not in result:
        rs = ["시험이 끝나지 않아 통과할 수 없습니다."] + ([floor_note] if n > mp else [])
        return {**base, "reasons": rs}
    P = result["periods"]
    p1, p2, p3 = P.get("1", {}), P.get("2", {}), P.get("3", {})

    def num(row, *keys):
        x = row
        for k in keys:
            x = x.get(k) if isinstance(x, dict) else None
        return _num(x)

    checks, reasons = {}, []
    m1, pv1, n1 = num(p1, "mean_roe"), num(p1, "p"), int(num(p1, "trades") or 0)
    checks["a"] = m1 is not None and pv1 is not None and m1 > 0 and pv1 < alpha1
    reasons.append(f"① 1기간 거래당 평균 ROE {_pct(m1)}, p={_pv(pv1)} — 기준 p < {alpha1:.3g} (0.05 ÷ "
                   f"이 시험 번호 {n + 1:,}: 지금까지 새 매매법 {n:,}개를 시험한 만큼 엄격하게)"
                   + (f"; {floor_note}" if n > mp else "") + f": {'통과' if checks['a'] else '미달'}")
    cp, cn = int(num(p1, "coins_pos") or 0), int(num(p1, "coins_n") or 0)
    checks["b"] = n1 >= MIN_TRADES_P1 and cn > 0 and cp * 2 > cn
    reasons.append(f"② 1기간 거래 {n1:,}건(기준 {MIN_TRADES_P1}건 이상), 플러스 코인 {cp}/{cn}(과반): "
                   f"{'통과' if checks['b'] else '미달'}")
    m2, pv2, n2 = num(p2, "mean_roe"), num(p2, "p"), int(num(p2, "trades") or 0)
    checks["c"] = m2 is not None and pv2 is not None and m2 > 0 and pv2 < ALPHA and n2 >= MIN_TRADES_P2
    reasons.append(f"③ 2기간 거래당 평균 ROE {_pct(m2)}, p={_pv(pv2)}, 거래 {n2:,}건 — 기준 플러스, p < 0.05, "
                   f"{MIN_TRADES_P2}건 이상: {'통과' if checks['c'] else '미달'}")
    if p3.get("available"):
        m3, n3 = num(p3, "mean_roe"), int(num(p3, "trades") or 0)
        checks["d"] = n3 >= MIN_TRADES_P3 and m3 is not None and m3 > 0
        reasons.append(f"④ 3기간(2020-01~2021-07) 거래당 평균 ROE {_pct(m3)}, 거래 {n3:,}건 — 기준 플러스, "
                       f"{MIN_TRADES_P3}건 이상: {'통과' if checks['d'] else '미달'}")
    else:
        checks["d"] = True
        reasons.append("④ 3기간(2020-01~2021-07): 자료가 없어 판단에서 뺌")
    e1, e2 = num(p1, "mean_pnl_equity"), num(p2, "mean_pnl_equity")
    checks["e"] = e1 is not None and e2 is not None and e1 > 0 and e2 > 0
    reasons.append(f"⑤ 자금 대비 거래당 손익 1기간 {_pct(e1)}, 2기간 {_pct(e2)} — 둘 다 플러스: "
                   f"{'통과' if checks['e'] else '미달'}")
    cf_ok = []
    txt = []
    for pid, row in (("1", p1), ("2", p2)):
        d, pv = num(row, "coinflip", "diff"), num(row, "coinflip", "p")
        ok = d is not None and pv is not None and d > 0 and pv < ALPHA
        cf_ok.append(ok)
        txt.append(f"{pid}기간 동전 {_pct(num(row, 'coinflip', 'mean_roe'))} 대비 차이 {LT._pp(d)}, p={_pv(pv)}")
    checks["f"] = all(cf_ok)
    reasons.append("⑥ 동전 던지기(같은 개수·같은 롱숏 비율의 무작위 진입, 같은 청산)보다 나은지: " + ", ".join(txt)
                   + f" — 둘 다 플러스, p < 0.05: {'통과' if checks['f'] else '미달'}")
    ok = all(checks[k] for k in "abcdef")
    return {**base, "pass": bool(ok), "checks": {k: bool(v) for k, v in checks.items()}, "reasons": reasons}


def _period_label(pid: str, row: dict) -> str:
    end = (pd.Timestamp(row["end"]) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    return f"{pid}기간({row['start']}~{end})"


def summary_ko(result: dict) -> str:
    """Plain-Korean summary with code numbers only."""
    if not result.get("ok"):
        return f"[새 매매법 시험] 하지 못했습니다: {result.get('error')}"
    lines = [f"[새 매매법 시험 #{result['test_number']:,}] {result['description_ko']}"]
    for pid, row in result["periods"].items():
        lab = _period_label(pid, row)
        if not row.get("available"):
            lines.append(f"{lab}: {row.get('why', '자료 없음')}")
            continue
        cf = row.get("coinflip") or {}
        lines.append(f"{lab}: 거래 {row['trades']:,}건, 거래당 평균 ROE {_pct(row.get('mean_roe'))}, "
                     f"승률 {LT._pct(row.get('win_rate'))}, 자금 대비 {_pct(row.get('mean_pnl_equity'))}, "
                     f"p={_pv(row.get('p'))}, 플러스 코인 {row.get('coins_pos', 0)}/{row.get('coins_n', 0)}; "
                     f"동전 던지기 {_pct(cf.get('mean_roe'))} ({cf.get('trades', 0):,}건, 차이 {LT._pp(cf.get('diff'))})")
    g = result.get("gate") or {}
    lines.append("판정: " + ("통과 — 새 paper 계좌 제안 가능(두 분 OK 필요)" if g.get("pass") else "통과 못함"))
    lines += [f"  {r}" for r in g.get("reasons", [])]
    lines.append("주의: 이 5년 자료는 이미 많이 뒤진 자료입니다(라이브러리 2,000개 조합, 통과 0개). 통과해도 "
                 "진짜 확인은 paper 계좌의 새 자료입니다.")
    lines.append(f"걸린 시간 {result.get('runtime_s', 0):.1f}초")
    return "\n".join(lines)


def ledger_row(result: dict) -> dict:
    """Compact record for the caller's global ledger (store it when counts_as_test(result))."""
    g = result.get("gate") or {}
    P = result.get("periods") or {}

    def pick(pid):
        r = P.get(pid) or {}
        cf = r.get("coinflip") or {}
        return {"trades": r.get("trades"), "mean_roe": r.get("mean_roe"), "mean_pnl_equity": r.get("mean_pnl_equity"),
                "p": r.get("p"), "coinflip_diff": cf.get("diff"), "coinflip_p": cf.get("p")} if r.get("available") \
            else None
    return {"spec_hash": result.get("spec_hash"), "spec": result.get("spec"), "grammar": GRAMMAR_VERSION,
            "status": result.get("status"), "counts_as_test": counts_as_test(result),
            "test_number": result.get("test_number"), "n_tests_so_far": result.get("n_tests_so_far"),
            "pass": bool(g.get("pass")), "checks": g.get("checks"),
            "periods": {pid: pick(pid) for pid in ("1", "2", "3")}, "runtime_s": result.get("runtime_s")}


def proposal_of(result: dict, n_tests_now: Optional[int] = None) -> Optional[dict]:
    """A new-paper-account proposal for a passing result (re-judged with ``n_tests_now`` when given),
    else None. Needs the owners' OK; nothing starts by itself."""
    if not counts_as_test(result):
        return None
    g = gate(result, n_tests_now) if n_tests_now is not None else result.get("gate") or {}
    if not g.get("pass"):
        return None
    sp = result["spec"]
    return {"kind": "new_paper_account", "needs_owner_ok": True, "spec": sp, "spec_hash": result["spec_hash"],
            "timeframe": sp["timeframe"], "rules": "paper v3 (exits, sizing and costs unchanged)",
            "description_ko": result.get("description_ko"), "gate": g,
            "summary_ko": ("새 매매법이 5년 시험 관문을 통과했습니다. 같은 규칙(paper v3)의 새 paper 계좌로 "
                           "새 자료에서 확인하자는 제안입니다. 두 분 OK가 있어야 시작합니다.\n"
                           + result.get("summary_ko", ""))}
