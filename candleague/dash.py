"""후보 리그 dashboard: password login, read-only views of the engine's snapshots (CONTRACT.md 3-4).

    python -m candleague.dash            serve on CANDLEAGUE_DASH_HOST:CANDLEAGUE_DASH_PORT (default 127.0.0.1:8091)
    python -m candleague.dash hash       print a password hash for CANDLEAGUE_DASH_PASSWORD_HASH

CANDLEAGUE_DASH_OPEN=1 (setup_env.sh --no-password) serves it without the password, only on a Tailscale or loopback
address (open_ok); the firewall keeps the port to Tailscale.

Reads only CANDLEAGUE_SNAP (league.json, trades.json) and candleague/data/strategies_ko.json; never writes; a missing
file shows "준비 중". The page is the rule bot's v4 look (static/: the v4 css and the demo lab's js kit, copied). The login
pieces are the demo lab dashboard's (pbkdf2 password hash, signed session cookie, same-origin POST)."""

import asyncio
import base64
import hashlib
import hmac
import json
import math
import os
import sys
import threading
import time
import urllib.parse
from typing import Optional

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
SESSION_S = 7 * 86_400
COOKIE = "candleague_session"


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


def same_origin(req) -> bool:
    origin = req.headers.get("origin")
    if origin is not None:
        o = urllib.parse.urlsplit(origin)
        if not o.netloc or o.netloc.lower() != req.headers.get("host", "").lower():
            return False
    return req.headers.get("sec-fetch-site", "") != "cross-site"


def finite_json(o):
    """NaN / inf -> None (the browser's JSON.parse refuses NaN)."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: finite_json(v) for k, v in o.items()}
    if isinstance(o, list):
        return [finite_json(v) for v in o]
    return o


def read_snap(snap: str, name: str):
    try:
        with open(os.path.join(snap, name)) as fh:
            return finite_json(json.load(fh))
    except (OSError, ValueError):
        return None


KLINE_TFS = ("1m", "5m", "15m", "30m", "1h", "4h")      # 1m / 5m: the 터미널's short charts, the 포지션 cards' 진입 뒤 가격
STATIC_TYPES = {".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml"}

# ---------------------------------------------------------------- DeepSeek money (D11)
# The snapshot's own switch (league.json ds_money, CANDLEAGUE_DS_MONEY on the engine) decides, as before: with it off
# the engine already writes no DeepSeek money and every view here adds none. DS_MONEY_STRICT=True hides DeepSeek money
# on every view and API field whatever the snapshot says (the whole league.json / trades.json is stripped the same way
# the engine strips it, plus the checkpoint results); False keeps the owners' 2026-10-11 choice (shown).
DS_MONEY_STRICT = False
DS_KEEP_OPEN = ("symbol", "side", "since")                 # what a hidden DeepSeek position keeps (runner.account_rows)
DS_ACCOUNT_MONEY = ("mean_ret", "wallet", "max_dd")
DS_TRADE_PRICES = ("entry_price", "exit_price", "stop_initial", "tp_price", "mae_price", "mfe_price")
# summary.watch_summary / checkpoint.check fields that carry money (the rest are counts, wins and yes / no labels)
MONEY_KEYS = frozenset(("mean", "sum", "p", "wallet_sum", "dd_median", "dd_max", "base_mean", "flip_mean", "best_med",
                        "worst_med", "cand_vs_exitonly", "cand_wallet", "cand_max_dd", "quarter_wallet", "quarter_max_dd"))


def ds_hidden(a: dict, doc: Optional[dict], strict: bool = DS_MONEY_STRICT) -> bool:
    """True when this account's money must not leave the server: a DeepSeek account while the snapshot hides DeepSeek
    money (or always under DS_MONEY_STRICT)."""
    return (a or {}).get("kind") == "ds" and (strict or not (doc or {}).get("ds_money"))


def scrub_money(x):
    """A copy of a summary tree with every MONEY_KEYS value set to None (counts and labels stay)."""
    if isinstance(x, dict):
        return {k: (None if k in MONEY_KEYS and not isinstance(v, (dict, list)) else scrub_money(v)) for k, v in x.items()}
    if isinstance(x, list):
        return [scrub_money(v) for v in x]
    return x


def strict_league(doc: Optional[dict]) -> Optional[dict]:
    """league.json as the engine writes it with DeepSeek money off: DeepSeek accounts without money, their open
    position without prices, the DeepSeek pool / strategies / picks of the watch summary without money."""
    if not doc or not doc.get("ds_money") or not isinstance(doc.get("accounts"), list):
        return doc
    out = dict(doc)
    ds_ids = set()
    rows = []
    for a in doc["accounts"]:
        if a.get("kind") == "ds":
            ds_ids.add(a.get("id"))
            a = {**a, **{k: None for k in DS_ACCOUNT_MONEY}}
            if a.get("open"):
                a["open"] = {k: a["open"].get(k) for k in DS_KEEP_OPEN}
        rows.append(a)
    out["accounts"] = rows
    w = doc.get("watch")
    if isinstance(w, dict):
        w = dict(w)
        if isinstance(w.get("pools"), dict) and "ds" in w["pools"]:
            w["pools"] = {**w["pools"], "ds": {**scrub_money(w["pools"]["ds"]), "money": False}}
        if isinstance(w.get("strategies"), dict):
            w["strategies"] = {k: (scrub_money(v) if (v or {}).get("kind") == "ds" else v) for k, v in w["strategies"].items()}
        if isinstance(w.get("picks"), dict):
            w["picks"] = {k: (scrub_money(v) if k in ds_ids else v) for k, v in w["picks"].items()}
        out["watch"] = w
    out["ds_money"] = False
    return out


def strict_book(book: Optional[dict], ds_ids) -> Optional[dict]:
    """trades.json as the engine writes it with DeepSeek money off (runner.trade_book): no equity line, trades with the
    win / loss label but no P&L and no prices."""
    if not book:
        return book
    out = {}
    for aid, b in book.items():
        if aid not in ds_ids or not isinstance(b, dict):
            out[aid] = b
            continue
        trades = []
        for t in b.get("trades") or []:
            t = dict(t)
            if "win" not in t:
                t["win"] = bool(t.get("pnl") is not None and t["pnl"] > 0)
            t["pnl"] = t["roe"] = None
            for k in DS_TRADE_PRICES:
                if k in t:
                    t[k] = None
            trades.append(t)
        out[aid] = {**b, "equity": None, "trades": trades}
    return out


# ---------------------------------------------------------------- open positions: size, margin, liquidation (B1)
# The snapshot's open position is {symbol, side, entry, stop, tp, since, lev} (runner.account_rows). Its size, margin
# and liquidation price follow from the engine's own sizing rule (paperbot.sizing.size_position under
# config.V3_QUALITY_TIERS, the account's ``size`` scaling the margin fraction: exits.settings_for): margin fraction =
# lev/100 x size of the equity at entry E, qty = floor(E x frac x lev / fill, qty_step), margin = qty x fill / lev,
# fee = qty x fill x taker; the wallet after the entry is E - fee, so E = wallet + fee (a fixed point, 4 steps). Exact
# for every open position of the real league (all 73 of the 10/01-10/10 replay) while no funding was paid since the
# entry; funding moves the wallet and the margin a little (the numbers are "진입 때 기준"). When the snapshot carries the
# engine's own qty / margin_initial / liq (runner D-4), those are used instead (exact: true).
TAKER_FEE = 0.0005                                          # paperbot.config.Settings.taker_fee (v3_settings)
EXCHANGE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "research", "fullgrid",
                             "exchange.json")
_EXCHANGE: dict = {}


def load_exchange(path: str = EXCHANGE_FILE) -> Optional[dict]:
    """{"brackets": {symbol: paperbot.margin.Brackets}, "steps": {symbol: qty_step}, "source": "exchange.json (<utc>)"}
    from the study's exchange.json (the leverage table and order sizes the engine runs with: runner.load_exchange),
    read once; None when the file or paperbot is missing (the liquidation fields are then null)."""
    if path in _EXCHANGE:
        return _EXCHANGE[path]
    try:
        from paperbot.margin import Brackets
        with open(path) as fh:
            doc = json.load(fh)
        ex = {"brackets": {p["symbol"]: Brackets.from_binance(p) for p in doc["brackets"]},
              "steps": {s: float(v["qty_step"]) for s, v in doc["specs"].items()},
              "source": f"{os.path.basename(path)} ({doc.get('fetched_utc')})"}
    except (OSError, ValueError, KeyError, TypeError, ImportError):
        ex = None
    _EXCHANGE[path] = ex
    return ex


def _round_down(x: float, step: float) -> float:
    """paperbot.sizing._round_down."""
    return math.floor(x / step + 1e-9) * step if step > 0 else x


def rebuild_open(o: dict, wallet: float, size: float, ex: Optional[dict]) -> dict:
    """{qty, margin, equity_at_entry, liq, exact} of an open position (see the block comment above)."""
    lev, entry, side, sym = int(o["lev"]), float(o["entry"]), int(o["side"]), o["symbol"]
    from paperbot.margin import liquidation_price
    if o.get("qty") is not None and o.get("margin_initial") is not None:          # the engine's own numbers (D-4)
        qty, margin = float(o["qty"]), float(o["margin_initial"])
        eq0 = margin / (lev / 100 * size) if lev and size else None
        liq = o.get("liq")
        if liq is None and ex and sym in ex["brackets"]:
            liq = liquidation_price(side, qty, entry, margin, ex["brackets"][sym].for_notional(qty * entry))
        return {"qty": qty, "margin": margin, "equity_at_entry": eq0, "liq": liq, "exact": True}
    frac = round(lev / 100 * size, 6)
    step = (ex or {}).get("steps", {}).get(sym, 0.0)
    eq0 = wallet / (1 - frac * lev * TAKER_FEE)
    qty = 0.0
    for _ in range(4):
        qty = _round_down(eq0 * frac * lev / entry, step)
        eq0 = wallet + qty * entry * TAKER_FEE
    margin = qty * entry / lev
    liq = None
    if ex and sym in ex["brackets"] and qty > 0:
        liq = liquidation_price(side, qty, entry, margin, ex["brackets"][sym].for_notional(qty * entry))
    return {"qty": qty, "margin": margin, "equity_at_entry": eq0, "liq": liq, "exact": False}


RULE_KO = ("규칙: 좋은 자리는 50배(증거금 50%) → 40배(40%), 보통 자리는 30배(30%) → 20배(20%) 순서로 시도하고, "
           "손절선이 청산가 안쪽에 여유를 두고 손절 손실이 잔고의 15% 이하인 첫 배수로 들어갑니다")


def why_lev(a: dict, lev: int, margin_pct: Optional[float], liq_dist: Optional[float]) -> dict:
    """"왜 N배" in plain Korean from the leverage the engine chose (the snapshot has no 좋은 자리 / 보통 mark: a 30x or
    20x core entry may be either a 보통 자리 or a 좋은 자리 that stepped down, and the text says so)."""
    ds = a.get("kind") == "ds"
    if lev >= 50:
        group, lev_ko = "좋은 자리", "좋은 자리 첫 배수 50배 그대로"
    elif lev >= 40:
        group, lev_ko = "좋은 자리", "좋은 자리 · 50배가 안전 검사에 걸려 40배"
    elif lev >= 30:
        group = "보통 자리" if ds else None
        lev_ko = ("딥시크 매매법은 규칙상 늘 보통 자리 · 첫 배수 30배 그대로" if ds else
                  "보통 자리 첫 배수 30배 그대로, 또는 좋은 자리가 50·40배 안전 검사에 걸려 내려옴 (기록에 자리 표시 없음)")
    else:
        group = "보통 자리" if ds else None
        lev_ko = "30배가 안전 검사(손절선이 청산가에 너무 가까움 / 손절 손실이 잔고 15% 초과)에 걸려 20배"
    role = a.get("role")
    if role == "quarter":
        sub = "1/4 계좌: 같은 신호, 증거금 비율만 1/4 (배수는 같은 규칙으로 다시 골라 후보보다 높을 수도 있음)"
    elif role == "flip":
        sub = "동전 계좌: 후보와 같은 신호 · 같은 배수 규칙, 방향만 동전으로 정함"
    elif role == "base":
        sub = "기본값 계좌: 규칙봇과 같은 숫자 · 같은 배수 규칙"
    elif role == "exitonly":
        sub = "청산만 바꾼 기본값: 기본값 숫자 · 후보의 익절·손절 · 같은 배수 규칙"
    else:
        sub = "후보: 커스텀값 · 규칙봇과 같은 배수 규칙"
    parts = [group or "보통 또는 좋은 자리", f"{lev}배"]
    if margin_pct is not None:
        parts.append(f"증거금 {margin_pct * 100:.4g}%")
    if liq_dist is not None:
        parts.append(f"진입 때 청산까지 {liq_dist * 100:.1f}%")
    return {"group_ko": group, "head_ko": " · ".join(parts), "lev_ko": lev_ko, "sub_ko": sub, "rule_ko": RULE_KO}


POS_MONEY = ("lev", "entry", "stop", "tp", "stop_is_lock", "wallet", "equity_at_entry", "qty", "notional", "margin",
             "margin_pct", "liq", "liq_dist_entry", "stop_pnl", "stop_roe", "tp_pnl", "why")


def pick_of(a: dict, cands: list) -> Optional[str]:
    """The 후보 an account belongs to: itself, its ``of``, or (기본값) the first pick of its cell."""
    if a.get("role") == "cand":
        return a.get("id")
    if a.get("of"):
        return a["of"]
    for c in cands:
        if c.get("kind") == a.get("kind") and c.get("name") == a.get("name") and c.get("tf") == a.get("tf"):
            return c.get("id")
    return None


CATCHING_MS = 30 * 60_000


def catching_up(doc: dict) -> bool:
    """lk.js catchingUp: the engine is catching up (its processed time was more than 30 minutes behind the clock when it
    wrote the snapshot: right after an install or a start-over, or after an outage). Not the install time: a league
    that starts at its install has no replay before it (owners 2026-10-12)."""
    gen, done = doc.get("generated_ms"), doc.get("done_ms")
    return bool(gen is not None and done is not None and gen - done > CATCHING_MS)


def positions_doc(doc: Optional[dict], ex: Optional[dict], strict: bool = DS_MONEY_STRICT) -> dict:
    """/api/positions without its time fields (cached per snapshot): every open position with its money rebuilt, D11
    applied, and the counts."""
    if not doc or not isinstance(doc.get("accounts"), list):
        return {"status": "준비 중", "positions": [], "counts": None}
    accts = doc["accounts"]
    cands = [a for a in accts if a.get("role") == "cand"]
    out, exact_all = [], True
    counts = {"open": 0, "long": 0, "short": 0, "hidden": 0, "by_coin": {}, "by_role": {}, "by_kind": {}}
    for a in accts:
        o = a.get("open")
        if not o:
            continue
        sym = o.get("symbol") or ""
        coin = sym[:-1] if sym.endswith("USDT") else sym
        side = int(o.get("side") or 0)
        hidden = ds_hidden(a, doc, strict)
        p = {"id": a.get("id"), "pick": pick_of(a, cands), "of": a.get("of"), "role": a.get("role"), "kind": a.get("kind"),
             "name": a.get("name"), "tf": a.get("tf"), "exit": a.get("exit"), "exit_ko": a.get("exit_ko"),
             "size": a.get("size", 1.0), "coin": coin, "symbol": sym, "side": side, "since": o.get("since"),
             "trades": a.get("trades"), "wins": a.get("wins"), "bust": bool(a.get("bust")), "hidden": hidden}
        p.update({k: None for k in POS_MONEY})
        if not hidden and o.get("entry") is not None and o.get("lev") and a.get("wallet") is not None:
            lev, entry = int(o["lev"]), float(o["entry"])
            stop = None if o.get("stop") is None else float(o["stop"])
            tp = None if o.get("tp") is None else float(o["tp"])
            r = rebuild_open(o, float(a["wallet"]), float(a.get("size") or 1.0), ex)
            exact_all = exact_all and r["exact"]
            qty, margin, liq = r["qty"], r["margin"], r["liq"]
            ld = None if liq is None else abs(liq - entry) / entry
            mp = margin / r["equity_at_entry"] if r["equity_at_entry"] else None
            p.update(lev=lev, entry=entry, stop=stop, tp=tp, wallet=a["wallet"], equity_at_entry=r["equity_at_entry"],
                     qty=qty, notional=qty * entry, margin=margin, margin_pct=mp, liq=liq, liq_dist_entry=ld,
                     stop_is_lock=None if stop is None else bool(side * (stop - entry) > 0),
                     stop_pnl=None if stop is None else side * qty * (stop - entry),
                     stop_roe=None if stop is None or not margin else side * qty * (stop - entry) / margin,
                     tp_pnl=None if tp is None else side * qty * (tp - entry),
                     why=why_lev(a, lev, mp, ld))
        out.append(p)
        counts["open"] += 1
        counts["long" if side > 0 else "short"] += 1
        counts["hidden"] += hidden
        c = counts["by_coin"].setdefault(coin, {"long": 0, "short": 0})
        c["long" if side > 0 else "short"] += 1
        counts["by_role"][p["role"]] = counts["by_role"].get(p["role"], 0) + 1
        counts["by_kind"][p["kind"]] = counts["by_kind"].get(p["kind"], 0) + 1
    out.sort(key=lambda p: (-(p["since"] or 0), p["id"] or ""))
    return {"ds_money": bool(doc.get("ds_money")) and not strict, "exact": bool(out) and exact_all,
            "brackets": ex["source"] if ex else None, "generated_ms": doc.get("generated_ms"),
            "done_ms": doc.get("done_ms"), "start_ms": doc.get("start_ms"), "started_ms": doc.get("started_ms"),
            "positions": out, "counts": counts}


SPARK_N = 30


def spark(equity: Optional[list], wallet: Optional[float] = None, n: int = SPARK_N) -> Optional[list]:
    """At most n wallet values from an equity line [[ms, wallet], ...] (the 5,000 start first), sampled evenly by time
    (the last value at or before each sample time), the account's wallet now last; None for fewer than 2 points."""
    pts = [(int(t), float(w)) for t, w in (equity or []) if t is not None and w is not None]
    if wallet is not None and pts and abs(float(wallet) - pts[-1][1]) > 1e-9:
        pts.append((pts[-1][0] + 1, float(wallet)))
    if len(pts) < 2:
        return None
    if len(pts) <= n:
        return [round(w, 2) for _, w in pts]
    t0, t1 = pts[0][0], pts[-1][0]
    out, j = [], 0
    for i in range(n):
        t = t0 + (t1 - t0) * i / (n - 1)
        while j + 1 < len(pts) and pts[j + 1][0] <= t:
            j += 1
        out.append(round(pts[j][1], 2))
    out[-1] = round(pts[-1][1], 2)
    return out


HOUR = 3_600_000
DAY_MS = 86_400_000
KST = 9 * HOUR


def pnl_doc(league: Optional[dict], book: Optional[dict], role: str, kind: str, strict: bool = DS_MONEY_STRICT) -> dict:
    """Realized P&L of one role's accounts (kind all / core / ds) from the equity lines (every closed trade): per hour
    (UTC hour start) and per Korean day (00:00 KST), with the trade count and wins; the total, wins / losses and the
    largest fall of the summed realized line (참고). Hidden accounts (D11) are left out and counted."""
    accts = [a for a in (league or {}).get("accounts") or []
             if a.get("role") == role and (kind == "all" or a.get("kind") == kind)]
    steps, hidden = [], 0
    for a in accts:
        eq = ((book or {}).get(a.get("id")) or {}).get("equity")
        if ds_hidden(a, league, strict) or eq is None:
            hidden += 1
            continue
        for (_t0, w0), (t1, w1) in zip(eq, eq[1:]):
            steps.append((int(t1), float(w1) - float(w0)))
    steps.sort()
    hours: dict = {}
    days: dict = {}
    run = peak = dd = total = 0.0
    wins = 0
    for t, p in steps:
        for bucket, key in ((hours, t // HOUR * HOUR), (days, (t + KST) // DAY_MS * DAY_MS - KST)):
            b = bucket.setdefault(key, [key, 0.0, 0, 0])
            b[1] += p
            b[2] += 1
            b[3] += p > 0
        total += p
        wins += p > 0
        run += p
        peak = max(peak, run)
        dd = max(dd, peak - run)
    rnd = lambda rows: [[k, round(s, 2), n, w] for k, s, n, w in rows]     # noqa: E731
    return {"role": role, "kind": kind, "accounts": len(accts) - hidden, "hidden": hidden,
            "hours": rnd(sorted(hours.values())), "days": rnd(sorted(days.values())), "total": round(total, 2),
            "trades": len(steps), "wins": wins, "losses": len(steps) - wins, "max_dd": round(dd, 2)}


def _static_files() -> frozenset:
    """Every .js / .css / .svg file under static/ (relative paths): the only files /static/ serves."""
    out = []
    for root, _dirs, files in os.walk(STATIC):
        for f in files:
            if os.path.splitext(f)[1] in STATIC_TYPES:
                out.append(os.path.relpath(os.path.join(root, f), STATIC).replace(os.sep, "/"))
    return frozenset(out)


STATIC_FILES = _static_files()
STATIC_RESCAN_S = 10.0                        # a miss under /static/ looks at the folder again at most this often
_static_seen = {"files": STATIC_FILES, "at": time.monotonic()}


def static_known(name: str) -> bool:
    """``name`` is a file /static/ may serve. The list is made when the server starts; a file added later (the code
    updated without restarting candleague-dash) is found by one rescan on its first miss, at most every
    STATIC_RESCAN_S seconds (so a stream of wrong names cannot make the server walk the folder on every request). The
    rescan uses the same rule as the start-up list: only .js / .css / .svg files under static/."""
    seen = _static_seen
    if name in seen["files"]:
        return True
    now = time.monotonic()
    if now - seen["at"] < STATIC_RESCAN_S:
        return False
    seen["at"] = now
    seen["files"] = _static_files()
    return name in seen["files"]


PUBLIC_FILES = frozenset(("tokens.css", "base.css", "login.css", "login.js", "icon.svg"))   # the login page's own
META_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "strategies_ko.json")


KLINE_END_MIN = 1_790_812_800_000            # 2026-10-01 00:00 UTC: no league trade is older (an older end is refused)


def klines_query(params, now_ms: Optional[int] = None) -> Optional[dict]:
    """coin / tf / limit (and an optional ``end``, ms: the bars before it, for a past entry's chart) of /api/klines,
    whitelisted (None when anything is off). ``end`` is rounded up to 24 bars of the timeframe so the cache serves
    nearby entries with one answer; an end after now means the latest bars."""
    from .live import COINS, TF_MS
    coin, tf = params.get("coin", ""), params.get("tf", "")
    try:
        limit = int(params.get("limit", "300"))
        end = int(params["end"]) if params.get("end") not in (None, "") else None
    except ValueError:
        return None
    if coin not in COINS or tf not in KLINE_TFS or not 50 <= limit <= 1000:
        return None
    if end is not None:
        now = int(time.time() * 1000) if now_ms is None else now_ms
        if end < KLINE_END_MIN:
            return None
        block = TF_MS[tf] * 24
        end = -(-end // block) * block
        if end > now:
            end = None
    return {"coin": coin, "tf": tf, "limit": limit, "end": end}


def open_ok(host: str) -> bool:
    """A dashboard may run without the password only where nobody but the owners' own devices can reach it: a Tailscale
    address (100.64.0.0/10) or this machine (loopback). Anything else keeps the login."""
    import ipaddress
    try:
        ip = ipaddress.ip_address((host or "").strip())
    except ValueError:
        return False
    return ip.is_loopback or ip in ipaddress.ip_network("100.64.0.0/10")


def host_ok(header: str, hosts) -> bool:
    """The request's Host (without its port) is one of ``hosts``, or this machine's Tailscale name (``name`` or
    ``name.<tailnet>.ts.net``). Without the password a page on another site could otherwise point its own name at the
    dashboard's address (DNS rebinding) and read the league from the owner's browser."""
    h = (header or "").strip().lower()
    h = h[1:h.index("]")] if h.startswith("[") and "]" in h else h.rsplit(":", 1)[0] if h.count(":") == 1 else h
    if h in hosts:
        return True
    import socket
    me = socket.gethostname().lower().split(".")[0]
    return bool(me) and (h == me or (h.startswith(me + ".") and h.endswith(".ts.net")))


def create_app(snap: str, password_hash: str, secret: bytes, live=None, open_: bool = False, hosts=None,
               ds_strict: Optional[bool] = None, exchange: Optional[str] = None):
    """``open_``: no password (owners 2026-10-11, "비밀번호 없애고 싶은데"); main() allows it only on a Tailscale or
    loopback address (open_ok), and then answers only requests addressed to this dashboard (``hosts``, host_ok).
    ``ds_strict``: DS_MONEY_STRICT for this app (tests); ``exchange``: another exchange.json (tests)."""
    from fastapi import FastAPI, Request
    from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    if live is None:
        from .live import Live
        live = Live.from_env()
    strict = DS_MONEY_STRICT if ds_strict is None else bool(ds_strict)
    # one clock for the whole server: the live feed's (the real time; a fixture's virtual time)
    clock = getattr(live, "clock", None) or time.time

    def now_ms() -> int:
        return int(clock() * 1000)

    def authed(req: Request) -> bool:
        return open_ or token_ok(secret, req.cookies.get(COOKIE))

    @app.middleware("http")
    async def headers(req: Request, call_next):
        if open_ and hosts is not None and not host_ok(req.headers.get("host", ""), hosts):
            return Response("이 대시보드는 Tailscale 주소로 여세요 (예: http://100.x.x.x:8091)", status_code=400)
        resp = await call_next(req)
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "same-origin"     # no-referrer makes a form POST's Origin "null"
        # style attributes: the chart library adds one <style> element (the rule bot's and the demo lab's CSP allow it too)
        resp.headers["Content-Security-Policy"] = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                                                   "script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        return resp

    @app.get("/login")
    def login_page():
        if open_:
            return RedirectResponse("/", status_code=303)
        return FileResponse(os.path.join(STATIC, "login.html"), headers={"Cache-Control": "no-cache"})

    @app.post("/login")
    async def login(req: Request):
        if not same_origin(req):
            return Response(status_code=403)
        form = urllib.parse.parse_qs((await req.body()).decode(errors="replace"))
        pw = (form.get("password") or [""])[0]
        if not password_hash or not check_password(pw, password_hash):
            await asyncio.sleep(1.0)                       # slows guessing without stalling other requests
            return RedirectResponse("/login?bad=1", status_code=303)
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(COOKIE, make_token(secret), max_age=SESSION_S, httponly=True, samesite="strict",
                        secure=req.url.scheme == "https")
        return resp

    @app.post("/logout")
    def logout(req: Request):
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(COOKIE)
        return resp

    @app.get("/")
    def index(req: Request):
        if not authed(req):
            return RedirectResponse("/login", status_code=303)
        return FileResponse(os.path.join(STATIC, "index.html"), headers={"Cache-Control": "no-cache"})

    @app.get("/static/{name:path}")
    def static(name: str, req: Request):
        if not static_known(name) or (name not in PUBLIC_FILES and not authed(req)):
            return Response(status_code=404)
        return FileResponse(os.path.join(STATIC, name), media_type=STATIC_TYPES[os.path.splitext(name)[1]],
                            headers={"Cache-Control": "no-cache"})

    @app.get("/favicon.ico")
    def favicon():
        return FileResponse(os.path.join(STATIC, "icon.svg"), media_type="image/svg+xml")

    cp_cache: dict = {}
    book_cache: dict = {}
    book_lock = threading.Lock()
    pos_cache: dict = {}
    pos_lock = threading.Lock()
    spark_cache: dict = {}
    pnl_cache: dict = {}
    ex_path = exchange or EXCHANGE_FILE

    def file_key(name: str):
        try:
            st = os.stat(os.path.join(snap, name))
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def read_league():
        """league.json as served (DS_MONEY_STRICT applied); None while the engine has not written it."""
        doc = read_snap(snap, "league.json")
        return strict_league(doc) if strict else doc

    def ds_ids_of(league) -> set:
        return {a.get("id") for a in (league or {}).get("accounts") or [] if a.get("kind") == "ds"}

    def read_book():
        """trades.json, parsed once per change of the file and shared (several screens ask for it at once; parsing it
        per request would grow with the league past the dashboard's memory cap). Callers never modify it.
        (served book, fills, the book as written: the last only for /api/checkpoints, which hides afterwards)."""
        key = file_key("trades.json")
        if key is None:
            return None
        lkey = file_key("league.json") if strict else None
        with book_lock:
            if book_cache.get("key") != (key, lkey):
                raw = read_snap(snap, "trades.json")
                book = raw
                if strict and raw:
                    ids = ds_ids_of(read_snap(snap, "league.json")) | {a for a in raw if a.startswith(("ds-", "base-ds-"))}
                    book = strict_book(raw, ids)
                rows = [{**t, "account": aid} for aid, b in (book or {}).items() for t in (b.get("trades") or [])]
                rows.sort(key=lambda t: t.get("exit_time") or 0, reverse=True)
                book_cache.update(key=(key, lkey), doc=book, fills=rows[:300], raw=raw)
            return book_cache["doc"], book_cache["fills"], book_cache["raw"]

    @app.get("/api/checkpoints")
    def checkpoints(req: Request):
        """The confirmed checkpoint results (WATCH_PREREG 3) for every checkpoint date already reached, computed from the
        snapshot exactly as research/fullgrid/diag/watch_check.py does (candleague/checkpoint.py); "final" once the
        engine has processed past that date. Cached until the snapshot changes. Under DS_MONEY_STRICT the numbers are
        computed from the whole snapshot and the DeepSeek pool's / strategies' money is blanked afterwards (the yes / no
        of every condition stays)."""
        if not authed(req):
            return JSONResponse({"error": "login"}, status_code=401)
        from . import checkpoint as CP
        from . import summary as SM
        today = time.strftime("%Y-%m-%d", time.gmtime())
        due = [c for c in SM.CHECKPOINTS if c["date"] <= today]
        if not due:
            return JSONResponse({"due": [], "results": {}})
        try:
            key = (os.path.getmtime(os.path.join(snap, "league.json")), os.path.getmtime(os.path.join(snap, "trades.json")),
                   tuple(c["date"] for c in due))
        except OSError:
            return JSONResponse({"due": [c["date"] for c in due], "results": {}, "status": "준비 중"})
        if cp_cache.get("key") != key:
            league, book = read_snap(snap, "league.json"), (read_book() or (None, None, None))[2]
            if not league or not league.get("accounts") or book is None:
                return JSONResponse({"due": [c["date"] for c in due], "results": {}, "status": "준비 중"})
            res = {}
            for c in due:
                r = CP.check(league, book, c["date"])
                r["final"] = int(league.get("done_ms") or 0) >= SM.day_ms(c["date"])
                r["ko"] = c["ko"]
                if strict and league.get("ds_money"):
                    if isinstance(r.get("pools"), dict) and "ds" in r["pools"]:
                        r["pools"]["ds"] = scrub_money(r["pools"]["ds"])
                    r["strategies"] = {k: (scrub_money(v) if (v or {}).get("kind") == "ds" else v)
                                       for k, v in (r.get("strategies") or {}).items()}
                res[c["date"]] = r
            cp_cache.update(key=key, doc=finite_json({"due": [c["date"] for c in due], "results": res}))
        return JSONResponse(cp_cache["doc"])

    @app.get("/api/meta")
    def meta(req: Request):
        """Korean names, entry rules, parameter meanings and each pick's character (candleague/data/strategies_ko.json)."""
        if not authed(req):
            return JSONResponse({"error": "login"}, status_code=401)
        return JSONResponse(read_snap(os.path.dirname(META_FILE), os.path.basename(META_FILE)) or {})

    @app.get("/api/live")
    def api_live(req: Request):
        """The six coins' price, mark, 24h change, funding (live.py), plus ``server_ms``: this server's clock, so the page
        can tell how old the snapshot and the prices are whatever the device's clock says."""
        if not authed(req):
            return JSONResponse({"error": "login"}, status_code=401)
        return JSONResponse(finite_json({**live.live(), "server_ms": now_ms()}))

    @app.get("/api/klines")
    def api_klines(req: Request):
        if not authed(req):
            return JSONResponse({"error": "login"}, status_code=401)
        q = klines_query(req.query_params, now_ms=now_ms())
        if q is None:
            return JSONResponse({"error": "coin / tf / limit"}, status_code=400)
        return JSONResponse(finite_json(live.klines(q["coin"], q["tf"], q["limit"], q["end"])))

    @app.get("/api/league")
    def league(req: Request):
        if not authed(req):
            return JSONResponse({"error": "login"}, status_code=401)
        return JSONResponse(read_league() or {"status": "준비 중"})

    @app.get("/api/positions")
    def positions(req: Request):
        """Every open position with its size, margin, liquidation price, stop / take-profit P&L and "왜 N배" (rebuilt from
        the snapshot: rebuild_open), DeepSeek money hidden by ds_hidden; the counts per side / coin / role / kind; the
        snapshot's times and the catch-up flag. The page adds the live mark (js/poskit.js livePnl)."""
        if not authed(req):
            return JSONResponse({"error": "login"}, status_code=401)
        key = file_key("league.json")
        with pos_lock:
            if pos_cache.get("key") != key or key is None:
                doc = read_snap(snap, "league.json") if key is not None else None
                pos_cache.update(key=key, doc=finite_json(positions_doc(doc, load_exchange(ex_path), strict)))
            base = pos_cache["doc"]
        now = now_ms()
        gen, done = base.get("generated_ms"), base.get("done_ms")
        age = None if gen is None else max(0, (now - int(gen)) // 1000)
        return JSONResponse({**base, "server_ms": now, "snap_age_s": age,
                             "lag_s": None if done is None else max(0, (now - int(done)) // 1000),
                             "catching_up": catching_up(base), "old": age is not None and age > 15 * 60})

    @app.get("/api/sparks")
    def sparks(req: Request):
        """{account id: at most 30 wallet values (the 5,000 start first, the wallet now last) | null} for the 순위표 rows;
        null for a hidden DeepSeek account (D11) or one without a closed trade."""
        if not authed(req):
            return JSONResponse({"error": "login"}, status_code=401)
        bk = read_book()
        lg = read_league()
        if bk is None or not lg:
            return JSONResponse({"status": "준비 중", "generated_ms": None, "sparks": {}})
        key = (file_key("trades.json"), file_key("league.json"))
        if spark_cache.get("key") != key:
            book = bk[0] or {}
            out = {}
            for a in lg.get("accounts") or []:
                aid = a.get("id")
                hide = ds_hidden(a, lg, strict)
                out[aid] = None if hide else spark((book.get(aid) or {}).get("equity"), a.get("wallet"))
            spark_cache.update(key=key, doc=finite_json({"generated_ms": lg.get("generated_ms"), "sparks": out}))
        return JSONResponse(spark_cache["doc"])

    @app.get("/api/pnl")
    def pnl(req: Request):
        """Realized P&L per hour and per Korean day of one role's accounts (``role`` = cand | quarter | exitonly | base |
        flip, default cand; ``kind`` = all | core | ds, default all): the 터미널's 수익 차트 and calendar (pnl_doc)."""
        if not authed(req):
            return JSONResponse({"error": "login"}, status_code=401)
        role = req.query_params.get("role", "cand")
        kind = req.query_params.get("kind", "all")
        if role not in ("cand", "quarter", "exitonly", "base", "flip") or kind not in ("all", "core", "ds"):
            return JSONResponse({"error": "role / kind"}, status_code=400)
        bk = read_book()
        lg = read_league()
        if bk is None or not lg:
            return JSONResponse({"status": "준비 중", "server_ms": now_ms(), "role": role, "kind": kind})
        key = (file_key("trades.json"), file_key("league.json"), role, kind)
        if pnl_cache.get(key) is None:
            if len(pnl_cache) > 30:
                pnl_cache.clear()
            pnl_cache[key] = finite_json({**pnl_doc(lg, bk[0], role, kind, strict), "generated_ms": lg.get("generated_ms")})
        return JSONResponse({**pnl_cache[key], "server_ms": now_ms()})

    @app.get("/api/fills")
    def fills(req: Request):
        """The league's newest closed trades over every account (newest first, at most 300)."""
        if not authed(req):
            return JSONResponse({"error": "login"}, status_code=401)
        return JSONResponse({"fills": (read_book() or (None, [], None))[1]})

    @app.get("/api/trades/{aid}")
    def trades(aid: str, req: Request):
        if not authed(req):
            return JSONResponse({"error": "login"}, status_code=401)
        book = (read_book() or (None, None, None))[0] or {}
        return JSONResponse(book.get(aid) or {"equity": None, "trades": []})

    return app


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["hash"]:
        import getpass
        pw = getpass.getpass("대시보드 비밀번호: ")
        if pw != getpass.getpass("한 번 더: "):
            print("두 번 입력한 비밀번호가 다릅니다", file=sys.stderr)
            return 2
        print(hash_password(pw))
        return 0
    import uvicorn
    host = os.environ.get("CANDLEAGUE_DASH_HOST", "127.0.0.1")
    want_open = os.environ.get("CANDLEAGUE_DASH_OPEN") == "1"
    open_ = want_open and open_ok(host)
    if want_open and not open_:
        print(f"CANDLEAGUE_DASH_OPEN=1 but {host} is not a Tailscale or loopback address: the login stays on",
              file=sys.stderr)
    secret = os.environ.get("CANDLEAGUE_DASH_SECRET", "").encode()
    if not open_ and (len(secret) < 16 or not os.environ.get("CANDLEAGUE_DASH_PASSWORD_HASH")):
        print("CANDLEAGUE_DASH_SECRET (16자 이상)과 CANDLEAGUE_DASH_PASSWORD_HASH가 필요합니다", file=sys.stderr)
        return 2
    app = create_app(os.environ.get("CANDLEAGUE_SNAP", "/var/lib/candleague/snap"),
                     os.environ.get("CANDLEAGUE_DASH_PASSWORD_HASH", ""), secret or os.urandom(32), open_=open_,
                     hosts={host.lower(), "localhost", "127.0.0.1", "::1"})
    uvicorn.run(app, host=host, port=int(os.environ.get("CANDLEAGUE_DASH_PORT", "8091")), log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
