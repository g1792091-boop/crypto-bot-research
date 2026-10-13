"""타임라인 (league.json key ``timeline``): the milestones of the owner-exit league in time order, newest first.

Pure function of the closed-trade book, the account rows, the lineup and a few snapshot fields (start_ms, started_ms, done_ms, decision, notes); no
clock, no randomness. A row is one plain sentence with its time (epoch ms, shown in KST by the screen) and the account it is about (the screen links
``#/account/<id>``)::

    {"cap": 60, "more": int (rows left out), "headline_ko", "note_ko": [...], "undated_ko": [engine notes without a time],
     "rows": [{"ms": int | None, "kind", "tag_ko", "text_ko", "account": id | None, "suffix": "-fq" | None, "state": "done" | "coming" | None,
               "approx": bool}]}

``kind``: install, start, observe, decide, first, best, worst, liq, bust. Rows with a time come first, newest first (a coming date is the newest);
rows without a time (a bust of an account with no closed trade) go last. ``state`` is only set for the two dated checks (done = the engine's
processed time ``done_ms`` is past it). The 판정 단계 (observe -> decide) changes at the 28일째 row, so that row says so.

What the snapshot does NOT carry: when the engine restarted or started over (``reset_ms`` is in the engine's database only; ``notes`` have no time),
and the time an account went bust (its last closed trade is used and the row is marked ``approx``). The note says so.

Rows kept (the four focus kinds -fq, -ld, -fqc, -ldc): the first closed trade of each; the biggest single win and loss ($) of 실전 후보 and 대조;
liquidations (exit reason LIQ; at most ``MAX_LIQ`` newest rows, the rest counted); accounts marked bust (at most ``MAX_BUST``).

DeepSeek money (D11): a DeepSeek account is left out of every row unless ``ds_money``."""

from __future__ import annotations

from typing import Optional

from .riskview import COIN_TWIN, CONTROL, LIVE, _coin, _name, _num, _shown

CAP = 60
MAX_LIQ = 10
MAX_BUST = 10
FOCUS = (LIVE, CONTROL, COIN_TWIN[LIVE], COIN_TWIN[CONTROL])
SIDE_KO = {1: "롱", -1: "숏"}
MINUS = "−"


def _money(x: float) -> str:
    return f"{'+' if x > 0 else MINUS if x < 0 else ''}${abs(x):,.2f}"


def _trade_ko(t: dict) -> str:
    bits = [_coin(t.get("symbol")), SIDE_KO.get(int(_num(t.get("side")) or 0)),
            None if _num(t.get("leverage")) is None else f"{_num(t.get('leverage')):.0f}배"]
    return " ".join(b for b in bits if b)


def timeline_notes_ko() -> list:
    return [
        "엔진이 다시 시작했거나 처음부터 다시 계산한 시각은 기록에 없어서 이 표에 넣지 못했습니다.",
        "파산한 시각은 그 계좌의 마지막 닫힌 거래 시각으로 대신했습니다 (표에 ‘대략’이라고 적습니다).",
        "살펴보는 계좌 종류는 실전 후보 · 대조와 그 동전 던지기 짝 네 가지입니다. 가장 큰 이익과 손실은 실전 후보와 대조만 봅니다 (금액은 가상 돈).",
        "최근 60개까지만 보여 줍니다.",
    ]


def timeline_views(book: dict, rows: list, lineup: Optional[list], decision: Optional[dict], start_ms=None, started_ms=None, done_ms=None,
                   notes: Optional[list] = None, ds_money: bool = False) -> dict:
    """The snapshot's ``timeline`` block (see the module doc)."""
    start, started, done = _num(start_ms), _num(started_ms), _num(done_ms)
    lu = {k["suffix"]: k for k in lineup or [] if k.get("role") and k.get("suffix")}
    suffix_of = {k["role"]: k["suffix"] for k in lu.values()}
    accts: dict = {s: [] for s in FOCUS if s in lu}
    for r in sorted(rows or [], key=lambda r: str(r.get("id"))):
        s = suffix_of.get(r.get("role"))
        if s in accts and _shown(r, ds_money):
            accts[s].append(r)
    out: list = []

    def add(ms, kind, tag, text, account=None, suffix=None, state=None, approx=False):
        out.append({"ms": None if ms is None else int(ms), "kind": kind, "tag_ko": tag, "text_ko": text, "account": account, "suffix": suffix,
                    "state": state, "approx": approx})

    # --- install / start
    if start is not None and started is not None and abs(start - started) > 60_000:
        add(started, "install", "설치", "후보 리그 엔진을 처음 설치해 켠 때")
        add(start, "start", "시작", "리그의 기록 시작 시각 (이 시각부터의 1분봉으로 계산)")
    elif start is not None or started is not None:
        add(start if start is not None else started, "start", "시작", "후보 리그 시작 (설치한 때부터 기록)")
    # --- the two dated checks
    dec = decision if isinstance(decision, dict) else {}
    cp = dec.get("checkpoints") if isinstance(dec.get("checkpoints"), dict) else {}
    od, dd = int(_num(cp.get("observe_day")) or 14), int(_num(cp.get("decide_day")) or 28)
    for key, day, kind, tag, past, future in (
            ("observe_ms", od, "observe", f"{od}일째 확인", "숫자만 살펴보고 아무것도 바꾸지 않는 날이 지났습니다", "숫자만 살펴보는 날 (아무것도 바꾸지 않음)"),
            ("decide_ms", dd, "decide", f"{dd}일째 판정", "판정 단계로 바뀌었습니다 (판정은 이 날 한 번만)", "판정 단계로 바뀌는 날 (판정은 이 날 한 번만)")):
        ms = _num(dec.get(key))
        if ms is not None:
            passed = done is not None and done >= ms
            add(ms, kind, tag, past if passed else future, state="done" if passed else "coming")
    # --- the first closed trade of each focus kind, the biggest win and loss
    exits: dict = {}
    for s, rs in accts.items():
        first = best = worst = None
        for r in rs:
            for t in (book or {}).get(r.get("id")) or []:
                ex, pnl = _num(t.get("exit_time")), _num(t.get("pnl"))
                if ex is None:
                    continue
                key = (ex, str(r.get("id")))
                if first is None or key < first[0]:
                    first = (key, r, t)
                if pnl is not None:
                    if best is None or (pnl, -ex) > (best[0], -best[1]):
                        best = (pnl, ex, r, t)
                    if worst is None or (pnl, ex) < (worst[0], worst[1]):
                        worst = (pnl, ex, r, t)
                if t.get("exit_reason") == "LIQ":
                    exits.setdefault(s, []).append((ex, r, t))
        nm = _name(lu[s])
        if first is not None:
            (ex, _id), r, t = first
            add(ex, "first", "첫 거래", f"‘{nm}’ 계좌의 첫 닫힌 거래: {_trade_ko(t)}", r.get("id"), s)
        if s in (LIVE, CONTROL):
            if best is not None and best[0] > 0:
                add(best[1], "best", "가장 큰 이익", f"‘{nm}’의 가장 큰 한 번 이익 {_money(best[0])} ({_trade_ko(best[3])})", best[2].get("id"), s)
            if worst is not None and worst[0] < 0:
                add(worst[1], "worst", "가장 큰 손실", f"‘{nm}’의 가장 큰 한 번 손실 {_money(worst[0])} ({_trade_ko(worst[3])})", worst[2].get("id"), s)
    # --- liquidations (newest first, capped) and busts
    liqs = sorted(((ex, s, r, t) for s, v in exits.items() for ex, r, t in v), key=lambda x: (-x[0], str(x[2].get("id"))))
    for ex, s, r, t in liqs[:MAX_LIQ]:
        add(ex, "liq", "강제청산", f"‘{_name(lu[s])}’ 계좌가 강제청산됨: {_trade_ko(t)}", r.get("id"), s)
    n_liq_more = max(0, len(liqs) - MAX_LIQ)
    busts = []
    for s, rs in accts.items():
        for r in rs:
            if r.get("bust") is True:
                ts = [_num(t.get("exit_time")) for t in (book or {}).get(r.get("id")) or []]
                ts = [x for x in ts if x is not None]
                busts.append((max(ts) if ts else None, s, r))
    busts.sort(key=lambda x: (x[0] is None, -(x[0] or 0), str(x[2].get("id"))))
    for ms, s, r in busts[:MAX_BUST]:
        add(ms, "bust", "파산", f"‘{_name(lu[s])}’ 계좌의 잔고가 바닥남" + ("" if ms is not None else " (시각을 알 수 없음)"), r.get("id"), s, approx=ms is not None)
    n_bust_more = max(0, len(busts) - MAX_BUST)
    # --- order: dated rows newest first (ties: the same order each time), undated last; then the cap
    out.sort(key=lambda r: (r["ms"] is None, -(r["ms"] or 0), r["kind"], str(r["account"])))
    more = n_liq_more + n_bust_more
    if len(out) > CAP:
        more += len(out) - CAP
        out = out[:CAP]
    undated = [str(n)[:200] for n in (notes or []) if isinstance(n, str)][:5]
    return {"cap": CAP, "more": more, "headline_ko": _headline(out), "note_ko": timeline_notes_ko(), "undated_ko": undated, "rows": out}


def _headline(rows: list) -> str:
    dated = [r for r in rows if r["ms"] is not None and r["state"] != "coming"]
    if not dated:
        return "아직 적을 일이 없습니다"
    n_liq = sum(r["kind"] == "liq" for r in rows)
    n_bust = sum(r["kind"] == "bust" for r in rows)
    return f"기록된 일 {len(rows)}개 · 강제청산 {n_liq}건 · 파산 {n_bust}개 (표에 보이는 것만 센 숫자)"
