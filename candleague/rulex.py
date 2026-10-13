"""후보 리그 규칙 계좌 (rule accounts): a pick's own entries, hard stop and sizing with a RULE exit on top, in a league
of their own (research/exitflex/PREREG_EXITFLEX.md sections 4, 5 and 11; the generic mechanism, no variant chosen here).

What this module is
-------------------
* **Rule interface** (``parse_rule``): the study's ids, "F1.w3.a", "F1.w3.b.q15", "F2.n20.b", "F3.a", "F4.m1.5.a",
  "F5.P1.5.g25.a", "F6.w2.d0.5", "F7.N24.b", "F8.w3.P1.a", "F9.b.q15", "F10.N6.a" (or a dict with ``family`` and the
  parameters), plus "F11.a" / "F11.b" (the strategy's own exit) and "F12.a" / "F12.b" (all nine at once), both below. Mode "a"
  keeps the pick's own take-profit, mode "b" has no take-profit and no lock (F11.b and F12.b: the strategy's own target where it
  has one); q15 checks on 15m closes for picks on 1h and 4h.
* **Engine** (``RuleMixin``, ``RuleEngine``, ``RuleLadderEngine``, ``LockEngine``, ``LockLadderEngine``, ``make_engine``): a PaperEngine whose ``step`` runs
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
  ATR14, EMA(n), the swings confirmed at that close, both raw signal flags, the strategy's component values for F11 and F12),
  and the 15m closes for q15. They are handed to ``engine.submit`` like signals (``replay_day``); the engine keeps only those of
  its held coin after the signal bar. No bar carries both flags (PREREG 3): ``chunk_rule`` stops with ``BothFlags`` when one
  does; a coin flip takes one signal per signal bar with a seeded side.
* **Accounts** (``accounts``, PREREG 11.2): only when a rule config file exists and is enabled (``DEFAULT_FILE``,
  ``CANDLEAGUE_RULES``; ``"enabled": true`` is the owners' OK). Per pick, both pools: in a pool with a new exit ``<id>-n``
  (the new exit, live size), ``<id>-nq`` (quarter size, the judged account), ``<id>-e`` and ``<id>-eq`` (E0, the pick's own
  exit, live and quarter size: the same-day twins) and ``<id>-nflip`` (the new exit at quarter size, a seeded coin at the pick's
  signal times); in a pool with no new exit ``<id>-e``, ``<id>-eq`` and ``<id>-eflip`` (E0, live size, a seeded coin). The
  league that runs them is the restarted league itself (its own database and start, PREREG 11.3 and 11.4 item 1), not a side
  league: ``runner.main`` takes these accounts instead of the candidate accounts when the file is enabled.
* **Counters and marks** (PREREG 11.4 items 10-12): ``replay_day`` counts, per account and UTC day, the signals decided (entered,
  skipped while holding, rejected) and ``League.advance`` the trades closed (table ``acct_day``); at every 00:00 UTC it writes each
  account's realised wallet and its mark value (table ``acct_mark``); all in the commit of the chunk. ``no_entry_from_ms`` on an
  account of the new exit stops its new entries from that time (the C1 script sets it; it is part of the fingerprint).
* **Owner exits** (owners 2026-10-12, "익절기준이랑 손절기준을 좀 바꾸고 싶어서"; ``owner_accounts``): a second form of the config
  file, ``{"enabled": true, "owner_exits": [...]}`` instead of ``"pools"``. Per pick one account per entry, side by side on the same
  signals (all from ``chunk_rule``): the pick's current exit (the entry with no rule, no exit and no weekend switch: role ``cand``,
  the pick's own source and band), a study rule on top (``"rule": "F2.n50.b"``: the ``RuleEngine`` as above), another take-profit
  with the pick's own stop multiple (``"exit": "roe50"`` -> "roe50|<k>": the plain engine of that exit; skipped for a pick whose
  own exit is already that one), or the current exit with no new entry from a signal bar that closes Saturday 00:00 to Monday 00:00
  UTC (``"weekend_off": true``: the plain engine with the ``RuleMixin`` gate, ``is_weekend``). Every entry is at the live size
  unless it says ``size``. Each account carries ``ox`` (its entry's role, suffix and Korean words) for the snapshot's ``lineup``.

F13 (the rule bot's stepped profit lock; PREREG 5.2, ``exits.lock_exit``)
------------------------------------------------------------------------
"F13.a" (the pick's own fixed take-profit kept and the stepped lock added) and "F13.b" (no fixed take-profit, the lock alone: the rule bot's
exit) make no decision at a chart close and read no chart data. The pick's hard stop (k x ATR14) stays. The three accounts of the new exit
(``-n``, ``-nq``, ``-nflip``) simply run another exit of ``candleague.exits`` on the plain engine: ``exit_name(a)`` = ``exits.lock_exit`` of the
pick's own exit ("tp3R|4" -> "lock+tp3R|4", mode b "ladder|4"). Their signals carry the same stop distance; no ``RuleClose`` is handed in, no
``meta['rx']`` exists, a restart restores the position, its stop and its lock (``lock_roe``) with the engine state. The engine is the plain
engine of that exit with the ``RuleMixin`` gate and no rule (``LockEngine`` / ``LockLadderEngine``, ``rx_rule`` None: ``step`` and ``submit``
are the plain engine's), so that ``no_entry_from_ms`` (the C1 stop, PREREG 11.4 item 9) refuses a new entry from that time as it does for every
other rule account. The twins (``-e``, ``-eq``) and every account id and count are unchanged.

F11 and F12 (the strategy's own exit; all nine at once; PREREG 5.2 and Appendix A)
----------------------------------------------------------------------------------
The strategy's component arrays, levels and targets come from a provider (``register_native``; production:
``load_native_provider`` = research/exitflex/native.py and native_ds.py, the code the study runs) with the signature of
``kernel_x.register_f11``. Per chart close the record carries the tri-state values (1 true, 0 false, 2 unknown) of both sides'
components; the entry seed carries the position side's component kinds and the values at the signal bar (rule C3: a state
component is armed once it has been false at a close), the strategy's invalidation level and target (``meta['native_inv']``,
``meta['native_tgt']``, mirrored around the fill for a coin flip on the other side) and the strategy's side. F11.b has a
take-profit limit at the target when it lies beyond the fill (the engine's ``tp_price``, without the lock); F11.a keeps the pick's
own. F12 tests F1, F2, F3, F4, F5, F6, F7h, F10 and F11 on the same frozen state at the fixed values (``F12_PARAMS``) and records
every component that fired at the exit's check (``rx['comp']``, in the trade's ``context['rx_comp']``).

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
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from dataclasses import replace
from typing import Callable, Iterable, Optional

import numpy as np

from paperbot.engine import PaperEngine
from paperbot.ladder import tighten
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
DB_NAME = "rule_league.db"             # the first draft's side-league database: no longer created (the restarted league IS the league, in --db)
REL_TOL = 1e-7
RULEX_VERSION = 2                      # the meaning of a rule account: part of the fingerprint of rule accounts only (runner.fingerprint)
POOLS = ("core", "ds")
DAY = 86_400_000

# roles of the rule league's accounts
ROLE_RULE, ROLE_LIVE, ROLE_FLIP, ROLE_BASE, ROLE_BASE_LIVE = "rule", "rulelive", "ruleflip", "rulebase", "rulebaselive"
ROLES = (ROLE_RULE, ROLE_LIVE, ROLE_FLIP, ROLE_BASE, ROLE_BASE_LIVE)
NO_RULE = {"id": "E0", "family": None, "mode": "a", "q15": False}


class RuleConfigError(ValueError):
    """A rule id, a rule config file or an F11 plug-in the league cannot run as the study defines it."""


# ====================================================================== the rule interface
FAMILIES = ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F7h", "F8", "F9", "F10", "F11", "F12", "F13")
NATIVE_FAMILIES = ("F11", "F12")       # the families that read the strategy's own exit arrays
LOCK_FAMILIES = ("F13",)               # the stepped lock: another exit of candleague.exits, no rule state and no chart records
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
    "F12": r"F12\.(?P<mode>[ab])",
    "F13": r"F13\.(?P<mode>[ab])",
}
F9_FIXED = {"w": 3, "P": 1.0, "d": 0.5}
# F12's fixed values (PREREG 5.2: the middle of each component's grid, the larger of a two-value grid); equal to kernel_x.F12_PARAMS
F12_PARAMS = {"w": 3, "n": 20, "m": 2.0, "P": 1.5, "g": 0.5, "d": 0.5, "H": 8, "N": 12}
# F12 component bits of the exit mask (PREREG 5.2), the order of kernel_x.COMP_NAMES
CB = {"F1": 1, "F2": 2, "F3": 4, "F4": 8, "F5": 16, "F6": 32, "F7h": 64, "F10": 128, "F11": 256}
KO = {"F1": "구조 이탈", "F2": "이동평균 이탈", "F3": "반대 신호", "F4": "샹들리에 추적", "F5": "수익 반납",
      "F6": "조기 손절", "F7": "시간 청산", "F7h": "시계 시간 청산", "F8": "수익 뒤 구조 이탈", "F9": "두 갈래 규칙", "F10": "정체", "F11": "전략 자체 청산", "F12": "아홉 가지 동시",
      "F13": "규칙봇 계단 잠금(12%→10%, 17%→15%…)"}


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
    if f == "F12":
        return f"F12.{m}"
    if f == "F13":
        return f"F13.{m}"
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
    if fam == "F12":
        out.update(F12_PARAMS)
    out["id"] = rule_id(out)
    return {"id": out.pop("id"), **out}


def study_ids() -> list[str]:
    """The study's 82 rule variant ids of F1-F10 (F7h included) in its canonical order (PREREG 5.3); ``native_ids`` are the other four."""
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


def native_ids() -> list[str]:
    """F11 and F12, the 4 variants that read the strategy's own exit (86 with ``study_ids``; 88 with ``lock_ids``)."""
    return ["F11.a", "F11.b", "F12.a", "F12.b"]


def lock_ids() -> list[str]:
    """F13, the 2 variants of the stepped lock (the pick's own take-profit kept; the lock alone). 88 with ``study_ids`` and ``native_ids``."""
    return ["F13.a", "F13.b"]


def exit_name(a: dict) -> str:
    """The exit of ``candleague.exits`` that account ``a`` runs: the pick's own (``a['exit']``), except under F13 where it is the pick's exit with
    the stepped lock added (mode a) or the lock alone (mode b), ``exits.lock_exit``."""
    rule = a.get("rule") or NO_RULE
    if rule.get("family") in LOCK_FAMILIES:
        return X.lock_exit(a["exit"], rule["mode"])
    return a["exit"]


def effective_q15(rule: dict, tf: str) -> bool:
    """q15 means 15m checks only on picks of 1h and 4h; on 15m and 30m picks it equals the base variant (PREREG 5.1)."""
    return bool(rule.get("q15")) and tf in Q15_TFS


def sched_of(a: dict) -> str:
    """The check schedule of a rule account: "q" (15m closes) or "p" (the pick's own closes)."""
    return "q" if effective_q15(a["rule"], a["tf"]) else "p"


def rule_needs(rule: dict) -> dict:
    """What the chart side must hand in per close for this rule."""
    f = rule.get("family")
    if f == "F12":
        return {"atr": True, "ema": [rule["n"]], "sw": [rule["w"]], "flags": True, "nat": True}
    return {"atr": f == "F4", "ema": [rule["n"]] if f == "F2" else [],
            "sw": [rule["w"]] if f in ("F1", "F6", "F8", "F9") else [], "flags": f == "F3", "nat": f == "F11"}


def rule_ko(rule: Optional[dict]) -> str:
    """A short Korean label for the dashboard: the family, its numbers and the mode."""
    if not rule or not rule.get("family"):
        return "기존 청산 (규칙 없음)"
    f = rule["family"]
    bits = {"F1": f"스윙 {rule.get('w')}봉", "F2": f"EMA {rule.get('n')}", "F3": "", "F4": f"ATR x{_fmt(rule.get('m', 0))}",
            "F5": f"{_fmt(rule.get('P', 0))}R 뒤 {int(round(rule.get('g', 0) * 100))}% 반납",
            "F6": f"스윙 {rule.get('w')}봉, 손실 {_fmt(rule.get('d', 0))}R 이상",
            "F7": f"{rule.get('N')}봉", "F7h": f"{rule.get('H')}시간", "F8": f"스윙 {rule.get('w')}봉, {_fmt(rule.get('P', 0))}R 뒤",
            "F9": "", "F10": f"{rule.get('N')}봉", "F11": "", "F12": "", "F13": ""}[f]
    mode = "익절 유지" if rule["mode"] == "a" else "익절 없음"
    return f"{KO[f]}{' (' + bits + ')' if bits else ''} · {mode}" + (" · 15분 확인" if rule.get("q15") else "")


# ====================================================================== the config file and the accounts
def load_config(path: Optional[str] = None) -> Optional[dict]:
    """The rule config (None when the file does not exist: then the league creates no rule account):
    {"enabled": bool, "pools": {"core": <rule id or dict or null>, "ds": ...}, "picks": [candidate ids] (optional: every
    candidate of the pools), "no_entry_from_ms": {"core": ms or null, "ds": ...}}. A pool with a rule runs that new exit (the
    pool's PASS, PREREG 11.1); a pool with null runs its current exit only. Raises RuleConfigError for a file that exists but
    cannot be run."""
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
    if isinstance(doc, dict) and "owner_exits" in doc:
        return normalize_owner(doc)
    if not isinstance(doc, dict) or not isinstance(doc.get("pools"), dict) or not doc["pools"]:
        raise RuleConfigError("rule config: 'pools' must say, per pool (core, ds), the new exit or null")
    bad = [k for k in doc["pools"] if k not in POOLS]
    if bad:
        raise RuleConfigError(f"rule config: unknown pools {bad} (core, ds)")
    pools = {}
    for pool in POOLS:
        v = doc["pools"].get(pool)
        if v is None:
            pools[pool] = None
            continue
        rule = parse_rule(v["rule"] if isinstance(v, dict) and "rule" in v else v)
        pools[pool] = {"rule": rule, "label_ko": str(v.get("label_ko", "")) if isinstance(v, dict) else ""}
    picks = doc.get("picks")
    if picks is not None and (not isinstance(picks, list) or not all(isinstance(p, str) for p in picks)):
        raise RuleConfigError("rule config: 'picks' must be a list of candidate ids")
    nef = doc.get("no_entry_from_ms") or {}
    if not isinstance(nef, dict) or any(k not in POOLS for k in nef) or any(
            v is not None and (isinstance(v, bool) or not isinstance(v, int) or v <= 0) for v in nef.values()):
        raise RuleConfigError("rule config: 'no_entry_from_ms' must map core / ds to a time in ms or null")
    enabled = doc.get("enabled", False)
    if not isinstance(enabled, bool):
        raise RuleConfigError("rule config: 'enabled' must be true or false")
    return {"enabled": enabled, "pools": pools, "picks": picks, "no_entry_from_ms": {p: nef.get(p) for p in POOLS}}


def pick_list(cands: list[dict], cfg: dict) -> list[dict]:
    """The picks that get accounts: the listed ids, else every candidate of both pools (D11 governs what is shown, not what runs)."""
    if cfg.get("picks") is None:
        return list(cands)
    by_id = {c["id"]: c for c in cands}
    missing = [p for p in cfg["picks"] if p not in by_id]
    if missing:
        raise RuleConfigError(f"rule config: picks {missing} are not in the candidate list")
    return [by_id[p] for p in cfg["picks"]]


def accounts(cands: list[dict], cfg: dict) -> list[dict]:
    """The restarted league's accounts (PREREG 11.2; see the module docstring). Each is {id, kind, name, tf, combo, exit, source, role,
    of, pick, size, rule}; ``rule`` is the normalized rule, or NO_RULE for the pick's own exit (E0). A pool with a new exit: ``-n``,
    ``-nq``, ``-e``, ``-eq``, ``-nflip``; a pool without: ``-e``, ``-eq``, ``-eflip``. The accounts of the new exit carry
    ``no_entry_from_ms`` when the config sets it (the C1 script's output, PREREG 11.4 item 9). A config of the owner-exit form
    (``"owner_exits"``) gives ``owner_accounts`` instead."""
    if cfg.get("mode") == "owner":
        return owner_accounts(cands, cfg)
    out = []
    for c in pick_list(cands, cfg):
        base = {k: c[k] for k in ("kind", "name", "tf", "combo", "exit")}
        pid, pool = c["id"], c["kind"]
        new = (cfg.get("pools") or {}).get(pool)
        nef = (cfg.get("no_entry_from_ms") or {}).get(pool)

        def acct(suffix, role, size, rule, of, src, with_nef=False):
            a = {**base, "id": pid + suffix, "role": role, "of": of, "pick": pid, "size": size, "rule": rule, "source": dict(src)}
            if with_nef and nef:
                a["no_entry_from_ms"] = int(nef)
            return a
        twin = {"rule_of": pid, "rule": "E0"}
        if new:
            rule = new["rule"]
            src = {"rule": rule["id"], "rule_of": pid}
            if new["label_ko"]:
                src["label_ko"] = new["label_ko"]
            out.append(acct("-n", ROLE_LIVE, 1.0, rule, pid, src, True))
            out.append(acct("-nq", ROLE_RULE, C.QUARTER, rule, pid, src, True))
            out.append(acct("-e", ROLE_BASE_LIVE, 1.0, dict(NO_RULE), pid, twin))
            out.append(acct("-eq", ROLE_BASE, C.QUARTER, dict(NO_RULE), pid, twin))
            out.append(acct("-nflip", ROLE_FLIP, C.QUARTER, rule, pid + "-nq", src, True))
        else:
            out.append(acct("-e", ROLE_BASE_LIVE, 1.0, dict(NO_RULE), pid, twin))
            out.append(acct("-eq", ROLE_BASE, C.QUARTER, dict(NO_RULE), pid, twin))
            out.append(acct("-eflip", ROLE_FLIP, 1.0, dict(NO_RULE), pid + "-e", twin))
    return out


# ====================================================================== owner exits (owners 2026-10-12)
# "솔라나 롱으로 70%~80% 먹고 있던 수익률이 결국 익절가가 너무 길어서 ... 커스텀값봇들을 익절기준이랑 손절기준을 좀 바꾸고
# 싶어서": per pick, the current-exit account and, next to it on the same signals, accounts with other exits. The file says
# which (``normalize_owner``); the code adds no exit of its own. The study's rules run on its RuleEngine exactly as above (no new
# rule logic); a changed take-profit is another exit of candleague.exits on the plain engine; the weekend switch is a gate on
# new entries only.
OWNER_KEYS = frozenset(("suffix", "label_ko", "short_ko", "desc_ko", "why_ko", "rule", "exit", "weekend_off", "size", "stop_max", "coin_of", "tighten"))
OWNER_RESERVED = ("quarter", "exitonly", "base", "flip") + ROLES           # role names other leagues give their accounts
OWNER_MAX = 20
_SUFFIX_RE = re.compile(r"^-[a-z][a-z0-9]{0,7}$")
TP_NAMES = tuple(r[0] for r in X.TP_RULES) + (X.ULAD,)
WEEKEND_KO = "토 00:00 ~ 월 00:00 UTC (한국 토 09:00 ~ 월 09:00)"
WEEKEND_REASON = "weekend off: no new entry from a signal bar closing Sat 00:00 - Mon 00:00 UTC"


def is_weekend(ms: int) -> bool:
    """Saturday 00:00 <= t < Monday 00:00 UTC (1970-01-01 was a Thursday, so (day + 3) % 7 is 0 on a Monday); the owners' weekend,
    as research/exitflex/extra/common.is_weekend and research/hunt/reads_o.is_weekend_close read it."""
    return (int(ms) // DAY + 3) % 7 >= 5


def _owner_words(e: dict) -> tuple:
    """(short label, what it does, what it is for) in plain Korean for an owner-exit entry the file does not describe itself."""
    r, tp = e["rule"], e["tp"]
    if e.get("coin_of"):
        return ("동전", "같은 청산 · 방향만 같은 신호 시각에 동전으로 정함 · 시장 방향 덕을 가리는 대조 계좌", "번 것이 시장 방향 덕인지 가르는 대조")
    if e["kind"] == "own":
        return "지금", "후보의 지금 익절·손절 그대로 (비교 기준)", "다른 계좌들이 이보다 나은가를 보는 기준"
    if r is not None and r["family"] == "F2":
        tail = "고정 익절 없음" if r["mode"] == "b" else "후보의 익절은 그대로"
        return ("이동평균", f"그 후보 봉의 EMA({r['n']})를 반대로 넘어 마감하면 다음 분 시장가로 청산 (먼저 EMA 바른 쪽에서 한 번 마감해야 켜짐) · "
                f"{tail} · 손절은 그대로", "추세가 꺾일 때 나와서 크게 번 수익을 지키나")
    if r is not None and r["family"] == "F5":
        tail = "후보의 익절과 손절은 그대로" if r["mode"] == "a" else "고정 익절 없음 · 손절은 그대로"
        return ("반납 보호", f"수익이 +{_fmt(r['P'])}R(손절 거리 {_fmt(r['P'])}배)에 닿은 뒤, 봉 마감 때 최고 수익의 "
                f"{int(round(r['g'] * 100))}%를 돌려주면 다음 분 시장가로 청산 · {tail}", "크게 벌었다가 다 돌려주는 일을 막으면 나은가")
    if r is not None and tp == X.ULAD:
        cap = f"손절은 최대 {e['stop_max']:g} ATR" if e.get("stop_max") else "손절은 후보의 것 그대로"
        when = (f"{r['w']}봉 스윙 구조가 무너지면(반대로 마감)" if r["family"] == "F1" else
                f"{r['w']}봉 스윙 구조가 무너지고 손실이 손절 거리의 {_fmt(r['d'] * 100)}% 넘게 났으면" if r["family"] == "F6" else
                f"{rule_ko(r)} 규칙이 켜지면")
        base = f"계단 익절(+13%→+10%, +20%→+15% …) · {cap} · {when}"
        if e.get("tighten"):
            return ("손절 좁힘", f"{base} 청산하지 않고 손절선을 처음 거리의 {_fmt(e['tighten'] * 100)}%로 좁힘(가격이 이미 그 선을 넘었으면 바로 시장가 청산) · 한 번 좁힌 손절은 되돌리지 않음",
                    "구조가 무너질 때 바로 자르는 것보다 손절만 좁히는 편이 나은가")
        return (("빠른 손절", f"{base} 다음 분 시장가로 청산", "구조가 무너질 때 손실을 줄이고도 승률이 버티나") if r["family"] == "F6" else
                ("구조 청산", f"{base} 다음 분 시장가로 청산 (이익 중이든 손실 중이든)", "구조가 무너지면 이익이든 손실이든 나오는 편이 나은가"))
    if r is not None:
        return KO[r["family"]], f"{rule_ko(r)} · 손절은 그대로", "이 청산 규칙이 지금 청산보다 나은가"
    if tp == X.ULAD:
        cap = f" · 손절은 후보의 것, 단 최대 {e['stop_max']:g} ATR" if e.get("stop_max") else " · 손절은 후보의 것 그대로"
        return ("계단", "수수료 뺀 순수익이 +13%에 닿으면 +10%에 손절선을 올리고, +20%면 +15%, +25%면 +20%, +30%면 +25% (이후 5%씩) · 고정 익절 없음" + cap,
                "손절을 좁히면 승률과 손실이 어떻게 달라지나" if e.get("stop_max") else "계단식 익절로 승률을 지키며 나오면 나은가")
    if tp is not None:
        ko = X.TP_KO[tp]
        kind, val = {x[0]: (x[1], x[2]) for x in X.TP_RULES}[tp]
        short = ko.replace("고정 익절 수익 ", "ROE ").replace("고정 익절 ", "익절 ")
        what = (f"증거금 대비 순수익 +{int(round(val * 100))}%(수수료 뺀 뒤)에 미리 걸어 둔 지정가로 익절 · 손절은 그대로"
                if kind == X.TP_ROE else f"{ko} · 손절은 그대로")
        return short, what, "짧게 확실히 먹고 나오면 나은가" if kind == X.TP_ROE else "이 익절이 지금 청산보다 나은가"
    return "주말 쉼", f"지금 청산과 같음 · {WEEKEND_KO}에 마감한 봉의 신호로는 새로 들어가지 않음 · 열린 포지션은 그대로 관리", "주말 신호를 거르면 나은가"


def _owner_entry(x, i: int) -> dict:
    """One normalized entry of ``owner_exits``: {suffix, role, kind (own / rule / exit / weekend), label_ko, short_ko, desc_ko, why_ko,
    rule (normalized or None), tp (a take-profit rule name or None), weekend_off, size}. RuleConfigError when it cannot be run."""
    where = f"owner_exits[{i}]"
    if not isinstance(x, dict):
        raise RuleConfigError(f"rule config: {where} must be an object")
    bad = sorted(set(x) - OWNER_KEYS)
    if bad:
        raise RuleConfigError(f"rule config: {where} has unknown keys {bad} (allowed: {sorted(OWNER_KEYS)})")
    suffix = x.get("suffix")
    if not isinstance(suffix, str) or not _SUFFIX_RE.match(suffix):
        raise RuleConfigError(f"rule config: {where} suffix {suffix!r} must look like '-ma' (a dash, then 1-8 small letters or digits)")
    label = x.get("label_ko")
    if not isinstance(label, str) or not label.strip() or len(label) > 40:
        raise RuleConfigError(f"rule config: {where} needs a Korean label 'label_ko' (1-40 characters)")
    for k in ("short_ko", "desc_ko", "why_ko"):
        if k in x and (not isinstance(x[k], str) or not x[k].strip() or len(x[k]) > 300):
            raise RuleConfigError(f"rule config: {where} {k} must be a short text")
    rule = parse_rule(x["rule"]) if x.get("rule") is not None else None
    tp = x.get("exit")
    if tp is not None:
        if rule is not None and tp != X.ULAD:
            raise RuleConfigError(f"rule config: {where} has both a rule and an exit (one or the other; only the owners' ladder {X.ULAD!r} takes a rule)")
        if rule is not None and (rule["mode"] != "a" or rule["family"] in NATIVE_FAMILIES + LOCK_FAMILIES):
            raise RuleConfigError(f"rule config: {where} the owners' ladder takes a decision rule of mode a only (mode b has no lock; F11, F12, F13 are not decisions on the chart)")
        if not isinstance(tp, str) or tp not in TP_NAMES:
            raise RuleConfigError(f"rule config: {where} exit {tp!r} is not a take-profit rule of candleague.exits ({', '.join(TP_NAMES)}); "
                                  "the pick's own stop multiple is kept, so name the take-profit only (e.g. 'roe50')")
        if tp != X.ULAD and {r[0]: r[1] for r in X.TP_RULES}[tp] == X.TP_STRUCT:
            raise RuleConfigError(f"rule config: {where} exit {tp!r} needs a structure level the league does not hand in here")
    sm = x.get("stop_max")
    if sm is not None and (isinstance(sm, bool) or not isinstance(sm, (int, float)) or float(sm) not in X.STOPS or tp is None):
        raise RuleConfigError(f"rule config: {where} stop_max must be one of the stops {list(X.STOPS)} and needs an 'exit'")
    coin = x.get("coin_of")
    if coin is not None and (not isinstance(coin, str) or not _SUFFIX_RE.match(coin) or tp is None or rule is not None):
        raise RuleConfigError(f"rule config: {where} coin_of must be the suffix of another entry (like '-ld') and needs an 'exit' (and no rule)")
    tg = x.get("tighten")
    if tg is not None and (isinstance(tg, bool) or not isinstance(tg, (int, float)) or not 0 < float(tg) <= 1 or rule is None or tp != X.ULAD):
        raise RuleConfigError(f"rule config: {where} tighten must be a number in (0, 1] (the share of the stop distance the stop narrows to) "
                              "and needs a rule on the owners' ladder")
    wk = x.get("weekend_off", False)
    if not isinstance(wk, bool):
        raise RuleConfigError(f"rule config: {where} weekend_off must be true or false")
    size = x.get("size", 1.0)
    if isinstance(size, bool) or not isinstance(size, (int, float)) or not 0 < float(size) <= 1:
        raise RuleConfigError(f"rule config: {where} size must be a number in (0, 1] (1 = the league's live size)")
    kind = "rule" if rule is not None else "exit" if tp is not None else "weekend" if wk else "own"
    role = "cand" if kind == "own" and float(size) == 1.0 else suffix[1:]
    if coin is not None and role == "cand":
        raise RuleConfigError(f"rule config: {where} cannot be both the current exit and a coin flip")
    if role != "cand" and role in OWNER_RESERVED:
        raise RuleConfigError(f"rule config: {where} suffix {suffix!r} gives the role {role!r}, which another league's accounts use")
    e = {"suffix": suffix, "role": role, "kind": kind, "label_ko": label.strip(), "rule": rule, "tp": tp, "weekend_off": wk,
         "size": float(size), "stop_max": None if sm is None else float(sm), "coin_of": coin,
         "tighten": None if tg is None else float(tg)}
    short, desc, why = _owner_words(e)
    e.update(short_ko=str(x.get("short_ko") or short).strip(), desc_ko=str(x.get("desc_ko") or desc).strip(),
             why_ko=str(x.get("why_ko") or why).strip())
    return e


def normalize_owner(doc: dict) -> dict:
    """The owner-exit form of the config: {"enabled": bool, "owner_exits": [entries], "picks": [ids] (optional)}. Exactly one
    entry is the pick's current exit at the live size (no rule, no exit, no weekend switch: role ``cand``); suffixes and roles are
    unique. ``pools`` and ``no_entry_from_ms`` belong to the study's form and are refused here (no pool rule, no C1 stop)."""
    if "pools" in doc:
        raise RuleConfigError("rule config: either 'pools' (the exit study's restart) or 'owner_exits', not both")
    if doc.get("no_entry_from_ms"):
        raise RuleConfigError("rule config: 'no_entry_from_ms' is the exit study's C1 stop and has no meaning with 'owner_exits'")
    ents = doc.get("owner_exits")
    if not isinstance(ents, list) or not ents or len(ents) > OWNER_MAX:
        raise RuleConfigError(f"rule config: 'owner_exits' must list 1-{OWNER_MAX} accounts per pick")
    out = [_owner_entry(x, i) for i, x in enumerate(ents)]
    for key in ("suffix", "role"):
        seen = [e[key] for e in out]
        if len(set(seen)) != len(seen):
            raise RuleConfigError(f"rule config: owner_exits repeat a {key} ({seen})")
    by_suffix = {e["suffix"]: e for e in out}
    for e in out:
        if e["coin_of"] is not None and (e["coin_of"] not in by_suffix or by_suffix[e["coin_of"]]["coin_of"] is not None
                                         or by_suffix[e["coin_of"]]["tp"] is None or by_suffix[e["coin_of"]]["rule"] is not None):
            raise RuleConfigError(f"rule config: owner_exits {e['suffix']!r} coin_of {e['coin_of']!r} must name another entry with an "
                                  "'exit' that is not a coin twin itself")
    own = [e for e in out if e["role"] == "cand"]
    if len(own) != 1:
        raise RuleConfigError("rule config: owner_exits must hold the pick's current exit once (an entry with no rule, no exit, no "
                              "weekend switch and the live size): the others are compared with it")
    picks = doc.get("picks")
    if picks is not None and (not isinstance(picks, list) or not all(isinstance(p, str) for p in picks)):
        raise RuleConfigError("rule config: 'picks' must be a list of candidate ids")
    enabled = doc.get("enabled", False)
    if not isinstance(enabled, bool):
        raise RuleConfigError("rule config: 'enabled' must be true or false")
    return {"enabled": enabled, "mode": "owner", "owner_exits": out, "picks": picks, "pools": {p: None for p in POOLS},
            "no_entry_from_ms": {p: None for p in POOLS}}


def owner_accounts(cands: list[dict], cfg: dict) -> list[dict]:
    """The owner-exit league's accounts: per pick (the listed ones, else every candidate) one account per entry of
    ``cfg["owner_exits"]``, id ``<pick id><suffix>``, in the file's order. The current-exit account (role ``cand``) keeps the pick's
    source (its backtest band and rank) and is the ``of`` of the others. A take-profit entry runs "<take-profit>|<the pick's own
    stop multiple>" (``stop_max``: at most that multiple); a pick whose own exit is already that one, or an earlier entry of the same
    pick that runs it, gets no such account. An entry with ``coin_of`` is that other entry's account with a seeded coin for the side
    at the pick's signal times (``coin``). Each carries ``ox`` (the entry's role, suffix and Korean words) and ``weekend_off`` when
    the entry has the weekend switch."""
    ents = cfg["owner_exits"]
    own = next(e for e in ents if e["role"] == "cand")
    out = []
    for c in pick_list(cands, cfg):
        pid = c["id"]
        k = c["exit"].split("|", 1)[1]
        cand_id = pid + own["suffix"]
        made, seen = {}, {}
        for e in ents:
            exit_ = c["exit"]
            tgt = None
            if e["tp"]:
                kk = k if e["stop_max"] is None else f"{min(float(k), e['stop_max']):g}"
                exit_ = f"{e['tp']}|{kk}"
            if e["coin_of"]:
                tgt = made.get(e["coin_of"])
                if tgt is None:
                    continue                                  # that entry made no account for this pick
                exit_ = tgt["exit"]
            elif e["tp"]:
                key = (exit_, bool(e["weekend_off"]), e["size"], e["rule"]["id"] if e["rule"] is not None else None, e["tighten"])
                if (e["rule"] is None and exit_ == c["exit"]) or key in seen:
                    continue                                  # the pick's own exit (or an earlier entry's) already: no duplicate account
                seen[key] = e["suffix"]
            src = {"pick": pid, "owner_exit": e["suffix"], "label_ko": e["label_ko"]}
            if e["role"] == "cand":
                src = {**(c.get("source") or {}), **src}
            elif tgt is not None:
                src["coin_of"] = tgt["id"]
            elif e["rule"] is not None:
                src["rule"] = e["rule"]["id"]
                if e["tp"]:
                    src["exit_of"] = c["exit"]
            elif e["tp"]:
                src["exit_of"] = c["exit"]
            a = {**{q: c[q] for q in ("kind", "name", "tf", "combo")}, "exit": exit_, "id": pid + e["suffix"], "role": e["role"],
                 "of": (tgt["id"] if tgt is not None else pid if e["role"] == "cand" else cand_id), "pick": pid, "size": e["size"],
                 "rule": dict(e["rule"]) if e["rule"] is not None else dict(NO_RULE), "source": src,
                 "ox": {q: e[q] for q in ("role", "suffix", "kind", "label_ko", "short_ko", "desc_ko", "why_ko", "tp", "weekend_off", "size")}}
            a["ox"]["rule"] = e["rule"]["id"] if e["rule"] is not None else None
            if e["tighten"] is not None:
                a["tighten"] = e["tighten"]
                a["ox"]["tighten"] = e["tighten"]
            if e["weekend_off"]:
                a["weekend_off"] = True
            if tgt is not None:
                a["coin"] = True
            made[e["suffix"]] = a
            out.append(a)
    return out


def lineup(accts: list[dict]) -> Optional[list[dict]]:
    """The owner-exit league's account kinds in the file's order, for the dashboard and the Telegram summary: [{role, suffix, kind,
    label_ko, short_ko, desc_ko, why_ko, rule, tp, weekend_off, size, accounts}]; None for any other league."""
    out, by = [], {}
    for a in accts:
        ox = a.get("ox")
        if not ox:
            continue
        if ox["role"] not in by:
            by[ox["role"]] = {**ox, "accounts": 0}
            out.append(by[ox["role"]])
        by[ox["role"]]["accounts"] += 1
    return out or None


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
        if not X.known(a["exit"]):
            bad.append(f"{a['id']}: exit {a['exit']!r} unknown")
        else:
            try:
                if not X.known(exit_name(a)):
                    bad.append(f"{a['id']}: exit {exit_name(a)!r} unknown")
            except (KeyError, ValueError):
                bad.append(f"{a['id']}: exit {a['exit']!r} has no F13 form")
    if any(a["rule"]["family"] in NATIVE_FAMILIES for a in accts):
        try:
            native_provider()
        except RuleConfigError as exc:
            bad.append(str(exc))
    return bad


def load_accounts(path: Optional[str], cands: list[dict]) -> Optional[list[dict]]:
    """The restarted league's accounts from the config file; None when there is no file or it is not enabled (``"enabled": true`` is
    the owners' OK, PREREG 11.1: committing the file alone starts nothing)."""
    cfg = load_config(path)
    if cfg is None or not cfg["enabled"]:
        return None
    bad = check(cands, cfg)
    if bad:
        raise RuleConfigError("; ".join(bad))
    return accounts(cands, cfg)


def code_version(rule: dict) -> str:
    """What a rule account's meaning depends on besides its own definition (runner.fingerprint of rule accounts only): this module's
    RULEX_VERSION and, for F11 and F12, the sha256 of the native exit modules the study runs (so a changed definition starts the
    league over instead of mixing two code versions in one record)."""
    v = str(RULEX_VERSION)
    if rule.get("family") in NATIVE_FAMILIES:
        v += "|" + native_hash()
    if rule.get("family") in LOCK_FAMILIES:                  # the lock's numbers are part of what an F13 account means
        v += "|lock" + ",".join(format(x, "g") for x in X.LOCK)
    return v


# ====================================================================== F11 / F12: the strategy's own exit
NATIVE: dict = {"provider": None}
NATIVE_FILES = ("native.py", "native_ds.py")


def register_native(fn: Optional[Callable]) -> None:
    """Register the provider of the strategy's own exit: ``fn(account, sym, df, close_ms, long_flags, short_flags, btc_frame) ->
    {"comp_long": [(kind, array)...], "comp_short": [...], "lvl_long": array|None, "lvl_short": ..., "tgt_long": ..., "tgt_short": ...}``
    (``kernel_x.register_f11``'s contract: kind 'state' or 'event', one array value per chart bar, booleans or floats with NaN for
    'neither fires nor arms'; levels and targets indexed by the signal bar, NaN elsewhere)."""
    NATIVE["provider"] = fn


def native_dir() -> str:
    return os.path.join(C.ROOT, "research", "exitflex")


def native_hash() -> str:
    """sha256 over native.py and native_ds.py (research/exitflex), the code that defines the strategies' own exits; 'absent' when missing."""
    import hashlib
    h = hashlib.sha256()
    for f in NATIVE_FILES:
        path = os.path.join(native_dir(), f)
        if not os.path.exists(path):
            return "absent"
        with open(path, "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()[:16]


def load_native_provider() -> Callable:
    """The production provider: research/exitflex/native.py (core strategies) and native_ds.py (DeepSeek), the code the study runs
    (PREREG 11.4 item 4). RuleConfigError when they cannot be imported."""
    import importlib
    import sys
    d = native_dir()
    try:
        if d not in sys.path:
            sys.path.insert(0, d)
        native, native_ds = importlib.import_module("native"), importlib.import_module("native_ds")
    except Exception as exc:  # noqa: BLE001
        raise RuleConfigError(f"F11 / F12: the native exit modules cannot be imported ({type(exc).__name__}: {exc})") from None

    def prov(a, sym, df, close_ms, lo, sh, btc):
        if a["kind"] == "core":
            r = native.native_arrays(a["name"], df, a["tf"], a["combo"])
            return {k: r.get(k) for k in ("comp_long", "comp_short", "lvl_long", "lvl_short", "tgt_long", "tgt_short")}
        ctx = None if sym == "BTCUSDT" else {"BTCUSD": btc}
        r = native_ds.native(df, a["tf"], a["name"], a["combo"], ctx, sym[:-1])
        if isinstance(r, dict):
            lx, sx, inv_l, inv_s, tgt_l, tgt_s = (r[k] for k in ("lx", "sx", "inv_l", "inv_s", "tgt_l", "tgt_s"))
        else:
            lx, sx, inv_l, inv_s, tgt_l, tgt_s = r
        return {"comp_long": [("state", lx)], "comp_short": [("state", sx)], "lvl_long": inv_l, "lvl_short": inv_s,
                "tgt_long": tgt_l, "tgt_short": tgt_s}
    return prov


def native_provider() -> Callable:
    """The registered provider, else the production one (loaded once)."""
    if NATIVE["provider"] is None:
        NATIVE["provider"] = load_native_provider()
    return NATIVE["provider"]


NC = 6                                   # components per side (kernel_x.NC)


def _tri(a) -> list:
    """0 / 1 / 2 (unknown: NaN) per bar of a component array (booleans, or floats with NaN)."""
    a = np.asarray(a)
    if a.dtype == bool:
        return a.astype(np.int8)
    a = a.astype(float)
    return np.where(np.isnan(a), 2, (a != 0)).astype(np.int8)


def normalize_native(ret: dict, n: int) -> dict:
    """The provider's return value as {"kinds": {"l": [...], "s": [...]}, "tri": {"l": [arrays], "s": [...]}, "lvl": {"l": array,
    "s": array}, "tgt": {...}} for ``n`` chart bars; refuses a component that is not (kind, array of n values) or more than NC."""
    nan = np.full(n, np.nan)
    out = {"kinds": {}, "tri": {}, "lvl": {}, "tgt": {}}
    for key, side in (("long", "l"), ("short", "s")):
        comps = list(ret.get("comp_" + key) or [])
        if len(comps) > NC:
            raise RuleConfigError(f"F11: at most {NC} components per side")
        for kind, arr in comps:
            if kind not in ("state", "event") or len(arr) != n:
                raise RuleConfigError("F11: a component is (kind in 'state' / 'event', one value per chart bar)")
        out["kinds"][side] = [k for k, _ in comps]
        out["tri"][side] = [_tri(arr) for _, arr in comps]
        for what in ("lvl", "tgt"):
            v = ret.get(f"{what}_{key}")
            if v is not None and len(v) != n:
                raise RuleConfigError(f"F11: the {what}_{key} array does not match the {n} chart bars")
            out[what][side] = nan if v is None else np.asarray(v, float)
    return out


def flip_levels(side_strategy: int, side_flip: int, fill_flip: float, inv: float, tgt: float) -> tuple:
    """PREREG 11.2 (the F11 coin flip; kernel_x.flip_levels): the invalidation level and target of a position on side ``side_flip``
    whose signal bar belongs to a strategy trade on side ``side_strategy`` (level ``inv``, target ``tgt``; NaN = none). On the
    strategy's own side the values stand. On the other side they are mirrored around the flip's fill: inv' = f' - side' x |f' - inv|,
    tgt' = f' + side' x (tgt - f') x s, the target only where (tgt - f') x s > 0. A NaN input gives no level / target."""
    if side_flip == side_strategy:
        return inv, tgt
    inv2 = fill_flip - side_flip * abs(fill_flip - inv) if math.isfinite(inv) else float("nan")
    ok = math.isfinite(tgt) and (tgt - fill_flip) * side_strategy > 0
    tgt2 = fill_flip + side_flip * (tgt - fill_flip) * side_strategy if ok else float("nan")
    return inv2, tgt2


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


def close_record(pack: FramePack, i: int, sym: str, close_ms: int, needs: dict, lo=None, sh=None, nat=None) -> dict:
    """The record of chart bar i's close for a rule with ``needs`` (rule_needs): {"k": "p", "sym", "t": close ms,
    "c": close} plus "atr", "ema" {n}, "sl"/"sh" {w: the swing low / high confirmed at this close, or None}, "lf"/"sf"
    (the pick's long / short flag), "nl"/"ns" (F11 / F12: the values, 1 true, 0 false, 2 unknown, of the long / short side's
    components at this bar). Everything is known at the bar's close."""
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
    if needs["nat"]:
        d["nl"] = [int(t[i]) for t in nat["tri"]["l"]]
        d["ns"] = [int(t[i]) for t in nat["tri"]["s"]]
    return d


def entry_seed(pack: FramePack, rule: dict, i: int, side: int, nat=None) -> dict:
    """What the position needs from the signal bar: F1-type reference (``ref``), F2's arm at entry (``above``: the signal bar's close
    is on the right side of its EMA), and for F11 / F12 the position side's component kinds (``ck``) and values at the signal bar
    (``nv``: 1 true, 0 false, 2 unknown; rule C3 arms a state component that is false there) and the signal bar's close (``c0px``,
    which arms the level test)."""
    seed = {}
    nd = rule_needs(rule)
    for w in nd["sw"]:
        ph, pl = pack.swings(w)
        seed["ref"] = start_ref(side, ph, pl, pack.h, pack.l, pack.c, i, w)
    for n in nd["ema"]:
        e = pack.ema(n)[i]
        seed["above"] = bool(math.isfinite(e) and (pack.c[i] - e) * side > 0)
    if nd["nat"] and nat is not None:
        key = "l" if side > 0 else "s"
        seed["ck"] = list(nat["kinds"][key])
        seed["nv"] = [int(t[i]) for t in nat["tri"][key]]
        seed["c0px"] = _fin(pack.c[i])
    return seed


# ====================================================================== rule state and decision (pure)
def new_rx(rule: dict, tf_ms: int, c0: int, seed: dict, atr: Optional[float], fill: float, open_time: int, side: int = 1) -> dict:
    """The rule state of a new position (kept in the signal meta; plain JSON). ``c0``: the signal bar's close; ``side``: the
    position's side. For F11 and F12 the seed also holds the strategy's level ``inv``, target ``tgt`` and side ``s0`` (the signal's
    ``native_*`` meta): a position on the other side gets them mirrored around its fill (``flip_levels``)."""
    f = rule["family"]
    rx = {"c0": int(c0), "k": 0, "x": float(fill), "tx": int(open_time), "q": []}
    if f in ("F1", "F6", "F8", "F9", "F12"):
        rx["ref"] = seed.get("ref")
    if f in ("F2", "F12"):
        rx["arm"] = bool(seed.get("above"))
    if f in ("F5", "F8", "F9", "F12"):
        rx["armed"] = False
    if f == "F7":
        rx["dl"] = int(c0) + int(rule["N"]) * int(tf_ms)
    if f in ("F7h", "F12"):                                         # clock hours from the signal bar's close (PREREG 5.2)
        rx["dl"] = int(c0) + int(rule["H"]) * 3_600_000
    if f in ("F4", "F12"):
        rx["atr"] = None if atr is None else float(atr)
    if f in NATIVE_FAMILIES:
        ck = list(seed.get("ck") or [])
        nv = list(seed.get("nv") or [])
        rx["ck"] = ck
        rx["car"] = [bool(k == "state" and i < len(nv) and nv[i] == 0) for i, k in enumerate(ck)]      # rule C3
        inv, tgt = seed.get("inv"), seed.get("tgt")
        s0 = seed.get("s0") or side
        inv2, tgt2 = flip_levels(int(s0), int(side), float(fill), float("nan") if inv is None else float(inv),
                                 float("nan") if tgt is None else float(tgt))
        rx["lvl"] = inv2 if math.isfinite(inv2) else None
        rx["tgt"] = tgt2 if math.isfinite(tgt2) else None
        c0px = seed.get("c0px")
        rx["carl"] = bool(rx["lvl"] is not None and c0px is not None and side * (rx["lvl"] - c0px) <= 0)
    return rx


def _update_levels(rule: dict, rx: dict, side: int, r: dict) -> None:
    f = rule["family"]
    if f in ("F4", "F12") and r.get("atr") is not None:
        rx["atr"] = r["atr"]
    if f in ("F1", "F6", "F8", "F9", "F12"):
        v = ((r.get("sl") if side > 0 else r.get("sh")) or {}).get(str(rule["w"]))
        if v is not None and (rx.get("ref") is None or (v - rx["ref"]) * side > 0):
            rx["ref"] = v
    if f in ("F2", "F12"):
        e = (r.get("ema") or {}).get(str(rule["n"]))
        if e is not None and (r["c"] - e) * side > 0:
            rx["arm"] = True


def _native_bar(rx: dict, side: int, r: dict) -> bool:
    """One chart close of F11 (PREREG A.0, rules C3 and C7): True when a component of the position's side fires at this bar. A state
    component (and the level test: the close is beyond the invalidation level) fires where it is true once it has been false at an
    earlier close; an event component fires where it is true; an unknown value (2, NaN) neither fires nor arms."""
    any_ = False
    vals = r.get("nl" if side > 0 else "ns") or []
    for c, kind in enumerate(rx["ck"]):
        vv = vals[c] if c < len(vals) else 2
        if vv == 2:
            continue
        if kind == "event":
            if vv == 1:
                any_ = True
        elif vv == 1:
            if rx["car"][c]:
                any_ = True
        else:
            rx["car"][c] = True
    lvl = rx.get("lvl")
    if lvl is not None and math.isfinite(r["c"]):
        if side * (lvl - r["c"]) > 0:
            if rx.get("carl"):
                any_ = True
        else:
            rx["carl"] = True
    return any_


def decide(rule: dict, sched: str, rx: dict, side: int, fill: float, R: float, rt: float, f: float, X_: float,
           tf_ms: int) -> bool:
    """One check at a minute: the queued chart records (rx["q"], consumed here) are read in order, the pick-timeframe
    ones update the levels (F1 reference, F2 arm, F4 ATR, F11's component arms), and the latest record of the schedule is the check
    close. ``side`` +1 / -1; ``fill`` the entry price with slippage; ``R`` the stop distance; ``rt`` the round-trip cost; ``f`` the
    funding paid per unit of notional before this minute; ``X_`` the favourable extreme before it; rx["tx"] is T_X. Returns True when
    the rule fires (F12: ``rx["comp"]`` = the bit mask of every component that fired, ``CB``). Nothing of the minute being decided
    enters."""
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
            if fam in NATIVE_FAMILIES and _native_bar(rx, side, r):
                xit = True
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
    if fam == "F12":
        # nine components on the same frozen state; none reads another's result (PREREG 5.2). The F2 arm is read as it was before the
        # check bar (a bar cannot arm and fire: arming needs the close above the EMA, firing below it).
        if rpk >= rule["P"]:
            rx["armed"] = True
        e = (chk.get("ema") or {}).get(str(rule["n"]))
        a = rx.get("atr")
        cm = 0
        if brk:
            cm |= CB["F1"]
        if rx["arm"] and e is not None and (c - e) * side < 0:
            cm |= CB["F2"]
        if opp:
            cm |= CB["F3"]
        if a is not None and (c - (X_ - side * rule["m"] * a)) * side < 0:
            cm |= CB["F4"]
        if rx["armed"] and rc <= (1 - rule["g"]) * rpk:
            cm |= CB["F5"]
        if brk and rc < -rule["d"]:
            cm |= CB["F6"]
        if chk["t"] >= rx["dl"]:
            cm |= CB["F7h"]
        if rc > 0 and chk["t"] - rx["tx"] >= rule["N"] * tf_ms:
            cm |= CB["F10"]
        if xit:
            cm |= CB["F11"]
        rx["comp"] = cm
        return cm != 0
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
    rx_no_entry_from: Optional[int] = None   # PREREG 11.4 item 9: from this time (ms) the account takes no new entry
    rx_weekend_off: bool = False             # owners 2026-10-12: no new entry from a signal bar closing Sat 00:00 - Mon 00:00 UTC
    rx_tighten: Optional[float] = None       # owners 2026-10-13: when the rule fires, narrow the stop to this share of the stop distance instead of closing

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
        if self.rx_no_entry_from is not None and bar.open_time >= self.rx_no_entry_from:
            self._record(sig, "REJECTED", "no new entry from the C1 time", bar.open_time)       # an open position closes by its own rules
            return False
        if self.rx_weekend_off and is_weekend(sig.ts + 1):                # the signal bar's close (Signal.ts = close - 1)
            self._record(sig, "REJECTED", WEEKEND_REASON, bar.open_time)                       # an open position is managed as usual
            return False
        ok = super()._try_enter(sig, bar)
        if ok and self.rx_rule is not None:
            p = self.position
            meta = p.signal.meta
            seed = dict(meta.get("rx0") or {})
            seed.update(inv=meta.get("native_inv"), tgt=meta.get("native_tgt"), s0=meta.get("native_s"))      # the strategy's level, target, side
            rx = new_rx(self.rx_rule, self.rx_tf_ms, p.signal.ts + 1, seed, p.signal.atr, p.entry_price, bar.open_time, p.side)
            rx["q"] = [dict(r) for r in meta.pop("rx_early", ()) if r["t"] > rx["c0"]]
            meta["rx"] = rx
            t = rx.get("tgt")
            if (self.rx_rule["family"] in NATIVE_FAMILIES and self.rx_rule["mode"] == "b" and t is not None
                    and (t - p.entry_price) * p.side > 0):
                p.tp_price = float(t)               # F11.b / F12.b: the strategy's own target as a limit, without the lock (PREREG C6, C8)
        return ok

    def _rx_decide(self, p, rx) -> bool:
        f = p.funding_paid / p.notional_entry if p.notional_entry else 0.0
        prev = None if self.rx_seen is None else self.rx_seen.get(p.symbol)
        return decide_ready(self.rx_rule, self.rx_sched, rx, p.side, p.entry_price, float(p.signal.meta["stop_dist"]),
                            self.s.round_trip_cost, f, p.mfe_price, self.rx_tf_ms, prev)

    def _narrow_stop(self, p) -> None:
        """The owners' stop narrowing: the stop moves to ``rx_tighten`` x the stop distance from the reference the first stop was set from (so 1 is
        the first stop itself), never away from the price. A stop the price is already beyond is a gap for the engine's own exit handling (a
        market close at the minute's open, slippage, taker fee)."""
        want = p.stop_initial + p.side * (1.0 - self.rx_tighten) * float(p.signal.meta["stop_dist"])
        new = tighten(p.side, p.stop_price, want)
        if new != p.stop_price:
            p.stop_price = new
            p.signal.meta.setdefault("ctx", {})["rx_narrowed"] = 1

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
                comp = (self.position.signal.meta.get("rx") or {}).get("comp")
                if comp is not None:                                  # F12: every component that fired at this check (PREREG 5.2, tr_comp)
                    self.position.signal.meta.setdefault("ctx", {})["rx_comp"] = int(comp)
                if self.rx_tighten is not None:
                    self._narrow_stop(self.position)                  # the engine's own exit handling below takes a stop the price is already past
                else:
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


class RuleUserLadder(RuleMixin, X.UserLadder):
    """The owners' stepped lock (``exits.UserLadder``) with a rule account's step order; with no rule it is that engine plus the gates."""


class LockEngine(RuleEngine):
    """F13 on a PaperEngine exit ("ladder|k", or a fixed take-profit with the lock): ``rx_rule`` stays None, so ``step`` and ``submit`` are the plain
    engine's; the engine carries only the C1 gate (``rx_no_entry_from``, PREREG 11.4 item 9) of ``RuleMixin._try_enter``."""


class LockLadderEngine(RuleLadderEngine):
    """The same on a ``candleague.exits.LadderTP`` exit (the lock with a take-profit at m x R, at a net ROE or at a structure level)."""


def _lock_engine(a: dict, brackets: dict, specs: dict) -> PaperEngine:
    """``exits.make_engine`` of ``exit_name(a)``, built as the same class with the ``RuleMixin`` gate and no rule: the same branches, the same
    settings, take-profit and policy (a test compares every field with ``exits.make_engine``). F13's engine, and the owner-exit league's
    weekend-off account (the pick's own exit with the weekend gate, ``rx_weekend_off``)."""
    name, size = exit_name(a), a.get("size", 1.0)
    s, st = X.spec(name), X.settings_for(name, size=size)
    if name.startswith(X.ULAD + "|"):
        return RuleUserLadder(st, brackets, symbol_specs=specs, book=a["id"])
    if s["ladder"] and s["tp_kind"] == X.TP_STRUCT:
        return LockLadderEngine(st, brackets, symbol_specs=specs, struct=True, book=a["id"])
    if s["ladder"] and s["tp_kind"] == X.TP_R:
        return LockLadderEngine(st, brackets, symbol_specs=specs, m=s["tp_val"], book=a["id"])
    if s["ladder"] and s["tp_kind"] == X.TP_ROE:
        return LockLadderEngine(st, brackets, symbol_specs=specs, roe=s["tp_val"], book=a["id"])
    if s["ladder"] or s["tp_kind"] == X.TP_ROE:
        return LockEngine(st, brackets, symbol_specs=specs, book=a["id"])
    return LockEngine(st, brackets, symbol_specs=specs, policy=X.RPolicy(st, s["tp_val"]), book=a["id"])


def make_engine(a: dict, brackets: dict, specs: dict) -> PaperEngine:
    """The engine of a rule-league account. The twins (no rule) are the plain engines of candleague.exits; a rule
    account is the same set-up (the pick's exit, ``size``) as a RuleMixin engine: mode a keeps the exit's own
    take-profit, mode b has none and no lock. An F13 account (the stepped lock) is the plain engine of the exit with the lock added, with the
    C1 gate (``rx_no_entry_from``) and no rule."""
    rule, name, size = a.get("rule") or NO_RULE, a["exit"], a.get("size", 1.0)
    weekend = bool(a.get("weekend_off"))
    if rule.get("family") is None:
        if not weekend:
            return X.make_engine(name, brackets, specs, book=a["id"], size=size)
        e = _lock_engine(a, brackets, specs)                               # the plain engine of the exit, with the weekend gate
        e.rx_weekend_off = True
        return e
    if rule["family"] in LOCK_FAMILIES:                                    # F13: another exit of candleague.exits, the plain engine with the C1 gate
        e = _lock_engine(a, brackets, specs)
        e.rx_no_entry_from = int(a["no_entry_from_ms"]) if a.get("no_entry_from_ms") else None
        e.rx_weekend_off = weekend
        return e
    s, st = X.spec(name), X.settings_for(name, size=size)
    if rule["mode"] == "b":
        st = replace(st, tp_mode="fixed")                  # no take-profit and no stepped lock
        e = RuleEngine(st, brackets, symbol_specs=specs, policy=NoTP(st), book=a["id"])
    elif name.startswith(X.ULAD + "|"):
        e = RuleUserLadder(st, brackets, symbol_specs=specs, book=a["id"])
        e.rx_tighten = a.get("tighten")
    elif s["ladder"] and s["tp_kind"] == X.TP_STRUCT:
        e = RuleLadderEngine(st, brackets, symbol_specs=specs, struct=True, book=a["id"])
    elif s["ladder"] and s["tp_kind"] == X.TP_R:
        e = RuleLadderEngine(st, brackets, symbol_specs=specs, m=s["tp_val"], book=a["id"])
    elif s["ladder"] or s["tp_kind"] == X.TP_ROE:
        e = RuleEngine(st, brackets, symbol_specs=specs, book=a["id"])
    else:
        e = RuleEngine(st, brackets, symbol_specs=specs, policy=X.RPolicy(st, s["tp_val"]), book=a["id"])
    e.rx_rule, e.rx_sched, e.rx_tf_ms = rule, sched_of(a), TF_MS[a["tf"]]
    e.rx_no_entry_from = int(a["no_entry_from_ms"]) if a.get("no_entry_from_ms") else None
    e.rx_weekend_off = weekend
    return e


# ====================================================================== the league side: signals and records per chunk
class BothFlags(RuntimeError):
    """A chart bar carries both a long and a short flag of one pick (PREREG 3: no pick does; the league asserts it and stops)."""


def native_arrays(a: dict, sym: str, df, close, lo, sh, btc) -> dict:
    """The strategy's own exit arrays of account ``a`` on ``sym``'s chart frame, normalized (``normalize_native``)."""
    ret = native_provider()(a, sym, df, close, lo, sh, btc)
    return normalize_native(ret, len(df))


def chunk_rule(lib, source, accts: list[dict], symbols: Iterable[str], start: int, end: int, run_start: int,
               strategies: Optional[L.Strategies] = None, log: Callable[[str], None] = lambda s: None) -> tuple:
    """The rule accounts' signals and chart records of the chart bars closing in (max(start, run_start), end]:
    ({bar close: [(account id, Signal or RuleClose)]}, [notes]). Twins and rule accounts offer every flag; a bar that carries both
    a long and a short flag stops the run (``BothFlags``, PREREG 3); a coin flip takes one signal per signal bar with its seeded
    side; a rule account also gets a RuleClose for every chart close of every coin (and every 15m close for q15 on 1h / 4h picks)."""
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
            natc: dict = {}
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
                if len(idx) and bool((lo[idx] & sh[idx]).any()):
                    raise BothFlags(f"{a['id']} {sym} {tf}: a chart bar carries both a long and a short flag (PREREG 3)")
                smod = S.strength(a["name"]) if a["kind"] == "core" else None
                if smod is not None and a["name"] not in strength:
                    try:
                        import warnings
                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore")
                            strength[a["name"]] = {"arrays": smod.strength(df.copy(), tf)}
                    except Exception as exc:  # noqa: BLE001  live: a failed strength sizes 'normal'
                        strength[a["name"]] = {"error": f"{type(exc).__name__}: {exc}"[:200]}
                rule, spec = a["rule"], X.spec(exit_name(a))
                decides = rule["family"] not in (None,) + LOCK_FAMILIES        # F13 makes no decision at a chart close: no seed, no record
                nat = None
                if rule["family"] in NATIVE_FAMILIES:
                    if key not in natc:
                        natc[key] = native_arrays(a, sym, df, close, lo, sh, frames.get("BTCUSDT"))
                    nat = natc[key]
                for pos in np.flatnonzero(lo[idx] | sh[idx]):
                    i = int(idx[pos])
                    at = float(pack.atr()[i])
                    if not (math.isfinite(at) and at > 0):
                        continue                                      # live: NO_ATR, never traded
                    s0 = 1 if lo[i] else -1                           # the strategy's side at this bar
                    s = flip_of(a, int(close[i])) if (a["role"] == ROLE_FLIP or a.get("coin")) else s0
                    meta = {"stop_dist": spec["stop_atr"] * at, "account": a["id"],
                            "ctx": {"strength": _strength_feats(strength.get(a["name"]), smod, i, s)}}
                    if rule["family"] is not None:
                        meta["style"] = f"rule:{rule['id']}"
                    if decides:
                        meta["rx0"] = entry_seed(pack, rule, i, s, nat)
                        if nat is not None:             # the strategy's level and target (mirrored at the fill for a flip: new_rx)
                            k0 = "l" if s0 > 0 else "s"
                            meta["native_inv"], meta["native_tgt"], meta["native_s"] = (
                                _fin(nat["lvl"][k0][i]), _fin(nat["tgt"][k0][i]), s0)
                    sig = Signal(ts=int(close[i]) - 1, symbol=sym, timeframe=tf, strategy_id=a["name"], side=s,
                                 stop_price=0.0, tier="best", atr=at, meta=meta)
                    by_close.setdefault(int(close[i]), []).append((a["id"], sig))
                if not decides:
                    continue
                needs = rule_needs(rule)
                rk = (key, json.dumps(needs, sort_keys=True))
                if rk not in recs:
                    recs[rk] = [close_record(pack, int(i), sym, int(close[i]), needs, lo, sh, nat) for i in idx]
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
    btc = None
    if a["kind"] == "ds" and sym != "BTCUSDT":                  # the DeepSeek strategies read BTC's chart as context
        bcols = source.load("BTCUSDT", lo_ms - window_5m(lib, tf) * FIVE, hi_ms)
        btc = rule_frame(lib, bcols, tf, hi_ms)
    lo, sh = S.signals(a, df, sym, btc) if (needs["flags"] or needs["nat"]) else (None, None)
    nat = native_arrays(a, sym, df, close, lo, sh, btc) if needs["nat"] else None
    for i in idx:
        out.append(close_record(pack, int(i), sym, int(close[i]), needs, lo, sh, nat))
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


_OUTCOME_COL = {"ENTERED": 0, "SKIPPED": 1, "REJECTED": 2}


def replay_day(engines: dict, active: set, by_close: dict, steps, brackets, seen: dict, fund_wait: Optional[dict] = None,
               stats: Optional[dict] = None, last_close: Optional[dict] = None) -> None:
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
    trades as paramshadow.replay_day.

    Counters (PREREG 11.4 item 10; ``paramshadow.replay_day`` clears ``e.outcomes`` at every step and so keeps none): with ``stats`` a
    dict, every signal outcome is counted before it is cleared, ``stats[(account id, UTC day of the decision)] = [entered, skipped while
    holding, rejected]``. ``last_close`` {coin: the last close price seen} is kept for the daily marks (11.4 item 11)."""
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
            if stats is not None:
                for o in e.outcomes:
                    row = stats.setdefault((aid, int(o.step_ts) // DAY * DAY), [0, 0, 0])
                    row[_OUTCOME_COL.get(o.status, 2)] += 1
            e.outcomes.clear()
            if held:
                e.pending = held + e.pending
            if e.position is None and not e.pending:
                active.discard(aid)
        for s, b in tb.items():
            seen[s] = ts
            if last_close is not None:
                last_close[s] = float(b.close)
        while k < len(closes) and closes[k] <= ts + MIN:
            for aid, sig in by_close[closes[k]]:
                engines[aid].submit(sig)
                active.add(aid)
            k += 1
    for c in closes[k:]:
        for aid, sig in by_close[c]:
            engines[aid].submit(sig)
            active.add(aid)


def mark_value(e, last_close: dict) -> float:
    """PREREG 11.4 item 11: the account's realised wallet plus, when a position is open, its mark value: the last 1m close (last
    price) of the held coin, less the taker fee and the slippage of a market exit, after the funding the position had paid by then
    (the engine's wallet already holds the entry fee and the funding)."""
    p = e.position
    if p is None:
        return float(e.wallet)
    px = float(last_close.get(p.symbol, p.entry_price))
    out = px * (1 - p.side * e.s.slippage_frac)
    return float(e.wallet + p.side * p.qty * (out - p.entry_price) - p.qty * out * e.s.taker_fee)


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


class IncompleteBars(RuntimeError):
    """The bars fetched for a recomputation do not reach as far as the league itself has seen: the answer was cut short."""


def check_coverage(steps, sym: str, entry_time: int, seen: Optional[dict]) -> None:
    """A recomputation from fetched bars must cover the position: a bar at the entry minute, and a last bar as late as the league's own
    last minute of the coin (``seen``). ``paperbot.paramshadow.make_fetcher`` stops quietly on an empty page, so a short answer would
    otherwise 'correct' a saved state to a wrong one (review): this raises, and ``audit_restored`` then keeps the saved state."""
    times = [t for t, bars, _f in steps if sym in bars and not (bars[sym].volume is not None and bars[sym].volume == 0.0)]
    if entry_time not in times:
        raise IncompleteBars(f"{sym}: no bar at the entry minute in the fetched bars")
    want = None if seen is None else seen.get(sym)
    if want is not None and max(times) < int(want):
        raise IncompleteBars(f"{sym}: the fetched bars end at {max(times)}, before the league's last minute {int(want)}")


def recompute_rx(lg, a: dict, p) -> dict:
    """The rule state of the open position ``p`` of account ``a`` as it should be at the league's ``done`` time, from
    the bars alone: the seed of the signal, the chart records closed since, and the position's minutes (the favourable
    extreme, the funding). The same ``decide`` / ``track_extreme`` the engine uses."""
    rule, sym = a["rule"], p.symbol
    tf_ms, sched = TF_MS[a["tf"]], sched_of(a)
    c0 = int(p.signal.ts) + 1
    meta = p.signal.meta
    seed = dict(meta.get("rx0") or {})
    seed.update(inv=meta.get("native_inv"), tgt=meta.get("native_tgt"), s0=meta.get("native_s"))
    rx = new_rx(rule, tf_ms, c0, seed, p.signal.atr, p.entry_price, p.entry_time, p.side)
    done = lg.done
    recs = sorted(account_records(lg.lib, lg.source, a, sym, c0, done, lg.strategies),
                  key=lambda r: (r["t"], 0 if r["k"] == "p" else 1))
    steps = lg.fetch_steps(None, [sym], p.entry_time // FIVE * FIVE, done)
    check_coverage(steps, sym, p.entry_time, getattr(lg, "seen", None))
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
        if not rule or rule.get("family") is None or rule["family"] in LOCK_FAMILIES:      # no rule state to recompute (F13: the engine's own lock)
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


# ====================================================================== forward checks C1 / C2 (PREREG 11.5, 11.4 item 14)
# The script that decides, from the league database alone (tables trades, acct_day, acct_mark), whether the new exit of a pool stops
# (C1, install + 30 days) or is shown ahead (C2, install + 61 days, the repeat at + 92). It prints DeepSeek as labels, counts, win shares
# and hold hours only (D11); the full figures go to a private folder on request.
CHECK_DAYS = {"c1": 30, "c2": 61, "repeat": 92}
P_LIMIT = {"c2": 0.03, "repeat": 0.02}                 # the exact sign-flip test of C2 and of its repeat
INITIAL_EQUITY = X.start_equity()
MONTH_DAYS = 365.25 / 12
MIN_TRADES_C2 = 150
EXACT_MAX_WEEKS = 20
N_RANDOM_PATTERNS = 20_000
ROLE_SUFFIX = {"nq": "-nq", "eq": "-eq", "nflip": "-nflip", "n": "-n", "e": "-e"}
DS_PUBLIC_KEYS = ("new_exit", "label", "conds", "trades_nq", "n_weeks", "hold", "win_share", "counts", "stopped_before")


def check_time(install_ms: int, which: str) -> int:
    """00:00 UTC of the install's UTC date + 30 / 61 / 92 days (11.5)."""
    return (int(install_ms) // DAY + CHECK_DAYS[which]) * DAY


def seed_of(*parts) -> int:
    """run._seed: the first 8 hex digits of the sha256 of the '|'-joined parts."""
    import hashlib
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def monthly_growth(w_end: float, install_ms: int, t_ms: int, w0: float = INITIAL_EQUITY) -> float:
    """G = ln(W_T / 5,000) / months, months = days / (365.25 / 12), days from the install to T (11.5)."""
    months = (int(t_ms) - int(install_ms)) / DAY / MONTH_DAYS
    return math.log(max(float(w_end), 1e-12) / w0) / months


def week_bounds(install_ms: int, t_ms: int) -> list[int]:
    """The week boundaries of C2's sign-flip test (11.5): UTC weeks from Monday 00:00; the part-week from the install to the first Monday
    is merged into the first full week, the part-week from the last Monday to the check time into the last full week. [install, ..., T]."""
    first_monday = (int(install_ms) // DAY + (4 - int(install_ms) // DAY) % 7) * DAY       # 1970-01-01 was a Thursday: Monday = day % 7 == 4
    mons = list(range(first_monday + (0 if first_monday >= install_ms else 7 * DAY), int(t_ms) + 1, 7 * DAY))
    mons = [m for m in mons if install_ms <= m <= t_ms]
    b = list(mons) if mons and mons[0] == install_ms else [int(install_ms)] + mons[1:]
    if b[-1] != t_ms:
        if len(b) >= 2:
            b[-1] = int(t_ms)                                    # the last Monday is dropped: its part-week is merged
        else:
            b.append(int(t_ms))
    return b


def sign_flip_p(d: list[float], seed: int) -> float:
    """One-sided sign-flip p of the mean of the weekly differences ``d`` (11.5): the share of the 2^n sign patterns e whose mean of
    e_w x d_w is >= the observed mean of d_w, all patterns counted (n <= 20); above 20 weeks 20,000 random patterns with ``seed``,
    p = (1 + count) / 20,001."""
    d = np.asarray(d, float)
    n = len(d)
    obs = d.mean()
    tol = 1e-12 * max(1.0, float(np.abs(d).max()) if n else 1.0)
    if n <= EXACT_MAX_WEEKS:
        signs = ((np.arange(2 ** n)[:, None] >> np.arange(n)[None, :]) & 1) * 2 - 1
        return float(((signs * d[None, :]).mean(axis=1) >= obs - tol).mean())
    e = np.random.default_rng(seed).choice([-1.0, 1.0], size=(N_RANDOM_PATTERNS, n))
    return float((1 + int(((e * d[None, :]).mean(axis=1) >= obs - tol).sum())) / (N_RANDOM_PATTERNS + 1))


def _marks(conn, t_ms: int) -> dict:
    return {a: (float(w), float(m)) for a, w, m in conn.execute("SELECT account, wallet, marked FROM acct_mark WHERE day = ?", (int(t_ms),))}


def _mark_series(conn, aid: str, bounds: list[int], install_ms: int) -> list[float]:
    """The marked wallet at every week boundary (5,000 at the install)."""
    out = [INITIAL_EQUITY]
    for b in bounds[1:]:
        row = conn.execute("SELECT marked FROM acct_mark WHERE account = ? AND day = ?", (aid, int(b))).fetchone()
        if row is None:
            raise LookupError(f"{aid}: no mark at {b}")
        out.append(float(row[0]))
    return out


def _trade_rows(conn, aid: str, t_ms: int) -> list[dict]:
    out = []
    for (d,) in conn.execute("SELECT data FROM trades WHERE account = ? AND exit_time < ? ORDER BY exit_time, rowid", (aid, int(t_ms))):
        out.append(json.loads(d))
    return out


def _hold(trades: list[dict]) -> dict:
    h = sorted((t["exit_time"] - t["entry_time"]) / 3_600_000.0 for t in trades)
    if not h:
        return {"n": 0, "median": None, "share_gt4": None, "share_gt8": None, "share_gt18": None}
    mid = h[len(h) // 2] if len(h) % 2 else (h[len(h) // 2 - 1] + h[len(h) // 2]) / 2
    return {"n": len(h), "median": round(mid, 3), **{f"share_gt{x}": round(sum(v > x for v in h) / len(h), 4) for x in (4, 8, 18)}}


def forward_check(conn, accts: list[dict], install_ms: int, which: str, stopped=(), skip=()) -> dict:
    """C1 (``which`` = "c1"), C2 ("c2") or the repeat ("repeat") of PREREG 11.5 from the league database ``conn`` (tables trades, acct_day,
    acct_mark) and the league's accounts ``accts`` (rulex.accounts): per pool with a new exit, the pooled monthly log growth G of its
    -nq, -eq and -nflip accounts at the check time T (the daily mark of 11.4 item 11, the realised-only wallet beside), then
    C1: stop when G(nq) < G(eq) and G(nq) < G(nflip); C2: shown ahead when G(nq) > G(eq) with the sign-flip test on the weekly
    differences below its limit, G(nq) > G(nflip), at least 150 closed -nq trades and G(nq) > 0. ``stopped``: pools stopped at C1
    (no C2); ``skip``: pools already shown ahead (not asked again at the repeat). Returns the full report (the DeepSeek money in it is
    for the private folder: ``public_view``)."""
    t = check_time(install_ms, which)
    report = {"which": which, "time_ms": t, "install_ms": int(install_ms), "days": (t - install_ms) / DAY, "pools": {}}
    marks = _marks(conn, t)
    by_pick: dict = {}
    for a in accts:
        by_pick.setdefault(a["pick"], {})[a["id"][len(a["pick"]):]] = a
    for pool in POOLS:
        picks = [pk for pk, r in by_pick.items() if next(iter(r.values()))["kind"] == pool]
        new = [pk for pk in picks if "-nq" in by_pick[pk]]
        if not picks or not new:
            continue
        rule = by_pick[new[0]]["-nq"]["rule"]["id"]
        info: dict = {"new_exit": rule, "picks": len(new)}
        if pool in stopped:
            info.update(label="stopped at C1", stopped_before=True)
            report["pools"][pool] = info
            continue
        if pool in skip:
            info.update(label="already shown ahead")
            report["pools"][pool] = info
            continue
        if any(by_pick[pk][ROLE_SUFFIX["nq"]]["id"] not in marks for pk in new):
            info.update(label="not yet (no mark at the check time)")
            report["pools"][pool] = info
            continue
        g, gr, win, hold, counts, mret = {}, {}, {}, {}, {}, {}
        for role in ("nq", "eq", "nflip"):
            ids = [by_pick[pk][ROLE_SUFFIX[role]]["id"] for pk in new]
            g[role] = float(np.mean([monthly_growth(marks[i][1], install_ms, t) for i in ids]))
            gr[role] = float(np.mean([monthly_growth(marks[i][0], install_ms, t) for i in ids]))
            rows = [r for i in ids for r in _trade_rows(conn, i, t)]
            hold[role] = _hold(rows)
            win[role] = (sum(r["pnl"] > 0 for r in rows) / len(rows)) if rows else None
            ct = conn.execute(f"SELECT SUM(offered), SUM(entered), SUM(skipped), SUM(rejected), SUM(closed) FROM acct_day WHERE day < ? AND account IN "
                              f"({','.join('?' * len(ids))})", (t, *ids)).fetchone()
            counts[role] = dict(zip(("offered", "entered", "skipped", "rejected", "closed"), (int(x or 0) for x in ct)))
            eq, rets = INITIAL_EQUITY, []
            for r in sorted(rows, key=lambda r: r["exit_time"]):          # the per-trade line (core only): P&L as a fraction of the wallet before
                rets.append(r["pnl"] / eq if eq > 0 else 0.0)
                eq += r["pnl"]
            mret[role] = float(np.mean(rets)) if rets else None
        info.update(g=g, g_realised=gr, mean_trade_return=mret, hold=hold, win_share=win, counts=counts,
                    trades_nq=counts["nq"]["closed"])
        if which == "c1":
            stop = g["nq"] < g["eq"] and g["nq"] < g["nflip"]
            info.update(label="stop" if stop else "continue", stop=stop, conds={"nq_below_eq": g["nq"] < g["eq"], "nq_below_flip": g["nq"] < g["nflip"]})
            info["no_entry_from_ms"] = t if stop else None
        else:
            bounds = week_bounds(install_ms, t)
            diffs = []
            for w in range(1, len(bounds)):
                dn = [math.log(max(s[w], 1e-12) / max(s[w - 1], 1e-12)) for s in (_mark_series(conn, by_pick[pk][ROLE_SUFFIX["nq"]]["id"], bounds, install_ms) for pk in new)]
                de = [math.log(max(s[w], 1e-12) / max(s[w - 1], 1e-12)) for s in (_mark_series(conn, by_pick[pk][ROLE_SUFFIX["eq"]]["id"], bounds, install_ms) for pk in new)]
                diffs.append(float(np.mean(dn)) - float(np.mean(de)))
            day = time.strftime("%Y-%m-%d", time.gmtime(t / 1000))
            p = sign_flip_p(diffs, seed_of("exitflex", "league", pool, day))
            conds = {"beats_e0_and_sign_flip": g["nq"] > g["eq"] and p < P_LIMIT[which], "beats_flip": g["nq"] > g["nflip"],
                     "trades_150": counts["nq"]["closed"] >= MIN_TRADES_C2, "positive": g["nq"] > 0}
            info.update(p=p, n_weeks=len(diffs), weekly_diffs=diffs, p_limit=P_LIMIT[which], conds=conds,
                        shown_ahead=all(conds.values()), label="shown ahead" if all(conds.values()) else "not shown ahead")
        report["pools"][pool] = info
    return report


def public_view(report: dict) -> dict:
    """What may be printed or committed (D11): the core pool in full; the DeepSeek pool as labels, counts, win shares and hold hours only."""
    out = json.loads(json.dumps(report))
    for pool, info in out["pools"].items():
        if pool == "ds":
            out["pools"][pool] = {k: v for k, v in info.items() if k in DS_PUBLIC_KEYS}
            if "conds" in out["pools"][pool]:
                out["pools"][pool]["conds"] = dict(info["conds"])          # pass / fail labels
    return out


def format_check(report: dict) -> str:
    """The Korean text of a check (public part only): hold hours and entries first, then the labels, for core the figures."""
    pv = public_view(report)
    t = time.strftime("%Y-%m-%d", time.gmtime(pv["time_ms"] / 1000))
    L_ = [f"[{pv['which'].upper()}] {t} 00:00 UTC (설치 후 {pv['days']:.0f}일)"]
    for pool, name in (("core", "코어"), ("ds", "딥시크")):
        i = pv["pools"].get(pool)
        if i is None:
            continue
        L_.append(f"- {name}: 새 청산 {i['new_exit']} → {i['label']}")
        for role in ("nq", "eq", "nflip"):
            h, c = (i.get("hold") or {}).get(role), (i.get("counts") or {}).get(role)
            if h and c:
                L_.append(f"    {role}: 보유 중앙값 {h['median']}시간 (>4h {h['share_gt4']}, >8h {h['share_gt8']}, >18h {h['share_gt18']}), "
                          f"진입 {c['entered']}, 놓침 {c['skipped']}, 거절 {c['rejected']}, 청산 {c['closed']}, 승률 {(i['win_share'] or {}).get(role)}")
        if pool == "core" and "g" in i:
            L_.append("    월 로그성장 G: " + ", ".join(f"{r} {v:+.5f}" for r, v in i["g"].items()) + (f"; p = {i['p']:.4f} (주 {i['n_weeks']}개)" if "p" in i else ""))
        if i.get("conds"):
            L_.append("    조건: " + ", ".join(f"{k} {'예' if v else '아니오'}" for k, v in i["conds"].items()))
    return "\n".join(L_)


def checks_main(argv: list) -> int:
    import argparse
    import sqlite3
    import sys
    ap = argparse.ArgumentParser(description="후보 리그 앞으로의 점검 C1 / C2 (PREREG_EXITFLEX 11.5)")
    ap.add_argument("which", choices=tuple(CHECK_DAYS))
    ap.add_argument("--db", required=True, help="the league database (tables trades, acct_day, acct_mark)")
    ap.add_argument("--install", required=True, help="the install time (with its time zone, or epoch ms): the restart's start")
    ap.add_argument("--rules", default=None)
    ap.add_argument("--candidates", default=C.DEFAULT_FILE)
    ap.add_argument("--private", default=None, help="a folder outside the repository for the full report (DeepSeek money included)")
    ap.add_argument("--skip", default="", help="pools already shown ahead (the repeat), comma separated")
    a = ap.parse_args(argv)
    from . import runner as RN
    install = RN.parse_start(a.install)
    cfg = load_config(a.rules)
    if cfg is None or not cfg["enabled"]:
        print("no enabled rule config: nothing to check", file=sys.stderr)
        return 2
    accts = accounts(C.load(a.candidates), cfg)
    stopped = [p for p in POOLS if cfg["no_entry_from_ms"].get(p)]
    conn = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    try:
        rep = forward_check(conn, accts, install, a.which, stopped, [x for x in a.skip.split(",") if x])
    finally:
        conn.close()
    if a.private:
        os.makedirs(a.private, exist_ok=True)
        with open(os.path.join(a.private, f"check_{a.which}.json"), "w") as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=1)
    print(format_check(rep))
    if a.which == "c1":
        print(json.dumps({"no_entry_from_ms": {p: i.get("no_entry_from_ms") for p, i in rep["pools"].items() if i.get("no_entry_from_ms")}}))
    return 0


# ====================================================================== command line
def main(argv: Optional[list] = None) -> int:
    import argparse
    import sys
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "checks":                           # python -m candleague.rulex checks c1|c2|repeat --db ... --install ...
        return checks_main(argv[1:])
    ap = argparse.ArgumentParser(description="후보 리그 규칙 계좌")
    ap.add_argument("cmd", choices=("check", "accounts", "ids"))
    ap.add_argument("--rules", default=None, help=f"rule config (default {DEFAULT_FILE}, env {RULES_ENV})")
    ap.add_argument("--candidates", default=C.DEFAULT_FILE)
    ap.add_argument("--all", action="store_true", help="ids: the 88 study ids (F11, F12 and F13 included)")
    a = ap.parse_args(argv)
    if a.cmd == "ids":
        print("\n".join(study_ids() + (native_ids() + lock_ids() if a.all else [])))
        return 0
    try:
        cfg = load_config(a.rules)
        accts = load_accounts(a.rules, C.load(a.candidates))
    except RuleConfigError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    if accts is None:
        print("no rule config file: the league creates no rule account" if cfg is None else
              "the rule config is not enabled (\"enabled\": true is the owners' OK): the league creates no rule account")
        return 0
    if a.cmd == "accounts":
        print("\n".join(x["id"] for x in accts))
    else:
        print(f"ok: {len(accts)} rule accounts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
