"""The v4 page's code files, fingerprinted so a browser keeps them (review 10/06: every open, F5 and phone tab restore
downloaded the 60-66 screen files again, 1.4-2.6 s of empty screen).

- ``Assets.ver()`` is a short hash of the bytes of every file under static/v4 and static/vendor. It is computed from
  the files on disk, never typed in and never from git, so it is right after ``deploy/update-dash.sh`` (which copies the
  tree with ``cp -a`` and restarts), after ``--rollback`` (the old files give the old hash back) and while a builder edits
  files under a running server (a size or mtime change is noticed within ``CHECK_S`` and the hash is taken again).
- The page at '/' is static/v4/index.html with every ``/static/v4/`` turned into ``/static/v-<ver>/v4/`` and a
  ``<meta name="pb-ver">`` (``index_html``). Everything the page loads after that is relative to its own module URL, so
  it carries the same ``v-<ver>`` prefix: those answers are stored for a year (``IMMUTABLE``). A file asked under an
  older ``v-<ver>`` (an open tab from before an update loading its next screen) is the current file, revalidated every
  time ('no-cache'), and the page's '새 버전' chip (core/version.js, /api/time ``ver``) offers the reload.
- Unversioned /static files (the old /v3 page, a direct /static/v4/... link) are revalidated on every use with an ETag
  (``etag``: the content hash for v4 / vendor files, not Starlette's mtime-and-size one).
- A file is promised for a year (and given its content ETag) only while it is the very file the fingerprint was taken
  from (``current``: same size and mtime). Between an update landing on disk and the next look (up to ``CHECK_S``) the
  new bytes are served revalidated, never stored for a year under the old version's address (a later ``--rollback``
  to that version would otherwise find the newer file in the browser's cache).
- ``index_html`` also lists the boot modules (the static imports reachable from core/main.js) as
  ``<link rel="modulepreload">``, so the first open after an update asks for them in one round instead of a chain
  nine imports deep.
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from typing import Optional

ASSET_DIRS = ("v4", "vendor")           # under static/: the v4 page and the chart library it loads
VERSIONED = "/static/v-"                # /static/v-<ver>/v4/... and /static/v-<ver>/vendor/...
IMMUTABLE = "private, max-age=31536000, immutable"
REVALIDATE = "no-cache"
CHECK_S = 2.0                           # look for changed files at most this often
BOOT = "v4/core/main.js"
IMPORT_RE = re.compile(r"""(?:^|[;\n])\s*(?:import|export)\s+(?:[^;'"]*?\sfrom\s*)?["'](\.{1,2}/[^"']+\.js)["']""", re.S)
VER_RE = re.compile(r"^[0-9a-f]{6,16}$")


class Assets:
    """Content fingerprints of static/v4 and static/vendor (thread-safe; the routes call it from worker threads)."""

    def __init__(self, static_dir: str, dirs: tuple = ASSET_DIRS, check_s: float = CHECK_S):
        self.root = os.path.abspath(static_dir)
        self.dirs = dirs
        self.check_s = check_s
        self._lock = threading.Lock()
        self._checked = 0.0
        self._sig: Optional[tuple] = None
        self._ver = ""
        self._etags: dict = {}
        self._stats: dict = {}          # rel -> (size, mtime_ns) the fingerprint was taken from
        self._index: Optional[str] = None

    # ------------------------------------------------------------------ fingerprints
    def _stat_sig(self) -> tuple:
        out = []
        for d in self.dirs:
            for base, dirs, names in os.walk(os.path.join(self.root, d)):
                dirs[:] = sorted(x for x in dirs if x != "__pycache__")
                for n in sorted(names):
                    p = os.path.join(base, n)
                    try:
                        st = os.stat(p)
                    except OSError:
                        continue
                    out.append((os.path.relpath(p, self.root).replace(os.sep, "/"), st.st_size, st.st_mtime_ns))
        return tuple(out)

    def refresh(self) -> None:
        """Take the hashes again when a file was added, removed or changed (size or mtime) since the last look."""
        now = time.monotonic()
        if self._sig is not None and now - self._checked < self.check_s:
            return
        with self._lock:
            if self._sig is not None and time.monotonic() - self._checked < self.check_s:
                return
            sig = self._stat_sig()
            self._checked = time.monotonic()
            if sig == self._sig:
                return
            etags, whole = {}, hashlib.sha256()
            stats = {rel: (size, mt) for rel, size, mt in sig}
            for rel, _, _ in sig:
                h = hashlib.sha256()
                try:
                    with open(os.path.join(self.root, rel), "rb") as fh:
                        for chunk in iter(lambda: fh.read(1 << 16), b""):
                            h.update(chunk)
                except OSError:
                    continue
                etags[rel] = h.hexdigest()[:24]
                whole.update(f"{rel}\0{etags[rel]}\n".encode())
            self._etags, self._ver, self._sig, self._index = etags, whole.hexdigest()[:10], sig, None
            self._stats = stats

    def ver(self) -> str:
        """The current fingerprint of the page's code (10 hex digits)."""
        self.refresh()
        return self._ver

    def current(self, rel: str, st) -> bool:
        """The file on disk (``st``: its os.stat) is the one the fingerprint was taken from. False for a file changed
        since the last look (an update landing between two looks): the next request looks again at once."""
        want = self._stats.get(rel)
        ok = want == (st.st_size, st.st_mtime_ns)
        if not ok and (want is not None or rel.startswith(tuple(d + "/" for d in self.dirs))):
            self._checked = float("-inf")       # (an asset changed or added; the old /v3 page's files never force a look;
                                                # -inf, not 0: monotonic time starts near 0 at boot)
        return ok

    def etag(self, rel: str) -> Optional[str]:
        """'"<content hash>"' of a file under static/ (relative path, '/' separators), None when it is not an asset."""
        self.refresh()
        e = self._etags.get(rel)
        return f'"{e}"' if e else None

    # ------------------------------------------------------------------ the page
    def boot_modules(self) -> list:
        """The static imports reachable from core/main.js (relative paths under static/), in a stable order."""
        seen, todo, out = set(), [BOOT], []
        while todo:
            rel = todo.pop(0)
            if rel in seen:
                continue
            seen.add(rel)
            try:
                with open(os.path.join(self.root, rel), encoding="utf-8") as fh:
                    src = fh.read()
            except OSError:
                continue
            out.append(rel)
            base = os.path.dirname(rel)
            for spec in IMPORT_RE.findall(src):
                nxt = os.path.normpath(os.path.join(base, spec)).replace(os.sep, "/")
                if nxt.startswith(self.dirs[0] + "/") and nxt not in seen:
                    todo.append(nxt)
        return out

    def index_html(self) -> str:
        """static/v4/index.html with versioned file addresses, the version meta and the boot modulepreloads."""
        self.refresh()
        with self._lock:
            if self._index is not None:
                return self._index
            ver = self._ver
            with open(os.path.join(self.root, "v4", "index.html"), encoding="utf-8") as fh:
                html = fh.read()
            pre = f"{VERSIONED}{ver}/"
            html = html.replace('"/static/v4/', f'"{pre}v4/')
            links = "".join(f'<link rel="modulepreload" href="{pre}{m}">\n' for m in self.boot_modules()
                            if m in self._etags)
            meta = f'<meta name="pb-ver" content="{ver}">\n'
            html = html.replace("</head>", meta + links + "</head>", 1)
            self._index = html
            return html


def split_versioned(path: str) -> Optional[tuple]:
    """'/static/v-<ver>/v4/core/x.js' -> ('<ver>', 'v4/core/x.js'); None for any other path."""
    if not path.startswith(VERSIONED):
        return None
    ver, _, rest = path[len(VERSIONED):].partition("/")
    if not VER_RE.match(ver) or not rest.startswith(tuple(d + "/" for d in ASSET_DIRS)):
        return None
    return ver, rest


def asset_files(static_dir: str, assets: Assets):
    """The /static mount: Starlette's StaticFiles plus the versioned prefix and the content ETags (see the module
    doc). Built lazily so this module imports without Starlette."""
    import anyio
    from starlette.datastructures import Headers
    from starlette.responses import FileResponse
    from starlette.staticfiles import NotModifiedResponse, StaticFiles

    class AssetFiles(StaticFiles):
        async def get_response(self, path: str, scope):
            await anyio.to_thread.run_sync(assets.refresh)
            sp = split_versioned("/static/" + path.replace(os.sep, "/"))
            cc = None
            if sp:
                ver, path = sp
                cc = IMMUTABLE if ver == assets._ver else REVALIDATE
            resp = await super().get_response(path, scope)
            if cc and resp.status_code in (200, 304):
                # a year only for the very file the version was taken from (an update landing just now: revalidated)
                resp.headers["Cache-Control"] = cc if cc != IMMUTABLE or getattr(resp, "pb_current", False) else REVALIDATE
            return resp

        def file_response(self, full_path, stat_result, scope, status_code: int = 200):
            rel = os.path.relpath(os.path.abspath(full_path), assets.root).replace(os.sep, "/")
            ok = assets.current(rel, stat_result)
            e = assets._etags.get(rel) if ok else None          # (a changed file: Starlette's own mtime-and-size ETag)
            resp = FileResponse(full_path, status_code=status_code, stat_result=stat_result,
                                headers={"etag": f'"{e}"'} if e else None)
            if self.is_not_modified(resp.headers, Headers(scope=scope)):
                resp = NotModifiedResponse(resp.headers)
            resp.pb_current = ok
            return resp

    return AssetFiles(directory=static_dir)
