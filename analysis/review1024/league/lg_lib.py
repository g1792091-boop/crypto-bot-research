"""Shared helpers for the candidate-league (커스텀값봇) review of 2026-10-24.

Everything here only READS: the export zip is untrusted data. It is unpacked by ``safe_extract`` into a new, empty folder
(members are checked: no absolute paths, no '..', only the file types the export is known to hold), and the sqlite files are
opened read-only and immutable (``mode=ro&immutable=1``), so nothing is ever written next to them. No code from the zip runs.

Units used everywhere
- ROE: a trade's net profit over its margin (fees, slippage, funding included), as the engine stores it.
- wallet %: a trade's net profit over the account's wallet just before the trade closed (pnl / (equity_after - pnl)).
- net R: net profit over the money at risk at the first stop (|entry - stop_initial| x qty).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import re
import sqlite3
import zipfile
from typing import Iterable, Optional

import numpy as np
import pandas as pd

KST = dt.timezone(dt.timedelta(hours=9))
DAY_MS = 86_400_000
EQUITY0 = 1000.0
TAKER, SLIP = 0.0005, 0.0002          # paperbot/config.py: taker fee and slippage per side
SEED = 20261024

ID_RE = re.compile(r"^(core|ds)-(.+)-(15m|30m|1h|4h)-(\d+)(-[a-z0-9]+)$")
ALLOWED_EXT = (".db", ".json", ".txt")

# account kinds of the owner-exit league (etc/rules.json order), Korean short name, group, what it is compared with
KINDS = {
    "fq": ("빠른 손절", "메인", "실전 후보. 계단 익절 + 손절 최대 2 ATR + 그 매매법 구조가 무너지고 손실이 손절 거리의 절반을 넘으면 바로 청산"),
    "nv": ("자체 판단 청산", "메인", "계단 + 2 ATR, 그 매매법이 스스로 구조가 무너졌다고 보면 손익과 상관없이 청산"),
    "sw": ("반대 신호 스위칭", "메인", "계단 + 2 ATR, 반대 방향 신호가 나오면 청산하고 반대로 진입"),
    "tg": ("손절 좁힘", "메인", "계단 + 2 ATR, 구조가 무너지면 손절선을 처음 거리의 절반으로 좁힘"),
    "iv": ("자체 무효화 손절", "메인", "계단, 처음 손절을 그 매매법의 무효화 가격에(0.5~2 ATR). 13개 후보에만"),
    "ot": ("자체 구조 청산+목표", "메인", "계단 + 2 ATR, 구조가 무너지면 청산, 그 매매법 목표가에 익절. 13개 후보에만"),
    "ld": ("대조(원래 방식)", "대조", "두 분 계단 익절(+13%→+10% …) + 손절 최대 2 ATR. 비교 기준"),
    "ldc": ("대조의 동전 짝", "동전", "대조와 같은 시각·같은 청산, 방향만 동전"),
    "fqc": ("빠른 손절의 동전 짝", "동전", "빠른 손절과 같은 시각·같은 청산, 방향만 동전"),
    "ldp": ("계단 + 후보 손절", "대조", "계단, 손절은 후보 것 그대로(3~4 ATR이 많음)"),
    "ld1": ("계단 + 손절 1 ATR", "대조", "계단, 손절 최대 1 ATR"),
    "ldt": ("대조 + BTC 추세 필터", "필터", "대조 신호 중 BTC 4시간 추세와 같은 방향만"),
    "ldv": ("대조 + 변동성 필터", "필터", "대조 신호 중 변동성이 보통일 때만"),
    "fqt": ("빠른 손절 + BTC 추세 필터", "필터", "빠른 손절 신호 중 BTC 4시간 추세와 같은 방향만"),
    "fqv": ("빠른 손절 + 변동성 필터", "필터", "빠른 손절 신호 중 변동성이 보통일 때만"),
    "sb": ("공통 3봉 구조 청산", "연구", "계단 + 2 ATR, 모든 매매법에 같은 3봉 스윙 구조가 무너지면 청산"),
    "l5": ("계단 5%부터", "연구", "+7%에 +5% 잠금부터 시작하는 계단"),
    "l20": ("계단 20%부터", "연구", "+22%에 +20% 잠금부터 시작하는 계단"),
    "e": ("지금 청산(후보 원래)", "연구", "후보의 원래 청산: 고정 익절 3R 등 + 손절 1~4 ATR"),
    "tp10": ("고정 익절 +10%", "연구", "순수익 +10%에 지정가 익절, 손절 최대 2 ATR"),
    "gb": ("큰 수익 반납 보호", "연구", "원래 청산 + +1R 뒤 최고 수익의 절반을 돌려주면 청산"),
    "ma": ("이동평균 이탈", "연구", "고정 익절 없음, EMA50을 반대로 넘어 마감하면 청산(원래 손절)"),
    "ts": ("시간 제한 4시간", "연구", "원래 청산 + 4시간 안에 안 풀리면 청산"),
    "ch": ("추적 손절 1.5 ATR", "연구", "원래 청산 + 최고가에서 1.5 ATR 되돌리면 청산"),
    "oc": ("반대 신호 청산", "연구", "고정 익절 없음, 반대 신호가 나오면 청산(원래 손절)"),
    "wk": ("주말 쉬는 계좌", "연구", "원래 청산, 주말(한국 토 09시~월 09시)에는 새로 들어가지 않음"),
}
KIND_ORDER = list(KINDS)

# what each kind is compared with on the same signals (paired by coin, side and entry minute)
CONTROL_OF = {
    "fq": "ld", "nv": "ld", "sw": "ld", "tg": "ld", "iv": "ld", "ot": "ld", "ldp": "ld", "ld1": "ld", "sb": "ld",
    "l5": "ld", "l20": "ld", "tp10": "ld", "e": "ld",
    "gb": "e", "ma": "e", "ts": "e", "ch": "e", "oc": "e", "wk": "e",
    "fqt": "fq", "fqv": "fq", "ldt": "ld", "ldv": "ld",
}
COIN_OF = {"fqc": "fq", "ldc": "ld"}          # coin twin -> its target

EXIT_KO = {"LOCK": "계단 잠금(이익 확정)", "SL": "손절", "RULE": "규칙 청산", "TP": "지정가 익절", "LIQ": "강제청산",
           "SWITCH": "스위칭", "END": "기간 끝"}
TF_ORDER = ["15m", "30m", "1h", "4h"]
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LTCUSDT", "BCHUSDT")


# ------------------------------------------------------------------------------------------------ files
def safe_extract(zip_path: str, dest: str, allowed: tuple = ALLOWED_EXT, only: Optional[set] = None) -> dict:
    """Unpack the export into ``dest`` (created; must be missing or empty). Returns {member: sha256}.
    ``only``: unpack just these member names (the rule bot export is large; only two tables are read)."""
    if os.path.exists(dest) and os.listdir(dest):
        raise SystemExit(f"압축을 풀 폴더가 비어 있지 않습니다: {dest} (새 빈 폴더를 주세요)")
    os.makedirs(dest, exist_ok=True)
    root = os.path.realpath(dest)
    out = {}
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = info.filename
            if info.is_dir():
                continue
            if name.startswith(("/", "\\")) or ".." in name.replace("\\", "/").split("/") or ":" in name:
                raise SystemExit(f"수상한 파일 이름이라 멈춥니다: {name!r}")
            if not name.endswith(allowed) or (only is not None and name not in only):
                continue                                   # nothing else is expected; never unpacked
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise SystemExit(f"링크 파일이라 멈춥니다: {name!r}")
            target = os.path.realpath(os.path.join(root, name))
            if not target.startswith(root + os.sep):
                raise SystemExit(f"폴더 밖으로 나가는 이름이라 멈춥니다: {name!r}")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                h = hashlib.sha256()
                while True:
                    b = src.read(1 << 20)
                    if not b:
                        break
                    h.update(b)
                    dst.write(b)
            out[name] = h.hexdigest()
    return out


def open_ro(path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{os.path.abspath(path)}?mode=ro&immutable=1", uri=True)


def read_json(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------------------------------------------ time
def kst(ms: Optional[float], fmt: str = "%m/%d %H:%M") -> str:
    if ms is None or (isinstance(ms, float) and math.isnan(ms)):
        return "—"
    return dt.datetime.fromtimestamp(ms / 1000, KST).strftime(fmt)


def utc(ms: Optional[float], fmt: str = "%m/%d %H:%MZ") -> str:
    if ms is None:
        return "—"
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime(fmt)


# ------------------------------------------------------------------------------------------------ league DB
def parse_id(acct: str) -> Optional[dict]:
    m = ID_RE.match(acct)
    if not m:
        return None
    return {"pool": m.group(1), "strategy": m.group(2), "tf": m.group(3), "rank": int(m.group(4)),
            "suffix": m.group(5)[1:], "pick": acct[: -len(m.group(5))]}


def load_db(path: str) -> dict:
    """One league DB: meta, engine states, closed trades (DataFrame), daily signal counts and marks."""
    c = open_ro(path)
    kv = dict(c.execute("SELECT k, v FROM kv").fetchall())
    meta = json.loads(kv.get("meta", "{}"))
    engines = json.loads(kv.get("engines", "{}"))
    last_close = json.loads(kv.get("last_close", "{}"))
    recs = []
    for acct, _et, data in c.execute("SELECT account, exit_time, data FROM trades"):
        d = json.loads(data)
        ctx = d.pop("context", None) or {}
        d["g1"] = ctx.get("g1")          # signal's side agrees with the BTC 4h trend (close vs EMA50), recorded at entry
        d["g2"] = ctx.get("g2")          # the bar's ATR% inside the middle 60 % of the last 200 bars (volatility normal)
        d["account"] = acct
        recs.append(d)
    trades = pd.DataFrame(recs)
    day = pd.read_sql("SELECT * FROM acct_day", c)
    mark = pd.read_sql("SELECT * FROM acct_mark", c)
    c.close()
    if len(trades):
        info = trades["account"].map(parse_id)
        for k in ("pool", "strategy", "tf", "rank", "suffix", "pick"):
            trades[k] = info.map(lambda x, k=k: x[k] if x else None)
        trades = enrich(trades)
    return {"path": path, "name": os.path.basename(path), "meta": meta, "engines": engines, "last_close": last_close,
            "trades": trades, "day": day, "mark": mark}


def enrich(t: pd.DataFrame) -> pd.DataFrame:
    t = t.sort_values(["exit_time", "account"]).reset_index(drop=True)
    t["eq_before"] = t["equity_after"] - t["pnl"]
    t["wallet_ret"] = t["pnl"] / t["eq_before"]
    t["notional"] = t["qty"] * t["entry_price"]
    t["slip_cost"] = t["notional"] * SLIP + (t["qty"] * t["exit_price"]).where(t["exit_reason"] != "TP", 0.0) * SLIP
    t["gross"] = t["pnl"] + t["fees"] + t["funding"] + t["slip_cost"]     # before every cost (slippage estimated)
    risk = (t["entry_price"] - t["stop_initial"]).abs() * t["qty"]
    t["net_r"] = t["pnl"] / risk.where(risk > 0)
    t["stop_pct"] = (t["entry_price"] - t["stop_initial"]).abs() / t["entry_price"]
    t["hold_h"] = (t["exit_time"] - t["entry_time"]) / 3.6e6
    t["win"] = t["pnl"] > 0
    t["day"] = (t["exit_time"] // DAY_MS) * DAY_MS                        # UTC day = KST 09:00 to 09:00
    t["entry_kst"] = pd.to_datetime(t["entry_time"], unit="ms", utc=True).dt.tz_convert("Asia/Seoul")
    t["entry_hour_kst"] = t["entry_kst"].dt.hour
    t["entry_dow_kst"] = t["entry_kst"].dt.dayofweek                       # Monday = 0
    ent_utc = pd.to_datetime(t["entry_time"], unit="ms", utc=True)
    t["weekend"] = ent_utc.dt.dayofweek >= 5                              # UTC Sat/Sun = KST Sat 09:00 .. Mon 09:00
    t["side_ko"] = np.where(t["side"] > 0, "롱", "숏")
    return t


def unrealized(engines: dict, last_close: dict) -> dict:
    """Open position value at the last closes, net of an estimated market exit (taker + slippage)."""
    out = {}
    for a, e in engines.items():
        p = e.get("position")
        if not p:
            continue
        px = last_close.get(p["symbol"])
        if px is None:
            continue
        side, qty, entry = int(p["side"]), float(p["qty"]), float(p["entry_price"])
        out[a] = side * qty * (px - entry) - qty * px * (TAKER + SLIP)
    return out


# ------------------------------------------------------------------------------------------------ statistics
def max_drawdown(values: Iterable[float], start: float = EQUITY0) -> float:
    peak, mdd, v = start, 0.0, start
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, 1 - v / peak)
    return mdd


def longest_streak(wins: Iterable[bool], value: bool = False) -> int:
    best = cur = 0
    for w in wins:
        cur = cur + 1 if bool(w) == value else 0
        best = max(best, cur)
    return best


def profit_factor(pnl: np.ndarray) -> float:
    gain, loss = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    if loss <= 0:
        return float("inf") if gain > 0 else float("nan")
    return float(gain / loss)


def day_groups(days: np.ndarray, values: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per day: (day ids, sum of values, count)."""
    u, inv = np.unique(days, return_inverse=True)
    s = np.bincount(inv, weights=values, minlength=len(u))
    n = np.bincount(inv, minlength=len(u)).astype(float)
    return u, s, n


def boot_mean(days: np.ndarray, values: np.ndarray, n_boot: int = 4000, seed: int = SEED) -> dict:
    """Mean per item with whole days resampled (time-block bootstrap). p = share of resampled means <= 0 (one-sided)."""
    values = np.asarray(values, float)
    ok = np.isfinite(values)
    days, values = np.asarray(days)[ok], values[ok]
    if len(values) == 0:
        return {"n": 0, "days": 0, "mean": None, "lo": None, "hi": None, "p_pos": None}
    u, s, n = day_groups(days, values)
    mean = float(values.mean())
    if len(u) < 5:
        return {"n": int(len(values)), "days": int(len(u)), "mean": mean, "lo": None, "hi": None, "p_pos": None}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(u), size=(n_boot, len(u)))
    bs = s[idx].sum(1) / np.maximum(n[idx].sum(1), 1)
    return {"n": int(len(values)), "days": int(len(u)), "mean": mean, "lo": float(np.quantile(bs, 0.05)),
            "hi": float(np.quantile(bs, 0.95)), "p_pos": float((1 + (bs <= 0).sum()) / (n_boot + 1))}


def signflip_p(days: np.ndarray, diffs: np.ndarray, exact_max_days: int = 16, n_mc: int = 20000, seed: int = SEED) -> Optional[float]:
    """Paired test by whole days: under 'no difference' each day's summed difference is as likely + as -.
    One-sided p for 'mean difference > 0' (exact enumeration up to 16 days)."""
    diffs = np.asarray(diffs, float)
    ok = np.isfinite(diffs)
    days, diffs = np.asarray(days)[ok], diffs[ok]
    if len(diffs) == 0:
        return None
    u, s, n = day_groups(days, diffs)
    if len(u) < 5:
        return None
    obs = s.sum()
    k = len(u)
    if k <= exact_max_days:
        signs = ((np.arange(2 ** k)[:, None] >> np.arange(k)) & 1) * 2 - 1
    else:
        rng = np.random.default_rng(seed)
        signs = rng.choice([-1, 1], size=(n_mc, k))
    tot = (signs * s).sum(1)
    return float(((tot >= obs - 1e-12).sum()) / len(tot))


def boot_diff_two(days_a, va, days_b, vb, n_boot: int = 4000, seed: int = SEED) -> dict:
    """Difference of two pooled means (a - b), whole days resampled together for both sides (same calendar days)."""
    va, vb = np.asarray(va, float), np.asarray(vb, float)
    da, db = np.asarray(days_a), np.asarray(days_b)
    ua = set(da.tolist()) | set(db.tolist())
    u = np.array(sorted(ua))
    if len(va) == 0 or len(vb) == 0:
        return {"n_a": int(len(va)), "n_b": int(len(vb)), "diff": None, "lo": None, "hi": None, "p_pos": None}
    pos = {d: i for i, d in enumerate(u)}
    ia = np.array([pos[d] for d in da])
    ib = np.array([pos[d] for d in db])
    sa = np.bincount(ia, weights=va, minlength=len(u)); na = np.bincount(ia, minlength=len(u)).astype(float)
    sb = np.bincount(ib, weights=vb, minlength=len(u)); nb = np.bincount(ib, minlength=len(u)).astype(float)
    diff = float(va.mean() - vb.mean())
    if len(u) < 5:
        return {"n_a": int(len(va)), "n_b": int(len(vb)), "diff": diff, "lo": None, "hi": None, "p_pos": None}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(u), size=(n_boot, len(u)))
    ma = sa[idx].sum(1) / np.maximum(na[idx].sum(1), 1)
    mb = sb[idx].sum(1) / np.maximum(nb[idx].sum(1), 1)
    bs = ma - mb
    return {"n_a": int(len(va)), "n_b": int(len(vb)), "diff": diff, "lo": float(np.quantile(bs, 0.05)),
            "hi": float(np.quantile(bs, 0.95)), "p_pos": float((1 + (bs <= 0).sum()) / (n_boot + 1))}


def bh(pvals: list) -> list:
    """Benjamini-Hochberg adjusted p (q). None stays None."""
    idx = [i for i, p in enumerate(pvals) if p is not None and np.isfinite(p)]
    q = [None] * len(pvals)
    if not idx:
        return q
    ps = np.array([pvals[i] for i in idx])
    order = np.argsort(ps)
    m = len(ps)
    adj = ps[order] * m / (np.arange(m) + 1)
    adj = np.minimum.accumulate(adj[::-1])[::-1]
    adj = np.minimum(adj, 1.0)
    for r, o in enumerate(order):
        q[idx[o]] = float(adj[r])
    return q


def holm(pvals: list) -> list:
    idx = [i for i, p in enumerate(pvals) if p is not None and np.isfinite(p)]
    q = [None] * len(pvals)
    if not idx:
        return q
    ps = np.array([pvals[i] for i in idx])
    order = np.argsort(ps)
    m = len(ps)
    adj = np.maximum.accumulate(ps[order] * (m - np.arange(m)))
    adj = np.minimum(adj, 1.0)
    for r, o in enumerate(order):
        q[idx[o]] = float(adj[r])
    return q


def spearman(a, b) -> Optional[float]:
    a, b = pd.Series(a, dtype=float), pd.Series(b, dtype=float)
    ok = a.notna() & b.notna()
    if ok.sum() < 5:
        return None
    return float(a[ok].rank().corr(b[ok].rank()))


def jsonable(x):
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        v = float(x)
        return None if not math.isfinite(v) else v
    if isinstance(x, (np.bool_,)):
        return bool(x)
    if isinstance(x, pd.Timestamp):
        return x.isoformat()
    return x
