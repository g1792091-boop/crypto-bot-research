"""Paper trading engine: simulated fills on real market bars.

Execution rules (fixed, from the handover document):
- Signals come from confirmed bars and fill at the NEXT bar's open, as a
  taker market order with adverse slippage.
- Stops are stop-market: fill at the stop price with adverse slippage, or at
  the bar open if the bar gaps through the stop.
- Take-profit is a resting limit: fills only when price trades through it
  (touching is not enough), at the limit price or a better gapped open,
  with maker fee.
- Isolated margin; liquidation triggers on mark price and costs the whole
  isolated margin.
- One position at a time. Signals that arrive while a position is open are
  recorded as skipped.
- If a bar touches both stop and take-profit, the stop is assumed first.

Drive it with ``step(bars, funding)`` once per base-timeframe bar, after
submitting the signals produced by the previous closed bar.
"""

from __future__ import annotations

from typing import Callable, Optional

from .config import Settings
from .margin import Brackets, liquidation_price
from .models import Bar, Position, Signal, SignalOutcome, TradeRecord
from .notify import CRITICAL, INFO, WARN, NullNotifier, Notifier
from .sizing import size_position, tp_from_roe


class PaperEngine:
    def __init__(self, settings: Settings, brackets: dict[str, Brackets],
                 notifier: Optional[Notifier] = None,
                 symbol_specs: Optional[dict[str, dict]] = None,
                 on_trade: Optional[Callable[[TradeRecord], None]] = None,
                 on_outcome: Optional[Callable[[SignalOutcome], None]] = None,
                 on_equity: Optional[Callable[[int, float, float], None]] = None):
        self.s = settings
        self.brackets = brackets
        self.notifier = notifier or NullNotifier()
        self.specs = symbol_specs or {}
        self.on_trade = on_trade
        self.on_outcome = on_outcome
        self.on_equity = on_equity

        self.wallet = settings.initial_equity
        self.peak_equity = self.wallet
        self.max_drawdown = 0.0
        self.position: Optional[Position] = None
        self.pending: list[Signal] = []
        self.halted = False
        self.halt_reason = ""
        self._warned: set[float] = set()
        self._last_mark: dict[str, float] = {}

        self.trades: list[TradeRecord] = []
        self.outcomes: list[SignalOutcome] = []

    # ------------------------------------------------------------ inputs
    def submit(self, signal: Signal) -> None:
        if signal.symbol not in self.brackets:
            raise ValueError(f"no bracket table for {signal.symbol}")
        self.pending.append(signal)

    def step(self, bars: dict[str, Bar],
             funding: Optional[dict[str, float]] = None) -> None:
        """Process one aligned bar per symbol. ``funding`` maps symbol to the
        funding rate settled at the open of these bars."""
        entered_now = self._handle_entries(bars)
        if self.position is not None:
            bar = bars.get(self.position.symbol)
            if bar is not None:
                self._handle_exit(bar, entry_bar=entered_now)
        if funding and self.position is not None:
            rate = funding.get(self.position.symbol)
            bar = bars.get(self.position.symbol)
            if rate is not None and bar is not None:
                self._apply_funding(rate, bar.m_open)
        for sym, bar in bars.items():
            self._last_mark[sym] = bar.m_close
        ts = max(b.close_time for b in bars.values()) if bars else 0
        self._mark_to_market(ts, bars)

    def kill(self, ts: int, bars: dict[str, Bar], reason: str = "manual kill") -> None:
        """Emergency stop: close any position at the bar close and halt."""
        if self.position is not None and self.position.symbol in bars:
            bar = bars[self.position.symbol]
            self._close_market(bar.close, ts, "MANUAL")
        self._halt(reason)

    def resume(self) -> None:
        self.halted = False
        self.halt_reason = ""
        self.peak_equity = self.equity()
        self._warned.clear()
        self.notifier.send(WARN, "engine resumed by operator")

    # ------------------------------------------------------------ state
    def equity(self) -> float:
        if self.position is None:
            return self.wallet
        mark = self._last_mark.get(self.position.symbol, self.position.entry_price)
        return self.wallet + self._unrealized(self.position, mark)

    @staticmethod
    def _unrealized(p: Position, price: float) -> float:
        return p.side * p.qty * (price - p.entry_price)

    # ------------------------------------------------------------ entries
    def _record(self, sig: Signal, status: str, reason: str, ts: int,
                **detail) -> None:
        out = SignalOutcome(sig, status, reason, ts, detail)
        self.outcomes.append(out)
        if self.on_outcome:
            self.on_outcome(out)

    def _rank_key(self, sig: Signal) -> tuple:
        pri = self.s.symbol_priority
        idx = pri.index(sig.symbol) if sig.symbol in pri else len(pri)
        return (-sig.score, idx, sig.strategy_id, sig.timeframe)

    def _handle_entries(self, bars: dict[str, Bar]) -> bool:
        if not self.pending:
            return False
        pending, self.pending = self.pending, []
        ready = []
        for sig in pending:
            bar = bars.get(sig.symbol)
            if bar is None:
                self._record(sig, "REJECTED", "no next bar", sig.ts)
            elif bar.open_time < sig.ts:
                self._record(sig, "REJECTED", "signal from the future", bar.open_time)
            else:
                ready.append((sig, bar))
        if not ready:
            return False
        if self.halted:
            for sig, bar in ready:
                self._record(sig, "REJECTED", f"halted: {self.halt_reason}", bar.open_time)
            return False
        if self.s.single_position and self.position is not None:
            held = self.position
            for sig, bar in ready:
                self._record(sig, "SKIPPED", "in position", bar.open_time,
                             held_symbol=held.symbol,
                             held_strategy=held.signal.strategy_id)
            return False

        ready.sort(key=lambda x: self._rank_key(x[0]))
        entered = False
        for sig, bar in ready:
            if entered:
                self._record(sig, "SKIPPED", "lower score than entered signal",
                             bar.open_time)
                continue
            entered = self._try_enter(sig, bar)
        return entered

    def _try_enter(self, sig: Signal, bar: Bar) -> bool:
        side = sig.side
        fill = bar.open * (1 + side * self.s.slippage_frac)
        spec = self.specs.get(sig.symbol, {})
        dec = size_position(self.s, self.wallet, side, fill, sig.stop_price,
                            sig.tier, self.brackets[sig.symbol], atr=sig.atr,
                            qty_step=spec.get("qty_step", 0.0),
                            min_notional=spec.get("min_notional", 0.0))
        if not dec.ok:
            self._record(sig, "REJECTED", "sizing", bar.open_time,
                         reasons=dec.reasons, fill=fill)
            return False
        notional = dec.qty * fill
        fee = notional * self.s.taker_fee
        self.wallet -= fee
        roe = sig.tp_roe if sig.tp_roe is not None else self.s.default_tp_roe
        tp = tp_from_roe(side, fill, dec.leverage, roe)
        self.position = Position(
            signal=sig, symbol=sig.symbol, side=side, qty=dec.qty,
            entry_price=fill, entry_time=bar.open_time, leverage=dec.leverage,
            tier=dec.tier, margin=dec.margin, margin_initial=dec.margin,
            stop_price=sig.stop_price, tp_price=tp, liq_price=dec.liq_price,
            entry_fee=fee, mae_price=fill, mfe_price=fill)
        self._record(sig, "ENTERED", "ok", bar.open_time, tier=dec.tier,
                     leverage=dec.leverage, margin=dec.margin, fill=fill,
                     downgrades=dec.reasons)
        self.notifier.send(INFO, (
            f"ENTRY {sig.symbol} {'LONG' if side > 0 else 'SHORT'} {sig.strategy_id} "
            f"{dec.tier} {dec.leverage}x margin {dec.margin:.2f} @ {fill:.6g} "
            f"SL {sig.stop_price:.6g} TP {tp:.6g} LIQ {dec.liq_price:.6g}"))
        return True

    # ------------------------------------------------------------ exits
    def _handle_exit(self, bar: Bar, entry_bar: bool) -> None:
        p = self.position
        assert p is not None
        side = p.side
        if side > 0:
            p.mae_price = min(p.mae_price, bar.low)
            p.mfe_price = max(p.mfe_price, bar.high)
        else:
            p.mae_price = max(p.mae_price, bar.high)
            p.mfe_price = min(p.mfe_price, bar.low)

        if not entry_bar:
            if (bar.m_open - p.liq_price) * side <= 0:
                self._liquidate(bar.open_time)
                return
            if (bar.open - p.stop_price) * side <= 0:
                self._close(bar.open * (1 - side * self.s.slippage_frac),
                            bar.open_time, "SL", maker=False)
                return
            if (bar.open - p.tp_price) * side > 0:
                self._close(bar.open, bar.open_time, "TP", maker=True)
                return

        low, high = bar.low, bar.high
        hit_stop = (low <= p.stop_price) if side > 0 else (high >= p.stop_price)
        hit_tp = (high > p.tp_price) if side > 0 else (low < p.tp_price)
        m_low, m_high = bar.m_low, bar.m_high
        hit_liq = (m_low <= p.liq_price) if side > 0 else (m_high >= p.liq_price)

        if hit_stop and hit_tp and not self.s.stop_first_on_ambiguous_bar:
            self._close(p.tp_price, bar.close_time, "TP", maker=True)
        elif hit_stop:
            self._close(p.stop_price * (1 - side * self.s.slippage_frac),
                        bar.close_time, "SL", maker=False)
        elif hit_liq:
            # Mark price reached liquidation without last price hitting the stop.
            self._liquidate(bar.close_time)
        elif hit_tp:
            self._close(p.tp_price, bar.close_time, "TP", maker=True)

    def _close_market(self, price: float, ts: int, reason: str) -> None:
        p = self.position
        assert p is not None
        self._close(price * (1 - p.side * self.s.slippage_frac), ts, reason, maker=False)

    def _close(self, price: float, ts: int, reason: str, maker: bool) -> None:
        p = self.position
        assert p is not None
        gross = p.side * p.qty * (price - p.entry_price)
        # Isolated margin caps the loss; beyond that the position is liquidated.
        if gross < -p.margin:
            self._liquidate(ts)
            return
        fee_rate = self.s.maker_fee if maker else self.s.taker_fee
        exit_fee = p.qty * price * fee_rate
        self.wallet += gross - exit_fee
        self._finish(price, ts, reason, exit_fee)

    def _liquidate(self, ts: int) -> None:
        p = self.position
        assert p is not None
        self.wallet -= p.margin
        self._finish(p.liq_price, ts, "LIQ", exit_fee=0.0, forced_pnl=-p.margin)
        self.notifier.send(CRITICAL, (
            f"LIQUIDATED {p.symbol} {p.leverage}x lost margin {p.margin_initial:.2f}"))

    def _finish(self, price: float, ts: int, reason: str, exit_fee: float,
                forced_pnl: Optional[float] = None) -> None:
        p = self.position
        assert p is not None
        gross = forced_pnl if forced_pnl is not None else p.side * p.qty * (price - p.entry_price)
        net = gross - p.entry_fee - exit_fee - p.funding_paid
        rec = TradeRecord(
            strategy_id=p.signal.strategy_id, symbol=p.symbol,
            timeframe=p.signal.timeframe, side=p.side, signal_ts=p.signal.ts,
            entry_time=p.entry_time, entry_price=p.entry_price, exit_time=ts,
            exit_price=price, exit_reason=reason, qty=p.qty, leverage=p.leverage,
            tier=p.tier, margin=p.margin_initial, stop_price=p.stop_price,
            tp_price=p.tp_price, liq_price=p.liq_price,
            fees=p.entry_fee + exit_fee, funding=p.funding_paid, pnl=net,
            roe=net / p.margin_initial,
            price_move=p.side * (price / p.entry_price - 1),
            mae_price=p.mae_price, mfe_price=p.mfe_price,
            equity_after=self.wallet, score=p.signal.score)
        self.trades.append(rec)
        self.position = None
        if self.on_trade:
            self.on_trade(rec)
        self.notifier.send(INFO, (
            f"EXIT {rec.symbol} {reason} pnl {rec.pnl:+.2f} ROE {rec.roe:+.1%} "
            f"equity {self.wallet:.2f}"))

    # ------------------------------------------------------------ funding
    def _apply_funding(self, rate: float, mark: float) -> None:
        p = self.position
        assert p is not None
        payment = p.side * p.qty * mark * rate  # positive = we pay
        self.wallet -= payment
        p.margin -= payment
        p.funding_paid += payment
        bracket = self.brackets[p.symbol].for_notional(p.qty * p.entry_price)
        p.liq_price = liquidation_price(p.side, p.qty, p.entry_price, p.margin, bracket)

    # ------------------------------------------------------------ risk
    def _mark_to_market(self, ts: int, bars: dict[str, Bar]) -> None:
        eq = self.equity()
        if eq > self.peak_equity:
            self.peak_equity = eq
            self._warned.clear()
        dd = 1 - eq / self.peak_equity if self.peak_equity > 0 else 0.0
        self.max_drawdown = max(self.max_drawdown, dd)
        if self.on_equity:
            self.on_equity(ts, eq, dd)
        if self.halted:
            return
        for lvl in self.s.dd_warn_levels:
            if dd >= lvl and lvl not in self._warned:
                self._warned.add(lvl)
                self.notifier.send(WARN, f"drawdown {dd:.1%} (level {lvl:.0%}), equity {eq:.2f}")
        if dd >= self.s.dd_halt:
            if self.position is not None and self.position.symbol in bars:
                self._close_market(bars[self.position.symbol].close, ts, "HALT")
            self._halt(f"drawdown {dd:.1%} reached halt level {self.s.dd_halt:.0%}")

    def _halt(self, reason: str) -> None:
        self.halted = True
        self.halt_reason = reason
        self.notifier.send(CRITICAL, f"ENGINE HALTED: {reason}. Operator action required.")

    # ------------------------------------------------------------ report
    def summary(self) -> dict:
        n = len(self.trades)
        wins = sum(1 for t in self.trades if t.pnl > 0)
        return {
            "settings_version": self.s.version,
            "trades": n,
            "win_rate": wins / n if n else None,
            "net_pnl": sum(t.pnl for t in self.trades),
            "fees": sum(t.fees for t in self.trades),
            "funding": sum(t.funding for t in self.trades),
            "liquidations": sum(1 for t in self.trades if t.exit_reason == "LIQ"),
            "final_equity": self.equity(),
            "max_drawdown": self.max_drawdown,
            "signals": len(self.outcomes),
            "skipped": sum(1 for o in self.outcomes if o.status == "SKIPPED"),
            "rejected": sum(1 for o in self.outcomes if o.status == "REJECTED"),
            "halted": self.halted,
        }
