"""실거래 › 비용 › 수수료 줄이기 (owners 10/21 night: the 7/1~10/20 replay of the 추세판단 봇 was about break-even before
costs and the costs took about 4.5 %p a trade, so the costs are the main loss). Sent inside GET /api/v4/livebots/costs as
``fees`` (livebots.costs); read-only like every 실거래 tab, nothing here changes an executor (an order type is the owners'
decision).

Per executor (its own database, executor.py tables, read-only), each closed trade:
    fees paid     from its exchange fills (``fills``: commission per fill; the entry fills are the opening side's, the
                  rest the exit's), the trade's total the executor booked from those fills (``trades.commission``)
    slippage      each fill against the price the executor saw when it decided (livepnl.trade_costs: entry = the last
                  price just before the order, ``entry_ref``; exit = the stop level for an exchange stop, the last price
                  before a market close, ``exit_ref``); + = worse for us; the trade's total as booked (``trades.slippage``)
    before costs  net P&L + fees + slippage - funding received (the price move at the reference prices); per trade also
                  as net-ROE points of its margin (entry price x qty / leverage), so a 30x and a 40x trade compare
    share         the part of the before-cost profit the fees and the slippage took (None when there was no profit
                  before costs: then the costs only made a loss bigger, said in words on the page)
    limit (가상)  the same trades with the fees at the exchange's documented maker rate: the entry only (the realistic
                  case: exits are exchange stop orders or market closes, filled as taker) and both sides (the most it
                  could be). The slippage is kept as measured (a limit filled at its price would not have the entry
                  slippage either, shown apart); a limit that does not fill is a trade that never happened, and that risk is
                  not in the number. A maker rate the repository does not document is None (모름), never invented.
A trade counts in the sums only when its cost was measured from its fills (``pnl_source`` fills, commission and
slippage booked, ``cost_ok`` not 0: livereplayref.exec_row's rule, so the 재현 비교 tab's 비용 쪼개기 agrees); the others are
counted and said (지갑 변화로 어림 · 비용 못 잼), never a zero. Two spans: since the trend bot's start (``trend_since``) and
all of the executor's trades (전환 전 포함), each labelled.

The paper bot: its trades since the start with the fees it booked and the slippage its fills carry at the rule's rate
(livereplayref.paper_row: the paper's assumed rates, said so).

States (CONTRACT 1.6): an executor database not there = missing, unreadable = error; a source that is not the trend bot
counts all its trades and says so. Ratios are ratios (0.0002 = 0.02 %), money is USDT, times UTC ms.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Optional

from . import livebots as L

QUOTE = ("USDT", "USDC")                 # livepnl.QUOTE_ASSETS: a commission in another asset cannot be split here
ROWS_KEEP = 12                           # trades listed per span (newest first)
# Each exchange's fee per side at the basic tier, as this repository documents it (the owners' own tier may differ: the
# page says so). A maker rate the repository does not document is None (the page says 모름); never guessed.
#   bybit    docs/live1019-start-ko.md "거래소 수수료 (10/19 새벽 확인)": VIP0 USDT perpetual taker 0.055 %, maker 0.02 %
#   wooxpro  docs/wooxpro-ko.md "수수료": market (taker) 0.06 % a side, 0.042 % after the TetherMax sign-up (executor.py
#            NET_COSTS, deploy/executor.live-wooxpro.json net_costs); no maker rate is written anywhere (the drill prints
#            the API's maker_pct: once the owners read it off, it goes here)
#   mexc     docs/mexc-ko.md (MEXC notice 2026-06-01): API futures maker 0.06 %, taker 0.08 %
#   binance  docs/trade-review-system.md: USDⓈ-M VIP0 maker 0.02 %, taker 0.05 %
RATES = {
    "bybit": {"taker": 0.00055, "maker": 0.0002, "src": "docs/live1019-start-ko.md",
              "src_ko": "일반 등급(VIP0) 무기한 선물 · 10/19 확인"},
    "wooxpro": {"taker": 0.0006, "taker_disc": 0.00042, "maker": None, "src": "docs/wooxpro-ko.md",
                "src_ko": "시장가 0.06% · TetherMax 가입 할인이면 0.042% · 메이커 요율은 문서에 없어요 (drill 결과의 maker_pct로 확인)"},
    "mexc": {"taker": 0.0008, "maker": 0.0006, "src": "docs/mexc-ko.md", "src_ko": "API 주문 요율 · MEXC 공지 2026-06-01"},
    "binance": {"taker": 0.0005, "maker": 0.0002, "src": "docs/trade-review-system.md", "src_ko": "USDⓈ-M VIP0"},
}
RATES_KO = "기본 등급 요율 · 두 분 계정 등급에 따라 다를 수 있어요"
LIMIT_RISK_KO = ("지정가 주문은 안 채워질 수 있어요: 안 채워졌으면 그 거래는 없었던 거고, 그 위험(놓친 이익·피한 손실)은 이 숫자에 "
                 "들어 있지 않아요")
EXIT_LIMIT_KO = "청산까지 지정가는 최대치예요: 손절·계단 익절은 거래소 손절 주문이라 시장가(테이커)로 나가요"
WHO_KO = "실행기를 지정가로 바꿀지는 두 분이 정해요 · 이 화면은 계산만 보여 드리고 아무것도 바꾸지 않아요"
PAPER_KO = "페이퍼(연습)는 규칙에 넣은 가정 요율로 계산해요 (실제 체결이 아니에요)"
SINCE_KO = "추세판단 봇 시작부터"
ALL_KO = "전체 거래 (전환 전 포함)"
NOT_TREND_KO = "지금 페이퍼 봇이 추세판단 봇이 아니라서 시작 시각이 없어요 · 전체 거래만 셌어요"


def _f(x) -> Optional[float]:
    return L._f(x)


def _sum(xs: list) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return sum(xs) if xs else None


def _mean(xs: list) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def rates_of(exchange: Optional[str]) -> dict:
    """The documented rates of an exchange ({taker, maker (None = 모름), src, src_ko}); an unknown exchange: both None."""
    r = RATES.get(exchange or "")
    if r is None:
        return {"exchange": exchange, "taker": None, "taker_disc": None, "maker": None, "src": None,
                "src_ko": "이 거래소의 요율은 문서에 없어요"}
    return {"exchange": exchange, "taker_disc": None, **r}


# ================================================================ one executor's database
def read_extra(path: str) -> dict:
    """{trade key: {"data": the trade's record (entry_ref, exit_ref, stop), "cost_ok": 1 / 0 / None, "fills": [...]}}
    of an executor's database (one read-only snapshot); a state dict when it cannot be read."""
    try:
        conn = L.open_ro(path)
    except FileNotFoundError:
        return L._missing(path)
    except (OSError, sqlite3.Error) as exc:
        return L._err(path, exc)
    try:
        conn.execute("BEGIN")
        tables = L._tables(conn)
        if "trades" not in tables:
            return L._missing(path, L.NO_TABLE_KO)
        ok_col = "cost_ok" if "cost_ok" in L._cols(conn, "trades") else "NULL"
        out = {str(k): {"data": L._j(d), "cost_ok": None if ok is None else int(ok), "fills": []}
               for k, d, ok in conn.execute(f"SELECT key, data, {ok_col} FROM trades WHERE exit_ts IS NOT NULL")}
        if "fills" in tables:
            for key, d in conn.execute("SELECT trade_key, data FROM fills ORDER BY ts, id"):
                if str(key) in out:
                    try:
                        f = json.loads(d or "{}")
                    except ValueError:
                        continue
                    if isinstance(f, dict):
                        out[str(key)]["fills"].append(f)
    except sqlite3.Error as exc:
        return L._err(path, exc)
    finally:
        conn.close()
    return {"state": "ok", "path": path, "trades": out}


def split_fills(side: int, fills: list) -> dict:
    """The fills of one trade by side: {qty_in, qty_out, n_in, n_out (notional), avg_in, avg_out, fee_in, fee_out}; a
    fee side is None when a commission was paid in another asset (it cannot be told in USDT here) or the side has no fill."""
    open_side = "BUY" if side > 0 else "SELL"
    out = {}
    for k, part in (("in", [f for f in fills if f.get("side") == open_side]), ("out", [f for f in fills if f.get("side") != open_side])):
        qty = sum(_f(f.get("qty")) or 0.0 for f in part)
        notional = sum((_f(f.get("qty")) or 0.0) * (_f(f.get("price")) or 0.0) for f in part)
        quote = all(f.get("commissionAsset") in QUOTE + (None,) for f in part)
        out[f"qty_{k}"] = qty or None
        out[f"n_{k}"] = notional or None
        out[f"avg_{k}"] = notional / qty if qty else None
        out[f"fee_{k}"] = sum(_f(f.get("commission")) or 0.0 for f in part) if part and quote else None
    return out


def trade_cost(t: dict, extra: Optional[dict], maker: Optional[float]) -> dict:
    """One closed executor trade (livebots._live_trade) with its costs: fees (entry / exit), slippage (entry / exit),
    funding, before costs, each as USDT and as net-ROE points of its margin; the maker case. ``measured`` False: not in
    the sums (``why``: est = a wallet estimate, unmeasured = its cost could not be measured from its fills)."""
    extra = extra or {}
    side, m = int(t.get("side") or 0), _f(t.get("margin"))
    fills = extra.get("fills") or []
    sp = split_fills(side, fills) if fills else {}
    d = extra.get("data") or {}
    e_ref, x_ref = _f(d.get("entry_ref")), _f(d.get("exit_ref")) or _f(d.get("stop"))
    slip_in = sp["qty_in"] * side * (sp["avg_in"] - e_ref) if sp.get("avg_in") and e_ref else None
    slip_out = sp["qty_out"] * side * (x_ref - sp["avg_out"]) if sp.get("avg_out") and x_ref else None
    fee, slip, fund, pnl = _f(t.get("commission")), _f(t.get("slippage")), _f(t.get("funding")) or 0.0, _f(t.get("pnl"))
    measured = (not t.get("est")) and fee is not None and slip is not None and extra.get("cost_ok") != 0 and pnl is not None
    why = None if measured else ("est" if t.get("est") else "unmeasured")
    row = {"key": t.get("key"), "symbol": t.get("symbol"), "side": side, "leverage": t.get("leverage"), "entry_time": t.get("entry_ts"),
           "exit_time": t.get("exit_ts"), "margin": m, "pnl": pnl, "roe": _f(t.get("roe")), "measured": measured, "why": why,
           "fills": len(fills), "fee": fee if measured else None, "fee_in": sp.get("fee_in") if measured else None,
           "fee_out": sp.get("fee_out") if measured else None, "slip": slip if measured else None,
           "slip_in": slip_in if measured else None, "slip_out": slip_out if measured else None,
           "funding": fund if measured else None, "n_in": sp.get("n_in"), "n_out": sp.get("n_out"),
           "before": None, "before_roe": None, "fee_roe": None, "slip_roe": None, "funding_roe": None,
           "maker_in": None, "maker_both": None}
    if not measured:
        return row
    before = pnl + fee + slip - fund
    row["before"] = before
    if m and m > 0:
        row.update(before_roe=before / m, fee_roe=fee / m, slip_roe=slip / m, funding_roe=fund / m)
    if maker is not None and sp.get("n_in"):
        # the entry at the maker rate (the exit as paid), and both sides at the maker rate (the most it could be)
        if row["fee_in"] is not None:
            save = row["fee_in"] - sp["n_in"] * maker
            row["maker_in"] = {"fee": fee - save, "save": save, "pnl": pnl + save, "save_roe": save / m if m else None,
                               "roe": (pnl + save) / m if m else None}
        if sp.get("n_out"):
            save = fee - (sp["n_in"] + sp["n_out"]) * maker
            row["maker_both"] = {"fee": fee - save, "save": save, "pnl": pnl + save, "save_roe": save / m if m else None,
                                 "roe": (pnl + save) / m if m else None}
    return row


def _maker_sum(rows: list, k: str, maker: Optional[float]) -> Optional[dict]:
    xs = [r[k] for r in rows if r.get(k)]
    if maker is None or not xs:
        return None
    return {"n": len(xs), "fee": sum(x["fee"] for x in xs), "save": sum(x["save"] for x in xs), "pnl": sum(x["pnl"] for x in xs),
            "save_roe": _mean([x["save_roe"] for x in xs]), "roe": _mean([x["roe"] for x in xs]),
            "pnl_paid": sum(r["pnl"] for r in rows if r.get(k))}


def block(rows: list, maker: Optional[float]) -> dict:
    """The sums of one span's trades (only the measured ones; the rest counted): fees (entry / exit), slippage (entry /
    exit), funding, net and before-cost P&L, the per-trade means in net-ROE points, the share of the before-cost profit the
    fees and the slippage took (None without a profit before costs), the fee rate really paid a side, the maker case."""
    m = [r for r in rows if r["measured"]]
    fee, slip, before, pnl = _sum([r["fee"] for r in m]), _sum([r["slip"] for r in m]), _sum([r["before"] for r in m]), _sum([r["pnl"] for r in m])
    split = [r for r in m if r["fee_in"] is not None and r["fee_out"] is not None]
    sl_split = [r for r in m if r["slip_in"] is not None and r["slip_out"] is not None]
    notional = [r for r in m if r["n_in"] and r["n_out"]]
    nsum = sum(r["n_in"] + r["n_out"] for r in notional)
    profit = before is not None and before > 0
    return {"n": len(rows), "measured": len(m), "est": sum(1 for r in rows if r["why"] == "est"),
            "unmeasured": sum(1 for r in rows if r["why"] == "unmeasured"),
            "fee": fee, "fee_in": _sum([r["fee_in"] for r in split]), "fee_out": _sum([r["fee_out"] for r in split]), "fee_split_n": len(split),
            "slip": slip, "slip_in": _sum([r["slip_in"] for r in sl_split]), "slip_out": _sum([r["slip_out"] for r in sl_split]),
            "slip_split_n": len(sl_split), "funding": _sum([r["funding"] for r in m]), "pnl": pnl, "before": before,
            "fee_rate": sum(r["fee"] for r in notional) / nsum if nsum else None,
            "before_roe": _mean([r["before_roe"] for r in m]), "fee_roe": _mean([r["fee_roe"] for r in m]),
            "slip_roe": _mean([r["slip_roe"] for r in m]), "funding_roe": _mean([r["funding_roe"] for r in m]),
            "net_roe": _mean([r["roe"] for r in m]),
            "fee_share": fee / before if profit and fee is not None else None,
            "slip_share": slip / before if profit and slip is not None else None,
            "maker_in": _maker_sum(m, "maker_in", maker), "maker_both": _maker_sum(m, "maker_both", maker),
            "small": len(m) < L.SMALL[0],
            "rows": sorted(rows, key=lambda r: (r["exit_time"] or 0, str(r["key"])), reverse=True)[:ROWS_KEEP]}


def exec_part(x: dict, p: dict, since: Optional[int]) -> dict:
    """One executor (livebots.sources entry): its exchange and the documented rates, and the two spans."""
    dk = next(d for ex, _ko, d, _ck in L.EXECS if ex == x["id"])
    cfg = x.get("config") or {}
    r = x["record"]
    exchange = (cfg.get("exchange") if cfg.get("state") == "ok" else None) or r.get("exchange")
    head = {"id": x["id"], "name_ko": x["name_ko"], "exchange": exchange, "rates": rates_of(exchange)}
    if r.get("state") != "ok":
        return {**head, **{k: r.get(k) for k in ("state", "reason_ko", "reason", "path")}}
    ex = read_extra(p[dk])
    if ex.get("state") != "ok":
        return {**head, **{k: ex.get(k) for k in ("state", "reason_ko", "reason", "path")}}
    maker = head["rates"]["maker"]
    rows = [trade_cost(t, ex["trades"].get(str(t["key"])), maker) for t in r.get("trades") or []]
    mine = [row for row, t in zip(rows, r.get("trades") or []) if since is not None and (t.get("entry_ts") or 0) >= since]
    return {**head, "state": "ok", "mode": r.get("mode"), "real": r.get("mode") == "mainnet",
            "since": block(mine, maker) if since is not None else None, "all": block(rows, maker)}


# ================================================================ the paper bot (its assumed rates)
def paper_part(paper: dict, since: Optional[int]) -> dict:
    """The paper bot's trades since the start: the fees it booked and the slippage its fills carry at the rule's rate
    (livereplayref.paper_row), per trade in net-ROE points and summed in USDT, and the shares; its assumed rates."""
    from . import livereplayref as X
    from . import livetape as T
    if paper.get("state") != "ok":
        return {k: paper.get(k) for k in ("state", "reason_ko", "reason", "path")}
    a = (paper.get("accounts") or {}).get(L.ACCOUNT) or {}
    if not a.get("known"):
        return {"state": "missing", "reason_ko": "페이퍼 DB에 이 계좌의 기록이 아직 없어요", "path": paper.get("path")}
    trades = L.trend_since(a.get("trades") or [], since)
    rules = T.rules_of({"fees": None}, {"taker_fee": paper.get("taker_fee")})
    slip = rules["slippage"]
    rows = []
    for t in trades:
        r = X.paper_row(t, slip)
        m = _f(t.get("margin"))
        ok = r["before"] is not None and m
        rows.append({"symbol": t.get("symbol"), "side": t.get("side"), "exit_time": t.get("exit_time"), "measured": bool(ok),
                     "before_roe": r["before"], "fee_roe": r["fee"], "slip_roe": r["slip"], "funding_roe": r["funding"], "roe": r["roe"],
                     "fee": _f(t.get("fees")) if ok else None, "slip": r["slip"] * m if ok else None,
                     "funding": r["funding"] * m if ok else None, "before": r["before"] * m if ok else None, "pnl": _f(t.get("pnl"))})
    m = [r for r in rows if r["measured"]]
    fee, slp, before = _sum([r["fee"] for r in m]), _sum([r["slip"] for r in m]), _sum([r["before"] for r in m])
    profit = before is not None and before > 0
    return {"state": "ok", "taker": rules["taker_fee"], "slip_rate": slip, "n": len(rows), "measured": len(m),
            "fee": fee, "slip": slp, "before": before, "pnl": _sum([r["pnl"] for r in m]),
            "before_roe": _mean([r["before_roe"] for r in m]), "fee_roe": _mean([r["fee_roe"] for r in m]),
            "slip_roe": _mean([r["slip_roe"] for r in m]), "net_roe": _mean([r["roe"] for r in m]),
            "fee_share": fee / before if profit and fee is not None else None,
            "slip_share": slp / before if profit and slp is not None else None, "small": len(m) < L.SMALL[0], "note_ko": PAPER_KO}


def replay_part() -> dict:
    """The replay's costs a trade (7/1~10/20, 가상: livereplayref.replay_costs), for the line on top."""
    from . import livereplayref as X
    ref = X.load_ref()
    if ref.get("state") != "ok":
        return {k: ref.get(k) for k in ("state", "reason_ko", "reason")}
    c = X.replay_costs(ref["d"])
    return {"state": "ok", "window_kst": ref["d"]["window_kst"], "n": c["n"], "before": c["before"], "slip": c["slip"],
            "fee": c["fee"], "net": c["net"], "cost": c["cost"], "lev_mean": _f(ref["d"]["trades"].get("lev_mean"))}


def fees(p: dict, now: int) -> dict:
    """수수료 줄이기 (module docstring): per executor the two spans and its documented rates, the paper bot, the replay."""
    _configs, _follows, paper, execs = L.sources(p, now)
    tb = L.trend_bot(p["paper"])
    since = tb["since"] if tb else None
    return {"state": "ok", "trend": {"name": tb["name"], "since": since} if tb else None, "since": since,
            "since_ko": SINCE_KO if tb else None, "all_ko": ALL_KO, "not_trend_ko": None if tb else NOT_TREND_KO,
            "execs": [exec_part(x, p, since) for x in execs], "paper": paper_part(paper, since), "replay": replay_part(),
            "rates_ko": RATES_KO, "limit_ko": LIMIT_RISK_KO, "exit_ko": EXIT_LIMIT_KO, "who_ko": WHO_KO, "small_n": L.SMALL[0]}
