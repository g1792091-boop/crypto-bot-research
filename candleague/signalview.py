"""신호 (league.json key ``signals``): when did each account kind last ENTER a trade, per coin. Read-only; it changes nothing in the engine.

This shows ENTRIES (a position that was opened), not the strategy's conditions: a strategy can be "on" without an entry (a gate said no, the
account already held a position, the signal came while it was busy). Counts only, never advice.

Entries come from two places: the closed trades (entry_time, side, symbol) and the positions open right now (``since``, side, symbol) of the account
rows. Both are in the snapshot already. Pure functions of the closed-trade book, the account rows and the lineup; ``now_ms`` is the snapshot's time
(runner passes it); ages are against it, so the same data always gives the same numbers. DeepSeek money: DeepSeek accounts are left out of every
figure unless ``ds_money`` (summary.decision_views' rule).

The block, ``signal_views(...)``::

    {"ref_ms", "day_start_ms", "ds_in_stats", "headline_ko", "rules_ko": [...], "note_ko": [...], "coins": [coin, ...],
     "last": [{coin, ms, age_ms, side, suffix, name_ko, pick, open, open_n}],       # per coin over the shown kinds: the newest entry of any kind
     "kinds": [kind, ...]}
    kind = {"role", "suffix", "label_ko", "name_ko", "short_ko", "group", "live", "accounts", "open_n", "today", "h24", "total",
            "coins": [{coin, ms, age_ms, side, pick, n_at, open, open_n, h24}]}   # one entry per coin in ``coins`` (all None when the kind never entered it)
      today: entries since 00:00 UTC of ``ref_ms``; h24: entries in the 24 hours before ``ref_ms``; total: every entry the snapshot knows;
      n_at: how many accounts of the kind entered that coin at that same moment; open: the last entry is still open; open_n: accounts holding it now."""

from __future__ import annotations

from typing import Optional

from .riskview import _coin, _group, _name, _num, _shown, _sgn

DAY_MS = 86_400_000
SUFFIXES = ("-fq", "-ld", "-ldc", "-fqc")     # 실전 후보, 대조, their coin twins
LIVE = "-fq"
COIN_ORDER = ("BTC", "ETH", "SOL", "DOGE", "LTC", "BCH")


def signal_rules_ko() -> list:
    return [
        "무엇을 보여 주나: 계좌 종류가 마지막으로 언제 어느 코인에 들어갔는지(진입)만 보여 줍니다. 전략의 조건이 지금 켜져 있는지는 아닙니다.",
        "진입이 없었다고 신호가 없었다는 뜻은 아닙니다. 필터가 막았거나, 계좌가 이미 포지션을 들고 있었거나, 다른 이유가 있을 수 있습니다.",
        "기준: 이미 닫힌 거래의 진입 시각과 지금 열려 있는 포지션의 진입 시각입니다. 오늘은 UTC 0시부터, 24시간은 스냅샷 시각 기준 직전 24시간입니다.",
        "모든 숫자는 세기만 합니다. 무엇을 하라는 말은 없습니다.",
    ]


def signal_notes_ko(ds_money: bool) -> list:
    out = [
        "같은 신호에 여러 계좌가 함께 들어가므로, 한 번의 신호가 계좌 수만큼 진입으로 세어집니다. ‘같은 순간 N개 계좌’가 그 수입니다.",
        "스냅샷은 5분마다 쓰입니다. 그 사이의 진입은 다음 스냅샷에서 보입니다.",
        "기록은 짧습니다. 진입이 없는 코인은 아직 신호가 없었거나, 기록이 시작된 뒤에 그 코인 신호가 없었던 것입니다.",
    ]
    if not ds_money:
        out.append("딥시크 계좌는 금액 숨김 설정이라 모든 숫자에서 뺐습니다.")
    return out


def _events(accts: list, book: dict) -> list:
    """[(ms, coin, side, account id, pick, is_open)] of every entry the snapshot knows for the accounts."""
    ev = []
    for r in accts:
        aid, pick = r.get("id"), r.get("pick") or r.get("id")
        for t in (book or {}).get(aid) or []:
            ms, side, coin = _num(t.get("entry_time")), _sgn(t.get("side")), _coin(t.get("symbol"))
            if ms is not None and side and coin:
                ev.append((int(ms), coin, side, aid, pick, False))
        o = r.get("open")
        if o:
            ms, side, coin = _num(o.get("since")), _sgn(o.get("side")), _coin(o.get("symbol"))
            if ms is not None and side and coin:
                ev.append((int(ms), coin, side, aid, pick, True))
    return ev


def _last(ev: list) -> Optional[tuple]:
    """The newest entry; at one instant the account whose id sorts first (deterministic)."""
    return min(ev, key=lambda e: (-e[0], str(e[3]))) if ev else None


def _kind_block(k: dict, accts: list, book: dict, coins: list, ref: int, day0: int) -> dict:
    ev = _events(accts, book)
    open_by = {}
    for r in accts:
        o = r.get("open")
        if o and _sgn(o.get("side")) and _coin(o.get("symbol")):
            open_by[_coin(o["symbol"])] = open_by.get(_coin(o["symbol"]), 0) + 1
    cells = []
    for c in coins:
        mine = [e for e in ev if e[1] == c]
        last = _last(mine)
        cell = {"coin": c, "ms": None, "age_ms": None, "side": None, "pick": None, "n_at": 0, "open": None, "open_n": open_by.get(c, 0),
                "h24": sum(1 for e in mine if ref - DAY_MS < e[0] <= ref)}
        if last:
            cell.update(ms=last[0], age_ms=max(0, ref - last[0]), side=last[2], pick=last[4], n_at=sum(1 for e in mine if e[0] == last[0]), open=last[5])
        cells.append(cell)
    return {"role": k["role"], "suffix": k.get("suffix"), "label_ko": k.get("label_ko"), "name_ko": k.get("name_ko") or _name(k), "short_ko": k.get("short_ko"),
            "group": _group(k.get("label_ko")), "live": k.get("suffix") == LIVE, "accounts": len(accts), "open_n": sum(open_by.values()),
            "today": sum(1 for e in ev if day0 <= e[0] <= ref), "h24": sum(1 for e in ev if ref - DAY_MS < e[0] <= ref), "total": len(ev), "coins": cells}


def _headline(kinds: list) -> str:
    if not kinds:
        return "아직 보여 줄 계좌 종류가 없습니다"
    f = next((k for k in kinds if k["live"]), kinds[0])
    if not f["total"]:
        return f"{f['name_ko']}: 아직 진입 기록이 없습니다."
    return f"{f['name_ko']}: 오늘(UTC) 진입 {f['today']:,}건, 최근 24시간 {f['h24']:,}건, 지금 열린 포지션 {f['open_n']:,}개 (진입 기록 {f['total']:,}건 기준)."


def signal_views(book: dict, rows: list, lineup: Optional[list], now_ms: Optional[int] = None, ds_money: bool = False) -> dict:
    """The snapshot's ``signals`` block (see the module doc). Kinds shown: the lineup's -fq, -ld, -ldc, -fqc that have a shown account."""
    ref = int(now_ms) if _num(now_ms) is not None else 0
    day0 = ref // DAY_MS * DAY_MS
    lu = {k["suffix"]: k for k in lineup or [] if k.get("role") and k.get("suffix")}
    by_role: dict = {}
    for r in sorted(rows or [], key=lambda r: str(r.get("id"))):
        if _shown(r, ds_money):
            by_role.setdefault(r.get("role"), []).append(r)
    shown = [(lu[s], by_role[lu[s]["role"]]) for s in SUFFIXES if s in lu and by_role.get(lu[s]["role"])]
    seen = {e[1] for _k, a in shown for e in _events(a, book)}
    coins = list(COIN_ORDER) + sorted(seen - set(COIN_ORDER))
    kinds = [_kind_block(k, a, book, coins, ref, day0) for k, a in shown]
    last = []
    for i, c in enumerate(coins):
        best = None
        for kb in kinds:
            cell = kb["coins"][i]
            if cell["ms"] is not None and (best is None or (-cell["ms"], str(kb["suffix"])) < (-best[0]["ms"], str(best[1]["suffix"]))):
                best = (cell, kb)
        last.append({"coin": c, "ms": None, "age_ms": None, "side": None, "suffix": None, "name_ko": None, "pick": None, "open": None,
                     "open_n": sum(kb["coins"][i]["open_n"] for kb in kinds)})
        if best:
            cell, kb = best
            last[-1].update(ms=cell["ms"], age_ms=cell["age_ms"], side=cell["side"], suffix=kb["suffix"], name_ko=kb["name_ko"], pick=cell["pick"], open=cell["open"])
    return {"ref_ms": ref, "day_start_ms": day0, "ds_in_stats": bool(ds_money), "headline_ko": _headline(kinds), "rules_ko": signal_rules_ko(),
            "note_ko": signal_notes_ko(ds_money), "coins": coins, "last": last, "kinds": kinds}
