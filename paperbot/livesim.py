"""가상 거래 한 번 (livesim): ONE signal of the combined paper bot (paperbot/combo.py, account COMBO@mix) run on the paper
bot's own engine, for 못 탄 신호 성적 (paperbot/livemissed.py, owners 10/19 "못 탄 신호들은 어땠나"). View only: nothing
here trades, sends an order or writes a bot's database.

    rig = rig_of(cfg_raw, taker_fee=...)              # the engine rules of the config the paper bot runs
    sig = signal_of(outcome_json["signal"])           # the Signal exactly as the engine received it
    res = simulate(rig, sig, iter_bars(rule_conn, sig.symbol, entry_ts), entry_ts, wallet=...)

The engine is the paper bot's own class, never a copy of its rules: a fresh ``combo.ComboEngine`` (paperbot/engine.py
``PaperEngine`` with the combined bot's sizing ``FixedLevPolicy``, its stop rules, the house ladder take-profit: lock
``first_lock`` net ROE when the best net ROE reaches ``first_lock + trigger_gap``, then ``step`` steps), built from the
config the paper bot runs (``combo.settings_of``: fees, slippage, the loss cap, the liquidation buffer). The rebuilt
Signal is submitted and the rule bot's 1m bars (paper3.db ``live_bars``, the bars the paper bot steps on, with their
mark-price fields, through ``combo._bar``) are stepped from its entry minute until the trade closes, the bars run out
or ``max_minutes`` pass. The fill, the stop (house ATR, pulled in to fit, or the setting's research stop in the
signal's meta), the size, the liquidation price, the ladder and the exit are the engine's.

What can differ from the paper bot's own numbers (said by the caller where it shows them):
- funding: the paper bot pays Binance's funding rates (FundingFeed), but no database keeps those rates; ``funding``
  takes them when the caller has them ({minute ms: {symbol: rate}}, paid as FundingFeed pays them: every rate at or
  before a stepped minute, at that minute's mark open); without them the virtual result has no funding
  (``FUNDING_NOTE_KO``);
- the wallet (``wallet``): the size follows it (margin = a share of it); the ROE barely does (only the quantity step
  and the bracket tiers). The caller passes the paper account's wallet at that moment when it can read it;
- leverage brackets and coin specs: the config's ``brackets_file`` when it names one, else the repository's saved
  Binance table (research/fullgrid/exchange.json, as paperbot/livereplay.py when Binance cannot be asked); the paper
  bot reads Binance's live table with its read-only key. Only the maintenance margin of the first tier matters at
  these sizes (the liquidation price, so the stop-inside-liquidation check and the pulled-in stops);
- only the signal's own coin is stepped: a minute without that coin's bar is no minute for this position (the engine
  does the same: no bar, no exit check);
- early exit (``early_exit``, off in the live config): the opposite signals that would close the position are not fed.
Never a made-up price: no 1m bar at the entry minute -> state ``no_data``.
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass, field
from typing import Iterable, Iterator, Optional

MIN = 60_000
DAY = 86_400_000
MAX_MINUTES = 14 * 1440            # a virtual trade is followed at most this long
CHUNK_MIN = 720                    # 1m bars read per query (a trade that closes early reads little)
PATH_KEEP = 120                    # points kept by thin_path
FUNDING_NOTE_KO = ("펀딩비는 빠져 있어요: 페이퍼 봇은 바이낸스 펀딩비(8시간마다)를 내지만 그 비율은 어디에도 기록되지 않아서 "
                   "가상 결과에는 넣지 못했어요 (보통 8시간에 순ROE 0.3%p 안팎)")
REJECT_KO = {"sizing": "크기 계산이 거절했어요", "stop rule": "손절 자리가 강제청산 안쪽에 안 맞아요",
             "no next bar": "진입할 분의 1분봉이 없어요", "signal from the future": "신호 시각이 맞지 않아요"}
EXIT_KO = {"SL": "손절", "LOCK": "계단 익절", "LIQ": "강제청산", "HALT": "멈춤 청산", "MANUAL": "수동 청산",
           "REV": "빠른 청산(반대 신호)", "JUDGE": "감독 청산(추세 뒤집힘)", "TIME": "감독 청산(시간 정리)"}


@dataclass
class Rig:
    """What every simulated trade of one pass shares: the config (combo.ComboConfig), the engine settings, the leverage
    brackets and the coin specs, the initial equity, and notes on where the brackets came from."""
    cfg: object
    settings: object
    brackets: dict
    specs: dict
    initial: float
    notes: list = field(default_factory=list)


def rig_of(cfg_raw: dict, taker_fee: Optional[float] = None, brackets: Optional[dict] = None,
           specs: Optional[dict] = None) -> Rig:
    """The engine rules of a combined-bot config (combo.json, or the ``combo_run`` record of the paper bot's database:
    the config it really runs). ``taker_fee``: the fee the paper bot ran with (``combo_run``'s taker_fee). Keys this
    code does not know are left out (a newer config); raises combo.ComboError on a config the bot itself refuses."""
    from . import combo as C
    from . import livereplay as LR
    known = {f.name for f in dataclasses.fields(C.ComboConfig)}
    raw = {k: v for k, v in dict(cfg_raw or {}).items() if k in known}
    raw.setdefault("paper_db", "-")
    raw.setdefault("db", "-")
    raw.setdefault("members", [])
    raw["telegram"] = False
    cfg = C.ComboConfig.from_dict(raw)
    fee = None if taker_fee is None else float(taker_fee)
    settings = C.settings_of(cfg, **({} if fee is None or not math.isfinite(fee) or fee <= 0 else {"taker_fee": fee}))
    syms = list(cfg.symbols)
    notes = []
    if brackets is None:
        brackets = None
        if cfg.brackets_file:
            try:
                brackets, src = C._brackets(cfg, None)
                notes.append(f"brackets: {src}")
            except (SystemExit, Exception) as exc:  # noqa: BLE001  the saved table, said in the notes
                notes.append(f"brackets: {cfg.brackets_file} unreadable ({type(exc).__name__}), saved table used")
                brackets = None
        if brackets is None:
            brackets, src = LR.file_brackets(syms)
            notes.append(f"brackets: saved table ({src}), the paper bot reads Binance's")
    if specs is None:
        specs = LR.file_specs(syms)
    return Rig(cfg=cfg, settings=settings, brackets=brackets, specs=specs, initial=float(cfg.initial_equity), notes=notes)


def signal_of(d: dict):
    """The Signal as the engine received it, from an outcome's JSON (store3 ``outcomes.data["signal"]``:
    dataclasses.asdict of it)."""
    from .models import Signal
    names = {f.name for f in dataclasses.fields(Signal)}
    kw = {k: v for k, v in dict(d).items() if k in names}
    kw["meta"] = dict(kw.get("meta") or {})
    kw["ts"] = int(kw["ts"])
    kw["side"] = int(kw["side"])
    kw["stop_price"] = float(kw.get("stop_price") or 0.0)
    kw["score"] = float(kw.get("score") or 0.0)
    if kw.get("atr") is not None:
        kw["atr"] = float(kw["atr"])
    return Signal(**kw)


BAR_SQL = ("SELECT ts, symbol, open, high, low, close, volume, mark_open, mark_high, mark_low, mark_close, close_time "
           "FROM live_bars WHERE symbol = ? AND ts >= ? AND ts < ? ORDER BY ts")


def read_bars(conn, symbol: str, a: int, b: int) -> list:
    """The rule bot's 1m bars of one coin with open time in [a, b), as the paper bot reads them (combo._bar)."""
    from .combo import _bar
    cur = conn.execute(BAR_SQL, (symbol, int(a), int(b)))
    cols = [c[0] for c in cur.description]
    return [_bar(dict(zip(cols, r))) for r in cur.fetchall()]


def last_bar_ts(conn, symbol: str) -> Optional[int]:
    r = conn.execute("SELECT ts FROM live_bars WHERE symbol = ? ORDER BY ts DESC LIMIT 1", (symbol,)).fetchone()
    return None if r is None else int(r[0])


def iter_bars(conn, symbol: str, a: int, max_minutes: int = MAX_MINUTES, chunk: int = CHUNK_MIN) -> Iterator:
    """The coin's 1m bars from ``a`` on, read ``chunk`` minutes at a time (a trade that closes early reads little),
    up to ``max_minutes`` and the newest bar there is."""
    end = int(a) + int(max_minutes) * MIN
    last = last_bar_ts(conn, symbol)
    if last is None:
        return
    end = min(end, last + MIN)
    t = int(a)
    while t < end:
        yield from read_bars(conn, symbol, t, min(end, t + chunk * MIN))
        t += chunk * MIN


def _take(rates: dict, ts: int) -> dict:
    """FundingFeed.take: every rate at or before minute ts (a rate that arrived late is paid on the next step)."""
    out = {}
    for t in [k for k in rates if k <= ts]:
        out.update(rates.pop(t))
    return out


def simulate(rig: Rig, sig, bars: Iterable, entry_ts: int, wallet: Optional[float] = None,
             funding: Optional[dict] = None, max_minutes: int = MAX_MINUTES) -> dict:
    """One signal on a fresh ComboEngine (module docstring). ``bars``: the signal coin's 1m bars from ``entry_ts`` on,
    oldest first (``iter_bars``); ``entry_ts``: the minute the paper bot handled the signal (its outcome's step: the
    minute that opens at the signal bar's close). Returns {state, entry, path, exit, latest, best_roe, stop, lock,
    minutes, last_ts, wallet, funding, why}:
      state  "closed" (exit filled), "open" (the bars ran out first: ``latest`` holds the last close and its net ROE),
             "no_data" (no 1m bar of the coin at the entry minute: nothing is made up), "refused" (the engine would not
             enter it: ``why``, ``reject``);
      entry  {ts, price, stop, leverage, margin, qty, liq, fee, stop_rule};
      path   per stepped minute while open {t, c (close), roe (net ROE at the close, the ladder's formula: leverage x
             (side x (close / entry - 1) - round trip - funding / notional)), stop, lock}, then the exit point {t, c,
             roe, stop, lock, exit: True};
      exit   {ts, price, reason, reason_ko, roe (the trade's net pnl / margin, as the paper bot records it), pnl, fees,
             funding, lock, stop, liq (at the exit: funding moves it)}."""
    from . import combo as C
    from .ladder import net_roe
    w = float(rig.initial if wallet is None or not math.isfinite(float(wallet)) or float(wallet) <= 0 else wallet)
    out = {"state": "no_data", "entry": None, "path": [], "exit": None, "latest": None, "best_roe": None, "stop": None,
           "lock": None, "minutes": 0, "last_ts": None, "wallet": w,
           "funding": "included" if funding is not None else "excluded", "why": ""}
    it = iter(bars)
    first = next(it, None)
    while first is not None and first.symbol != sig.symbol:
        first = next(it, None)
    if first is None or int(first.open_time) != int(entry_ts):
        out["why"] = "진입할 분의 1분봉이 없어요" if first is None or int(first.open_time) > int(entry_ts) else \
            "1분봉이 진입 분과 맞지 않아요"
        return out
    e = C.ComboEngine(rig.settings, rig.brackets, combo=rig.cfg, symbol_specs=rig.specs)
    e.wallet = e.peak_equity = w
    e.submit(sig)
    rates = {int(k): dict(v) for k, v in (funding or {}).items()}
    rt = rig.settings.round_trip_cost
    end = int(entry_ts) + int(max_minutes) * MIN
    bar = first
    while bar is not None and int(bar.open_time) < end:
        if bar.symbol == sig.symbol:
            got = _take(rates, int(bar.open_time)) if rates else {}
            e.step({sig.symbol: bar}, got or None)
            out["minutes"] += 1
            out["last_ts"] = int(bar.open_time)
            if out["entry"] is None:
                if e.position is None and not e.trades:
                    rej = [o for o in e.outcomes if o.status != "ENTERED"]
                    o = rej[-1] if rej else None
                    reason = o.reason if o is not None else "?"
                    out.update(state="refused", why=REJECT_KO.get(reason, reason),
                               reject={"reason": reason, "detail": [str(x) for x in (o.detail.get("reasons") or [])] if o else []})
                    return out
                out["entry"] = _entry(e)
            if e.trades:
                return _closed(out, e.trades[0], rt, net_roe)
            p = e.position
            ff = p.funding_paid / p.notional_entry if p.notional_entry else 0.0
            out["path"].append({"t": int(bar.open_time), "c": float(bar.close),
                                "roe": net_roe(p.side, p.entry_price, bar.close, p.leverage, rt, ff),
                                "stop": float(p.stop_price), "lock": p.lock_roe})
        bar = next(it, None)
    p = e.position
    if p is None:                       # cannot happen (closed returns above); kept honest
        return out
    ff = p.funding_paid / p.notional_entry if p.notional_entry else 0.0
    last = out["path"][-1]
    out.update(state="open", latest={"ts": last["t"], "close": last["c"], "roe": last["roe"]},
               best_roe=net_roe(p.side, p.entry_price, p.mfe_price, p.leverage, rt, ff), stop=float(p.stop_price),
               lock=p.lock_roe, funding_paid=float(p.funding_paid))
    return out


def _entry(e) -> dict:
    """The entry as the engine made it (the position, or the trade when it closed in its entry minute)."""
    ent = next((o for o in e.outcomes if o.status == "ENTERED"), None)
    rule = (ent.signal.meta.get("stop_rule") if ent is not None else None) or ""
    p = e.position
    if p is not None:
        return {"ts": int(p.entry_time), "price": float(p.entry_price), "stop": float(p.stop_initial),
                "leverage": int(p.leverage), "margin": float(p.margin_initial), "qty": float(p.qty), "liq": float(p.liq_price),
                "fee": float(p.entry_fee), "stop_rule": rule}
    t = e.trades[0]
    return {"ts": int(t.entry_time), "price": float(t.entry_price), "stop": float(t.stop_initial), "leverage": int(t.leverage),
            "margin": float(t.margin), "qty": float(t.qty), "liq": float(t.liq_price), "fee": None, "stop_rule": rule}


def _closed(out: dict, rec, rt: float, net_roe) -> dict:
    notional = rec.qty * rec.entry_price
    ff = rec.funding / notional if notional else 0.0
    out["exit"] = {"ts": int(rec.exit_time), "price": float(rec.exit_price), "reason": rec.exit_reason,
                   "reason_ko": EXIT_KO.get(rec.exit_reason, rec.exit_reason), "roe": float(rec.roe), "pnl": float(rec.pnl),
                   "fees": float(rec.fees), "funding": float(rec.funding), "lock": rec.lock_roe, "stop": float(rec.stop_price),
                   "liq": float(rec.liq_price)}
    out["path"].append({"t": int(rec.exit_time), "c": float(rec.exit_price), "roe": float(rec.roe), "stop": float(rec.stop_price),
                        "lock": rec.lock_roe, "exit": True})
    out.update(state="closed", best_roe=net_roe(rec.side, rec.entry_price, rec.mfe_price, rec.leverage, rt, ff),
               stop=float(rec.stop_price), lock=rec.lock_roe)
    return out


def simulate_db(rig: Rig, sig, rule_conn, entry_ts: int, wallet: Optional[float] = None, funding: Optional[dict] = None,
                max_minutes: int = MAX_MINUTES) -> dict:
    """``simulate`` on the rule bot's own 1m bars (a read-only connection to paper3.db)."""
    return simulate(rig, sig, iter_bars(rule_conn, sig.symbol, entry_ts, max_minutes), entry_ts, wallet=wallet,
                    funding=funding, max_minutes=max_minutes)


def thin_path(path: list, n: int = PATH_KEEP) -> list:
    """At most ``n`` points of a path: the first, the last (the exit), every lock step, the rest evenly picked."""
    if len(path) <= n:
        return list(path)
    keep = {0, len(path) - 1}
    for i in range(1, len(path)):
        if path[i].get("lock") != path[i - 1].get("lock"):
            keep.add(i)
    room = max(0, n - len(keep))
    if room:
        step = (len(path) - 1) / (room + 1)
        keep |= {round(step * k) for k in range(1, room + 1)}
    return [path[i] for i in sorted(keep)][: max(n, len(keep))]
