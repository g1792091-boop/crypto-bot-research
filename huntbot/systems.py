"""Which systems huntbot records, how they group into entry cells, the account variants and the lineup file.

* Systems: every system of ``research.hunt.entries_wide.systems()`` (the wide study's list: 730 when this was
  written, 762 with the F5 famous rules; whatever the pinned file holds) plus the v1 systems of
  ``research.hunt.hunt.v1_systems()``. A v1 system that is the same entry, timeframe, numbers and gate as a wide one
  (all six are: v1 = F1 at the main numbers with gate G1) is recorded once, under the wide id, and its v1 id
  (``v1:E1:1h``) is an alias the lineup may use.
* Cells: one entry on one timeframe with its numbers (research/hunt/hunt.py ``cell_key``); the two gate systems of a
  cell share its events. Cell id = the system id without the gate (``F2:X:15m``, ``F4:X:15m:r3``).
* Variants (one $5,000 wallet each): ``r0.5`` (r = 0.5%, the tested machine of PREREG_HUNT 7-10, the prereg's main
  account) and ``r1`` (r = 1%, PREREG_HUNT 15 / WIDE 12 "both sizes"); and two goal-size cells of the R1 goal board
  (PREREG_HUNT_WIDE W 7.3), with the machine taken from ``research/hunt/reads_a.cell_overrides`` so they stay the
  board's machines: ``A2`` (machine A at r = 2%: the tested machine, open-risk cap 4% x r / 0.5%, margin budget
  B = equity / 6 as written) and ``B5`` (machine B, the goal-mode machine of the headline cell, at r = 5%: open-risk cap
  min(4r, 60%), n_max = floor(cap / r) positions and margin divisor, leverage up to the bracket maximum). The goal-size
  cells are paper "not tested" (W 7.1 rule 6, Q9): a lineup account may use one only with an ``owners_decision`` text
  (who decided and when), and ``suggest_lineup`` never proposes one. They replace the retired ``goal2`` / ``goal5`` of
  the first draft's W 7 sizing read (B scaled with r), which no longer exists in W 7.
* Lineup (``huntbot/lineup.json``, empty at install): the owners' accounts once the picks are known. Every system is
  recorded at r0.5 either way; the lineup only decides what the dashboard shows first and what Telegram sends.

    {"version": 1, "note": "...",
     "accounts": [
       {"system": "F2:X:1h:G1", "label": "정식", "variant": "r0.5", "pick_no": 1, "study": "wide"},
       {"system": "v1:E1:1h", "label": "참고", "variant": "r0.5", "study": "v1"},
       {"basket": ["F2:X:1h:G1", "F1:E2:4h:NONE"], "pick_nos": [1, 3], "label": "정식", "variant": "r0.5",
        "name": "바구니"},
       {"system": "F2:X:1h:G1", "label": "정식", "variant": "B5", "owners_decision": "두 분, 2026-11-.."}]}
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Optional

from . import config as CFG

LABELS = ("정식", "참고")
DS_KINDS = ("ds",)
FAMILY_KO = {"F1": "사냥 진입 E1-E3", "F2": "기존 36 매매법", "F3": "딥시크 44", "F4": "관찰 후보 38",
             "F5": "유명 추세 규칙"}
HUNT_KO = {"E1": "E1 돌파 55봉 + 거래량", "E2": "E2 볼린저 수축 뒤 돌파", "E3": "E3 변동성 확대"}
TF_KO = {"15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}
GATE_KO = {"G1": "추세장만", "NONE": "장세 무관"}


def _H():
    from research.hunt import hunt as H
    return H


# Goal-size paper cells (W 7.3 R1 board): (variant, machine, r). A2 = machine A at 2%; B5 = machine B (goal-mode) at
# 5%, the headline cell's machine and size. W 7.1 rule 6: only by the owners' explicit decision, "not tested".
GOAL_CELLS = (("A2", "A", 0.02), ("B5", "B", 0.05))
GOAL_KO = {"A": "목표 크기 모의 · 기계 A {r}% (시험 안 함)", "B": "목표 크기 모의 · 기계 B 목표 모드 {r}% (시험 안 함)"}
RETIRED_VARIANTS = {"goal2": "A2", "goal5": "B5"}       # the first draft's W 7 sizing read (B scaled with r): gone


def variants() -> dict:
    """{name: {"r", "risk_cap", "b_div", "overrides" (engine PR_* overrides), "machine", "ko", "read"}}; ``read``
    marks a goal-size cell (not the tested machine at a tested size)."""
    H = _H()
    out = {"r0.5": {"r": H.R_BASE, "risk_cap": H.RISK_CAP, "b_div": H.B_DIV, "overrides": {}, "machine": "tested",
                    "ko": "위험 0.5%", "read": False},
           "r1": {"r": H.R_ONE, "risk_cap": H.RISK_CAP, "b_div": H.B_DIV, "overrides": {}, "machine": "tested",
                  "ko": "위험 1%", "read": False}}
    from research.hunt import reads_a as RA                 # the R1 board's own machines (W 7.3), not a copy
    for name, machine, r in GOAL_CELLS:
        r_, ov = RA.cell_overrides(machine, r)
        out[name] = {"r": float(r_), "risk_cap": float(ov.get("PR_CAP", H.RISK_CAP)),
                     "b_div": float(ov.get("PR_BDIV", H.B_DIV)), "overrides": dict(ov), "machine": machine,
                     "ko": GOAL_KO[machine].format(r=f"{r * 100:g}"), "read": True}
    return out


def is_ds(spec: dict) -> bool:
    return spec.get("kind") in DS_KINDS


GATE_IDS = ("G1", "NONE", "TS")


def cell_id(spec: dict) -> str:
    """The system id without its gate part (``F<n>:<name>:<tf>:<gate>[:r<rank>]`` -> ``F<n>:<name>:<tf>[:r<rank>]``)."""
    parts = spec["id"].split(":")
    if len(parts) >= 4 and parts[3] in GATE_IDS:
        return ":".join(parts[:3] + parts[4:])
    return f"{spec.get('family')}:{spec['name']}:{spec['tf']}"


def system_list() -> tuple:
    """(systems in the wide order, then any v1 system that is not already there; {v1 id: wide id})."""
    H = _H()
    out = [dict(s) for s in H.wide_systems()]
    by_key = {(H.cell_key(s), s["gate"]): s["id"] for s in out}
    aliases = {}
    for s in H.v1_systems():
        k = (H.cell_key(s), s["gate"])
        if k in by_key:
            aliases[s["id"]] = by_key[k]
        else:
            out.append(dict(s))
            by_key[k] = s["id"]
    ids = [s["id"] for s in out]
    if len(set(ids)) != len(ids):
        raise RuntimeError("system ids are not unique")
    return out, aliases


class Cell:
    __slots__ = ("id", "key", "spec", "tf", "kind", "family", "name", "rank", "systems")

    def __init__(self, cid: str, key: tuple, spec: dict):
        self.id, self.key = cid, key
        self.spec = {k: spec[k] for k in ("family", "name", "kind", "tf", "combo") if k in spec}
        self.spec.update({"id": cid, "gate": "NONE", "strategy": spec.get("strategy", spec["name"])})
        self.tf, self.kind, self.family, self.name = spec["tf"], spec["kind"], spec.get("family"), spec["name"]
        self.rank = spec.get("rank")
        self.systems: list = []

    def sys_of(self, gate: str) -> Optional[str]:
        for s in self.systems:
            if s["gate"] == gate:
                return s["id"]
        return None


def cells_of(systems: list) -> dict:
    """{cell id: Cell} in the systems' order (cells keyed by research/hunt/hunt.py cell_key)."""
    H = _H()
    by_key: dict = {}
    out: dict = {}
    for s in systems:
        k = H.cell_key(s)
        c = by_key.get(k)
        if c is None:
            c = Cell(cell_id(s), k, s)
            if c.id in out:
                raise RuntimeError(f"cell id {c.id} names two different cells")
            by_key[k] = c
            out[c.id] = c
        c.systems.append(s)
    return out


def label_ko(spec: dict) -> str:
    name = spec.get("name", "")
    if spec.get("kind") == "hunt":
        name = HUNT_KO.get(name, name)
    s = f"{name} · {TF_KO.get(spec.get('tf'), spec.get('tf'))}"
    if spec.get("gate"):
        s += f" · {GATE_KO.get(spec['gate'], spec['gate'])}"
    if spec.get("rank") is not None:
        s += f" · 후보 {spec['rank']}위"
    return s


# ---------------------------------------------------------------- lineup
class LineupError(ValueError):
    pass


def account_id(a: dict) -> str:
    if a.get("basket"):
        return "basket:" + "+".join(a["basket"]) + "|" + a["variant"]
    return f"{a['system']}|{a['variant']}"


def parse_lineup(doc: dict, systems_by_id: dict, aliases: dict) -> list:
    """Checked lineup accounts: [{"id", "label", "variant", "parts": [(spec, src)], "system" or "basket", ...}]."""
    if not isinstance(doc, dict):
        raise LineupError("lineup.json must be an object")
    accts = doc.get("accounts") or []
    if not isinstance(accts, list):
        raise LineupError("'accounts' must be a list")
    var = variants()
    out, seen = [], set()
    for i, a in enumerate(accts, 1):
        if not isinstance(a, dict):
            raise LineupError(f"account {i}: not an object")
        label = a.get("label")
        if label not in LABELS:
            raise LineupError(f"account {i}: label must be 정식 or 참고 (got {label!r})")
        v = a.get("variant", "r0.5")
        if v in RETIRED_VARIANTS:
            raise LineupError(f"account {i}: variant {v!r} was the retired W 7 sizing read; the R1 board cell is "
                              f"{RETIRED_VARIANTS[v]!r} (PREREG_HUNT_WIDE W 7.3)")
        if v not in var:
            raise LineupError(f"account {i}: variant must be one of {sorted(var)} (got {v!r})")
        decided = a.get("owners_decision")
        if var[v]["read"] and not (isinstance(decided, str) and decided.strip()):
            raise LineupError(f"account {i}: {v} is goal-size paper, not tested: it exists only by the owners' "
                              f"explicit decision (PREREG_HUNT_WIDE W 7.1 rule 6, Q9); write who decided and when "
                              f"in 'owners_decision'")
        if a.get("machine", "hunt") != "hunt":
            raise LineupError(f"account {i}: only the hunt machine (PREREG_HUNT 7-10) exists")
        if a.get("basket"):
            ids = [aliases.get(x, x) for x in a["basket"]]
            nos = a.get("pick_nos") or list(range(1, len(ids) + 1))
            if len(ids) < 2 or len(nos) != len(ids):
                raise LineupError(f"account {i}: a basket needs 2+ systems and one pick number each")
            for x in ids:
                if x not in systems_by_id:
                    raise LineupError(f"account {i}: unknown system {x}")
            acct = {"basket": ids, "pick_nos": [int(n) for n in nos], "name": a.get("name") or "바구니",
                    "parts": [(systems_by_id[x], int(n)) for x, n in zip(ids, nos)]}
        else:
            sid = aliases.get(a.get("system"), a.get("system"))
            if sid not in systems_by_id:
                raise LineupError(f"account {i}: unknown system {a.get('system')!r}")
            acct = {"system": sid, "alias": a.get("system") if a.get("system") != sid else None,
                    "parts": [(systems_by_id[sid], 0)]}
        acct.update({"label": label, "variant": v, "pick_no": a.get("pick_no"), "study": a.get("study"),
                     "note": a.get("note"), "owners_decision": decided if var[v]["read"] else None})
        acct["id"] = account_id(acct)
        if acct["id"] in seen:
            raise LineupError(f"account {i}: {acct['id']} twice")
        seen.add(acct["id"])
        acct["ds"] = any(is_ds(s) for s, _ in acct["parts"])
        acct["cells"] = sorted({cell_id(s) for s, _ in acct["parts"]})
        out.append(acct)
    return out


def read_lineup(path: str, systems_by_id: dict, aliases: dict) -> dict:
    """{"accounts": [...], "error": None or text, "sha256": ..., "path": ...}; a bad file gives no accounts."""
    res = {"accounts": [], "error": None, "path": path, "sha256": CFG.sha256_file(path)}
    if not os.path.exists(path):
        return res
    try:
        with open(path) as fh:
            doc = json.load(fh)
        res["accounts"] = parse_lineup(doc, systems_by_id, aliases)
        res["note"] = doc.get("note")
    except (OSError, ValueError, LineupError) as e:
        res["error"] = f"{type(e).__name__}: {e}"
    return res


LINEUP_VARIANTS = {"정식": ("r0.5", "r1"), "참고": ("r0.5",)}   # W 12 / H 15: 정식 at both sizes; 참고 one r = 0.5%
LINEUP_TIERS = ("정식", "참고", "excluded")


def _study_lineup(study: str, test: dict) -> tuple:
    """(proposed accounts, excluded rows, status) of one study from its test.json's own ``lineup`` field (written by
    the test step, research/hunt/hunt.py ``lineup_table``: W 12 / H 15). Raises LineupError when the field is missing
    or does not agree with the verdict: nothing is guessed."""
    lu = test.get("lineup")
    if not isinstance(lu, dict) or not isinstance(lu.get("picks"), dict):
        raise LineupError("test.json has no 'lineup' field (W 12): nothing proposed")
    picks = lu["picks"]
    for sid, d in picks.items():
        if not isinstance(d, dict) or d.get("lineup") not in LINEUP_TIERS:
            raise LineupError(f"lineup of {sid}: {(d or {}).get('lineup')!r} is not 정식 / 참고 / excluded")
    for tier in LINEUP_TIERS:                                 # the lists, when present, must say what 'picks' says
        if tier in lu and sorted(lu[tier]) != sorted(i for i, d in picks.items() if d["lineup"] == tier):
            raise LineupError(f"lineup '{tier}' list disagrees with lineup 'picks'")
    formal = {i for i, d in picks.items() if d["lineup"] == "정식"}
    verdict = test.get("verdict") or {}
    passing = set(verdict.get("passing") or []) if study == "wide" else \
        ({(test.get("pick") or {}).get("id")} if verdict.get("v1_pass") else set())
    if formal != passing:                                     # 정식 = research PASS (W 12), nothing else
        raise LineupError(f"lineup 정식 {sorted(formal)} is not the verdict's PASS {sorted(passing)}")
    accts, excluded = [], []
    for sid in sorted(picks, key=lambda i: (int(picks[i].get("pick_no") or 0), i)):
        d = picks[sid]
        if d["lineup"] == "excluded":
            excluded.append({"system": sid, "study": study, "pick_no": d.get("pick_no"), "batch": d.get("batch"),
                             "why": list(d.get("why") or [])})
            continue
        for v in LINEUP_VARIANTS[d["lineup"]]:
            accts.append({"system": sid, "label": d["lineup"], "variant": v, "study": study,
                          "pick_no": d.get("pick_no"), "batch": d.get("batch")})
    if study == "wide" and len(formal) >= 2:                  # W 12: the one-wallet basket of the passing picks
        members = sorted(formal, key=lambda i: (int(picks[i].get("pick_no") or 0), i))
        for v in ("r0.5", "r1"):
            accts.append({"basket": members, "pick_nos": [int(picks[i].get("pick_no") or 0) for i in members],
                          "label": "정식", "variant": v, "name": "바구니 (통과한 픽 한 지갑)", "study": "wide"})
    status = {t: sum(1 for d in picks.values() if d["lineup"] == t) for t in LINEUP_TIERS}
    return accts, excluded, status


def suggest_lineup(root: str = CFG.ROOT) -> dict:
    """A lineup proposal read from each study's test.json ``lineup`` field (research/hunt/out/<study>/test.json; the
    test step labels every tested pick 정식 / 참고 / excluded per PREREG_HUNT_WIDE W 12, also the v1 pick, H 15):
    정식 -> r0.5 and r1 (H 15 / W 12 "both sizes"); 참고 -> r0.5 only; excluded -> no account (listed under
    "excluded" with its failing conditions); two or more 정식 wide picks -> the one-wallet basket (정식, r0.5 and r1).
    A study without test.json, or whose test.json has no ``lineup`` field or one that disagrees with its verdict, gets
    no account (its status says why). Goal-size cells (A2, B5) are never proposed (W 7.1 rule 6: the owners' explicit
    decision only). Only a proposal: the owners / main session decide and write the file."""
    out = {"version": 1, "note": "proposal from research/hunt/out/<study>/test.json 'lineup' "
                                 "(huntbot.systems.suggest_lineup); real money only from 정식 (W 12)",
           "accounts": [], "excluded": [], "studies": {}}
    for study in ("v1", "wide"):
        p = os.path.join(root, "research", "hunt", "out", study, "test.json")
        if not os.path.exists(p):
            out["studies"][study] = "no test.json: nothing proposed"
            continue
        try:
            with open(p) as fh:
                test = json.load(fh)
            accts, excl, status = _study_lineup(study, test)
        except (OSError, ValueError, LineupError) as e:
            out["studies"][study] = f"{type(e).__name__}: {e}"
            continue
        out["accounts"] += accts
        out["excluded"] += excl
        out["studies"][study] = status
    return out


def lineup_hash(accts: list) -> str:
    body = json.dumps([[a["id"], a["label"]] for a in accts], ensure_ascii=False)
    return hashlib.sha256(body.encode()).hexdigest()[:16]
