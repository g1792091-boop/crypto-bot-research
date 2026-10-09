"""Demo lab dashboard ("데모 랩"): a read-only web view of the engine's snapshot folder (demobot/CONTRACT.md section 4).

    DEMOBOT_DASH_PASSWORD_HASH=... DEMOBOT_DASH_SECRET=... python -m demobot.dash --snap /var/lib/demobot/snap

- Reads only: the snapshot files (``status.json``, ``home.json``, ``accounts.json``, ``acct/<id>.json``,
  ``trades.json``, ``judge.json``, ``views.json``, ``rank_<STRAT>_<tf>.npz``, ``rank_meta.json``; CONTRACT 8:
  ``costs.json``, ``regime.json``, ``backup.json``, ``watch.json``, ``bars/<COIN>.npz``) and the 5-year files
  ``demobot/data/past5y_<STRAT>_<tf>.npz``. Nothing here writes a file, opens the database or places an order.
- Every file is cached by its modification time; a file that is not there yet answers ``{"missing": true}``.
- ``/api/bars?coin=BTCUSD&tf=15m&from=<ms>&to=<ms>[&limit=n]``: candles for the trade charts (CONTRACT 8.6), coin and
  timeframe from a whitelist, the range clamped to the file, at most 3000 bars (the newest of the range when cut);
  30m bars are built by pairing the 15m bars hh:00 + hh:15 and hh:30 + hh:45 (a half without its partner is left out).
- ``/api/coins`` ("코인별 보기", CONTRACT 8.12): per coin, every account line's trades and P&L on that coin, summed
  from the ``acct/<id>.json`` trades (cached until one of those files or accounts.json changes).
- ``/api/review`` (``review.json``, 8.10) and ``/api/telegram`` (``telegram.json``, 8.11): as-is, like the others.
- CONTRACT 9 (round 4, part A): ``/api/positions``, ``/api/calendar``, ``/api/signals_now``, ``/api/dataq``,
  ``/api/timeline`` (the engine's files as-is, no parameters); ``/api/live``, ``/api/klines``, ``/api/market`` (Binance
  public market data read by this server, cached: live.py; ``DEMOBOT_DASH_LIVE=on|fake|off``); ``/api/export`` (which
  accounts have a CSV) and ``/api/export/<id>.csv`` (``snap/export/<id>.csv.gz`` decompressed, as an attachment).
- Login: one password (PBKDF2 hash in DEMOBOT_DASH_PASSWORD_HASH, ``python -m demobot.dash hash``) and a signed session
  cookie ``demobot_s`` (DEMOBOT_DASH_SECRET). The helpers are a copy of paperbot/dash/app.py's, so this dashboard does
  not depend on the rule bot's dashboard module.
- The page: static/index.html and vanilla ES modules (no outside host, no inline script), the rule bot's v4 look.
"""
from __future__ import annotations

import base64
import collections
import gzip
import hashlib
import hmac
import json
import math
import os
import re
import threading
import time
import urllib.parse
from typing import Optional

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from starlette.middleware.gzip import GZipMiddleware
from starlette.staticfiles import StaticFiles

from .. import grid
from .live import KLINE_TFS, LIMIT_MAX as KLINES_MAX, Live

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
DATA_DIR = os.path.join(os.path.dirname(HERE), "data")      # demobot/data: past5y_<STRAT>_<tf>.npz
COOKIE = "demobot_s"
SESSION_S = 7 * 86400
LOGIN_BODY_MAX = 4096
LOGIN_FAILS = 10                 # failed logins per address per 15 minutes before 429
GZIP_MIN_BYTES = 1024
RANK_CACHE_FILES = 3             # rank npz files kept in memory (one is ~5-10 MB of float32)

# no inline script, no outside host, never inside another site's frame. Inline style attributes stay allowed (the chart
# library sizes its own boxes); data: covers the copied components.css SVG masks.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'self'; "
       "form-action 'self'; frame-ancestors 'none'")
# reachable without a session: the login page and what it loads (no data in them)
PUBLIC_PATHS = frozenset(("/login", "/static/login.js", "/static/login.css", "/static/tokens.css", "/static/base.css",
                          "/static/icon.svg", "/favicon.ico"))

SNAP_FILES = {"status": "status.json", "home": "home.json", "accounts": "accounts.json", "trades": "trades.json",
              "judge": "judge.json", "rank_meta": "rank_meta.json", "views": "views.json"}
# CONTRACT 8 (round 3): the same as-is answers, but these refuse any query parameter
SNAP_FILES_STRICT = {"costs": "costs.json", "regime": "regime.json", "backup": "backup.json", "watch": "watch.json",
                     "review": "review.json", "telegram": "telegram.json"}
# CONTRACT 9 (round 4): the engine's new files, as-is, no query parameters
SNAP_FILES_LIVE = {"positions": "positions.json", "calendar": "calendar.json", "signals_now": "signals_now.json",
                   "dataq": "dataq.json", "timeline": "timeline.json"}
KLINES_PARAMS = ("coin", "tf", "limit")
EXPORT_MAX_BYTES = 64 * 1024 * 1024    # one account's decompressed CSV (every trade of every line)
TRADE_CAP = 600                  # acct/<id>.json keeps the newest 600 trades (CONTRACT 4)
M15_MS = 15 * 60_000
BARS_PARAMS = ("coin", "tf", "from", "to", "limit")
BARS_MAX = 3000                  # bars per answer
BARS_CACHE = 14                  # 7 coins x 2 timeframes (a coin's 15m file is ~0.4 MB after 3 months)
MS_RE = re.compile(r"^\d{1,15}$")
ACCOUNT_ID = re.compile(r"^[A-Za-z0-9-]{3,40}$")   # contract ids carry the upper-case strategy name (fx-def-S2-15m)


# ---------------------------------------------------------------- auth (copied from paperbot/dash/app.py)
def hash_password(password: str, salt: Optional[bytes] = None, rounds: int = 200_000) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    return f"pbkdf2${rounds}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, rounds, salt, dk = stored.split("$")
        got = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(rounds))
        return hmac.compare_digest(got, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


def _sign(secret: bytes, payload: str) -> str:
    return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()


def make_token(secret: bytes, now: Optional[float] = None) -> str:
    exp = int((now or time.time()) + SESSION_S)
    return f"{exp}.{_sign(secret, str(exp))}"


def token_ok(secret: bytes, token: Optional[str], now: Optional[float] = None) -> bool:
    if not token or "." not in token:
        return False
    exp, sig = token.split(".", 1)
    if not exp.isdigit() or int(exp) < (now or time.time()):
        return False
    return hmac.compare_digest(sig, _sign(secret, exp))


def safe_next(path: Optional[str]) -> bool:
    """A login ``next`` this server may send the browser to: a same-origin path ('/...', never '//host', a
    backslash, a control character or the login page itself)."""
    return (isinstance(path, str) and 0 < len(path) <= 2000 and path.startswith("/") and not path.startswith("//")
            and "\\" not in path and not any(ord(ch) < 32 or ord(ch) == 127 for ch in path)
            and not path.startswith("/login") and not path.startswith("/api/"))


def login_redirect(path: str, query: str = "") -> str:
    """'/login?next=<path>' for a page asked without a session (the path and its query string; '/' when unsafe)."""
    nxt = path + (f"?{query}" if query else "")
    return "/login?next=" + urllib.parse.quote(nxt if safe_next(nxt) else "/", safe="/")


def same_origin(req: Request) -> bool:
    """POST /login and /logout: refuse a request whose Origin header is present and is not this site (scheme
    included), and any browser request marked cross-site."""
    origin = req.headers.get("origin")
    if origin is not None:
        try:
            o = urllib.parse.urlsplit(origin)
        except ValueError:
            return False
        if not o.netloc or o.netloc.lower() != req.headers.get("host", "").lower():
            return False
        if (o.scheme or "").lower() != req.url.scheme.lower():
            return False
    return req.headers.get("sec-fetch-site", "") != "cross-site"


# ---------------------------------------------------------------- snapshot reading (cached by mtime)
def finite_json(o):
    """NaN / inf -> None anywhere in a parsed JSON value (the browser's JSON.parse refuses NaN)."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: finite_json(v) for k, v in o.items()}
    if isinstance(o, list):
        return [finite_json(v) for v in o]
    return o


def _stamp(path: str):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


MISSING = b'{"missing":true}'


class Snap:
    """The snapshot folder, read-only. JSON files come back as ready bytes (parsed once per change, NaN -> null);
    rank npz files as dicts of arrays (a few kept in memory)."""

    def __init__(self, snap_dir: str, data_dir: Optional[str] = None):
        self.dir = os.path.abspath(snap_dir)
        self.data_dir = os.path.abspath(data_dir or DATA_DIR)
        self._lock = threading.Lock()
        self._json: dict[str, tuple] = {}
        self._npz: "collections.OrderedDict[str, tuple]" = collections.OrderedDict()
        self._bars: "collections.OrderedDict[tuple, tuple]" = collections.OrderedDict()   # its own cache: never
        self._labels: dict[str, list] = {}                                                 # evicts the rank files
        self._coins: Optional[tuple] = None                                                # (key, body) of /api/coins

    # -- json
    def json_bytes(self, rel: str) -> bytes:
        path = os.path.join(self.dir, rel)
        stamp = _stamp(path)
        if stamp is None:
            return MISSING
        with self._lock:
            hit = self._json.get(rel)
            if hit and hit[0] == stamp:
                return hit[1]
        try:
            with open(path, "rb") as f:
                raw = f.read()
            obj = json.loads(raw)
            body = json.dumps(finite_json(obj), ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        except (OSError, ValueError):
            # a file being replaced or broken: keep the last good copy if there is one
            with self._lock:
                hit = self._json.get(rel)
            return hit[1] if hit else MISSING
        with self._lock:
            self._json[rel] = (stamp, body)
            if len(self._json) > 80:                     # 48 account files + the 6 shared ones, with room
                self._json.pop(next(iter(self._json)))
        return body

    def json_obj(self, rel: str):
        body = self.json_bytes(rel)
        return None if body == MISSING else json.loads(body)

    # -- npz
    def npz(self, path: str) -> Optional[dict]:
        stamp = _stamp(path)
        if stamp is None:
            return None
        with self._lock:
            hit = self._npz.get(path)
            if hit and hit[0] == stamp:
                self._npz.move_to_end(path)
                return hit[1]
        try:
            with np.load(path, allow_pickle=False) as z:
                arrays = {k: np.asarray(z[k]) for k in z.files}
        except (OSError, ValueError, EOFError):
            with self._lock:
                hit = self._npz.get(path)
            return hit[1] if hit else None
        with self._lock:
            self._npz[path] = (stamp, arrays)
            self._npz.move_to_end(path)
            while len(self._npz) > RANK_CACHE_FILES * 2:   # rank files and their 5-year partners
                self._npz.popitem(last=False)
        return arrays

    # -- bars (CONTRACT 8.6)
    def bars(self, coin: str, tf: str):
        """(ts, o, h, l, c) of one coin in 15m or 30m (sorted, finite, one bar per time), None when the file is not
        there, BAD_BARS when its arrays are not the contract's. coin must already be whitelisted."""
        path = os.path.join(self.dir, "bars", coin + ".npz")
        stamp = _stamp(path)
        if stamp is None:
            return None
        key = (coin, tf)
        with self._lock:
            hit = self._bars.get(key)
            if hit and hit[0] == stamp:
                self._bars.move_to_end(key)
                return hit[1]
        try:
            with np.load(path, allow_pickle=False) as z:
                raw = {k: np.asarray(z[k]) for k in ("ts", "o", "h", "l", "c") if k in z.files}
        except (OSError, ValueError, EOFError):
            with self._lock:
                hit = self._bars.get(key)
            return hit[1] if hit else None
        arr = clean_bars(raw)
        if arr is not BAD_BARS and tf == "30m":
            arr = pair_30m(*arr)
        with self._lock:
            self._bars[key] = (stamp, arr)
            self._bars.move_to_end(key)
            while len(self._bars) > BARS_CACHE:
                self._bars.popitem(last=False)
        return arr

    def rank_file(self, strat: str, tf: str) -> Optional[dict]:
        for name in (f"rank_{strat}_{tf}.npz", f"rank_{grid.SHORT[strat]}_{tf}.npz"):
            z = self.npz(os.path.join(self.dir, name))
            if z is not None:
                return z
        return None

    def past_file(self, strat: str, tf: str) -> Optional[dict]:
        for name in (f"past5y_{strat}_{tf}.npz", f"past5y_{grid.SHORT[strat]}_{tf}.npz"):
            z = self.npz(os.path.join(self.data_dir, name))
            if z is not None:
                return z
        return None

    def labels(self, strat: str) -> list:
        if strat not in self._labels:
            self._labels[strat] = [grid.combo_label(strat, c) for c in range(grid.NCOMBO[strat])]
        return self._labels[strat]


# ---------------------------------------------------------------- per coin (/api/coins)
def _num(x) -> float:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return 0.0
    return x if math.isfinite(x) else 0.0


def coin_view(snap: "Snap") -> bytes:
    """Every account line's closed trades, wins, mean R, P&L (closed + open) and open positions per coin, from the
    acct/<id>.json trades. An account whose file holds TRADE_CAP trades only covers its newest ones: "partial"."""
    accts = snap.json_obj("accounts.json")
    if not isinstance(accts, dict) or isinstance(accts.get("missing"), bool):
        return MISSING
    rows = [a for a in accts.get("accounts") or [] if isinstance(a, dict) and ACCOUNT_ID.fullmatch(str(a.get("id", "")))]
    key = (_stamp(os.path.join(snap.dir, "accounts.json")),
           tuple(_stamp(os.path.join(snap.dir, "acct", a["id"] + ".json")) for a in rows))
    with snap._lock:
        if snap._coins and snap._coins[0] == key:
            return snap._coins[1]
    per = {c: {} for c in grid.COINS}
    partial = 0
    for a in rows:
        d = snap.json_obj(os.path.join("acct", a["id"] + ".json"))
        trades = d.get("trades") if isinstance(d, dict) else None
        if not isinstance(trades, list):
            continue
        cut = len(trades) >= TRADE_CAP
        partial += cut
        since = min((int(_num(t.get("entry_ms"))) for t in trades if isinstance(t, dict) and t.get("entry_ms")), default=None)
        for t in trades:
            if not isinstance(t, dict) or t.get("coin") not in per:
                continue
            try:
                L = int(t.get("L"))
            except (TypeError, ValueError):
                continue
            ln = per[t["coin"]].setdefault((a["id"], L), {
                "id": a["id"], "name": a.get("name") or a["id"], "kind": a.get("kind"), "tf": a.get("tf"), "L": L,
                "trades": 0, "wins": 0, "sum_R": 0.0, "n_R": 0, "pnl": 0.0, "pnl_closed": 0.0, "open": 0,
                "partial": cut, "since_ms": since})
            pnl = _num(t.get("pnl"))
            ln["pnl"] += pnl
            if t.get("status") == "open":
                ln["open"] += 1
                continue
            ln["trades"] += 1
            ln["wins"] += pnl > 0
            ln["pnl_closed"] += pnl
            if t.get("R") is not None and math.isfinite(_num(t.get("R"))):
                ln["sum_R"] += _num(t.get("R"))
                ln["n_R"] += 1
    coins = []
    for c in grid.COINS:
        lines = []
        for ln in per[c].values():
            n_R = ln.pop("n_R")
            sum_R = ln.pop("sum_R")
            ln["mean_R"] = round(sum_R / n_R, 4) if n_R else None
            ln["win_rate"] = round(ln["wins"] / ln["trades"], 4) if ln["trades"] else None
            ln["pnl"], ln["pnl_closed"] = round(ln["pnl"], 2), round(ln["pnl_closed"], 2)
            lines.append(ln)
        lines.sort(key=lambda x: -x["pnl"])
        n = sum(x["trades"] for x in lines)
        coins.append({"coin": c, "lines": lines, "total": {
            "lines": len(lines), "up": sum(1 for x in lines if x["pnl"] > 0), "down": sum(1 for x in lines if x["pnl"] < 0),
            "trades": n, "wins": sum(x["wins"] for x in lines), "open": sum(x["open"] for x in lines),
            "pnl": round(sum(x["pnl"] for x in lines), 2)}})
    body = json.dumps({"generated_ms": accts.get("generated_ms"), "accounts": len(rows), "partial_accounts": partial,
                       "trade_cap": TRADE_CAP, "coins": coins}, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode()
    with snap._lock:
        snap._coins = (key, body)
    return body


# ---------------------------------------------------------------- candles for the trade charts (/api/bars)
BAD_BARS = "bad"


def clean_bars(raw: dict):
    """The contract's arrays (ts int64, o h l c float64, 1-D, one length) -> sorted, finite, unique times."""
    if set(raw) != {"ts", "o", "h", "l", "c"}:
        return BAD_BARS
    ts = raw["ts"]
    n = ts.shape[0] if ts.ndim == 1 else -1
    if n < 0 or ts.dtype.kind not in "iu" or any(raw[k].ndim != 1 or raw[k].shape[0] != n or raw[k].dtype.kind not in "fiu"
                                                 for k in ("o", "h", "l", "c")):
        return BAD_BARS
    ts = ts.astype(np.int64)
    o, h, l, c = (raw[k].astype(np.float64) for k in ("o", "h", "l", "c"))
    ok = np.isfinite(o) & np.isfinite(h) & np.isfinite(l) & np.isfinite(c) & (ts >= 0)
    ts, o, h, l, c = ts[ok], o[ok], h[ok], l[ok], c[ok]
    order = np.argsort(ts, kind="stable")
    ts, o, h, l, c = ts[order], o[order], h[order], l[order], c[order]
    if ts.size > 1:                                     # one bar per time (the last written one wins)
        keep = np.append(ts[1:] != ts[:-1], True)
        ts, o, h, l, c = ts[keep], o[keep], h[keep], l[keep], c[keep]
    return ts, o, h, l, c


def pair_30m(ts, o, h, l, c):
    """30m bars from 15m ones (CONTRACT 8.6): hh:00 + hh:15 and hh:30 + hh:45; a half without its partner is dropped."""
    if ts.size < 2:
        return ts[:0], o[:0], h[:0], l[:0], c[:0]
    first = (ts[:-1] % (2 * M15_MS) == 0) & (ts[1:] == ts[:-1] + M15_MS)
    i = np.flatnonzero(first)
    return ts[i], o[i], np.maximum(h[i], h[i + 1]), np.minimum(l[i], l[i + 1]), c[i + 1]


def strict_params(params, allowed) -> dict:
    """A query with only known, single, short parameters (else 400)."""
    seen: dict[str, str] = {}
    for k, v in params.multi_items():
        if k not in allowed:
            _bad(f"unknown parameter: {k[:20]}")
        if k in seen:
            _bad(f"repeated parameter: {k}")
        if len(v) > 40:
            _bad(f"too long: {k}")
        seen[k] = v
    return seen


def bars_query(params) -> dict:
    seen = strict_params(params, BARS_PARAMS)
    coin = seen.get("coin", "")
    if coin not in grid.COINS:
        _bad("coin: " + " | ".join(grid.COINS))
    tf = seen.get("tf", "15m")
    if tf not in grid.TFS:
        _bad("tf: 15m | 30m")

    def ms(name):
        raw = seen.get(name)
        if raw is None:
            return None
        if not MS_RE.fullmatch(raw):
            _bad(f"{name}: epoch milliseconds (a whole number)")
        return int(raw)

    lo, hi = ms("from"), ms("to")
    if lo is not None and hi is not None and lo > hi:
        _bad("from must not be after to")
    raw = seen.get("limit")
    if raw is not None and (not re.fullmatch(r"\d{1,5}", raw) or not 1 <= int(raw) <= BARS_MAX):
        _bad(f"limit: a whole number 1-{BARS_MAX}")
    return {"coin": coin, "tf": tf, "from": lo, "to": hi, "limit": int(raw) if raw is not None else BARS_MAX}


def bars_payload(snap: "Snap", q: dict) -> dict:
    base = {"coin": q["coin"], "tf": q["tf"]}
    arr = snap.bars(q["coin"], q["tf"])
    if arr is None:
        return {"missing": True, **base}
    if arr is BAD_BARS:
        return {"missing": True, "bad_shape": True, **base}
    ts, o, h, l, c = arr
    if not ts.size:
        return {**base, "first_ms": None, "last_ms": None, "from_ms": None, "to_ms": None, "n": 0, "truncated": False,
                "bars": []}
    first, last = int(ts[0]), int(ts[-1])
    lo = first if q["from"] is None else max(q["from"], first)
    hi = last if q["to"] is None else min(q["to"], last)
    i0 = int(np.searchsorted(ts, lo, "left"))
    i1 = int(np.searchsorted(ts, hi, "right")) if hi >= lo else i0
    truncated = i1 - i0 > q["limit"]
    if truncated:                                        # the newest bars of the range (a chart that ends at "to")
        i0 = i1 - q["limit"]
    sl = slice(i0, i1)
    rows = [list(x) for x in zip(ts[sl].tolist(), o[sl].tolist(), h[sl].tolist(), l[sl].tolist(), c[sl].tolist())]
    return {**base, "first_ms": first, "last_ms": last, "from_ms": lo, "to_ms": hi, "n": len(rows),
            "truncated": bool(truncated), "bars": rows}


# ---------------------------------------------------------------- live market data (/api/klines, CONTRACT 9.1)
def klines_query(params) -> dict:
    seen = strict_params(params, KLINES_PARAMS)
    coin = seen.get("coin", "")
    if coin not in grid.COINS:
        _bad("coin: " + " | ".join(grid.COINS))
    tf = seen.get("tf", "15m")
    if tf not in KLINE_TFS:
        _bad("tf: " + " | ".join(KLINE_TFS))
    raw = seen.get("limit", "500")
    if not re.fullmatch(r"\d{1,4}", raw) or not 1 <= int(raw) <= KLINES_MAX:
        _bad(f"limit: a whole number 1-{KLINES_MAX}")
    return {"coin": coin, "tf": tf, "limit": int(raw)}


def _dump(body: dict) -> bytes:
    return json.dumps(finite_json(body), ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


# ---------------------------------------------------------------- CSV export (CONTRACT 9.9)
def account_ids(snap: "Snap") -> set:
    accts = snap.json_obj("accounts.json")
    if not isinstance(accts, dict):
        return set()
    return {str(a.get("id")) for a in accts.get("accounts") or [] if isinstance(a, dict)
            and ACCOUNT_ID.fullmatch(str(a.get("id", "")))}


def export_list(snap: "Snap") -> dict:
    """Which accounts have a CSV now (the files themselves, so the page never offers a missing one), plus the
    engine's index time."""
    folder = os.path.join(snap.dir, "export")
    known = account_ids(snap)
    try:
        names = os.listdir(folder)
    except OSError:
        names = None
    if names is None or not known:
        return {"missing": True, "ids": []}
    ids = sorted(n[:-7] for n in names if n.endswith(".csv.gz") and n[:-7] in known)
    idx = snap.json_obj(os.path.join("export", "index.json"))
    gen = idx.get("generated_ms") if isinstance(idx, dict) and isinstance(idx.get("generated_ms"), (int, float)) else None
    return {"generated_ms": gen, "ids": ids}


def export_csv(snap: "Snap", aid: str) -> bytes:
    """The decompressed CSV of one account (aid already checked against accounts.json); 404 when it is not there."""
    path = os.path.join(snap.dir, "export", aid + ".csv.gz")
    try:
        with gzip.open(path, "rb") as f:
            raw = f.read(EXPORT_MAX_BYTES + 1)
    except FileNotFoundError:
        raise HTTPException(404, "준비 중: 이 계좌의 CSV가 아직 없습니다") from None
    except (OSError, EOFError):
        raise HTTPException(503, "CSV 파일을 읽지 못했습니다 (다시 쓰는 중일 수 있음)") from None
    if len(raw) > EXPORT_MAX_BYTES:
        raise HTTPException(413, "CSV가 너무 큽니다")
    return raw


# ---------------------------------------------------------------- the ranking table (/api/rank)
STATS_K = ("n", "wins", "mean_R", "mean_G", "mdd_R", "whip", "avg_win_R", "avg_loss_R", "plateau", "open", "nsig")
KI = {k: i for i, k in enumerate(STATS_K)}
PERIODS = ("2020", "2021-23", "2024-26", "2020-03", "2022-05", "2022-11")
PERIODS_KO = {"2020": "2020", "2021-23": "21–23", "2024-26": "24–26", "2020-03": "코로나", "2022-05": "루나",
              "2022-11": "FTX"}
SORTS = ("plateau", "mean_R", "win_rate", "n", "mdd_R", "whip", "mean_G")
LOW_IS_BETTER = ("mdd_R", "whip")                  # their default order is ascending
RANK_PARAMS = ("strat", "tf", "exit", "scope", "window", "sort", "dir", "limit", "offset", "min_ok", "win60",
               "low_whip", "q")
LIMIT_MAX = 200
OFFSET_MAX = 100_000
Q_RE = re.compile(r"^[A-Za-z0-9 ./:_x-]{0,40}$")
BOOL = {"": False, "0": False, "false": False, "no": False, "off": False, "1": True, "true": True, "yes": True,
        "on": True}


def _bad(msg: str):
    raise HTTPException(400, msg)


def rank_query(params) -> dict:
    """Strict reading of /api/rank's query: unknown, repeated or out-of-range values are a 400."""
    seen: dict[str, str] = {}
    for k, v in params.multi_items():
        if k not in RANK_PARAMS:
            _bad(f"unknown parameter: {k[:20]}")
        if k in seen:
            _bad(f"repeated parameter: {k}")
        if len(v) > 40:
            _bad(f"too long: {k}")
        seen[k] = v
    s = seen.get("strat", "S2")
    strat = grid.LONG.get(s, s)
    if strat not in grid.STRATS:
        _bad("strat: S2 | N02 | N04")
    tf = seen.get("tf", "15m")
    if tf not in grid.TFS:
        _bad("tf: 15m | 30m")
    ex = seen.get("exit", "0")
    if re.fullmatch(r"\d{1,2}", ex) and int(ex) < grid.NEXIT:
        exit_i = int(ex)
    elif ex in grid.EXITS:
        exit_i = grid.EXITS.index(ex)
    else:
        _bad("exit: 0-12 or an exit name")
    scope = seen.get("scope", "ALL")
    if scope not in grid.SCOPES:
        _bad("scope: ALL or a coin (BTCUSD ...)")
    window = seen.get("window", "26w")
    if window not in grid.WINDOWS:
        _bad("window: live | 26w | 4w")
    sort = seen.get("sort", "plateau")
    if sort not in SORTS:
        _bad("sort: " + " | ".join(SORTS))
    d = seen.get("dir", "")
    if d not in ("", "asc", "desc"):
        _bad("dir: asc | desc")
    desc = (sort not in LOW_IS_BETTER) if d == "" else d == "desc"

    def integer(name, default, lo, hi):
        raw = seen.get(name)
        if raw is None:
            return default
        if not re.fullmatch(r"\d{1,6}", raw) or not lo <= int(raw) <= hi:
            _bad(f"{name}: a whole number {lo}-{hi}")
        return int(raw)

    def flag(name):
        raw = seen.get(name, "").lower()
        if raw not in BOOL:
            _bad(f"{name}: 0 | 1")
        return BOOL[raw]

    q = seen.get("q", "")
    if not Q_RE.fullmatch(q):
        _bad("q: letters, numbers, space, / . : _ - only")
    return {"strat": strat, "tf": tf, "exit": exit_i, "scope": scope, "window": window, "sort": sort, "desc": desc,
            "limit": integer("limit", 50, 1, LIMIT_MAX), "offset": integer("offset", 0, 0, OFFSET_MAX),
            "min_ok": flag("min_ok"), "win60": flag("win60"), "low_whip": flag("low_whip"), "q": q.strip()}


def _f(x) -> Optional[float]:
    if x is None:
        return None
    x = float(x)
    return x if math.isfinite(x) else None


def _r(x, nd=4) -> Optional[float]:
    x = _f(x)
    return None if x is None else round(x, nd)


def _exit_ko(i: int) -> str:
    """grid.exit_ko, or the exit's own name for an exit grid.py cannot word (never an error in the page)."""
    try:
        return grid.exit_ko(i)
    except (IndexError, ValueError, TypeError):
        return grid.EXITS[i] if 0 <= i < len(grid.EXITS) else str(i)


def rank_table(snap: Snap, p: dict) -> dict:
    strat, tf = p["strat"], p["tf"]
    C = grid.NCOMBO[strat]
    base = {"strategy": strat, "short": grid.SHORT[strat], "tf": tf, "exit": p["exit"], "exit_name": grid.EXITS[p["exit"]],
            "exit_ko": _exit_ko(p["exit"]), "scope": p["scope"], "window": p["window"], "sort": p["sort"],
            "dir": "desc" if p["desc"] else "asc", "limit": p["limit"], "offset": p["offset"], "settings": C}
    z = snap.rank_file(strat, tf)
    if z is None:
        return {"missing": True, **base}
    # the exit dimension follows grid.NEXIT (CONTRACT 7.1: 14 exits); a file written before an exit was added has
    # fewer, and that exit is simply not there yet
    W, S = len(grid.WINDOWS), len(grid.SCOPES)
    stats = z.get("stats")
    if (stats is None or stats.ndim != 5 or stats.shape[0] != W or stats.shape[2:] != (S, C, len(STATS_K))
            or not 1 <= stats.shape[1] <= grid.NEXIT):
        return {"missing": True, "bad_shape": True, **base}
    E = stats.shape[1]
    if p["exit"] >= E:
        return {"missing": True, "exit_not_in_file": True, **base}
    w, e, s = grid.WINDOWS.index(p["window"]), p["exit"], grid.SCOPES.index(p["scope"])
    cell = stats[w, e, s].astype(np.float64)                       # (C, K)
    n = np.nan_to_num(cell[:, KI["n"]], nan=0.0)
    wins = np.nan_to_num(cell[:, KI["wins"]], nan=0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        win_rate = np.where(n > 0, wins / np.where(n > 0, n, 1), np.nan)
        aw, al = cell[:, KI["avg_win_R"]], cell[:, KI["avg_loss_R"]]
        den = aw + al
        breakeven = np.where(np.isfinite(den) & (den > 0), al / np.where(den > 0, den, 1), np.nan)
    mean_R, mean_G = cell[:, KI["mean_R"]], cell[:, KI["mean_G"]]
    cost_R = mean_G - mean_R
    luck = z.get("luck95")
    luck95 = _f(luck[w, e, s]) if luck is not None and luck.shape == (W, E, S) else None
    min_n_arr = z.get("min_n")
    min_n = int(min_n_arr[w, 0 if s == 0 else 1]) if min_n_arr is not None and min_n_arr.shape == (W, 2) else None
    bounds = z.get("bounds_ms")
    bounds_ms = [int(bounds[w, 0]), int(bounds[w, 1])] if bounds is not None and bounds.shape == (W, 2) else None
    gen = z.get("generated_ms")
    generated_ms = int(gen) if gen is not None and gen.size == 1 else None

    labels = snap.labels(strat)
    min_ok = n >= (min_n if min_n is not None else 1)
    # the luck line is the best of the settings that meet the window minimum: only those are compared with it
    beats = (np.isfinite(mean_R) & (n > 0) & min_ok & (luck95 is not None)
             & (mean_R > (luck95 if luck95 is not None else np.inf)))
    mask = np.ones(C, bool)
    if p["q"]:
        ql = p["q"].lower()
        mask &= np.array([ql in lb.lower() for lb in labels])
    if p["min_ok"]:
        mask &= min_ok
    if p["win60"]:
        mask &= np.nan_to_num(win_rate, nan=-1.0) >= 0.60
    whip = cell[:, KI["whip"]]
    whip_median = None
    if p["low_whip"]:
        shown = whip[mask & np.isfinite(whip)]
        if shown.size:
            whip_median = float(np.median(shown))
            mask &= np.isfinite(whip) & (whip <= whip_median)
        else:
            mask &= False
    metric = {"plateau": cell[:, KI["plateau"]], "mean_R": mean_R, "win_rate": win_rate, "n": n,
              "mdd_R": cell[:, KI["mdd_R"]], "whip": whip, "mean_G": mean_G}[p["sort"]]
    idx = np.flatnonzero(mask)
    v = metric[idx]
    nan = ~np.isfinite(v)
    key = np.where(nan, 0.0, -v if p["desc"] else v)
    order = idx[np.lexsort((idx, key, nan))]                      # finite first, then the value, ties: lower index
    page = order[p["offset"]: p["offset"] + p["limit"]]

    past = snap.past_file(strat, tf)
    pstats = past.get("stats") if past else None
    if pstats is not None and (pstats.ndim != 5 or pstats.shape[0] != len(PERIODS) or pstats.shape[2:] != (S, C, 3)):
        pstats = None
    # a 5-year file without this exit (written before it was added): its columns stay empty, never an error
    past_has_exit = pstats is not None and e < pstats.shape[1]
    pick = grid.PICK.get((strat, tf))
    dflt, frd = grid.default_combo(strat), grid.friend_combo(strat)

    rows = []
    for i, c in enumerate(page):
        c = int(c)
        row = {"rank": p["offset"] + i + 1, "c": c, "label": labels[c],
               "is_default": c == dflt, "is_friend": frd is not None and c == frd, "is_pick": pick is not None and c == pick,
               "n": int(n[c]), "wins": int(wins[c]), "win_rate": _r(win_rate[c]), "breakeven_win": _r(breakeven[c]),
               "mean_R": _r(mean_R[c]), "mean_G": _r(mean_G[c]), "cost_R": _r(cost_R[c]),
               "mdd_R": _r(cell[c, KI["mdd_R"]]), "whip": _r(whip[c]), "avg_win_R": _r(aw[c]), "avg_loss_R": _r(al[c]),
               "plateau": _r(cell[c, KI["plateau"]]), "open": int(np.nan_to_num(cell[c, KI["open"]])),
               "nsig": int(np.nan_to_num(cell[c, KI["nsig"]])), "min_ok": bool(min_ok[c]),
               "beats_luck": bool(beats[c]) if luck95 is not None and min_ok[c] else None, "past": None}
        if pstats is not None:
            pr = {}
            for pi, per in enumerate(PERIODS):
                pn, pw, pm = (float(x) for x in pstats[pi, e, s, c]) if past_has_exit else (math.nan,) * 3
                ok = math.isfinite(pn) and pn > 0
                pr[per] = {"n": int(pn) if ok else None, "win_rate": _r(pw) if ok else None,
                           "mean_R": _r(pm) if ok else None}
            row["past"] = pr
        rows.append(row)
    return {**base, "generated_ms": generated_ms, "bounds_ms": bounds_ms, "min_n": min_n, "luck95": _r(luck95, 5),
            "total": int(idx.size), "whip_median": _r(whip_median) if whip_median is not None else None,
            "past5y": pstats is not None, "past5y_exit": bool(past_has_exit), "periods": list(PERIODS), "periods_ko": [PERIODS_KO[x] for x in PERIODS],
            "rows": rows}


DIM_KO = {"st_atr_len": "ST 기간", "st_mult": "ST 배수", "roc_len": "ROC 기간", "kst_scale": "KST 배율",
          "kst_signal_len": "KST 신호선", "kvo_scale": "클링거 배율", "kvo_signal_len": "클링거 신호선"}


def grid_info() -> dict:
    """The settings grid in the page's words (demobot/grid.py is the one source). ``dims``: each strategy's parameters
    in combo order (a combo index is their row-major position, numpy.unravel_index) for the 설정 지도."""
    return {"strategies": [{"id": s, "short": grid.SHORT[s], "settings": grid.NCOMBO[s],
                            "default": grid.combo_label(s, grid.default_combo(s)),
                            "friend": grid.combo_label(s, grid.friend_combo(s)) if grid.friend_combo(s) is not None else None,
                            "pick": {tf: grid.combo_label(s, grid.PICK[(s, tf)]) for tf in grid.TFS},
                            "dims": [{"key": k, "ko": DIM_KO.get(k, k), "values": [float(v) for v in vals]}
                                     for k, vals in grid.DIMS[s]],
                            "default_idx": list(grid.DEFAULT_IDX[s])}
                           for s in grid.STRATS],
            "tfs": list(grid.TFS), "exits": [{"i": i, "name": n, "ko": _exit_ko(i)} for i, n in enumerate(grid.EXITS)],
            "scopes": list(grid.SCOPES), "windows": list(grid.WINDOWS), "coins": list(grid.COINS),
            "leverages": list(grid.LEVS), "sorts": list(SORTS), "periods": list(PERIODS),
            "periods_ko": [PERIODS_KO[x] for x in PERIODS], "limit_max": LIMIT_MAX}


# ---------------------------------------------------------------- the app
def _json(body: bytes) -> Response:
    return Response(content=body, media_type="application/json")


async def _login_body(req: Request) -> dict:
    raw = b""
    async for chunk in req.stream():
        raw += chunk
        if len(raw) > LOGIN_BODY_MAX:
            raise HTTPException(413, "too large")
    ctype = req.headers.get("content-type", "").split(";")[0].strip().lower()
    try:
        if ctype == "application/json":
            obj = json.loads(raw or b"{}")
            return obj if isinstance(obj, dict) else {}
        q = urllib.parse.parse_qs(raw.decode("utf-8"), keep_blank_values=True, max_num_fields=8)
        return {k: v[0] for k, v in q.items()}
    except (ValueError, UnicodeDecodeError):
        return {}


def create_app(snap_dir: str, password_hash: Optional[str], secret: bytes, data_dir: Optional[str] = None,
               live: Optional[Live] = None) -> FastAPI:
    """password_hash None: no login (tests and local development only; __main__ refuses to start without one).
    live: the market data source (default: DEMOBOT_DASH_LIVE from the environment; tests pass one with a fake fetcher)."""
    app = FastAPI(title="demobot dash", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(GZipMiddleware, minimum_size=GZIP_MIN_BYTES)
    snap = app.state.snap = Snap(snap_dir, data_dir)
    mkt = app.state.live = live if live is not None else Live.from_env(bars=lambda coin: snap.bars(coin, "15m"))
    fails: dict[str, list] = {}
    flock = threading.Lock()

    def authed(req: Request) -> bool:
        return password_hash is None or token_ok(secret, req.cookies.get(COOKIE))

    @app.middleware("http")
    async def guard(req: Request, call_next):
        path = req.url.path
        if path in PUBLIC_PATHS or (path == "/login" and req.method == "POST"):
            resp = await call_next(req)
        elif not authed(req):
            if path.startswith("/api/"):
                resp = JSONResponse({"error": "login required"}, status_code=401)
            else:
                resp = RedirectResponse(login_redirect(path, req.url.query), status_code=303)
        else:
            resp = await call_next(req)
        if path.startswith("/static/") and not path.endswith(".html"):
            resp.headers.setdefault("Cache-Control", "no-cache")
        else:
            resp.headers["Cache-Control"] = "no-store"
        resp.headers["Content-Security-Policy"] = CSP
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "same-origin"   # "no-referrer" makes a browser send Origin: null on the login POST
        resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        return resp

    # ---- pages
    @app.get("/login")
    def login_page():
        return FileResponse(os.path.join(STATIC, "login.html"), media_type="text/html")

    @app.post("/login")
    async def login(req: Request):
        as_json = req.headers.get("content-type", "").split(";")[0].strip().lower() == "application/json"
        if not same_origin(req):
            raise HTTPException(403, "cross-site login refused")
        body = await _login_body(req)
        nxt = str(body.get("next") or "/")
        nxt = nxt if safe_next(nxt) else "/"
        ip = req.client.host if req.client else "?"
        now = time.time()
        with flock:
            recent = [t for t in fails.get(ip, []) if now - t < 900]
            fails[ip] = recent
        if len(recent) >= LOGIN_FAILS:
            if as_json:
                raise HTTPException(429, "too many attempts, wait 15 minutes")
            return RedirectResponse("/login?e=wait&next=" + urllib.parse.quote(nxt, safe="/"), status_code=303)
        pw = body.get("password")
        if password_hash is None or (isinstance(pw, str) and len(pw) <= 1024 and check_password(pw, password_hash)):
            with flock:
                fails.pop(ip, None)
            resp = JSONResponse({"ok": True}) if as_json else RedirectResponse(nxt, status_code=303)
            resp.set_cookie(COOKIE, make_token(secret), max_age=SESSION_S, httponly=True, samesite="strict",
                            secure=bool(os.environ.get("DEMOBOT_SECURE_COOKIE")), path="/")
            return resp
        with flock:
            fails.setdefault(ip, []).append(now)
        if as_json:
            raise HTTPException(401, "wrong password")
        return RedirectResponse("/login?e=1&next=" + urllib.parse.quote(nxt, safe="/"), status_code=303)

    @app.post("/logout")
    def logout(req: Request):
        if not same_origin(req):
            raise HTTPException(403, "cross-site request refused")
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(COOKIE, path="/")
        return resp

    @app.get("/")
    def index():
        return FileResponse(os.path.join(STATIC, "index.html"), media_type="text/html")

    @app.get("/favicon.ico")
    def favicon():
        return FileResponse(os.path.join(STATIC, "icon.svg"), media_type="image/svg+xml")

    # ---- data (every route: the snapshot as-is, or {"missing": true})
    def snap_route(key: str, name: str):
        def handler():
            return _json(snap.json_bytes(name))
        handler.__name__ = f"api_{key}"
        app.get(f"/api/{key}")(handler)

    for key, name in SNAP_FILES.items():
        snap_route(key, name)

    def strict_route(key: str, name: str):
        def handler(req: Request):
            strict_params(req.query_params, ())
            return _json(snap.json_bytes(name))
        handler.__name__ = f"api_{key}"
        app.get(f"/api/{key}")(handler)

    for key, name in SNAP_FILES_STRICT.items():
        strict_route(key, name)

    for key, name in SNAP_FILES_LIVE.items():
        strict_route(key, name)

    # ---- live market data (CONTRACT 9.1; the server asks Binance, the page only asks this server)
    @app.get("/api/live")
    def live_route(req: Request):
        strict_params(req.query_params, ())
        return _json(_dump(mkt.live()))

    @app.get("/api/klines")
    def klines_route(req: Request):
        q = klines_query(req.query_params)
        return _json(_dump(mkt.klines(q["coin"], q["tf"], q["limit"])))

    @app.get("/api/market")
    def market_route(req: Request):
        strict_params(req.query_params, ())
        return _json(_dump(mkt.market()))

    # ---- CSV export (CONTRACT 9.9)
    @app.get("/api/export")
    def export_index(req: Request):
        strict_params(req.query_params, ())
        return _json(_dump(export_list(snap)))

    @app.get("/api/export/{name}")
    def export_file(name: str, req: Request):
        strict_params(req.query_params, ())
        aid = name[:-4] if name.endswith(".csv") else ""
        if not ACCOUNT_ID.fullmatch(aid):
            raise HTTPException(400, "bad account id")
        if aid not in account_ids(snap):
            raise HTTPException(404, "no such account")
        return Response(content=export_csv(snap, aid), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="demolab-{aid}.csv"'})

    @app.get("/api/coins")
    def coins(req: Request):
        strict_params(req.query_params, ())
        return _json(coin_view(snap))

    @app.get("/api/bars")
    def bars(req: Request):
        body = bars_payload(snap, bars_query(req.query_params))
        return _json(json.dumps(body, separators=(",", ":"), allow_nan=False).encode())

    @app.get("/api/account/{aid}")
    def account(aid: str):
        if not ACCOUNT_ID.fullmatch(aid):
            raise HTTPException(400, "bad account id")
        return _json(snap.json_bytes(os.path.join("acct", aid + ".json")))

    @app.get("/api/rank")
    def rank(req: Request):
        p = rank_query(req.query_params)
        body = rank_table(snap, p)
        return _json(json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode())

    @app.get("/api/grid")
    def grid_route():
        return grid_info()

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
