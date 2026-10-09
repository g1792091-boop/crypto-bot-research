"""The demo lab bot's service loop: one tick after every 15m close (+25 s), then accounts, judgment, snapshots,
the hourly ranking, and Telegram (CONTRACT sections 4-5). Never places an order."""
from __future__ import annotations

import os
import time
import traceback
import urllib.request
from typing import Optional

from . import accounts as A
from . import costs as CO
from . import data as D
from . import engine as EN
from . import judge as J
from . import rank as RK
from . import report as RP
from . import store as ST
from . import views as VW

SETTLE_S = 25
RANK_EVERY_MS = 60 * 60 * 1000
DAY_MS = 86400 * 1000
M15 = 15 * 60 * 1000
DEADMAN_TIMEOUT_S = 10


def ping_deadman(url: str, timeout: float = DEADMAN_TIMEOUT_S, opener=None) -> Optional[str]:
    """GET the healthchecks.io ping URL; None when it answered 2xx, else a short error (the URL is never echoed)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "demobot"})
        with (opener or urllib.request.urlopen)(req, timeout=timeout) as r:
            code = getattr(r, "status", 200)
        return None if 200 <= int(code) < 300 else f"HTTP {code}"
    except Exception as exc:
        return type(exc).__name__


def log(*a) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def _outbox(conn):
    try:
        from . import notify as N
    except Exception:          # notify not installed yet: run without Telegram
        return None, None
    try:
        return N, N.Outbox(conn)
    except Exception as exc:
        log("telegram outbox unavailable:", type(exc).__name__)
        return N, None


class Runner:
    def __init__(self, conn, market: Optional[D.Market] = None, snap: Optional[str] = None, clock_ms=None,
                 token: Optional[str] = None, chat: Optional[str] = None, logf=log, rank_inline: bool = False):
        self.conn = conn
        self.eng = EN.Engine(conn, market=market, clock_ms=clock_ms, log=logf)
        self.snap = snap or ST.default_snap()
        self.clock_ms = self.eng.clock_ms
        self.log = logf
        self.token = token if token is not None else os.environ.get("DEMOBOT_TG_TOKEN", "")
        self.chat = chat if chat is not None else os.environ.get("DEMOBOT_TG_CHAT", "")
        self.N, self.outbox = _outbox(conn)
        self.rank_inline = rank_inline          # the service leaves the ranking to demobot-rank.timer
        VW.ensure(conn)
        self.tg_offset = ST.get_meta(conn, "tg_offset", 0) or 0
        self.last_rank_ms = ST.get_meta(conn, "last_rank_ms", 0)
        self.last_funding_ms = 0
        self.deadman_url = os.environ.get("DEMOBOT_DEADMAN_URL", "").strip()
        self.deadman = dict(configured=bool(self.deadman_url), last_ok_ms=ST.get_meta(conn, "deadman_ok_ms"),
                            last_error=None)

    def start(self) -> None:
        self.eng.load()
        if self.outbox is not None:
            self._queue("start", {"phase": "live", "accounts": len(A.current_accounts()), "live_start_ms": self.eng.live_start})
            self._flush()

    def _queue(self, kind: str, payload: dict) -> None:
        if self.outbox is None:
            return
        try:
            self.outbox.queue(kind, payload)
        except Exception as exc:
            self.log("telegram queue failed:", kind, type(exc).__name__)

    def tick(self) -> dict:
        t0 = time.time()
        errors = []
        info = {}
        try:
            info = self.eng.tick()
        except Exception as exc:
            errors.append(f"tick: {type(exc).__name__}: {exc}")
            self.log(traceback.format_exc())
        now = self.clock_ms()
        if info.get("new_bars") and any(info["new_bars"].values()):
            self._depth(now)
            self._ping(now)
        if now - self.last_funding_ms > 3600 * 1000:
            try:
                self.eng.refresh_funding()
                self.last_funding_ms = now
            except Exception as exc:
                errors.append(f"funding: {type(exc).__name__}")
        res = judge = None
        try:
            res = A.run_all(self.eng, now, log=self.log)
            judge = J.judge_all(res, now, conn=self.conn)
        except Exception as exc:
            errors.append(f"accounts: {type(exc).__name__}: {exc}")
            self.log(traceback.format_exc())
        if self.rank_inline and (now - self.last_rank_ms >= RANK_EVERY_MS or
                                 not os.path.exists(os.path.join(self.snap, "rank_meta.json"))):
            try:
                RK.write_all(self.eng, self.snap, now, log=self.log)
                self.last_rank_ms = now
                ST.set_meta(self.conn, "last_rank_ms", now)
            except Exception as exc:
                errors.append(f"rank: {type(exc).__name__}: {exc}")
                self.log(traceback.format_exc())
        info["errors"] = errors
        info["seconds_total"] = round(time.time() - t0, 1)
        info["deadman"] = dict(self.deadman)
        if res is not None:
            try:
                RP.write_snapshots(self.eng, res, judge, self.snap, now, info,
                                   self.outbox.state() if self.outbox is not None else None)
            except Exception as exc:
                errors.append(f"snapshots: {type(exc).__name__}: {exc}")
                self.log(traceback.format_exc())
            self._telegram(res, judge, now)
        try:
            self._views(now)
        except Exception as exc:
            errors.append(f"views: {type(exc).__name__}: {exc}")
            self.log(traceback.format_exc())
        if errors:
            self._queue("warn", {"what": "error", "detail_ko": "; ".join(errors)[:500]})
        if self.eng.issues:
            self._queue("warn", {"what": "data", "detail_ko": "; ".join(self.eng.issues)[:500]})
        self._flush()
        self._telegram_log(now)
        self.log("tick", info)
        return info

    def _telegram_log(self, now: int) -> None:
        """snap/telegram.json: the messages as sent (CONTRACT 8.11)."""
        if self.outbox is None:
            return
        try:
            rows = self.conn.execute("SELECT id, ts_ms, kind, text, sent_ms, error FROM outbox ORDER BY id DESC "
                                     "LIMIT 300").fetchall()
            items = [dict(id=i, ts_ms=t, kind=k, text=x or "",
                          status=("sent" if s else ("error" if e else "queued"))) for i, t, k, x, s, e in rows]
            ST.write_json(os.path.join(self.snap, "telegram.json"), dict(generated_ms=now, items=items))
        except Exception as exc:
            self.log("telegram log failed:", type(exc).__name__)

    def _depth(self, now: int) -> None:
        """The order books of the bar that just opened (CONTRACT 8.3); a failure only skips this tick's record."""
        last = self.eng.last_bar("15m")
        if last is None or now - (last + M15) > 10 * 60 * 1000:      # a catch-up tick: the book is not the entry's
            return
        try:
            rows = CO.fetch_rows(self.eng.market, last + M15, log=self.log)
            if rows:
                ST.put_depth(self.conn, rows)
        except Exception as exc:
            self.log("depth record failed:", type(exc).__name__)

    def _ping(self, now: int) -> None:
        if not self.deadman_url:
            return
        err = ping_deadman(self.deadman_url)
        self.deadman["last_error"] = err
        if err is None:
            self.deadman["last_ok_ms"] = now
            ST.set_meta(self.conn, "deadman_ok_ms", now)
        else:
            self.log("dead-man ping failed:", err)

    def _telegram(self, res, judge, now) -> None:
        if self.outbox is None:
            return
        try:
            last = self.eng.last_bar("15m") or now
            tick, switches, mark = RP.tick_events(self.eng, res, now, last)
            if tick:
                self._queue("tick", tick)
            for s in switches:
                self._queue("switch", s)
            ST.put_notified(self.conn, mark)
            for aid, L, start in judge.get("confirm_started", []):
                row = next(r for r in judge["rows"] if r["id"] == aid and r["L"] == L)
                self._queue("pass", {"account": aid, "name": row["name"], "L": L, "checks": row["ours"]["checks"],
                                     "confirm_end_ms": start + J.CONFIRM_MIN_MS})
            for p in judge.get("confirm_decided", []):
                w = p["result"]
                self._queue("confirm_done", {"account": p["acct"], "name": A.by_id(p["acct"]).name, "L": p["L"],
                                             "result": p["status"], "start_ms": p["start_ms"],
                                             "decided_ms": p["decided_ms"],
                                             "window": {k: w.get(k) for k in ("n", "mean_R", "pnl", "pnl_pct",
                                                                              "max_dd")},
                                             "why_ko": w.get("why_ko", "")})
            day = time.strftime("%Y-%m-%d", time.gmtime((now + 9 * 3600 * 1000) / 1000))
            kst_hour = time.gmtime((now + 9 * 3600 * 1000) / 1000).tm_hour
            if kst_hour >= 9 and ST.get_meta(self.conn, "daily_sent") != day:
                home = _read_json(os.path.join(self.snap, "home.json")) or {}
                trades24 = sum(1 for a in A.current_accounts() for sim in res[a.id]["lines"].values()
                               for t in sim["trades"] if t["status"] == "closed" and t["exit_ms"] and
                               t["exit_ms"] >= now - DAY_MS)
                self._queue("daily", {"day": day, "live_days": home.get("live_days"), "best": home.get("best", []),
                                      "worst": home.get("worst", []), "by_kind": home.get("by_kind", []),
                                      "passed": len(judge.get("passed", [])), "leaders": home.get("leaders", []),
                                      "trades_24h": trades24,
                                      "confirming": home.get("totals", {}).get("confirming", 0),
                                      "candidates": home.get("totals", {}).get("candidates", 0),
                                      "costs": home.get("costs_now") or {"median_entry_bps": None,
                                                                         "assumed_bps": CO.ASSUMED_BPS},
                                      "regime": [{"coin": x["coin"], "trend": x["trend"], "vol": x["vol"]}
                                                 for x in home.get("regime_now", [])]})
                ST.set_meta(self.conn, "daily_sent", day)
            reviews = ST.get_meta(self.conn, "reviews", []) or []
            if reviews and kst_hour >= 9 and ST.get_meta(self.conn, "weekly_sent") != reviews[0].get("start_ms"):
                self._queue("weekly", {"week": reviews[0]})
                ST.set_meta(self.conn, "weekly_sent", reviews[0].get("start_ms"))
        except Exception as exc:
            self.log("telegram events failed:", type(exc).__name__, exc)

    def _views(self, now: int) -> None:
        """views.json and the result message of each view that finished since the last tick."""
        snap, newly = VW.snapshot(self.conn, self.eng.b15, now)
        ST.write_json(os.path.join(self.snap, "views.json"), snap)
        for v in newly:
            f = v["follow"]
            self._queue("view_done", {"id": v["id"], "coin": v["coin"], "side": v["side"], "dir": v["dir"],
                                      "reached": bool(v["reached"]), "touch": f["touch"], "confirm": f["confirm"],
                                      "summary_ko": snap["summary"]["verdict_ko"]})
        VW.mark_done(self.conn, [v["id"] for v in newly])

    def _price(self, coin: str):
        b = self.eng.b15.get(coin)
        return float(b["c"][-1]) if b is not None and len(b["c"]) else None

    def poll_once(self, timeout: float) -> int:
        """Read Telegram commands (view log) once; returns the number of messages handled."""
        if self.N is None or not (self.token and self.chat):
            time.sleep(max(1.0, timeout))
            return 0
        t0 = time.time()
        off, items = self.N.poll_commands(self.token, self.chat, self.tg_offset, timeout=int(max(1, timeout)))
        if off != self.tg_offset:
            self.tg_offset = off
            ST.set_meta(self.conn, "tg_offset", off)
        for it in items:
            try:
                for kind, payload in VW.handle(self.conn, it, self.clock_ms(), price_of=self._price):
                    self._queue(kind, payload)
            except Exception as exc:
                self.log("view command failed:", type(exc).__name__, exc)
        if items:
            self._flush()
        elif time.time() - t0 < 2:
            time.sleep(5)              # an error answers at once: do not spin
        return len(items)

    def _flush(self) -> None:
        if self.outbox is None or not (self.token and self.chat):
            return
        try:
            self.outbox.flush(self.token, self.chat)
        except Exception as exc:
            self.log("telegram flush failed:", type(exc).__name__)

    def loop(self) -> None:
        self.start()
        while True:
            now_s = time.time()
            nxt = (int(now_s) // 900 + 1) * 900 + SETTLE_S
            while time.time() < nxt - 1:     # between ticks: answer view-log commands within seconds
                try:
                    self.poll_once(min(25.0, nxt - time.time()))
                except Exception as exc:
                    self.log("poll failed:", type(exc).__name__)
                    time.sleep(5)
            self.tick()


def _read_json(path):
    import json
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None
