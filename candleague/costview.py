"""실제 비용 (league.json key ``costs``): what trading costs ate in the owner-exit league, per account kind, every figure an ESTIMATE.

The stored closed trade carries its entry / exit price, side, leverage, P&L and ROE, but not its fees, slippage or funding. This module rebuilds
them from what the league's rules say, and says so (every figure is labelled "추정" on the screen):
  * round trip by the rules: taker fee 0.05% + slippage 0.02%, in and out = 0.14% of the position's notional (paperbot.config.Settings), which
    is 0.14% x leverage of the margin (ROE): ``rt_roe``, the mean over the trades whose leverage is stored;
  * fees + funding as the stored prices show them: the price move times the leverage is the ROE before costs, the trade's net ROE is what is
    left, the difference times the margin (P&L / ROE) is what fees and funding took (summary.cost_of). The stored prices already contain the
    fill slippage, so slippage is added on top by the rule (0.04% of notional);
  * a liquidation (LIQ) loses the margin, not a fee: those trades are left out of every cost figure (counted in ``liq``).
A figure that cannot be derived (no leverage, ROE 0, no price) is None ("확인 못 함" on the screen), never a guess.

Pure functions of the closed-trade book ({account id: trades}, runner.closed_trades), the account rows and the lineup (rulex.lineup). Fractions,
not percent. DeepSeek money: the same rule as summary.decision_views (left out of every figure unless ``ds_money``).

The block, ``cost_views(...)``::

    {"equity0", "ds_in_stats", "assumptions": {fee, slip, round_trip}, "headline_ko", "rules_ko": [...], "note_ko": [...], "kinds": [kind, ...]}
    kind = {"role", "suffix", "label_ko", "name_ko", "short_ko", "group", "live", "pooled", "accounts", "trades", "lev_n", "lev_mean", "rt_roe",
            "cost_n", "liq", "fee_funding", "slip", "cost", "per_trade", "net", "gross", "share", "cost_roe", "net_roe", "ratio"}
      fee_funding / slip / cost: dollars over the ``cost_n`` trades (fees + funding as the prices show them; slippage by the rule; their sum);
      per_trade: cost / cost_n; net: the trades' P&L; gross: net + cost; share: cost / gross (None when gross <= 0); cost_roe / net_roe: the mean
      per-trade cost (fees + funding + slippage) and mean net ROE of the same trades; ratio: cost_roe / net_roe (None when net_roe <= 0)."""

from __future__ import annotations

from typing import Optional

from . import exits as X
from .riskview import _div, _group, _name, _num, _r, _shown

TAKER_FEE = 0.0005                    # paperbot.config.Settings.taker_fee (a test keeps them equal)
SLIPPAGE = 0.0002                     # paperbot.config.Settings.slippage_frac
ROUND_TRIP = 2 * (TAKER_FEE + SLIPPAGE)
SUFFIXES = ("-fq", "-ld", "-ldc", "-fqc")     # 실전 후보, 대조, their coin twins
LIVE = "-fq"
POOLED_ROLE = "cost_all"
POOLED_KO = "네 종류 합계"


def _trade(t: dict) -> dict:
    """One closed trade's cost facts: {lev, roe, margin, liq, ff_roe, ff_usd}; a key is None where the stored trade cannot give it."""
    lev, roe, pnl = _num(t.get("leverage")), _num(t.get("roe")), _num(t.get("pnl"))
    out = {"lev": lev if lev and lev > 0 else None, "roe": roe, "pnl": pnl, "margin": None, "liq": t.get("exit_reason") == "LIQ", "ff_roe": None, "ff_usd": None}
    if roe is None or pnl is None or abs(roe) <= 1e-12:
        return out
    margin = pnl / roe
    out["margin"] = margin
    e, x, side = _num(t.get("entry_price")), _num(t.get("exit_price")), _num(t.get("side"))
    if out["lev"] is None or not e or e <= 0 or x is None or not side or out["liq"]:
        return out
    ff = side * (x / e - 1.0) * out["lev"] - roe
    out["ff_roe"], out["ff_usd"] = ff, ff * margin
    return out


def _kind_block(k: dict, trades: list, accounts: int, pooled: bool) -> dict:
    facts = [_trade(t) for t in trades]
    lev = [f["lev"] for f in facts if f["lev"] is not None]
    use = [f for f in facts if f["ff_usd"] is not None and f["margin"] is not None]
    n = len(use)
    ff = sum(f["ff_usd"] for f in use)
    notional = [f["margin"] * f["lev"] for f in use]
    slip = SLIPPAGE * 2 * sum(abs(v) for v in notional)
    cost = ff + slip
    net = sum(f["pnl"] for f in use)
    gross = net + cost
    cost_roe = sum(f["ff_roe"] + 2 * SLIPPAGE * f["lev"] for f in use) / n if n else None
    net_roe = sum(f["roe"] for f in use) / n if n else None
    return {"role": k["role"], "suffix": k.get("suffix"), "label_ko": k.get("label_ko"), "name_ko": k.get("name_ko") or _name(k), "short_ko": k.get("short_ko"),
            "group": _group(k.get("label_ko")), "live": k.get("suffix") == LIVE, "pooled": pooled, "accounts": accounts, "trades": len(facts),
            "lev_n": len(lev), "lev_mean": _r(sum(lev) / len(lev), 2) if lev else None,
            "rt_roe": _r(ROUND_TRIP * sum(lev) / len(lev)) if lev else None,
            "cost_n": n, "liq": sum(1 for f in facts if f["liq"]),
            "fee_funding": _r(ff, 2) if n else None, "slip": _r(slip, 2) if n else None, "cost": _r(cost, 2) if n else None,
            "per_trade": _r(cost / n, 2) if n else None, "net": _r(net, 2) if n else None, "gross": _r(gross, 2) if n else None,
            "share": _r(_div(cost, gross)) if n and gross > 0 else None,
            "cost_roe": _r(cost_roe), "net_roe": _r(net_roe),
            "ratio": _r(_div(cost_roe, net_roe)) if n and net_roe > 0 else None}


def cost_rules_ko() -> list:
    """The "what this is" box (the screen keeps the same text as its fallback; a test keeps them equal)."""
    return [
        "무엇을 보여 주나: 수수료 · 미끄러짐(슬리피지) · 펀딩비가 수익을 얼마나 깎았는지 보여 줍니다. 모두 추정이고 무엇을 하라는 말은 없습니다.",
        "저장되지 않은 값: 거래 기록에는 수수료 · 미끄러짐 · 펀딩비가 따로 저장돼 있지 않아서, 저장된 가격 · 배수 · 손익으로 되짚거나 규칙에서 계산했습니다.",
        "규칙 기준 왕복 비용: 시장가 수수료 0.05% + 미끄러짐 0.02%, 들어갈 때와 나갈 때 모두 해서 포지션 크기의 0.14%입니다. 배수가 클수록 증거금 대비로는 더 크게 느껴집니다 (0.14% × 배수).",
        "되짚은 비용: 가격이 움직인 만큼의 수익률에서 실제 수익률을 빼면 수수료와 펀딩비가 남습니다. 저장된 체결가에는 미끄러짐이 이미 들어 있어서, 미끄러짐은 규칙으로 더했습니다.",
        "강제청산 거래는 증거금을 잃은 것이라 비용 계산에서 뺐습니다.",
    ]


def cost_notes_ko(eq0: float, ds_money: bool) -> list:
    out = [
        f"모든 계좌는 각각 ${eq0:,.0f}에서 시작하는 모의 지갑입니다. 금액은 가상의 돈입니다.",
        "비용은 실제 거래소 명세서가 아니라 추정입니다. 수수료율 · 미끄러짐은 이 리그의 규칙 값을 썼고, 일부 청산이 더 싼 지정가였다면 실제 비용은 조금 더 작을 수 있습니다.",
        "‘총손익’은 순손익에 추정 비용을 다시 더한 값입니다. 총손익이 0 이하이면 비용 비율은 의미가 없어서 ‘확인 못 함’으로 둡니다.",
        "계좌 종류들은 같은 신호를 나눠 쓰므로 ‘네 종류 합계’는 같은 거래가 여러 번 들어 있는 합입니다.",
    ]
    if not ds_money:
        out.append("딥시크 계좌는 금액 숨김 설정이라 모든 숫자에서 뺐습니다.")
    return out


def _fmt_pct(f: Optional[float], dec: int = 2) -> str:
    return "—" if f is None else ("−" if f < 0 and round(abs(f) * 100, dec) else "") + f"{abs(f) * 100:.{dec}f}%"


def _usd(x: float) -> str:
    return ("−" if x < 0 and round(abs(x)) else "") + f"${abs(x):,.0f}"


def _headline(kinds: list) -> str:
    """One sentence of counts about the 실전 후보 (else the first kind shown). Never advice."""
    if not kinds:
        return "아직 보여 줄 계좌 종류가 없습니다"
    f = next((k for k in kinds if k["live"]), kinds[0])
    if not f["cost_n"]:
        return f"{f['name_ko']}: 비용을 되짚을 닫힌 거래가 아직 없습니다."
    share = f"총손익의 {_fmt_pct(f['share'], 1)}" if f["share"] is not None else "총손익이 0 이하라 비율은 확인 못 함"
    return (f"{f['name_ko']}: 추정 비용은 거래 한 번에 평균 증거금의 {_fmt_pct(f['cost_roe'])}이고, 합치면 {_usd(f['cost'])} ({share}) "
            f"입니다 (닫힌 거래 {f['cost_n']:,}건 기준).")


def cost_views(book: dict, rows: list, lineup: Optional[list], equity0: Optional[float] = None, ds_money: bool = False) -> dict:
    """The snapshot's ``costs`` block (see the module doc). Kinds shown: the lineup's -fq, -ld, -ldc, -fqc that have a shown account, and the pooled
    sum of them when there are two or more."""
    eq0 = _num(equity0)
    eq0 = X.start_equity() if eq0 is None or eq0 <= 0 else eq0
    lu = {k["suffix"]: k for k in lineup or [] if k.get("role") and k.get("suffix")}
    by_role: dict = {}
    for r in sorted(rows or [], key=lambda r: str(r.get("id"))):
        if _shown(r, ds_money):
            by_role.setdefault(r.get("role"), []).append(r)
    kinds, pool, pool_accts = [], [], 0
    for sfx in SUFFIXES:
        k = lu.get(sfx)
        accts = by_role.get(k["role"], []) if k else []
        if not accts:
            continue
        trades = [t for a in accts for t in (book or {}).get(a.get("id")) or []]
        kinds.append(_kind_block(k, trades, len(accts), False))
        pool += trades
        pool_accts += len(accts)
    if len(kinds) >= 2:
        kinds.append(_kind_block({"role": POOLED_ROLE, "suffix": None, "label_ko": "메인 · " + POOLED_KO, "name_ko": POOLED_KO, "short_ko": POOLED_KO},
                                 pool, pool_accts, True))
    return {"equity0": _r(eq0, 2), "ds_in_stats": bool(ds_money),
            "assumptions": {"fee": TAKER_FEE, "slip": SLIPPAGE, "round_trip": ROUND_TRIP},
            "headline_ko": _headline(kinds), "rules_ko": cost_rules_ko(), "note_ko": cost_notes_ko(eq0, ds_money), "kinds": kinds}
