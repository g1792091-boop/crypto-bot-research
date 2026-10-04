"""What exactly ran: one append-only ``runs`` row per start of the live runner.

Each row holds the code commit, a hash of the files that decide fills, exits and
sizing, the installed package set, the settings, the leverage brackets, the locked
signal code and the rules text. When any of these differs from the previous start,
the runner writes a WARN so the rule keeper can apply the mid-run fix policy
(docs/paper-v3-rules-addendum.md, Q5): a change to fills, exits or sizing restarts
the affected 30-day window from that date.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from dataclasses import asdict
from importlib import metadata
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The entry-strength definitions that decide each strategy signal's leverage group (quality_v1: entry_marks loads
# research/entry_study/strength_defs/<NAME>.py only when its bytes match DEFS_BC.sha256). Both the lock file and
# every definition are watched, so an edit to a definition changes the trading-code hash even when the lock file is
# left alone (the definition would then fail its check and the strategy would trade "normal").
_DEFS_DIR = os.path.join(ROOT, "research", "entry_study", "strength_defs")
STRENGTH_DEF_FILES = tuple(sorted("research/entry_study/strength_defs/" + f
                                  for f in (os.listdir(_DEFS_DIR) if os.path.isdir(_DEFS_DIR) else ())
                                  if f.endswith(".py")))
# Files whose change can alter a fill, an exit or a position size.
TRADING_FILES = ("paperbot/engine.py", "paperbot/ladder.py", "paperbot/margin.py", "paperbot/sizing.py",
                 "paperbot/config.py", "paperbot/models.py", "paperbot/accounts.py",
                 "paperbot/sigservice.py", "paperbot/aggregate.py", "paperbot/feed.py", "paperbot/live3.py",
                 "paperbot/recorder.py", "paperbot/policy.py", "paperbot/levrule.py", "paperbot/quality_edges.json",
                 "paperbot/entry_marks.py",
                 "paperbot/binance.py",                       # bars_from_klines builds the feed's bars
                 "paperbot/p_best_cells.json",                # coin-flip fairness per cell (checkpoint bots)
                 "research/entry_study/DEFS_BC.sha256") + STRENGTH_DEF_FILES
RULES_FILES = ("docs/paper-v3-rules.md", "docs/paper-v3-rules-addendum.md", "docs/paper-v3-rules-change-1.md",
               "docs/levrule-eval.md")     # how rule B is judged at day 30 (pre-registered 2026-10-04)
# Files that decide only the extra accounts (paperbot/extras.py): their trading code and signals, and the
# code that judges an approval at creation (not trading). A change is a Q5 event for the extras only.
EXTRA_FILES = ("paperbot/extras.py", "paperbot/newlab_live.py", "paperbot/agents/newlab_signals.py")
# Signal input code the original accounts use too (recorder.build_frames makes their signal frames, context the chart context
# of their cards) and the extras (new-strategy frames, copies' skip tags). recorder.py is also in TRADING_FILES
# (Q-11, decided 2026-10-01 before the first start: it builds the originals' signal frames, like sigservice.py); a
# change here is reported without saying the original accounts are unaffected.
SHARED_SIGNAL_FILES = ("paperbot/recorder.py", "paperbot/context.py")
EXTRA_GATE_FILES = ("paperbot/agents/newlab.py", "paperbot/agents/labtests.py", "paperbot/agents/actions.py",
                    "paperbot/agents/rooms_db.py")

# (key, what the owners see when it changes, does it touch fills/exits/sizing)
WATCHED = (("commit", "코드 버전", False), ("trading_code", "체결·청산·사이즈 코드", True),
           ("settings", "설정", True), ("brackets", "레버리지 구간", True),
           ("signal_code", "잠긴 신호 코드", True), ("packages", "설치된 패키지", False),
           ("rules", "규칙 문서", False))
# Kept apart from WATCHED (which applies to every account): (key, name, touches the extras' trading)
EXTRA_WATCHED = (("extra_code", "추가 계좌 코드", True), ("extra_gate_code", "추가 계좌 승인 확인 코드", False))
# Neither WATCHED nor extras-only: (key, name, trading)
SHARED_WATCHED = (("shared_signal_code", "신호 입력 코드(recorder·context: 원래 계좌와 추가 계좌가 함께 씀)", True),)
EXTRAS_ONLY_KO = "추가 계좌만 해당"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def files_hash(paths, root: str = ROOT) -> str:
    h = hashlib.sha256()
    for rel in paths:
        p = os.path.join(root, rel)
        h.update(rel.encode() + b"\0")
        h.update(open(p, "rb").read() if os.path.exists(p) else b"<missing>")
    return h.hexdigest()


def code_version(root: str = ROOT) -> dict:
    """VERSION.json written by deploy/install.sh, else git in a checkout."""
    vf = os.path.join(root, "VERSION.json")
    if os.path.exists(vf):
        with open(vf) as fh:
            return json.load(fh)
    try:
        run = lambda *a: subprocess.run(["git", "-C", root, *a], capture_output=True, text=True,  # noqa: E731
                                        timeout=10).stdout.strip()
        commit = run("rev-parse", "HEAD") or None
        dirty = bool(run("status", "--porcelain", "--untracked-files=no"))
        return {"commit": commit, "dirty": dirty, "tag": run("describe", "--tags", "--exact-match") or None,
                "source": "git"}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None, "tag": None, "source": "unknown"}


def packages_hash() -> str:
    pkgs = sorted({f"{d.metadata['Name'].lower()}=={d.version}" for d in metadata.distributions()
                   if d.metadata["Name"]})
    return _sha("\n".join(pkgs).encode())


def brackets_hash(brackets: dict) -> str:
    rows = {s: [asdict(t) for t in b.tiers] for s, b in sorted(brackets.items())}
    return _sha(json.dumps(rows, sort_keys=True).encode())


def run_record(settings, brackets: dict, brackets_src: str, argv, signal_lock: Optional[dict] = None,
               root: str = ROOT) -> dict:
    ver = code_version(root)
    return {
        "commit": ver.get("commit"), "dirty": ver.get("dirty"), "tag": ver.get("tag"),
        "trading_code": files_hash(TRADING_FILES, root),
        "settings": _sha(json.dumps(asdict(settings), sort_keys=True, default=str).encode()),
        "settings_version": settings.version,
        "brackets": brackets_hash(brackets), "brackets_src": brackets_src,
        "signal_code": None if signal_lock is None else signal_lock.get("prereg_sha256_file"),
        "packages": packages_hash(),
        "rules": files_hash(RULES_FILES, root),
        "extra_code": files_hash(EXTRA_FILES, root),
        "shared_signal_code": files_hash(SHARED_SIGNAL_FILES, root),
        "extra_gate_code": files_hash(EXTRA_GATE_FILES, root),
        "python": platform.python_version(),
        "argv": list(argv),
    }


def changes(prev: Optional[dict], cur: dict) -> list[dict]:
    """What differs from the previous start (empty on the first run). Entries of EXTRA_WATCHED carry
    ``extras_only``, entries of SHARED_WATCHED ``shared``. A key the previous record does not have yet (a record
    written before the key existed) is not a change."""
    if prev is None:
        return []
    out = [{"key": k, "name": name, "trading": trading, "before": prev.get(k), "after": cur.get(k)}
           for k, name, trading in WATCHED if prev.get(k) != cur.get(k)]
    out += [{"key": k, "name": name, "trading": trading, "before": prev.get(k), "after": cur.get(k),
             "extras_only": True}
            for k, name, trading in EXTRA_WATCHED if prev.get(k) != cur.get(k)]
    out += [{"key": k, "name": name, "trading": trading, "before": prev.get(k), "after": cur.get(k), "shared": True}
            for k, name, trading in SHARED_WATCHED if k in prev and prev.get(k) != cur.get(k)]
    return out


def change_text(ch: list[dict]) -> Optional[str]:
    """The restart's WARN / INFO (owners' Telegram layout 2026-10-04: a title, then short lines)."""
    if not ch:
        return None
    names = ", ".join(c["name"] + (f"({EXTRAS_ONLY_KO})" if c.get("extras_only") else "") for c in ch)
    if any(c["trading"] and not c.get("extras_only") and not c.get("shared") for c in ch):
        return (f"재시작 변경 · 거래 규칙 영향 있음\n\n바뀐 것: {names}\n"
                "규칙(Q5)상 그 30일 기간을 오늘부터 다시 셈\n→ 규칙 관리자 확인 필요")
    if any(c["trading"] and c.get("shared") for c in ch):
        return (f"재시작 변경 · 원래·추가 계좌 모두 확인 필요\n\n바뀐 것: {names}\n"
                "원래 계좌의 신호 계산(recorder.py)·차트 설명(context.py)에도 쓰는 코드\n"
                "→ 규칙 관리자가 Q5(30일을 다시 셀지) 확인 (recorder.py 변경은 따로도 잡힘, Q-11)")
    if any(c["trading"] for c in ch):
        return (f"재시작 변경 · 추가 계좌만 영향\n\n바뀐 것: {names}\n"
                f"추가 계좌의 체결·신호 코드 ({EXTRAS_ONLY_KO}, 원래 계좌의 코드는 그대로)\n"
                "→ 그 계좌들의 30일을 다시 셀지 규칙 관리자 확인")
    return f"ℹ️ 재시작 변경 · {names} (거래에는 영향 없음)"
