"""실거래 › 게이트 봇 (#/gatebot; owners 11-01 "게이트 대시보드 화면 만드는거 진행해줘야지"): the friend's own Gate positions and
what the 게이트 봇 (paperbot/gateguard.py, docs/gate-bot-ko.md) put on them. There is no trading rule: the friend enters by
hand, the bot puts the stop (Gate's 15m ATR(14) x 3, pulled inside the liquidation price) and the ladder (10 % ->
the stop at +8 %, then 2 % steps; since 11-03 in Gate's own ROE, before fees: rules.basis "gross", the bot's
``ladder_basis``; "net" = both fees paid). Read-only from the bot's state file and its config; never the Gate key (the site has
none). A bot not installed, not switched on or not run yet says so; nothing is made up.

    GET /api/v4/livebots/gate

    {now_ms, state ok | off | missing | error, ko (when not ok), unit {active, enabled, state run | fail | stop | off | unknown, ko},
     rules {words, stop_atr, atr_tf_ko, atr_n, first_trigger, first_lock, step, trigger_gap, basis (net | gross), roe_ko,
            liq_keep, fee, coins, poll_s}
     (or {words None, refused_ko}),
     loop {ms, ago_s, fresh}, account {total, available, upnl, ms},
     positions [{contract, coin, side, side_ko, size, entry, lev, cross, liq, margin, upnl, mark, opened_ms, guarded,
                 bot {stop, kind (atr | liq | lock), kind_ko, atr, atr_stop, fee, lock, best, best_roe, next {lock, trigger,
                 price}, hands_off, late, has_stop, seen_ms, closing, roe_now}, to_stop, to_liq}],
     closed [{contract, coin, side, side_ko, entry, exit, pnl, fee, cause, best_roe, lock, opened_ms, end_ms}] (newest
     first), totals {n, wins, losses, unknown, pnl}, log [{ms, level, text}] (newest first)}
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Callable, Optional

from ...ladder import net_roe, roe_price
from . import livebots as L

ROUTE = "/api/v4/livebots/gate"
UNIT = "paperbot-gateguard"
STATE_ENV, STATE_DEFAULT = "PAPERBOT_GATE_STATE", "/var/lib/paperbot/exec/gateguard.json"
CONFIG_ENV, CONFIG_DEFAULT = "PAPERBOT_GATE_CONFIG", "/etc/paperbot/gateguard.json"
FRESH_S = 90                                       # the bot loops every 10 s: a state older than this is not "now"
LOG_SHOW = 40
KIND_KO = {"atr": "15분봉 ATR × 3", "liq": "청산가 안쪽으로 당김", "lock": "계단 잠금"}
UNIT_KO = {"run": "돌고 있음", "fail": "오류로 멈춤", "stop": "꺼져 있음", "off": "설치 전", "unknown": "상태를 못 물어봄"}


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def _ms(s: Any) -> Optional[int]:
    v = _f(s)
    return int(v * 1000) if v else None


def paths() -> dict:
    return {"state": os.environ.get(STATE_ENV) or STATE_DEFAULT, "config": os.environ.get(CONFIG_ENV) or CONFIG_DEFAULT}


def coin_ko(c: str) -> str:
    return str(c or "").replace("_USDT", "")


def rules_of(path: str) -> Optional[dict]:
    """The bot's rules from its config file (gateguard.load_config: the same checks the bot starts with); None when the
    file is not there; ``refused_ko`` when the bot itself would refuse it."""
    if not os.path.exists(path):
        return None
    from ... import gateguard as GG
    try:
        cfg = GG.load_config(path)
    except Exception as exc:  # noqa: BLE001  (a config the bot would refuse: said)
        return {"words": None, "refused_ko": str(exc)[:200]}
    lad = cfg.ladder
    return {"words": cfg.words(), "stop_atr": cfg.stop_atr, "atr_tf_ko": GG.TF_KO.get(cfg.atr_tf, cfg.atr_tf), "atr_n": cfg.atr_n,
            "first_trigger": lad.first_trigger, "first_lock": lad.first_lock, "step": lad.step, "trigger_gap": lad.trigger_gap,
            "basis": cfg.ladder_basis, "roe_ko": cfg.roe_word(), "liq_keep": cfg.liq_keep, "fee": cfg.fee, "coins": cfg.coins, "poll_s": cfg.poll_s}


def unit_of(active: str, enabled: str) -> str:
    """run (running or starting) · fail (systemd stopped it on an error) · off (no unit file: not installed; systemctl
    is-enabled says "not-found" or nothing) · stop (installed, not running) · unknown (systemctl could not be asked)."""
    if not active and not enabled:
        return "unknown"
    if active in ("active", "activating", "reloading"):
        return "run"
    if active == "failed":
        return "fail"
    return "off" if enabled in ("not-found", "") else "stop"


def next_step(rules: Optional[dict], lock: Optional[float]) -> Optional[dict]:
    """The ladder's next lock and the best ROE (on the bot's basis) that arms it (form 1: 10 -> 8, then the same step)."""
    if not rules or rules.get("first_lock") is None:
        return None
    if lock is None:
        return {"lock": rules["first_lock"], "trigger": rules["first_trigger"]}
    nl = float(lock) + float(rules["step"])
    return {"lock": nl, "trigger": nl + float(rules["trigger_gap"])}


def position_view(c: str, live: dict, rec: Optional[dict], rules: Optional[dict]) -> dict:
    side = int(live.get("side") or (rec or {}).get("side") or 0)
    entry, mark, liq = _f(live.get("entry")), _f(live.get("mark")), _f(live.get("liq"))
    out = {"contract": c, "coin": coin_ko(c), "side": side, "side_ko": "롱" if side > 0 else "숏" if side < 0 else "?",
           "size": _f(live.get("size")), "entry": entry, "lev": _f(live.get("lev")), "cross": bool(live.get("cross")),
           "liq": liq if liq else None, "margin": _f(live.get("margin")), "upnl": _f(live.get("upnl")), "mark": mark,
           "opened_ms": _ms(live.get("open_s")), "guarded": rec is not None}
    if rec is not None:
        lock = _f(rec.get("lock"))
        nx = next_step(rules, lock)
        fee = _f(rec.get("fee")) or 0.0
        rt = 0.0 if (rules or {}).get("basis") == "gross" else 2 * fee   # the bot's Config.rt
        lev = _f(rec.get("lev")) or out["lev"]
        base = _f(rec.get("entry")) or entry
        if nx and base and lev and side:                 # (the bot's own formula: paperbot/ladder.py)
            nx["price"] = roe_price(side, base, lev, nx["trigger"], rt)
        stop = _f(rec.get("stop"))
        out["bot"] = {"stop": stop, "kind": rec.get("kind"), "kind_ko": KIND_KO.get(rec.get("kind"), rec.get("kind")),
                      "atr": _f(rec.get("atr")), "atr_stop": _f(rec.get("atr_stop")), "fee": fee, "lock": lock,
                      "best": _f(rec.get("best")), "best_roe": _f(rec.get("best_roe")), "next": nx,
                      "hands_off": bool(rec.get("hands_off")), "late": bool(rec.get("late")), "has_stop": rec.get("stop_id") is not None,
                      "seen_ms": _ms(rec.get("seen_s")), "closing": bool(rec.get("closing")), "roe_now": None}
        if mark and base and lev and side:
            out["bot"]["roe_now"] = net_roe(side, base, mark, lev, rt)
        if mark and stop:
            out["to_stop"] = side * (mark - stop) / mark
    if mark and out["liq"]:
        out["to_liq"] = side * (mark - out["liq"]) / mark
    return out


def view(state: Optional[dict], rules: Optional[dict], unit: tuple, now: int) -> dict:
    """The answer from the bot's state (None: no file yet), its rules (rules_of; None: no config in /etc yet) and its
    unit's (active, enabled) from systemctl (('', '') when it cannot be asked)."""
    active, enabled = (tuple(unit or ("", "")) + ("", ""))[:2]
    ust = unit_of(active, enabled)
    out: dict = {"now_ms": now, "unit": {"active": active, "enabled": enabled, "state": ust, "ko": UNIT_KO[ust]},
                 "rules": rules, "positions": [], "closed": [], "log": [], "totals": {"n": 0, "wins": 0, "losses": 0, "unknown": 0, "pnl": 0.0}}
    if state is None:
        out["state"] = "missing" if rules is None else "off"
        out["ko"] = ("게이트 봇 설정이 아직 서버에 없어요 (설치와 설정 복사: docs/gate-bot-ko.md 4장 A)" if rules is None
                     else "게이트 봇이 아직 한 번도 돌지 않았어요 (켜는 순서: docs/gate-bot-ko.md 4장 B)")
        return out
    out["state"] = "ok"
    loop = _ms(state.get("loop_s"))
    out["loop"] = {"ms": loop, "ago_s": (now - loop) / 1000 if loop else None, "fresh": bool(loop and now - loop <= FRESH_S * 1000)}
    acct = state.get("account") if isinstance(state.get("account"), dict) else None
    if acct:
        out["account"] = {"total": _f(acct.get("total")), "available": _f(acct.get("available")), "upnl": _f(acct.get("upnl")),
                          "ms": _ms(acct.get("s"))}
    live = state.get("live") if isinstance(state.get("live"), dict) else {}
    coins = state.get("coins") if isinstance(state.get("coins"), dict) else {}
    for c in sorted(set(live) | set(coins)):
        lv = live.get(c) if isinstance(live.get(c), dict) else None
        rec = coins.get(c) if isinstance(coins.get(c), dict) else None
        if lv is None and rec is not None:          # (the last loop did not see it: what the bot holds)
            lv = {k: rec.get(k) for k in ("side", "size", "entry", "lev", "liq", "open_s")}
        if lv is not None:
            out["positions"].append(position_view(c, lv, rec, out["rules"]))
    closed = [x for x in state.get("closed") or [] if isinstance(x, dict)]
    for x in sorted(closed, key=lambda r: r.get("end_s") or 0, reverse=True):
        side = int(x.get("side") or 0)
        out["closed"].append({"contract": x.get("contract"), "coin": coin_ko(x.get("contract")), "side": side,
                              "side_ko": "롱" if side > 0 else "숏", "entry": _f(x.get("entry")), "exit": _f(x.get("exit")),
                              "pnl": _f(x.get("pnl")), "fee": _f(x.get("fee")), "cause": x.get("cause"), "best_roe": _f(x.get("best_roe")),
                              "lock": _f(x.get("lock")), "opened_ms": _ms(x.get("open_s")), "end_ms": _ms(x.get("end_s"))})
    known = [x["pnl"] for x in out["closed"] if x["pnl"] is not None]
    out["totals"] = {"n": len(out["closed"]), "wins": sum(1 for v in known if v > 0), "losses": sum(1 for v in known if v <= 0),
                     "unknown": len(out["closed"]) - len(known), "pnl": sum(known)}
    log = [x for x in state.get("log") or [] if isinstance(x, dict)]
    out["log"] = [{"ms": _ms(x.get("s")), "level": x.get("level"), "text": x.get("text")} for x in reversed(log[-LOG_SHOW:])]
    return out


def _read_json(path: str) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else None
    except FileNotFoundError:
        return None


def build(now: Optional[int] = None, unit_state: Optional[Callable] = None) -> dict:
    now = int(time.time() * 1000) if now is None else int(now)
    p = paths()
    try:
        state = _read_json(p["state"])
    except (OSError, ValueError) as exc:
        return {"now_ms": now, "state": "error", "ko": "게이트 봇 상태 파일을 읽지 못했어요", "reason": L.reason_ko(exc, p["state"]),
                "positions": [], "closed": [], "log": []}
    rules = rules_of(p["config"])
    try:
        unit = unit_state(UNIT) if unit_state else ("", "")
    except Exception:  # noqa: BLE001  never the page's failure
        unit = ("", "")
    return view(state, rules, unit, now)


def register(app, ctx) -> dict:
    from ... import livecheck as LC
    from ..app import json_finite

    @app.get("/api/v4/livebots/gate")                   # (= ROUTE: written out for tests/test_dash_v4.py's route list)
    def get_livebots_gate():
        """실거래 › 게이트 봇: the friend's Gate positions and the bot's stops and ladder (read-only, 5 s cache)."""
        key = "gate:" + json.dumps(paths(), sort_keys=True)
        return L._cached(key, lambda: json_finite(build(None, LC.unit_state)))

    return {"routes": [ROUTE]}
