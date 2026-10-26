"""실거래 › V3.9 투비트 (#/v39; owners 10-26: "추세판단봇 화면 따로, vwap 개선판 봇 화면 따로, 친구 30분 봇 화면 따로, v3.9
화면 따로"): the fifth executor, 투비트 (docs/toobit-ko.md, $50 of real money), and the paper account it follows, the rule
bot's V3.9 1-hour account ``V39_ALL@1h`` in paper3.db, on one screen and nothing of the other bots. Read-only, one answer:

    GET /api/v4/livebots/v39   status (꺼짐 until its database is there, with the guide's step to start it; 켜짐 / 멈춤 /
                               기록 멈춤 / 못 읽음 after), the plan in words (the server's config, or the repo's template
                               deploy/executor.live-toobit.json while the server has none, said so), the open live position
                               with its ladder step and the next one, today's and the recent closed live trades, the paper
                               account's entries against the live ones (followed / missed and why, from the executor's own
                               records), the equity line (5 s cache, as every 실거래 tab)

Sources (read only; nothing here writes anywhere, no key file is opened): the executor's config
(PAPERBOT_LIVE_TOOBIT_CONFIG, /etc/paperbot/executor-toobit.json) and database (PAPERBOT_LIVE_TOOBIT_DB, else the
config's ``db``, else /var/lib/paperbot/exec/executor-toobit-live.db), the same variables the summary reads
(dash/more/livebots.py paths); the paper database the config names (``paper_db``; PAPERBOT_LIVE_V39_PAPER_DB,
/var/lib/paperbot/paper3.db, while there is no readable config) and its account (``account``; V39_ALL@1h without one).
Honest states as every live page (CONTRACT §1.6): a missing file = 꺼짐 / 수집 전, an unreadable one = 못 읽음 + why, never a
zero; the paper account's money is never shown as real money.

The numbers: ratios (0.12 = 12 %), money in USDT, times UTC ms. A live trade's P&L is the executor's own (Toobit's
realized P&L with its fees when it has the fills, else the wallet change: ``est``).
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Optional

from ...ladder2 import ComboLadder
from . import livebots as L

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir, os.pardir))
NAME_KO = "V3.9 투비트"
ACCOUNT = "V39_ALL@1h"                  # the template's account (docs/toobit-ko.md: 규칙봇의 V3.9 1시간 계좌)
ENV = {"paper": ("PAPERBOT_LIVE_V39_PAPER_DB", "/var/lib/paperbot/paper3.db"),
       "repo_config": ("PAPERBOT_LIVE_V39_REPO_CONFIG", os.path.join(REPO, "deploy", "executor.live-toobit.json"))}
UNIT = "paperbot-executor-toobit"
GUIDE = "docs/toobit-ko.md"
GUIDE_STEP_KO = "docs/toobit-ko.md의 '실행기 켜기' → '켜는 순서'"
OFF_KO = "아직 꺼져 있어요"
TRADES_KEEP = 30                        # closed live trades listed (newest first)
FOLLOW_KEEP = 40                        # paper entries listed against the live ones (newest first)
EVENTS_KEEP = 20
SIDE_KO = {1: "롱", -1: "숏"}
COIN_KO = {"BTCUSDT": "BTC", "ETHUSDT": "ETH", "SOLUSDT": "SOL", "DOGEUSDT": "DOGE", "LTCUSDT": "LTC", "BCHUSDT": "BCH"}
# the words of a followed / missed paper entry (state -> words); a missed one adds the executor's own reason
FOLLOW_KO = {"followed": "따라 들어감", "open": "따라 들어가 아직 열려 있음", "missed": "안 들어감", "before": "실행기 시작 전",
             "off": "실행기가 아직 꺼져 있어요", "waiting": "실거래 쪽 기록을 기다리는 중"}
WAIT_MS = 2 * L.MATCH_MS                # a paper entry this fresh may not have its live row yet (the executor loops ~3 s)


def _f(x: Any) -> Optional[float]:
    return L._f(x)


def _i(x: Any) -> Optional[int]:
    return L._i(x)


def coin_ko(symbol: Any) -> str:
    s = str(symbol or "")
    return COIN_KO.get(s, s.replace("USDT", ""))


def paths(env: Optional[dict] = None) -> dict:
    """{"config", "db", "paper", "repo_config"}: the executor's two files as the summary finds them (livebots.paths), the
    paper database to read while the config cannot be (the config's own ``paper_db`` wins, plan_of), the repo template."""
    env = os.environ if env is None else env
    lp = L.paths(env)
    out = {k: (env.get(var) or default) for k, (var, default) in ENV.items()}
    out.update(config=lp["toobit_config"], db=lp["toobit_db"])
    return out


def read_raw(path: str) -> dict:
    """The config file as JSON: {"state": "ok", "raw": {...}} / missing / error (never a guess)."""
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        return L._missing(path, "실행기 설정 파일이 아직 없어요")
    except ValueError as exc:
        return {**L._err(path, exc), "reason_ko": "실행기 설정 파일이 JSON 모양이 아니에요"}
    except OSError as exc:
        return L._err(path, exc)
    if not isinstance(raw, dict):
        return {"state": "error", "path": path, "reason": "not an object", "reason_ko": "실행기 설정 파일의 모양이 달라요"}
    return {"state": "ok", "path": path, "raw": raw}


def _pct(x: float, d: int = 0) -> str:
    """0.17 -> "17%", 0.0283 -> "2.83%" (as many decimals as it needs, up to ``d``)."""
    v = round(x * 100, max(d, 2))
    return f"{v:g}%"


def lev_of(raw: dict, symbol: Any) -> Optional[int]:
    """The fixed leverage the config gives a coin (``leverage_by_symbol``: the coin's own, else "*"); None without one."""
    m = raw.get("leverage_by_symbol")
    if not isinstance(m, dict):
        return None
    return _i(m.get(str(symbol))) or _i(m.get("*"))


def ladder_steps(lad: Optional[ComboLadder], n: int = 3) -> list:
    """The ladder's first ``n`` steps as [{"at": net ROE that arms it, "lock": the lock}] (20 % -> 17 %, 25 % -> 22 % ...)."""
    if lad is None:
        return []
    out, lock = [], None
    for _ in range(n):
        lock, at = lad.next_after(lock)
        out.append({"at": round(at, 6), "lock": round(lock, 6)})
    return out


def plan_of(raw: dict) -> dict:
    """The plan of a config in the owners' words (docs/toobit-ko.md "두 분이 정한 계획"), each line from the config's own
    numbers: [{"key", "k", "ko"}]; a key the config lacks says so (never the guide's number in its place)."""
    lines = []

    def add(key: str, k: str, ko: str) -> None:
        lines.append({"key": key, "k": k, "ko": ko})
    acc = raw.get("account") if isinstance(raw.get("account"), str) else None
    pdb = raw.get("paper_db") if isinstance(raw.get("paper_db"), str) else None
    add("follow", "따라갈 페이퍼", f"규칙봇의 V3.9 1시간 페이퍼 계좌 {acc or '(설정에 계좌 없음)'}" + (f" ({pdb})" if pdb else "")
        + " · 페이퍼가 진입하면 실거래도 진입")
    mf = _f(raw.get("margin_frac"))
    if raw.get("size_from") == "equity" and mf:
        add("size", "크기", f"진입할 때마다 증거금 = 그때 투비트 잔고의 {_pct(mf)} (수량 = 잔고 × {mf:g} × 배수 ÷ 가격)")
    else:
        add("size", "크기", L.size_ko({"size_from": raw.get("size_from") or "paper", "margin_frac": mf, "qty_scale": _f(raw.get("qty_scale"))}))
    m = raw.get("leverage_by_symbol")
    if isinstance(m, dict) and m:
        named = [f"{coin_ko(k)} {_i(v)}배" for k, v in m.items() if k != "*" and _i(v)]
        rest = _i(m.get("*"))
        add("leverage", "배수", " · ".join(named + ([f"{'나머지' if named else '모든 코인'} {rest}배"] if rest else []))
            + " (페이퍼 배수 대신 고정)")
    else:
        add("leverage", "배수", "페이퍼 배수 그대로 (고정 배수 설정 없음)")
    s = _f(raw.get("stop_scale"))
    if s and raw.get("stop_from", "ratio") == "ratio":
        add("stop", "손절", f"{2 * s:g} ATR (페이퍼 손절 거리 2 ATR × {s:g}) · 자기 체결가 기준 · 거래소에 걸어 둠")
    else:
        add("stop", "손절", "페이퍼 손절 거리 그대로 (손절 배율 설정 없음)")
    lad = ComboLadder.of(raw.get("ladder"))
    if lad is not None:
        steps = ladder_steps(lad)
        short = " · ".join(f"{_pct(x['at'])}→{_pct(x['lock'])}" for x in steps) + " …"
        basis = "화면 ROE" if raw.get("ladder_basis") == "gross" else "순ROE"
        where = ("자기 체결가 · 투비트 1분봉 · 투비트 비용으로 재요" if raw.get("ladder_from") == "own"
                 else "페이퍼의 잠금을 따라가요")
        add("ladder", "계단 익절", f"{basis} {short} ({lad.describe()}) · {where} · 손절은 올리기만 해요")
    else:
        add("ladder", "계단 익절", "계단 설정 없음")
    tp = _f(raw.get("take_profit_roe"))
    add("tp", "고정 익절", f"순ROE +{tp * 100:g}%에서 시장가로 전부 닫음" if tp else "없음")
    if raw.get("liq_guard") is True:
        mmr = _f(raw.get("liq_guard_mmr")) or 0.005
        levs = sorted({v for v in (_i(x) for x in (m or {}).values()) if v}, reverse=True) if isinstance(m, dict) else []
        far = " · ".join(f"{v}배 약 {_pct(1 / v - mmr, 2)}" for v in levs)
        add("liq", "청산가 확인", "손절이 강제청산 가격보다 멀면 그 진입은 안 함 (놓친 신호, 알람 아님)"
            + (f" · 유지증거금률 {_pct(mmr, 2)}로 어림: {far}" if far else ""))
    else:
        add("liq", "청산가 확인", "꺼짐")
    mb = _i(raw.get("macro_block_min"))
    add("macro", "경제 발표", f"미국 경제 발표(CPI·FOMC·NFP·PCE) 앞뒤 {mb}분은 새 진입 안 함 · 열린 포지션은 그대로" if mb
        else "경제 발표 진입 금지 없음")
    risk = raw.get("risk") if isinstance(raw.get("risk"), dict) else {}
    syms = risk.get("allowed_symbols") if isinstance(risk.get("allowed_symbols"), list) else []
    budget = _f(raw.get("budget_usd"))
    add("coins", "코인 · 주문", (" · ".join(coin_ko(x) for x in syms) + " · " if syms else "") + "한 번에 1포지션 · 시장가 · 격리 마진"
        + (f" · 정한 금액 ${budget:g}" if budget else ""))
    costs = raw.get("net_costs") if isinstance(raw.get("net_costs"), dict) else {}
    tb = costs.get("toobit") if isinstance(costs.get("toobit"), dict) else {}
    fee = _f(tb.get("taker_fee"))
    if fee:
        add("fee", "수수료", f"투비트 테이커 {_pct(fee, 3)} 한쪽 (계산용 · 페이백은 봇 밖에서 따로)")
    return {"lines": lines, "ladder": ladder_steps(lad, 4), "ladder_two": lad.two_part if lad else None,
            "mode": raw.get("mode") if isinstance(raw.get("mode"), str) else None, "account": acc, "paper_db": pdb,
            "budget_usd": budget, "margin_frac": mf}


def status_of(cfg: dict, rec: dict, now: int) -> dict:
    """off (no database yet: 아직 꺼져 있어요, with the step to start it) / error / stopped (its loop wrote nothing for
    EXEC_STALE_MS) / halted / running; ``seen_ms`` the executor's last saved state."""
    base = {"unit": UNIT, "guide": GUIDE, "guide_ko": GUIDE_STEP_KO}
    if rec.get("state") in ("missing", "none"):
        why = ("설정 파일은 서버에 있어요 · 실행기를 아직 켜지 않아 기록 파일이 없어요" if cfg.get("state") == "ok"
               else "서버에 설정 파일도 기록 파일도 아직 없어요")
        return {**base, "state": "off", "ko": OFF_KO, "why_ko": why, "path": rec.get("path"), "reason_ko": rec.get("reason_ko")}
    if rec.get("state") != "ok":
        return {**base, "state": "error", "ko": "실행기 기록을 못 읽었어요", "reason_ko": rec.get("reason_ko"),
                "reason": rec.get("reason"), "path": rec.get("path")}
    out = {**base, "seen_ms": rec.get("as_of_ms"), "since_ms": rec.get("since_ms"), "mode": rec.get("mode")}
    if rec.get("mode") and rec["mode"] != "mainnet":
        out["mode_ko"] = f"실거래(mainnet)가 아니라 {rec['mode']} 모드로 돌고 있어요"
    if rec.get("stale"):
        return {**out, "state": "stopped", "ko": "기록 멈춤",
                "why_ko": f"{L.EXEC_STALE_MS // 60_000}분 넘게 새 기록이 없어요 (실행기는 몇 초마다 기록해요) · 서버에서 systemctl status {UNIT}"}
    if rec.get("halted"):
        return {**out, "state": "halted", "ko": "멈춤", "why_ko": f"새 진입 멈춤: {rec.get('halt_reason') or '이유 기록 없음'}",
                "halted_ms": rec.get("halted_ts")}
    return {**out, "state": "running", "ko": "켜져 있어요", "why_ko": "페이퍼 V39_ALL@1h가 진입하면 따라 들어가요"}


def position_of(rec: dict, raw: dict) -> Optional[dict]:
    """The executor's open position with its ladder: the step it is on (0 = 처음 손절), the lock, the best net ROE, the next
    step (its own record's, 거래소 기준), the stop's distance and its ROE, the liquidation distance by the config's guard
    estimate (1 / leverage - mmr; labelled 어림)."""
    p = rec.get("position") if rec.get("state") == "ok" else None
    if not p:
        return None
    own = p.get("own") or {}
    lad = ComboLadder.of(own.get("ladder") or raw.get("ladder"))
    lock = own.get("lock") if own else p.get("lock_roe")
    side, entry, stop, lev = p.get("side") or 0, p.get("entry"), p.get("stop"), p.get("leverage")
    stop_move = side * (stop / entry - 1) if stop and entry and side else None
    mmr = _f(raw.get("liq_guard_mmr")) or 0.005
    liq_frac = 1 / lev - mmr if lev else None
    nx = own.get("next") if own else None
    return {"key": p.get("key"), "status": p.get("status"), "symbol": p.get("symbol"), "coin": coin_ko(p.get("symbol")),
            "side": side, "qty": p.get("qty"), "leverage": lev, "entry": entry, "entry_ms": p.get("entry_time"),
            "paper_entry": p.get("paper_entry"), "paper_ms": p.get("paper_time"), "stop": stop, "stop_initial": p.get("stop_initial"),
            "stop_move": stop_move, "stop_roe": stop_move * lev if stop_move is not None and lev else None,
            "locked": bool(p.get("locked")), "lock_roe": lock, "step": lad.index(lock) if lad else (1 if lock else 0),
            "best": own.get("best") if own else None, "best_roe": own.get("best_roe") if own else None,
            "next": {"at": nx.get("at"), "lock": nx.get("lock"), "price": nx.get("price"), "lock_price": nx.get("lock_price")} if nx else None,
            "margin": p.get("margin"), "notional": entry * p["qty"] if entry and p.get("qty") else None,
            "liq_frac": liq_frac, "liq_price": entry * (1 - side * liq_frac) if entry and liq_frac and side else None,
            "liq_mmr": mmr, "basis": own.get("basis") if own else None, "staying": bool(own.get("staying")) if own else False,
            "stop_order": bool(p.get("stop_order"))}


def live_trades(rec: dict, pairs: dict) -> list:
    """The closed live trades, newest first, each with the paper trade it followed (when matched)."""
    out = []
    for t in sorted(rec.get("trades") or [], key=lambda t: (t.get("exit_ts") or 0), reverse=True)[:TRADES_KEEP]:
        pt = pairs.get(str(t.get("key")))
        out.append({"key": t.get("key"), "symbol": t.get("symbol"), "coin": coin_ko(t.get("symbol")), "side": t.get("side"),
                    "leverage": t.get("leverage"), "qty": t.get("qty"), "entry_ms": t.get("entry_ts"), "entry": t.get("entry_price"),
                    "exit_ms": t.get("exit_ts"), "exit_reason": t.get("exit_reason"),
                    "exit_ko": L.EXIT_KO.get(t.get("exit_reason") or "", t.get("exit_raw") or "청산"),
                    "pnl": t.get("pnl"), "roe": t.get("roe"), "est": t.get("est"), "commission": t.get("commission"),
                    "funding": t.get("funding"),
                    "paper": {"exit_reason": pt.get("exit_reason"), "exit_ko": L.EXIT_KO.get(pt.get("exit_reason") or "", pt.get("exit_reason")),
                              "roe": pt.get("roe"), "entry_price": pt.get("entry_price"), "leverage": pt.get("leverage")} if pt else None})
    return out


def follow_of(paper_acc: Optional[dict], rec: dict, account: str, pairs: dict, now: int) -> dict:
    """The paper account's entries against the executor's: each closed paper trade (and its open position) since the
    executor's start, newest first, followed (with the live result) or missed with the executor's own reason
    (livebots.why_missed); before the start / while it is off said so, never a guess."""
    if not paper_acc:
        return {"rows": [], "counts": {}, "why": []}
    on = rec.get("state") == "ok"
    since = rec.get("since_ms") if on else None
    by_pid = {pt["id"]: lk for lk, pt in pairs.items()}
    live_by = {str(t.get("key")): t for t in rec.get("trades") or []} if on else {}
    rows = []
    for pt in paper_acc.get("trades") or []:
        row = {"id": pt["id"], "symbol": pt["symbol"], "coin": coin_ko(pt["symbol"]), "side": pt["side"], "entry_ms": pt["entry_time"],
               "exit_ms": pt["exit_time"], "leverage": pt["leverage"], "roe": pt["roe"], "exit_reason": pt["exit_reason"],
               "exit_ko": L.EXIT_KO.get(pt["exit_reason"] or "", pt["exit_reason"]), "open": False}
        if not on:
            row.update(state="off")
        elif pt["id"] in by_pid:
            lt = live_by.get(by_pid[pt["id"]]) or {}
            row.update(state="followed", live={"pnl": lt.get("pnl"), "roe": lt.get("roe"), "exit_reason": lt.get("exit_reason"),
                                              "exit_ko": L.EXIT_KO.get(lt.get("exit_reason") or "", "청산"), "est": lt.get("est"),
                                              "leverage": lt.get("leverage")})
        else:
            w = L.why_missed(rec, pt, account)
            row.update(state=w["state"], why_kind=w.get("why_kind"), why_ko=w.get("why_ko"), why_text=w.get("why_text"))
        rows.append(row)
    pp = paper_acc.get("position")
    if pp:
        row = {"id": None, "symbol": pp["symbol"], "coin": coin_ko(pp["symbol"]), "side": pp["side"], "entry_ms": pp["entry_time"],
               "exit_ms": None, "leverage": pp["leverage"], "roe": None, "exit_reason": None, "exit_ko": None, "open": True}
        lp = rec.get("position") if on else None
        if not on:
            row.update(state="off")
        elif lp and lp.get("key") == pp.get("key"):
            row.update(state="open", why_ko="실거래도 같은 포지션을 들고 있어요")
        elif since and pp.get("entry_time") and pp["entry_time"] < since:
            row.update(state="before", why_ko="실행기가 시작하기 전의 페이퍼 포지션이에요")
        else:
            w = L.why_missed(rec, {"symbol": pp["symbol"], "entry_time": pp["entry_time"]}, account)
            if w.get("why_kind") is None and pp.get("entry_time") and now - pp["entry_time"] < WAIT_MS:
                row.update(state="waiting", why_ko="방금 들어간 페이퍼 포지션이에요 · 실거래 쪽 기록을 기다리는 중")
            else:
                row.update(state=w["state"], why_kind=w.get("why_kind"), why_ko=w.get("why_ko"), why_text=w.get("why_text"))
        rows.append(row)
    rows.sort(key=lambda r: -(r["entry_ms"] or 0))
    counts: dict = {}
    why: dict = {}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
        if r["state"] == "missed":
            k = r.get("why_kind") or "none"
            why.setdefault(k, {"kind": k, "ko": r.get("why_ko"), "n": 0})["n"] += 1
    return {"rows": rows[:FOLLOW_KEEP], "counts": counts, "why": sorted(why.values(), key=lambda x: -x["n"]),
            "since_ms": since, "more": max(0, len(rows) - FOLLOW_KEEP)}


def paper_view(pr: dict, account: str, since: Optional[int]) -> dict:
    """The paper account (모의 돈): its file's state, wallet, open position and record (all trades, and since the executor's
    start when it has one)."""
    base = {"path": pr.get("path"), "account": account}
    if pr.get("state") != "ok":
        return {**base, "state": pr.get("state"), "reason_ko": pr.get("reason_ko"), "reason": pr.get("reason")}
    a = (pr.get("accounts") or {}).get(account) or {}
    if not a.get("known"):
        return {**base, "state": "none", "reason_ko": f"페이퍼 기록에 {account} 계좌가 아직 없어요", "as_of_ms": pr.get("as_of_ms")}
    trades = a.get("trades") or []
    after = [t for t in trades if since is None or (t.get("entry_time") or 0) >= since]
    pos = a.get("position")
    return {**base, "state": "ok", "as_of_ms": pr.get("as_of_ms"), "stale": pr.get("stale"), "wallet": a.get("wallet"),
            "initial": a.get("initial"), "since_ms": a.get("since_ms"),
            "position": {k: pos.get(k) for k in ("symbol", "side", "leverage", "entry", "entry_time", "stop", "stop_initial",
                                                 "lock_roe", "locked", "last_mark", "last_mark_roe_net", "key")}
            | {"coin": coin_ko(pos.get("symbol"))} if pos else None,
            "record": L.stats(t["pnl"] for t in trades), "record_live": L.stats(t["pnl"] for t in after) if since else None}


def equity_of(rec: dict, budget: Optional[float]) -> dict:
    """The executor's equity: now (its last read), the first one it recorded, the change with deposits and withdrawals
    left out (livebots.read_exec base_equity), the line (thinned)."""
    if rec.get("state") != "ok":
        return {"state": rec.get("state")}
    now, base = rec.get("last_equity"), rec.get("base_equity")
    ch = now - base if now is not None and base is not None else None
    return {"state": "ok", "now": now, "now_ms": rec.get("equity_ts") or rec.get("as_of_ms"), "first": rec.get("first_equity"),
            "first_ms": rec.get("first_equity_ts"), "base": base, "change": ch,
            "change_pct": ch / base if ch is not None and base else None, "budget": budget, "curve": rec.get("curve") or []}


def build(p: Optional[dict] = None, now_ms: Optional[int] = None) -> dict:
    """GET /api/v4/livebots/v39."""
    p = p or paths()
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    cfg = read_raw(p["config"])
    rec = L.read_exec(p["db"], now)
    if cfg.get("state") == "ok":
        raw, plan_src = cfg["raw"], {"source": "server", "path": p["config"]}
    else:
        rp = read_raw(p["repo_config"])
        raw = rp.get("raw") or {}
        plan_src = {"source": "repo", "path": p["repo_config"], "state": rp.get("state"),
                    "reason_ko": ("서버에 설정 파일이 아직 없어 저장소의 설정 원본(deploy/executor.live-toobit.json)으로 보여 줘요"
                                  if cfg.get("state") == "missing" else "서버 설정 파일을 못 읽어 저장소의 설정 원본으로 보여 줘요")}
    account = (raw.get("account") if isinstance(raw.get("account"), str) and raw.get("account") else None) or ACCOUNT
    paper_path = raw.get("paper_db") if cfg.get("state") == "ok" and isinstance(raw.get("paper_db"), str) and raw.get("paper_db") else p["paper"]
    pr = L.read_paper(paper_path, [account], now)
    acc = (pr.get("accounts") or {}).get(account) if pr.get("state") == "ok" else None
    acc = acc if acc and acc.get("known") else None
    pairs = {}
    if rec.get("state") == "ok" and acc:
        by = {t["id"]: t for t in acc.get("trades") or []}
        pairs = {lk: by[pid] for lk, pid in L.match(acc.get("trades") or [], rec.get("trades") or []).items()}
    notes = []
    if rec.get("state") == "ok" and rec.get("account") and rec["account"] != account:
        notes.append(f"실행기 기록의 계좌({rec['account']})와 설정의 계좌({account})가 달라요")
    kill = (((raw.get("risk") or {}) if isinstance(raw.get("risk"), dict) else {}).get("kill_file"))
    kill_on = None
    if isinstance(kill, str) and kill:
        try:
            kill_on = os.path.exists(kill)
        except OSError:
            kill_on = None
    closed = rec.get("trades") or [] if rec.get("state") == "ok" else []
    plan = plan_of(raw) if raw else None
    return {
        "now_ms": now, "name_ko": NAME_KO, "account": account,
        "status": status_of(cfg, rec, now),
        "files": {"config": {k: cfg.get(k) for k in ("state", "path", "reason_ko", "reason")},
                  "db": {k: rec.get(k) for k in ("state", "path", "reason_ko", "reason")},
                  "paper": {k: pr.get(k) for k in ("state", "path", "reason_ko", "reason")}},
        "plan": {**plan, **plan_src} if plan else {**plan_src, "lines": [], "state": "none",
                                                  "reason_ko": "설정 파일도 저장소의 설정 원본도 읽지 못했어요"},
        "kill_file": {"path": kill, "present": kill_on} if isinstance(kill, str) and kill else None,
        "notes": notes,
        "position": position_of(rec, raw),
        "today": L.today_of(closed, now, "exit_ts") if rec.get("state") == "ok" else None,
        "record": rec.get("stats") if rec.get("state") == "ok" else None,
        "trades": live_trades(rec, pairs) if rec.get("state") == "ok" else [],
        "paper": paper_view(pr, account, rec.get("since_ms") if rec.get("state") == "ok" else None),
        "follow": follow_of(acc, rec, account, pairs, now),
        "equity": equity_of(rec, plan["budget_usd"] if plan else None),
        "events": (rec.get("events") or [])[:EVENTS_KEEP] if rec.get("state") == "ok" else [],
    }


def register(app, ctx) -> dict:
    from ..app import json_finite

    @app.get("/api/v4/livebots/v39")
    def get_livebots_v39():
        """실거래 › V3.9 투비트: the Toobit executor and the rule bot's V3.9 1-hour paper account it follows: status, the
        plan in words, the open position with its ladder step, today's and recent live trades, paper entries followed or
        missed and why, the equity (read-only, 5 s cache)."""
        p = paths()
        return L._cached("v39:" + json.dumps(p, sort_keys=True), lambda: json_finite(build(p)))

    return {"routes": ["/api/v4/livebots/v39"], "paths": paths}
