"""데이터 점검 (league.json key ``dataq``): is the engine and its data healthy? One status sentence, a short checklist and what a beginner should do.

Everything here is read from what the snapshot already carries (engine time ``done_ms``, ``lag_s``, ``catching``, ``notes``, ``server``, the accounts'
rows, the closed trades, any ``*_error`` key a block left) and nothing is guessed: what the snapshot cannot show is written as "확인 못 함"
(the per-coin last price / bar time is not in the snapshot, so it is never claimed). Pure function of the in-progress snapshot dict and the trade
book; the clock is only ``now_ms`` (the snapshot's own ``generated_ms``). The age of the snapshot AFTER it was written is the screen's to add (it
knows the time now); this block says how the engine stood when it wrote.

The block, ``dataq_views(...)``::

    {"status": "ok" | "late" | "check", "status_ko": "정상" | "늦음" | "확인 필요", "headline_ko": "정상: ...", "reason_ko", "generated_ms", "done_ms",
     "counts": {"ok", "warn", "bad", "unknown"}, "checks": [check], "todo_ko": [...], "engine_notes": [...], "errors": [{"key", "text"}], "note_ko": [...]}
    check = {"id", "label_ko", "value_ko", "level": "ok" | "warn" | "bad" | "unknown", "word_ko": "정상" | "주의" | "확인 필요" | "확인 못 함",
             "core": bool, "detail_ko"}

``core`` checks decide the status: a bad one -> 확인 필요; the lag (over 30 minutes, or catching up) -> 늦음; a lag over 60 minutes -> 확인 필요
(the same limits as the header dot, lk.health). Other warnings (notes, load, memory, no recent trade) are listed with the word "주의" and counted in
the sentence but do not change the status. DeepSeek: only counts and flags are read; its wallet is hidden by design and never judged missing."""

from __future__ import annotations

import datetime
import math
from typing import Optional

from .riskview import _num

LAG_WARN_S = 30 * 60               # lk.js CATCHING_MS / health(): processed time behind the clock
LAG_BAD_S = 60 * 60
RSS_LIMIT_MB = 1300                # the unit's memory cap (status screen)
PASS_WARN_S = 300                  # a pass longer than the 5 minute cycle cannot keep up
QUIET_S = 24 * 3600                # no closed trade at all for this long (non-core)
FUTURE_S = 120                     # a trade closed after the engine's own time by more than this is wrong
WORD = {"ok": "정상", "warn": "주의", "bad": "확인 필요", "unknown": "확인 못 함"}
KST = datetime.timezone(datetime.timedelta(hours=9))


def _kst(ms) -> str:
    v = _num(ms)
    return "—" if v is None or v <= 0 else datetime.datetime.fromtimestamp(v / 1000, KST).strftime("%m/%d %H:%M")


def _dur(sec) -> str:
    v = _num(sec)
    if v is None:
        return "—"
    t = max(0, int(round(v)))
    if t < 60:
        return f"{t}초"
    if t < 3600:
        return f"{t // 60}분"
    if t < 86400:
        h, m = t // 3600, t % 3600 // 60
        return f"{h}시간 {m}분" if m else f"{h}시간"
    d, h = t // 86400, t % 86400 // 3600
    return f"{d}일 {h}시간" if h else f"{d}일"


def _chk(cid: str, label: str, value: str, level: str, core: bool = False, detail: str = "") -> dict:
    return {"id": cid, "label_ko": label, "value_ko": value, "level": level, "word_ko": WORD[level], "core": core, "detail_ko": detail}


def dataq_notes_ko() -> list:
    return [
        "스냅샷에 있는 숫자만으로 점검합니다. 거래소에서 코인별 마지막 시세나 봉이 언제였는지는 스냅샷에 없어서 ‘확인 못 함’입니다.",
        "‘정상’은 이 항목들에 이상이 없다는 뜻이지, 수익이나 전략이 괜찮다는 뜻이 아닙니다.",
        "이 화면의 판정은 엔진이 기록을 쓴 순간의 상태입니다. 기록을 쓴 지 오래되면 위 문장이 아니라 ‘기록을 쓴 지’ 줄을 먼저 보세요.",
    ]


def todo_ko(status: str) -> list:
    if status == "ok":
        return ["지금은 아무것도 하지 않아도 됩니다.", "이 화면은 5분마다 저절로 새로 고쳐집니다."]
    if status == "late":
        return ["10~20분만 기다린 뒤 이 화면을 다시 보세요. 따라잡는 중이면 저절로 좋아집니다.",
                "1시간이 지나도 ‘늦음’이면 이 화면 전체를 캡처해 개발자에게 보내 주세요.",
                "설정이나 파일은 건드리지 않아도 됩니다."]
    return ["이 화면 전체를 캡처해 개발자에게 보내 주세요 (아래 ‘확인 필요’ 줄이 보이게).",
            "‘확인 필요’가 아닌 줄은 참고용입니다. 직접 고치려고 하지 않아도 됩니다.",
            "그동안 이 리그의 숫자는 믿지 말고 보기만 하세요. 모의 거래라 실제 돈은 움직이지 않습니다."]


def dataq_views(doc: dict, book: Optional[dict] = None, lineup: Optional[list] = None, ds_money: bool = False) -> dict:
    """The snapshot's ``dataq`` block (see the module doc). ``doc``: the snapshot being written (accounts, done_ms, lag_s, ...)."""
    book = book or {}
    done, gen, start = _num(doc.get("done_ms")), _num(doc.get("generated_ms")), _num(doc.get("start_ms"))
    rows = [r for r in doc.get("accounts") or [] if isinstance(r, dict)]
    shown = [r for r in rows if r.get("kind") != "ds" or ds_money]
    checks: list = []
    # --- engine time and lag
    if done is None:
        checks.append(_chk("done", "엔진이 계산한 시각", "—", "bad", True, "스냅샷에 처리 시각이 없습니다"))
        lag = None
    else:
        checks.append(_chk("done", "엔진이 계산한 시각", f"{_kst(done)} (KST)", "ok", True, "이 시각까지의 1분봉을 계산했습니다"))
        lag = _num(doc.get("lag_s"))
        if lag is None and gen is not None:
            lag = max(0.0, (gen - done) / 1000)
    catching = doc.get("catching")
    if lag is None:
        checks.append(_chk("lag", "늦은 정도", "—", "unknown", False, "계산할 수 없습니다"))
    else:
        lvl = "bad" if lag > LAG_BAD_S else "warn" if lag > LAG_WARN_S or catching is True else "ok"
        checks.append(_chk("lag", "늦은 정도", _dur(lag), lvl, True, "5분봉이 확정되는 대로 계산해서 보통 10분 안입니다 (30분을 넘으면 늦음, 1시간을 넘으면 확인 필요)"))
    if isinstance(catching, bool):
        checks.append(_chk("catching", "따라잡는 중인가", "예" if catching else "아니오", "warn" if catching else "ok", True,
                           "엔진을 막 켰거나 처음부터 다시 계산하면 한동안 따라잡는 중입니다" if catching else ""))
    else:
        checks.append(_chk("catching", "따라잡는 중인가", "—", "unknown", False, "이 스냅샷에는 이 항목이 없습니다"))
    # --- errors a block left
    errs = [{"key": k, "text": str(v)[:200]} for k, v in sorted(doc.items()) if k.endswith("_error") and k != "dataq_error" and v]
    checks.append(_chk("errors", "계산 중 난 오류", "없음" if not errs else f"{len(errs)}개 ({', '.join(e['key'] for e in errs[:3])}{' 등' if len(errs) > 3 else ''})",
                       "ok" if not errs else "bad", True, "어느 화면의 기록을 못 만들었는지 알려 줍니다" if errs else ""))
    # --- accounts
    want = sum(int(_num(k.get("accounts")) or 0) for k in lineup or [])
    if not rows:
        checks.append(_chk("accounts", "계좌 수", "0개", "bad", True, "계좌 기록이 비어 있습니다"))
    elif not want:
        checks.append(_chk("accounts", "계좌 수", f"{len(rows):,}개", "ok", True, "비교할 종류별 개수가 스냅샷에 없습니다"))
    else:
        same = want == len(rows)
        checks.append(_chk("accounts", "계좌 수", f"{len(rows):,}개" + ("" if same else f" (종류별 합계 {want:,}개)"), "ok" if same else "warn", True,
                           "계좌 종류별 개수의 합과 같습니다" if same else "계좌 수가 종류별 개수의 합과 다릅니다"))
    # --- wallets, busts (a DeepSeek wallet is hidden by design: never judged)
    judged = [r for r in shown if r.get("kind") != "ds"]
    nowal = sum(_num(r.get("wallet")) is None for r in judged)
    checks.append(_chk("wallets", "지갑 잔고가 비었나", "없음" if not nowal else f"{nowal:,}개 계좌", "ok" if not nowal else "bad", True,
                       "모든 계좌에 잔고 숫자가 있습니다" if not nowal else "잔고가 숫자가 아닌 계좌가 있습니다"))
    bust = sum(r.get("bust") is True for r in shown)
    checks.append(_chk("bust", "잔고가 바닥난 계좌", f"{bust:,}개", "ok" if not bust else "warn", False, "파산은 전략 결과일 뿐 데이터 오류는 아닙니다" if bust else ""))
    # --- trades: times, numbers, how recent
    ids = {r.get("id") for r in shown}
    n_tr = bad_time = bad_num = 0
    last = None
    coins: set = set()
    for aid in sorted(ids, key=str):
        for t in book.get(aid) or []:
            n_tr += 1
            ex, en = _num(t.get("exit_time")), _num(t.get("entry_time"))
            if ex is None or en is None or en > ex or (done is not None and ex > done + FUTURE_S * 1000) or (start is not None and en < start - 60_000):
                bad_time += 1
            else:
                last = ex if last is None or ex > last else last
            if _num(t.get("pnl")) is None or _num(t.get("roe")) is None:
                bad_num += 1
            s = str(t.get("symbol") or "")
            if s:
                coins.add(s[:-4] if s.endswith("USDT") else s)
    checks.append(_chk("trade_time", "거래 시각이 이상한 것", "없음" if not bad_time else f"{bad_time:,}건 (닫힌 거래 {n_tr:,}건 중)", "ok" if not bad_time else "bad", True,
                       "들어간 시각이 나간 시각보다 늦거나, 엔진 시각보다 뒤에 닫힌 거래를 셉니다"))
    checks.append(_chk("trade_num", "손익이 비어 있는 거래", "없음" if not bad_num else f"{bad_num:,}건", "ok" if not bad_num else "warn", False))
    if n_tr == 0:
        quiet_young = done is not None and start is not None and done - start < QUIET_S * 1000
        checks.append(_chk("recent", "마지막 닫힌 거래", "아직 없음", "ok" if quiet_young else "unknown", False,
                           "리그를 시작한 지 하루가 안 됐습니다" if quiet_young else "닫힌 거래가 하나도 없어서 판단할 수 없습니다"))
    elif last is None or done is None:
        checks.append(_chk("recent", "마지막 닫힌 거래", "—", "unknown", False))
    else:
        age = max(0.0, (done - last) / 1000)
        checks.append(_chk("recent", "마지막 닫힌 거래", f"{_kst(last)} ({_dur(age)} 전, 엔진 시각 기준)", "ok" if age <= QUIET_S else "warn", False,
                           "하루 넘게 닫힌 거래가 없으면 신호나 시세가 끊겼는지 볼 만합니다" if age > QUIET_S else ""))
    checks.append(_chk("coins", "거래가 있는 코인", "아직 없음" if not coins else f"{len(coins)}개 ({' · '.join(sorted(coins))})", "ok" if coins else "unknown", False))
    checks.append(_chk("prices", "코인별 마지막 시세 · 봉 시각", "확인 못 함", "unknown", False, "스냅샷에 코인별 시세나 봉 시각이 들어 있지 않습니다"))
    # --- engine notes
    notes = [str(n)[:200] for n in doc.get("notes") or [] if isinstance(n, str)]
    checks.append(_chk("notes", "엔진 메모", "없음" if not notes else f"{len(notes)}개", "ok" if not notes else "warn", False,
                       "신호를 계산하다 생긴 일을 엔진이 적어 둔 것입니다. 아래에 있습니다" if notes else ""))
    # --- the machine
    sv = doc.get("server") if isinstance(doc.get("server"), dict) else {}
    load, cpus = sv.get("load"), _num(sv.get("cpus"))
    l1 = _num(load[0]) if isinstance(load, list) and load else None
    if l1 is None or not cpus:
        checks.append(_chk("load", "서버 부하", "—", "unknown", False))
    else:
        checks.append(_chk("load", "서버 부하", f"{l1:.2f} (CPU {int(cpus)}개)", "ok" if l1 <= cpus else "warn", False, "부하가 CPU 개수보다 크면 서버가 바쁜 것입니다" if l1 > cpus else ""))
    rss = _num(sv.get("rss_mb"))
    checks.append(_chk("memory", "엔진 메모리 (최대)", "—" if rss is None else f"{rss:,.0f} MB (한도 {RSS_LIMIT_MB:,} MB)", "unknown" if rss is None else
                       "ok" if rss <= 0.9 * RSS_LIMIT_MB else "warn", False))
    ps = _num(sv.get("pass_s"))
    checks.append(_chk("pass", "한 번 처리 시간", "—" if ps is None else _dur(ps), "unknown" if ps is None else "ok" if ps <= PASS_WARN_S else "warn", False,
                       "5분마다 한 번 계산하므로 5분보다 길면 따라가지 못합니다" if ps is not None and ps > PASS_WARN_S else ""))
    # --- the status
    counts = {k: sum(c["level"] == k for c in checks) for k in WORD}
    bad_core = [c for c in checks if c["core"] and c["level"] == "bad"]
    warn_core = [c for c in checks if c["core"] and c["level"] == "warn"]
    n_warn_other = sum(c["level"] == "warn" and not c["core"] for c in checks)
    if bad_core:
        status = "check"
    elif warn_core and all(c["id"] in ("lag", "catching") for c in warn_core):
        status = "late"
    elif warn_core:
        status = "check"
    else:
        status = "ok"
    status_ko = {"ok": "정상", "late": "늦음", "check": "확인 필요"}[status]
    lagtxt = f"엔진이 {_kst(done)}까지 계산했고 {_dur(lag)} 늦습니다" if done is not None and lag is not None else "엔진 시각을 알 수 없습니다"
    if status == "check":
        why = [lagtxt if c["id"] == "lag" else f"{c['label_ko']}: {c['value_ko']}" for c in bad_core + warn_core]
        reason = "; ".join(why[:3]) + (f" 외 {len(why) - 3}개" if len(why) > 3 else "")
    elif status == "late":
        reason = lagtxt + (" · 따라잡는 중" if catching is True else "")
    else:
        reason = lagtxt + f" · 오류 표시 없음 · 계좌 {len(rows):,}개"
    extra = []
    if n_warn_other:
        extra.append(f"참고할 주의 {n_warn_other}개")
    if counts["unknown"]:
        extra.append(f"확인 못 한 항목 {counts['unknown']}개")
    headline = f"{status_ko}: {reason}" + (f" ({', '.join(extra)})" if extra else "")
    return {"status": status, "status_ko": status_ko, "headline_ko": headline, "reason_ko": reason, "generated_ms": None if gen is None else int(gen),
            "done_ms": None if done is None else int(done), "counts": counts, "checks": checks, "todo_ko": todo_ko(status), "engine_notes": notes[:20],
            "errors": errs, "note_ko": dataq_notes_ko()}
