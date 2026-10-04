"""Alarm when the entry-strength score fails on live strategy signals (review M2, 2026-10-04).

Under the quality_v1 rule (paperbot/levrule.py) a strategy signal whose strength is missing, errored, fails its
lock-file check (strength_defs/<NAME>.py vs DEFS_BC.sha256) or has no usable value is sized "normal" (30x / 20x),
exactly as the rule says (docs/paper-v3-rules-change-1.md section 6). That is correct but silent: if it happens to
every signal, rule B's day-30 evaluation has no "best" trades and nobody knows. This module only WATCHES; it never
changes a signal or its size:

- ``failure(sig)``: the cause for one signal, or None. Coin-flip signals (no strength by design) and signals of a
  strategy x timeframe WITHOUT quality edges (always "normal", expected) are never failures.
- ``StrengthWatch``: called by live3 after a boundary's signals were submitted. Writes one alert row per boundary
  with failures and sends a WARN Telegram at most once per hour per cause (the count since the last message).
- ``day_counts`` / ``recent_edge_signals``: the same check on signal_log rows, for the 09:20 summary (daily3) and
  launchcheck --stage after.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, Callable, Optional

from . import levrule

# levrule reasons that mean "could have been scored, but was not"
FAIL_REASONS = ("no_strength", "strength_error", "no_values", "error")
CAUSE_KO = {"no_strength": "세기 기록 없음", "strength_error": "세기 계산 오류",
            "hash_mismatch": "세기 정의 잠금(해시) 불일치", "no_values": "쓸 값 없음", "error": "판정 오류"}
TF_KO = {"15m": "15분", "30m": "30분", "1h": "1시간", "4h": "4시간", "1d": "일봉"}
EVERY_MS = 3_600_000


def _get(sig: Any, name: str, default=None):
    return sig.get(name, default) if isinstance(sig, dict) else getattr(sig, name, default)


def _strength(sig: Any):
    meta = _get(sig, "meta") or {}
    ctx = meta.get("ctx") if isinstance(meta, dict) else None
    return ctx.get("strength") if isinstance(ctx, dict) else None


def failure(sig: Any) -> Optional[str]:
    """The cause ("no_strength", "strength_error", "hash_mismatch", "no_values", "error") when a strategy signal of a
    cell WITH quality edges got no quality score, else None. Never raises (an unexpected error is "error")."""
    try:
        strategy, tf = _get(sig, "strategy_id", ""), _get(sig, "timeframe", "")
        if levrule.coin_flip_seed(strategy) is not None:
            return None                                  # coin flips have no strength by design
        if not levrule.edges().get(f"{strategy}|{tf}"):
            return None                                  # no edges: always "normal", as the rule says
        g = levrule.signal_group(sig)
        if g.get("source") == "meta":
            return None                                  # forced group (tests, the checkpoint's engine check)
        reason = g.get("reason")
        if reason not in FAIL_REASONS:
            return None
        if reason == "strength_error":
            err = str((_strength(sig) or {}).get("error", ""))
            if "!= locked" in err or "sha256" in err:
                return "hash_mismatch"
        return reason
    except Exception:  # noqa: BLE001  a watcher never stops the runner
        return "error"


def error_text(sig: Any) -> Optional[str]:
    """The recorded error of the signal's strength or marks, if any (for the message)."""
    try:
        meta = _get(sig, "meta") or {}
        ctx = meta.get("ctx") if isinstance(meta, dict) else None
        if not isinstance(ctx, dict):
            return None
        s = ctx.get("strength")
        if isinstance(s, dict) and s.get("error"):
            return str(s["error"])
        return str(ctx["marks_error"]) if ctx.get("marks_error") else None
    except Exception:  # noqa: BLE001
        return None


def message(cause: str, n: int, cells: Counter, err: Optional[str]) -> str:
    """The owners' WARN (Korean)."""
    top = ", ".join(f"{s} {TF_KO.get(tf, tf)}" + (f" ×{k}" if k > 1 else "")
                    for (s, tf), k in cells.most_common(6))
    more = len(cells) - min(len(cells), 6)
    lines = [f"⚠ 신호 세기 계산 실패 {n}건 · {CAUSE_KO.get(cause, cause)}", "",
             f"전략·봉: {top}" + (f" 외 {more}칸" if more else ""),
             "좋은 자리 판정이 '보통'으로 처리됨 (30·20배)"]
    if err:
        lines.append(f"오류: {err[:160]}")
    lines += ["→ 개발자 확인 (대시보드 알림 목록) · 같은 원인은 1시간에 한 번만 알림"]
    return "\n".join(lines)


class StrengthWatch:
    """Counts failed strength scores of submitted strategy signals; never touches a signal."""

    def __init__(self, store, notifier, now_ms: Callable[[], int], every_ms: int = EVERY_MS):
        self.store, self.notifier, self.now_ms, self.every_ms = store, notifier, now_ms, every_ms
        self.last_sent: dict[str, int] = {}
        self.pending: dict[str, Counter] = {}
        self.pending_err: dict[str, str] = {}
        self.total: Counter = Counter()           # since the runner started (health row)

    def observe(self, boundary: int, subs) -> list[tuple[str, str, str, str]]:
        """``subs``: [(account_id, Signal)] submitted at ``boundary``. Returns the failures found."""
        fails = []
        for _aid, sig in subs:
            cause = failure(sig)
            if cause is None:
                continue
            s, tf, sym = _get(sig, "strategy_id", ""), _get(sig, "timeframe", ""), _get(sig, "symbol", "")
            fails.append((cause, s, tf, sym))
            self.pending.setdefault(cause, Counter())[(s, tf)] += 1
            err = error_text(sig)
            if err and cause not in self.pending_err:
                self.pending_err[cause] = err
        if not fails:
            return fails
        now = self.now_ms()
        self.total.update(c for c, *_ in fails)
        detail = "; ".join(f"{c} {s}@{tf} {sym}" for c, s, tf, sym in fails[:12])
        if self.store is not None:
            self.store.alert(now, "WARN", (f"strength score failed for {len(fails)} strategy signal(s) at {boundary} "
                                           f"(sized normal): {detail}")[:600])
        for cause in sorted({c for c, *_ in fails}):
            last = self.last_sent.get(cause)
            if last is not None and now - last < self.every_ms:
                continue
            cells = self.pending.pop(cause, Counter())
            text = message(cause, sum(cells.values()), cells, self.pending_err.pop(cause, None))
            self.last_sent[cause] = now
            if self.notifier is not None:
                self.notifier.send("WARN", text)
        return fails


# ------------------------------------------------------------------ signal_log (daily summary, launchcheck)
def _row_sig(strategy: str, tf: str, data) -> dict:
    d = json.loads(data) if isinstance(data, str) else (data or {})
    return {"strategy_id": strategy, "timeframe": tf, "symbol": "", "ts": 0,
            "meta": {"ctx": d.get("ctx") if isinstance(d, dict) else None}}


def day_counts(conn, start: int, end: int) -> dict:
    """{"checked", "failed", "causes": {cause: n}, "cells": {"S|tf": n}} over SUBMITTED strategy signals of cells with
    quality edges whose bar closed in [start, end) (signal_log)."""
    out = {"checked": 0, "failed": 0, "causes": {}, "cells": {}}
    causes, cells = Counter(), Counter()
    for strat, tf, data in conn.execute("SELECT strategy, timeframe, data FROM signal_log WHERE status = 'SUBMITTED' "
                                        "AND bar_close >= ? AND bar_close < ?", (start, end)):
        if levrule.coin_flip_seed(strat) is not None or not levrule.edges().get(f"{strat}|{tf}"):
            continue
        out["checked"] += 1
        try:
            cause = failure(_row_sig(strat, tf, data))
        except ValueError:
            cause = "error"
        if cause:
            causes[cause] += 1
            cells[f"{strat}|{tf}"] += 1
    out["failed"] = sum(causes.values())
    out["causes"], out["cells"] = dict(causes), dict(cells)
    return out


def recent_edge_signals(conn, n: int = 20) -> list[Optional[str]]:
    """The cause (None = scored) of the last ``n`` SUBMITTED strategy signals of cells with quality edges, newest
    first."""
    out: list[Optional[str]] = []
    cur = conn.execute("SELECT strategy, timeframe, data FROM signal_log WHERE status = 'SUBMITTED' "
                       "ORDER BY id DESC LIMIT 5000")
    for strat, tf, data in cur:
        if levrule.coin_flip_seed(strat) is not None or not levrule.edges().get(f"{strat}|{tf}"):
            continue
        try:
            out.append(failure(_row_sig(strat, tf, data)))
        except ValueError:
            out.append("error")
        if len(out) >= n:
            break
    return out


def summary_line(counts: Optional[dict]) -> Optional[str]:
    """The 09:20 summary line (daily3.notify_report), None when there is nothing to say."""
    if not counts or not counts.get("checked"):
        return None
    if not counts.get("failed"):
        return f"신호 세기 계산 실패 0/{counts['checked']}"
    causes = ", ".join(f"{CAUSE_KO.get(c, c)} {k}" for c, k in sorted(counts["causes"].items(), key=lambda x: -x[1]))
    return (f"⚠ 신호 세기 계산 실패 {counts['failed']}/{counts['checked']} ({causes}): "
            "그 신호는 '보통'으로 처리됨 · 개발자 확인")
