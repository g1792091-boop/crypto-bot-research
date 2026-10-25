"""운이냐 고장이냐 (owners 10-25: "vwap 개선판봇 … 연구분석이나 손실 분석 … 매매법 성공을 위해서 필요한 부분들" -> "전부 다
만들어줘"): where a live record of the 'VWAP 개선판' (docs/vwap-bot-ko.md) sits against the bot's own 5-year paper trades.

The yardstick is research/vwap30/band.json (research/vwap30/code/vwband.py: deploy/combo.vwap.json's 5,805 paper trades of
2020-03 .. 2026-10, the same trades as scale.json; nothing in it is a rule). Three checks, each with its verdict:

    win      the win rate of the n closed trades against the 5-year rate (binomial: the chance of this few wins or fewer
             if the bot plays as in the 5 years), the 90 % band of wins for n, and, for reference, the share of the
             5 years' real stretches of about n trades that won this little (good and bad spells kept together)
    streak   the losing run now (the last closed trades with P&L <= 0) against every losing run of the 5 years: how many
             of them reached this length
    dd       the deepest drop of the account since the start (closed trades, compounding) against the deepest drop of the
             5 years' stretches of about n trades, each started fresh (margin 40 % of the account per trade)

Verdicts (each check, then the worst of the three): 정상 범위 (5 % or more of the 5 years was like this or worse), 드묾
(1 to 5 %), 아주 드묾 (under 1 %: "설계와 다르게 돌고 있을 수 있어요"). The 17 days the bot was picked on are a reference
labelled as the picked best period, never a yardstick. HONESTY: the 5-year win rate was below its break-even, so the bot
lost per trade over the 5 years; every answer says so ("정상 범위" means "as in the 5 years", not "making money").

    band(trades, ...)        one account's answer (the paper, or an executor's live trades while it followed this bot)
    lines(b, label)          the morning check's two lines of it
    ref_line(ref)            the morning check's reference line (5 years, the 17 days, the honest words)
    streak_ko(b)             one line for a loss meeting ("지금 2연패 · 5년 연패 1,158번 중 2연패 이상 318번(27%) → 정상 범위")

Read-only: the research file is read (cached by its modification time); a file that cannot be read is said
(state "missing" / "error"), never replaced by numbers written here.
"""
from __future__ import annotations

import json
import math
import os
from typing import Any, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BAND_FILE = os.path.join(ROOT, "research", "vwap30", "band.json")
BAND_SRC = "research/vwap30/band.json"
VERDICTS = ("정상 범위", "드묾", "아주 드묾")
RARE, VERY_RARE = 0.05, 0.01               # 5 % and 1 % of the 5 years
VERY_RARE_KO = "아주 드묾: 설계와 다르게 돌고 있을 수 있어요"
VERDICT_KO = {"정상 범위": "정상 범위", "드묾": "드묾", "아주 드묾": VERY_RARE_KO}
SHORT_KO = {"정상 범위": "정상", "드묾": "드묾", "아주 드묾": "아주 드묾"}
SMALL_N = 20                               # under this many closed trades: 표본 적음 (the live pages' floor)
MARGIN = 0.4                               # the bot's margin share (deploy/combo.vwap.json): the account step of a trade
PICK17_SPAN_KO = "10/05~10/23"
MISSING_KO = f"5년 비교 파일({BAND_SRC})을 못 읽어서 비교하지 못해요"
_cache: dict = {}


# ---------------------------------------------------------------- the research file
def load(path: Optional[str] = None) -> dict:
    """band.json as {"state": "ok", ...}; {"state": "missing" | "error", "reason_ko"} when it cannot be read."""
    path = path or BAND_FILE
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return {"state": "missing", "reason_ko": MISSING_KO, "path": path}
    hit = _cache.get(path)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        if not isinstance(d, dict) or not all(k in d for k in ("trades", "win_rate", "breakeven_win", "streaks", "windows")):
            raise ValueError("band.json without trades / win_rate / breakeven_win / streaks / windows")
        out = {**d, "state": "ok", "src": BAND_SRC}
    except (OSError, ValueError, TypeError) as exc:
        out = {"state": "error", "reason_ko": MISSING_KO, "reason": f"{type(exc).__name__}: {exc}"[:200], "path": path}
    _cache[path] = (mt, out)
    return out


# ---------------------------------------------------------------- small helpers
def verdict_of(share: Optional[float]) -> str:
    """정상 범위 / 드묾 / 아주 드묾 of the share of the 5 years that was like this or worse."""
    if share is None or share >= RARE - 1e-12:
        return VERDICTS[0]
    return VERDICTS[1] if share >= VERY_RARE - 1e-12 else VERDICTS[2]


def worst(vs: list) -> str:
    return max((v for v in vs if v in VERDICTS), key=VERDICTS.index, default=VERDICTS[0])


def share_ko(x: Optional[float]) -> str:
    """"47%" / "2.5%" / "0.3%" / "0.1% 미만"."""
    if x is None:
        return "—"
    if x >= 0.095:
        return f"{x:.0%}"
    if x >= 0.001:
        return f"{x * 100:.1f}%"
    return "0.1% 미만"


def signed_ko(x: float, d: int = 1) -> str:
    """"+1.2%" / "−3.3%" of a ratio (the pages' minus sign)."""
    return ("+" if x >= 0 else "−") + f"{abs(x) * 100:.{d}f}%"


def binom_cdf(k: int, n: int, p: float) -> float:
    """P(X <= k) for X ~ Binomial(n, p) (log space: no overflow for long records)."""
    if k < 0:
        return 0.0
    if k >= n:
        return 1.0
    if p <= 0:
        return 1.0
    if p >= 1:
        return 0.0
    lp, lq = math.log(p), math.log1p(-p)
    lg = math.lgamma(n + 1)
    return min(1.0, sum(math.exp(lg - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * lp + (n - i) * lq) for i in range(k + 1)))


def binom_q(q: float, n: int, p: float) -> int:
    """The smallest k with P(X <= k) >= q."""
    for k in range(n + 1):
        if binom_cdf(k, n, p) >= q - 1e-12:
            return k
    return n


def nearest(grid: list, n: int) -> int:
    """The window length of the research grid closest to ``n`` (by ratio)."""
    n = max(1, int(n))
    return min(grid, key=lambda m: (abs(math.log(m) - math.log(n)), m))


def _f(x: Any) -> Optional[float]:
    if isinstance(x, bool) or x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


# ---------------------------------------------------------------- one account's record
def steps(trades: list, initial: Optional[float] = None, margin_frac: Optional[float] = None) -> tuple:
    """(per closed trade the account's change as a share of the account before it, how it was measured). A trade with
    ``equity_after`` (the paper engine's own): pnl / (equity_after - pnl), exact. Else, with ``initial`` (the paper's
    starting wallet): pnl / the wallet before it (its own P&L added up). Else ``margin_frac`` (an executor that sizes
    every entry at that share of its own balance, size_from "equity") x its net ROE. Else the bot's own margin (40 %) x
    the net ROE (said so)."""
    out, how = [], set()
    eq = _f(initial)
    for t in trades:
        pnl, roe, after = _f(t.get("pnl")), _f(t.get("roe")), _f(t.get("equity_after"))
        g = None
        if pnl is not None and after is not None and after - pnl > 0:
            g, h = pnl / (after - pnl), "equity"
        elif pnl is not None and eq is not None and eq > 0:
            g, h = pnl / eq, "equity"
        elif roe is not None and margin_frac:
            g, h = float(margin_frac) * roe, "margin_frac"
        elif roe is not None:
            g, h = MARGIN * roe, "margin40"
        else:
            h = None
        if eq is not None and pnl is not None:
            eq += pnl
        if g is not None:
            out.append(max(g, -0.999999))
            how.add(h)
    return out, ("margin40" if "margin40" in how else "margin_frac" if "margin_frac" in how else "equity")


HOW_KO = {"equity": "계좌 기록(닫힌 거래의 지갑) 그대로", "margin_frac": "진입마다 잔고의 증거금 비율 × 순ROE로 계산",
          "margin40": "증거금 40% × 순ROE로 계산"}


def drops(g: list) -> tuple:
    """(the deepest drop from the running peak, the drop now) of an account started at 1.0, from its trade steps."""
    eq, peak, deep = 1.0, 1.0, 0.0
    for x in g:
        eq *= 1 + x
        peak = max(peak, eq)
        deep = max(deep, 1 - eq / peak)
    return deep, (1 - eq / peak) if g else 0.0


def losing_run(trades: list) -> int:
    """The losing run now: the last closed trades with P&L <= 0 (win = P&L > 0, the executors' rule)."""
    k = 0
    for t in reversed(trades):
        if (_f(t.get("pnl")) or 0.0) > 0:
            break
        k += 1
    return k


def win_check(n: int, w: int, ref: dict) -> dict:
    p = float(ref["win_rate"])
    lo, hi = binom_q(0.05, n, p), binom_q(0.95, n, p)
    p_low, p_high = binom_cdf(w, n, p), 1.0 - binom_cdf(w - 1, n, p)
    out = {"n": n, "wins": w, "rate": w / n, "p5y": p, "lo": lo, "hi": hi, "p_low": p_low, "p_high": p_high,
           "verdict": verdict_of(p_low)}
    win = ref.get("windows") or {}
    grid = sorted(int(m) for m in win if str(m).isdigit())
    if grid:
        m = nearest(grid, n)
        hist = win[str(m)].get("wins") or []
        cut = int(math.floor((w / n) * m + 1e-9))
        tot = sum(hist)
        share = (sum(hist[:cut + 1]) / tot) if tot else None
        out["emp"] = {"m": m, "share": share,
                      "ko": f"참고: 5년의 실제 {m}번 구간 중 승률이 이만큼 낮았던 곳 {share_ko(share)} (좋은 때·나쁜 때가 몰려 있는 것까지 들어간 숫자)"}
    good = p_high < RARE and w / n > p
    out["ko"] = (f"승률 {w}/{n}승({w / n:.0%}) · 5년 승률({p:.1%})이면 {n}번에 보통 {lo}~{hi}승 · 이만큼 이하가 나올 확률 "
                 f"{share_ko(p_low)} → {VERDICT_KO[out['verdict']]}"
                 + (" (5년보다 드물게 좋음: 운이 좋은 구간일 수 있어요)" if good else ""))
    out["good"] = good
    return out


def streak_check(k: int, ref: dict) -> dict:
    st = ref["streaks"]
    runs, longest = int(st["runs"]), int(st["longest"])
    reach = int((st.get("reach") or {}).get(str(k), 0)) if k else runs
    share = reach / runs if runs else None
    v = VERDICTS[0] if k == 0 else VERDICTS[2] if k > longest else verdict_of(share)
    per_1000 = reach / int(ref["trades"]) * 1000 if k else None
    if k == 0:
        ko = "지금 연패 없음(마지막 거래가 이김)"
    elif k == 1:
        ko = f"지금 1연패 · 5년 거래의 {1 - float(ref['win_rate']):.0%}가 진 거래라 흔한 일이에요"
    elif k > longest:
        ko = f"지금 {k}연패 · 5년 동안 가장 긴 연패는 {longest}연패였어요"
    else:
        ko = (f"지금 {k}연패 · 5년 연패 {runs:,}번 중 {k}연패 이상 {reach:,}번({share_ko(share)}, 거래 1,000번에 약 "
              f"{per_1000:.0f}번)" if per_1000 >= 1 else f"지금 {k}연패 · 5년 연패 {runs:,}번 중 {k}연패 이상 {reach:,}번({share_ko(share)})")
    return {"now": k, "runs": runs, "reach": reach, "share": share, "per_1000": per_1000, "longest_5y": longest, "verdict": v,
            "ko": f"{ko} → {VERDICT_KO[v]}"}


def dd_check(g: list, n: int, ref: dict, how: str) -> dict:
    deep, now = drops(g)
    win = ref.get("windows") or {}
    grid = sorted(int(m) for m in win if str(m).isdigit())
    out = {"deepest": deep, "now": now, "how": how, "how_ko": HOW_KO.get(how, how)}
    if not grid or not g:
        return {**out, "verdict": VERDICTS[0], "share": None, "ko": "낙폭: 아직 계산할 거래가 없어요"}
    m = nearest(grid, n)
    w = win[str(m)]
    bins = [int(x) for x in w.get("dd_bins") or []]
    nb = len(bins) or 1
    tot = sum(bins)
    pos = min(deep, 0.999999) * nb
    b = int(pos)
    share = ((sum(bins[b + 1:]) + bins[b] * (1 - (pos - b))) / tot) if tot and deep > 0 else 1.0 if tot else None
    v = verdict_of(share)
    med = _f(w.get("dd_median"))
    out.update(m=m, share=share, median_5y=med, p95_5y=_f(w.get("dd_p95")), verdict=v,
               ko=(f"시작 뒤 가장 깊은 낙폭 −{deep:.0%}(지금 최고점에서 −{now:.0%}) · 5년 {m}번 구간 중 이만큼 깊었던 곳 "
                   f"{share_ko(share)}" + (f"(가운데 −{med:.0%})" if med is not None else "") + f" → {VERDICT_KO[v]}"))
    return out


def honest_ko(ref: dict) -> str:
    return (f"솔직히: 5년 페이퍼 {int(ref['trades']):,}번은 승률 {float(ref['win_rate']):.1%}로 본전 승률 "
            f"{float(ref['breakeven_win']):.1%}보다 낮아 거래당 손해였어요"
            + (f"(평균 순ROE {signed_ko(float(ref['roe_per_trade']))})" if _f(ref.get("roe_per_trade")) is not None else "")
            + ". '정상 범위'는 5년처럼 돈다는 뜻이지 돈을 번다는 뜻이 아니에요")


def pick17_of(ref: dict) -> Optional[dict]:
    p = ref.get("pick17")
    if not isinstance(p, dict) or not p.get("n"):
        return None
    return {**{k: p.get(k) for k in ("n", "wins", "losses", "win_rate", "longest_losing_run", "mult", "max_dd")},
            "span_ko": PICK17_SPAN_KO,
            "ko": (f"참고 17일({PICK17_SPAN_KO}, 이 봇을 고를 때 본 가장 좋은 기간): {p['n']}번 {p['wins']}승 {p['losses']}패"
                   f"({float(p['win_rate']):.1%}) · 가장 긴 연패 {p['longest_losing_run']}번 · 가장 깊은 낙폭 −{float(p['max_dd']):.1%}"
                   f" · ×{float(p['mult']):.2f} — 고른 기간이라 앞으로의 기대치가 아니에요")}


def ref_view(ref: Optional[dict] = None) -> dict:
    """The yardstick in a page's shape: the 5 years' numbers, the 17 days (labelled), the honest words, where from."""
    ref = ref if ref is not None else load()
    if ref.get("state") != "ok":
        return {k: ref.get(k) for k in ("state", "reason_ko", "reason")}
    st = ref["streaks"]
    return {"state": "ok", "trades": ref["trades"], "win_rate": ref["win_rate"], "breakeven_win": ref["breakeven_win"],
            "avg_win_roe": ref.get("avg_win_roe"), "avg_loss_roe": ref.get("avg_loss_roe"), "roe_per_trade": ref.get("roe_per_trade"),
            "runs": st["runs"], "longest": st["longest"], "reach": st.get("reach"), "pick17": pick17_of(ref),
            "honest_ko": honest_ko(ref), "src": ref.get("src") or BAND_SRC,
            "rule_ko": "정상 범위 = 5년에 이만큼 이상 나쁜 경우가 5% 넘게 있었음 · 드묾 = 1~5% · 아주 드묾 = 1% 미만"}


def band(trades: list, initial: Optional[float] = None, margin_frac: Optional[float] = None, ref: Optional[dict] = None) -> dict:
    """One account's answer (module docstring). ``trades``: its closed trades, oldest first (each with ``pnl`` and
    ``roe``; ``equity_after`` when the record has it). ``initial``: the paper's starting wallet; ``margin_frac``: an
    executor's share of its balance per entry. State "empty" before its first closed trade; the research file's state
    when it cannot be read."""
    ref = ref if ref is not None else load()
    if ref.get("state") != "ok":
        return {k: ref.get(k) for k in ("state", "reason_ko", "reason")}
    trades = [t for t in trades if _f(t.get("pnl")) is not None]
    n = len(trades)
    if not n:
        return {"state": "empty", "n": 0, "ko": "아직 닫힌 거래가 없어요", "verdict": None}
    w = sum(1 for t in trades if _f(t["pnl"]) > 0)
    g, how = steps(trades, initial, margin_frac)
    wc, sc, dc = win_check(n, w, ref), streak_check(losing_run(trades), ref), dd_check(g, n, ref, how)
    v = worst([wc["verdict"], sc["verdict"], dc["verdict"]])
    return {"state": "ok", "n": n, "wins": w, "small": n < SMALL_N, "win": wc, "streak": sc, "dd": dc, "verdict": v,
            "verdict_ko": VERDICT_KO[v], "rare": v != VERDICTS[0]}


# ---------------------------------------------------------------- words for messages
def lines(b: dict, label: str) -> list:
    """The morning check's lines of one account: "- 운이냐 고장이냐 · 페이퍼(거래 50번): 정상 범위" and one line of the three
    checks' numbers; one line when there is nothing to compare yet."""
    if b.get("state") == "empty":
        return [f"- 운이냐 고장이냐 · {label}: 아직 닫힌 거래가 없어요"]
    if b.get("state") != "ok":
        return [f"- 운이냐 고장이냐 · {label}: {b.get('reason_ko') or MISSING_KO}"]
    wc, sc, dc = b["win"], b["streak"], b["dd"]
    head = f"- 운이냐 고장이냐 · {label}(거래 {b['n']}번): {b['verdict_ko']}" + (" · 아직 표본 적음" if b["small"] else "")
    s = ("지금 1연패(흔함)" if sc["now"] == 1 else
         f"지금 {sc['now']}연패(5년 연패 중 {share_ko(sc['share'])}가 이만큼)" if sc["now"] and sc["now"] <= sc["longest_5y"]
         else f"지금 {sc['now']}연패(5년 최장 {sc['longest_5y']}연패보다 김)" if sc["now"] else "연패 없음")
    d = (f"가장 깊은 낙폭 −{dc['deepest']:.0%}(5년 {dc['m']}번 구간 중 {share_ko(dc['share'])}가 이만큼)" if dc.get("share") is not None
         else "낙폭 계산 전")
    detail = (f"  승률 {wc['wins']}/{wc['n']}승(5년이면 보통 {wc['lo']}~{wc['hi']}승, 이만큼 이하 {share_ko(wc['p_low'])}) "
              f"{SHORT_KO[wc['verdict']]} · {s} {SHORT_KO[sc['verdict']]} · {d} {SHORT_KO[dc['verdict']]}")
    return [head, detail]


def ref_line(ref: Optional[dict] = None) -> Optional[str]:
    """The morning check's reference line: the 5 years in one breath, honestly, and the 17 days labelled."""
    ref = ref if ref is not None else load()
    if ref.get("state") != "ok":
        return None
    p = ref.get("pick17") or {}
    return (f"  기준: 5년 페이퍼 {int(ref['trades']):,}번(승률 {float(ref['win_rate']):.1%}, 본전 {float(ref['breakeven_win']):.1%} 아래라 "
            "거래당 손해: 정상 범위 = 5년처럼 돈다는 뜻)"
            + (f" · 17일({PICK17_SPAN_KO}) {p['n']}번 {p['wins']}승 {p['losses']}패는 고른 가장 좋은 기간이라 기대치 아님" if p.get("n") else ""))


def streak_ko(b: dict) -> Optional[str]:
    """One line of the losing run against the 5 years (a loss meeting's ``how_rare``), None when there is none."""
    if b.get("state") != "ok":
        return None
    return b["streak"]["ko"]
