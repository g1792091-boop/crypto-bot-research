"""The demo lab bot's service loop: one tick after every 15m close (+25 s), then accounts, judgment, snapshots,
the hourly ranking, and Telegram (CONTRACT sections 4-5). Never places an order."""
from __future__ import annotations

import os
import time
import traceback
from typing import Optional

from . import accounts as A
from . import data as D
from . import engine as EN
from . import judge as J
from . import rank as RK
from . import report as RP
from . import store as ST

SETTLE_S = 25
RANK_EVERY_MS = 60 * 60 * 1000
DAY_MS = 86400 * 1000


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
        self.last_rank_ms = ST.get_meta(conn, "last_rank_ms", 0)
        self.last_funding_ms = 0

    def start(self) -> None:
        self.eng.load()
        if self.outbox is not None:
            self._queue("start", {"phase": "live", "accounts": len(A.ACCOUNTS), "live_start_ms": self.eng.live_start})
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
        if now - self.last_funding_ms > 3600 * 1000:
            try:
                self.eng.refresh_funding()
                self.last_funding_ms = now
            except Exception as exc:
                errors.append(f"funding: {type(exc).__name__}")
        res = judge = None
        try:
            res = A.run_all(self.eng, now)
            judge = J.judge_all(res, now)
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
        if res is not None:
            try:
                RP.write_snapshots(self.eng, res, judge, self.snap, now, info,
                                   self.outbox.state() if self.outbox is not None else None)
            except Exception as exc:
                errors.append(f"snapshots: {type(exc).__name__}: {exc}")
                self.log(traceback.format_exc())
            self._telegram(res, judge, now)
        if errors:
            self._queue("warn", {"what": "error", "detail_ko": "; ".join(errors)[:500]})
        if self.eng.issues:
            self._queue("warn", {"what": "data", "detail_ko": "; ".join(self.eng.issues)[:500]})
        self._flush()
        self.log("tick", info)
        return info

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
            sent_pass = set(ST.get_meta(self.conn, "pass_sent", []))
            for aid, L in judge.get("passed", []):
                k = f"{aid}|{L}"
                if k not in sent_pass:
                    row = next(r for r in judge["rows"] if r["id"] == aid and r["L"] == L)
                    self._queue("pass", {"account": aid, "name": row["name"], "L": L, "checks": row["ours"]["checks"]})
                    sent_pass.add(k)
            ST.set_meta(self.conn, "pass_sent", sorted(sent_pass))
            day = time.strftime("%Y-%m-%d", time.gmtime((now + 9 * 3600 * 1000) / 1000))
            kst_hour = time.gmtime((now + 9 * 3600 * 1000) / 1000).tm_hour
            if kst_hour >= 9 and ST.get_meta(self.conn, "daily_sent") != day:
                home = _read_json(os.path.join(self.snap, "home.json")) or {}
                trades24 = sum(1 for a in A.ACCOUNTS for sim in res[a.id]["lines"].values()
                               for t in sim["trades"] if t["status"] == "closed" and t["exit_ms"] and
                               t["exit_ms"] >= now - DAY_MS)
                self._queue("daily", {"day": day, "live_days": home.get("live_days"), "best": home.get("best", []),
                                      "worst": home.get("worst", []), "by_kind": home.get("by_kind", []),
                                      "passed": len(judge.get("passed", [])), "leaders": home.get("leaders", []),
                                      "trades_24h": trades24})
                ST.set_meta(self.conn, "daily_sent", day)
        except Exception as exc:
            self.log("telegram events failed:", type(exc).__name__, exc)

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
            time.sleep(max(1.0, nxt - time.time()))
            self.tick()


def _read_json(path):
    import json
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None
