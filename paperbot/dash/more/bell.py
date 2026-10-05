"""결재함 종 (머리글, v4 wave 3): how many proposals wait for the owners' approval. Read-only.

    GET /api/v4/bell

The same rule as the rooms' side panel (rooms-side.js) and /api/rooms ``open_proposals``: a proposal with status
``awaiting_owner`` whose owners' decision is not in yet (``effective_status`` still ``awaiting_owner``; a decided one
that the tick has not applied yet no longer waits for them). The answer is small: the count, per room, and the newest
five (id, room, strategy name). Approving stays where it is (the room's side panel, with its confirm step): the bell
only counts and links. Cached 30 s (the page asks every 60 s at most, and never while hidden).
"""
from __future__ import annotations

import threading
import time

TTL_S = 30.0
ITEMS_MAX = 5


def waiting(rooms) -> dict:
    """{n, rooms: [{room_id, title, n}], items: [...]} of the proposals that wait for the owners."""
    props = [p for p in rooms.proposals(status="awaiting_owner", limit=500)
             if p.get("effective_status") == "awaiting_owner"]
    per: dict = {}
    for p in props:
        rid = p.get("room_id") or ""
        per[rid] = per.get(rid, 0) + 1
    specs = getattr(rooms, "specs", {}) or {}
    title = lambda rid: (specs.get(rid) or {}).get("title") or rid      # noqa: E731
    props.sort(key=lambda p: (int(p.get("ts") or 0), int(p.get("id") or 0)), reverse=True)
    return {"n": len(props),
            "rooms": [{"room_id": rid, "title": title(rid), "n": n} for rid, n in sorted(per.items(), key=lambda kv: -kv[1])],
            "items": [{"id": int(p["id"]), "room_id": p.get("room_id"), "room_title": title(p.get("room_id") or ""),
                       "strategy": p.get("strategy"), "strategy_ko": p.get("strategy_ko"), "ts": p.get("ts")}
                      for p in props[:ITEMS_MAX]]}


def register(app, ctx) -> dict:
    rooms = ctx.rooms
    cache: dict = {}
    lock = threading.Lock()

    @app.get("/api/v4/bell")
    def get_bell():
        """Proposals waiting for the owners' approval (count, per room, newest five); 30 s cache."""
        hit = cache.get("v")
        if hit and time.time() - hit[0] < TTL_S:
            return hit[1]
        with lock:
            hit = cache.get("v")
            if hit and time.time() - hit[0] < TTL_S:
                return hit[1]
            try:
                v = {"ready": True, **waiting(rooms)}
            except Exception as exc:  # noqa: BLE001  (agents3.db missing or busy: the bell shows nothing, never a guess)
                v = {"ready": False, "n": 0, "rooms": [], "items": [], "why": type(exc).__name__}
            v["ts"] = int(time.time() * 1000)
            cache["v"] = (time.time(), v)
        return v

    return {"routes": ["/api/v4/bell"], "cache": cache}
