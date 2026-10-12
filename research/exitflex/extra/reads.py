"""Extra reads stage of the exit study (research/exitflex/PREREG_EXITFLEX_EXTRA.md E.3-E.6; main file 3, 7, 8.2, 13, 14).

    python research/exitflex/extra/reads.py run    [--procs N] [--rerun] [--skip-tests]   # every coded read -> outputs (calls report)
    python research/exitflex/extra/reads.py report [--rerun]                              # rewrite the outputs from the saved state
    python research/exitflex/extra/reads.py audit  [--rerun] [--private]                  # re-check every committed output (or the private one)

``run``: A's pin, the extra pin, the select cut and select.json (common.load_ctx, allow_select: after O8 only); the extra tests (E.6) unless
--skip-tests; the E.5 run record and disk rule; the E.5 projection on core-DOGE-15m-1 and the cap (tier A and the twins are never
dropped); the C5 audit (a mismatch stops the stage, 14); tier A (reads_a), tier B (reads_b.run_b when importable), X-046 last. Each read
is guarded: a failing read is recorded (type and a digit-free message committed, the full text private), never fatal.
Outputs (E.4), committed to research/exitflex/extra/out/ (``_r2`` names after an A select rerun):
  extra_reads.json            run record (E.5), dropped_at_o8, not coded, every read's committed parts, the private files' sha256;
  EXTRA_READS_KO.md           the tier A body in E.3's order (X-046 first), Korean, W0 at the top and the W1 box (E.1 item 2);
  EXTRA_READS_APPENDIX_KO.md  tier A appendix parts and tier B;
  extra_reads_rows.csv        count columns of all 89 rows of both pools.
Private (never committed): $WORK/<pin8>/ds_private/extra_reads_ds.json and owner_report_extra.md (common.write_owner_report_extra; part
핵심 = tier A and the twins' private section, then 부록). Working state: $WORK/<pin8>/extra/reads_state.json.
The console prints read ids, pass or fail and seconds only (E.4).
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
import csv  # noqa: E402
import glob  # noqa: E402
import importlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import common as XC  # noqa: E402
import reads_a as RA  # noqa: E402
import reads_lib as RL  # noqa: E402
from common import KX, RX  # noqa: E402

STAGE = "extra-reads"
TIMING_PICK = "core-DOGE-15m-1"                     # E.5: the projection's pick
EST_READ_BYTES = 50_000_000                          # bytes checked against the disk rule before each read
# E.5: account-equivalents of the re-runs (E.3 costs). Never dropped: the C5 audit (tier A), X-005, X-041 at c = 0, 2, 3, X-043 at quarter size.
CAP_BASE = (("C5 audit", "X-025", 152.0), ("X-005", "X-005", 740.0), ("X-041 c = 0, 2, 3", "X-041", 3 * 3950.0 / 4),
            ("X-043 quarter size", "X-043", 1980.0 / 2))
CAP_PART_EQ = {"X-022 fixed leverage": ("X-022", 3 * 4940.0 / 5), "X-041 c = 1.5": ("X-041", 3950.0 / 4), "X-043 live size": ("X-043", 1980.0 / 2),
               "X-023 and X-044 on every second Monday (72 starts)": ("X-023", 11900.0 * 71 / 143), "X-002": ("X-002", 4940.0),
               "X-022 entirely": ("X-022", 4940.0)}
assert tuple(CAP_PART_EQ) == XC.CAP_DROP_ORDER
FLAT_CPU_S = {"X-017": 95.0}                         # E.3 X-017: about 95 s CPU for all horizons, picks and sizes
POST_CPU_S = 15 * 60.0                               # E.5: about 15 CPU-minutes of post-processing, placebo reads and builds


def say(msg: str) -> None:
    print(msg, flush=True)


def names(ctx) -> dict:
    sfx = "_r2" if ctx.rerun else ""
    return {"json": f"extra_reads{sfx}.json", "ko": f"EXTRA_READS_KO{sfx}.md", "app": f"EXTRA_READS_APPENDIX_KO{sfx}.md",
            "csv": f"extra_reads_rows{sfx}.csv", "ds_json": f"extra_reads_ds{sfx}.json", "report": f"owner_report_extra{sfx}.md",
            "state": os.path.join(ctx.work_extra, f"reads_state{sfx}.json"),
            "twins_private": os.path.join(ctx.private_dir, "twins", f"owner_report_extra_twins{sfx}.md")}


def scrub(msg: str) -> str:
    """A committed error message: no digit (a DeepSeek figure could sit in an exception text); the full text goes to the private state."""
    return re.sub(r"\d", "#", str(msg))[:200]


# ====================================================================================================== context
def load(lay=None, rerun: bool = False, prep=None):
    """common.load_ctx with select.json (after O8); ``prep(ctx)`` lets a test give the synthetic market and chart builder."""
    ctx = XC.load_ctx(lay or RX.Layout(), stage="extra_r2" if rerun else "extra", allow_select=True)
    if prep is not None:
        prep(ctx)
    XC.c1_check(ctx.picks)
    return ctx


def load_reads_b():
    """reads_b (tier B, the other builder's module) when importable, else (None, reason)."""
    try:
        return importlib.import_module("reads_b"), None
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}"


def plan(rb) -> dict:
    """Which reads run: tier A always; tier B ids that reads_b codes; tier C dropped at O8 (E.0 item 2 a); X-017 when reads_b says so."""
    coded_b = list(getattr(rb, "READS", [])) if rb is not None else []
    dropped = [{"id": rid, "reason": RL.DROP_REASON_C} for rid in RL.TIER_C]
    own = dict(getattr(rb, "DROPPED_AT_O8", {}) or {}) if rb is not None else {}
    for rid, why in own.items():
        if rid == "X-017":
            dropped.append({"id": rid, "reason": str(why) or "X-017 tests not green at O8 (E.0 item 2 a)"})
            if rid in coded_b:
                coded_b.remove(rid)
    tier_b = [rid for rid in RL.TIER_B if rid in coded_b]
    dropped_ids = {d["id"] for d in dropped}
    not_coded = [rid for rid in RL.TIER_B if rid not in tier_b and rid not in dropped_ids]
    return {"tier_a": list(RL.BODY_ORDER), "tier_b": tier_b, "dropped_at_o8": dropped, "not_coded": not_coded}


# ====================================================================================================== E.5 projection and cap
def time_accounts(ctx) -> dict:
    """E.5: on core-DOGE-15m-1 (the first core pick when absent) one PickData build with F11 and one account each of E0, F12.a and a q15
    arm at quarter size (seconds; no figure of the accounts is kept)."""
    p = ctx.by_id.get(TIMING_PICK) or ctx.pool_picks("core")[0]
    mk = ctx.__dict__.get("make_pickdata")
    t0 = time.time()
    pdata = mk(p) if mk is not None else ctx.pickdata(p)
    t_pd = time.time() - t0
    arms = ["E0"] + [a for a in ("F12.a",) if a in ctx.vids] + [next((v for v in ctx.vids if v.endswith(".q15")), None)]
    ts = []
    for a in [x for x in arms if x]:
        t0 = time.time()
        XC.rerun(ctx, pdata, a, XC.SIZE_Q)
        ts.append(time.time() - t0)
    return {"pick": p["id"], "pickdata_s": t_pd, "account_s": sum(ts) / len(ts), "arms": [x for x in arms if x]}


def projection(t: dict, coded: set, dropped: set, n_picks: int, procs: int) -> dict:
    """E.5: projected wall seconds of the stage's re-runs and post-processing (the twins are their own stage)."""
    acc = sum(eq for _n, rid, eq in CAP_BASE if rid in coded)
    acc += sum(eq for name, (rid, eq) in CAP_PART_EQ.items() if rid in coded and name not in dropped)
    flat = sum(s for rid, s in FLAT_CPU_S.items() if rid in coded)
    builds = n_picks * (1 + sum(1 for rid in ("X-002", "X-005", "X-017", "X-026", "X-041", "X-043") if rid in coded))
    cpu = acc * t["account_s"] + builds * t["pickdata_s"] + flat + POST_CPU_S
    return {"account_equivalents": acc, "pickdata_builds": builds, "cpu_s": cpu, "wall_s": cpu / max(1, procs), "procs": procs}


def apply_cap(t: dict, coded: set, n_picks: int, procs: int) -> tuple:
    """E.5: while the projection exceeds 45 min wall, drop parts in common.CAP_DROP_ORDER (parts of reads not coded are skipped); every
    drop must lower the projection. Returns (dropped names, projections before and after)."""
    dropped = []
    before = projection(t, coded, set(), n_picks, procs)
    cur = before
    for name in XC.CAP_DROP_ORDER:
        if cur["wall_s"] <= XC.CAP_MINUTES * 60:
            break
        rid = CAP_PART_EQ[name][0]
        if rid not in coded:
            continue
        nxt = projection(t, coded, set(dropped) | {name}, n_picks, procs)
        if not nxt["wall_s"] < cur["wall_s"]:
            raise AssertionError(f"E.5: dropping {name} does not lower the projection")
        dropped.append(name)
        cur = nxt
    return dropped, before, cur


# ====================================================================================================== tier B adapter (reads_b's own result format)
def _get(d, *path):
    for k in path:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def _pct(x, nd=1):
    return RL.fmt_share(x, nd) if x is not None else XC.EMPTY


def headline_from_b(rid: str, res: dict, pool: str) -> dict | None:
    """The sentence X-046 quotes from a tier B result of reads_b's format ({'core': {'by_arm': {arm: {..., 'money'}}}, 'ds': ...,
    'private': {'ds': {'by_arm': {arm: {'money'}}}}}). DeepSeek money only in 'private'; None when the fields are absent."""
    ds = pool == "ds"
    row = _get(res, pool, "by_arm", "E0") or {}
    money = _get(res, "private", "ds", "by_arm", "E0", "money") if ds else row.get("money")
    tag = "딥시크 " if ds else ""
    try:
        if rid == "X-016":
            tg = next((t for t in (money or {}).get("targets", []) if t.get("target") == "x5"), None)
            if not tg:
                return None
            ceil = _get(res, "private", "ds", "entries_ceiling_per_account_month") if ds else _get(res, "core", "entries_ceiling_per_account_month")
            w, n = row.get("win_share"), row.get("n_entries_per_account_month")
            lw, le = tg.get("label_win") or "", tg.get("label_entries") or ""
            if lw == "불가능":
                win = f"승률로는 불가능(다 이겨도 모자람, 지금 {_pct(w)})"
            elif lw == "이미 넘음":
                win = f"승률은 이미 넘음(지금 {_pct(w)})"
            else:
                win = f"승률 {_pct(tg.get('win_share_need'))}(지금 {_pct(w)})"
            if tg.get("entries_need") is None:
                ent = f"한 달 진입으로도 불가능({le or '거래당 평균이 0 이하'}, 지금 {RL.fmt_f(n)}번)"
            else:
                ent = (f"한 달 진입 {RL.fmt_f(tg.get('entries_need'))}번(지금 {RL.fmt_f(n)}번, 최대 {RL.fmt_f(ceil)}번)"
                       + (f", {le}" if le else ""))
            s = f"{tag}한 달 x5에는 {win}, 또는 {ent}입니다(맞춘 기간의 성적)."
            return {"public": None, "private": s} if ds else {"public": s, "private": None}
        if rid == "X-021":
            if not money:
                return None
            s = (f"{tag}한 계좌로 합치면 증거금이 지갑의 평소 {_pct(money.get('margin_p50'), 0)}·최대 {_pct(money.get('margin_max'), 0)}이고, "
                 f"시간의 {_pct(money.get('share_over_100'))}는 100% 초과입니다(실제 한 계좌로는 불가능, {XC.W['W13']})")
            return {"public": None, "private": s} if ds else {"public": s, "private": None}
        if rid == "X-034":
            if not money or money.get("cost_month_pct") is None:
                return None
            s = (f"{tag}지금 청산의 한 달 비용은 지갑의 {RL.fmt_f(money.get('cost_month_pct'), 2)}%(수수료·미끄러짐)와 "
                 f"{RL.fmt_f(money.get('fund_month_pct'), 2)}%(펀딩)입니다.")
            return {"public": None, "private": s} if ds else {"public": s, "private": None}
        if rid == "X-041":
            own = (money or {}).get("own") or {}
            if "c2" not in own:
                return None
            s = f"{tag}비용이 2배면 지금 청산은 한 달 {RL.fmt_growth(own['c2'])}입니다(지금 {RL.fmt_growth(own.get('c1'))})."
            return {"public": None, "private": s} if ds else {"public": s, "private": None}
        if rid == "X-043":
            lab = _get(res, pool, "label_verdict")
            if not lab:
                return None
            return ({"public": f"1,000달러로 시작하면: {lab}.", "private": None} if not ds
                    else {"public": f"1,000달러로 시작하면 {lab}.", "private": f"딥시크 1,000달러로 시작하면 {lab}."})
    except Exception:  # noqa: BLE001
        return None
    return None


def _timed(rid: str, fn, timings: dict):
    def run(*a, **k):
        t0 = time.time()
        try:
            return fn(*a, **k)
        finally:
            timings[rid] = time.time() - t0
    return run


def run_tier_b(ctx, rb, reads: list, dropped: list) -> tuple:
    """reads_b.run_b once (its pre-pass is shared); each read's seconds by a timing wrapper around reads_b.FUNCS (restored after)."""
    timings = {}
    funcs = getattr(rb, "FUNCS", None)
    orig = dict(funcs) if isinstance(funcs, dict) else {}
    if orig:
        for rid, fn in orig.items():
            funcs[rid] = _timed(rid, fn, timings)
    t0 = time.time()
    try:
        out = rb.run_b(ctx, dropped=tuple(dropped), reads=list(reads))
    finally:
        if orig:
            funcs.update(orig)
    return out, timings, time.time() - t0


def _lines(text) -> list:
    if text is None:
        return []
    return list(text) if isinstance(text, (list, tuple)) else str(text).splitlines()


def from_b(ctx, rb, rid: str, res: dict) -> dict:
    """A tier B result in reads_b's format as this stage's result (status, guarded committed parts, Korean lines, headline)."""
    r = RL.new_result(rid, "B", res.get("title") or rid)
    r["status"] = "ok"
    if res.get("error"):
        r["status"], r["error"], r["error_private"] = "failed", scrub(res["error"]), str(res["error"])
        return r
    if res.get("dropped"):
        r["status"] = "dropped"
        r["parts_dropped"] = [str(res["dropped"])]
        return r
    r["public"] = {"core": res.get("core") or {}, "ds": RL.ds_public(dict(res.get("ds") or {"pool": "ds"}))}
    r["private"] = res.get("private") or {}
    r["notes"] = list(res.get("notes") or [])
    for pool in XC.POOLS:
        h = headline_from_b(rid, res, pool)
        if h and rid in RL.HEADLINE_KEYS:
            r["headline"][pool][RL.HEADLINE_KEYS[rid]] = h
    return r


NO_MD_KO = "이 읽기의 한국어 표는 이번 실행에 없습니다. 숫자는 extra_reads.json에 있습니다."


def render_tier_b(ctx, rb, raw: dict, results: dict) -> tuple:
    """reads_b's Korean appendix block and private 부록 for the reads in ``raw`` (failed reads as error entries): the block in one call
    when it passes the committed guards; otherwise each read alone, a read whose page fails being marked failed. Returns (md lines,
    private lines, note)."""
    fa, fp = getattr(rb, "appendix_md", None), getattr(rb, "private_md", None)
    note = ""
    if fa is None:
        md = [ln for rid in raw for ln in (f"## {rid} {(results.get(rid) or {}).get('title') or rid}", "", NO_MD_KO, "")]
        note = "reads_b has no appendix_md"
    else:
        try:
            md = _lines(fa(raw))
            bad = md_problems(ctx, "x.md", "\n".join(md))
        except Exception as exc:  # noqa: BLE001
            md, bad = [], [f"{type(exc).__name__}"]
        if bad:
            note = "tier B block failed a guard; rendered read by read"
            md = []
            for rid, res in raw.items():
                try:
                    one = _lines(fa({rid: res}))
                    head = next((i for i, ln in enumerate(one) if ln.startswith("#") and rid in ln), None)
                    one = one[head:] if head is not None else [f"## {rid}", ""] + one
                    if not one[0].startswith("## "):
                        one = [f"## {rid} {(results.get(rid) or {}).get('title') or rid}", ""] + one
                    bad1 = md_problems(ctx, "x.md", "\n".join(one))
                except Exception as exc:  # noqa: BLE001
                    one, bad1 = [], [f"{type(exc).__name__}"]
                if bad1:
                    r = results.get(rid) or {}
                    if r.get("status") == "ok":
                        r.update(status="failed", error="Korean page guard: " + scrub(bad1[0]), error_private=" | ".join(map(str, bad1[:10])),
                                 public={"core": {}, "ds": {"pool": "ds"}})
                    one = [f"## {rid} {(results.get(rid) or {}).get('title') or rid}", "", RA_FAILED_KO, ""]
                md += one + [""]
    priv = []
    if fp is not None:
        try:
            priv = _lines(fp(raw))
        except Exception as exc:  # noqa: BLE001
            priv, note = [], (note + "; " if note else "") + f"private_md {type(exc).__name__}"
        if XC._P_VALUE.search("\n".join(priv)):
            priv, note = [], (note + "; " if note else "") + "private_md held a p value: left out"
    return md, priv, note


# ====================================================================================================== pages
def _box() -> list:
    return [f"> **{RL.W_KO['W1']}**", ""]


def page_ko(ctx, results: dict) -> str:
    """EXTRA_READS_KO.md: W0 first (X-046 line 0), the W1 box, then the tier A body in E.3's order."""
    L = ["# 추가 읽기 (2021~2023년, 참고용)", "", f"**{XC.W['W0']}**", ""] + _box()
    L += ["이 문서는 고르기 표(SELECT_KO)와 같은 기간의 숫자를 여러 방향에서 나눠 본 참고 자료입니다. 표마다 '참고용 · 고르는 데 안 씀' 꼬리표가 붙습니다. "
          "단위: '%/월'은 한 달 성장(100 × (e^M - 1)), '%/월 기여(근사)'는 로그 성장의 부분, 'x'는 배수입니다. 칸에 '건수 적음'은 100건 미만, "
          "'픽 N개'는 픽이 3개 미만, '-'는 빈 칸입니다. 1/1 크기 칸에는 파산 수를 같이 적습니다.", ""]
    for rid in RL.BODY_ORDER:
        r = results.get(rid) or {}
        L += [f"## {rid} {RL.TITLE_KO[rid]}", ""]
        L += r.get("md") or [RA_FAILED_KO, ""]
    L += ["## 각주", "", XC.CONTRIB_NOTE_KO, "R(거래 하나의 손익을 처음 손절 거리로 나눈 값)은 부록에만 적습니다. 로그 값은 json에만 있습니다.", ""]
    return "\n".join(L).rstrip("\n") + "\n"


RA_FAILED_KO = "이 읽기는 이번 실행에서 계산하지 못했습니다(이유는 extra_reads.json의 error 칸)."


def page_appendix(ctx, results: dict, pl: dict, tier_b_md: list | None = None) -> str:
    """EXTRA_READS_APPENDIX_KO.md: tier A appendix parts, tier B in E.3's order, then the reads dropped at O8 and not coded."""
    L = ["# 추가 읽기 부록 (2021~2023년, 참고용)", "", f"**{XC.W['W0']}**", ""] + _box()
    for rid in RL.BODY_ORDER:
        r = results.get(rid) or {}
        if r.get("md_appendix"):
            L += [f"## {rid} {RL.TITLE_KO[rid]} (부록)", ""] + r["md_appendix"]
    L += list(tier_b_md or [])
    if tier_b_md:
        L.append("")
    L += ["## O8에 빠진 읽기", "", "아래 읽기는 사전 등록된 규칙(E.0 항목 2 a)에 따라 이번에 계산하지 않았습니다: "
          + ", ".join(d["id"] for d in pl["dropped_at_o8"]) + "."]
    failed = [rid for rid in list(RL.BODY_ORDER) + list(RL.TIER_B) if (results.get(rid) or {}).get("status") == "failed"]
    if failed:
        L.append("이번 실행에서 계산하지 못한 읽기(이유는 extra_reads.json의 error 칸): " + ", ".join(failed) + ".")
    if pl["not_coded"]:
        L.append("다음 읽기는 코드가 없어 빠졌습니다(DEVIATIONS.md에 적을 일): " + ", ".join(pl["not_coded"]) + ".")
    L += ["", "## 각주", "", XC.CONTRIB_NOTE_KO, "R: 거래 하나의 손익을 처음 손절까지의 거리(1R)로 나눈 값입니다.", ""]
    return "\n".join(L).rstrip("\n") + "\n"


def private_report(ctx, results: dict, twins_path: str, tier_b_private: list | None = None) -> str:
    """owner_report_extra.md's body (common.write_owner_report_extra adds the last line): part 핵심 (tier A, then the twins' private
    section verbatim), then part 부록 (tier A appendix parts, tier B). E0 and choosable rows only, committed row order, no p value."""
    L = ["# 딥시크 금액 보고서 (추가 읽기), 비공개: 저장소에 올리지 않음", "",
         "이 파일은 소유자 두 분께 대화로만 보여 드립니다. 딥시크 숫자를 금액 기준으로 줄 세우지 않았고, 검정 수치는 넣지 않았습니다. 줄 순서는 공개 표와 같습니다.",
         "", "## 핵심", ""]
    for rid in RL.BODY_ORDER:
        L += (results.get(rid) or {}).get("md_private") or []
    if twins_path and os.path.exists(twins_path):
        L += [open(twins_path, encoding="utf-8").read().rstrip("\n"), ""]
    L += ["## 부록", ""]
    for rid in RL.BODY_ORDER:
        L += (results.get(rid) or {}).get("md_private_appendix") or []
    L += list(tier_b_private or [])
    return "\n".join(L).rstrip("\n") + "\n"


# ====================================================================================================== guards
def md_problems(ctx, name: str, text: str) -> list:
    return XC.committed_problems(name, text, text) + RL.md_rule_problems(ctx, text)


def obj_problems(ctx, name: str, obj, text: str) -> list:
    return XC.committed_problems(name, obj, text) + RL.row_rule_problems(ctx, obj) + ["decision (a): " + b for b in RL.ds_strip_problems(obj)]


def guard_result(ctx, r: dict) -> dict:
    """A read whose committed parts fail a guard (C8, A8 tripwire, C14, the row rule) is marked failed and its committed parts are
    removed; the others go on."""
    if r.get("status") != "ok":
        return r
    doc = {"reads": {r["id"]: RL.jsonable(r["public"])}}
    text = json.dumps(doc, ensure_ascii=False)
    md = "\n".join([f"## {r['id']}", ""] + list(r.get("md") or []) + [f"## {r['id']} 부록", ""] + list(r.get("md_appendix") or []))
    bad = obj_problems(ctx, "extra_reads.json", json.loads(text), text) + md_problems(ctx, "x.md", md)
    bad += obj_problems(ctx, "x.csv", RL.jsonable(r.get("csv") or []), "")
    if bad:
        r.update(status="failed", error="committed guard: " + scrub(bad[0]), error_private=" | ".join(bad[:10]), public={"core": {}, "ds": {"pool": "ds"}},
                 md=[], md_appendix=[], csv=[])
    return r


# ====================================================================================================== run
def run_tests() -> dict:
    """E.6: the extra tests rerun by the stage before any read (pass / fail and counts only)."""
    files = sorted(glob.glob(os.path.join(HERE, "test_*.py")))
    t0 = time.time()
    p = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *files], capture_output=True, text=True, cwd=HERE)
    last = (p.stdout.strip().splitlines() or [""])[-1]
    return {"ok": p.returncode == 0, "summary": re.sub(r"\s+", " ", last)[:120], "files": [os.path.basename(f) for f in files],
            "seconds": round(time.time() - t0, 1)}


def _failed(rid: str, tier: str, exc: BaseException) -> dict:
    r = RL.new_result(rid, tier)
    r.update(status="failed", error=f"{type(exc).__name__}: {scrub(exc)}", error_private="".join(traceback.format_exception(exc))[-4000:])
    return r


def cmd_run(lay=None, procs: int = 1, rerun: bool = False, skip_tests: bool = False, prep=None) -> int:
    ctx = load(lay, rerun, prep)
    nm = names(ctx)
    tests = {"ok": None, "summary": "skipped (--skip-tests)"} if skip_tests else run_tests()
    say(f"[extra-reads] tests {'skipped' if skip_tests else ('pass' if tests['ok'] else 'FAIL')}")
    if tests["ok"] is False:
        RX.refuse("the extra tests do not pass (E.6): no read runs")
    rec = XC.run_record(ctx, STAGE, {"procs": procs, "tests": tests})
    rb, rb_err = load_reads_b()
    pl = plan(rb)
    rec["dropped_at_o8"] = pl["dropped_at_o8"]
    rec["not_coded"] = pl["not_coded"]
    rec["reads_b"] = "imported" if rb is not None else f"not importable ({rb_err})"
    coded = set(pl["tier_a"]) | set(pl["tier_b"])
    t = time_accounts(ctx)
    drops, before, after = apply_cap(t, coded, len(ctx.picks), procs)
    rec["projection"] = {"timing_pick": t["pick"], "arms": t["arms"], "minutes_before": round(before["wall_s"] / 60, 2),
                         "minutes_after": round(after["wall_s"] / 60, 2), "account_equivalents": before["account_equivalents"]}
    rec["dropped"] = list(drops)
    ctx.__dict__["xr_cap_dropped"] = set(drops)
    ctx.__dict__["xr_procs"] = procs
    for d in drops:
        say(f"[extra-reads] cap drop: {d}")
    # C5 audit (X-025): a mismatch stops the stage (14)
    t0 = time.time()
    arms = tuple(ctx.__dict__.get("xr_c5_audit_arms") or RL.C5_AUDIT_ARMS)      # E0 and F12.a (a test world sets its own arms)
    aud = RL.c5_audit(ctx, arms=arms)
    rec.part("C5 audit", seconds=round(time.time() - t0, 1), accounts=aud["accounts"], bytes=aud["bytes"], dropped=[], status="pass" if not aud["bad"] else "FAIL")
    say(f"[extra-reads] C5 audit {'pass' if not aud['bad'] else 'FAIL'} {time.time() - t0:.1f}s")
    if aud["bad"]:
        XC.write_out(ctx, os.path.join("errors", f"c5_audit{'_r2' if ctx.rerun else ''}.json"), {"bad": aud["bad"]}, private=True)
        rec.finish()
        RX.refuse("C5 audit: the rebuilt status differs from a real re-run; the finding is handled under section 14")
    results = {}
    ctx.__dict__["xr_results"] = results

    def one(rid: str, tier: str, fn):
        rec.check_disk(EST_READ_BYTES)
        t1 = time.time()
        try:
            r = fn()
            r.setdefault("status", "ok")
        except Exception as exc:  # noqa: BLE001
            r = _failed(rid, tier, exc)
        r = guard_result(ctx, r)
        results[rid] = r
        sec = round(time.time() - t1, 1)
        rec.part(rid, seconds=sec, accounts=int(r.get("accounts") or 0), bytes=int(r.get("bytes") or 0), dropped=list(r.get("parts_dropped") or []),
                 status=r["status"])
        say(f"[extra-reads] {rid} {'pass' if r['status'] == 'ok' else r['status'].upper()} {sec:.1f}s")

    for rid in [x for x in RL.BODY_ORDER if x != "X-046"]:
        one(rid, "A", lambda rid=rid: RA.READS[rid](ctx))
    if rb is not None and pl["tier_b"]:
        rec.check_disk(0.3 * XC.GB)                                       # E.5: expected writes are under 0.3 GB
        t1 = time.time()
        try:
            out, timings, total = run_tier_b(ctx, rb, pl["tier_b"], drops)
        except Exception as exc:  # noqa: BLE001
            out, timings, total = {rid: {"read": rid, "error": f"{type(exc).__name__}: {exc}"} for rid in pl["tier_b"]}, {}, time.time() - t1
        rec.part("tier B pre-pass and reads", seconds=round(total, 1), accounts=0, bytes=0, dropped=list(drops), status="ran")
        raw = {}
        for rid in pl["tier_b"]:
            res_b = out.get(rid) or {"read": rid, "error": "no result"}
            try:
                r = from_b(ctx, rb, rid, res_b)
            except Exception as exc:  # noqa: BLE001
                r = _failed(rid, "B", exc)
            r = guard_result(ctx, r)
            results[rid] = r
            raw[rid] = res_b if r["status"] in ("ok", "dropped") else {"read": rid, "title": r.get("title"), "error": r.get("error") or "failed"}
            rec.part(rid, seconds=round(timings.get(rid, 0.0), 1), accounts=int(r.get("accounts") or 0), bytes=int(r.get("bytes") or 0),
                     dropped=list(r.get("parts_dropped") or []), status=r["status"])
            say(f"[extra-reads] {rid} {'pass' if r['status'] == 'ok' else r['status'].upper()} {timings.get(rid, 0.0):.1f}s")
    tier_b_md, tier_b_private = [], []
    if rb is not None and pl["tier_b"]:
        tier_b_md, tier_b_private, note = render_tier_b(ctx, rb, raw, results)
        rec["tier_b_render"] = note or "one block"
        for rid in pl["tier_b"]:
            rec["parts"][rid]["status"] = results[rid]["status"]
    one("X-046", "A", lambda: RA.read_X_046(ctx, results))
    rec.finish()
    save_state(ctx, results, rec, pl, tier_b_md, tier_b_private)
    return cmd_report(ctx=ctx)


def save_state(ctx, results: dict, rec: dict, pl: dict, tier_b_md: list | None = None, tier_b_private: list | None = None) -> None:
    """The working state: committed parts to $WORK/<pin8>/extra/reads_state.json; the DeepSeek private parts (and the full error texts) to
    ds_private/extra_reads_ds.json."""
    nm = names(ctx)
    pub_keys = ("id", "tier", "title", "status", "error", "public", "md", "md_appendix", "csv", "notes", "parts_dropped")
    state = {"stage": STAGE, "pin8": ctx.pin8, "run": dict(rec), "plan": pl, "tier_b_md": list(tier_b_md or []),
             "reads": {rid: {**{k: r.get(k) for k in pub_keys},
                             "headline": {p: {k: {"public": (v or {}).get("public")} for k, v in (r.get("headline") or {}).get(p, {}).items()}
                                          for p in XC.POOLS}} for rid, r in results.items()}}
    os.makedirs(os.path.dirname(nm["state"]), exist_ok=True)
    with open(nm["state"] + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(RL.jsonable(state), fh, ensure_ascii=False)
    os.replace(nm["state"] + ".tmp", nm["state"])
    priv = {"stage": STAGE, "pin8": ctx.pin8, "tier_b_md_private": list(tier_b_private or []), "reads": {rid: {"private": r.get("private"), "md_private": r.get("md_private"),
                                                             "md_private_appendix": r.get("md_private_appendix"),
                                                             "error_private": r.get("error_private"),
                                                             "headline": {p: {k: {"private": (v or {}).get("private")}
                                                                              for k, v in (r.get("headline") or {}).get(p, {}).items()}
                                                                          for p in XC.POOLS}} for rid, r in results.items()}}
    XC.write_out(ctx, nm["ds_json"], RL.jsonable(priv), private=True)


def _merge(state: dict, priv: dict) -> dict:
    out = {}
    for rid, r in state["reads"].items():
        p = priv["reads"].get(rid) or {}
        out[rid] = {**r, "private": p.get("private"), "md_private": p.get("md_private"), "md_private_appendix": p.get("md_private_appendix")}
    return out


def cmd_report(lay=None, rerun: bool = False, prep=None, ctx=None) -> int:
    """The outputs from the saved state (no recomputation): the committed pages and csv, the private report, then extra_reads.json with
    the private files' sha256."""
    ctx = ctx or load(lay, rerun, prep)
    nm = names(ctx)
    state = json.load(open(nm["state"], encoding="utf-8"))
    ds_path = os.path.join(ctx.ds_private_root, nm["ds_json"])
    priv = json.load(open(ds_path, encoding="utf-8"))
    results = _merge(state, priv)
    pl = state["plan"]
    rows = [RL._strip(row) if row.get("pool") == "ds" else row
            for rid in list(RL.BODY_ORDER) + list(RL.TIER_B) for row in ((results.get(rid) or {}).get("csv") or [])]
    XC.write_out(ctx, nm["ko"], page_ko(ctx, results))
    XC.write_out(ctx, nm["app"], page_appendix(ctx, results, pl, state.get("tier_b_md")))
    XC.write_out(ctx, nm["csv"], rows if rows else [{"read": "", "pool": "", "arm": ""}])
    for name in (nm["ko"], nm["app"]):
        bad = RL.md_rule_problems(ctx, open(os.path.join(ctx.out_dir, name), encoding="utf-8").read())
        if bad:
            os.remove(os.path.join(ctx.out_dir, name))
            raise XC.Refused(f"{name}: a 선택 불가 id on a Korean page")
    try:
        sha_report = XC.write_owner_report_extra(ctx, private_report(ctx, results, nm["twins_private"], priv.get("tier_b_md_private")))
        private_note = "complete"
    except XC.Refused:                                                   # A8 (3) failed with tier B's private part: written without it
        sha_report = XC.write_owner_report_extra(ctx, private_report(ctx, results, nm["twins_private"],
                                                                     ["[비공개] 부록 B는 A8 (3) 검사를 통과하지 못해 이 보고서에서 빠졌습니다."]))
        private_note = "tier B private part left out (A8 3)"
    doc = {"stage": STAGE, "pin8": ctx.pin8, "run": state["run"], "dropped_at_o8": pl["dropped_at_o8"], "not_coded": pl["not_coded"],
           "reads": {rid: {"id": rid, "tier": r.get("tier"), "title": r.get("title"), "status": r.get("status"), "error": r.get("error"),
                           "notes": r.get("notes") or [], "parts_dropped": r.get("parts_dropped") or [],
                           "core": (r.get("public") or {}).get("core") or {}, "ds": (r.get("public") or {}).get("ds") or {"pool": "ds"}}
                     for rid, r in results.items()},
           "ds_private_sha256": RX.sha256_file(ds_path), "ds_owner_report_extra_sha256": sha_report, "private_report": private_note}
    doc = RL.jsonable(doc)
    bad = RL.row_rule_problems(ctx, doc)
    if bad:
        raise XC.Refused(f"{nm['json']}: money on a 선택 불가 row: {scrub(bad[0])}")
    XC.write_out(ctx, nm["json"], doc)
    say(f"[extra-reads] report written: {nm['json']}, {nm['ko']}, {nm['app']}, {nm['csv']} and the private report")
    return 0


# ====================================================================================================== audit
def audit_files(ctx) -> dict:
    """Every committed output: the name rule, common.committed_problems (C8, A8 tripwire, C14), the row rule (json, csv, Korean pages),
    runner_x audit-file (A8, A9), and extra_reads.json's dropped_at_o8 and reads. {name: [problems]}."""
    nm = names(ctx)
    out = {}
    for key in ("json", "ko", "app", "csv"):
        name = nm[key]
        path = os.path.join(ctx.out_dir, name)
        if not os.path.exists(path):
            out[name] = ["missing"]
            continue
        text = open(path, encoding="utf-8").read()
        bad = [] if not name.lower().startswith(XC.NEVER_OUT) else ["named like a stage file"]
        if name.endswith(".json"):
            doc = json.loads(text)
            bad += obj_problems(ctx, name, doc, text)
            ids = {d["id"] for d in doc.get("dropped_at_o8") or []}
            if not set(RL.TIER_C) <= ids or any(d["reason"] != RL.DROP_REASON_C for d in doc["dropped_at_o8"] if d["id"] in RL.TIER_C):
                bad.append("dropped_at_o8 does not list every tier C read with its reason")
            if any(rid not in doc.get("reads", {}) for rid in RL.BODY_ORDER):
                bad.append("a tier A read is missing")
        elif name.endswith(".csv"):
            rows = list(csv.DictReader(io.StringIO(text)))
            bad += obj_problems(ctx, name, rows, text)
        else:
            bad += md_problems(ctx, name, text)
        bad += [f"A8 {b}" for b in RX.audit_a8_file(path)] + [f"A9 {b}" for b in RX.audit_a9_file(path)]
        out[name] = bad
    return out


def audit_private(ctx) -> list:
    """The private report: A8 (3) checks of common.private_report_problems, its sha256 and extra_reads_ds.json's equal the committed ones,
    and both lie outside the repository."""
    nm = names(ctx)
    path = os.path.join(ctx.ds_private_root, nm["report"])
    ds_path = os.path.join(ctx.ds_private_root, nm["ds_json"])
    bad = list(XC.private_report_problems(ctx, path))
    jp = os.path.join(ctx.out_dir, nm["json"])
    doc = json.load(open(jp, encoding="utf-8")) if os.path.exists(jp) else {}
    if os.path.exists(path) and RX.sha256_file(path) != doc.get("ds_owner_report_extra_sha256"):
        bad.append("owner_report_extra sha256 differs from extra_reads.json")
    if not os.path.exists(ds_path) or RX.sha256_file(ds_path) != doc.get("ds_private_sha256"):
        bad.append("extra_reads_ds.json missing or its sha256 differs")
    if os.path.exists(ds_path) and XC._inside(ds_path, ctx.lay.root):
        bad.append("extra_reads_ds.json inside the repository")
    return bad


def cmd_audit(lay=None, rerun: bool = False, private: bool = False, prep=None) -> int:
    ctx = load(lay, rerun, prep)
    ok = True
    if private:
        bad = audit_private(ctx)
        ok = not bad
        say(f"[extra-reads audit] private report {'pass' if ok else 'FAIL'}")
    else:
        for name, bad in audit_files(ctx).items():
            ok &= not bad
            say(f"[extra-reads audit] {name} {'pass' if not bad else 'FAIL'}")
    return 0 if ok else 1


def main(argv=None, lay=None, prep=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--procs", type=int, default=1, help="processes the projection assumes (the reads themselves run in this process)")
    r.add_argument("--rerun", action="store_true", help="after an A select rerun (14): the select_r2 files, _r2 outputs")
    r.add_argument("--skip-tests", action="store_true", help="do not rerun the extra tests first (recorded in the run record)")
    p = sub.add_parser("report")
    p.add_argument("--rerun", action="store_true")
    a = sub.add_parser("audit")
    a.add_argument("--rerun", action="store_true")
    a.add_argument("--private", action="store_true", help="A8 (3) on the private report and the private files' sha256")
    args = ap.parse_args(argv)
    if args.cmd == "run":
        return cmd_run(lay, args.procs, args.rerun, args.skip_tests, prep)
    if args.cmd == "report":
        return cmd_report(lay, args.rerun, prep)
    return cmd_audit(lay, args.rerun, args.private, prep)


if __name__ == "__main__":
    sys.exit(main())
