"""실거래 › 바이비트 봇 › 친구 추세판 (owners 10-29): the friend's trend indicator per coin, as the two bots that use it saw it.

    GET /api/v4/livebots/ftrend

    30분  the 바이비트 봇 (paperbot/mixchop.py, docs/mixbybit-ko.md) at its last 30-minute close: its state file's ``board``
          (mixchop.board_row): the trend of the bar and its four votes (하늘·보라 선 · EMA RSI · 찹존 · 슈퍼트렌드; two
          or more the same way = that trend, two or more sideways or two against two = 진입 금지), the OBV pane's colour
          (green / red, light / dark, the light -> dark turn the OBV rule enters on), the Stoch RSI pane (K, D, its state,
          a golden / dead ● on the bar) and each rule's answer with the bot's reason. The live bot's file, else its paper
          twin's (said so).
    1시간 the 레인지 봇 (paperbot/rangebot.py, docs/range-bot-ko.md) on its last closed hour: its ``range`` snapshot's
          ``friend`` (dash/more/liverange.supertrend_of), once its config has ``friend_tf``.

Read-only: the bots' own files, never a computation of our own (what is shown is what the bots decided on). HONESTY: a bot
that is off, stopped or has not written its row yet says so; an old row says how old; never a guessed vote.
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

from . import livebots as L

MIN = 60_000
TREND_KO = {1: "상승", -1: "하락", 0: "진입 금지"}
VOTE_KO = {1: "상승", -1: "하락", 0: "횡보"}
VOTES = (("line", "하늘·보라 선"), ("ema", "EMA RSI"), ("chop", "찹존"), ("st", "슈퍼트렌드"))
RULE_KO = {"obv": "OBV 진한색", "srsi": "스톡RSI 50선"}
STALE_30M_MS = 35 * MIN                 # the bot writes at every 30-minute close
STALE_1H_MS = 70 * MIN                  # the 레인지 봇 reads its hour once it closed
RULES_KO = [
    "추세: 네 표(하늘·보라 선 · EMA RSI · 찹존 · 슈퍼트렌드) 중 같은 쪽이 2표 이상이고 반대쪽보다 많으면 그 추세 · "
    "횡보가 2표 이상이거나 2 대 2면 진입 금지",
    "OBV 진한색(바이비트 봇): 추세 쪽 색(상승 초록 · 하락 빨강)의 히스토그램이 연한색에서 진한색으로 바뀌는 봉에 들어가요",
    "스톡RSI 50선(바이비트 봇): 50선 아래 골든 ●이면 롱, 50선 위 데드 ●이면 숏 · 추세와 같은 쪽일 때만",
    "1시간 추세(레인지 봇): 신호와 반대이거나 진입 금지면 그 신호를 막아요",
]


def _i(x: Any) -> Optional[int]:
    return L._i(x)


def _f(x: Any) -> Optional[float]:
    return L._f(x)


def votes_out(v: Any) -> list:
    """[{id, ko, side, side_ko}] in the indicator's order (an unread vote: side None, 모름)."""
    v = v if isinstance(v, dict) else {}
    return [{"id": k, "ko": ko, "side": _i(v.get(k)), "side_ko": VOTE_KO.get(_i(v.get(k)), "모름")} for k, ko in VOTES]


def obv_out(r: dict) -> Optional[dict]:
    cs, dark, turn = _i(r.get("obv_cs")), r.get("obv_dark"), _i(r.get("turn"))
    if cs is None:
        return None
    colour = {1: "초록", -1: "빨강", 0: "회색"}.get(cs, "모름")
    shade = "" if cs == 0 else ("진한 " if dark else "연한 ")
    return {"cs": cs, "dark": bool(dark), "turn": turn or 0, "ko": f"{shade}{colour}",
            "turn_ko": {1: "연한 초록 → 진한 초록 (롱 쪽)", -1: "연한 빨강 → 진한 빨강 (숏 쪽)"}.get(turn or 0)}


def stoch_out(r: dict) -> Optional[dict]:
    k, d = _f(r.get("k")), _f(r.get("d"))
    if k is None and d is None and r.get("xs") is None:
        return None
    xs, cross = _i(r.get("xs")), r.get("cross") or ""
    return {"k": k, "d": d, "xs": xs, "cross": cross, "ko": {1: "K가 D 위", -1: "K가 D 아래", 0: "아직 상태 없음"}.get(xs, "모름"),
            "cross_ko": {"gold": "골든 ●", "dead": "데드 ●"}.get(cross),
            "side50_ko": None if k is None else ("50선 아래" if k < 50 else "50선 위")}


def m30_row(r: Any, now: int) -> dict:
    """One coin's 30-minute part from the 바이비트 봇's board row."""
    if not isinstance(r, dict):
        return {"state": "none", "ko": "이 코인 줄이 아직 없어요 (다음 30분봉 마감 뒤)"}
    t = _i(r.get("trend"))
    close_ms = _i(r.get("close_ms"))
    rules = {}
    for k, x in (r.get("rules") or {}).items():
        if isinstance(x, dict):
            rules[k] = {"side": _i(x.get("side")) or 0, "why": str(x.get("why") or ""), "ko": RULE_KO.get(k, k)}
    unread = t is None and any(x["why"] for x in rules.values())
    return {"state": "error" if unread else "ok" if t is not None else "none", "close_ms": close_ms,
            "age_ms": now - close_ms if close_ms is not None else None,
            "trend": t, "trend_ko": TREND_KO.get(t, "모름") if t is not None else None, "votes": votes_out(r.get("votes")),
            "ema_rsi": _f(r.get("ema_rsi")), "chop_zone": _i(r.get("chop_zone")), "close": _f(r.get("close")),
            "stop_pct": _f(r.get("stop_pct")), "liq_ok": r.get("liq_ok"), "obv": obv_out(r), "stoch": stoch_out(r),
            "rules": rules, "ko": next((x["why"] for x in rules.values() if x["why"]), "") if unread else ""}


def board_of(now: int, mp: Optional[dict] = None) -> tuple:
    """(source, {symbol: row}, coins in the config's order): the 바이비트 봇's live state, else its paper twin's."""
    from . import livemix as X
    prof = X.PROFILES["bybit"]
    mp = mp or X.paths(bot="bybit")
    coins: list = []
    tried = []
    for bid in ("live", "paper"):
        bp = mp[bid]
        conf = X.read_config(bp["config"], bp["repo_config"], prof)
        cfg = conf.get("cfg")
        if cfg is not None and not coins:
            coins = [c.symbol for c in cfg.coins]
        sp, _lp = X.files_of(bid, bp, conf)
        st = X.read_state(sp)
        tried.append((bid, st))
        if st.get("state") != "ok":
            continue
        d = st.get("d") or {}
        b = d.get("board")
        if not isinstance(b, dict) or not b:
            continue
        seen = _i(d.get("saved_ms")) or st.get("mtime_ms")
        last = _i(d.get("last_close_ms"))
        src = {"state": "ok", "bot": bid, "bot_ko": "실거래 봇" if bid == "live" else "모의 봇 (실거래 봇 기록이 없어 모의 쌍둥이 것)",
               "path": sp, "saved_ms": seen, "last_close_ms": last,
               "stale": seen is None or now - int(seen) > STALE_30M_MS, "unit": prof.bots[0 if bid == "live" else 1][2]}
        return src, b, coins
    states = {bid: st.get("state") for bid, st in tried}
    if all(s == "missing" for s in states.values()):
        ko = "바이비트 봇이 아직 꺼져 있어요 (상태 파일 없음) · 켜고 30분봉이 한 번 끝나면 여기 보여요"
        state = "off"
    elif any(s == "error" for s in states.values()):
        ko = "바이비트 봇 상태 파일을 읽지 못했어요"
        state = "error"
    else:
        ko = "바이비트 봇이 아직 이 표를 쓰지 않았어요 · 다음 30분봉 마감 뒤에 보여요 (새 코드로 다시 켠 뒤부터)"
        state = "none"
    return {"state": state, "ko": ko}, {}, coins


def h1_of(p: dict, now: int) -> tuple:
    """(source, {symbol: item}, symbols): the 레인지 봇's last hour (liverange.supertrend_of's ``friend``)."""
    from . import liverange as RG
    _b, path, _execs, _bots = RG.locate(p, now)
    snap = RG.snapshot(path, now) if path else L._missing("-", L.MISSING_KO)
    if snap.get("state") != "ok":
        return {"state": "off" if snap.get("state") == "missing" else "error",
                "ko": "레인지 봇 기록이 없어요" if snap.get("state") == "missing" else "레인지 봇 기록을 읽지 못했어요",
                "path": path}, {}, []
    sv = RG.supertrend_of(snap, now)
    if not sv or not sv.get("friend"):
        return {"state": "none", "path": path,
                "ko": "레인지 봇이 아직 친구 추세지표를 쓰지 않아요 (설정에 friend_tf 1h를 넣고 다시 켠 뒤부터 · docs/range-bot-ko.md 3장 E)"}, {}, []
    at = _i(sv.get("at"))
    src = {"state": "ok", "path": path, "at": at, "age_ms": sv.get("age_ms"),
           "stale": at is None or now - at > STALE_1H_MS}
    return src, {x["symbol"]: x for x in sv["friend"]}, [x["symbol"] for x in sv["friend"]]


def h1_row(x: Any) -> dict:
    if not isinstance(x, dict):
        return {"state": "none", "ko": "레인지 봇이 보는 코인이 아니에요"}
    if x.get("side") is None:
        return {"state": "error", "ko": x.get("error_ko") or "못 읽음"}
    return {"state": "ok", "trend": x["side"], "trend_ko": x.get("ko"), "votes": votes_out(x.get("votes")),
            "ema_rsi": x.get("ema_rsi"), "chop_zone": x.get("chop_zone")}


def build(p: Optional[dict] = None, now_ms: Optional[int] = None, mp: Optional[dict] = None) -> dict:
    """GET /api/v4/livebots/ftrend (module docstring)."""
    p = p or L.paths()
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    try:
        s30, b30, coins30 = board_of(now, mp)
    except Exception as exc:  # noqa: BLE001  (its own failure is said, never the page's)
        s30, b30, coins30 = {"state": "error", "ko": "바이비트 봇 기록을 읽지 못했어요", "reason": f"{type(exc).__name__}: {exc}"[:300]}, {}, []
    try:
        s1h, b1h, coins1h = h1_of(p, now)
    except Exception as exc:  # noqa: BLE001
        s1h, b1h, coins1h = {"state": "error", "ko": "레인지 봇 기록을 읽지 못했어요", "reason": f"{type(exc).__name__}: {exc}"[:300]}, {}, []
    order = list(dict.fromkeys([*coins30, *b30, *coins1h]))
    from .liverange import coin_ko
    rows = [{"symbol": sym, "coin": coin_ko(sym), "in30": not coins30 or sym in coins30, "m30": m30_row(b30.get(sym), now),
             "h1": h1_row(b1h.get(sym)) if s1h.get("state") == "ok" else {"state": "none"}} for sym in order]
    agree = [r["symbol"] for r in rows if r["m30"].get("trend") and r["h1"].get("trend") and r["m30"]["trend"] == r["h1"]["trend"]]
    return {"now_ms": now, "m30": s30, "h1": s1h, "coins": rows, "agree": agree, "rules_ko": RULES_KO}


def register(app, ctx) -> dict:
    from ..app import json_finite

    @app.get("/api/v4/livebots/ftrend")
    def get_livebots_ftrend():
        """실거래 › 바이비트 봇 › 친구 추세판: each coin's friend trend (30-minute: the 바이비트 봇's last close, with its OBV
        and Stoch RSI panes; 1-hour: the 레인지 봇's last hour), read from the bots' own files (read-only, 5 s cache)."""
        p = L.paths()
        return L._cached("ftrend:" + json.dumps(p, sort_keys=True), lambda: json_finite(build(p)))

    return {"routes": ["/api/v4/livebots/ftrend"]}
