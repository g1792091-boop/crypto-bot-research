"""Live records review (owners 10-28): every live trade of the executors and the friend bot, the same trade in the paper
it follows, the entry context from public 1m bars, and the same-side overlaps between bots. Read-only.

    python3 -I analysis/live1028/review.py --raw EXPORT_DIR --m1 M1_DIR [--m1 M1_DIR2] --out OUT_DIR

EXPORT_DIR: live_export.py's zip, extracted (db/, files/, paper3/). M1_DIR: public Binance 1m klines as <DIR>/1m/<SYM>.npz
(ts, o, h, l, c), e.g. analysis/v39_1h/fetch_bars.py minute with XRP and ZEC added. Outputs in OUT_DIR:
trades.csv (live), pairs.csv (live vs the same paper trade), context.csv (live and followed-paper entries), summary.json.
Research code: nothing here trades or writes outside OUT_DIR.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import site
import sqlite3
import sys

sys.dont_write_bytecode = True
if site.getusersitepackages() not in sys.path:
    sys.path.append(site.getusersitepackages())
import numpy as np  # noqa: E402

H1 = 3_600_000
EXECUTORS = ("toobit", "deepcoin", "wooxpro", "mexc", "bybit")
# which paper each executor followed, by entry time (WOO X Pro 1: 규칙봇15 until it switched to the trend bot on 10-21 23:28 KST,
# the range bot from 10-26 20:37 KST)
WOO_TREND, WOO_RANGE = 1792681200000, 1793014620000
PAPER_OF = {"toobit": ("paper3", "V3.9"), "deepcoin": ("vwap", "VWAP"), "mexc": ("live-ac", "추세판단"),
            "bybit": ("live-ac", "추세판단")}


def woo_paper(t: int) -> tuple:
    return ("live15-mexc", "규칙봇15") if t < WOO_TREND else (("live-ac", "추세판단") if t < WOO_RANGE else ("range", "레인지"))


def ro(raw: str, rel: str):
    return sqlite3.connect(f"file:{os.path.join(raw, rel)}?mode=ro&immutable=1", uri=True)


def ms(v) -> int:
    v = float(v)
    return int(v if v > 1e11 else v * 1000)


def live_trades(raw: str) -> list:
    out = []
    for ex in EXECUTORS:
        p = os.path.join(raw, "db", "exec", f"executor-{ex}-live.db")
        if not os.path.exists(p):
            continue
        c = ro(raw, f"db/exec/executor-{ex}-live.db")
        cols = [r[1] for r in c.execute("PRAGMA table_info(trades)")]
        for r in c.execute("SELECT * FROM trades WHERE exit_ts IS NOT NULL ORDER BY entry_ts"):
            d = dict(zip(cols, r))
            x = json.loads(d["data"] or "{}")
            db, src = woo_paper(d["entry_ts"]) if ex == "wooxpro" else PAPER_OF[ex]
            out.append({"bot": ex, "paper": db, "src": src, "sym": d["symbol"][:-4], "side": int(d["side"]),
                        "lev": d["leverage"], "t0": int(d["entry_ts"]), "t1": int(d["exit_ts"]),
                        "wallet": float(x.get("wallet_before") or np.nan), "entry": float(d["entry_price"]),
                        "paper_entry": float(x.get("paper_entry") or np.nan), "stop": float(d["stop_initial"]),
                        "pnl": float(d["pnl"]), "best_roe": (x.get("own") or {}).get("best_roe"),
                        "why": d["exit_reason"], "paper_exit": (x.get("paper_exit") or {}).get("reason")})
    mix = os.path.join(raw, "files", "exec", "mixchop-log.jsonl")
    if os.path.exists(mix):
        cur = None
        for line in open(mix, encoding="utf-8"):
            e = json.loads(line)
            if e["kind"] == "entry":
                cur = e
            elif e["kind"] == "exit" and cur is not None:
                out.append({"bot": "wooxpro2", "paper": "mixchop-paper", "src": "친구봇", "sym": e["symbol"][:-4],
                            "side": int(e["side"]), "lev": cur["leverage"], "t0": int(cur["opened_ms"]), "t1": int(e["ts"]),
                            "wallet": float(cur["equity_before"]), "entry": float(cur["entry"]),
                            "paper_entry": float(cur.get("signal_close") or np.nan), "stop": float(cur["stop"]),
                            "pnl": float(e["pnl"]), "best_roe": None, "why": e["why"], "paper_exit": None})
    for t in out:
        t["pct"] = t["pnl"] / t["wallet"] * 100
        t["slip_pct"] = t["side"] * (t["entry"] - t["paper_entry"]) / t["paper_entry"] * 100
    return sorted(out, key=lambda t: t["t0"])


def paper_trades(raw: str) -> list:
    out = []
    for db in ("vwap", "range", "live-ac", "live15-mexc"):
        if not os.path.exists(os.path.join(raw, "db", "combo", f"{db}.db")):
            continue
        for d, eq, pnl in ro(raw, f"db/combo/{db}.db").execute(
                "SELECT data, equity_after, pnl FROM trades WHERE account_id = 'COMBO@mix'"):
            d = json.loads(d)
            out.append({"paper": db, "sym": d["symbol"][:-4], "side": int(d["side"]), "t0": int(d["entry_time"]),
                        "t1": int(d["exit_time"]), "pct": pnl / (eq - pnl) * 100, "roe": float(d["roe"]),
                        "entry": float(d["entry_price"]), "stop": float(d["stop_initial"]), "why": d["exit_reason"]})
    p3 = os.path.join(raw, "paper3", "v39_trades.csv")
    if os.path.exists(p3):
        for r in csv.DictReader(open(p3, encoding="utf-8")):
            d = json.loads(r["data"])
            eq, pnl = float(r["equity_after"]), float(r["pnl"])
            out.append({"paper": "paper3", "sym": r["symbol"][:-4], "side": int(d["side"]), "t0": ms(r["entry_time"]),
                        "t1": ms(r["exit_time"]), "pct": pnl / (eq - pnl) * 100, "roe": float(r["roe"]),
                        "entry": float(d["entry_price"]), "stop": float(d["stop_initial"]), "why": r["exit_reason"]})
    return out


def pairs(live: list, paper: list) -> list:
    """Each live trade next to the paper trade it followed (same paper, coin and side, entry within 40 minutes)."""
    out = []
    for t in live:
        m = [p for p in paper if p["paper"] == t["paper"] and p["sym"] == t["sym"] and p["side"] == t["side"]
             and abs(p["t0"] - t["t0"]) < 40 * 60_000]
        if m:
            p = min(m, key=lambda p: abs(p["t0"] - t["t0"]))
            out.append({"bot": t["bot"], "src": t["src"], "t0": t["t0"], "sym": t["sym"], "side": t["side"],
                        "live_pct": round(t["pct"], 2), "paper_pct": round(p["pct"], 2), "live_why": t["why"],
                        "paper_why": p["why"]})
    return out


class Bars:
    def __init__(self, dirs: list):
        self.dirs, self.a = dirs, {}

    def get(self, sym: str) -> np.ndarray:
        if sym not in self.a:
            parts = []
            for d in self.dirs:
                p = os.path.join(d, "1m", f"{sym}USDT.npz")
                if os.path.exists(p):
                    z = np.load(p)
                    parts.append(np.c_[z["ts"], z["o"], z["h"], z["l"], z["c"]])
            a = np.concatenate(parts) if parts else np.zeros((0, 5))
            a = a[np.argsort(a[:, 0])]
            self.a[sym] = a[np.r_[True, np.diff(a[:, 0]) > 0]] if len(a) else a
        return self.a[sym]


def atr1h(a: np.ndarray, t0: int) -> float:
    b = a[a[:, 0] < t0 - t0 % H1]
    t = (b[:, 0] // H1).astype(np.int64)
    i = np.r_[0, np.nonzero(np.diff(t))[0] + 1]
    h, lo = np.maximum.reduceat(b[:, 2], i), np.minimum.reduceat(b[:, 3], i)
    c = b[np.r_[i[1:] - 1, len(b) - 1], 4]
    tr = np.maximum(h[1:] - lo[1:], np.maximum(abs(h[1:] - c[:-1]), abs(lo[1:] - c[:-1])))
    return float(tr[-14:].mean()) if len(tr) >= 14 else float("nan")


def context(B: Bars, kind: str, t: dict) -> dict | None:
    """Where the entry sat: 24h range position on the trade's side (1 = at the far end of the move), the move in the
    trade's direction over the 4 and 12 hours before (in 1h ATR), the first hour after (best and worst, in ATR), and
    after the exit: a loss that came back to its entry within 12 h, a win's furthest move from its entry within 12 h."""
    a = B.get(t["sym"])
    s, p, t0 = t["side"], t["entry"], t["t0"]
    if len(a) == 0 or t0 - 26 * H1 < a[0, 0] or t0 > a[-1, 0]:
        return None
    atr = atr1h(a, t0)
    pre = a[(a[:, 0] >= t0 - 24 * H1) & (a[:, 0] < t0)]
    hi, lo = pre[:, 2].max(), pre[:, 3].min()

    def px(at):
        return a[np.searchsorted(a[:, 0], at, side="right") - 1, 4]

    post = a[(a[:, 0] >= t0) & (a[:, 0] < t0 + H1)]
    fav, adv = (2, 3) if s > 0 else (3, 2)
    aft = a[(a[:, 0] >= t["t1"]) & (a[:, 0] < t["t1"] + 12 * H1)]
    res = t["pct"] if kind == "실거래" else t["roe"] * 40
    after = None
    if len(aft) >= 60:
        after = (bool((s * (aft[:, fav] - p) >= 0).any()) if res <= 0
                 else round(float((s * (aft[:, fav] - p)).max() / atr), 2))
    return {"kind": kind, "src": t.get("src") or t["paper"], "t0": t0, "sym": t["sym"], "side": s, "res": round(res, 2),
            "atr_pct": round(atr / p * 100, 3), "stop_atr": round(abs(t["stop"] - p) / atr, 2),
            "pos24": round(((p - lo) if s > 0 else (hi - p)) / (hi - lo), 3),
            "run4": round(s * (p - px(t0 - 4 * H1)) / atr, 2), "run12": round(s * (p - px(t0 - 12 * H1)) / atr, 2),
            "mfe1": round(float((s * (post[:, fav] - p)).max() / atr), 2) if len(post) >= 60 else None,
            "mae1": round(float((s * (post[:, adv] - p)).min() / atr), 2) if len(post) >= 60 else None, "after": after}


def overlaps(live: list, since: int) -> list:
    """Groups of trades of two or more bots on the same side that overlapped in time, from ``since``."""
    cur = [t for t in live if t["t0"] >= since and t["bot"] not in ("bybit", "mexc")]
    seen, out = set(), []
    for r in cur:
        if id(r) in seen:
            continue
        grp, more = [r], True
        seen.add(id(r))
        while more:
            more = False
            for x in cur:
                if id(x) not in seen and x["side"] == r["side"] and any(x["t0"] < g["t1"] and g["t0"] < x["t1"] for g in grp):
                    grp.append(x)
                    seen.add(id(x))
                    more = True
        if len({g["bot"] for g in grp}) >= 2:
            out.append({"side": r["side"], "t0": min(g["t0"] for g in grp), "t1": max(g["t1"] for g in grp),
                        "trades": [(g["bot"], g["sym"], round(g["pnl"], 2)) for g in sorted(grp, key=lambda g: g["t0"])],
                        "sum": round(sum(g["pnl"] for g in grp), 2)})
    return out


def write(path: str, rows: list) -> None:
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def payoff(rows: list) -> dict:
    w = [t["pct"] for t in rows if t["pnl"] > 0]
    lo = [t["pct"] for t in rows if t["pnl"] <= 0]
    aw = float(np.mean(w)) if w else float("nan")
    al = float(np.mean(lo)) if lo else float("nan")
    return {"n": len(rows), "wins": len(w), "losses": len(lo), "win_rate": round(len(w) / max(1, len(rows)), 3),
            "avg_win_pct": round(aw, 2), "avg_loss_pct": round(al, 2),
            "breakeven_win_rate": round(-al / (aw - al), 3) if w and lo else None,
            "pnl": round(sum(t["pnl"] for t in rows), 2)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--m1", action="append", default=[])
    ap.add_argument("--out", required=True)
    ap.add_argument("--since", type=int, default=1792932000000, help="overlaps from (UTC ms); default 10-25 21:40 KST")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    live, paper = live_trades(a.raw), paper_trades(a.raw)
    # the friend bot's two entries of 10-26 were a small test size (about $20): left out of the payoff numbers
    real = [t for t in live if not (t["bot"] == "wooxpro2" and abs(t["pnl"]) < 0.2)]
    write(os.path.join(a.out, "trades.csv"), [{k: (round(v, 6) if isinstance(v, float) else v) for k, v in t.items()}
                                              for t in live])
    pr = pairs(live, paper)
    write(os.path.join(a.out, "pairs.csv"), pr)
    B = Bars(a.m1)
    ctx = [c for c in ([context(B, "실거래", t) for t in live] + [context(B, "페이퍼", p) for p in paper]) if c]
    write(os.path.join(a.out, "context.csv"), ctx)
    summ = {"payoff": {b: payoff([t for t in real if t["bot"] == b]) for b in sorted({t["bot"] for t in real})},
            "payoff_all": payoff(real), "overlaps": overlaps(live, a.since),
            "pairs": {b: {"n": len([p for p in pr if p["bot"] == b]),
                          "live_sum_pct": round(sum(p["live_pct"] for p in pr if p["bot"] == b), 1),
                          "paper_sum_pct": round(sum(p["paper_pct"] for p in pr if p["bot"] == b), 1)}
                      for b in sorted({p["bot"] for p in pr})}}
    json.dump(summ, open(os.path.join(a.out, "summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(summ["payoff_all"], ensure_ascii=False), len(live), "live trades,", len(ctx), "with bars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
