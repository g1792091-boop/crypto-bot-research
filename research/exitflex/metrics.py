"""exitflex metrics (research/exitflex/PREREG_EXITFLEX.md sections 7-9).

Pure functions on an account's arrays: no file is read, nothing is printed. The wallet is realised at exits (no mark to
market). W_0 = $5,000 at the period start; W_m is the wallet after every trade that exited before the end of UTC month m;
g_m = ln(W_m / W_(m-1)); after a bust the later g_m are 0 (no later trade is taken).

Primary metric for pick p, variant V: M_p(V) = mean over the period's months of [g_m(V) - g_m(E0)] at quarter size, which is
[ln W_end(V) - ln W_end(E0)] / months. Pooled: M(V) = mean over the picks; the monthly pooled difference D_m(V) is the mean over
the picks of [g_m(V) - g_m(E0)].

``summarize`` turns one ``kernel_x.Result`` into a flat dict of numpy arrays (the content of one result file); the other
functions combine summaries of the picks: pooled and per pool (``core`` 23 picks, ``ds`` 15 picks). The DeepSeek rule D11
keeps every DeepSeek money figure out of committed files: the callers send those figures to the private folder and write only
the fields of ``DS_ALLOWED`` into a committed file; ``ds_whitelist_ok`` checks that.
"""

from __future__ import annotations

import datetime as dt
import math
import re

import numpy as np

import data_x as DX
import kernel_x as KX

HOLD_HOURS = (4, 8, 18)
MIN_PICK_SHARE = 0.6
N_BOOT = 2000
BLOCK = 3
N_STATE = 5
COMP_BITS = tuple(b for _n, b in KX.COMP_NAMES)
COMP_LABELS = tuple(n for n, _b in KX.COMP_NAMES)
MIN_STATE_TRADES = 100         # a state-table cell under 100 trades is marked 건수 적음 (prereg 7)
REASONS = ("NONE", "SL", "LOCK", "LIQ", "OPEN", "REJECT", "NOFILL", "NOATR", "TP", "RULE", "RAND", "END")


# ------------------------------------------------------------------ months
def month_edges(period: str) -> np.ndarray:
    """UTC month starts (ms) from the period's start to its end, inclusive: months + 1 values."""
    lo, hi = DX.PERIOD_MS[period]
    d = dt.datetime.fromtimestamp(lo / 1000, dt.timezone.utc)
    out = [lo]
    while out[-1] < hi:
        y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
        d = dt.datetime(y, m, 1, tzinfo=dt.timezone.utc)
        out.append(int(d.timestamp() * 1000))
    return np.array(out, np.int64)


def n_months(period: str) -> int:
    return len(month_edges(period)) - 1


def monthly_g(exit_ts: np.ndarray, pnl: np.ndarray, w0: float, edges: np.ndarray) -> tuple:
    """(g_m, W_m): monthly log growth and the wallet at each month end, from the trades in exit order."""
    m = len(edges) - 1
    cum = w0 + np.cumsum(pnl)
    k = np.searchsorted(exit_ts, edges[1:], side="left")      # trades that exited before each month end
    W = np.where(k > 0, cum[np.maximum(k - 1, 0)] if len(cum) else w0, w0)
    prev = np.r_[w0, W[:-1]]
    with np.errstate(invalid="ignore", divide="ignore"):
        g = np.log(np.maximum(W, 1e-12) / np.maximum(prev, 1e-12))
    return g, W


# ------------------------------------------------------------------ one account
def summarize(res, edges: np.ndarray) -> dict:
    """The numbers of one account that every later table needs, as flat numpy arrays (one result file)."""
    st = res.status
    ent = np.flatnonzero(st == 1)
    closed = ent[res.reason[ent] != KX.R_OPEN]
    pnl, ex, en = res.pnl[ent], res.exit_ts[ent], res.entry_ts[ent]
    g, W = monthly_g(ex, pnl, res.w0, edges)
    eq = res.w0 + np.cumsum(res.pnl[closed])
    peak = np.maximum.accumulate(np.r_[res.w0, eq])
    dd = float(np.max(1 - np.r_[res.w0, eq] / peak)) if len(eq) else 0.0
    rsn = res.reason[ent]
    at_rule = 0
    if len(ent) > 1:
        prev_rule = (rsn[:-1] == KX.R_RULE) | (rsn[:-1] == KX.R_RAND)
        at_rule = int(((en[1:] == ex[:-1]) & prev_rule).sum())
    sig = res.sig
    cm = res.comp[ent].astype(np.int64)
    rule = rsn == KX.R_RULE
    comp_fired = np.array([int((rule & ((cm & b) != 0)).sum()) for b in COMP_BITS], np.int64)
    comp_alone = np.array([int((rule & (cm == b)).sum()) for b in COMP_BITS], np.int64)
    return {
        "g": g, "W": W, "w0": np.float64(res.w0), "w_end": np.float64(res.wallet),
        "counts": np.array([len(st), len(ent), len(closed), int((st == 0).sum()), int((st == 2).sum()), int((st == 3).sum()),
                            int((st == 4).sum()), int(res.wallet < 10.0), int(res.both), at_rule,
                            int((res.pnl[closed] > 0).sum())], np.int64),
        "reasons": np.bincount(rsn, minlength=12).astype(np.int64),
        "hold_h": (ex - en) / 3_600_000.0, "max_dd": np.float64(dd),
        "tr_coin": sig["coin"][ent], "tr_side": sig["side"][ent], "tr_fill": en, "tr_exit": ex, "tr_reason": rsn.astype(np.int64),
        "tr_pnl": pnl, "num": res.num, "den": res.den,
        "tr_state": sig["state"][ent].astype(np.int64), "tr_comp": cm, "comp_fired": comp_fired, "comp_alone": comp_alone,
        # the leverage and exit price of every entered trade (the extra reads' ROE per trade and lock-level touches; read only)
        "tr_lev": np.asarray(res.lev)[ent].astype(np.float64), "tr_xpx": np.asarray(res.xpx)[ent].astype(np.float64)}


COUNT_NAMES = ("offered", "entered", "closed", "skipped", "rejected", "no_fill", "after_bust", "bust", "both_touched",
               "entries_at_rule_minute", "wins")


def count(s: dict, name: str) -> int:
    return int(s["counts"][COUNT_NAMES.index(name)])


def pick_Mp(sv: dict, se: dict) -> float:
    """M_p: mean monthly g difference of V against E0 at the same size (0 for a pick with no offered signal)."""
    return float(np.mean(sv["g"] - se["g"]))


def changed_trades(sv: dict, se: dict) -> int:
    """V's trades with no E0 trade of the same (coin, side, fill minute, exit minute, exit reason)."""
    keys = set(zip(se["tr_coin"].tolist(), se["tr_side"].tolist(), se["tr_fill"].tolist(), se["tr_exit"].tolist(),
                   se["tr_reason"].tolist()))
    return sum(1 for k in zip(sv["tr_coin"].tolist(), sv["tr_side"].tolist(), sv["tr_fill"].tolist(), sv["tr_exit"].tolist(),
                              sv["tr_reason"].tolist()) if k not in keys)


def hold_stats(hold_h: np.ndarray) -> dict:
    if not len(hold_h):
        return {"median": float("nan"), "p90": float("nan"), **{f"share_gt{h}": float("nan") for h in HOLD_HOURS}}
    return {"median": float(np.median(hold_h)), "p90": float(np.percentile(hold_h, 90)),
            **{f"share_gt{h}": float((hold_h > h).mean()) for h in HOLD_HOURS}}


def hold_by_state(hold_h: np.ndarray, tr_state: np.ndarray) -> dict:
    """Prereg 7: per market state at entry (keys: the Korean labels of data_x.STATE_KO, in STATE_ORDER), the number of trades, the median and 90th-percentile hold and
    the shares held over 4 h, 8 h and 18 h; ``few`` marks a cell under 100 trades (건수 적음), which is shown, not hidden."""
    hold_h = np.asarray(hold_h, float)
    tr_state = np.asarray(tr_state)
    out = {}
    for code in DX.STATE_ORDER:
        sel = hold_h[tr_state == code]
        d = hold_stats(sel)
        d["n"] = int(len(sel))
        d["few"] = bool(len(sel) < MIN_STATE_TRADES)
        out[DX.STATE_KO[code]] = d
    return out


# ------------------------------------------------------------------ the picks together
def pool_of(pick: dict) -> str:
    return "ds" if pick.get("kind") == "ds" else "core"


def pooled_series(sv: dict, se: dict, ids: list) -> np.ndarray:
    """D_m: the mean over the picks of g_m(V) - g_m(E0); ids = pick ids present in both dicts."""
    return np.mean([sv[i]["g"] - se[i]["g"] for i in ids], axis=0)


def comp_by_tf(sv: dict, ids: list, tfs: dict) -> dict:
    """F12 component counts (fired, fired alone) split by the pick's timeframe: {tf: {fired: {component: n}, alone: {...}, n_picks}}."""
    out = {}
    for tf in sorted({tfs[i] for i in ids}, key=lambda x: ("15m", "30m", "1h", "4h").index(x)):
        sel = [i for i in ids if tfs[i] == tf]
        out[tf] = {"fired": dict(zip(COMP_LABELS, np.sum([sv[i]["comp_fired"] for i in sel], axis=0).tolist())),
                   "alone": dict(zip(COMP_LABELS, np.sum([sv[i]["comp_alone"] for i in sel], axis=0).tolist())), "n_picks": len(sel)}
    return out


def pool_summary(sv: dict, se: dict, pools: dict | None = None, tfs: dict | None = None) -> dict:
    """V against E0 over the picks of ``sv`` / ``se`` ({pick id: summary}), pooled (key 'all') and per pool
    (``pools`` = {pick id: 'core'|'ds'}; default 'core' for all). ``tfs`` = {pick id: timeframe}: adds F12's component counts split
    by the pick's timeframe."""
    ids = sorted(sv)
    pools = pools or {i: "core" for i in ids}
    out = {}
    for name, sel in [("all", ids)] + [(p, [i for i in ids if pools[i] == p]) for p in sorted(set(pools.values()))]:
        if not sel:
            continue
        mp = np.array([pick_Mp(sv[i], se[i]) for i in sel])
        holds = np.concatenate([sv[i]["hold_h"] for i in sel])
        holds0 = np.concatenate([se[i]["hold_h"] for i in sel])
        states = np.concatenate([sv[i]["tr_state"] for i in sel])
        states0 = np.concatenate([se[i]["tr_state"] for i in sel])
        ch = sum(changed_trades(sv[i], se[i]) for i in sel)
        ent = sum(count(sv[i], "entered") for i in sel)
        out[name] = {
            "n_picks": len(sel), "M": float(mp.mean()), "median_Mp": float(np.median(mp)), "Mp": mp.tolist(), "ids": sel,
            "n_pos": int((mp > 0).sum()), "D": pooled_series(sv, se, sel),
            "entered": ent, "entered_e0": sum(count(se[i], "entered") for i in sel),
            "skipped": sum(count(sv[i], "skipped") for i in sel), "skipped_e0": sum(count(se[i], "skipped") for i in sel),
            "rejected": sum(count(sv[i], "rejected") for i in sel), "closed": sum(count(sv[i], "closed") for i in sel),
            "changed": ch, "changed_share": ch / ent if ent else 0.0,
            "entries_at_rule_minute": sum(count(sv[i], "entries_at_rule_minute") for i in sel),
            "reasons": np.sum([sv[i]["reasons"] for i in sel], axis=0).tolist(),
            "both_touched": sum(count(sv[i], "both_touched") for i in sel),
            "hold": hold_stats(holds), "hold_e0": hold_stats(holds0),
            "hold_by_state": hold_by_state(holds, states), "hold_by_state_e0": hold_by_state(holds0, states0),
            "comp_fired": np.sum([sv[i]["comp_fired"] for i in sel], axis=0).tolist(),
            "comp_alone": np.sum([sv[i]["comp_alone"] for i in sel], axis=0).tolist(),
            "comp_by_tf": comp_by_tf(sv, sel, tfs) if tfs else {},
            "win_share": (sum(count(sv[i], "wins") for i in sel) / max(1, sum(count(sv[i], "closed") for i in sel))),
            "busts": sum(count(sv[i], "bust") for i in sel),
            "max_dd_median": float(np.median([float(sv[i]["max_dd"]) for i in sel])),
            "final_multiple_median": float(np.median([float(sv[i]["w_end"]) / float(sv[i]["w0"]) for i in sel]))}
    return out


# ------------------------------------------------------------------ selection (section 8)
def eligibility(M: float, Mp: list, entered: int, entered_e0: int, placebo_pooled: np.ndarray | None, no_gate3: bool,
                min_share: float = MIN_PICK_SHARE) -> dict:
    """8.1, per pool (``Mp`` = the pool's M_p list): M_P(V) > 0; M_p(V) > 0 on at least 60% of the pool's picks (14 of 23, 9
    of 15); except F7, F7h and F13, M_P(V) above the 95th percentile (numpy linear) of V's placebo pooled means; trades entered at
    quarter size >= E0's. ``no_gate3`` = the families without a placebo (F7, F7h and F13: ``runner_x.no_placebo_gate``), which have no gate 3."""
    need = math.ceil(min_share * len(Mp) - 1e-9)
    c1 = M > 0
    c2 = int(sum(1 for m in Mp if m > 0)) >= need
    p95 = float(np.percentile(placebo_pooled, 95)) if placebo_pooled is not None and len(placebo_pooled) else float("nan")
    c3 = True if no_gate3 else bool(placebo_pooled is not None and len(placebo_pooled) and M > p95)
    c4 = entered >= entered_e0
    return {"c1_M_positive": bool(c1), "c2_picks_positive": bool(c2), "c3_beats_placebo_p95": bool(c3), "c4_entries": bool(c4),
            "eligible": bool(c1 and c2 and c3 and c4), "p95": p95, "need_picks": need}


def loss_class(v) -> str:
    """5.3: what a variant can cut a loss on before the hard stop. L0 no early loss cut before a gain (F5, F8, F10, and F13: the
    stepped lock exists only after the best price has reached +12% net ROE); L1 structure break at a loss deeper than 0.5R (F6.d0.5,
    F9, F9 q15); L2 structure break at any loss (F1, F1 q15, F6.d0); L3 not only a structure break (F2, F3, F4, F4 q15, F7, F7h, F11,
    and F12 which holds all of them)."""
    if v.fam in (KX.F5, KX.F8, KX.F10, KX.F13):
        return "L0"
    if v.fam == KX.F9 or (v.fam == KX.F6 and v.params.get("d", 0) >= 0.5):
        return "L1"
    if v.fam in (KX.F1, KX.F6):
        return "L2"
    return "L3"


def in_default_set(v) -> bool:
    """The default set D of 8.4: L0 and L1 (37 variants: the 35 of F5, F6.d0.5, F8, F9, F9 q15, F10 and the 2 of F13)."""
    return loss_class(v) in ("L0", "L1")


CLAIM_F12 = ("this fixed combination of the nine exits, of which at most seven can end a trade on a 1h or 4h pick and at most eight on a "
             "15m or 30m pick (F6 never moves the exit, F10 acts only on 15m and 30m picks), beats E0 and a random exit with the same "
             "8-hour clock and timing profile")
CLAIM_F12_LIMITS = "No claim that stacking beats a single rule, that all nine act on every pick, or that F12 is the best exit"
# prereg 8.5 (F13): what the lock is, and nothing more; it has no placebo gate, so there is no random-exit claim either
CLAIM_F13 = ("closes by the engine's stepped profit lock: after +12% net ROE it never gives back below +10%, except by the slippage of a "
             "stop and at a gapped open, which can lie anywhere; it reads no structure and makes no claim beyond that")


def claim_of(variant_id: str) -> str:
    """8.5: what a chosen variant may claim (the quoted wording of the pre-registration; for F12 the limits that go with it are
    ``CLAIM_F12_LIMITS``)."""
    if variant_id.startswith("F7.") or variant_id.startswith("F7h."):
        return "beats E0 by holding less; no claim about reading the market"
    if variant_id.startswith("F11."):
        return "the strategy's own exit beats E0 and a random exit with its timing profile"
    if variant_id.startswith("F12."):
        return CLAIM_F12
    if variant_id.startswith("F13."):
        return CLAIM_F13
    return "beats E0 and beats a random exit with its timing profile"


# prereg 8.3: choice.json lists, at least, the 2024-2026 material the owners had before the report was sent
REQUIRED_MATERIAL = ("ANALYSIS_KO.md", "STRATEGIES_KO.md", "STRATEGY_EVAL_KO.md")


def material_problems(choice: dict) -> list:
    """Problems in the 'material_received' list of a choice document: each of ``REQUIRED_MATERIAL`` must be named in some entry."""
    got = [str(x) for x in (choice.get("material_received") or [])]
    return [f"material_received does not name {m} (8.3: the full grid's per-trade results of the 84 exits)"
            for m in REQUIRED_MATERIAL if not any(m in g for g in got)]


def default_choice(rows: list, standing: list | None = None) -> list:
    """8.4, for one pool without an answer: among the choosable variants of the default set D, the one with the shortest median
    hold (quarter size, over all closed trades of the pool's accounts), then the shortest among those of a different group;
    ties go to fewer parameters, then to the canonical order. At most 2; [] when no candidate. ``rows``: dicts with id, group,
    nparams, order, eligible, default_set (or in_default_set) and hold (a dict with 'median'). ``standing`` (section 14, a rerun
    that voided some ids): ids that stand; the default only fills the free places, from groups the standing ids do not use."""
    standing = list(standing or [])
    taken_groups = {r["group"] for r in rows if r["id"] in standing}
    cand = [r for r in rows if r["eligible"] and r.get("default_set", r.get("in_default_set")) and not math.isnan(r["hold"]["median"])
            and r["id"] not in standing and r["group"] not in taken_groups]
    key = lambda r: (r["hold"]["median"], r["nparams"], r["order"])   # noqa: E731
    cand.sort(key=key)
    if not cand or len(standing) >= 2:
        return []
    out = [cand[0]]
    if len(standing) == 0:
        other = [r for r in cand if r["group"] != cand[0]["group"]]
        if other:
            out.append(other[0])
    return [r["id"] for r in out]


choose_variants = default_choice          # the name the earlier revisions used: the ranking is now the default of 8.4


def gate_failure_counts(rows: list) -> dict:
    """8.2: gate failures counted in sequence: gate 1; gate 2 among those passing 1; gate 4 among those passing 1 and 2; gate 3
    among those that reached step 2 (F7, F7h and F13 have no gate 3). ``rows`` carry gates 'g1', 'g2', 'g3', 'g4' as 'pass' / 'fail'
    / 'not_run' / 'n/a'."""
    g1 = [r for r in rows if r["gates"]["g1"] == "fail"]
    p1 = [r for r in rows if r["gates"]["g1"] == "pass"]
    g2 = [r for r in p1 if r["gates"]["g2"] == "fail"]
    p2 = [r for r in p1 if r["gates"]["g2"] == "pass"]
    g4 = [r for r in p2 if r["gates"]["g4"] == "fail"]
    p4 = [r for r in p2 if r["gates"]["g4"] == "pass"]
    g3 = [r for r in p4 if r["gates"]["g3"] == "fail"]
    return {"gate1": len(g1), "gate2": len(g2), "gate4": len(g4), "gate3": len(g3)}


def validate_choice_doc(select_doc: dict, choice: dict, sent: dict | None = None, prev_choice: dict | None = None) -> list:
    """8.3 and 14: problems in a ``choice.json`` (or ``choice_r2.json``) against ``select.json`` (and ``sent.json``); [] = valid.
    Each id must be choosable in its pool, a pool has at most 2 ids from different groups, the send time equals sent.json, a
    pool marked 'default used' has no answer timed before its deadline and holds the ids that 8.4 gives on select.json, a pool
    not marked 'default used' has an answer, and (rerun, ``prev_choice`` = the first choice.json) every id of the first choice
    that is still choosable stands and a pool answered 'none' stays none."""
    bad = []
    for pool in ("core", "ds"):
        ids = list(choice.get(pool) or [])
        P = (select_doc.get("pools") or {}).get(pool)
        info = (choice.get("pools") or {}).get(pool, {})
        if ids and P is None:
            bad.append(f"{pool}: no such pool in select.json")
            continue
        if len(ids) > 2 or len(set(ids)) != len(ids):
            bad.append(f"{pool}: at most 2 different variants")
        groups = []
        for i in ids:
            row = next((r for r in (P or {}).get("variants", []) if r["id"] == i), None)
            if row is None or not row["eligible"]:
                bad.append(f"{pool}: {i} is not choosable")
            else:
                groups.append(row["group"])
        if len(set(groups)) != len(groups):
            bad.append(f"{pool}: the chosen variants must be from different groups")
        standing = []
        if prev_choice is not None and P is not None:
            pinfo = (prev_choice.get("pools") or {}).get(pool, {})
            if pinfo.get("answer") == "없음" and ids:
                bad.append(f"{pool}: a pool answered 없음 stays none")
            standing = [i for i in (prev_choice.get(pool) or []) if any(r["id"] == i and r["eligible"] for r in P.get("variants", []))]
            dropped = [i for i in standing if i not in ids]
            if dropped:
                bad.append(f"{pool}: still-choosable ids cannot be swapped or dropped: {dropped}")
        times = list(info.get("answer_times_utc") or ([info["answer_time_utc"]] if info.get("answer_time_utc") else []))
        if info.get("default_used"):
            if info.get("deadline_utc") and any(t < info["deadline_utc"] for t in times):
                bad.append(f"{pool}: marked 'default used' but an answer was timed before the deadline")
            want = standing + default_choice((P or {}).get("variants", []), standing)
            if ids != want:
                bad.append(f"{pool}: the default's ids differ from 8.4's output")
        elif P is not None and not info.get("answer"):
            bad.append(f"{pool}: no answer recorded and the default was not used")
    if sent is not None and choice.get("sent_utc") != sent.get("sent_utc"):
        bad.append("the send time differs from sent.json")
    return bad


DS_ALLOWED = {"id", "name_ko", "family", "group", "mode", "q15", "nparams", "order", "loss_class", "in_default_set", "gates",
              "step2", "eligible", "label", "hold", "entered", "entered_e0", "entered_change_pct", "skipped", "skipped_e0",
              "rejected", "closed", "win_share", "entries_at_rule_minute", "reasons", "changed", "changed_share", "both_touched",
              "claim", "claim_ko", "mark_default", "same_as_f3", "n_picks", "pool", "holm_significant", "beats_placebo_p95",
              "entries_ok", "pass", "hold_e0", "chosen_by", "default_would_take", "ledger_label", "reasons_e0",
              "hold_by_state", "hold_by_state_e0", "comp_fired", "comp_alone", "comp_by_tf",
              "hold_live", "entered_live", "skipped_live", "rejected_live", "hazard"}


DS_NESTED_ALLOWED = ({"median", "p90", "share_gt4", "share_gt8", "share_gt18", "n", "few", "g1", "g2", "g3", "g4", "fired", "alone", "n_picks",
                      "num", "den",
                      "15m", "30m", "1h", "4h"} | set(REASONS) | set(DX.STATE_KO.values()) | set(COMP_LABELS))
DS_E0_ALLOWED = {"hold", "entered", "skipped", "win_share", "rejected", "closed", "reasons", "both_touched", "n_picks", "hold_by_state"}
DS_POOL_ALLOWED = {"n_picks", "e0", "variants", "eligible_ids", "default_ids", "gate_fail_counts"}
DS_TEXT_MONEY = None


def ds_whitelist_ok(row: dict) -> bool:
    """D11: a DeepSeek row of a committed file carries only counts, win shares, hold times, exit reasons and labels (nested
    dictionaries only hold hold-time statistics, exit-reason and market-state keys, gate labels and F12 component names)."""
    def nested(v):
        if isinstance(v, dict):
            return all(k in DS_NESTED_ALLOWED and nested(x) for k, x in v.items())
        return True
    return all(k in DS_ALLOWED and nested(v) for k, v in row.items())


def ds_text_problems(md: str) -> list:
    """Lines of a Korean report that sit in a DeepSeek section (a heading with 딥시크, or a table row of a ds pair) and show a money
    figure or a p value: a growth percentage per month, a log growth, a wallet multiple, a drawdown, a bust, an interval, a dollar
    amount or a p."""
    import re
    pat = re.compile(r"(월\s*[+-]?\d)|로그|배수|낙폭|파산|\bp\s*[=<>]|p값|구간\s*\[|\$\s?\d|M_P|\bM\s*=")
    bad, inside = [], False
    for ln in md.splitlines():
        if ln.startswith("#"):
            inside = "딥시크" in ln or (inside and not ln.startswith("## "))
            if ln.startswith("## "):
                inside = "딥시크" in ln
        if inside and pat.search(ln):
            bad.append(ln.strip())
    return bad


DS_MARKER = "[딥시크 금액 삭제]"
_DS_WORD = re.compile(r"ds-|딥시크|deepseek", re.I)
_UNIT_NUM = re.compile(r"[+-]?\$?\d[\d,]*(?:\.\d+)?\s*(?:%|퍼센트|percent|배|x|×)", re.I)
_MONEY_WORD = re.compile(r"성장|낙폭|파산|수익|손실|지갑|growth|drawdown|bust|wallet|multiple|p값|p-value", re.I)
_NUM_TOKEN = re.compile(r"(?<![A-Za-z0-9_.\-])[+-]?\$?\d[\d,]*(?:\.\d+)?(?:\s*(?:%|퍼센트|percent|배|x|×|달러|원|만원))?(?![A-Za-z0-9_])", re.I)
_COUNTER = re.compile(r"\s*(?:개|번|시간|등|위|가지|곳|명|일|분|년|달|주)")


_IDENT = re.compile(r"[A-Za-z][A-Za-z0-9_.\-]*\d[A-Za-z0-9_.\-]*")
_COUNTED = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:개|번|시간|등|위|가지|곳|명|일|분|년|달|주)")


def _tripwire(line: str) -> bool:
    """A8 (2): a line that holds a ds- id, 딥시크 or DeepSeek and also a number followed by %, 퍼센트, percent, 배, x or ×, or a money word
    and a digit. Identifier digits (F9.a, ds-F10_OTE-1h-1), numbers that count things (2개, 4시간) and the redaction marker are not
    figures: a line where the figures were replaced by the marker passes."""
    if not _DS_WORD.search(line):
        return False
    x = _COUNTED.sub(" ", _IDENT.sub(" ", line.replace(DS_MARKER, " ")))
    return bool(_UNIT_NUM.search(x) or (_MONEY_WORD.search(x) and re.search(r"\d", x)))


def audit_text(text: str) -> list:
    """The free-text tripwire of audit A8 (prereg 14): the lines of ``text`` that may hold a DeepSeek money figure or p value. A tripwire, not
    a proof: the main session reads each flagged line. [] = nothing flagged."""
    return [ln.strip() for ln in text.splitlines() if _tripwire(ln)]


def redact_ds_money(text: str) -> tuple:
    """Replace the DeepSeek money figures of an owner message or a main-session question by ``DS_MARKER`` (prereg 3, 8.3). Only lines that
    the tripwire flags are touched; in them every number is replaced except identifier digits (F9.a, ds-F10_OTE-1h-1) and numbers
    that count things (2개, 4시간). Returns (redacted text, number of figures replaced)."""
    out, n = [], 0
    for ln in text.splitlines(keepends=True):
        if _tripwire(ln):
            def repl(m, ln=ln):
                nonlocal n
                if _COUNTER.match(ln[m.end():]) and not m.group(0).strip().endswith(("%", "퍼센트", "percent", "배", "x", "×")):
                    return m.group(0)
                n += 1
                return DS_MARKER
            ln = _NUM_TOKEN.sub(repl, ln)
        out.append(ln)
    return "".join(out), n


def json_strings(obj):
    """Every string value of a JSON document (for the free-text tripwire)."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from json_strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from json_strings(v)


def d11_problems(select_doc: dict | None = None, confirm_doc: dict | None = None, select_md: str | None = None,
                 report_md: str | None = None) -> list:
    """Audit A8 on the committed files' content (pure): problems found in the DeepSeek rows of select.json and confirm.json and in the
    DeepSeek sections of SELECT_KO.md and REPORT_KO.md; [] = none."""
    bad = []
    if select_doc:
        ds = (select_doc.get("pools") or {}).get("ds")
        if ds:
            bad += [f"select.json ds pool key {k}" for k in ds if k not in DS_POOL_ALLOWED]
            bad += [f"select.json ds e0 key {k}" for k in ds.get("e0", {}) if k not in DS_E0_ALLOWED]
            bad += [f"select.json ds row {r.get('id')}" for r in ds.get("variants", []) if not ds_whitelist_ok(r)]
    if confirm_doc:
        bad += [f"confirm.json ds pair {k}" for k, r in (confirm_doc.get("pairs") or {}).items() if k.endswith("|ds") and not ds_whitelist_ok(r)]
        bad += [f"confirm.json ds e0 key {k}" for k in ((confirm_doc.get("e0") or {}).get("ds") or {}) if k not in DS_E0_ALLOWED]
    for name, md in (("SELECT_KO.md", select_md), ("REPORT_KO.md", report_md)):
        if md:
            bad += [f"{name}: {ln[:60]}" for ln in ds_text_problems(md)]
    return bad


# ------------------------------------------------------------------ confirm (section 9)
def block_means(D: np.ndarray, n_boot: int, seed: int, block: int = BLOCK) -> np.ndarray:
    """Means of ``n_boot`` circular moving-block resamples of the monthly series D (blocks of ``block`` consecutive months,
    wrapping around the end; ceil(T / block) blocks, cut to T)."""
    D = np.asarray(D, float)
    T = len(D)
    rng = np.random.default_rng(seed)
    nb = -(-T // block)
    starts = rng.integers(0, T, size=(n_boot, nb))
    idx = ((starts[:, :, None] + np.arange(block)[None, None, :]) % T).reshape(n_boot, nb * block)[:, :T]
    return D[idx].mean(axis=1)


def block_bootstrap_p(D: np.ndarray, seed: int, n_boot: int = N_BOOT, block: int = BLOCK) -> float:
    """One-sided p that the mean of D is <= 0: (1 + resamples with mean <= 0) / (n_boot + 1)."""
    m = block_means(D, n_boot, seed, block)
    return float((1 + int((m <= 0).sum())) / (n_boot + 1))


def iid_bootstrap_p(D: np.ndarray, seed: int, n_boot: int = N_BOOT) -> float:
    D = np.asarray(D, float)
    rng = np.random.default_rng(seed)
    m = D[rng.integers(0, len(D), size=(n_boot, len(D)))].mean(axis=1)
    return float((1 + int((m <= 0).sum())) / (n_boot + 1))


def block_bootstrap_ci(D: np.ndarray, seed: int, n_boot: int = N_BOOT, block: int = BLOCK, level: float = 95.0) -> tuple:
    """A percentile interval for M(V) from the block bootstrap (numpy percentile, linear)."""
    m = block_means(D, n_boot, seed, block)
    a = (100.0 - level) / 2.0
    return float(np.percentile(m, a)), float(np.percentile(m, 100.0 - a))


def holm(ps: dict, alpha: float = 0.05) -> dict:
    """Holm at ``alpha`` over {id: p}: with one test p < alpha; with two the smaller p < alpha / 2 and then the larger
    p < alpha. Returns {id: bool}."""
    order = sorted(ps, key=lambda i: ps[i])
    out = {i: False for i in ps}
    m = len(order)
    for r, i in enumerate(order):
        if ps[i] < alpha / (m - r):
            out[i] = True
        else:
            break
    return out


def confirm_verdict(sig: bool, M: float, placebo_pooled: np.ndarray | None, no_gate3: bool, entered: int, entered_e0: int) -> dict:
    """PASS needs all three: Holm-significant; except F7, F7h and F13 (``no_gate3``), M(V) above the 95th percentile of the confirm-period placebo pooled
    means; trades entered at quarter size >= E0's."""
    p95 = float(np.percentile(placebo_pooled, 95)) if placebo_pooled is not None and len(placebo_pooled) else float("nan")
    c2 = True if no_gate3 else bool(placebo_pooled is not None and len(placebo_pooled) and M > p95)
    c3 = entered >= entered_e0
    return {"holm": bool(sig), "beats_placebo_p95": bool(c2), "entries": bool(c3), "p95": p95,
            "pass": bool(sig and c2 and c3)}


def summarize_light(res, edges: np.ndarray) -> dict:
    """The part of ``summarize`` a placebo account keeps: monthly log growth, final wallet, counts, exit reasons, hold
    statistics (median, 90th percentile, shares held more than 4 / 8 / 18 h) and the maximum drawdown."""
    st = res.status
    ent = np.flatnonzero(st == 1)
    closed = ent[res.reason[ent] != KX.R_OPEN]
    g, _W = monthly_g(res.exit_ts[ent], res.pnl[ent], res.w0, edges)
    eq = res.w0 + np.cumsum(res.pnl[closed])
    peak = np.maximum.accumulate(np.r_[res.w0, eq])
    dd = float(np.max(1 - np.r_[res.w0, eq] / peak)) if len(eq) else 0.0
    hold = (res.exit_ts[ent] - res.entry_ts[ent]) / 3_600_000.0
    hs = hold_stats(hold)
    return {"g": g, "w_end": float(res.wallet), "max_dd": dd,
            "counts": np.array([len(st), len(ent), len(closed), int((st == 0).sum()), int((st == 2).sum()), int((st == 3).sum()),
                                int((st == 4).sum()), int(res.wallet < 10.0), int(res.both), 0,
                                int((res.pnl[closed] > 0).sum())], np.int64),
            "reasons": np.bincount(res.reason[ent], minlength=12).astype(np.int64),
            "hold": np.array([hs["median"], hs["p90"]] + [hs[f"share_gt{h}"] for h in HOLD_HOURS]),
            "num": res.num, "den": res.den}


def stack_light(items: list) -> dict:
    """Stack ``summarize_light`` results of several seeds: arrays get a leading seed axis; the hazard counts are summed."""
    out = {k: np.stack([np.asarray(it[k]) for it in items]) for k in ("g", "w_end", "max_dd", "counts", "reasons", "hold")}
    out["num"] = np.sum([it["num"] for it in items], axis=0)
    out["den"] = np.sum([it["den"] for it in items], axis=0)
    return out
