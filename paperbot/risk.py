"""Risk rules for a live account (testnet or mainnet). Pure functions, no I/O except the kill file.

Every threshold comes from the owners' config (paper v3.1 addendum Q6); nothing has a built-in
default. ``RiskConfig.problems()`` lists what is missing or wrong, and the executor refuses to
start until the list is empty.

Decisions
- ``allow``            go ahead
- ``reduce``           go ahead smaller (quantity and/or leverage cut to the limits)
- ``block``            no new position (an open one keeps its stop)
- ``flatten_and_halt`` close everything now and stop trading until a person clears the halt

Every decision carries its reasons in Korean (the owners read them in alerts and in the db).

Halts are part of ``RiskState``. The executor saves that state in its own database after every
loop, so a halt survives a restart; only ``clear_halt`` (run by a person) lifts it.

Days are UTC days (00:00 UTC = 09:00 KST), the same boundary as the paper runner.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import os
from dataclasses import asdict, dataclass, field, fields
from typing import Callable, Optional

ALLOW, REDUCE, BLOCK, FLATTEN_HALT = "allow", "reduce", "block", "flatten_and_halt"

# config key -> the owners' name for it (docs/paper-v3-rules-addendum.md Q6)
REQUIRED = {
    "daily_max_loss_usd": "하루 최대 손실($)",
    "max_drawdown_pct": "멈춤 낙폭(%)",
    "max_consecutive_losses": "연속 손실 멈춤(번)",
    "max_leverage": "최대 레버리지(배)",
    "max_notional_usd": "포지션 최대 크기($)",
    "allowed_symbols": "거래 허용 코인",
    "kill_file": "비상 정지 파일 경로",
}


@dataclass(frozen=True)
class RiskConfig:
    daily_max_loss_usd: Optional[float] = None
    max_drawdown_pct: Optional[float] = None      # 0.20 = halt at 20 % below the peak
    max_consecutive_losses: Optional[int] = None
    max_leverage: Optional[int] = None
    max_notional_usd: Optional[float] = None
    allowed_symbols: tuple = ()
    kill_file: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "RiskConfig":
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(d) - known)
        if unknown:
            raise ValueError(f"알 수 없는 위험 설정 항목: {', '.join(unknown)}")
        d = dict(d)
        if "allowed_symbols" in d and d["allowed_symbols"] is not None:
            d["allowed_symbols"] = tuple(str(s).upper() for s in d["allowed_symbols"])
        return cls(**d)

    def problems(self) -> list[str]:
        """Korean list of missing or impossible values; empty = ready."""
        out = []
        for key, name in REQUIRED.items():
            v = getattr(self, key)
            if v is None or v == () or v == "":
                out.append(f"{name}({key}) 값이 비어 있습니다")
        if self.daily_max_loss_usd is not None and not self.daily_max_loss_usd > 0:
            out.append("하루 최대 손실은 0보다 커야 합니다")
        if self.max_drawdown_pct is not None and not 0 < self.max_drawdown_pct < 1:
            out.append("멈춤 낙폭은 0과 1 사이 비율로 적습니다(예: 20% → 0.2)")
        if self.max_consecutive_losses is not None and not (
                isinstance(self.max_consecutive_losses, int) and self.max_consecutive_losses >= 1):
            out.append("연속 손실 멈춤은 1 이상의 정수입니다")
        if self.max_leverage is not None and not (isinstance(self.max_leverage, int) and 1 <= self.max_leverage <= 125):
            out.append("최대 레버리지는 1~125 사이 정수입니다")
        if self.max_notional_usd is not None and not self.max_notional_usd > 0:
            out.append("포지션 최대 크기는 0보다 커야 합니다")
        return out


@dataclass
class Decision:
    action: str
    reasons: list = field(default_factory=list)
    qty: Optional[float] = None
    leverage: Optional[int] = None
    kinds: list = field(default_factory=list)     # check_loop: "kill", "halted", "daily", "drawdown", "streak"

    @property
    def ok(self) -> bool:
        return self.action in (ALLOW, REDUCE)

    def text(self) -> str:
        return "; ".join(self.reasons)


@dataclass
class RiskState:
    halted: bool = False
    halt_reason: str = ""
    halted_ts: Optional[int] = None
    peak_equity: Optional[float] = None
    day: Optional[str] = None
    day_start_equity: Optional[float] = None
    consecutive_losses: int = 0
    trades: int = 0
    last_equity: Optional[float] = None
    halt_kinds: Optional[list] = None             # which limits the halt came from (clear_halt resets only those)
    day_start_ts: Optional[int] = None            # when day_start_equity was observed
    peak_ts: Optional[int] = None                 # when peak_equity was observed
    transfers: float = 0.0                        # net deposits (+) / withdrawals (-) applied since tracking began
    transfer_ids: list = field(default_factory=list)   # tranIds already applied (recent)
    transfers_checked: Optional[int] = None       # exchange time up to which transfers were read

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "RiskState":
        if not d:
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})


def utc_day(ts_ms: int) -> str:
    return _dt.datetime.fromtimestamp(ts_ms / 1000, _dt.timezone.utc).strftime("%Y-%m-%d")


def kill_switch_on(cfg: RiskConfig, exists: Callable[[str], bool] = os.path.exists) -> Optional[str]:
    """Korean reason when the kill file is present."""
    if cfg.kill_file and exists(cfg.kill_file):
        return f"비상 정지 파일이 있습니다({cfg.kill_file})"
    return None


# ---------------------------------------------------------------- state updates
def observe_equity(st: RiskState, now_ms: int, equity: float) -> None:
    """Track the peak and the equity at the start of the UTC day."""
    day = utc_day(now_ms)
    if st.day != day:
        st.day, st.day_start_equity, st.day_start_ts = day, equity, now_ms
    if st.peak_equity is None or equity > st.peak_equity:
        st.peak_equity, st.peak_ts = equity, now_ms
    st.last_equity = equity


def apply_transfer(st: RiskState, amount: float, ts_ms: int) -> None:
    """A deposit (+) or withdrawal (-) at ``ts_ms`` is not trading P&L: move the day's starting equity and the
    drawdown peak by the same amount when they were observed before it (an observation after it already
    includes it). Without this a withdrawal of profit reads as a loss (false halt) and a deposit hides one."""
    if st.day_start_equity is not None and (st.day_start_ts is None or ts_ms >= st.day_start_ts):
        st.day_start_equity += amount
    if st.peak_equity is not None and (st.peak_ts is None or ts_ms >= st.peak_ts):
        st.peak_equity += amount
    st.transfers += amount


def record_trade(st: RiskState, pnl: float) -> None:
    st.trades += 1
    st.consecutive_losses = st.consecutive_losses + 1 if pnl < 0 else 0


def halt(st: RiskState, now_ms: int, reason: str, kinds: Optional[list] = None) -> bool:
    """Set the halt (keeps the first reason). True when it was not halted before."""
    if st.halted:
        return False
    st.halted, st.halt_reason, st.halted_ts = True, reason, now_ms
    st.halt_kinds = list(kinds or [])
    return True


def _halt_kinds(st: RiskState) -> set:
    if st.halt_kinds is not None:
        return set(st.halt_kinds)
    kinds = set()                                   # a halt saved before the kinds were recorded: read the reason
    if "낙폭" in st.halt_reason:
        kinds.add("drawdown")
    if "연속 손실" in st.halt_reason:
        kinds.add("streak")
    return kinds


def clear_halt(st: RiskState, equity: Optional[float] = None) -> str:
    """A person lifts the halt. Only the limit that caused it restarts from here: a drawdown halt moves the
    drawdown peak to the current equity, a loss-streak halt sets the streak to 0. Any other halt (the kill file,
    a daily loss, a wrong-side position) keeps both, so a routine stop does not loosen the drawdown or streak
    limits. The day's starting equity never changes (a daily-loss halt cleared on the same day halts again)."""
    reason, kinds = st.halt_reason, _halt_kinds(st)
    st.halted, st.halt_reason, st.halted_ts, st.halt_kinds = False, "", None, None
    if "streak" in kinds:
        st.consecutive_losses = 0
    if "drawdown" in kinds:
        if equity is not None:
            st.peak_equity = equity
        elif st.last_equity is not None:
            st.peak_equity = st.last_equity
    return reason


# ---------------------------------------------------------------- decisions
def check_loop(cfg: RiskConfig, st: RiskState, equity: Optional[float], kill_reason: Optional[str] = None) -> Decision:
    """Checked every loop, before following the paper account. ``observe_equity`` first. ``equity`` None: only the
    kill file, the persisted halt and the loss streak (the executor checks those before reading the account)."""
    reasons, kinds = [], []
    if kill_reason:
        reasons.append(kill_reason)
        kinds.append("kill")
    if st.halted:
        reasons.append(f"멈춤 상태입니다(사람이 풀어야 함): {st.halt_reason}")
        kinds.append("halted")
    if equity is not None and cfg.daily_max_loss_usd is not None and st.day_start_equity is not None:
        loss = st.day_start_equity - equity
        if loss >= cfg.daily_max_loss_usd - 1e-9:
            reasons.append(f"오늘 손실 ${loss:,.2f}가 하루 한도 ${cfg.daily_max_loss_usd:,.2f}에 닿았습니다")
            kinds.append("daily")
    if equity is not None and cfg.max_drawdown_pct is not None and st.peak_equity:
        dd = 1 - equity / st.peak_equity
        if dd >= cfg.max_drawdown_pct - 1e-12:
            reasons.append(f"최고점 ${st.peak_equity:,.2f} 대비 낙폭 {dd:.1%}가 멈춤 기준 "
                           f"{cfg.max_drawdown_pct:.0%}에 닿았습니다")
            kinds.append("drawdown")
    if cfg.max_consecutive_losses is not None and st.consecutive_losses >= cfg.max_consecutive_losses:
        reasons.append(f"연속 손실 {st.consecutive_losses}번이 멈춤 기준 {cfg.max_consecutive_losses}번에 닿았습니다")
        kinds.append("streak")
    if reasons:
        return Decision(FLATTEN_HALT, reasons, kinds=kinds)
    return Decision(ALLOW, ["위험 한도 안입니다"])


def check_entry(cfg: RiskConfig, st: RiskState, symbol: str, qty: float, price: float, leverage: int,
                qty_step: float, min_qty: float = 0.0, min_notional: float = 0.0, stop: Optional[float] = None,
                equity: Optional[float] = None, max_loss_frac: Optional[float] = None,
                cost_frac: float = 0.0) -> Decision:
    """Before a new position: may cut the size or the leverage, or block it.

    With ``stop``: the loss if the stop is hit (price distance plus ``cost_frac`` of the entry and the exit
    notional for fees and slippage) must fit what is left of today's loss limit (``daily_max_loss_usd`` minus
    today's loss so far, from ``st``) and, with ``max_loss_frac`` (the paper rules' own share, passed by the
    executor), that share of the live ``equity``; a larger quantity is cut to fit."""
    if st.halted:
        return Decision(BLOCK, [f"멈춤 상태라 새 진입을 하지 않습니다: {st.halt_reason}"])
    if symbol.upper() not in cfg.allowed_symbols:
        return Decision(BLOCK, [f"{symbol}은(는) 거래 허용 코인이 아닙니다"])
    if not (qty > 0 and price > 0 and leverage >= 1):
        return Decision(BLOCK, [f"주문 값이 이상합니다(수량 {qty}, 가격 {price}, 레버리지 {leverage})"])
    reasons, action = [], ALLOW
    lev = int(leverage)
    if cfg.max_leverage is not None and lev > cfg.max_leverage:
        reasons.append(f"레버리지 {lev}배를 상한 {cfg.max_leverage}배로 낮춥니다")
        lev, action = cfg.max_leverage, REDUCE
    q = qty
    if cfg.max_notional_usd is not None and q * price > cfg.max_notional_usd + 1e-9:
        q = math.floor(cfg.max_notional_usd / price / qty_step + 1e-9) * qty_step
        q = round(q, 12)
        reasons.append(f"크기 ${qty * price:,.2f}를 상한 ${cfg.max_notional_usd:,.2f}에 맞춰 줄입니다")
        action = REDUCE
    if stop is not None and stop > 0 and abs(price - stop) > 0:
        per = abs(price - stop) + (price + stop) * cost_frac         # loss per unit if the stop is hit
        caps = []
        if cfg.daily_max_loss_usd is not None:
            lost = 0.0
            if st.day_start_equity is not None and equity is not None:
                lost = max(0.0, st.day_start_equity - equity)
            caps.append((cfg.daily_max_loss_usd - lost, f"오늘 남은 손실 한도 ${cfg.daily_max_loss_usd - lost:,.2f}"))
        if max_loss_frac is not None and equity is not None and equity > 0:
            caps.append((max_loss_frac * equity, f"계좌 ${equity:,.2f}의 {max_loss_frac:.0%}"))
        for cap, why in caps:
            if q * per > cap + 1e-9:
                q2 = round(math.floor(max(cap, 0.0) / per / qty_step + 1e-9) * qty_step, 12)
                reasons.append(f"손절 때 손실 ${q * per:,.2f}가 {why}를 넘어 수량을 {q:g} → {q2:g}로 줄입니다")
                q, action = q2, REDUCE
    if q < min_qty - 1e-12 or q <= 0:
        return Decision(BLOCK, reasons + [f"줄인 수량 {q}이 거래소 최소 수량 {min_qty}보다 작아 진입하지 않습니다"])
    if min_notional and q * price < min_notional - 1e-9:
        return Decision(BLOCK, reasons + [f"주문 크기 ${q * price:,.2f}가 거래소 최소 ${min_notional:,.2f}보다 작아 "
                                          "진입하지 않습니다"])
    return Decision(action, reasons or ["위험 한도 안입니다"], qty=q, leverage=lev)


def load_config(path: str) -> RiskConfig:
    with open(path, encoding="utf-8") as fh:
        return RiskConfig.from_dict(json.load(fh))


# ---------------------------------------------------------------------------------------------
# leverage stages (owners, 2026-10-01): live trading starts with at most 20x; after 30 days, if the
# live record earns it, the account may run the paper rules' own 20-50x tiers. Code only REVIEWS the
# record; raising ``max_leverage`` stays a person's edit of the config (never automatic).
# ---------------------------------------------------------------------------------------------
LEVERAGE_STAGES = (20, 50)
STAGE_MIN_DAYS = 30
STAGE_MIN_TRADES = 30
STAGE_MAX_DRAWDOWN = 0.25        # of the peak equity, over the live period
STAGE_MAX_COST_RATIO = 1.5       # real trading cost / the cost the paper rules assume (addendum Q6 #4)


def max_drawdown(equity_curve: list) -> float:
    peak, dd = None, 0.0
    for e in equity_curve:
        e = float(e)
        peak = e if peak is None or e > peak else peak
        if peak and peak > 0:
            dd = max(dd, 1 - e / peak)
    return dd


def leverage_stage_review(trades: list, start_ms: int, now_ms: int, equity_curve: list,
                          cost_ratio: Optional[float], paper_pnl: Optional[float],
                          unplanned_halts: int) -> dict:
    """May the live account move from stage 1 (max 20x) to stage 2 (the paper rules' 20-50x)? All must hold:
    30+ days live, 30+ closed trades, live net P&L > 0, the paper account it follows also > 0 over the same
    days, live drawdown < 25 %, real cost <= 1.5x the assumed cost (measured, not missing), and no halt that
    was not one of the planned limits (a bug, a reconcile emergency). Returns {ok, next, reasons (Korean)}."""
    closed = [t for t in trades if t.get("exit_ts") is not None and t.get("pnl") is not None]
    days = (now_ms - start_ms) / 86_400_000
    pnl = sum(float(t["pnl"]) for t in closed)
    dd = max_drawdown(equity_curve)
    checks = [
        (days >= STAGE_MIN_DAYS, f"실거래 기간 {days:.0f}일 (30일 이상 필요)"),
        (len(closed) >= STAGE_MIN_TRADES, f"끝난 거래 {len(closed)}건 (30건 이상 필요)"),
        (pnl > 0, f"실거래 순손익 ${pnl:,.2f} (플러스 필요)"),
        (paper_pnl is not None and paper_pnl > 0,
         "같은 기간 paper 계좌 손익 " + ("확인 안 됨" if paper_pnl is None else f"${paper_pnl:,.2f}") + " (플러스 필요)"),
        (dd < STAGE_MAX_DRAWDOWN, f"최대 낙폭 {dd:.0%} (25% 미만 필요)"),
        (cost_ratio is not None and cost_ratio <= STAGE_MAX_COST_RATIO,
         "실제 비용 ÷ 가정 비용 " + ("아직 계산 안 됨" if cost_ratio is None else f"{cost_ratio:.2f}") + " (1.5 이하 필요)"),
        (unplanned_halts == 0, f"계획에 없던 멈춤 {unplanned_halts}번 (0번 필요)"),
    ]
    ok = all(c for c, _ in checks)
    return {"ok": ok, "next": LEVERAGE_STAGES[1] if ok else LEVERAGE_STAGES[0],
            "reasons": [("통과: " if c else "미달: ") + why for c, why in checks],
            "note": ("조건을 모두 채웠습니다. 두 분이 설정의 max_leverage를 50으로 바꾸면 paper와 같은 20~50배 단계로 돕니다."
                     if ok else "아직 20배 상한을 유지합니다.")}
