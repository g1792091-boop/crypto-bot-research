"""What exactly ran: one append-only ``runs`` row per start of the live runner.

Each row holds the code commit, a hash of the files that decide fills, exits and
sizing, the installed package set, the settings, the leverage brackets, the locked
signal code and the rules text. When any of these differs from the previous start,
the runner writes a WARN so the rule keeper can apply the mid-run fix policy
(docs/paper-v3-rules-addendum.md, Q5): a change to fills, exits or sizing restarts
the affected 30-day window from that date.

Paper v4 (owners' D8): one hash per group. ``TRADING_FILES`` is the shared set (a change restarts every group's
window); ``DS_FILES`` decide only the DeepSeek accounts (kind "ds200") and ``REEL_FILES`` only the reel (kind "reel",
plus the three 5m coin flips, which trade with the reel's entry levels and exits and are never judged). Their keys
are ``GROUP_WATCHED``, kept apart from ``WATCHED`` (which applies to every account), so a DeepSeek-only or reel-only
fix never restarts the core group's window. ``groups_hit`` says which groups a start's changes restart.
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
                 "research/paper_rules/out/summary.json",     # random_rate: the live coin-flip accounts' fire rate (live3)
                 "research/entry_study/DEFS_BC.sha256",
                 "paperbot/sweepsig.py") + STRENGTH_DEF_FILES  # loads the locked library (v4: hashed itself too)
# Paper v4 group sets (D8). The locked vendor code they import (third_party/sweep/harness/vendor: fg_indicators,
# pine_indicators, engine) is the core group's locked code: third_party/sweep/PREREG.sha256 is the "signal_code" key
# and sweepsig.verify() refuses a changed file, so it is not repeated here.
DS_FILES = ("paperbot/dssig.py", "paperbot/ds_pins.json",
            "research/deepseek200/lib_c.py", "research/deepseek200/PREREG_DEEPSEEK200.sha256",
            "research/library/lib.py", "research/search/search.py")        # lib_c.env() loads both
# research/library/lib.py and research/search/search.py are in both group sets: lib_reel5m.env() loads them as
# lib_c.env() does, so a change to them restarts the DeepSeek and the reel windows (never the core group's).
REEL_FILES = ("paperbot/reelsig.py", "paperbot/reel_engine.py",
              "research/reel5m/lib_reel5m.py", "research/reel5m/PREREG_REEL5M.sha256",
              "research/library/lib.py", "research/search/search.py") + tuple(
    rel for rel in ("paperbot/reel_pins.json",)       # the reel wrapper's own pin file, if it keeps one
    if os.path.exists(os.path.join(ROOT, rel)))
GROUP_FILES = {"ds200": DS_FILES, "reel": REEL_FILES}
# Repository modules on the live runner's path that are deliberately in NO hash set, with the reason (they decide
# no fill, exit, size or signal). tests/test_runinfo.py checks that every repository file the runner imports (and
# every import of a hashed module) is hashed, locked by third_party/sweep/PREREG.sha256, in an extras set, or here;
# a new module on the trading path therefore needs a decision before it can ship.
NOT_HASHED = {
    "paperbot/__init__.py": "re-exports only",
    "paperbot/runinfo.py": "this run record",
    "paperbot/notify.py": "Telegram text and routing",
    "paperbot/store3.py": "database rows (an engine's saved state is engine.py's engine_state / restore_engine)",
    "paperbot/health.py": "systemd watchdog and dead-man ping",
    "paperbot/fillcost.py": "order-book cost shadow, records only (the fill is the engine's)",
    "paperbot/strengthwatch.py": "alarm on failed strength scores, never changes a signal or its size",
    "paperbot/live.py": "REST client, notifier and the bracket file loader (the brackets are the 'brackets' key)",
    "paperbot/ledger.py": "v1 ledger and the order-book reader of the record-only signal recorder (recorder.py)",
    "paperbot/archive.py": "market.db recorder; recorder.build_frames takes only its FIVE_MIN constant (300,000 ms)",
    "paperbot/strategy.py": "the v1 strategy Protocol (types only)",
}
RULES_FILES = ("docs/paper-v3-rules.md", "docs/paper-v3-rules-addendum.md", "docs/paper-v3-rules-change-1.md",
               "docs/levrule-eval.md",     # how rule B is judged at day 30 (pre-registered 2026-10-04)
               # paper v4 (2026-10-05): the run's rules, its verdict method, rule B's v4 population (D12)
               "docs/paper-v4-rules.md", "docs/paper-v4-verdict.md", "docs/levrule-eval-v4.md")
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
# Paper v4, one key per group set (D8), kept apart from WATCHED: (key, name, trading). GROUP_OF_KEY: the group
# (accounts.GROUP_OF_KIND) whose window the key restarts.
GROUP_WATCHED = (("ds_code", "딥시크 신호 코드", True), ("reel_code", "5분 단타 신호·청산 코드", True))
GROUP_OF_KEY = {"ds_code": "ds200", "reel_code": "reel"}
GROUP_ONLY_KO = {"ds200": "딥시크만 해당", "reel": "5분 단타만 해당"}
# Every account group (accounts.GROUP_OF_KIND values): a shared trading change restarts all of them.
ALL_GROUPS = ("core", "ds200", "reel", "flip", "extra")


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


def code_hashes(root: str = ROOT) -> dict:
    """The run record's file-set hashes, one key per set."""
    return {"trading_code": files_hash(TRADING_FILES, root),
            "ds_code": files_hash(DS_FILES, root), "reel_code": files_hash(REEL_FILES, root),
            "rules": files_hash(RULES_FILES, root),
            "extra_code": files_hash(EXTRA_FILES, root),
            "shared_signal_code": files_hash(SHARED_SIGNAL_FILES, root),
            "extra_gate_code": files_hash(EXTRA_GATE_FILES, root)}


def run_record(settings, brackets: dict, brackets_src: str, argv, signal_lock: Optional[dict] = None,
               root: str = ROOT, group_locks: Optional[dict] = None) -> dict:
    """``group_locks``: what the runner's pin checks of the v4 groups gave at this start, recorded as is (e.g.
    {"ds200": dssig.verify(), "reel": {"refused": "..."}}); not watched (their code is, as ds_code / reel_code)."""
    ver = code_version(root)
    h = code_hashes(root)
    rec = {
        "commit": ver.get("commit"), "dirty": ver.get("dirty"), "tag": ver.get("tag"),
        "trading_code": h["trading_code"],
        "settings": _sha(json.dumps(asdict(settings), sort_keys=True, default=str).encode()),
        "settings_version": settings.version,
        "brackets": brackets_hash(brackets), "brackets_src": brackets_src,
        "signal_code": None if signal_lock is None else signal_lock.get("prereg_sha256_file"),
        "packages": packages_hash(),
        "rules": h["rules"],
        "extra_code": h["extra_code"],
        "shared_signal_code": h["shared_signal_code"],
        "extra_gate_code": h["extra_gate_code"],
        "ds_code": h["ds_code"], "reel_code": h["reel_code"],
        "python": platform.python_version(),
        "argv": list(argv),
    }
    if group_locks is not None:
        rec["group_locks"] = json.loads(json.dumps(group_locks, sort_keys=True, default=str))
    return rec


def changes(prev: Optional[dict], cur: dict) -> list[dict]:
    """What differs from the previous start (empty on the first run). Entries of EXTRA_WATCHED carry
    ``extras_only``, entries of SHARED_WATCHED ``shared``, entries of GROUP_WATCHED ``group`` (the one group whose
    window they restart). A SHARED_WATCHED key the previous record does not have yet (a record written before the
    key existed) is not a change; a missing WATCHED or GROUP_WATCHED key is (the v4 run starts with all of them)."""
    if prev is None:
        return []
    out = [{"key": k, "name": name, "trading": trading, "before": prev.get(k), "after": cur.get(k)}
           for k, name, trading in WATCHED if prev.get(k) != cur.get(k)]
    out += [{"key": k, "name": name, "trading": trading, "before": prev.get(k), "after": cur.get(k),
             "group": GROUP_OF_KEY[k]}
            for k, name, trading in GROUP_WATCHED if prev.get(k) != cur.get(k)]
    out += [{"key": k, "name": name, "trading": trading, "before": prev.get(k), "after": cur.get(k),
             "extras_only": True}
            for k, name, trading in EXTRA_WATCHED if prev.get(k) != cur.get(k)]
    out += [{"key": k, "name": name, "trading": trading, "before": prev.get(k), "after": cur.get(k), "shared": True}
            for k, name, trading in SHARED_WATCHED if k in prev and prev.get(k) != cur.get(k)]
    return out


def groups_hit(keys) -> tuple:
    """The groups whose 30-day window a start's recorded change keys (a runs row's "changes") restart under Q5 and
    D8, in ALL_GROUPS order: a trading key of WATCHED hits every group, a GROUP_WATCHED key only its own group, an
    EXTRA_WATCHED or SHARED_WATCHED trading key only the extras (recorder.py is also in TRADING_FILES, so the
    originals see it as trading_code, Q-11). Keys that do not touch trading hit nothing. "reel" here also means the
    three 5m coin flips (group "flip", timeframe 5m): they trade with the reel's code, and they are never judged."""
    keys = set(keys or ())
    if keys & {k for k, _, t in WATCHED if t}:
        return ALL_GROUPS
    hit = {GROUP_OF_KEY[k] for k, _, t in GROUP_WATCHED if t and k in keys}
    if keys & {k for k, _, t in EXTRA_WATCHED + SHARED_WATCHED if t}:
        hit.add("extra")
    return tuple(g for g in ALL_GROUPS if g in hit)


def _label(c: dict) -> str:
    if c.get("extras_only"):
        return c["name"] + f"({EXTRAS_ONLY_KO})"
    if c.get("group"):
        return c["name"] + f"({GROUP_ONLY_KO[c['group']]})"
    return c["name"]


def change_text(ch: list[dict]) -> Optional[str]:
    """The restart's WARN / INFO (owners' Telegram layout 2026-10-04: a title, then short lines)."""
    if not ch:
        return None
    names = ", ".join(_label(c) for c in ch)
    if any(c["trading"] and not c.get("extras_only") and not c.get("shared") and not c.get("group") for c in ch):
        return (f"재시작 변경 · 거래 규칙 영향 있음\n\n바뀐 것: {names}\n"
                "모든 그룹이 쓰는 코드·설정: 규칙(Q5)상 모든 그룹의 30일 기간을 오늘부터 다시 셈\n→ 규칙 관리자 확인 필요")
    groups = [g for g in GROUP_ONLY_KO if any(c["trading"] and c.get("group") == g for c in ch)]
    if groups:
        only = "·".join(GROUP_ONLY_KO[g].replace("만 해당", "") for g in groups)
        more = "\n5분 동전 3개도 같은 신호·청산 코드 (비교용, 판정 없음)" if "reel" in groups else ""
        if any(c["trading"] and c.get("shared") for c in ch):
            more += "\n신호 입력 코드(recorder·context)도 바뀜 → 추가 계좌의 Q5도 확인 (Q-11)"
        elif any(c["trading"] and c.get("extras_only") for c in ch):
            more += f"\n추가 계좌 코드도 바뀜 ({EXTRAS_ONLY_KO}) → 그 계좌들의 30일을 다시 셀지 확인"
        return (f"재시작 변경 · {only} 그룹만 영향\n\n바뀐 것: {names}\n"
                f"규칙(Q5)상 {only} 계좌의 30일 기간만 오늘부터 다시 셈 (잠긴 매매법 36개·다른 그룹은 그대로)"
                f"{more}\n→ 규칙 관리자 확인 필요")
    if any(c["trading"] and c.get("shared") for c in ch):
        return (f"재시작 변경 · 원래·추가 계좌 모두 확인 필요\n\n바뀐 것: {names}\n"
                "원래 계좌의 신호 계산(recorder.py)·차트 설명(context.py)에도 쓰는 코드\n"
                "→ 규칙 관리자가 Q5(30일을 다시 셀지) 확인 (recorder.py 변경은 따로도 잡힘, Q-11)")
    if any(c["trading"] for c in ch):
        return (f"재시작 변경 · 추가 계좌만 영향\n\n바뀐 것: {names}\n"
                f"추가 계좌의 체결·신호 코드 ({EXTRAS_ONLY_KO}, 원래 계좌의 코드는 그대로)\n"
                "→ 그 계좌들의 30일을 다시 셀지 규칙 관리자 확인")
    return f"ℹ️ 재시작 변경 · {names} (거래에는 영향 없음)"
