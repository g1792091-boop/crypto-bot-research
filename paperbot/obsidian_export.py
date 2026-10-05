"""Nightly export of the agents' knowledge as an Obsidian vault (a folder of Markdown files), Korean, read-only.

    python -m paperbot.obsidian_export build  --out /var/lib/paperbot/obsidian --paper-db ... --daily-db ... \\
        --agents-db ... --checkpoint-db ... --inbox-db ... --repo-dir /opt/crypto-bot-research [--dry-run]
    python -m paperbot.obsidian_export status --out /var/lib/paperbot/obsidian
    python -m paperbot.obsidian_export preview --vault /var/lib/paperbot/obsidian --out /tmp/preview

What it is: a one-way, regenerable VIEW of paper3.db, daily3.db, agents3.db, checkpoint.db, inbox.db and the repo's
documents (docs/*.md, research/**.md). The databases stay the source of truth: every database is opened read-only
(rooms_db.open_ro) and nothing here ever writes to one. No trading code is imported.

What it writes (docs/obsidian-vault.md):
- notes in 00 홈 ... 08 규칙·문서 and `.obsidian/` (colour theme, graph colours, CSS snippets) in the vault folder;
- ``.paperbot-obsidian-manifest.json``: the files it generated and their SHA-256. Only files in the manifest are
  ever replaced or removed, and only while they still have the bytes it wrote (a note the owners edited is kept);
- never anything in ``99 내 메모`` (the owners' folder; created empty with a starter note when missing, then left
  alone) and never any file it did not generate. Every file is written to a staging folder inside the vault and renamed
  into place, so a reader (Obsidian, Syncthing) never sees a half-written note. A note whose only change is its
  generation-time line is not rewritten (no needless sync traffic).
- same input, same bytes (except the generation-time line): everything is sorted, nothing random.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from typing import Optional

from . import obsidian_home as H
from . import obsidian_notes as N
from . import obsidian_notes_b as NB
from .obsidian_sources import load_all
from .obsidian_util import MOCHA, TYPE_COLORS, kst_stamp, rgb_int

MANIFEST = ".paperbot-obsidian-manifest.json"
STAGING = ".paperbot-obsidian-staging"
PROTECTED_DIR = N.FOLDERS["mine"]
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "obsidian_vault", "config")
DEFAULT_OUT = "/var/lib/paperbot/obsidian"
DEFAULT_REPO = "/opt/crypto-bot-research"
DEFAULT_DBS = {"paper_db": "/var/lib/paperbot/paper3.db", "daily_db": "/var/lib/paperbot/daily3.db",
               "agents_db": "/var/lib/paperbot/agents3.db", "checkpoint_db": "/var/lib/paperbot/checkpoint.db",
               "inbox_db": "/var/lib/paperbot/inbox.db"}
STARTER_NAME = "메모 시작.md"
STARTER = """# 내 메모

이 폴더(`99 내 메모`)는 두 분이 직접 쓰는 곳입니다. 자동 갱신이 이 폴더의 파일을 **만들지도 고치지도 지우지도 않습니다**.

- 새 노트를 만들면 이 폴더에 저장되도록 설정돼 있습니다.
- 다른 노트로 연결하려면 `[[` 를 입력하고 이름을 고르세요. 예: `[[홈]]`
- 이 파일은 지워도 됩니다.
"""


# ================================================================== template (.obsidian)
def graph_json() -> str:
    groups = []
    order = ["허브", "전략", "회의", "교훈", "가설", "연구", "규칙", "직원", "점검", "시험", "실험"]
    for t in order:
        groups.append({"query": f"tag:#{t}", "color": {"a": 1, "rgb": rgb_int(MOCHA[TYPE_COLORS[t]])}})
    cfg = {
        "collapse-filter": True, "search": "", "showTags": False, "showAttachments": False, "hideUnresolved": True,
        "showOrphans": False, "collapse-color-groups": False, "colorGroups": groups, "collapse-display": True,
        "showArrow": False, "textFadeMultiplier": -0.7, "nodeSizeMultiplier": 1.4, "lineSizeMultiplier": 0.8,
        "collapse-forces": True, "centerStrength": 0.45, "repelStrength": 14, "linkStrength": 0.9, "linkDistance": 190,
        "scale": 0.5, "close": True,
    }
    return json.dumps(cfg, ensure_ascii=False, indent=2) + "\n"


def bookmarks_json() -> str:
    items = [{"type": "file", "title": t, "path": p} for t, p in (
        ("홈", "00 홈/홈.md"), ("읽는 법", "00 홈/읽는 법.md"), ("매매법 목록", "02 매매법/매매법 목록.md"),
        ("회의 목록", "04 회의/회의 목록.md"), ("교훈과 가설", "05 교훈·가설/교훈과 가설.md"),
        ("매일 점검 목록", "07 매일 점검/매일 점검 목록.md"), ("시스템 지도", "00 홈/시스템 지도.md"))]
    return json.dumps({"items": items}, ensure_ascii=False, indent=2) + "\n"


def template_files() -> dict[str, str]:
    out: dict[str, str] = {}
    for root, _, names in os.walk(TEMPLATE_DIR):
        for n in sorted(names):
            p = os.path.join(root, n)
            rel = os.path.relpath(p, TEMPLATE_DIR).replace(os.sep, "/")
            with open(p, "r", encoding="utf-8") as fh:
                out[f".obsidian/{rel}"] = fh.read()
    out[".obsidian/graph.json"] = graph_json()
    out[".obsidian/bookmarks.json"] = bookmarks_json()
    return out


# ================================================================== generate (pure: no writes)
def generate(data, now_ms: int, repo_dir: str) -> dict[str, bytes]:
    ctx = N.make_ctx(data, now_ms, repo_dir)
    NB.prepare(ctx)
    v = N.Vault(ctx)
    N.build_strategies(v)
    N.build_v4_groups(v)          # paper v4: DeepSeek families, the reel, their hub
    N.build_staff(v)
    N.build_experiment(v)
    NB.build_meetings(v)
    NB.build_lessons(v)
    NB.build_research(v)
    NB.build_rules(v)
    NB.build_daily(v)
    H.build_home(v)
    H.build_guide(v)
    H.build_system_map(v)
    H.build_status(v)
    files: dict[str, bytes] = {p: t.encode("utf-8") for p, t in v.files.items()}
    for p, t in v.canvases.items():
        files[p] = (t + "\n").encode("utf-8")
    for p, t in template_files().items():
        files[p] = t.encode("utf-8")
    for p in files:
        _check_path(p)
    return files


def _check_path(p: str) -> None:
    if p.startswith("/") or ".." in p.split("/") or "\\" in p or "\x00" in p:
        raise ValueError(f"unsafe generated path {p!r}")
    if p == PROTECTED_DIR or p.startswith(PROTECTED_DIR + "/"):
        raise ValueError(f"generated path {p!r} is inside the owners' folder")


# ================================================================== checks (also used by the tests)
WIKILINK = re.compile(r"\[\[([^\]\n|#^\\]+)(?:#[^\]\n|\\]*)?(?:\\?\|[^\]\n]*)?\]\]")
FENCE = re.compile(r"^(```|~~~).*?^\1[^\n]*$", re.S | re.M)


def strip_code(text: str) -> str:
    text = FENCE.sub("", text)
    return re.sub(r"`[^`\n]*`", "", text)


def broken_links(files: dict) -> list[tuple[str, str]]:
    """[(file, target)] of wikilinks that point at no generated note (Obsidian resolves a link by file name)."""
    names, paths = set(), set()
    for p in files:
        if p.endswith(".md"):
            paths.add(p[:-3])
            names.add(p.rsplit("/", 1)[-1][:-3])
    out = []
    for p, b in files.items():
        if not p.endswith(".md"):
            continue
        text = b.decode("utf-8") if isinstance(b, bytes) else b
        for m in WIKILINK.finditer(strip_code(text)):
            t = m.group(1).strip()
            if t not in names and t not in paths:
                out.append((p, t))
    return out


# ================================================================== writer
def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def strip_stamp(b: bytes) -> bytes:
    return N.STAMP_RE.sub("", b.decode("utf-8", "replace")).encode("utf-8")


def load_manifest(out: str) -> dict:
    try:
        with open(os.path.join(out, MANIFEST), "r", encoding="utf-8") as fh:
            m = json.load(fh)
        return m if isinstance(m, dict) and isinstance(m.get("files"), dict) else {"files": {}}
    except (OSError, ValueError):
        return {"files": {}}


def _read(path: str) -> Optional[bytes]:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def _put(out: str, stage: str, rel: str, data: bytes) -> None:
    dest = os.path.join(out, rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = os.path.join(stage, hashlib.sha1(rel.encode("utf-8")).hexdigest())
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, dest)


def write_vault(out: str, files: dict[str, bytes], *, dry_run: bool = False, sources: Optional[dict] = None,
                stamp: str = "") -> dict:
    """Bring ``out`` in line with ``files`` without touching what the exporter did not write. Returns a report."""
    manifest = load_manifest(out)
    old: dict = manifest["files"]
    rep = {"written": [], "unchanged": [], "kept_user_edit": [], "skipped_user_file": [], "removed": [], "forgotten": []}
    new_files: dict[str, str] = {}
    stage = os.path.join(out, STAGING)
    if not dry_run:
        os.makedirs(out, exist_ok=True)
        if os.path.isdir(stage):
            shutil.rmtree(stage, ignore_errors=True)
        os.makedirs(stage, exist_ok=True)
    try:
        for rel in sorted(files):
            data = files[rel]
            sha = _sha(data)
            dest = os.path.join(out, rel)
            disk = _read(dest) if os.path.isfile(dest) else None
            if disk is None:                                   # not there (or the owners deleted it): write
                rep["written"].append(rel)
                new_files[rel] = sha
                if not dry_run:
                    _put(out, stage, rel, data)
                continue
            dsha = _sha(disk)
            if rel not in old:
                if dsha == sha:
                    rep["unchanged"].append(rel)
                    new_files[rel] = sha
                else:                                          # somebody else's file with our name: never touched
                    rep["skipped_user_file"].append(rel)
                continue
            if dsha != old[rel]:                               # a generated file the owners edited: keep their version
                if dsha == sha:
                    rep["unchanged"].append(rel)
                    new_files[rel] = sha
                else:
                    rep["kept_user_edit"].append(rel)
                    new_files[rel] = old[rel]
                continue
            if dsha == sha or strip_stamp(disk) == strip_stamp(data):   # same but for the time line
                rep["unchanged"].append(rel)
                new_files[rel] = dsha
                continue
            rep["written"].append(rel)
            new_files[rel] = sha
            if not dry_run:
                _put(out, stage, rel, data)
        for rel, h in sorted(old.items()):                      # files an earlier run made that are no longer made
            if rel in files:
                continue
            _check_path(rel)
            dest = os.path.join(out, rel)
            disk = _read(dest) if os.path.isfile(dest) else None
            if disk is not None and _sha(disk) == h:
                rep["removed"].append(rel)
                if not dry_run:
                    os.remove(dest)
                    _prune_dirs(out, os.path.dirname(dest))
            else:
                rep["forgotten"].append(rel)                   # edited by the owners or already gone: left alone
        if not dry_run:
            if new_files != old or (sources or {}) != (manifest.get("sources") or {}) or not os.path.exists(os.path.join(out, MANIFEST)):
                m = {"version": 1, "generated": stamp, "sources": sources or {}, "files": dict(sorted(new_files.items()))}
                _put(out, stage, MANIFEST, (json.dumps(m, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
            mine = os.path.join(out, PROTECTED_DIR)
            if not os.path.exists(mine):                       # the owners' folder: created once, then never touched
                os.makedirs(mine)
                _put(out, stage, f"{PROTECTED_DIR}/{STARTER_NAME}", STARTER.encode("utf-8"))
    finally:
        if not dry_run:
            shutil.rmtree(stage, ignore_errors=True)
    return rep


def _prune_dirs(out: str, d: str) -> None:
    out = os.path.abspath(out)
    d = os.path.abspath(d)
    while d != out and d.startswith(out + os.sep):
        rel = os.path.relpath(d, out)
        if rel.split(os.sep)[0] in (PROTECTED_DIR, ".obsidian"):
            return
        try:
            os.rmdir(d)
        except OSError:
            return
        d = os.path.dirname(d)


# ================================================================== commands
def build(out: str, *, paper_db=None, daily_db=None, agents_db=None, checkpoint_db=None, inbox_db=None,
          repo_dir: str = DEFAULT_REPO, dry_run: bool = False, now_ms: Optional[int] = None,
          allow_empty: bool = False) -> dict:
    t0 = time.time()
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    data = load_all(paper_db, daily_db, agents_db, checkpoint_db, inbox_db)
    old = load_manifest(out).get("sources") or {}
    lost = [k for k in ("paper3", "agents3") if old.get(k) and not data.present.get(k)]
    if lost and not allow_empty:
        raise SystemExit(f"obsidian_export: {', '.join(lost)} was read last time but is missing now; refusing to replace "
                         f"the vault with empty notes (use --allow-empty to force)")
    files = generate(data, now_ms, repo_dir)
    bl = broken_links(files)
    rep = write_vault(out, files, dry_run=dry_run, sources=dict(data.present), stamp=kst_stamp(now_ms))
    rep.update(notes=sum(1 for p in files if p.endswith(".md")), files=len(files), broken_links=len(bl),
               seconds=round(time.time() - t0, 2), present=dict(data.present), dry_run=dry_run,
               largest=sorted(((len(b), p) for p, b in files.items()), reverse=True)[:5])
    rep["broken_link_examples"] = bl[:5]
    return rep


def status(out: str) -> dict:
    m = load_manifest(out)
    files = m["files"]
    modified, missing = [], []
    for rel, h in files.items():
        b = _read(os.path.join(out, rel))
        if b is None:
            missing.append(rel)
        elif _sha(b) != h:
            modified.append(rel)
    mine = os.path.join(out, PROTECTED_DIR)
    n_mine = sum(len(fs) for _, _, fs in os.walk(mine)) if os.path.isdir(mine) else 0
    other = 0
    for root, dirs, fs in os.walk(out):
        dirs[:] = [d for d in dirs if d not in (PROTECTED_DIR, STAGING) and not d.startswith(".st")]
        for f in fs:
            if f.startswith(".st"):                            # Syncthing's own marker files
                continue
            rel = os.path.relpath(os.path.join(root, f), out).replace(os.sep, "/")
            if rel != MANIFEST and rel not in files:
                other += 1
    return {"exists": os.path.isdir(out), "generated_at": m.get("generated"), "sources": m.get("sources"),
            "generated_files": len(files), "edited_by_owners": modified, "missing": missing,
            "owner_files_in_99": n_mine, "other_files_not_ours": other}


def _print_build(rep: dict) -> None:
    mode = "DRY RUN (nothing written)" if rep["dry_run"] else "written"
    print(f"obsidian_export: {mode}: notes {rep['notes']}, files {rep['files']}, {rep['seconds']}s")
    print(f"  sources present: {rep['present']}")
    for k in ("written", "unchanged", "kept_user_edit", "skipped_user_file", "removed", "forgotten"):
        print(f"  {k}: {len(rep[k])}")
    print(f"  broken wikilinks: {rep['broken_links']}")
    for size, p in rep["largest"]:
        print(f"  largest: {size:>8} B  {p}")
    if rep["dry_run"]:
        for p in rep["written"]:
            print(f"  would write: {p}")
        for p in rep["removed"]:
            print(f"  would remove: {p}")


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(prog="paperbot.obsidian_export", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="regenerate the vault from the read-only sources")
    b.add_argument("--out", default=DEFAULT_OUT)
    b.add_argument("--paper-db", default=DEFAULT_DBS["paper_db"])
    b.add_argument("--daily-db", default=DEFAULT_DBS["daily_db"])
    b.add_argument("--agents-db", default=DEFAULT_DBS["agents_db"])
    b.add_argument("--checkpoint-db", default=DEFAULT_DBS["checkpoint_db"])
    b.add_argument("--inbox-db", default=DEFAULT_DBS["inbox_db"])
    b.add_argument("--repo-dir", default=DEFAULT_REPO)
    b.add_argument("--dry-run", action="store_true", help="list what would be written; write nothing")
    b.add_argument("--allow-empty", action="store_true", help="build even if a database read last time is gone")
    s = sub.add_parser("status", help="what the last build made, and what the owners changed")
    s.add_argument("--out", default=DEFAULT_OUT)
    p = sub.add_parser("preview", help="a static single-file HTML preview of a built vault (no Obsidian needed)")
    p.add_argument("--vault", default=DEFAULT_OUT)
    p.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "build":
        rep = build(a.out, paper_db=a.paper_db, daily_db=a.daily_db, agents_db=a.agents_db,
                    checkpoint_db=a.checkpoint_db, inbox_db=a.inbox_db, repo_dir=a.repo_dir, dry_run=a.dry_run,
                    allow_empty=a.allow_empty)
        _print_build(rep)
        return 0
    if a.cmd == "status":
        st = status(a.out)
        print(json.dumps(st, ensure_ascii=False, indent=1))
        return 0
    from .obsidian_preview import render_preview
    print(render_preview(a.vault, a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
