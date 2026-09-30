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

# Files whose change can alter a fill, an exit or a position size.
TRADING_FILES = ("paperbot/engine.py", "paperbot/ladder.py", "paperbot/margin.py", "paperbot/sizing.py",
                 "paperbot/config.py", "paperbot/models.py", "paperbot/accounts.py",
                 "paperbot/sigservice.py", "paperbot/aggregate.py", "paperbot/feed.py", "paperbot/live3.py")
RULES_FILES = ("docs/paper-v3-rules.md", "docs/paper-v3-rules-addendum.md")

# (key, what the owners see when it changes, does it touch fills/exits/sizing)
WATCHED = (("commit", "코드 버전", False), ("trading_code", "체결·청산·사이즈 코드", True),
           ("settings", "설정", True), ("brackets", "레버리지 구간", True),
           ("signal_code", "잠긴 신호 코드", True), ("packages", "설치된 패키지", False),
           ("rules", "규칙 문서", False))


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
        "python": platform.python_version(),
        "argv": list(argv),
    }


def changes(prev: Optional[dict], cur: dict) -> list[dict]:
    """What differs from the previous start (empty on the first run)."""
    if prev is None:
        return []
    return [{"key": k, "name": name, "trading": trading, "before": prev.get(k), "after": cur.get(k)}
            for k, name, trading in WATCHED if prev.get(k) != cur.get(k)]


def change_text(ch: list[dict]) -> Optional[str]:
    if not ch:
        return None
    names = ", ".join(c["name"] for c in ch)
    if any(c["trading"] for c in ch):
        return (f"재시작 때 바뀐 것: {names}. 체결·청산·사이즈에 영향이 있을 수 있어 규칙(Q5)상 "
                "해당 30일 기간을 오늘부터 다시 셉니다. 규칙 관리자 확인 필요")
    return f"재시작 때 바뀐 것: {names} (체결·청산·사이즈에는 영향 없음)"
