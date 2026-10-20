"""실거래 › 진입 근거 (owners 10/20 "진입하면 왜 진입했는지 어떤 근거로 진입했는지 대시보드에 보여?" → "응 만들어줘"). Read-only.

    GET /api/v4/livebots/why?bot=paper|paper2&symbol=BTCUSDT&entry=<the paper's entry minute, ms>

One entry of a paper bot (an executor's entry is the paper entry it followed: the positions card and the 거래 tab pass
that entry's ``why`` reference), from the records, in the order the bots decided it:

- ``signal``    the setting that gave it (its number in the config the bot runs, A / B group, entry mode, stop), the
                strategy, its timeframe, side, the signal bar's close, the reference price and the delay, the entry
                strength score (1-5, the 5-year entry study's bins) and whether the bot ranks by it: the ENTERED outcome
                of the paper's own database (``outcomes``: the engine's record of the signal it filled)
- ``conditions`` the strategy's own entry conditions on the signal bar (paperbot/strategy_views.py: the locked code's
                conditions with Korean names, checked against the locked signals), worked out again here on Binance futures
                bars of the bot's window that end at the signal bar, with the indicator values on that bar. A recheck,
                said so: the rule bot computed the signal on its own bars; a condition that comes out off says the bars
                may differ, never that the bot was wrong. Kept per signal bar (a closed bar never changes).
- ``chart``     the chart around the signal bar as the rule bot recorded it with the signal (paper3.db ``signal_log`` data
                ctx, sigservice.chart_context: regime of this and the higher timeframe, ADX / DI, the distance from EMA20,
                the place in the recent range, the support / resistance marks) in words, and the descriptive marks of the
                loss cards (paperbot/cards.py TAGS) that an entry alone decides (descriptive only, no rule)
- ``checks``    what the bot checked before it entered, with the numbers it saw: the KST weekend, the US macro releases
                around the minute (the nearest one), the NYSE open pause, a B setting's chase test (24-hour and 7-day
                range places of the reference price, combo.chase_hours / chase_check on the rule bot's 1m bars), one
                position at a time
- ``rivals``    other signals of the same bar close in the bot's own signal_log and what became of them
- ``record``    this setting's and this strategy's closed trades in this bot before this entry; the main bot's 5-year
                numbers of the setting and the strategy (deploy/combo.live-ac.expected.json: whole-period fit = optimistic,
                and the honest unseen 2025-26 rate), never mixed with the live numbers

HONESTY: a record that is not there says so (수집 전 / 못 읽음 / 기록 없음); nothing is guessed. Every database is opened
read-only (livebots.open_ro: mode=ro, query_only); nothing here changes a bot.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from collections import OrderedDict
from typing import Any, Optional

from . import livebots as L

MIN = 60_000
HOUR = 3_600_000
TF_MS = {"15m": 15 * MIN, "30m": 30 * MIN, "1h": HOUR, "4h": 4 * HOUR}
SINCE_MAX_BARS = 1500                  # bars from the signal bar to now that a recheck still fetches (older: said so)
COND_KEEP = 400                        # rechecked signal bars kept
SIDE_KO = {1: "롱", -1: "숏"}
SOURCE_KO = {"rule": "규칙봇 신호 그대로 (기본값 숫자)", "custom": "이 봇이 직접 계산한 커스텀값 신호"}
RECHECK_KO = ("바이낸스 선물 봉으로 이 대시보드가 다시 계산한 값이에요 (규칙봇과 같은 식 · 같은 길이의 봉). 규칙봇은 자기 봉으로 "
              "신호를 냈어요: 아주 드물게 봉이 달라 조건 하나가 다르게 나올 수 있어요")
CHART_KO = "규칙봇이 신호와 함께 기록한 그 봉의 차트 상황 (설명용: 매매 규칙 아님)"
TAG_KO = "손실 카드와 같은 설명용 표시 (진입 연구에서 수익과의 관계가 확인되지 않은 것도 있어요 · 매매 규칙 아님)"
# loss-card marks that an entry alone decides (paperbot/cards.py TAGS); the ones that read the exit, the old +12 % first
# lock or the 2-ATR stop are left out (this bot's stop and ladder are other numbers)
ENTRY_TAGS = ("추세 반대 진입", "상위 봉 추세 반대", "횡보장 진입", "추세 약함 (ADX 20 미만)", "DI 방향 반대", "많이 오른/내린 뒤 추격",
              "최근 범위 끝에서 진입", "돌파 진입")
REF_PAPER2_KO = "5년 기준표는 −50% 봇(규칙봇 15) 것이라 이 봇(손절이 달라요)에는 보여 드리지 않아요"

_lock = threading.Lock()
_cond: "OrderedDict[tuple, dict]" = OrderedDict()


# ---------------------------------------------------------------- the paper's records
def entered(path: str, account: str, symbol: str, entry: int) -> dict:
    """The ENTERED outcome of ``account`` filled at minute ``entry`` on ``symbol``: {"state": "ok", "signal", "detail"}."""
    try:
        conn = L.open_ro(path)
    except FileNotFoundError:
        return L._missing(path)
    except (OSError, sqlite3.Error) as exc:
        return L._err(path, exc)
    try:
        if "outcomes" not in L._tables(conn):
            return L._missing(path, L.NO_TABLE_KO)
        r = conn.execute("SELECT data FROM outcomes WHERE account_id = ? AND status = 'ENTERED' AND symbol = ? AND step_ts = ? "
                         "ORDER BY id DESC LIMIT 1", (account, symbol, int(entry))).fetchone()
    except sqlite3.Error as exc:
        return L._err(path, exc)
    finally:
        conn.close()
    if r is None:
        return {"state": "none", "path": path, "reason_ko": "이 진입의 신호 기록(ENTERED)이 페이퍼 DB에 없어요"}
    d = L._j(r[0])
    sig = d.get("signal") if isinstance(d.get("signal"), dict) else {}
    det = d.get("detail") if isinstance(d.get("detail"), dict) else {}
    if L._i(sig.get("ts")) is None:
        return {"state": "none", "path": path, "reason_ko": "신호 기록에 신호 봉 시각이 없어요"}
    return {"state": "ok", "signal": sig, "detail": det}


def rivals(path: str, account: str, bar_close: int, own: tuple) -> dict:
    """The bot's other signals of the same bar close (its signal_log) and what became of each (its outcome for the account:
    entered, lost to this one, filtered with the bot's own why)."""
    try:
        conn = L.open_ro(path)
    except FileNotFoundError:
        return L._missing(path)
    except (OSError, sqlite3.Error) as exc:
        return L._err(path, exc)
    try:
        conn.execute("BEGIN")
        tables = L._tables(conn)
        if "signal_log" not in tables:
            return L._missing(path, L.NO_TABLE_KO)
        rows = conn.execute("SELECT timeframe, strategy, symbol, side, status, data FROM signal_log WHERE bar_close = ? ORDER BY id",
                            (int(bar_close),)).fetchall()
        outs = conn.execute("SELECT status, reason, symbol, data FROM outcomes WHERE account_id = ? AND step_ts >= ? AND step_ts <= ?",
                            (account, int(bar_close) - 1, int(bar_close) + 6 * HOUR)).fetchall() if "outcomes" in tables else []
    except sqlite3.Error as exc:
        return L._err(path, exc)
    finally:
        conn.close()
    oc = {}
    for st, reason, sym, data in outs:
        sig = L._j(data).get("signal") or {}
        meta = sig.get("meta") if isinstance(sig.get("meta"), dict) else {}
        if L._i(sig.get("ts")) == int(bar_close) - 1:
            oc[(sig.get("timeframe"), meta.get("member") or sig.get("strategy_id"), sym)] = (st, reason)
    out = []
    for tf, member, sym, side, status, data in rows:
        if (tf, member, sym) == own:
            continue
        d = L._j(data)
        if status == "SUBMITTED":
            o = oc.get((tf, member, sym))
            cat, ko = L.outcome_cat(o[0], o[1]) if o else ("pending", "결과 기록 없음")
        else:
            cat, ko = L.why_cat(status, d.get("why"))
        out.append({"strategy": d.get("strategy") or str(member).split("@")[0], "tf": tf, "symbol": sym, "side": L._i(side),
                    "status": status, "cat": cat, "ko": ko, "why_ko": L.why_words(d.get("why")) if d.get("why") else None})
    return {"state": "ok", "rows": out}


def rule_row(path: str, bar_close: int, tf: str, strategy: str, symbol: str) -> dict:
    """The rule bot's own signal_log row of this signal (paper3.db): its data (close, bid, ask, the chart ctx)."""
    try:
        conn = L.open_ro(path)
    except FileNotFoundError:
        return L._missing(path, "규칙봇 DB 파일이 아직 없어요 (PAPERBOT_LIVE_RULE_DB 경로를 확인해 주세요)")
    except (OSError, sqlite3.Error) as exc:
        return L._err(path, exc)
    try:
        if "signal_log" not in L._tables(conn):
            return L._missing(path, L.NO_TABLE_KO)
        r = conn.execute("SELECT side, atr, ref_price, ref_time, delay_ms, status, data FROM signal_log WHERE bar_close = ? AND timeframe = ? "
                         "AND strategy = ? AND symbol = ?", (int(bar_close), tf, strategy, symbol)).fetchone()
    except sqlite3.Error as exc:
        return L._err(path, exc)
    finally:
        conn.close()
    if r is None:
        return {"state": "none", "path": path, "reason_ko": "규칙봇 신호 기록에 이 신호가 없어요 (커스텀값 신호이거나 규칙봇 DB가 다른 파일)"}
    d = L._j(r[6])
    return {"state": "ok", "side": L._i(r[0]), "atr": L._f(r[1]), "ref_price": L._f(r[2]), "ref_time": L._i(r[3]), "delay_ms": L._i(r[4]),
            "status": r[5], "close": L._f(d.get("close")), "bid": L._f(d.get("bid")), "ask": L._f(d.get("ask")),
            "ctx": d.get("ctx") if isinstance(d.get("ctx"), dict) else {}}


# ---------------------------------------------------------------- the chart around the signal bar (words)
def _num(x: Any, nd: int = 2) -> Optional[float]:
    v = L._f(x)
    return None if v is None else round(v, nd)


def chart_of(ctx: dict, side: int, tf: str) -> dict:
    """The rule bot's chart context of the signal bar as items {k, v, ko, tone} ("good": with the trade, "bad": against it,
    None: neither) and the entry marks of the loss cards."""
    from ...cards import REGIME_KO, TAGS
    from ...context import HTF, REGIME_N
    if not ctx:
        return {"state": "none", "reason_ko": "규칙봇이 이 신호와 함께 차트 상황을 기록하지 않았어요"}
    items = []

    def add(k, v, ko, tone=None):
        items.append({"k": k, "v": v, "ko": ko, "tone": tone})

    def along(reg):
        return "good" if (side > 0 and reg == "trend_up") or (side < 0 and reg == "trend_down") else \
            "bad" if (side > 0 and reg == "trend_down") or (side < 0 and reg == "trend_up") else None
    reg, hreg = ctx.get("regime"), ctx.get("htf_regime")
    if reg:
        t = along(reg)
        add("장세 (이 봉)", REGIME_KO.get(reg, reg), "진입 방향과 같은 추세" if t == "good" else "진입 방향과 반대 추세" if t == "bad" else
            f"최근 {REGIME_N.get(tf, 60)}봉 기준", t)
    if hreg:
        t = along(hreg)
        htf = HTF.get(tf)
        add(f"장세 (상위 {L.TF_KO.get(htf, htf)}봉)", REGIME_KO.get(hreg, hreg),
            "진입 방향과 같은 추세" if t == "good" else "진입 방향과 반대 추세" if t == "bad" else "", t)
    adx = L._f(ctx.get("adx"))
    if adx is not None:
        add("ADX 14", _num(adx, 1), "20 미만: 추세 약함" if adx < 20 else "25 넘음: 추세 뚜렷" if adx >= 25 else "20-25: 보통",
            "bad" if adx < 20 else None)
    dp, dm = L._f(ctx.get("di_plus")), L._f(ctx.get("di_minus"))
    if dp is not None and dm is not None:
        fav = (dp - dm) * side > 0
        add("DI+ / DI−", f"{dp:.1f} / {dm:.1f}", ("롱 쪽이 셈" if dp > dm else "숏 쪽이 셈") + (" · 진입 방향과 같음" if fav else " · 진입 방향과 반대"),
            "good" if fav else "bad")
    e20 = L._f(ctx.get("ema20_dist_atr"))
    if e20 is not None:
        go = e20 * side
        add("EMA20에서 거리", f"{e20:+.2f} ATR", "진입 방향으로 2 ATR 넘게 간 뒤 (추격 쪽)" if go >= 2.0 else
            "진입 방향으로 조금 간 자리" if go > 0 else "진입 방향 반대쪽 (되돌림 자리)", "bad" if go >= 2.0 else None)
    age = L._i(ctx.get("trend_age"))
    if age is not None:
        add("EMA20 같은 쪽", f"{age}봉째", "종가가 EMA20의 같은 쪽에 머문 봉 수")
    rp = L._f(ctx.get("range_pct"))
    if rp is not None:
        edge = (side > 0 and rp >= 0.9) or (side < 0 and rp <= 0.1)
        add("최근 범위 안 위치", f"{rp * 100:.0f}%", f"최근 {REGIME_N.get(tf, 60)}봉 저점 0% · 고점 100%" + (" · 진입 방향 끝 (범위 끝에서 진입)" if edge else ""),
            "bad" if edge else None)
    bp = L._f(ctx.get("box_pos"))
    if bp is not None and reg in ("box", "chop"):
        add("박스 안 위치", f"{bp * 100:.0f}%", "박스 아래 0% · 위 100%")
    sr = ctx.get("sr") if isinstance(ctx.get("sr"), dict) else {}
    if sr.get("breakout") == 1:
        add("가격선", "돌파", "신호 봉 종가가 가격선 하나를 진입 방향으로 넘음 (설명용)", None)
    c = {"reason": None, "best_roe": None, "hold_bars": None, "side": side, "ctx": ctx, "macro": []}
    tags = []
    for name, test in TAGS:
        if name not in ENTRY_TAGS:
            continue
        try:
            if test(c):
                tags.append(name)
        except (KeyError, TypeError, ValueError):
            continue
    return {"state": "ok", "items": items, "tags": tags, "tags_ko": TAG_KO, "note_ko": CHART_KO,
            "marks_error": ctx.get("marks_error")}


# ---------------------------------------------------------------- the strategy's own conditions on the signal bar
def _cond_get(key: tuple) -> Optional[dict]:
    with _lock:
        v = _cond.get(key)
        if v is not None:
            _cond.move_to_end(key)
        return v


def _cond_put(key: tuple, v: dict) -> None:
    with _lock:
        _cond[key] = v
        _cond.move_to_end(key)
        while len(_cond) > COND_KEEP:
            _cond.popitem(last=False)


def _last_values(view: dict, bar_open_s: int) -> list:
    """{name, value} of every line of the view at the signal bar (its open time, seconds); a line without a value there
    is left out."""
    out = []

    def take(group: str, name: str, data: list):
        if data and int(data[-1].get("time", -1)) == bar_open_s and data[-1].get("value") is not None:
            out.append({"group": group, "name": name, "value": float(data[-1]["value"])})
    for o in view.get("overlays") or []:
        take("차트 위 선", o.get("name"), o.get("data") or [])
    for p in view.get("panes") or []:
        for s in p.get("series") or []:
            take(p.get("name"), s.get("name"), s.get("data") or [])
    return out


def recheck(frames, strategy: str, tf: str, symbol: str, bar_close: int, side: int, invert: bool, now: int) -> dict:
    """The strategy's conditions for ``side`` (the strategy's own side: the other one for an inverted setting) on the bar
    that closed at ``bar_close``, from Binance futures bars of the bot's window ending at that bar."""
    key = (strategy, tf, symbol, int(bar_close), int(side), bool(invert))
    hit = _cond_get(key)
    if hit is not None:
        return hit
    span = TF_MS.get(tf)
    if not span:
        return {"state": "none", "reason_ko": f"{tf} 봉은 다시 계산하지 않아요"}
    try:
        from ... import strategy_views as SV
        known = SV.has_view(strategy)
    except Exception:  # noqa: BLE001  (the vendored code not loadable here: said so, never a 500)
        known = False
    if not known:
        return {"state": "none", "reason_ko": "이 매매법의 조건 보기(strategy_views)가 아직 없어요"}
    since = max(0, (int(now) - int(bar_close)) // span)
    if since > SINCE_MAX_BARS:
        return {"state": "old", "reason_ko": f"신호가 {SINCE_MAX_BARS}봉보다 오래돼 다시 계산하지 않아요"}
    from .. import app as D
    want = D.view_bars(tf, strategy)
    n = want + since + 3
    try:
        df = frames(symbol, tf, n)
        btc = frames("BTCUSDT", tf, n) if strategy == "F14_SMT" and symbol != "BTCUSDT" else None
    except Exception as exc:  # noqa: BLE001
        return {"state": "error", "reason": f"{type(exc).__name__}: {exc}"[:200], "reason_ko": "바이낸스 봉을 받지 못했어요 (잠시 뒤 다시)"}
    if df is None or not len(df):
        return {"state": "error", "reason_ko": "바이낸스 봉을 받지 못했어요 (잠시 뒤 다시)"}
    import pandas as pd
    opens = pd.to_datetime(df["ts"], utc=True).astype("int64") // 10**6
    df = df[(opens + span <= int(bar_close)).to_numpy()]
    if not len(df) or int(pd.Timestamp(df["ts"].iloc[-1]).value // 10**6) != int(bar_close) - span:
        return {"state": "none", "reason_ko": "받은 바이낸스 봉에 신호 봉이 없어요"}
    df = df.iloc[-want:].reset_index(drop=True)
    if len(df) < 50:
        return {"state": "none", "reason_ko": "다시 계산할 봉이 모자라요"}
    if btc is not None:
        bo = pd.to_datetime(btc["ts"], utc=True).astype("int64") // 10**6
        btc = btc[(bo + span <= int(bar_close)).to_numpy()].reset_index(drop=True)
    try:
        v = SV.render(strategy, df, tf, tail=1, symbol=symbol, btc=btc)
    except Exception as exc:  # noqa: BLE001
        return {"state": "error", "reason": f"{type(exc).__name__}: {exc}"[:200], "reason_ko": "조건을 다시 계산하지 못했어요"}
    own = -side if invert else side
    name = "long" if own > 0 else "short"
    items = [{"name": c["name"], "on": bool(c["on"])} for c in (v.get("conditions") or {}).get(name, [])]
    out = {"state": "ok", "side": own, "side_ko": SIDE_KO.get(own), "items": items, "all_on": bool(items) and all(c["on"] for c in items),
           "n_on": sum(1 for c in items if c["on"]), "values": _last_values(v, (int(bar_close) - span) // 1000),
           "bars": len(df), "inverted": bool(invert), "note_ko": RECHECK_KO}
    _cond_put(key, out)
    return out


# ---------------------------------------------------------------- what the bot checked before the entry
def _range_place(hours: dict, k: int, n: int, price: float) -> Optional[dict]:
    v = [hours[j] for j in range(k - n, k) if j in hours]
    if not v:
        return None
    hi, lo = max(a for a, _ in v), min(b for _, b in v)
    return {"place": (price - lo) / max(hi - lo, 1e-12), "high": hi, "low": lo, "hours": len(v)}


def chase_numbers(rule_db: str, symbol: str, bar_close: int, side: int, price: Optional[float]) -> dict:
    """A B setting's chase test as the bot ran it (combo.chase_hours / chase_check on the rule bot's 1m bars), with the
    24-hour and 7-day range places of the reference price."""
    from ... import combo as C
    if not price:
        return {"state": "none", "reason_ko": "기준 가격 기록이 없어 추격 판단 숫자를 다시 보지 못했어요"}
    try:
        conn = L.open_ro(rule_db)
    except FileNotFoundError:
        return L._missing(rule_db, "규칙봇 1분봉 파일이 아직 없어요")
    except (OSError, sqlite3.Error) as exc:
        return L._err(rule_db, exc)
    try:
        if "live_bars" not in L._tables(conn):
            return L._missing(rule_db, "규칙봇 파일에 1분봉 표(live_bars)가 아직 없어요")
        hours = C.chase_hours(conn, symbol, bar_close)
    except sqlite3.Error as exc:
        return L._err(rule_db, exc)
    finally:
        conn.close()
    chase, why = C.chase_check(hours, bar_close, int(side), float(price))
    k = int(bar_close) // HOUR
    return {"state": "ok", "chase": chase, "why_ko": why or None, "price": float(price),
            "d24": _range_place(hours, k, C.CHASE_24H, float(price)), "d7": _range_place(hours, k, C.CHASE_7D, float(price)),
            "limits": {"h24_hi": C.CHASE_24H_HI, "h24_lo": C.CHASE_24H_LO, "d7_hi": C.CHASE_7D_HI, "d7_lo": C.CHASE_7D_LO}}


def nearest_macro(ts: int) -> Optional[dict]:
    """The registered US release nearest to minute ``ts`` (data/macro_events.csv), with its distance."""
    from ... import events as EV
    try:
        evs = EV.all_events()
    except Exception:  # noqa: BLE001
        return None
    if not evs:
        return None
    e = min(evs, key=lambda x: abs(int(x.ts_ms) - int(ts)))
    return {"kind": e.kind, "kind_ko": EV.KIND_KO.get(e.kind, e.kind), "ts": int(e.ts_ms), "gap_ms": int(e.ts_ms) - int(ts)}


def checks(cfg: dict, member: Optional[dict], entry: int, bar_close: int, side: int, symbol: str, ref_price: Optional[float],
           rule_db: str) -> list:
    """What the bot checked before this entry (paperbot/combo.py ``_entry_block`` order, then one position at a time),
    each {id, ok, ko, detail}: ok True = passed (it entered, so every rule that was on passed; the numbers say by how much)."""
    from ... import combo as C
    out = []

    def add(id_, ok, ko, detail=None):
        out.append({"id": id_, "ok": ok, "ko": ko, "detail": detail})
    if member and (member.get("filter") or member.get("off") or member.get("when")):
        parts = [f["ko"] for f in member.get("filter") or []]
        if member.get("off"):
            parts.append(f"끄는 구간 {len(member['off'])}개에 안 걸림")
        if member.get("when"):
            parts.append("설정의 조건 안")
        add("member", True, "설정의 조건 통과: " + " · ".join(parts))
    if cfg.get("no_weekend"):
        dow = L.DOW_KO[((int(entry) + L.KST_MS) // L.DAY + 3) % 7]
        add("weekend", not C.kst_weekend(entry), f"주말 아님 (한국 시간 {dow}요일)" if not C.kst_weekend(entry) else "주말인데 진입 기록이 있어요")
    mb = L._i(cfg.get("macro_blackout_min"))
    if mb:
        near = nearest_macro(entry)
        inside = near is not None and abs(near["gap_ms"]) <= mb * MIN
        ko = f"미국 경제 발표 앞뒤 {mb}분이 아님" if not inside else f"경제 발표 앞뒤 {mb}분 안이에요"
        add("macro", not inside, ko, near)
    up = L._i(cfg.get("us_open_pause_min"))
    if up:
        why = C.us_open_pause(entry, up)
        add("usopen", not why, f"나스닥 개장 뒤 {up}분이 아님" if not why else why)
    if member and member.get("no_chase"):
        ch = chase_numbers(rule_db, symbol, bar_close, side, ref_price)
        if ch.get("state") != "ok":
            add("chase", None, "추격 진입 막기: 판단 숫자를 다시 보지 못했어요", ch)
        else:
            add("chase", ch["chase"] is False, "추격 진입 막기 통과 (고점 추격 롱 · 저점 추격 숏 아님)" if ch["chase"] is False else
                f"추격 진입 막기: {ch['why_ko'] or '판단 못 함'}", ch)
    add("one", True, "포지션이 비어 있었어요 (한 번에 하나)")
    return out


# ---------------------------------------------------------------- the record before this entry
def record_of(trades: list, meta: dict, order: Optional[int], strategy: str, tf: str, entry: int) -> dict:
    """This setting's (its order in the config, else the strategy x timeframe) and this strategy's closed trades of the bot
    that ended before this entry."""
    before = [t for t in trades if (L._i(t.get("exit_time")) or 0) <= int(entry)]
    if order:
        mine = [t for t in before if (meta.get((t.get("symbol"), L._i(t.get("entry_time")))) or {}).get("member_order") == order]
    else:
        mine = [t for t in before if t.get("strategy_id") == strategy and t.get("timeframe") == tf]
    return {"setting": L._record(mine), "strategy": L._record([t for t in before if t.get("strategy_id") == strategy]),
            "all": L._record(before)}


def five_year(order: Optional[int], strategy: str) -> dict:
    """The main bot's 5-year numbers of this setting and this strategy (livebots.rank's reading of the reference)."""
    from ... import livecheck as LC
    try:
        from ... import liveimprove as LI
        ref = LI.load_ref()
    except LC.RefConfigMismatch as exc:
        return {"state": "missing", "reason_ko": str(exc)}
    except (OSError, ValueError) as exc:
        return {"state": "error", "reason": f"{type(exc).__name__}: {exc}"[:200],
                "reason_ko": "5년 기준표(deploy/combo.live-ac.expected.json)를 못 읽었어요"}
    return {"state": "ok", "member": L._bt_member(ref, order), "strategy": L._bt_strategy(ref, strategy),
            "break_even": L._f(ref.get("break_even_win")),
            "note_ko": "5년 백테스트: '전체 기간' 승률은 전체 기간에 맞춘 값이라 낙관적이에요 · '안 본 2025-26'이 정직한 값이에요"}


# ---------------------------------------------------------------- one entry
def build(p: dict, more: dict, bot: str, symbol: str, entry: int, frames, now_ms: Optional[int] = None) -> dict:
    """GET /api/v4/livebots/why."""
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    base = {"now_ms": now, "bot": bot, "symbol": symbol, "entry": int(entry)}
    _configs, _follows, paper, execs = L.sources(p, now)
    bots = L.paper_bots(p, paper, execs)
    b = next((x for x in bots if x["id"] == bot), None)
    if b is None:
        return {**base, "state": "missing", "reason_ko": "그 페이퍼 봇이 지금 화면에 없어요"}
    base["bot_ko"] = (b.get("label_ko") or "").split(" (")[0] or ("페이퍼(연습)" if bot == "paper" else bot)
    e = entered(b["path"], L.ACCOUNT, symbol, int(entry))
    if e.get("state") != "ok":
        return {**base, **{k: e.get(k) for k in ("state", "reason_ko", "reason", "path")}}
    sig, det = e["signal"], e["detail"]
    meta = sig.get("meta") if isinstance(sig.get("meta"), dict) else {}
    bar_close = int(sig["ts"]) + 1
    side, tf, strategy = int(sig.get("side") or 0), sig.get("timeframe"), sig.get("strategy_id")
    combo = L.read_combo(b["path"], more["combo_config"] if bot == "paper" else (more.get("combo2_config") or "-"))
    cfg = (combo.get("config") or {}) if combo.get("state") == "ok" else {}
    members = L.members_of(combo) if combo.get("state") == "ok" else []
    order = L._i(meta.get("member_order"))
    member = members[order - 1] if order and 0 < order <= len(members) and members[order - 1].get("strategy") == strategy else None
    rank = cfg.get("rank") if isinstance(cfg.get("rank"), list) else []
    score = L._f(meta.get("score_raw"))
    signal = {"strategy": strategy, "tf": tf, "tf_ko": L.TF_KO.get(tf, tf), "side": side, "side_ko": SIDE_KO.get(side), "bar_close": bar_close,
              "ref_price": L._f(meta.get("ref_price")), "ref_time": L._i(meta.get("ref_time")), "delay_ms": L._i(meta.get("delay_ms")),
              "fill": L._f(det.get("fill")), "leverage": L._i(det.get("leverage")), "margin": L._f(det.get("margin")),
              "atr": L._f(sig.get("atr")), "source": meta.get("source"), "source_ko": SOURCE_KO.get(meta.get("source"), meta.get("source")),
              "score": score, "score_used": "score" in rank, "order": order, "member": meta.get("member"),
              "break_level": L._f(meta.get("break_level"))}
    setting = None
    if member:
        setting = {**member, "group": "B" if member.get("no_chase") else "A"}
    rule = rule_row(more["rule_db"], bar_close, tf, strategy, symbol) if (meta.get("source") or "rule") == "rule" else \
        {"state": "none", "reason_ko": "커스텀값 신호라 규칙봇 신호 기록이 없어요"}
    chart = chart_of(rule.get("ctx") or {}, side, tf) if rule.get("state") == "ok" else {k: rule.get(k) for k in ("state", "reason_ko", "reason", "path")}
    cond = recheck(frames, strategy, tf, symbol, bar_close, side, bool(member and member.get("invert")), now) if frames else \
        {"state": "none", "reason_ko": "이 화면은 바이낸스 봉을 받지 않아요"}
    acc = (b["read"].get("accounts") or {}).get(L.ACCOUNT) if b["read"].get("state") == "ok" else None
    trades = (acc or {}).get("trades") or []
    rec = record_of(trades, L.entered_meta(b["path"], L.ACCOUNT) if order else {}, order, strategy, tf, int(entry))
    return {**base, "state": "ok", "signal": signal, "setting": setting,
            "combo": {k: combo.get(k) for k in ("state", "reason_ko", "reason", "path", "source")},
            "rule": {k: rule.get(k) for k in ("state", "reason_ko", "reason", "path", "status", "close", "bid", "ask", "delay_ms")},
            "chart": chart, "conditions": cond,
            "checks": checks(cfg, member, int(entry), bar_close, side, symbol, signal["ref_price"], more["rule_db"]),
            "rivals": rivals(b["path"], L.ACCOUNT, bar_close, (tf, meta.get("member") or strategy, symbol)),
            "record": rec, "five_year": five_year(order, strategy) if bot == "paper" else {"state": "missing", "reason_ko": REF_PAPER2_KO}}


# ---------------------------------------------------------------- routes
def register(app, ctx) -> dict:
    import json

    from fastapi import HTTPException

    from ..app import json_finite
    frames = getattr(ctx, "frames", None)

    @app.get("/api/v4/livebots/why")
    def get_livebots_why(bot: str, symbol: str, entry: int):
        """실거래 › 진입 근거: one paper entry's signal, the strategy's conditions on the signal bar, the chart, the checks it
        passed, the other signals of that bar and the record before it (5 s cache; the recheck is kept per signal bar)."""
        if bot not in ("paper", "paper2"):
            raise HTTPException(400, "unknown bot")
        if symbol not in L.COINS:
            raise HTTPException(400, "unknown symbol")
        p, more = L.paths(), L.paths_more()
        k = "why:" + json.dumps([p, more, bot, symbol, int(entry)], sort_keys=True)
        return L._cached(k, lambda: json_finite(build(p, more, bot, symbol, int(entry), frames)))

    return {"routes": ["/api/v4/livebots/why"]}
