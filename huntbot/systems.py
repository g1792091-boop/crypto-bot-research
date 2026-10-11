"""Which systems huntbot records, how they group into entry cells, the account variants and the lineup file.

* Systems: every system of ``research.hunt.entries_wide.systems()`` (the wide study's 730) plus the v1 systems of
  ``research.hunt.hunt.v1_systems()``. A v1 system that is the same entry, timeframe, numbers and gate as a wide one
  (all six are: v1 = F1 at the main numbers with gate G1) is recorded once, under the wide id, and its v1 id
  (``v1:E1:1h``) is an alias the lineup may use.
* Cells: one entry on one timeframe with its numbers (research/hunt/hunt.py ``cell_key``); the two gate systems of a
  cell share its events. Cell id = the system id without the gate (``F2:X:15m``, ``F4:X:15m:r3``).
* Variants (one $5,000 wallet each, the machine of PREREG_HUNT 7-10): ``r0.5`` (r = 0.5%, the prereg's main account),
  ``r1`` (r = 1%, PREREG_HUNT 15 / WIDE 12 "both sizes"), ``goal2`` / ``goal5`` (the W 7 sizing read: r = 2% / 5%, total
  open-risk cap and margin budget scaled by r / 0.5%; a labelled read, never a pass).
* Lineup (``huntbot/lineup.json``, empty at install): the owners' accounts once the picks are known. Every system is
  recorded at r0.5 either way; the lineup only decides what the dashboard shows first and what Telegram sends.

    {"version": 1, "note": "...",
     "accounts": [
       {"system": "F2:X:1h:G1", "label": "정식", "variant": "r0.5", "pick_no": 1, "study": "wide"},
       {"system": "v1:E1:1h", "label": "참고", "variant": "r0.5", "study": "v1"},
       {"basket": ["F2:X:1h:G1", "F1:E2:4h:NONE"], "pick_nos": [1, 3], "label": "정식", "variant": "r0.5",
        "name": "바구니"}]}
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Optional

from . import config as CFG

LABELS = ("정식", "참고")
DS_KINDS = ("ds",)
FAMILY_KO = {"F1": "사냥 진입 E1-E3", "F2": "기존 36 매매법", "F3": "딥시크 44", "F4": "관찰 후보 38"}
HUNT_KO = {"E1": "E1 돌파 55봉 + 거래량", "E2": "E2 볼린저 수축 뒤 돌파", "E3": "E3 변동성 확대"}
TF_KO = {"15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간"}
GATE_KO = {"G1": "추세장만", "NONE": "장세 무관"}


def _H():
    from research.hunt import hunt as H
    return H


def variants() -> dict:
    H = _H()
    out = {"r0.5": {"r": H.R_BASE, "risk_cap": H.RISK_CAP, "b_div": H.B_DIV, "ko": "위험 0.5%", "read": False},
           "r1": {"r": H.R_ONE, "risk_cap": H.RISK_CAP, "b_div": H.B_DIV, "ko": "위험 1%", "read": False}}
    for r in H.SIZING_RS:
        scale = r / H.R_BASE
        out[f"goal{r * 100:g}"] = {"r": r, "risk_cap": H.RISK_CAP * scale, "b_div": H.B_DIV / scale,
                                   "ko": f"목표 모드 {r * 100:g}% (참고 읽기)", "read": True}
    return out


def is_ds(spec: dict) -> bool:
    return spec.get("kind") in DS_KINDS


def cell_id(spec: dict) -> str:
    parts = spec["id"].split(":")
    if parts[0] in ("F1", "F2", "F3", "F4") and len(parts) >= 4:
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
        if v not in var:
            raise LineupError(f"account {i}: variant must be one of {sorted(var)} (got {v!r})")
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
                     "note": a.get("note")})
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


def suggest_lineup(root: str = CFG.ROOT) -> dict:
    """A lineup proposal from the studies' outputs (research/hunt/out/...): a passing pick -> 정식 at r0.5 and r1
    (PREREG_HUNT 15, WIDE 12), plus its W 7 goal reads (r 2% / 5%) labelled 참고; a pick that did not pass -> 참고 at
    r0.5 (H 15: "may still run as a paper shadow"); two or more passing wide picks -> the one-wallet basket (정식,
    r0.5 and r1). Only a proposal: the owners / main session decide and write the file."""
    out = {"version": 1, "note": "proposal from research/hunt/out (huntbot.systems.suggest_lineup)", "accounts": []}

    def load(rel):
        p = os.path.join(root, rel)
        if os.path.exists(p):
            with open(p) as fh:
                return json.load(fh)
        return None
    v1p, v1t = load("research/hunt/out/v1/pick.json"), load("research/hunt/out/v1/test.json")
    if v1p:
        sid = v1p["pick"]["id"]
        ok = bool(v1t and (v1t.get("verdict") or {}).get("v1_pass"))
        for v in (("r0.5", "r1") if ok else ("r0.5",)):
            out["accounts"].append({"system": sid, "label": "정식" if ok else "참고", "variant": v, "study": "v1",
                                    "pick_no": 1})
    wp, wt = load("research/hunt/out/wide/picks.json"), load("research/hunt/out/wide/test.json")
    passing = set(((wt or {}).get("verdict") or {}).get("passing") or [])
    passed = []
    for p in (wp or {}).get("picks", []):
        ok = p["id"] in passing
        if ok:
            passed.append(p)
        for v in (("r0.5", "r1", "goal2", "goal5") if ok else ("r0.5",)):
            out["accounts"].append({"system": p["id"], "label": "정식" if ok and not v.startswith("goal") else "참고",
                                    "variant": v, "study": "wide", "pick_no": p.get("pick_no")})
    if len(passed) >= 2:
        for v in ("r0.5", "r1"):
            out["accounts"].append({"basket": [p["id"] for p in passed], "pick_nos": [p["pick_no"] for p in passed],
                                    "label": "정식", "variant": v, "name": "바구니 (통과한 픽 한 지갑)", "study": "wide"})
    return out


def lineup_hash(accts: list) -> str:
    body = json.dumps([[a["id"], a["label"]] for a in accts], ensure_ascii=False)
    return hashlib.sha256(body.encode()).hexdigest()[:16]
