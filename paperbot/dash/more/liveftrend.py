"""실거래 › 바이비트 봇 › 친구 추세판 (owners 10-29): the friend's trend indicator per coin, as the bots that use it saw it.

    GET /api/v4/livebots/ftrend

Owners 10-31 night: the three mix bots (바이비트 봇, 친구 15분 봇, 레인지 봇) share one trend, the '추세 바' 종합
(paperbot/friendtrend.py part 9: six rows, 상승 초록 / 하락 빨강 / 횡보 노랑 = 진입 금지); owners 10-31, last: all three
enter on 15-minute bars and read the trend bar on the 30-minute bar only (their configs' ``trend_tf``: the rows' ``trend_tf``
"30분" next to ``tf`` "15분", each source's ``trend_tf_ko``; the board keys ``m30`` / ``f30`` / ``r15`` are only names).
Each board row carries it
(``bar``: the six rows with their words, ``bar_n`` [상승, 하락, 횡보], ``bar_score`` the 3개 점수) and rule "h0x"'s
histogram (``x0`` its 0 cross on the bar, ``h6`` its value). Each bot's board says its name (its config's ``name``) and
bar (``tf_ko``); the 레인지 봇's own board (``r15``, the coin's ``rg``) once its state file has one. Once the 레인지 봇 trades
WOO X Pro by itself (livebots.range_moved) the old 레인지 봇 paper's 1-hour and ROC / 추세 3개 reads (``h1``, ``roc``) leave
the board (None).

    30분  the 바이비트 봇 (paperbot/mixchop.py, docs/mixbybit-ko.md) at its last 30-minute close: its state file's ``board``
          (mixchop.board_row): the trend of the bar and its four votes (하늘·보라 선 · EMA RSI · 찹존 · 슈퍼트렌드; two
          or more the same way = that trend, two or more sideways or two against two = 진입 금지), the OBV pane's colour
          (green / red, light / dark, the light -> dark turn the OBV rule enters on), its 50 line's value (``obv50``, the
          rule of 10-30), the Stoch RSI pane (K, D, its state, a golden / dead ● on the bar; the rules of 10-29 only) and
          each rule's answer with the bot's reason. The live bot's file, else its paper
          twin's (said so).
    1시간 the 레인지 봇 (paperbot/rangebot.py, docs/range-bot-ko.md) on its last closed hour: its ``range`` snapshot's
          ``friend`` (dash/more/liverange.supertrend_of), once its config has ``friend_tf``.
    owners 10-30: the friend bot (WOO X Pro 2, the same program; 10-31 evening: 친구 30분 봇, rules "obvac" and "ema3" on 30m
          bars, the four votes again):
          its own board row of its last close
          (``f30``, its coins); the 레인지 봇's ROC entry (``roc``): each coin's ROC read at its last 30-minute close
          (liverange.supertrend_of ``roc``).

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
# the trend bar's 종합 (owners 10-31 night): its words and colour
BAR_TREND_KO = {1: "상승", -1: "하락", 0: "횡보"}
BAR_COLOUR_KO = {1: "초록", -1: "빨강", 0: "노랑"}
X0_KO = {1: "0선 위로 돌파", -1: "0선 아래로 돌파", 0: "0선 돌파 없음"}
VOTE_KO = {1: "상승", -1: "하락", 0: "횡보"}
VOTES = (("line", "하늘·보라 선"), ("ema", "EMA RSI"), ("chop", "찹존"), ("st", "슈퍼트렌드"))
RULE_KO = {"obv": "OBV 진한색", "srsi": "스톡RSI 50선", "obv50": "OBV 50선", "roc50": "ROC 50선", "ema3": "추세 3개 일치",
           "obvac": "OBV 진한색 + AC", "h0x": "히스토그램 0선 돌파"}
# the boards of the mix bots: (the answer's key, the coin row's key, livemix profile)
BOARDS = (("m30", "m30", "bybit"), ("f30", "f30", "mix"), ("r15", "rg", "range"))
STALE_30M_MS = 35 * MIN                 # the bot writes at every 30-minute close
STALE_1H_MS = 70 * MIN                  # the 레인지 봇 reads its hour once it closed
RULES_KO = [
    "추세 바 종합(10-31 밤부터 세 봇 모두: 바이비트 봇 · 친구 15분 봇 · 레인지 봇): 여섯 줄(3개 점수 · 6종 평균 · "
    "하늘·보라 선 · EMA RSI · 슈퍼트렌드 · 4종 평균) 중 상승이 2줄 이상이면 상승(초록), 하락이 2줄 이상이면 하락(빨강) · "
    "횡보가 2줄 이상이거나 상승·하락이 둘 다 2줄 이상이면 횡보(노랑) = 진입 금지",
    "봉(10-31 마지막 결정부터 세 봇 모두): 진입 신호는 15분봉 · 추세 바 종합은 30분봉에서만 봐요 (15분봉 추세는 안 봐요)",
    "히스토그램 0선 돌파(친구 15분 봇 · 레인지 봇, 10-31 밤부터): 'ALL + OBV6 MACD' 히스토그램이 0선을 위로 돌파하면 롱, "
    "아래로 돌파하면 숏 · 추세 바 종합이 같은 쪽일 때만 (노랑이면 진입 안 함)",
    "OBV 진한색 + AC(바이비트 봇, 10-31 밤부터 추세 바 종합 쪽으로 · 마지막 결정부터 15분봉): 아래의 OBV 진한색 + AC와 같아요",
    "추세(10-31 저녁까지): 네 표(하늘·보라 선 · EMA RSI · 찹존 · 슈퍼트렌드) 중 같은 쪽이 2표 이상이고 반대쪽보다 많으면 그 추세 · "
    "횡보가 2표 이상이거나 2 대 2면 진입 금지",
    "OBV 진한색 + AC(바이비트 봇 · 친구 30분 봇, 10-31 저녁부터): OBV 히스토그램이 연한 초록→진한 초록인 봉에서 OBV MACD의 "
    "AC 막대가 플러스 양봉(0 위 · 앞 막대보다 커짐)이면 롱, 연한 빨강→진한 빨강이고 마이너스 음봉(0 아래 · 앞 막대보다 작아짐)이면 숏 · "
    "추세와 같은 쪽일 때만 · 플러스 음봉 · 마이너스 양봉과 그 밖의 막대는 진입 안 함 · 50선 조건 없음",
    "OBV 50선(바이비트 봇, 10-30 ~ 10-31): 진한 초록이 50 아래면 롱, 진한 빨강이 50 위면 숏 (10-31 저녁부터 안 씀)",
    "OBV 진한색 · 스톡RSI 50선: 10-29의 두 규칙 (10-30부터 바이비트 봇은 OBV 50선 하나)",
    "1시간 추세(레인지 봇): 신호와 반대이거나 진입 금지면 그 신호를 막아요",
    "친구 30분 봇(WOO X Pro 2, 10-31 저녁부터 30분봉 · 네 표 추세): OBV 진한색 + AC 하나 (위와 같음, 바이비트 봇과 같은 매매법) · "
    "10-31 밤부터 친구 15분 봇(15분봉 · 추세 바 종합 · 히스토그램 0선 돌파)",
    "ROC 30분(레인지 봇, 10-30): ROC 막대가 연한색→진한색이고 보라선이 롱은 50 아래·숏은 50 위이면 신호, 30분 추세가 같은 쪽일 때만 들어가요",
    "추세 3개 15분(레인지 봇, 10-31부터): EMA RSI · 하늘·보라 선 · 슈퍼트렌드가 모두 같은 쪽일 때 EMA RSI 막대가 연한색→진한색이면 신호",
    "레인지 봇(10-31 밤부터 WOO X Pro 계정에서 스스로 매매, 15분봉 진입 · 추세 30분봉): 추세 바 종합 + 히스토그램 0선 돌파 "
    "(친구 15분 봇과 같은 매매법)",
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


def bar_out(r: dict) -> Optional[dict]:
    """The trend bar of a board row (owners 10-31 night, trend "bar"): {"trend", "ko" (상승 / 하락 / 횡보), "colour_ko"
    (초록 / 빨강 / 노랑), "no_entry", "rows": [{id, ko, side, side_ko}] in the bar's order, "n": [상승, 하락, 횡보],
    "score" (the 3개 점수), "words" (friendtrend.bar_words)}; None for a row of another trend."""
    rows = r.get("bar")
    if r.get("trend_mode") != "bar" and not isinstance(rows, dict):
        return None
    from ... import friendtrend as FT
    from ... import mixchop as MC
    rows = rows if isinstance(rows, dict) else {}
    t = _i(r.get("trend"))
    n = r.get("bar_n") if isinstance(r.get("bar_n"), (list, tuple)) and len(r.get("bar_n")) == 3 else [None, None, None]
    score = _i(r.get("bar_score"))
    out_rows = []
    for k, ko in FT.BAR_ROWS:
        v = _i(rows.get(k))
        word = FT.ROW_KO[k].get(v, "모름") if v is not None else "모름"
        if k == "score" and score is not None:
            word = f"{word} ({'+' if score > 0 else ''}{score})"
        out_rows.append({"id": k, "ko": ko, "side": v, "side_ko": word})
    try:
        words = FT.bar_words(MC.bar_of(r))
    except Exception:  # noqa: BLE001  (an odd row: the rows alone)
        words = None
    return {"trend": t, "ko": BAR_TREND_KO.get(t, "모름") if t is not None else "모름",
            "colour_ko": BAR_COLOUR_KO.get(t) if t is not None else None, "no_entry": t == 0,
            "rows": out_rows, "n": [_i(x) for x in n], "score": score, "words": words}


def m30_row(r: Any, now: int, tf_ko: str = "30분") -> dict:
    """One coin's part of a mix bot's board row (``tf_ko``: its signal bar from its config, 15분 for all three since 10-31,
    last; the row's ``trend_tf`` the bar its trend was read on)."""
    if not isinstance(r, dict):
        return {"state": "none", "ko": f"이 코인 줄이 아직 없어요 (다음 {tf_ko}봉 마감 뒤)"}
    t = _i(r.get("trend"))
    close_ms = _i(r.get("close_ms"))
    rules = {}
    for k, x in (r.get("rules") or {}).items():
        if isinstance(x, dict):
            rules[k] = {"side": _i(x.get("side")) or 0, "why": str(x.get("why") or ""), "ko": RULE_KO.get(k, k)}
    unread = t is None and any(x["why"] for x in rules.values())
    bar = bar_out(r)
    x0 = _i(r.get("x0"))
    return {"state": "error" if unread else "ok" if t is not None else "none", "close_ms": close_ms,
            "age_ms": now - close_ms if close_ms is not None else None, "tf": r.get("tf") or None,
            "trend_tf": r.get("trend_tf") or None,
            "trend": t, "trend_ko": (bar["ko"] if bar else TREND_KO.get(t, "모름")) if t is not None else None,
            "trend_mode": r.get("trend_mode") or None, "bar": bar,
            "h0x": {"x0": x0 or 0, "h6": _f(r.get("h6")), "ko": X0_KO.get(x0 or 0)} if x0 is not None or r.get("h6") is not None else None,
            "votes": [] if bar else votes_out(r.get("votes")),
            "ema_rsi": _f(r.get("ema_rsi")), "chop_zone": _i(r.get("chop_zone")), "close": _f(r.get("close")),
            "stop_pct": _f(r.get("stop_pct")), "liq_ok": r.get("liq_ok"), "obv": obv_out(r), "stoch": stoch_out(r),
            "obv50": _f(r.get("obv50")), "ac": _f(r.get("ac")), "ac_col": _i(r.get("ac_col")),
            "rules": rules, "ko": next((x["why"] for x in rules.values() if x["why"]), "") if unread else ""}


def board_of(now: int, mp: Optional[dict] = None, bot: str = "bybit") -> tuple:
    """(source, {symbol: row}, coins in the config's order): the mix bot's (``bot``: "bybit" the 바이비트 봇, "mix" the
    friend bot, "range" the 레인지 봇) live state, else its paper twin's. The source names the bot (its live config's
    ``name``) and its bar (``tf_ko``); old after its bar + 5 minutes (livemix.stale_of)."""
    from . import livemix as X
    prof = X.PROFILES[bot]
    mp = mp or X.paths(bot=bot)
    coins: list = []
    tried = []
    name, tf_ko, ttf_ko, stale_ms = prof.name, "30분", None, STALE_30M_MS
    for bid in ("live", "paper"):
        bp = mp[bid]
        conf = X.read_config(bp["config"], bp["repo_config"], prof)
        cfg = conf.get("cfg")
        if cfg is not None and not coins:
            coins = [c.symbol for c in cfg.coins]
            name = getattr(cfg, "name", None) or prof.name   # the live config's (read first)
            tf_ko = X.tf_of(cfg)[1]
            ttf_ko = X.trend_tf_ko(cfg)                     # the trend's bar (owners 10-31, last: 30분 on 15분)
            stale_ms = X.stale_of(cfg)[0]
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
               "path": sp, "saved_ms": seen, "last_close_ms": last, "name_ko": name, "tf_ko": tf_ko, "trend_tf_ko": ttf_ko,
               "profile": bot,
               "stale": seen is None or now - int(seen) > stale_ms, "unit": prof.bots[0 if bid == "live" else 1][2]}
        return src, b, coins
    states = {bid: st.get("state") for bid, st in tried}
    if all(s == "missing" for s in states.values()):
        ko = f"{L.josa(name, '이', '가')} 아직 꺼져 있어요 (상태 파일 없음) · 켜고 {tf_ko}봉이 한 번 끝나면 여기 보여요"
        state = "off"
    elif any(s == "error" for s in states.values()):
        ko = f"{name} 상태 파일을 읽지 못했어요"
        state = "error"
    else:
        ko = f"{L.josa(name, '이', '가')} 아직 이 표를 쓰지 않았어요 · 다음 {tf_ko}봉 마감 뒤에 보여요 (새 코드로 다시 켠 뒤부터)"
        state = "none"
    return {"state": state, "ko": ko, "name_ko": name, "tf_ko": tf_ko, "trend_tf_ko": ttf_ko, "profile": bot}, {}, coins


def h1_of(p: dict, now: int) -> tuple:
    """(source, {symbol: item}, symbols, {symbol: ROC read}): the 레인지 봇's last hour (liverange.supertrend_of's
    ``friend``) and its ROC entry's reads (``roc``, owners 10-30)."""
    from . import liverange as RG
    _b, path, _execs, _bots = RG.locate(p, now)
    snap = RG.snapshot(path, now) if path else L._missing("-", L.MISSING_KO)
    if snap.get("state") != "ok":
        return {"state": "off" if snap.get("state") == "missing" else "error",
                "ko": "레인지 봇 기록이 없어요" if snap.get("state") == "missing" else "레인지 봇 기록을 읽지 못했어요",
                "path": path}, {}, [], {}
    sv = RG.supertrend_of(snap, now)
    roc = {x["symbol"]: {**x, "kind": "roc"} for x in (sv or {}).get("roc") or []}
    roc.update({x["symbol"]: {**x, "kind": "ema3"} for x in (sv or {}).get("ema3") or []})   # owners 10-31
    if not sv or not sv.get("friend"):
        return {"state": "none", "path": path,
                "ko": "레인지 봇이 아직 친구 추세지표를 쓰지 않아요 (설정에 friend_tf 1h를 넣고 다시 켠 뒤부터 · docs/range-bot-ko.md 3장 E)"}, {}, [], roc
    at = _i(sv.get("at"))
    src = {"state": "ok", "path": path, "at": at, "age_ms": sv.get("age_ms"),
           "stale": at is None or now - at > STALE_1H_MS}
    return src, {x["symbol"]: x for x in sv["friend"]}, [x["symbol"] for x in sv["friend"]], roc


def h1_row(x: Any) -> dict:
    if not isinstance(x, dict):
        return {"state": "none", "ko": "레인지 봇이 보는 코인이 아니에요"}
    if x.get("side") is None:
        return {"state": "error", "ko": x.get("error_ko") or "못 읽음"}
    return {"state": "ok", "trend": x["side"], "trend_ko": x.get("ko"), "votes": votes_out(x.get("votes")),
            "ema_rsi": x.get("ema_rsi"), "chop_zone": x.get("chop_zone")}


def roc_row(x: Any) -> Optional[dict]:
    """The 레인지 봇's ROC read of a coin (liverange.supertrend_of ``roc``), None when it has none."""
    if not isinstance(x, dict):
        return None
    if x.get("side") is None:
        return {"state": "error", "ko": x.get("error_ko") or "못 읽음"}
    return {"state": "ok", "side": x["side"], "ko": x.get("ko"), "osc": x.get("osc"), "osc_ko": x.get("osc_ko"), "at": x.get("at"),
            "kind": x.get("kind") or "roc"}


def build(p: Optional[dict] = None, now_ms: Optional[int] = None, mp: Optional[dict] = None,
          mpf: Optional[dict] = None, mpr: Optional[dict] = None) -> dict:
    """GET /api/v4/livebots/ftrend (module docstring); ``mp`` / ``mpf`` / ``mpr``: the 바이비트 봇's / the friend bot's /
    the 레인지 봇's paths (livemix.paths)."""
    p = p or L.paths()
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    srcs, boards, coins = {}, {}, {}
    for key, _rk, bot in BOARDS:
        try:
            srcs[key], boards[key], coins[key] = board_of(now, {"m30": mp, "f30": mpf, "r15": mpr}[key], bot=bot)
        except Exception as exc:  # noqa: BLE001  (its own failure is said, never the page's)
            from . import livemix as X
            srcs[key], boards[key], coins[key] = {"state": "error", "ko": f"{X.PROFILES[bot].name} 기록을 읽지 못했어요",
                                                  "name_ko": X.PROFILES[bot].name, "profile": bot,
                                                  "reason": f"{type(exc).__name__}: {exc}"[:300]}, {}, []
    moved = L.range_moved(p)            # owners 10-31 night: the old 레인지 봇 paper's reads leave the board
    if moved:
        s1h, b1h, coins1h, roc = None, {}, [], {}
    else:
        try:
            s1h, b1h, coins1h, roc = h1_of(p, now)
        except Exception as exc:  # noqa: BLE001
            s1h, b1h, coins1h, roc = {"state": "error", "ko": "레인지 봇 기록을 읽지 못했어요", "reason": f"{type(exc).__name__}: {exc}"[:300]}, {}, [], {}
    coins30, b30, coinsf, bf = coins["m30"], boards["m30"], coins["f30"], boards["f30"]
    coinsr, br = coins["r15"], boards["r15"]
    rshow = srcs["r15"].get("state") != "off"           # the 레인지 봇's own board once its bot has files
    order = list(dict.fromkeys([*coins30, *b30, *coinsf, *bf, *(coinsr if rshow else []), *br, *coins1h, *roc]))
    from .liverange import coin_ko
    tff, tfr = srcs["f30"].get("tf_ko") or "30분", srcs["r15"].get("tf_ko") or "15분"
    rows = [{"symbol": sym, "coin": coin_ko(sym), "in30": not coins30 or sym in coins30,
             "m30": m30_row(b30.get(sym), now, srcs["m30"].get("tf_ko") or "30분"),
             "inf": sym in coinsf or sym in bf, "f30": m30_row(bf.get(sym), now, tff) if sym in coinsf or sym in bf else None,
             "inrg": rshow and (sym in coinsr or sym in br),
             "rg": m30_row(br.get(sym), now, tfr) if rshow and (sym in coinsr or sym in br) else None,
             "h1": h1_row(b1h.get(sym)) if s1h and s1h.get("state") == "ok" else {"state": "none"},
             "roc": roc_row(roc.get(sym))} for sym in order]
    agree = [r["symbol"] for r in rows if r["m30"].get("trend") and r["h1"].get("trend") and r["m30"]["trend"] == r["h1"]["trend"]]
    ats = [x.get("at") for x in roc.values() if isinstance(x, dict) and x.get("at") is not None]
    sroc = None if moved else {"state": "ok", "at": max(ats), "stale": now - max(ats) > STALE_30M_MS} if ats else \
        {"state": "none", "ko": "레인지 봇이 아직 ROC 30분 값을 쓰지 않았어요 (10/30 설정으로 켜고 30분봉이 끝난 뒤부터)"}
    return {"now_ms": now, "m30": srcs["m30"], "f30": srcs["f30"], "r15": srcs["r15"], "h1": s1h, "roc": sroc, "moved": moved,
            "coins": rows, "agree": agree, "rules_ko": RULES_KO}


def register(app, ctx) -> dict:
    from ..app import json_finite

    @app.get("/api/v4/livebots/ftrend")
    def get_livebots_ftrend():
        """실거래 › 바이비트 봇 › 친구 추세판: each coin's trend as each mix bot saw it at its last close (the 바이비트 봇 30분,
        the friend bot and the 레인지 봇 15분: the trend bar's 종합 and its six rows, the OBV pane, the AC bar, the histogram's
        0 cross, each rule's answer; before the 레인지 봇's move, its paper's 1-hour and ROC reads), read from the bots' own
        files (read-only, 5 s cache)."""
        p = L.paths()
        return L._cached("ftrend:" + json.dumps(p, sort_keys=True), lambda: json_finite(build(p)))

    return {"routes": ["/api/v4/livebots/ftrend"]}
