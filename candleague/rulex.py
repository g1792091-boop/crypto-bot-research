"""후보 리그 규칙 계좌 (rule accounts): a pick's own entries, hard stop and sizing with a RULE exit on top, in a league
of their own (research/exitflex/PREREG_EXITFLEX.md sections 4, 5 and 11; the generic mechanism, no variant chosen here).

What this module is
-------------------
* **Rule interface** (``parse_rule``): the study's ids, "F1.w3.a", "F1.w3.b.q15", "F2.n20.b", "F3.a", "F4.m1.5.a",
  "F5.P1.5.g25.a", "F6.w2.d0.5", "F7.N24.b", "F8.w3.P1.a", "F9.b.q15", "F10.N6.a" (or a dict with ``family`` and the
  parameters), plus a plug-in family "F11" for the strategy's own exit arrays (below). Mode "a" keeps the pick's own
  take-profit, mode "b" has no take-profit and no lock; q15 checks on 15m closes for picks on 1h and 4h.
* **Engine** (``RuleMixin``, ``RuleEngine``, ``RuleLadderEngine``, ``make_engine``): a PaperEngine whose ``step`` runs
  funding -> RULE exit -> entries -> the engine's normal exit handling (stop, liquidation, take-profit, range checks).
  A rule decided from the chart closes handed in since the last minute is a market order at this minute's open
  (slippage, taker fee, reason "RULE"). The decision is computed from state frozen before the minute (the favourable
  extreme X and its time T_X over the earlier minutes, the funding paid before it, chart bars closed by the check
  close), executed after this minute's funding, and only when the open gaps past neither liquidation (mark), the stop
  nor the take-profit: a gapped open is left to the engine's own exit handling, so entries at that minute stay
  blocked. After a RULE exit the account is free for a signal that fills at the same open (a reversal under F3).
* **Rule state** lives in the open position's signal meta (``meta["rx"]``: reference, arms, deadline, X and T_X, the
  checks not yet acted on). ``paperbot.engine.engine_state`` / ``restore_engine`` save and restore it with the
  position, so a restart in the middle of a position continues exactly (tests/test_candleague_rulex.py). On a restore
  ``audit_restored`` recomputes it from the bars and corrects it where it differs (a Korean note says so).
* **Inputs** (``chunk_rule``): for every rule account, a ``RuleClose`` for every chart close of every coin (close,
  ATR14, EMA(n), the swings confirmed at that close, both raw signal flags, the strategy's exit flags for F11), and
  the 15m closes for q15. They are handed to ``engine.submit`` like signals (``paramshadow.replay_day`` is used as it
  is); the engine keeps only those of its held coin after the signal bar. Both sides are offered when both flags are
  true, long first (PREREG 3 and 11.3); a coin flip takes one signal per signal bar with a seeded side.
* **Accounts** (``accounts``): only when a rule config file exists (``DEFAULT_FILE``, ``CANDLEAGUE_RULES``). Per core
  pick and chosen rule ``<id>-f`` (the rule at quarter size, the judged account), ``<id>-f-live`` (live size),
  ``<id>-f-flip`` (a coin flip with the rule, quarter size), and per pick ``<id>-f0`` / ``<id>-f0-live`` (the pick's
  own exit at quarter / live size, the same-day twins). With two rules the tags are f1 and f2. They run in a league of
  their own (own database, own start, own fingerprint, ``runner.make_rule_league``), so the existing record is
  neither reset nor replayed.

Readings of the pre-registration that the code fixes (change them here, in ``decide``, if section 5 says otherwise)
----------------------------------------------------------------------------------------------------------------
* F8 and F9 arm and test at the same check close, like F5 ("the arming one included"): Rpk >= P at a check arms the rule
  and the break is tested at that very close.
* Several chart closes that reach one minute (a minute missing, a restart, a chunk end) make one check on the latest
  closed bar: the levels (F1 reference, F2 arm, F4 ATR) are updated with every bar in between, F3 sees an opposite flag on
  any of them, F7 is a clock test, F4, F5 and F10 read X, T_X and the funding of the earlier minutes.
* The decision is made at the start of ``step`` from the state before the minute, executed after the minute's funding.
* Fills and checks sit on each coin's OWN minutes, as the study's kernel reads them (``kernel._entry_index`` on the coin's
  array, PREREG 3, 5.1 and 11.4 item 13), not on the union of the coins' minutes that the league steps on: a signal fills at
  the coin's first minute after the coin's first minute at or after the bar's close minus one minute, a chart record is read at
  the same minute (``replay_day``, ``decide_ready``; the league keeps {coin: last minute present} with its engines). A signal
  or check whose coin has no bar at the minute waits for the coin's next bar.
* A record whose close is after the signal bar's close but reaches the engine while the signal still waits for its minute (the
  coin's minutes were missing for a whole bar) travels with the pending signal (``meta["rx_early"]``) and becomes the position's
  first check, read at the entry minute + 1 (PREREG 5.1: "if j <= e, then j = e + 1"). Records at or before the signal bar's
  close are never a check.
* Chart bars come from the 5m klines up to the chunk's end (``rule_frame``): a bin that closes at or before the end is kept even
  when its last 5m klines are missing ("a bin with minutes missing inside is kept as built", PREREG 2); ``chart_frame`` would drop
  it and, as the next chunk starts after its close, lose that close for good.

F11 plug-in (the strategy's own exit; its definition arrives later, nothing is invented here)
---------------------------------------------------------------------------------------------
``register_f11(strategy name, fn)`` with ``fn(df, tf, combo) -> {"long_exit": bool[n], "short_exit": bool[n],
"target_long": float[n] | None, "target_short": float[n] | None}`` computed per chart bar from the strategy's own
module on the pick-timeframe frame. The rule "F11.a" / "F11.b" fires at a pick-timeframe check close when the exit
flag of the position's side is true on a bar closed since the last check. An optional target level is carried on the
signal (``meta["rx0"]["target"]``) and becomes the take-profit price only when the rule has ``"use_target": true`` and
the level lies beyond the fill. Both points are provisional until the appendix fixes them.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import replace
from typing import Callable, Iterable, Optional

import numpy as np

from paperbot.engine import PaperEngine
from paperbot.models import Signal
from paperbot.paramshadow import _strength_feats, chart_frame, stamp_ref
from paperbot.policy import OwnerPolicy

from . import candidates as C
from . import exits as X
from . import league as L

MIN = 60_000
FIVE = 300_000
TF_MS = dict(L.TF_MS)
Q15_TFS = ("1h", "4h")                       # the picks on which a q15 variant differs from its base variant
LOOKBACK = X.STRUCT_LOOKBACK
RULES_ENV = "CANDLEAGUE_RULES"
DEFAULT_FILE = os.path.join(C.ROOT, "candleague", "data", "rules.json")
DB_NAME = "rule_league.db"
MAX_VARIANTS = 2
REL_TOL = 1e-7

# roles of the rule league's accounts
ROLE_RULE, ROLE_LIVE, ROLE_FLIP, ROLE_BASE, ROLE_BASE_LIVE = "rule", "rulelive", "ruleflip", "rulebase", "rulebaselive"
ROLES = (ROLE_RULE, ROLE_LIVE, ROLE_FLIP, ROLE_BASE, ROLE_BASE_LIVE)
NO_RULE = {"id": "E0", "family": None, "mode": "a", "q15": False}


class RuleConfigError(ValueError):
    """A rule id, a rule config file or an F11 plug-in the league cannot run as the study defines it."""


# ====================================================================== the rule interface
FAMILIES = ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F7h", "F8", "F9", "F10", "F11")
Q15_FAMILIES = ("F1", "F4", "F9")
_N = r"\d+(?:\.\d+)?"
_PAT = {
    "F1": r"F1\.w(?P<w>\d+)\.(?P<mode>[ab])(?P<q>\.q15)?",
    "F2": r"F2\.n(?P<n>\d+)\.(?P<mode>[ab])",
    "F3": r"F3\.(?P<mode>[ab])",
    "F4": rf"F4\.m(?P<m>{_N})\.(?P<mode>[ab])(?P<q>\.q15)?",
    "F5": rf"F5\.P(?P<P>{_N})\.g(?P<g>\d+)\.(?P<mode>[ab])",
    "F6": rf"F6\.w(?P<w>\d+)\.d(?P<d>{_N})",
    "F7": r"F7\.N(?P<N>\d+)\.(?P<mode>[ab])",
    "F7h": r"F7h\.H(?P<H>\d+)\.(?P<mode>[ab])",
    "F8": rf"F8\.w(?P<w>\d+)\.P(?P<P>{_N})\.(?P<mode>[ab])",
    "F9": r"F9\.(?P<mode>[ab])(?P<q>\.q15)?",
    "F10": r"F10\.N(?P<N>\d+)\.(?P<mode>[ab])",
    "F11": r"F11\.(?P<mode>[ab])",
}
F9_FIXED = {"w": 3, "P": 1.0, "d": 0.5}
KO = {"F1": "구조 이탈", "F2": "이동평균 이탈", "F3": "반대 신호", "F4": "샹들리에 추적", "F5": "수익 반납",
      "F6": "조기 손절", "F7": "시간 청산", "F7h": "시계 시간 청산", "F8": "수익 뒤 구조 이탈", "F9": "두 갈래 규칙", "F10": "정체", "F11": "전략 자체 청산"}


def _num(x) -> float:
    return float(x)


def _fmt(x) -> str:
    return format(float(x), "g")


def rule_id(r: dict) -> str:
    """The canonical id of a normalized rule (the study's spelling)."""
    f, m, q = r["family"], r["mode"], ".q15" if r["q15"] else ""
    if f == "F1":
        return f"F1.w{r['w']}.{m}{q}"
    if f == "F2":
        return f"F2.n{r['n']}.{m}"
    if f == "F3":
        return f"F3.{m}"
    if f == "F4":
        return f"F4.m{_fmt(r['m'])}.{m}{q}"
    if f == "F5":
        return f"F5.P{_fmt(r['P'])}.g{int(round(r['g'] * 100))}.{m}"
    if f == "F6":
        return f"F6.w{r['w']}.d{_fmt(r['d'])}"
    if f == "F7":
        return f"F7.N{r['N']}.{m}"
    if f == "F7h":
        return f"F7h.H{r['H']}.{m}"
    if f == "F8":
        return f"F8.w{r['w']}.P{_fmt(r['P'])}.{m}"
    if f == "F9":
        return f"F9.{m}{q}"
    if f == "F10":
        return f"F10.N{r['N']}.{m}"
    return f"F11.{m}"


def parse_rule(x) -> dict:
    """A normalized rule {id, family, mode, q15, <parameters>} from a study id or a dict ({"family": "F1", "w": 3,
    "mode": "a", "q15": False, ...} or {"id": ...}); RuleConfigError when it is not one the study defines."""
    if isinstance(x, dict) and x.get("family") is None and "id" in x:
        x = x["id"]
    if isinstance(x, str):
        fam = re.match(r"F(\d+h?)", x)
        if not fam or f"F{fam.group(1)}" not in _PAT:
            raise RuleConfigError(f"rule {x!r}: unknown family")
        m = re.fullmatch(_PAT[f"F{fam.group(1)}"], x)
        if not m:
            raise RuleConfigError(f"rule {x!r}: not written the way the study writes it")
        g = m.groupdict()
        d = {"family": f"F{fam.group(1)}", "mode": g.get("mode") or "a", "q15": bool(g.get("q"))}
        for k in ("w", "n", "N", "H"):
            if g.get(k) is not None:
                d[k] = int(g[k])
        for k in ("m", "P", "d"):
            if g.get(k) is not None:
                d[k] = _num(g[k])
        if g.get("g") is not None:
            d["g"] = int(g["g"]) / 100
    elif isinstance(x, dict):
        d = dict(x)
        d.pop("id", None)
        d.setdefault("mode", "a")
        d["q15"] = bool(d.get("q15", False))
    else:
        raise RuleConfigError(f"rule {x!r}: neither an id nor a dict")
    return _normalize(d, x)


def _normalize(d: dict, src) -> dict:
    fam = d.get("family")
    if fam not in FAMILIES:
        raise RuleConfigError(f"rule {src!r}: family {fam!r} is not one of {FAMILIES}")
    if d["mode"] not in ("a", "b"):
        raise RuleConfigError(f"rule {src!r}: mode {d['mode']!r} is not a or b")
    if fam == "F6" and d["mode"] != "a":
        raise RuleConfigError(f"rule {src!r}: F6 has mode a only (the take-profit stays)")
    if d["q15"] and fam not in Q15_FAMILIES:
        raise RuleConfigError(f"rule {src!r}: q15 exists only for {Q15_FAMILIES}")
    out = {"family": fam, "mode": d["mode"], "q15": d["q15"]}

    def need(key, kind, lo, hi=None):
        if key not in d:
            raise RuleConfigError(f"rule {src!r}: {fam} needs {key}")
        v = d[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise RuleConfigError(f"rule {src!r}: {key}={v!r} is not a number")
        if kind is int:
            if float(v) != int(v):
                raise RuleConfigError(f"rule {src!r}: {key}={v!r} is not a whole number")
            v = int(v)
        else:
            v = float(v)
        if v < lo or (hi is not None and v > hi):
            raise RuleConfigError(f"rule {src!r}: {key}={v!r} is out of range")
        out[key] = v

    if fam in ("F1", "F6", "F8"):
        need("w", int, 1)
    if fam == "F2":
        need("n", int, 2)
    if fam == "F4":
        need("m", float, 1e-9)
    if fam in ("F5", "F8"):
        need("P", float, 1e-9)
    if fam == "F5":
        need("g", float, 1e-9, 1 - 1e-9)
    if fam == "F6":
        need("d", float, 0.0)
    if fam in ("F7", "F10"):
        need("N", int, 1)
    if fam == "F7h":
        need("H", int, 1)
    if fam == "F9":
        out.update(F9_FIXED)
    if fam == "F11":
        out["use_target"] = bool(d.get("use_target", False))
    out["id"] = rule_id(out)
    return {"id": out.pop("id"), **out}


def study_ids() -> list[str]:
    """The study's 82 rule variant ids of F1-F10 (F7h included) in its canonical order (PREREG 5.3; F11 and F12 are the strategies'
    own exits and come with them)."""
    out = []
    modes = ("a", "b")
    out += [f"F1.w{w}.{m}" for w in (2, 3, 5) for m in modes]
    out += [f"F1.w{w}.{m}.q15" for w in (2, 3, 5) for m in modes]
    out += [f"F2.n{n}.{m}" for n in (10, 20, 50) for m in modes]
    out += [f"F3.{m}" for m in modes]
    out += [f"F4.m{x}.{m}" for x in ("1.5", "2", "3") for m in modes]
    out += [f"F4.m{x}.{m}.q15" for x in ("1.5", "2", "3") for m in modes]
    out += [f"F5.P{p}.g{g}.{m}" for p in ("1", "1.5", "2") for g in (25, 50) for m in modes]
    out += [f"F6.w{w}.d{d}" for w in (2, 3, 5) for d in ("0", "0.5")]
    out += [f"F7.N{n}.{m}" for n in (12, 24, 48) for m in modes]
    out += [f"F7h.H{h}.{m}" for h in (4, 8, 16) for m in modes]
    out += [f"F8.w{w}.P{p}.{m}" for w in (2, 3, 5) for p in ("1", "2") for m in modes]
    out += [f"F9.{m}" for m in modes] + [f"F9.{m}.q15" for m in modes]
    out += [f"F10.N{n}.{m}" for n in (6, 12) for m in modes]
    return out


def effective_q15(rule: dict, tf: str) -> bool:
    """q15 means 15m checks only on picks of 1h and 4h; on 15m and 30m picks it equals the base variant (PREREG 5.1)."""
    return bool(rule.get("q15")) and tf in Q15_TFS


def sched_of(a: dict) -> str:
    """The check schedule of a rule account: "q" (15m closes) or "p" (the pick's own closes)."""
    return "q" if effective_q15(a["rule"], a["tf"]) else "p"


def rule_needs(rule: dict) -> dict:
    """What the chart side must hand in per close for this rule."""
    f = rule.get("family")
    return {"atr": f == "F4", "ema": [rule["n"]] if f == "F2" else [],
            "sw": [rule["w"]] if f in ("F1", "F6", "F8", "F9") else [], "flags": f == "F3", "xf": f == "F11"}


def rule_ko(rule: Optional[dict]) -> str:
    """A short Korean label for the dashboard: the family, its numbers and the mode."""
    if not rule or not rule.get("family"):
        return "기존 청산 (규칙 없음)"
    f = rule["family"]
    bits = {"F1": f"스윙 {rule.get('w')}봉", "F2": f"EMA {rule.get('n')}", "F3": "", "F4": f"ATR x{_fmt(rule.get('m', 0))}",
            "F5": f"{_fmt(rule.get('P', 0))}R 뒤 {int(round(rule.get('g', 0) * 100))}% 반납",
            "F6": f"스윙 {rule.get('w')}봉, 손실 {_fmt(rule.get('d', 0))}R 이상",
            "F7": f"{rule.get('N')}봉", "F7h": f"{rule.get('H')}시간", "F8": f"스윙 {rule.get('w')}봉, {_fmt(rule.get('P', 0))}R 뒤",
            "F9": "", "F10": f"{rule.get('N')}봉", "F11": ""}[f]
    mode = "익절 유지" if rule["mode"] == "a" else "익절 없음"
    return f"{KO[f]}{' (' + bits + ')' if bits else ''} · {mode}" + (" · 15분 확인" if rule.get("q15") else "")


# ====================================================================== the config file and the accounts
def load_config(path: Optional[str] = None) -> Optional[dict]:
    """The rule config (None when the file does not exist: then the league creates no rule account):
    {"variants": [{"rule": <id or dict>, "label_ko": "..."}] (one or two), "picks": [candidate ids] (optional: every
    core candidate)}. Raises RuleConfigError for a file that exists but cannot be run."""
    path = path or os.environ.get(RULES_ENV) or DEFAULT_FILE
    if not os.path.exists(path):
        return None
    try:
        with open(path) as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        raise RuleConfigError(f"{path}: cannot be read ({type(exc).__name__}: {exc})") from None
    return normalize_config(doc)


def normalize_config(doc) -> dict:
    if not isinstance(doc, dict) or not isinstance(doc.get("variants"), list) or not doc["variants"]:
        raise RuleConfigError("rule config: 'variants' must be a list of one or two rules")
    if len(doc["variants"]) > MAX_VARIANTS:
        raise RuleConfigError(f"rule config: at most {MAX_VARIANTS} rules (PREREG 8: at most two are chosen)")
    variants, seen = [], set()
    for v in doc["variants"]:
        rule = parse_rule(v["rule"] if isinstance(v, dict) and "rule" in v else v)
        if rule["id"] in seen:
            raise RuleConfigError(f"rule config: {rule['id']} listed twice")
        seen.add(rule["id"])
        variants.append({"rule": rule, "label_ko": str(v.get("label_ko", "")) if isinstance(v, dict) else ""})
    picks = doc.get("picks")
    if picks is not None and (not isinstance(picks, list) or not all(isinstance(p, str) for p in picks)):
        raise RuleConfigError("rule config: 'picks' must be a list of candidate ids")
    return {"variants": variants, "picks": picks}


def pick_list(cands: list[dict], cfg: dict) -> list[dict]:
    """The picks that get rule accounts: the listed ids, else every core candidate (DeepSeek never: D11)."""
    if cfg.get("picks") is None:
        return [c for c in cands if c["kind"] == "core"]
    by_id = {c["id"]: c for c in cands}
    missing = [p for p in cfg["picks"] if p not in by_id]
    if missing:
        raise RuleConfigError(f"rule config: picks {missing} are not in the candidate list")
    bad = [p for p in cfg["picks"] if by_id[p]["kind"] != "core"]
    if bad:
        raise RuleConfigError(f"rule config: {bad} are not core picks (DeepSeek never gets rule accounts, D11)")
    return [by_id[p] for p in cfg["picks"]]


def accounts(cands: list[dict], cfg: dict) -> list[dict]:
    """The rule league's accounts (see the module docstring). Each is {id, kind, name, tf, combo, exit, source, role,
    of, pick, size, rule}; ``rule`` is the normalized rule, or NO_RULE for the pick's own exit (the twins)."""
    out = []
    many = len(cfg["variants"]) > 1
    for c in pick_list(cands, cfg):
        base = {k: c[k] for k in ("kind", "name", "tf", "combo", "exit")}
        for n, v in enumerate(cfg["variants"], 1):
            tag, rule = (f"f{n}" if many else "f"), v["rule"]
            src = {"rule": rule["id"], "rule_of": c["id"]}
            if v["label_ko"]:
                src["label_ko"] = v["label_ko"]
            fid = f"{c['id']}-{tag}"
            out.append({**base, "id": fid, "role": ROLE_RULE, "of": c["id"], "pick": c["id"], "size": C.QUARTER,
                        "rule": rule, "source": dict(src)})
            out.append({**base, "id": f"{fid}-live", "role": ROLE_LIVE, "of": c["id"], "pick": c["id"], "size": 1.0,
                        "rule": rule, "source": dict(src)})
            out.append({**base, "id": f"{fid}-flip", "role": ROLE_FLIP, "of": fid, "pick": c["id"], "size": C.QUARTER,
                        "rule": rule, "source": dict(src)})
        twin = {"rule_of": c["id"], "rule": "E0"}
        out.append({**base, "id": f"{c['id']}-f0", "role": ROLE_BASE, "of": c["id"], "pick": c["id"],
                    "size": C.QUARTER, "rule": dict(NO_RULE), "source": dict(twin)})
        out.append({**base, "id": f"{c['id']}-f0-live", "role": ROLE_BASE_LIVE, "of": c["id"], "pick": c["id"],
                    "size": 1.0, "rule": dict(NO_RULE), "source": dict(twin)})
    return out


def check(cands: list[dict], cfg: dict) -> list[str]:
    """Problems that would make the league run the rule accounts differently from the study (empty = fine)."""
    bad = []
    try:
        accts = accounts(cands, cfg)
    except RuleConfigError as exc:
        return [str(exc)]
    seen = set()
    for a in accts:
        if not C.ID_RE.match(a["id"]) or a["id"] in seen:
            bad.append(f"{a['id']}: bad or repeated id")
        seen.add(a["id"])
        if a["exit"] not in X.BY_NAME:
            bad.append(f"{a['id']}: exit {a['exit']!r} unknown")
        if a["rule"]["family"] == "F11" and a["name"] not in F11_PROVIDERS:
            bad.append(f"{a['id']}: no F11 definition registered for {a['name']!r}")
    return bad


def load_accounts(path: Optional[str], cands: list[dict]) -> Optional[list[dict]]:
    """The rule league's accounts from the config file; None when there is no file (no rule account is created)."""
    cfg = load_config(path)
    if cfg is None:
        return None
    bad = check(cands, cfg)
    if bad:
        raise RuleConfigError("; ".join(bad))
    return accounts(cands, cfg)


# ====================================================================== F11 plug-in
F11_PROVIDERS: dict[str, Callable] = {}


def register_f11(strategy: str, fn: Callable) -> None:
    """Register the strategy's own exit arrays (module docstring): fn(df, tf, combo) -> dict."""
    F11_PROVIDERS[strategy] = fn


def _f11_arrays(a: dict, df, tf: str) -> tuple:
    fn = F11_PROVIDERS.get(a["name"])
    if fn is None:
        raise RuleConfigError(f"F11: no definition registered for {a['name']!r}")
    d = fn(df, tf, {k: (tuple(v) if isinstance(v, list) else v) for k, v in a["combo"].items()})
    n = len(df)
    xl, xs = np.asarray(d["long_exit"], bool), np.asarray(d["short_exit"], bool)
    if len(xl) != n or len(xs) != n:
        raise RuleConfigError(f"F11 arrays of {a['name']!r} do not match the {n} chart bars")
    tl, ts = d.get("target_long"), d.get("target_short")
    return (xl, xs, None if tl is None else np.asarray(tl, float), None if ts is None else np.asarray(ts, float))


# ====================================================================== chart side: swings, seeds, records
def swing_flags(h, l, w: int) -> tuple:
    """(swing high, swing low) flags per bar: bar p is a swing low when its low is strictly below the lows of the w bars
    on each side (a swing high: above the highs), known at the close of bar p + w (kernel.structure_levels)."""
    h, l = np.asarray(h, float), np.asarray(l, float)
    n = len(h)
    ph, pl = np.zeros(n, bool), np.zeros(n, bool)
    if n > 2 * w:
        from numpy.lib.stride_tricks import sliding_window_view as swv
        H, Lw = swv(h, 2 * w + 1), swv(l, 2 * w + 1)
        ph[w:n - w] = H[:, w] > np.maximum(H[:, :w].max(1), H[:, w + 1:].max(1))
        pl[w:n - w] = Lw[:, w] < np.minimum(Lw[:, :w].min(1), Lw[:, w + 1:].min(1))
    return ph, pl


def start_ref(side: int, ph, pl, h, l, c, i: int, w: int, lookback: int = LOOKBACK) -> Optional[float]:
    """F1's reference at the signal bar i: for a long the highest swing low below c[i] among the swings at
    p in [i - lookback, i - w] (the second output of kernel.structure_levels), for a short the lowest swing high above
    it; None when there is none."""
    lo, hi = max(0, i - lookback), i - w
    if hi < lo:
        return None
    if side > 0:
        m = pl[lo:hi + 1] & (l[lo:hi + 1] < c[i])
        return float(l[lo:hi + 1][m].max()) if m.any() else None
    m = ph[lo:hi + 1] & (h[lo:hi + 1] > c[i])
    return float(h[lo:hi + 1][m].min()) if m.any() else None


def _fin(v) -> Optional[float]:
    v = float(v)
    return v if math.isfinite(v) else None


def rule_frame(lib, cols: tuple, tf: str, end: int):
    """``paramshadow.chart_frame`` for the rule league: chart bars of ``tf`` from the 5m bars [.., ``end``), a partial bin at the
    start dropped and every bin that closes at or before ``end`` kept, even when its last 5m bars are missing (the coin's
    minutes were gone for a while at the end of the chunk). ``chart_frame`` keeps a bin only when it closes at or before the
    last 5m bar's close, which would lose the close (its signal and its check) of a bin whose tail is missing at a chunk's end,
    for good, because the next chunk starts after that close. The study keeps such a bin as built (PREREG 2: "a bin with minutes
    missing inside is kept as built"); a bin with no 5m bar does not exist, and a 5m bar without volume is no bar (the study's data.py
    drops the minutes without trades). With nothing missing and no 5m bar without volume it is chart_frame."""
    import pandas as pd
    ts, o, h, l, c, v = cols
    if len(ts):
        traded = ~(np.asarray(v, float) == 0.0)         # a 5m interval without a trade is flat and is not market data (data.py)
        if not traded.all():
            ts, o, h, l, c, v = (np.asarray(a)[traded] for a in cols)
    if not len(ts):
        return chart_frame(lib, (ts, o, h, l, c, v), tf)
    df5 = pd.DataFrame({"ts": pd.to_datetime(np.asarray(ts, dtype=np.int64), unit="ms", utc=True), "open": o, "high": h,
                        "low": l, "close": c, "volume": v})
    r = lib.resample_ohlcv(df5, tf)
    t = (r["ts"].astype("int64") // 1_000_000).to_numpy(np.int64)
    df = r.loc[(t >= int(ts[0])) & (t + TF_MS[tf] <= int(end))].reset_index(drop=True)
    df.attrs["tf"] = tf
    return df


class RuleClose:
    """A chart close handed to a rule engine through ``submit`` (the dict ``d`` is plain JSON: see ``close_record``)."""
    __slots__ = ("d",)

    def __init__(self, d: dict):
        self.d = d


class FramePack:
    """One chart frame's arrays for the records and the seeds (computed once, only what a rule asks for)."""

    def __init__(self, lib, df):
        self.lib, self.df = lib, df
        self.h, self.l, self.c = (df[k].to_numpy(float) for k in ("high", "low", "close"))
        t_open = (df["ts"].astype("int64") // 1_000_000).to_numpy(np.int64)
        self.close_ms = t_open
        self._atr, self._ema, self._sw = None, {}, {}

    def atr(self):
        if self._atr is None:
            self._atr = self.lib.fg.atr(self.df, 14).to_numpy(float)
        return self._atr

    def ema(self, n: int):
        if n not in self._ema:
            self._ema[n] = self.lib.fg.ema(self.df["close"], n).to_numpy(float)
        return self._ema[n]

    def swings(self, w: int):
        if w not in self._sw:
            self._sw[w] = swing_flags(self.h, self.l, w)
        return self._sw[w]


def close_record(pack: FramePack, i: int, sym: str, close_ms: int, needs: dict, lo=None, sh=None, f11=None) -> dict:
    """The record of chart bar i's close for a rule with ``needs`` (rule_needs): {"k": "p", "sym", "t": close ms,
    "c": close} plus "atr", "ema" {n}, "sl"/"sh" {w: the swing low / high confirmed at this close, or None}, "lf"/"sf"
    (the pick's long / short flag), "xl"/"xs" (F11 exit flags). Everything is known at the bar's close."""
    d = {"k": "p", "sym": sym, "t": int(close_ms), "c": float(pack.c[i])}
    if needs["atr"]:
        d["atr"] = _fin(pack.atr()[i])
    if needs["ema"]:
        d["ema"] = {str(n): _fin(pack.ema(n)[i]) for n in needs["ema"]}
    if needs["sw"]:
        sl, sh_ = {}, {}
        for w in needs["sw"]:
            ph, pl = pack.swings(w)
            p = i - w
            sl[str(w)] = float(pack.l[p]) if p >= 0 and pl[p] else None
            sh_[str(w)] = float(pack.h[p]) if p >= 0 and ph[p] else None
        d["sl"], d["sh"] = sl, sh_
    if needs["flags"]:
        d["lf"], d["sf"] = bool(lo[i]), bool(sh[i])
    if needs["xf"]:
        d["xl"], d["xs"] = bool(f11[0][i]), bool(f11[1][i])
    return d


def entry_seed(pack: FramePack, rule: dict, i: int, side: int, f11=None) -> dict:
    """What the position needs from the signal bar: F1-type reference (``ref``), F2's arm at entry (``above``: the
    signal bar's close is on the right side of its EMA), F11's target level."""
    seed = {}
    nd = rule_needs(rule)
    for w in nd["sw"]:
        ph, pl = pack.swings(w)
        seed["ref"] = start_ref(side, ph, pl, pack.h, pack.l, pack.c, i, w)
    for n in nd["ema"]:
        e = pack.ema(n)[i]
        seed["above"] = bool(math.isfinite(e) and (pack.c[i] - e) * side > 0)
    if nd["xf"] and f11 is not None:
        t = f11[2] if side > 0 else f11[3]
        if t is not None and math.isfinite(t[i]):
            seed["target"] = float(t[i])
    return seed


# ====================================================================== rule state and decision (pure)
def new_rx(rule: dict, tf_ms: int, c0: int, seed: dict, atr: Optional[float], fill: float, open_time: int) -> dict:
    """The rule state of a new position (kept in the signal meta; plain JSON). ``c0``: the signal bar's close."""
    f = rule["family"]
    rx = {"c0": int(c0), "k": 0, "x": float(fill), "tx": int(open_time), "q": []}
    if f in ("F1", "F6", "F8", "F9"):
        rx["ref"] = seed.get("ref")
    if f == "F2":
        rx["arm"] = bool(seed.get("above"))
    if f in ("F5", "F8", "F9"):
        rx["armed"] = False
    if f == "F7":
        rx["dl"] = int(c0) + int(rule["N"]) * int(tf_ms)
    if f == "F7h":                                                  # clock hours from the signal bar's close (PREREG 5.2)
        rx["dl"] = int(c0) + int(rule["H"]) * 3_600_000
    if f == "F4":
        rx["atr"] = None if atr is None else float(atr)
    return rx


def _update_levels(rule: dict, rx: dict, side: int, r: dict) -> None:
    f = rule["family"]
    if f == "F4" and r.get("atr") is not None:
        rx["atr"] = r["atr"]
    if f in ("F1", "F6", "F8", "F9"):
        v = ((r.get("sl") if side > 0 else r.get("sh")) or {}).get(str(rule["w"]))
        if v is not None and (rx.get("ref") is None or (v - rx["ref"]) * side > 0):
            rx["ref"] = v
    if f == "F2":
        e = (r.get("ema") or {}).get(str(rule["n"]))
        if e is not None and (r["c"] - e) * side > 0:
            rx["arm"] = True


def decide(rule: dict, sched: str, rx: dict, side: int, fill: float, R: float, rt: float, f: float, X_: float,
           tf_ms: int) -> bool:
    """One check at a minute: the queued chart records (rx["q"], consumed here) are read in order, the pick-timeframe
    ones update the levels (F1 reference, F2 arm, F4 ATR), and the latest record of the schedule is the check close.
    ``side`` +1 / -1; ``fill`` the entry price with slippage; ``R`` the stop distance; ``rt`` the round-trip cost;
    ``f`` the funding paid per unit of notional before this minute; ``X_`` the favourable extreme before it; rx["tx"]
    is T_X. Returns True when the rule fires. Nothing of the minute being decided enters."""
    queue = sorted(rx["q"], key=lambda r: (r["t"], 0 if r["k"] == "p" else 1))
    rx["q"] = []
    fam = rule["family"]
    chk, opp, xit = None, False, False
    for r in queue:
        if r["t"] <= rx["c0"]:
            continue
        if r["k"] == "p":
            _update_levels(rule, rx, side, r)
            opp = opp or bool(r.get("sf") if side > 0 else r.get("lf"))
            xit = xit or bool(r.get("xl") if side > 0 else r.get("xs"))
        if r["k"] == sched:
            chk = r
    if chk is None:
        return False
    rx["k"] += 1
    c = chk["c"]

    def rn(price):
        return (side * (price - fill) - fill * (rt + f)) / R

    rc, rpk = rn(c), rn(X_)
    ref = rx.get("ref")
    brk = ref is not None and (c - ref) * side < 0
    if fam == "F1":
        return brk
    if fam == "F2":
        e = (chk.get("ema") or {}).get(str(rule["n"]))
        return bool(rx["arm"] and e is not None and (c - e) * side < 0)
    if fam == "F3":
        return opp
    if fam == "F4":
        a = rx.get("atr")
        return a is not None and (c - (X_ - side * rule["m"] * a)) * side < 0
    if fam == "F5":
        if rpk >= rule["P"]:
            rx["armed"] = True
        return bool(rx["armed"] and rc <= (1 - rule["g"]) * rpk)
    if fam == "F6":
        return bool(brk and rc < -rule["d"])
    if fam in ("F7", "F7h"):
        return chk["t"] >= rx["dl"]
    if fam == "F8":
        if rpk >= rule["P"]:
            rx["armed"] = True
        return bool(rx["armed"] and brk)
    if fam == "F9":
        if rpk >= rule["P"]:
            rx["armed"] = True
        return bool(brk and (rx["armed"] or rc < -rule["d"]))
    if fam == "F10":
        return bool(rc > 0 and chk["t"] - rx["tx"] >= rule["N"] * tf_ms)
    return xit                                                     # F11


def decide_ready(rule: dict, sched: str, rx: dict, side: int, fill: float, R: float, rt: float, f: float, X_: float,
                 tf_ms: int, prev: Optional[int]) -> bool:
    """``decide`` on the queued chart records whose check minute has come. A record closing at C is read at the coin's
    first minute after the coin's first minute at or after C - 1 minute (kernel._entry_index on the coin's own minutes,
    PREREG 5.1): ``prev``, the coin's previous minute present, must be at or after C - 1 minute; the others stay queued.
    ``prev`` None = no gating (every queued record is read, the single-coin case)."""
    if prev is not None and rx["q"]:
        wait = [r for r in rx["q"] if r["t"] - MIN > prev]
        if wait:
            rx["q"] = [r for r in rx["q"] if r["t"] - MIN <= prev]
            fire = decide(rule, sched, rx, side, fill, R, rt, f, X_, tf_ms)
            rx["q"] = wait
            return fire
    return decide(rule, sched, rx, side, fill, R, rt, f, X_, tf_ms)


def track_extreme(rx: dict, side: int, mfe: float, open_time: int) -> None:
    """X and T_X: the favourable extreme and the open time of the last minute that raised it."""
    if (mfe - rx["x"]) * side > 0:
        rx["x"], rx["tx"] = float(mfe), int(open_time)


# ====================================================================== the engine
class NoTP(OwnerPolicy):
    """Mode (b): no take-profit (with tp_mode "fixed" the engine also has no lock)."""

    def take_profit(self, sig, entry, dec):
        return math.nan


class RuleMixin:
    """PaperEngine step order for a rule account: funding -> RULE exit -> entries -> the engine's exit handling.
    ``rx_rule`` None = no rule (the plain engine)."""
    rx_rule: Optional[dict] = None
    rx_sched: str = "p"
    rx_tf_ms: int = 0
    rx_seen: Optional[dict] = None       # {coin: its previous minute present} (the league's, see replay_day); None = no gating

    def submit(self, signal) -> None:
        if isinstance(signal, RuleClose):
            d = signal.d
            if self.rx_rule is None:
                return
            p = self.position
            if p is not None and d["sym"] == p.symbol:
                rx = p.signal.meta.get("rx")
                if rx is not None and d["t"] > rx["c0"]:
                    rx["q"].append(dict(d))
            for s in self.pending:
                # a signal of this coin is still waiting for its minute (the coin's minutes are missing for a while): the
                # close is a check of the position it may open, and is read at the entry minute + 1 (PREREG 5.1: "if
                # j <= e, then j = e + 1"); it travels with the pending signal
                if s.symbol == d["sym"] and d["t"] > s.ts + 1:
                    s.meta.setdefault("rx_early", []).append(dict(d))
            return
        super().submit(signal)

    def _try_enter(self, sig, bar) -> bool:
        ok = super()._try_enter(sig, bar)
        if ok and self.rx_rule is not None:
            p = self.position
            seed = p.signal.meta.get("rx0") or {}
            rx = new_rx(self.rx_rule, self.rx_tf_ms, p.signal.ts + 1, seed, p.signal.atr, p.entry_price, bar.open_time)
            rx["q"] = [dict(r) for r in p.signal.meta.pop("rx_early", ()) if r["t"] > rx["c0"]]
            p.signal.meta["rx"] = rx
            t = seed.get("target")
            if self.rx_rule.get("use_target") and t is not None and math.isfinite(t) and (t - p.entry_price) * p.side > 0:
                p.tp_price = float(t)
        return ok

    def _rx_decide(self, p, rx) -> bool:
        f = p.funding_paid / p.notional_entry if p.notional_entry else 0.0
        prev = None if self.rx_seen is None else self.rx_seen.get(p.symbol)
        return decide_ready(self.rx_rule, self.rx_sched, rx, p.side, p.entry_price, float(p.signal.meta["stop_dist"]),
                            self.s.round_trip_cost, f, p.mfe_price, self.rx_tf_ms, prev)

    @staticmethod
    def _gapped(p, bar) -> bool:
        """The open is beyond liquidation (mark), the stop or the take-profit: the engine's own exit handling takes it."""
        if (bar.m_open - p.liq_price) * p.side <= 0 or (bar.open - p.stop_price) * p.side <= 0:
            return True
        return not math.isnan(p.tp_price) and (bar.open - p.tp_price) * p.side > 0

    def step(self, bars, funding=None) -> None:
        if self.rx_rule is None:
            return super().step(bars, funding)
        p = self.position
        fire = False
        if p is not None:
            rx = p.signal.meta.get("rx")
            if rx is not None and rx["q"] and p.symbol in bars:
                fire = self._rx_decide(p, rx)                         # state frozen before this minute
        if funding and self.position is not None:                     # funding first (the engine's own rule)
            rate, bar = funding.get(self.position.symbol), bars.get(self.position.symbol)
            if rate is not None and bar is not None:
                self._apply_funding(rate, bar.m_open)
        if fire and self.position is not None:
            bar = bars[self.position.symbol]
            if not self._gapped(self.position, bar):
                self._close_market(bar.open, bar.open_time, "RULE")   # taker fee, slippage, at the open
        super().step(bars, None)                                      # entries, then the normal exit handling
        p = self.position
        if p is not None:
            rx, bar = p.signal.meta.get("rx"), bars.get(p.symbol)
            if rx is not None and bar is not None:
                track_extreme(rx, p.side, p.mfe_price, bar.open_time)


class RuleEngine(RuleMixin, PaperEngine):
    pass


class RuleLadderEngine(RuleMixin, X.LadderTP):
    pass


def make_engine(a: dict, brackets: dict, specs: dict) -> PaperEngine:
    """The engine of a rule-league account. The twins (no rule) are the plain engines of candleague.exits; a rule
    account is the same set-up (the pick's exit, ``size``) as a RuleMixin engine: mode a keeps the exit's own
    take-profit, mode b has none and no lock."""
    rule, name, size = a.get("rule") or NO_RULE, a["exit"], a.get("size", 1.0)
    if rule.get("family") is None:
        return X.make_engine(name, brackets, specs, book=a["id"], size=size)
    s, st = X.spec(name), X.settings_for(name, size=size)
    if rule["mode"] == "b":
        st = replace(st, tp_mode="fixed")                  # no take-profit and no stepped lock
        e = RuleEngine(st, brackets, symbol_specs=specs, policy=NoTP(st), book=a["id"])
    elif s["ladder"] and s["tp_kind"] == X.TP_STRUCT:
        e = RuleLadderEngine(st, brackets, symbol_specs=specs, struct=True, book=a["id"])
    elif s["ladder"] and s["tp_kind"] == X.TP_R:
        e = RuleLadderEngine(st, brackets, symbol_specs=specs, m=s["tp_val"], book=a["id"])
    elif s["ladder"] or s["tp_kind"] == X.TP_ROE:
        e = RuleEngine(st, brackets, symbol_specs=specs, book=a["id"])
    else:
        e = RuleEngine(st, brackets, symbol_specs=specs, policy=X.RPolicy(st, s["tp_val"]), book=a["id"])
    e.rx_rule, e.rx_sched, e.rx_tf_ms = rule, sched_of(a), TF_MS[a["tf"]]
    return e


# ====================================================================== the league side: signals and records per chunk
def _sides(lo_i: bool, sh_i: bool) -> list:
    """Both sides when both flags are true, the long first (PREREG 3 and 11.3)."""
    return ([1] if lo_i else []) + ([-1] if sh_i else [])


def chunk_rule(lib, source, accts: list[dict], symbols: Iterable[str], start: int, end: int, run_start: int,
               strategies: Optional[L.Strategies] = None, log: Callable[[str], None] = lambda s: None) -> tuple:
    """The rule accounts' signals and chart records of the chart bars closing in (max(start, run_start), end]:
    ({bar close: [(account id, Signal or RuleClose)]}, [notes]). Twins and rule accounts offer every flag (both sides
    when both are true, long first); a coin flip takes one signal per signal bar with its seeded side; a rule account
    also gets a RuleClose for every chart close of every coin (and every 15m close for q15 on 1h / 4h picks)."""
    from paperbot.sigservice import window_5m
    S = strategies or L.Strategies()
    ra = [a for a in accts if a.get("rule")]
    by_close: dict[int, list] = {}
    notes: list[str] = []
    for tf in sorted({a["tf"] for a in ra}, key=lambda t: TF_MS[t]):
        span, w = TF_MS[tf], lib.warmup_bars(tf)
        group = [a for a in ra if a["tf"] == tf]
        frames, cols_of = {}, {}
        for sym in symbols:
            cols_of[sym] = source.load(sym, start - window_5m(lib, tf) * FIVE, end)
            frames[sym] = rule_frame(lib, cols_of[sym], tf, end)
        for sym in symbols:
            df = frames[sym]
            if len(df) <= w:
                notes.append(f"{sym} {tf}: 차트 봉 {len(df)}개(필요 {w + 1}개 이상), 이 구간 신호 없음")
                continue
            t_open = (df["ts"].astype("int64") // 1_000_000).to_numpy(np.int64)
            close = t_open + span
            idx = np.flatnonzero((close > max(start, run_start)) & (close <= end) & (np.arange(len(df)) >= w))
            pack15 = None
            if any(sched_of(a) == "q" for a in group):             # 15m closes come between the pick's own closes
                f15 = rule_frame(lib, cols_of[sym], "15m", end)
                c15 = (f15["ts"].astype("int64") // 1_000_000).to_numpy(np.int64) + TF_MS["15m"]
                i15 = np.flatnonzero((c15 > max(start, run_start)) & (c15 <= end))
                pack15 = (np.asarray(f15["close"], float), c15, i15)
            if not len(idx) and (pack15 is None or not len(pack15[2])):
                continue
            pack = FramePack(lib, df)
            cache: dict = {}
            strength: dict = {}
            f11c: dict = {}
            recs: dict = {}                       # the same records serve every account with the same pick and needs
            for a in group:
                key = (a["kind"], a["name"], repr(sorted(a["combo"].items())))
                if key not in cache:
                    try:
                        cache[key] = S.signals(a, df, sym, frames.get("BTCUSDT"))
                    except Exception as exc:  # noqa: BLE001  live (strict=False): a failing rule gives no signal
                        notes.append(f"{a['id']} {sym} {tf}: 신호 계산 실패 ({type(exc).__name__}), 이 구간 신호 없음")
                        cache[key] = (np.zeros(len(df), bool), np.zeros(len(df), bool))
                lo, sh = cache[key]
                smod = S.strength(a["name"]) if a["kind"] == "core" else None
                if smod is not None and a["name"] not in strength:
                    try:
                        import warnings
                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore")
                            strength[a["name"]] = {"arrays": smod.strength(df.copy(), tf)}
                    except Exception as exc:  # noqa: BLE001  live: a failed strength sizes 'normal'
                        strength[a["name"]] = {"error": f"{type(exc).__name__}: {exc}"[:200]}
                rule, spec = a["rule"], X.spec(a["exit"])
                f11 = None
                if rule["family"] == "F11":
                    if key not in f11c:
                        f11c[key] = _f11_arrays(a, df, tf)
                    f11 = f11c[key]
                for pos in np.flatnonzero(lo[idx] | sh[idx]):
                    i = int(idx[pos])
                    at = float(pack.atr()[i])
                    if not (math.isfinite(at) and at > 0):
                        continue                                      # live: NO_ATR, never traded
                    sides = [flip_of(a, int(close[i]))] if a["role"] == ROLE_FLIP else _sides(bool(lo[i]), bool(sh[i]))
                    for s in sides:
                        meta = {"stop_dist": spec["stop_atr"] * at, "account": a["id"],
                                "ctx": {"strength": _strength_feats(strength.get(a["name"]), smod, i, s)}}
                        if rule["family"] is not None:
                            meta["style"] = f"rule:{rule['id']}"
                            meta["rx0"] = entry_seed(pack, rule, i, s, f11)
                        sig = Signal(ts=int(close[i]) - 1, symbol=sym, timeframe=tf, strategy_id=a["name"], side=s,
                                     stop_price=0.0, tier="best", atr=at, meta=meta)
                        by_close.setdefault(int(close[i]), []).append((a["id"], sig))
                if rule["family"] is None:
                    continue
                needs = rule_needs(rule)
                rk = (key, json.dumps(needs, sort_keys=True))
                if rk not in recs:
                    recs[rk] = [close_record(pack, int(i), sym, int(close[i]), needs, lo, sh, f11) for i in idx]
                for i, rec in zip(idx, recs[rk]):
                    by_close.setdefault(int(close[i]), []).append((a["id"], RuleClose(rec)))
                if sched_of(a) == "q" and pack15 is not None:
                    cl15, c15, i15 = pack15
                    for j in i15:
                        by_close.setdefault(int(c15[j]), []).append(
                            (a["id"], RuleClose({"k": "q", "sym": sym, "t": int(c15[j]), "c": float(cl15[j])})))
        log(f"rule signals {tf}: {sum(len(v) for v in by_close.values())} so far")
    return by_close, notes


def flip_of(a: dict, close_ms: int) -> int:
    return L.flip_side(a["id"], close_ms)


def account_records(lib, source, a: dict, sym: str, lo_ms: int, hi_ms: int,
                    strategies: Optional[L.Strategies] = None) -> list[dict]:
    """The chart records chunk_rule hands to account ``a`` for coin ``sym`` over closes in (lo_ms, hi_ms], rebuilt from
    the bars alone (the restore check): pick-timeframe records and, for q15, the 15m ones."""
    from paperbot.sigservice import window_5m
    S = strategies or L.Strategies()
    tf, rule = a["tf"], a["rule"]
    span, w = TF_MS[tf], lib.warmup_bars(tf)
    cols = source.load(sym, lo_ms - window_5m(lib, tf) * FIVE, hi_ms)
    df = rule_frame(lib, cols, tf, hi_ms)
    out = []
    if len(df) <= w:
        return out
    close = (df["ts"].astype("int64") // 1_000_000).to_numpy(np.int64) + span
    idx = np.flatnonzero((close > lo_ms) & (close <= hi_ms) & (np.arange(len(df)) >= w))
    pack = FramePack(lib, df)
    needs = rule_needs(rule)
    lo, sh = S.signals(a, df, sym, None) if needs["flags"] else (None, None)
    f11 = _f11_arrays(a, df, tf) if rule["family"] == "F11" else None
    for i in idx:
        out.append(close_record(pack, int(i), sym, int(close[i]), needs, lo, sh, f11))
    if sched_of(a) == "q":
        f15 = rule_frame(lib, cols, "15m", hi_ms)
        c15 = (f15["ts"].astype("int64") // 1_000_000).to_numpy(np.int64) + TF_MS["15m"]
        for j in np.flatnonzero((c15 > lo_ms) & (c15 <= hi_ms)):
            out.append({"k": "q", "sym": sym, "t": int(c15[j]), "c": float(f15["close"].iloc[j])})
    return out


# ====================================================================== the replay: the study's per-coin minutes
def _due(sig, prev: Optional[int]) -> bool:
    """A pending signal may fill at its coin's minute when the coin's previous minute present is at or after the signal
    bar's close minus one minute (``prev`` None: not known, so yes)."""
    return prev is None or sig.ts + 1 - MIN <= prev


def replay_day(engines: dict, active: set, by_close: dict, steps, brackets, seen: dict, fund_wait: Optional[dict] = None) -> None:
    """``paramshadow.replay_day`` for a league that must place fills and checks on the minutes the study's kernel uses
    (PREREG 3, 5.1 and 11.4 item 13): the kernel reads each coin's OWN minutes (kernel._entry_index on the coin's array),
    the league's steps are the union of the coins' minutes, so a minute missing for one coin while the others trade
    (a bin's last minute, a zero-volume minute the study drops) must not move a fill or a check.

    * A signal fills at the first step of its coin after the coin's first minute at or after the bar's close minus one
      minute (the kernel's ``j0 + 1``): a pending signal whose coin has no bar at this step waits (paramshadow's
      engine would reject it, "no next bar"), and so does one whose coin's previous minute present is earlier than the
      close minus one minute (the close minute was the coin's own first minute).
    * A chart record is read at the same minute (``decide_ready``, through ``engine.rx_seen``).
    * A coin's minute without trades (volume 0: the archive writes an exchange halt as flat bars) is no minute, as data.py drops
      it; a funding settlement that falls on a minute the coin does not have is paid at the coin's next minute present
      (data.py: "the next minute when that one is missing"), kept in ``fund_wait`` until then.
    ``seen`` is {coin: the coin's last minute present}, updated here after each step, and ``fund_wait`` {coin: funding
    waiting for the coin's next minute}; the league keeps both across chunks and restarts. Everything else is
    paramshadow.replay_day: only busy engines are stepped, a signal or record is submitted after the step of the minute
    that ends at its bar's close (or after the first step past it), and a close after the day's last step goes in at the
    end (pending into the next day). With no minute missing for a single coin and none without trades it gives the same
    trades as paramshadow.replay_day."""
    closes = sorted(by_close)
    k = 0
    fund_wait = {} if fund_wait is None else fund_wait
    for ts, bars, funding in steps:
        tb = {s: b for s, b in bars.items() if s in brackets and not (b.volume is not None and b.volume == 0.0)}
        if funding or fund_wait:
            funding = dict(funding or {})
            for s in [s for s in funding if s in brackets and s not in tb]:   # not the coin's minute: its next one
                fund_wait[s] = fund_wait.get(s, 0.0) + funding.pop(s)
            for s in [s for s in tb if s in fund_wait]:
                funding[s] = funding.get(s, 0.0) + fund_wait.pop(s)
        for aid in sorted(active if tb else ()):
            e = engines[aid]
            held = []
            if e.pending:
                ok = [g.symbol in tb and _due(g, seen.get(g.symbol)) for g in e.pending]
                held = [g for g, o in zip(e.pending, ok) if not o]
                if held:
                    e.pending = [g for g, o in zip(e.pending, ok) if o]
            stamp_ref(e, tb)
            e.step(tb, funding)
            e.outcomes.clear()
            if held:
                e.pending = held + e.pending
            if e.position is None and not e.pending:
                active.discard(aid)
        for s in tb:
            seen[s] = ts
        while k < len(closes) and closes[k] <= ts + MIN:
            for aid, sig in by_close[closes[k]]:
                engines[aid].submit(sig)
                active.add(aid)
            k += 1
    for c in closes[k:]:
        for aid, sig in by_close[c]:
            engines[aid].submit(sig)
            active.add(aid)


# ====================================================================== the restore check
def _same(a, b) -> bool:
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, float) or isinstance(b, float):
        if a is None or b is None:
            return a is b
        return math.isclose(float(a), float(b), rel_tol=REL_TOL, abs_tol=1e-9)
    return a == b


def recompute_rx(lg, a: dict, p) -> dict:
    """The rule state of the open position ``p`` of account ``a`` as it should be at the league's ``done`` time, from
    the bars alone: the seed of the signal, the chart records closed since, and the position's minutes (the favourable
    extreme, the funding). The same ``decide`` / ``track_extreme`` the engine uses."""
    rule, sym = a["rule"], p.symbol
    tf_ms, sched = TF_MS[a["tf"]], sched_of(a)
    c0 = int(p.signal.ts) + 1
    rx = new_rx(rule, tf_ms, c0, p.signal.meta.get("rx0") or {}, p.signal.atr, p.entry_price, p.entry_time)
    done = lg.done
    recs = sorted(account_records(lg.lib, lg.source, a, sym, c0, done, lg.strategies),
                  key=lambda r: (r["t"], 0 if r["k"] == "p" else 1))
    steps = lg.fetch_steps(None, [sym], p.entry_time // FIVE * FIVE, done)
    rt = lg.engines[a["id"]].s.round_trip_cost
    R, side, qty = float(p.signal.meta["stop_dist"]), p.side, p.qty
    fpaid, mfe, ri, prev, fwait = 0.0, p.entry_price, 0, p.entry_time, 0.0
    for t, bars, fund in steps:
        b = bars.get(sym)
        if b is not None and b.volume is not None and b.volume == 0.0:
            b = None                                          # a minute without trades is no minute (replay_day)
        if b is None:
            if p.entry_time <= t < done:
                fwait += fund.get(sym, 0.0)                   # a settlement at a minute the coin lacks waits for its next one
            continue
        if b.open_time < p.entry_time or b.open_time >= done:
            continue
        entry = b.open_time == p.entry_time
        rate = fund.get(sym, 0.0) + fwait
        fwait = 0.0
        if not entry:
            if rx["q"]:
                decide_ready(rule, sched, rx, side, p.entry_price, R, rt, fpaid / (qty * p.entry_price), mfe, tf_ms, prev)
            if rate:
                fpaid += side * qty * b.m_open * rate
        mfe = max(mfe, b.high) if side > 0 else min(mfe, b.low)
        track_extreme(rx, side, mfe, b.open_time)
        prev = b.open_time
        while ri < len(recs) and recs[ri]["t"] <= b.open_time + MIN:
            if recs[ri]["t"] > c0:
                rx["q"].append(dict(recs[ri]))
            ri += 1
    while ri < len(recs):                                     # closes after the last minute: pending into the next day
        if recs[ri]["t"] > c0:
            rx["q"].append(dict(recs[ri]))
        ri += 1
    return rx


def audit_restored(lg, log: Callable[[str], None] = print) -> list[str]:
    """After a restore: recompute every open rule position's state from the bars and compare (the pre-registration's
    11.5). A difference is corrected to the recomputation and returned as a Korean note; a recomputation that cannot be
    made (no data right now) is returned as a note too and changes nothing."""
    notes = []
    for a in lg.accts:
        rule = a.get("rule")
        if not rule or rule.get("family") is None:
            continue
        p = lg.engines[a["id"]].position
        if p is None:
            continue
        have = p.signal.meta.get("rx")
        try:
            want = recompute_rx(lg, a, p)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{a['id']}: 규칙 상태를 봉에서 다시 계산하지 못했습니다 ({type(exc).__name__}), 저장된 상태를 그대로 씁니다")
            log(notes[-1])
            continue
        if have is None or not _same(have, want):
            bad = sorted(k for k in set(want) | set(have or {}) if not _same((have or {}).get(k), want.get(k)))
            notes.append(f"{a['id']}: 저장된 규칙 상태가 봉에서 다시 계산한 값과 달라 고쳤습니다 ({', '.join(bad)})")
            log(notes[-1])
            p.signal.meta["rx"] = want
    return notes


# ====================================================================== command line
def main(argv: Optional[list] = None) -> int:
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="후보 리그 규칙 계좌")
    ap.add_argument("cmd", choices=("check", "accounts", "ids"))
    ap.add_argument("--rules", default=None, help=f"rule config (default {DEFAULT_FILE}, env {RULES_ENV})")
    ap.add_argument("--candidates", default=C.DEFAULT_FILE)
    a = ap.parse_args(argv)
    if a.cmd == "ids":
        print("\n".join(study_ids()))
        return 0
    try:
        accts = load_accounts(a.rules, C.load(a.candidates))
    except RuleConfigError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    if accts is None:
        print("no rule config file: the league creates no rule account")
        return 0
    if a.cmd == "accounts":
        print("\n".join(x["id"] for x in accts))
    else:
        print(f"ok: {len(accts)} rule accounts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
