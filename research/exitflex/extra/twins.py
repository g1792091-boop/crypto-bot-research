"""Twin accounts of the exit study (research/exitflex/PREREG_EXITFLEX_EXTRA.md, section TW, with the decisions of TW.0).

    python research/exitflex/extra/twins.py check                                  # TW-C1..C5 and the disk need -> out/twins_check.json
    python research/exitflex/extra/twins.py run    [--procs N] [--rerun]           # every twin account -> $WORK/<pin8>/extra/twins/results/
    python research/exitflex/extra/twins.py report [--rerun] [--o8-breach] [--fix N --fix-note TEXT]
    python research/exitflex/extra/twins.py audit  [--rerun] [--private]           # TW-A1..A8, or TW-A9 alone with --private

Four unit kinds per pick p of A's 38 (TW.2):
  x twin     '<pick id>-x'             the cell's default combo, E0 (the pick's exit) and A's 88 variants, sizes 0.25 and 1.0;
  house      'base-<kind>-<name>-<tf>' the default combo with ``ladder|2`` (exit index 0), sizes 0.25 and 1.0;
  house + V  the house under A's variants translated by ``exit_of_pick`` onto exit index 0 (F13.a / F13.b equal E0: not run);
  coin flip  '<pick id>-flip' (seed 0) and '<pick id>-flip-x<s>' (s = 1..19): the pick's own numbers and signal times with the side
             from sha256('<unit id>|<close ms>')[0] & 1, quarter size (seed 0 also E0 at 1.0, TW.0 item 3); F11 and F12 are not run.
Descriptive only: no test, gate or choice. Every command prints pass / fail, counts and progress, never a figure. DeepSeek money goes
only to $WORK/<pin8>/ds_private/extra/twins/ (D11, TW.6); this module never writes $WORK/<pin8>/ds_private/owner_report_extra.md.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True                         # TW.3: before A's modules are imported

import argparse  # noqa: E402
import contextlib  # noqa: E402
import copy  # noqa: E402
import datetime as dt  # noqa: E402
import hashlib  # noqa: E402
import importlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402

import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
XDIR = os.path.dirname(HERE)
ROOT = os.path.dirname(os.path.dirname(XDIR))
for _p in (XDIR, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import data_x as DX  # noqa: E402
import kernel_x as KX  # noqa: E402
import metrics as MT  # noqa: E402
import runner_x as RX  # noqa: E402  (only the pure helpers TW.3 names; TW.0 item 7)

K = KX.K
PERIOD = "select"                                      # the only period: there is no path to the confirm
SIZES = (0.25, 1.0)
TAG = {0.25: "q25", 1.0: "q100"}
N_SEEDS = 20
FLIP_TAG = "q25__s00-19"                               # 20 seeds stacked in one file (TW.3)
FLIP_LIVE_TAG = "q100__s00"                            # TW.0 item 3: seed 0 also runs E0 at size 1.0
THIN_ENTRIES = 30                                      # 거래 적음: own E0 entered < 30 at quarter size
NO_FLIP = ("F11.a", "F11.b", "F12.a", "F12.b")         # never run on a flipped offer (TW.2)
F1112 = NO_FLIP
F13_IDS = ("F13.a", "F13.b")
F3_SAME_NAMES = ("F7_RF_ONLY",)                        # F11 = F3 marks (A Known limit 11; TW-C5)
KINDS = ("pick", "x", "house", "flip")
# TW.3: twins.py holds its own copies of the league's ROLE_KO labels (dashboard order), the base- id format and flip_side
ROLE_KO = {"cand": "후보", "quarter": "1/4 크기", "exitonly": "청산만 바꾼 기본값", "base": "기본값", "flip": "동전 던지기"}
BASE_ID = "base-{kind}-{name}-{tf}"
N_SINGLE_FILES, N_FLIP_FILES = 13_376, 3_230           # TW.8
NEED_FLOOR, NEED_CACHE, NEED_MARGIN = 0.8e9, 0.15e9, 0.5e9
P_VALUE = re.compile(r"\bp\s*[=<>]|p값|p-value", re.I)
A8_SCOPE = ("select.json", "confirm.json", "sent.json", "choice.json", "SELECT_KO.md", "REPORT_KO.md", "select_r2.json", "SELECT_KO_r2.md",
            "sent_r2.json", "choice_r2.json", "confirm_r2.json", "REPORT_KO_r2.md")
COMMITTED = re.compile(r"^(twins_check|twins|TWINS_KO)(_r2|_fix\d+)?\.(json|md)$")
assert K.EXITS[0][0] == "ladder|2"

# TW.6: the only keys a DeepSeek row of a committed twin file may hold, and the keys nested dictionaries may hold
DS_TWIN_ALLOWED = {"id", "kind", "size", "name_ko", "order", "same_as_f3", "mark", "n_units", "thin_ids",
                   "entered", "entered_e0", "entered_change_pct", "skipped", "skipped_e0", "rejected", "closed", "win_share",
                   "hold", "hold_e0", "reasons", "reasons_e0", "dir_hold", "dir_entries"}
DS_NESTED_ALLOWED = {"median", "p90", "share_gt4", "share_gt8", "share_gt18", "seed_median", "seed_min", "seed_max"} | set(MT.REASONS)
DS_NEVER = {"offered", "no_fill", "after_bust", "bust", "busts", "w_end", "g", "G", "M", "M_pct_month", "max_dd", "final_multiple",
            "n_pos", "same_side", "dir_growth"}
DS_POOL_KEYS = {"n_units", "eligible_ids", "thin_ids", "removed", "f11_note", "rows", "table1"}
DS_SECTION_WORDS = re.compile(r"성장|나아|나빠|같은 쪽|반대 쪽|%/월|파산|낙폭|배수|최종|지갑|수익|손실|G_P|M_P")
assert not (DS_TWIN_ALLOWED & DS_NEVER)

# ------------------------------------------------------------------ the Korean report's fixed text (TW.5, verbatim)
FIXED_LINES = (
    "이 표로는 고르지 않습니다. 고르는 건 A 표(SELECT_KO.md)의 '선택 가능' 줄에서만 하시고, 이 표는 그 줄이 기본수치와 동전 계좌에서도 같은 쪽으로 움직이는지 참고로만 보세요.",
    "고를 수 있는 것은 A 표(SELECT_KO.md)의 '선택 가능' 줄의 청산 id뿐입니다. 숫자를 기본수치로 바꾸기, 규칙봇 청산으로 바꾸기, 동전 계좌는 이번 선택지에 없습니다(A 12).",
    "'규칙봇 청산 위에' 줄은 실제로 돌고 있는 규칙봇의 청산을 바꾸자는 제안이 아닙니다. 규칙봇은 이번 연구 범위 밖입니다(A 12).",
    "이 계좌들의 정의는 A 계획이 고정된 뒤, A 고르기 계산이 시작되기 전에 고정했고, 계산 코드는 A 고르기 결과를 열기 전에 고정했습니다. 참고용이고, 시험, 가짜 규칙 비교, 통과 기준이 없습니다.",
    "A의 통과 기준(코어 23개 중 14개·딥시크 15개 중 9개 픽에서 나아짐, 가짜 규칙 비교, 진입 횟수)은 쌍둥이 계좌에 적용되지 않습니다. 쌍둥이에는 통과·탈락이 없습니다.",
    "2021~2023년은 커스텀값과 지금 청산을 고른 기간입니다. 이 기간에 커스텀값이 기본수치보다 좋아 보이는 건 당연하고 증거가 아닙니다.",
    "커스텀값이 기본수치보다 나은지는 앞으로 쌓이는 리그 기록으로만 알 수 있습니다. A 계획대로 리그를 다시 시작하면 그 비교 계좌(기본값·청산만 바꾼 기본값)가 없어지므로, 이 비교를 계속하려면 따로 정해야 합니다(A 11.3).",
    "2024~2026 숫자는 없습니다.")
O8_BREACH_LINE = "쌍둥이 계좌의 정의는 A 고르기 계산 전에 고정되었고, 코드는 A 고르기 결과를 연 뒤에 고정되었습니다."
GLOSSARY = (
    "커스텀값: 지금 후보 리그 픽의 숫자(5년 연구에서 고른 숫자).",
    "기본수치: 규칙봇 숫자(매매법마다 원래 정해진 기본 설정값).",
    "지금 청산(E0): 지금 후보 리그 픽의 청산(3R 고정 익절과 그 손절 등).",
    "규칙봇 청산: 2 ATR 손절 + 계단 잠금(순 ROE, 곧 수수료를 뺀 증거금 대비 수익이 12%에 닿으면 10%를 잠그고, 17%면 15%, 22%면 20% ...).",
    "청산만 바꾼 기본값 계좌: 기본수치 + 지금 청산(리그의 같은 이름 계좌).",
    "기본값 계좌: 기본수치 + 규칙봇 청산(리그의 같은 이름 계좌).",
    "규칙봇 청산 위에: 기본값 계좌에 A의 청산 규칙을 얹은 것. '.a'는 계단 잠금과 그 규칙을 함께, '.b'는 잠금 없이 2 ATR 손절과 그 규칙(11번·12번 '.b'는 매매법 자체 목표가 포함). 13번(규칙봇 계단 잠금)은 기본값 계좌와 같아 따로 계산하지 않았습니다.",
    "동전 던지기 계좌: 커스텀값 픽과 같은 신호 시각에 방향만 동전으로 정한 계좌. 20번 따로 던졌고, 리그의 동전 계좌는 그중 1번째 동전입니다. 리그 계좌는 실제 크기로 돌고, 이 보고서는 1/4 크기만 계산했습니다. 11번(매매법 자체 청산)과 12번(9가지 청산 동시 적용)은 동전 계좌로 계산하지 않았습니다.",
    "이 표의 '기본값 계좌'는 리그 화면의 그 계좌입니다. A 표의 '기본값'(답이 없을 때 자동으로 넣는 청산)과 다릅니다.",
    "거래 적음: 지금 청산으로 3년 동안 1/4 크기에서 진입이 30번 미만인 칸. 모든 합계에 그대로 들어 있습니다.")
CARD_A_LINE = "픽 칸은 '선택 가능' 줄만 보여 주므로 진입은 늘 '늘어남' 또는 '같음'입니다. A의 통과 기준을 넘은 줄만 남겼기 때문이고, 증거가 아닙니다."
TABLE1_LINES = (
    "리그는 이 다섯 계좌를 2026-10-11부터 앞으로 돌리고 있습니다. 이 표는 같은 정의의 계좌를 2021~2023년에 대해 연구 계산기로 다시 계산한 것이고, 리그 기록이 아닙니다.",
    "리그의 동전 계좌는 실제 크기로 돌고, 이 표의 동전은 1/4 크기입니다.",
    "5년 연구 성적표의 같은 칸 숫자와 다릅니다. 이번 계산은 2021~2023년, 한 번에 한 자리, 1분봉이고, 자리를 잡고 있는 동안 놓친 신호까지 셉니다.",
    "이 표의 차이로 리그 계좌를 고르거나 바꾸지 않습니다.")
FLIP20_LINE = "'동전 20번' 줄은 20번 던진 결과의 가운데 값이고, 보유 시간과 진입 칸에는 [가장 낮은 ~ 가장 높은] 값도 적었습니다."
FLIP_LIVE_LINE = ("'실제 크기' 동전 줄은 리그의 동전 계좌와 같은 크기로 1번째 동전의 지금 청산만 한 번 더 계산한 것입니다"
                  "(나머지 동전 계산은 모두 1/4 크기).")
CARD_D_LINES = (
    "픽 칸의 성장은 늘 '나아짐'입니다. A의 통과 기준을 넘은 줄만 남겼기 때문이고, 증거가 아닙니다.",
    "효과가 없어도 대략 절반은 '나아짐'으로 나옵니다. 같은 쪽이라는 것만으로는 증명되는 것이 없습니다.",
    "'나아짐'이나 '같은 쪽'의 개수를 더해 점수처럼 쓰지 마세요.",
    "동전 계좌에서도 나아졌다고 그 청산이 좋다는 증거는 아닙니다. 동전 계좌는 픽과 같은 시각에 들어가므로, 그 시각의 시장 움직임 덕분일 수도 있습니다.")
TABLE4_LINES = ("커스텀값은 이 기간을 보고 고른 숫자라 픽이 앞서는 게 당연합니다.",
                "기본수치가 앞서는 줄이 있어도 리그 픽의 숫자를 바꾸는 근거가 되지 않습니다.")
THIN_HEAD = "거래 적음(지금 청산으로 3년 동안 진입 30번 미만, 모든 합계에 그대로 들어 있음):"
DS_LINE = "딥시크는 거래 수·승률·보유 시간만 적습니다. 딥시크의 돈 숫자는 대화창에서만 보여 드리는 비공개 보고서에 있습니다."
LAST_LINE = "답은 A 표의 id(예: F9.a)로만 해 주세요. 이 보고서의 계좌 이름이나 숫자로 답하지 마세요."
FIX_RULE_LINE = "고르기 규칙과 마감은 그대로입니다."
F11_NOTE = "(F7_RF_ONLY 3칸은 = F3.a / = F3.b)"
MARK_HOUSE_F13, MARK_NO_FLIP, MARK_REMOVED = "= 기본값 계좌", "동전 없음(계산 안 함)", "기본수치에서 계산 못 함"
KIND_KO = {"pick": "픽", "x": "청산만 바꾼 기본값", "house": "규칙봇 청산 위에", "flip": "동전"}


class TwinsRefused(SystemExit):
    """A twins command refuses to run (gate, cut, disk, a missing or unpinned file); nothing runs (TW.10)."""


def refuse(msg: str):
    raise TwinsRefused(f"[twins refused] {msg}")


def say(msg: str) -> None:
    print(msg, flush=True)


# ------------------------------------------------------------------ units and ids (TW.2)
def flip_side(account_id: str, close_ms: int) -> int:
    return 1 if hashlib.sha256(f"{account_id}|{close_ms}".encode()).digest()[0] & 1 else -1


def x_id(p: dict) -> str:
    return p["id"] + "-x"


def base_id(p: dict) -> str:
    return BASE_ID.format(kind=p["kind"], name=p["name"], tf=p["tf"])


def flip_id(p: dict, s: int) -> str:
    return f"{p['id']}-flip" if s == 0 else f"{p['id']}-flip-x{s}"


def strategy(p: dict) -> str:
    return f"{p['kind']}:{p['name']}"


def twin_pick(p: dict, combo: dict) -> dict:
    return {**p, "id": x_id(p), "combo": combo}


def house_pick(p: dict, combo: dict) -> dict:
    return {**p, "id": base_id(p), "combo": combo, "exit": "ladder|2", "exit_index": 0}


def unit_ids(p: dict) -> dict:
    return {"x": x_id(p), "house": base_id(p), "flip": flip_id(p, 0)}


# ------------------------------------------------------------------ layout, paths, context
class TLayout:
    """Where the twins' files live; tests point it at temporary folders. ``a`` is A's runner Layout."""

    def __init__(self, a=None, extra_dir=None, extra_sha=None, out=None, deviations=None):
        self.a = a or RX.Layout()
        self.root = self.a.root
        self.extra_dir = extra_dir or os.path.join(self.a.base, "extra")
        self.extra_sha = extra_sha or os.path.join(self.a.base, "PREREG_EXITFLEX_EXTRA.sha256")
        self.extra_md = os.path.join(os.path.dirname(self.extra_sha), "PREREG_EXITFLEX_EXTRA.md")
        self.out = out or os.path.join(self.extra_dir, "out")
        self.deviations = deviations or os.path.join(self.a.base, "DEVIATIONS.md")

    def xlay(self):
        """A runner Layout whose pin file is PREREG_EXITFLEX_EXTRA.sha256 (for read_sha_file / require_pinned_file)."""
        return RX.Layout(base=self.a.base, root=self.root, sha_file=self.extra_sha, pin_file=self.a.pin_file, required=())

    def out_file(self, name: str) -> str:
        return os.path.join(self.out, name)


class Paths:
    """$WORK/<pin8>/extra/twins/ (core) and $WORK/<pin8>/ds_private/extra/twins/ (DeepSeek) and A's select files (TW.3)."""

    def __init__(self, work: str, ph: str, rerun: bool = False, results_sfx: str | None = None):
        self.root = os.path.join(work, DX.pin8(ph))
        self.tw = os.path.join(self.root, "extra", "twins")
        self.ptw = os.path.join(self.root, "ds_private", "extra", "twins")
        sfx = "_r2" if rerun else ""
        rs = sfx if results_sfx is None else results_sfx
        self.results = {"core": os.path.join(self.tw, "results" + rs), "ds": os.path.join(self.ptw, "results" + rs)}
        self.cache, self.check_tmp = os.path.join(self.tw, "cache"), os.path.join(self.tw, "check_tmp")
        self.run_record = os.path.join(self.tw, f"run_record{rs}.json")
        self.isolation = os.path.join(self.tw, "isolation.json")
        self.ds_json = os.path.join(self.ptw, f"twins_ds{sfx}.json")
        self.private_md = os.path.join(self.ptw, f"owner_report_extra_twins{sfx}.md")
        self.owner_extra = os.path.join(self.root, "ds_private", f"owner_report_extra{sfx}.md")
        stage = "select_r2" if rerun else "select"
        self.a_results = {"core": os.path.join(self.root, "results", stage), "ds": os.path.join(self.root, "ds_private", "results", stage)}


class Ctx:
    """Everything a twins step needs. ``make_pickdata(unit pick, with_f11)`` builds chart data (real: the cut and the pinned
    param_defs; tests: a synthetic provider); ``default_combo(kind, name)`` gives the cell's default numbers (lists as tuples)."""

    def __init__(self, tl, pin, ph, market, picks, variants, make_pickdata, default_combo, procs=1, rerun=False, removed=(),
                 f11_mark=None, results_sfx=None, native_check=None, league_flip=None):
        self.tl, self.pin, self.ph, self.market, self.picks = tl, pin, ph, market, list(picks)
        self.variants = [v for v in variants if v.id != "E0"]
        self.make_pickdata, self.default_combo, self.procs, self.rerun = make_pickdata, default_combo, procs, rerun
        self.removed = set(removed)
        self.f11_mark = dict(f11_mark or {"x": False, "house": False})
        self.paths = Paths(pin["work"], ph, rerun, results_sfx)
        self.edges = MT.month_edges(PERIOD)
        self.by_id = {p["id"]: p for p in self.picks}
        self.native_check, self.league_flip = native_check, league_flip


def arms(ctx: Ctx, kind: str, p: dict) -> list:
    """The arms of a unit kind (TW.2): E0 first, then the variants in canonical order."""
    vs = [KX.E0] + list(ctx.variants)
    if kind == "flip":
        return [v for v in vs if v.id not in NO_FLIP]
    if kind == "house":
        vs = [v for v in vs if v.id not in F13_IDS]
    if strategy(p) in ctx.removed:
        vs = [v for v in vs if v.id not in F1112]
    return vs


def twin_file(ctx: Ctx, p: dict, kind: str, arm: str, tag: str) -> str:
    return os.path.join(ctx.paths.results[p["pool"]], unit_ids(p)[kind], f"{arm}__{tag}.npz")


def a_file(ctx: Ctx, p: dict, arm: str, tag: str) -> str:
    """A's per-account select result file of a pick (read as a program only, A 16.7 item 4)."""
    return os.path.join(ctx.paths.a_results[p["pool"]], p["id"], f"{arm}__{tag}.npz")


def files_of(ctx: Ctx, p: dict) -> list:
    out = [twin_file(ctx, p, k, v.id, TAG[s]) for k in ("x", "house") for v in arms(ctx, k, p) for s in SIZES]
    out += [twin_file(ctx, p, "flip", v.id, FLIP_TAG) for v in arms(ctx, "flip", p)]
    return out + [twin_file(ctx, p, "flip", "E0", FLIP_LIVE_TAG)]


def expected(ctx: Ctx) -> list:
    return [f for p in ctx.picks for f in files_of(ctx, p)]


def account_counts(ctx: Ctx) -> dict:
    n = {"x": 0, "house": 0, "house_e0": 0, "flip": 0}
    for p in ctx.picks:
        n["x"] += 2 * len(arms(ctx, "x", p))
        n["house_e0"] += 2
        n["house"] += 2 * (len(arms(ctx, "house", p)) - 1)
        n["flip"] += N_SEEDS * len(arms(ctx, "flip", p)) + 1
    n["total"] = sum(n.values())
    return n


# ------------------------------------------------------------------ accounts
def assert_select_only(market) -> None:
    """A5 / TW-A3: no array of the twin process holds a minute at or after 2024-01-01."""
    DX.assert_no_minute_at_or_after({s: {"ts": market.ts(i)} for i, s in enumerate(market.symbols)}, DX.SELECT_CUT_MS)


def sim(ctx: Ctx, pdata, v, scale: float, offered: dict | None = None, period: str = PERIOD, force_end: bool = True):
    """One account through A's kernel. Refuses the confirm period, F11 / F12 on a flipped offer and F11 / F12 on a unit built
    without the strategy's own exit (TW-C2 removal)."""
    if period != PERIOD:
        raise ValueError("the twins run on the select period only")
    if offered is not None and v.id in NO_FLIP:
        raise ValueError(f"{v.id} is not run on a flipped offer (TW.2)")
    if v.id in F1112 and getattr(pdata, "no_f11", False):
        raise ValueError(f"{v.id} was removed from this unit (TW-C2)")
    return KX.simulate(ctx.market, pdata, v, scale, PERIOD, force_end=force_end, offered=offered)


def flip_offer(pdata, off: dict, side) -> dict:
    """A new offer with every key of ``off``: side replaced (int64), best' by side' at tp_idx (bool), lvl NaN; the rest and the order
    are kept and ``off`` is never modified (TW.2)."""
    side = np.asarray(side, np.int64)
    out = dict(off)
    out["side"] = side
    out["best"] = np.where(side > 0, pdata.best_l[off["tp_idx"]], pdata.best_s[off["tp_idx"]]).astype(bool)
    out["lvl"] = np.full(len(side), np.nan)
    return out


def flipped(pdata, off: dict, acct: str) -> dict:
    return flip_offer(pdata, off, [flip_side(acct, int(c)) for c in off["close"]])


def light(res, edges) -> dict:
    """``MT.summarize_light`` plus the hold of every entered trade in whole minutes (entry order), the sum of wallet changes and W_0."""
    d = MT.summarize_light(res, edges)
    ent = res.status == 1
    d["hold_min"] = ((res.exit_ts[ent] - res.entry_ts[ent]) // 60_000).astype(np.int32)
    d["pnl_sum"] = float(np.sum(res.pnl[ent]))
    d["w0"] = float(res.w0)
    return d


def stack(items: list) -> dict:
    d = MT.stack_light(items)
    d["hold_min"] = np.concatenate([np.asarray(i["hold_min"], np.int32) for i in items])
    d["hold_n"] = np.array([len(i["hold_min"]) for i in items], np.int64)
    d["pnl_sum"] = np.array([i["pnl_sum"] for i in items])
    d["w0"] = float(items[0]["w0"])
    return d


def save(path: str, doc: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path[:-4] + ".part.npz"
    np.savez_compressed(tmp, **{k: np.asarray(v) for k, v in doc.items()})
    os.replace(tmp, path)


def load(path: str) -> dict:
    with np.load(path) as z:
        return {k: z[k] for k in z.files}


def unit_data(ctx: Ctx, p: dict) -> tuple:
    """(x twin PickData, house PickData): one build on the default combo; the house is a copy.copy with the house pick (TW.3)."""
    combo = ctx.default_combo(p["kind"], p["name"])
    removed = strategy(p) in ctx.removed
    xd = ctx.make_pickdata(twin_pick(p, combo), not removed)
    xd.no_f11 = removed
    hd = copy.copy(xd)
    hd.pick = house_pick(p, combo)
    return xd, hd


def run_pick(ctx: Ctx, p: dict) -> int:
    """Every missing result file of one pick's x twin, house and flip units. Returns the number of files written."""
    made = 0
    todo = {k: [(v, s) for v in arms(ctx, k, p) for s in SIZES if not os.path.exists(twin_file(ctx, p, k, v.id, TAG[s]))]
            for k in ("x", "house")}
    if todo["x"] or todo["house"]:
        xd, hd = unit_data(ctx, p)
        for kind, pdata in (("x", xd), ("house", hd)):
            for v, s in todo[kind]:
                save(twin_file(ctx, p, kind, v.id, TAG[s]), light(sim(ctx, pdata, v, s), ctx.edges))
                made += 1
        del xd, hd
    todo_f = [v for v in arms(ctx, "flip", p) if not os.path.exists(twin_file(ctx, p, "flip", v.id, FLIP_TAG))]
    live = twin_file(ctx, p, "flip", "E0", FLIP_LIVE_TAG)
    if todo_f or not os.path.exists(live):
        pdata = ctx.make_pickdata(p, True)
        off = pdata.offered(PERIOD, ctx.market)
        offs = [flipped(pdata, off, flip_id(p, s)) for s in range(N_SEEDS)]
        for v in todo_f:
            save(twin_file(ctx, p, "flip", v.id, FLIP_TAG), stack([light(sim(ctx, pdata, v, 0.25, o), ctx.edges) for o in offs]))
            made += 1
        if not os.path.exists(live):
            save(live, stack([light(sim(ctx, pdata, KX.E0, 1.0, offs[0]), ctx.edges)]))
            made += 1
    return made


_CTX: dict = {}


def _worker(pid: str) -> int:
    ctx = _CTX["ctx"]
    return run_pick(ctx, ctx.by_id[pid])


def run_all(ctx: Ctx, quiet: bool = False) -> int:
    """Every missing result file (a resume computes only those); progress lines only (files done, out of how many)."""
    assert_select_only(ctx.market)
    files = expected(ctx)
    done = sum(os.path.exists(f) for f in files)
    todo = [p["id"] for p in ctx.picks if not all(os.path.exists(f) for f in files_of(ctx, p))]
    made = 0
    if not quiet:
        say(f"[twins run] {done}/{len(files)} files")
    if ctx.procs <= 1 or len(todo) <= 1:
        for pid in todo:
            n = run_pick(ctx, ctx.by_id[pid])
            done, made = done + n, made + n
            if not quiet:
                say(f"[twins run] {done}/{len(files)} files")
        return made
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor, as_completed
    _CTX["ctx"] = ctx
    with ProcessPoolExecutor(ctx.procs, mp_context=mp.get_context("fork")) as ex:
        for f in as_completed([ex.submit(_worker, pid) for pid in todo]):
            n = f.result()
            done, made = done + n, made + n
            if not quiet:
                say(f"[twins run] {done}/{len(files)} files")
    return made


# ------------------------------------------------------------------ metrics (TW.4)
def thin(entered: int) -> bool:
    """거래 적음: the unit's own E0 entered fewer than 30 trades at quarter size in the 36 months (29 is thin, 30 is not)."""
    return entered < THIN_ENTRIES


def pct(m: float) -> float:
    return 100.0 * (math.exp(m) - 1.0)


def chg(a, b) -> float:
    return 100.0 * (a / b - 1.0) if b else 0.0


def isnan(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def sgn(x):
    if isnan(x):
        return None
    return 1 if x > 0 else (-1 if x < 0 else 0)


DIR_WORDS = {"dir_hold": {-1: "짧아짐", 1: "길어짐", 0: "같음"}, "dir_entries": {1: "늘어남", -1: "줄어듦", 0: "같음"},
             "dir_growth": {1: "나아짐", -1: "나빠짐", 0: "같음"}}


def word(key: str, x) -> str:
    s = sgn(x)
    return "-" if s is None else DIR_WORDS[key][s]


def same_side(kind_m, pick_m) -> str:
    """TW.4: 같은 쪽 when sign M(kind) = sign M(pick) != 0, 반대 쪽 when both are non-zero and opposite, else 0."""
    a, b = sgn(kind_m), sgn(pick_m)
    if a and b:
        return "같은 쪽" if a == b else "반대 쪽"
    return "0"


def hold_of(ss: list) -> dict:
    """Median, p90 and the shares over 4, 8 and 18 h over all entered trades of the accounts, from ``hold_min`` (MT.hold_stats on hours)."""
    hm = [np.asarray(s["hold_min"], np.int64) for s in ss]
    return MT.hold_stats((np.concatenate(hm) if hm else np.zeros(0, np.int64)) / 60.0)


def _cnt(ss: list, name: str) -> int:
    return int(sum(MT.count(s, name) for s in ss))


def _reasons(ss: list) -> dict:
    tot = np.sum([np.asarray(s["reasons"]) for s in ss], axis=0) if ss else np.zeros(len(MT.REASONS), np.int64)
    return dict(zip(MT.REASONS, [int(x) for x in tot]))


def fig(sv: list, se: list) -> dict:
    """V against the kind's own E0 over the same units at one size (single-account kinds; TW.4). Keys with '_' stay internal."""
    n = len(sv)
    G = [float(np.mean(s["g"])) for s in sv]
    Mp = [float(np.mean(np.asarray(a["g"]) - np.asarray(b["g"]))) for a, b in zip(sv, se)]
    M = float(np.mean(Mp)) if n else 0.0
    h, h0 = hold_of(sv), hold_of(se)
    ent, ent0, closed = _cnt(sv, "entered"), _cnt(se, "entered"), _cnt(sv, "closed")
    return {"n_units": n, "entered": ent, "entered_e0": ent0, "entered_change_pct": chg(ent, ent0),
            "skipped": _cnt(sv, "skipped"), "skipped_e0": _cnt(se, "skipped"), "rejected": _cnt(sv, "rejected"), "closed": closed,
            "win_share": _cnt(sv, "wins") / max(1, closed), "hold": h, "hold_e0": h0, "reasons": _reasons(sv), "reasons_e0": _reasons(se),
            "dir_hold": word("dir_hold", h["median"] - h0["median"]), "dir_entries": word("dir_entries", ent - ent0),
            "G": float(np.mean(G)) if n else 0.0, "M": M, "M_pct_month": pct(M), "dir_growth": word("dir_growth", M),
            "n_pos": int(sum(m > 0 for m in Mp)), "busts": _cnt(sv, "bust"),
            "final_multiple_median": float(np.median([float(s["w_end"]) / float(s["w0"]) for s in sv])) if n else float("nan"),
            "max_dd_median": float(np.median([float(s["max_dd"]) for s in sv])) if n else float("nan"), "_G": G, "_Mp": Mp}


def seed_view(f: dict, s: int) -> dict:
    hn = np.asarray(f["hold_n"])
    a = int(hn[:s].sum())
    return {"g": f["g"][s], "w_end": f["w_end"][s], "w0": f["w0"], "max_dd": f["max_dd"][s], "counts": f["counts"][s],
            "reasons": f["reasons"][s], "hold_min": f["hold_min"][a:a + int(hn[s])], "pnl_sum": f["pnl_sum"][s]}


def sstat(xs) -> dict:
    xs = np.asarray(xs, float)
    return {"seed_median": float(np.median(xs)), "seed_min": float(np.min(xs)), "seed_max": float(np.max(xs))}


def fig_flip(fv: list, fe: list) -> dict:
    """Flips (TW.4): every figure per seed, pooled over the units; the median, lowest and highest over the seeds; the seeds with
    M_P > 0; directions by the sign of the median over seeds of the per-seed differences."""
    ns = len(fv[0]["g"]) if fv else N_SEEDS
    per = [fig([seed_view(f, s) for f in fv], [seed_view(f, s) for f in fe]) for s in range(ns)]
    hk = ("median", "p90", "share_gt4", "share_gt8", "share_gt18")

    def hst(key):
        return {st: {k: float(fn([p[key][k] for p in per])) for k in hk}
                for st, fn in (("seed_median", np.median), ("seed_min", np.min), ("seed_max", np.max))}

    med = lambda key: float(np.median([p[key] for p in per]))   # noqa: E731
    Ms = [p["M"] for p in per]
    return {"n_units": len(fv), "entered": sstat([p["entered"] for p in per]), "entered_e0": sstat([p["entered_e0"] for p in per]),
            "entered_change_pct": med("entered_change_pct"), "skipped": med("skipped"), "skipped_e0": med("skipped_e0"),
            "rejected": med("rejected"), "closed": med("closed"), "win_share": med("win_share"), "hold": hst("hold"),
            "hold_e0": hst("hold_e0"), "reasons": {r: float(np.median([p["reasons"][r] for p in per])) for r in MT.REASONS},
            "reasons_e0": {r: float(np.median([p["reasons_e0"][r] for p in per])) for r in MT.REASONS},
            "dir_hold": word("dir_hold", float(np.median([p["hold"]["median"] - p["hold_e0"]["median"] for p in per]))),
            "dir_entries": word("dir_entries", float(np.median([p["entered"] - p["entered_e0"] for p in per]))),
            "G": sstat([p["G"] for p in per]), "M": sstat(Ms), "dir_growth": word("dir_growth", float(np.median(Ms))),
            "n_pos": int(sum(m > 0 for m in Ms)), "busts": sstat([p["busts"] for p in per]),
            "final_multiple_median": sstat([p["final_multiple_median"] for p in per]),
            "max_dd_median": sstat([p["max_dd_median"] for p in per]), "_per": per}


E0_KEYS = ("n_units", "entered", "skipped", "rejected", "closed", "win_share", "hold", "reasons", "G", "busts", "final_multiple_median",
           "max_dd_median")


def e0_only(d: dict) -> dict:
    return {k: d[k] for k in E0_KEYS if k in d}


def adapt_a(a: dict) -> dict:
    """A's per-account summary (MT.summarize) in the twins' light layout (hold in whole minutes from the trade times)."""
    return {"g": a["g"], "w_end": a["w_end"], "w0": a["w0"], "max_dd": a["max_dd"], "counts": a["counts"], "reasons": a["reasons"],
            "hold_min": ((np.asarray(a["tr_exit"], np.int64) - np.asarray(a["tr_fill"], np.int64)) // 60_000).astype(np.int32)}


class Files:
    """Cached loads of the twins' result files and A's select files of E0 and the choosable ids (never of a 선택 불가 id)."""

    def __init__(self, ctx: Ctx, allowed: dict):
        self.ctx, self.allowed, self._c = ctx, allowed, {}

    def _get(self, path):
        if path not in self._c:
            self._c[path] = load(path)
        return self._c[path]

    def t(self, p, kind, arm, size=0.25):
        return self._get(twin_file(self.ctx, p, kind, arm, TAG[size]))

    def f(self, p, arm, tag=FLIP_TAG):
        return self._get(twin_file(self.ctx, p, "flip", arm, tag))

    def a(self, p, arm, tag="q25"):
        if arm not in self.allowed[p["pool"]]:
            raise ValueError(f"{arm} is not E0 or a choosable id of pool {p['pool']}: its file is never read")
        return adapt_a(self._get(a_file(self.ctx, p, arm, tag)))


def select_rows(sel: dict, pool: str, order: dict) -> tuple:
    """(choosable ids in A's canonical order, {id: the fields TW.5 reads}); no field of a 선택 불가 row is read."""
    P = sel["pools"][pool]
    elig = sorted(P["eligible_ids"], key=lambda i: order.get(i, 10 ** 6))
    keys = ("name_ko", "hold", "entered", "entered_e0") + (("M", "M_pct_month", "Mp", "live") if pool == "core" else ())
    rows = {}
    for r in P["variants"]:
        if r["id"] in elig:
            rows[r["id"]] = {k: r[k] for k in keys}
    return elig, rows


def pool_doc(ctx: Ctx, F: Files, sel: dict, pool: str) -> dict:
    """Every figure of one pool (money included): rows E0 + choosable ids x the four kinds, Table 1, Table 4, the 거래 적음 ids."""
    picks = [p for p in ctx.picks if p["pool"] == pool]
    N = len(picks)
    order = {v.id: i + 1 for i, v in enumerate(ctx.variants)}
    elig, srows = select_rows(sel, pool, order)
    f7 = any(p["name"] in F3_SAME_NAMES for p in picks)
    rows = []

    def add(vid, kind, d, mark=None, f3=None):
        name = "지금 청산(E0)" if vid == "E0" else srows[vid]["name_ko"]
        rows.append({"id": vid, "kind": kind, "size": 0.25, "order": 0 if vid == "E0" else order[vid], "name_ko": name, "mark": mark,
                     "same_as_f3": f3, **d})

    a_e0 = [F.a(p, "E0", "q25") for p in picks]
    a_e0l = [F.a(p, "E0", "q100") for p in picks]
    e0 = {"x": [F.t(p, "x", "E0") for p in picks], "house": [F.t(p, "house", "E0") for p in picks]}
    e0l = {"x": [F.t(p, "x", "E0", 1.0) for p in picks], "house": [F.t(p, "house", "E0", 1.0) for p in picks]}
    f_e0 = [F.f(p, "E0") for p in picks]
    pe = fig(a_e0, a_e0)
    E0F = {"pick": pe, "x": fig(e0["x"], e0["x"]), "house": fig(e0["house"], e0["house"]), "flip": fig_flip(f_e0, f_e0)}
    for kind in KINDS:
        add("E0", kind, e0_only(E0F[kind]), MARK_HOUSE_F13 if kind == "house" else None)
    t4 = [{"id": "E0", "n_units": N, "G_pick": pe["G"], "G_x": E0F["x"]["G"],
           "pick_above": int(sum(a > b for a, b in zip(pe["_G"], E0F["x"]["_G"])))}]
    for vid in elig:
        sr = srows[vid]
        a_v = [F.a(p, vid, "q25") for p in picks]
        pv = fig(a_v, a_e0)
        pk = {"n_units": N, "hold": sr["hold"], "entered": sr["entered"], "entered_e0": sr["entered_e0"],
              "entered_change_pct": chg(sr["entered"], sr["entered_e0"]),
              "dir_hold": word("dir_hold", sr["hold"]["median"] - pe["hold"]["median"]),
              "dir_entries": word("dir_entries", sr["entered"] - sr["entered_e0"]), "G": pv["G"]}
        if pool == "core":
            pk.update(M=sr["M"], M_pct_month=sr["M_pct_month"], live_M_pct_month=sr["live"]["M_pct_month"])
            mp_pick = [sr["Mp"][p["id"]] for p in picks]
        else:
            pk.update(M=pv["M"], M_pct_month=pv["M_pct_month"])
            mp_pick = pv["_Mp"]
        pk["dir_growth"] = word("dir_growth", pk["M"])
        f3 = ("F3." + vid[-1]) if (f7 and vid in ("F11.a", "F11.b")) else None
        add(vid, "pick", pk, None, f3)
        for kind in ("x", "house"):
            arm = "E0" if (kind == "house" and vid in F13_IDS) else vid
            keep = [i for i, p in enumerate(picks) if not (vid in F1112 and strategy(p) in ctx.removed)]
            mark = MARK_HOUSE_F13 if arm != vid else (MARK_REMOVED if len(keep) < N else None)
            kf3 = f3 if ctx.f11_mark.get(kind) else None
            if not keep:
                add(vid, kind, {"n_units": 0}, mark, kf3)
                continue
            d = fig([F.t(picks[i], kind, arm) for i in keep], [e0[kind][i] for i in keep])
            d["n_same"] = int(sum(1 for m, i in zip(d["_Mp"], keep) if sgn(m) and sgn(m) == sgn(mp_pick[i])))
            d["same_side"] = same_side(d["M"], pk["M"])
            if pool == "core":
                lv = fig([F.t(picks[i], kind, arm, 1.0) for i in keep], [e0l[kind][i] for i in keep])
                d["live_M_pct_month"] = lv["M_pct_month"]
            add(vid, kind, d, mark, kf3)
            if kind == "x":
                t4.append({"id": vid, "n_units": len(keep), "G_pick": float(np.mean([pv["_G"][i] for i in keep])), "G_x": d["G"],
                           "pick_above": int(sum(pv["_G"][i] > g for i, g in zip(keep, d["_G"])))})
        if vid in NO_FLIP:
            add(vid, "flip", {"n_units": 0}, MARK_NO_FLIP)
        else:
            d = fig_flip([F.f(p, vid) for p in picks], f_e0)
            d["same_side"] = same_side(d["M"]["seed_median"], pk["M"])
            add(vid, "flip", d)
    seed0 = [seed_view(f, 0) for f in f_e0]
    live0 = [seed_view(F.f(p, "E0", FLIP_LIVE_TAG), 0) for p in picks]

    def t1(role, size, label, d):
        return {"kind": role, "size": size, "name_ko": label, **e0_only(d)}
    table1 = [t1("cand", 1.0, ROLE_KO["cand"], fig(a_e0l, a_e0l)), t1("quarter", 0.25, ROLE_KO["quarter"], pe),
              t1("exitonly", 1.0, ROLE_KO["exitonly"], fig(e0l["x"], e0l["x"])), t1("exitonly", 0.25, ROLE_KO["exitonly"], E0F["x"]),
              t1("base", 1.0, ROLE_KO["base"], fig(e0l["house"], e0l["house"])), t1("base", 0.25, ROLE_KO["base"], E0F["house"]),
              t1("flip", 1.0, ROLE_KO["flip"] + "(리그와 같은 동전, 실제 크기)", fig(live0, live0)),
              t1("flip", 0.25, ROLE_KO["flip"] + "(리그와 같은 동전, 1/4 크기)", fig(seed0, seed0)),
              t1("flip20", 0.25, "동전 20번(1/4 크기)", E0F["flip"])]
    thin_ids = {"x": [x_id(p) for p, s in zip(picks, e0["x"]) if thin(MT.count(s, "entered"))],
            "house": [base_id(p) for p, s in zip(picks, e0["house"]) if thin(MT.count(s, "entered"))],
            "flip": [flip_id(p, 0) for p, s in zip(picks, seed0) if thin(MT.count(s, "entered"))]}
    rem = sorted({strategy(p) for p in picks if strategy(p) in ctx.removed})
    return {"n_units": N, "eligible_ids": elig, "thin_ids": thin_ids,
            "removed": {"strategies": rem, "units": sum(strategy(p) in ctx.removed for p in picks)},
            "f11_note": {"pick": f7, "x": bool(f7 and ctx.f11_mark.get("x")), "house": bool(f7 and ctx.f11_mark.get("house"))},
            "rows": rows, "table1": table1, "table4": t4}


def strip(obj):
    """Drop the internal keys ('_' prefix) everywhere."""
    if isinstance(obj, dict):
        return {k: strip(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [strip(v) for v in obj]
    return obj


def ds_public(P: dict) -> dict:
    """The DeepSeek pool as a committed file may hold it: the whitelisted keys of each row only (TW.6)."""
    keep = lambda r: {k: v for k, v in r.items() if k in DS_TWIN_ALLOWED}   # noqa: E731
    return {"n_units": P["n_units"], "eligible_ids": P["eligible_ids"], "thin_ids": P["thin_ids"], "removed": P["removed"],
            "f11_note": P["f11_note"], "rows": [keep(r) for r in P["rows"]], "table1": [keep(r) for r in P["table1"]]}


# ------------------------------------------------------------------ D11 checks and the writers (TW.6)
def ds_row_ok(row: dict) -> bool:
    def nested(v):
        if isinstance(v, dict):
            return all(k in DS_NESTED_ALLOWED and nested(x) for k, x in v.items())
        return True
    return all(k in DS_TWIN_ALLOWED and nested(v) for k, v in row.items())


def ds_doc_problems(doc: dict) -> list:
    ds = (doc.get("pools") or {}).get("ds")
    if not ds:
        return []
    bad = [f"ds pool key {k}" for k in ds if k not in DS_POOL_KEYS]
    for part in ("rows", "table1"):
        bad += [f"ds {part} row {r.get('id', r.get('kind'))}" for r in ds.get(part, []) if not ds_row_ok(r)]
    return bad


def ds_section_problems(md: str) -> list:
    """Lines of a DeepSeek section (MT.ds_text_problems' notion) that hold a growth word or another money word of the twins."""
    bad, inside = [], False
    for ln in md.splitlines():
        if ln.startswith("## "):
            inside = "딥시크" in ln
        if inside and DS_SECTION_WORDS.search(ln):
            bad.append(ln.strip())
    return bad


def committed_problems(name: str, text: str) -> list:
    if name.endswith(".json"):
        doc = json.loads(text)
        return ds_doc_problems(doc) + ["free text: " + x[:60] for x in MT.audit_text("\n".join(MT.json_strings(doc)))]
    return (MT.ds_text_problems(text) + ds_section_problems(text) + ["free text: " + x[:60] for x in MT.audit_text(text)])


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(path + ".tmp", path)


def write_committed(tl: TLayout, name: str, text: str) -> str:
    """The only writer of research/exitflex/extra/out/: it refuses a DeepSeek money key or text (whitelist, MT.ds_text_problems,
    MT.audit_text, the twins' own DeepSeek words) before anything is written."""
    if not COMMITTED.match(name):
        refuse(f"{name} is not a committed twins file")
    bad = committed_problems(name, text)
    if bad:
        refuse(f"{name}: D11 check failed ({len(bad)} problems): " + "; ".join(bad[:3]))
    path = tl.out_file(name)
    _write(path, text)
    return path


def inside(path: str, folder: str) -> bool:
    p, f = os.path.abspath(path), os.path.abspath(folder)
    return os.path.commonpath([p, f]) == f


def write_private(ctx: Ctx, path: str, text: str) -> str:
    """DeepSeek money only under $WORK/<pin8>/ds_private/extra/ and never inside the repository (TW.6)."""
    if not inside(path, os.path.join(ctx.paths.root, "ds_private", "extra")) or inside(path, ctx.tl.root):
        refuse(f"a private file must lie under $WORK/<pin8>/ds_private/extra/ outside the repository: {path}")
    _write(path, text)
    return path


def dumps(doc) -> str:
    def dflt(o):
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.bool_):
            return bool(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        raise TypeError(type(o))
    return json.dumps(doc, indent=1, ensure_ascii=False, default=dflt) + "\n"


def sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rows_guard(doc: dict, elig: dict) -> list:
    """TW.5: no row of a 선택 불가 id, in any kind, table or pool."""
    bad = []
    for pool, P in doc.items():
        ok = {"E0"} | set(elig.get(pool, ()))
        bad += [f"{pool}: {r['id']}" for part in ("rows", "table4") for r in P.get(part, []) if r["id"] not in ok]
    return bad


# ------------------------------------------------------------------ the Korean report (TW.5) and the private section (TW.6)
def f_h(x) -> str:
    return "-" if isnan(x) else f"{x:.1f}시간"


def f_sh(x) -> str:
    return "-" if isnan(x) else f"{100 * x:.0f}%"


def f_n(x) -> str:
    if isnan(x):
        return "-"
    x = float(x)
    return f"{int(x):,}" if x.is_integer() else f"{x:,.1f}"


def f_chg(x) -> str:
    return "-" if isnan(x) else f"{x:+.0f}%"


def f_g(m) -> str:
    return "-" if isnan(m) else f"{pct(m):+.2f}%/월"


def f_mult(x) -> str:
    return "-" if isnan(x) else f"{x:.2f}x"


def f_dd(x) -> str:
    return "-" if isnan(x) else f"{100 * x:.0f}%"


def f_rng(d, fn) -> str:
    """median [lowest ~ highest] over the seeds."""
    return f"{fn(d['seed_median'])} [{fn(d['seed_min'])} ~ {fn(d['seed_max'])}]"


def seeds(v, fn) -> str:
    return f_rng(v, fn) if isinstance(v, dict) and "seed_median" in v else fn(v)


def m_line(t: str, private: bool) -> str:
    return ("[비공개] " + t) if private else t


def m_head(level: int, t: str, private: bool) -> str:
    return "#" * level + " " + ("[비공개] " if private else "") + t


def m_table(head: list, rows: list, private: bool) -> list:
    if private:
        head, rows = ["비공개"] + head, [["비공개"] + r for r in rows]
    return (["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(r) + " |" for r in rows] + [""])


def _idx(P: dict) -> dict:
    return {(r["id"], r["kind"]): r for r in P["rows"]}


def _label(r: dict) -> str:
    return r["name_ko"] if r["id"] == "E0" else f"{r['id']} ({r['name_ko']})"


def _has(r: dict) -> bool:
    return r.get("n_units", 0) > 0 and "entered" in r


def _suffix(r: dict, P: dict, extra=(), f11: bool = True) -> str:
    """The cell's notes in one parenthesis (the given counts, the mark, a TW-C2 removal with its unit count), then the F11 = F3 note."""
    notes = list(extra)
    if r.get("mark") and not (r["id"] == "E0" and r["kind"] == "house"):
        notes.append(r["mark"] + (f" {P['n_units'] - r['n_units']}칸" if r["mark"] == MARK_REMOVED else ""))
    out = f" ({', '.join(notes)})" if notes else ""
    return out + (f" {F11_NOTE}" if f11 and r.get("same_as_f3") else "")


def _part(r: dict, key: str, P: dict, extra=()) -> str:
    """One kind of a card line: '<kind> <word> (notes)', or the mark alone when the kind has no figure."""
    if not _has(r):
        return r.get("mark") if r.get("mark") == MARK_NO_FLIP else f"{KIND_KO[r['kind']]} {r.get('mark') or '-'}"
    return f"{KIND_KO[r['kind']]} {r[key]}{_suffix(r, P, extra, False)}"


def _card_label(I: dict, vid: str) -> str:
    r = I[(vid, "pick")]
    return _label(r) + (f" {F11_NOTE}" if r.get("same_as_f3") else "")


def card_a(P: dict) -> list:
    I = _idx(P)
    L = [m_head(3, "a. 한눈에 보기 (1) 보유 시간과 진입 (참고용, 고르는 표 아님)", False), ""]
    if not P["eligible_ids"]:
        L.append("선택 가능한 청산이 없어 지금 청산(E0) 줄만 있습니다.")
    for vid in P["eligible_ids"]:
        hold = " · ".join(_part(I[(vid, k)], "dir_hold", P) for k in KINDS)
        ent = " · ".join(_part(I[(vid, k)], "dir_entries", P) for k in KINDS)
        L.append(f"- {_card_label(I, vid)}: 보유 시간 {hold} / 진입 {ent}")
    return L + ["", CARD_A_LINE, ""]


def _cell2(r: dict, P: dict) -> str:
    if not _has(r):
        return r.get("mark") or "-"
    h = r["hold"]["seed_median"] if "seed_median" in r["hold"] else r["hold"]
    ent = r["entered"]["seed_median"] if isinstance(r["entered"], dict) else r["entered"]
    c = "-" if r["id"] == "E0" else f_chg(r["entered_change_pct"])
    return f"{f_h(h['median'])} / {f_sh(h['share_gt4'])} / {f_n(ent)} / {c}" + _suffix(r, P)


def table2(P: dict) -> list:
    I = _idx(P)
    L = [m_head(3, "b. 표 2, 보유 시간과 진입 (지금 청산 → 각 청산)", False), "",
         "칸 안의 숫자: 보유 시간 중앙값 / 4시간 넘게 들고 있던 거래 비율 / 진입한 거래 수 / 같은 계좌의 지금 청산 대비 진입 변화. "
         "동전 칸은 20번 던진 결과의 가운데 값입니다.", ""]
    head = ["청산", "픽", "청산만 바꾼 기본값", "규칙봇 청산 위에 (지금 청산 줄 = 기본값 계좌)", "동전 20번"]
    rows = [[_label(I[(vid, "pick")])] + [_cell2(I[(vid, k)], P) for k in KINDS] for vid in ["E0"] + P["eligible_ids"]]
    return L + m_table(head, rows, False)


def table1(P: dict) -> list:
    L = [m_head(3, "c. 표 1, 리그 다섯 계좌 2021~2023 (보유 시간과 진입)", False), ""]
    head = ["계좌", "크기", "보유 시간 중앙값", "4시간 넘게", "8시간 넘게", "18시간 넘게", "진입", "들고 있어서 놓친 신호", "거절된 신호", "이긴 비율"]
    rows = []
    for r in P["table1"]:
        h = r["hold"]
        hv = (lambda k, fn: f_rng({s: h[s][k] for s in h}, fn)) if "seed_median" in h else (lambda k, fn: fn(h[k]))
        rows.append([r["name_ko"], "1" if r["size"] == 1.0 else "1/4", hv("median", f_h), hv("share_gt4", f_sh), hv("share_gt8", f_sh),
                     hv("share_gt18", f_sh), seeds(r["entered"], f_n), f_n(r["skipped"]), f_n(r["rejected"]), f_sh(r["win_share"])])
    return L + m_table(head, rows, False) + [t for x in TABLE1_LINES + (FLIP_LIVE_LINE, FLIP20_LINE) for t in (x, "")]


def _gcell(r: dict, P: dict, with_side: bool) -> str:
    if not _has(r):
        return r.get("mark") or "-"
    v = r["G"] if r["id"] == "E0" else r["M"]
    s = f_rng(v, f_g) if isinstance(v, dict) else f_g(v)
    side = (r["same_side"],) if (with_side and r["id"] != "E0" and r["kind"] != "pick") else ()
    return s + _suffix(r, P, side)


def card_d(P: dict, private: bool) -> list:
    I = _idx(P)
    L = [m_head(3, "d. 한눈에 보기 (2) 성장" + ("" if private else " (코어만)"), private), ""]
    if not P["eligible_ids"]:
        L.append(m_line("선택 가능한 청산이 없어 지금 청산(E0) 줄만 있습니다.", private))
    for vid in P["eligible_ids"]:
        parts = []
        for k in KINDS:
            r = I[(vid, k)]
            extra = ()
            if _has(r) and k in ("x", "house"):
                extra = (f"{r['n_units']}칸 중 나아진 칸 {r['n_pos']}",)
            elif _has(r) and k == "flip":
                extra = (f"{N_SEEDS}번 중 나아진 번 {r['n_pos']}",)
            parts.append(_part(r, "dir_growth", P, extra))
        L.append(m_line(f"- {_card_label(I, vid)}: " + " · ".join(parts), private))
    return L + [""] + [t for x in CARD_D_LINES for t in (m_line(x, private), "")]


def table3(P: dict, private: bool) -> list:
    I = _idx(P)
    L = [m_head(3, "e. 표 3, 한 달 계좌 성장 차이 (1/4 크기" + ("" if private else ", 코어만") + ")", private), "",
         m_line("표 3a. 지금 청산 줄은 각 계좌의 한 달 성장(%/월)이고, 다른 줄은 같은 계좌의 지금 청산과 비교한 한 달 성장 차이(%/월)와 "
                "픽과 같은 쪽인지입니다. 동전 칸은 가운데 값 [가장 낮은 ~ 가장 높은]입니다.", private), ""]
    head = ["청산", "픽", "청산만 바꾼 기본값", "규칙봇 청산 위에", "동전 20번"]
    rows = [[_label(I[(vid, "pick")])] + [_gcell(I[(vid, k)], P, True) for k in KINDS] for vid in ["E0"] + P["eligible_ids"]]
    L += m_table(head, rows, private)
    L += [m_line("괄호 안: 같은 쪽 = 픽과 같은 방향, 반대 쪽 = 픽과 반대 방향, 0 = 어느 한쪽의 차이가 0이라 방향이 없음.", private), ""]
    L += [m_line("표 3b. 칸 수와 동전 수(나아짐 = 같은 계좌의 지금 청산보다 한 달 성장이 큼).", private), ""]
    head = ["청산", "나아진 칸: 청산만 바꾼 기본값", "나아진 칸: 규칙봇 청산 위에", "픽과 같은 쪽 칸: 청산만 바꾼 기본값",
            "픽과 같은 쪽 칸: 규칙봇 청산 위에", "나아진 동전"]

    def frac(r, key, n=None):
        return f"{r[key]}/{r['n_units'] if n is None else n}" if _has(r) else (r.get("mark") or "-")
    rows = [[_label(I[(vid, "pick")]), frac(I[(vid, "x")], "n_pos"), frac(I[(vid, "house")], "n_pos"), frac(I[(vid, "x")], "n_same"),
             frac(I[(vid, "house")], "n_same"), frac(I[(vid, "flip")], "n_pos", N_SEEDS)] for vid in P["eligible_ids"]]
    return L + m_table(head, rows, private)


def table1b(P: dict, private: bool) -> list:
    L = [m_head(3, "f. 표 1b, 리그 다섯 계좌 2021~2023 (돈" + ("" if private else ", 코어만") + ")", private), ""]
    head = ["계좌", "크기", "한 달 성장", "최종 배수(가운데 값)", "최대 낙폭(가운데 값)", "파산"]
    rows = [[r["name_ko"], "1" if r["size"] == 1.0 else "1/4", seeds(r["G"], f_g), seeds(r["final_multiple_median"], f_mult),
             seeds(r["max_dd_median"], f_dd), seeds(r["busts"], f_n)] for r in P["table1"]]
    return L + m_table(head, rows, private)


def table4(P: dict, private: bool) -> list:
    I = _idx(P)
    L = [m_head(3, "g. 표 4, 커스텀값 대 기본수치 (같은 청산, 1/4 크기" + ("" if private else ", 코어만") + ")", private), ""]
    head = ["청산", "픽 한 달 성장", "청산만 바꾼 기본값 한 달 성장", "픽이 기본수치보다 나은 칸"]
    rows = []
    for r in P["table4"]:
        rows.append([_label(I[(r["id"], "pick")]), f_g(r["G_pick"]), f_g(r["G_x"]), f"{r['pick_above']}/{r['n_units']}"])
    for vid in P["eligible_ids"]:
        if not any(r["id"] == vid for r in P["table4"]):
            rows.append([_label(I[(vid, "pick")]), "-", MARK_REMOVED, "-"])
    return L + m_table(head, rows, private) + [t for x in TABLE4_LINES for t in (m_line(x, private), "")]


def thin_md(P: dict) -> list:
    t = P["thin_ids"]
    show = lambda ids: ", ".join(ids) if ids else "없음"   # noqa: E731
    return [m_head(3, "h. 거래 적음", False), "", THIN_HEAD, "", f"- {ROLE_KO['exitonly']}: {show(t['x'])}",
            f"- {ROLE_KO['base']}(규칙봇 청산 위에도 같은 계좌): {show(t['house'])}", f"- {ROLE_KO['flip']}: {show(t['flip'])}", ""]


def pool_md(P: dict, pool: str) -> list:
    L = ["## 코어 풀" if pool == "core" else "## 딥시크 풀", ""]
    L += card_a(P) + table2(P) + table1(P)
    if pool == "core":
        L += card_d(P, False) + table3(P, False) + table1b(P, False) + table4(P, False)
    L += thin_md(P)
    if pool == "ds":
        L += [m_head(3, "i. 딥시크", False), "", DS_LINE, ""]
    return L


def render_md(doc: dict) -> str:
    """TWINS_KO.md from twins.json alone (TW-A8: every number of the file equals twins.json)."""
    meta = doc["meta"]
    L = []
    if meta.get("fix"):
        L += [f"{meta['fix']['utc']} 고친 판: {meta['fix']['note']}", FIX_RULE_LINE, ""]
    L += ["# 쌍둥이 계좌 보고서 (2021~2023, 참고용)", ""]
    fixed = list(FIXED_LINES)
    if meta.get("o8_breach"):                          # TW.7 step 2: the O8-breach line replaces the fourth fixed line
        fixed = [O8_BREACH_LINE] + fixed[:3] + fixed[4:]
    L += [t for x in fixed for t in (x, "")]
    L += ["## 용어", ""] + [t for x in GLOSSARY for t in (x, "")]
    L += pool_md(doc["pools"]["core"], "core") + pool_md(doc["pools"]["ds"], "ds")
    return "\n".join(L + [LAST_LINE]) + "\n"


def render_private(P: dict) -> str:
    """The twins' private section for the DeepSeek pool (TW.6): card d, Tables 3a, 3b, 1b and 4 with n/15 and n/20, the lines of
    item d; every heading, prose line and table row carries the private marker; no glossary, no fixed line, no p value."""
    L = [m_head(2, "쌍둥이 계좌, 딥시크 풀의 돈 숫자 (대화창에서만 보여 드림, 저장소에 올리지 않음)", True), "",
         m_line("지금 청산(E0), 기본값 계좌와 딥시크 풀의 선택 가능 줄만 있습니다. 순위는 매기지 않았습니다.", True), ""]
    return "\n".join(L + card_d(P, True) + table3(P, True) + table1b(P, True) + table4(P, True)) + "\n"


def build_report(ctx: Ctx, sel: dict, meta: dict) -> tuple:
    """(twins.json document, TWINS_KO.md, twins_ds.json text, private section text). Computes no account."""
    order = {v.id: i for i, v in enumerate(ctx.variants)}
    allowed = {pool: {"E0"} | set(select_rows(sel, pool, order)[0]) for pool in ("core", "ds")}
    F = Files(ctx, allowed)
    core, ds = strip(pool_doc(ctx, F, sel, "core")), strip(pool_doc(ctx, F, sel, "ds"))
    bad = rows_guard({"core": core, "ds": ds}, {k: v - {"E0"} for k, v in allowed.items()})
    if bad:
        refuse("a row of a 선택 불가 id: " + ", ".join(bad[:4]))
    private = render_private(ds)
    ds_text = dumps({"section": "TW", "pool": "ds", "doc": ds, "private_section_sha256": sha_text(private)})
    doc = {"section": "TW", "stage": "twins_r2" if ctx.rerun else "twins",
           "meta": {**meta, "accounts": account_counts(ctx), "files": len(expected(ctx)), "removed": sorted(ctx.removed),
                    "f11_mark": ctx.f11_mark, "twins_ds_sha256": sha_text(ds_text), "private_section_sha256": sha_text(private)},
           "pools": {"core": core, "ds": ds_public(ds)}}
    return doc, render_md(doc), ds_text, private


# ------------------------------------------------------------------ the gate and the refusals (TW.3)
def git_out(root: str, *args) -> str:
    try:
        return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True, timeout=60).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def sha(path: str) -> str:
    return RX.sha256_file(path)


def gate(tl: TLayout, verify_data: bool = True) -> tuple:
    """A's gate (its '[pin ok]' line captured), every file listed in PREREG_EXITFLEX_EXTRA.sha256 with its hash, every .py file under
    extra/ listed. Prints '[twins pin ok] ...' and returns (pin, pin hash)."""
    with contextlib.redirect_stdout(io.StringIO()):
        pin, ph = RX.gate_pin(tl.a, verify_data)
    if not os.path.exists(tl.extra_sha):
        refuse(f"pin file missing: {tl.extra_sha}")
    pins = RX.read_sha_file(tl.xlay())
    bad = [os.path.relpath(p, tl.root) for p, h in pins.items() if not os.path.exists(p) or sha(p) != h]
    if bad:
        refuse("hash mismatch (PREREG_EXITFLEX_EXTRA.sha256): " + ", ".join(bad[:6]))
    loose = []
    for dp, dns, fns in os.walk(tl.extra_dir):
        dns[:] = [d for d in dns if d != "__pycache__"]
        loose += [os.path.relpath(os.path.join(dp, f), tl.root) for f in sorted(fns)
                  if f.endswith(".py") and os.path.normpath(os.path.join(dp, f)) not in pins]
    if loose:
        refuse("not pinned (code of extra/): " + ", ".join(loose[:6]))
    say(f"[twins pin ok] commit {git_out(tl.root, 'rev-parse', 'HEAD')[:10]} pin {DX.pin8(ph)} extra {sha(tl.extra_sha)[:8]}")
    return pin, ph


def select_names(rerun: bool) -> tuple:
    return ("select_r2.json", "SELECT_KO_r2.md") if rerun else ("select.json", "SELECT_KO.md")


def require_select(tl: TLayout, rerun: bool) -> dict:
    """A's select.json and SELECT_KO.md (the _r2 pair with --rerun) listed in PREREG_EXITFLEX.sha256 with their present hashes."""
    for n in select_names(rerun):
        RX.require_pinned_file(tl.a, tl.a.out_file(n), n)
    return json.load(open(tl.a.out_file(select_names(rerun)[0]), encoding="utf-8"))


def is_check_file(path: str) -> bool:
    """twins_check.json (or _r2) itself: a rerun of check after TW.10 finds its earlier line in the pin file, so neither check nor
    require_check records or compares the file's own hash (DEVIATIONS.md, [extra/twins] 2026-10-12, second entry)."""
    return os.path.basename(path) in ("twins_check.json", "twins_check_r2.json")


def require_check(tl: TLayout) -> dict:
    """out/twins_check.json listed in PREREG_EXITFLEX_EXTRA.sha256 with its present hash, saying pass, and recording for every file
    listed there at check time the hash that file has now."""
    path = tl.out_file("twins_check.json")
    RX.require_pinned_file(tl.xlay(), path, "twins_check.json")
    doc = json.load(open(path, encoding="utf-8"))
    if not doc.get("pass"):
        refuse("twins_check.json does not say pass")
    for rel, h in (doc.get("hashes") or {}).items():
        p = os.path.join(tl.root, rel)
        if is_check_file(p):
            continue                                       # its own earlier line, listed before a rerun of check (TW.10)
        if not os.path.exists(p) or sha(p) != h:
            refuse(f"{rel} changed since twins check")
    return doc


def free_bytes(path: str) -> int:
    return shutil.disk_usage(path).free


def require_disk(need_gb: float, path: str) -> None:
    """TW.8: run refuses when less than need + 0.5 GB is free on the filesystem of $WORK (at its start and at every resume)."""
    if free_bytes(path) < need_gb * 1e9 + NEED_MARGIN:
        refuse(f"not enough free disk under $WORK: need {need_gb:.1f} GB + 0.5 GB (TW.8)")


def listing(tl: TLayout, paths: Paths) -> dict:
    """TW-A7: (size, sha256) of every file of research/exitflex/ outside extra/ and of $WORK/<pin8>/ outside extra/,
    ds_private/extra/ and ds_private/owner_report_extra.md (__pycache__ folders left out)."""
    skip_dirs = {os.path.abspath(d) for d in (tl.extra_dir, os.path.join(paths.root, "extra"), os.path.join(paths.root, "ds_private", "extra"))}
    skip_files = {os.path.abspath(os.path.join(paths.root, "ds_private", n)) for n in ("owner_report_extra.md", "owner_report_extra_r2.md")}
    out = {}
    for top in (tl.a.base, paths.root):
        for dp, dns, fns in os.walk(top):
            dns[:] = sorted(d for d in dns if d != "__pycache__" and os.path.abspath(os.path.join(dp, d)) not in skip_dirs)
            for f in sorted(fns):
                p = os.path.abspath(os.path.join(dp, f))
                if p not in skip_files and os.path.isfile(p):
                    out[p] = (os.path.getsize(p), sha(p))
    return out


def record_isolation(paths: Paths, cmd: str, ok: bool) -> None:
    doc = json.load(open(paths.isolation)) if os.path.exists(paths.isolation) else {}
    doc[cmd] = bool(ok)
    _write(paths.isolation, dumps(doc))


@contextlib.contextmanager
def isolated(tl: TLayout, paths: Paths, cmd: str, res: dict | None = None):
    """TW-A7 around one command: the two listings at its start and at its end must be equal."""
    before = listing(tl, paths)
    yield
    ok = listing(tl, paths) == before
    record_isolation(paths, cmd, ok)
    if res is not None:
        res["ok"] = ok
    if not ok:
        say(f"[twins {cmd}] TW-A7 FAIL")
        raise SystemExit(1)


# ------------------------------------------------------------------ the real configuration
def real_ctx(tl: TLayout, pin: dict, ph: str, procs: int = 3, rerun: bool = False, removed=(), f11_mark=None,
             results_sfx: str | None = None) -> Ctx:
    """The cut (opened, never made), the market, the F11 provider (A's glue) and the compiled kernel. The twins' cache folder is
    deleted first (check, run, audit)."""
    try:
        cut = DX.open_cut(pin["work"], ph, DX.SELECT_CUT_MS)
    except DX.PinError as exc:
        refuse(f"the select cut is missing or does not verify; the twins never make it ({exc})")
    paths = Paths(pin["work"], ph, rerun, results_sfx)
    shutil.rmtree(paths.cache, ignore_errors=True)
    os.makedirs(paths.cache, exist_ok=True)
    rprov = DX.RealProvider(cut, paths.cache)
    market = DX.Market(cut)
    assert_select_only(market)
    native, native_ds = RX.try_load_native()
    prov11 = RX.f11_provider_from_modules(rprov, native, native_ds)
    if prov11 is None:
        refuse("native.py / native_ds.py are not available (F11 and F12)")
    KX.register_f11(prov11)
    KX.warm_up(market)
    vs = KX.variants()
    if len(vs) != 88:
        refuse(f"expected A's 88 variants, got {len(vs)}")

    def make(unit, with_f11):
        return DX.PickData(market, unit, rprov, f11=prov11 if with_f11 else None)

    def combo(kind, name):
        return DX._tup(DX.fg().default_combo(kind, name))

    def native_check(unit):                            # TW-C2: A's T6 on the default combo (the modules raise on a mismatch)
        for sym in market.symbols:
            df, _close = rprov.frame(sym, unit["tf"])
            lo, sh = rprov.signals(unit, sym)
            if unit["kind"] == "core":
                native.native_arrays(unit["name"], df, unit["tf"], unit["combo"], expect=(lo, sh))
            else:
                cx = None if sym == "BTCUSDT" else {"BTCUSD": rprov.frame("BTCUSDT", unit["tf"])[0]}
                native_ds.native(df, unit["tf"], unit["name"], unit["combo"], cx, sym[:-1], expect=(lo, sh))
        return True
    return Ctx(tl, pin, ph, market, DX.picks(), vs, make, combo, procs, rerun, removed, f11_mark, results_sfx, native_check)


def report_ctx(tl: TLayout, pin: dict, ph: str, chk: dict, rerun: bool) -> Ctx:
    """A read-only context for report: no market, no cache, nothing can be computed."""
    prov11 = RX.f11_provider_from_modules(None, *RX.try_load_native())
    if prov11 is None:
        refuse("native.py / native_ds.py are not available (F11 and F12)")
    KX.register_f11(prov11)

    def no_compute(*_a):
        raise RuntimeError("report computes no account")
    sfx = None
    if rerun:
        sfx = "_r2" if os.path.isdir(Paths(pin["work"], ph, True).results["core"]) else ""
    return Ctx(tl, pin, ph, None, DX.picks(), KX.variants(), no_compute, no_compute, 1, rerun, chk.get("removed", ()),
               chk.get("f11_mark"), sfx)


# ------------------------------------------------------------------ check (TW-C1 .. TW-C5 and the disk need)
def same_result(a, b) -> bool:
    return all(np.array_equal(getattr(a, k), getattr(b, k)) for k in ("status", "pnl", "entry_ts", "exit_ts", "reason", "lev", "xpx")) \
        and a.wallet == b.wallet


def kernel_account(market, off: dict, exit_index: int, scale: float) -> tuple:
    m = market
    return K.account(m.S(scale), m.brs, m.cat["ts"], m.cat["o"], m.cat["h"], m.cat["l"], m.cat["mo"], m.cat["mh"], m.cat["ml"],
                     m.cat["fund"], m.starts, m.ends, off["coin"], off["close"], off["side"], off["atr"], off["best"], m.qty_steps,
                     m.min_notionals, *K.exit_args(exit_index), np.full(len(off["coin"]), np.nan))


def e0_parity(ctx: Ctx, pdata, exit_index: int, scale: float, force_end: bool = False) -> bool:
    """E0 through kernel_x equals kernel.account (A's T1, or with the forced end A's A6: equal up to the position END closes)."""
    off = pdata.offered(PERIOD, ctx.market)
    st, pnl, ext, rs, lv, w = kernel_account(ctx.market, off, exit_index, scale)
    r = sim(ctx, pdata, KX.E0, scale, force_end=force_end)
    if not force_end:
        return bool(np.array_equal(st, r.status) and np.array_equal(pnl, r.pnl) and np.array_equal(ext, r.exit_ts)
                    and np.array_equal(rs, r.reason) and np.array_equal(lv, r.lev) and w == r.wallet)
    open_ = np.flatnonzero((st == 1) & (rs == K.R_OPEN))
    cut = int(open_[0]) if len(open_) else len(st)
    ok = np.array_equal(st, r.status) and np.array_equal(pnl[:cut], r.pnl[:cut]) and np.array_equal(ext[:cut], r.exit_ts[:cut])
    return bool(ok and (not len(open_) or r.reason[cut] == KX.R_END))


def run_checks(ctx: Ctx, c4: bool = True) -> dict:
    """TW-C1 .. TW-C5 and the disk need (TW.8). Counts only."""
    league_flip = ctx.league_flip or importlib.import_module("candleague.league").flip_side
    out = {}
    offered_n, c3a, c3b, n3a, n3b = {}, True, True, 0, 0
    for p in ctx.picks:                                # TW-C3 on the picks' own chart data
        pdata = ctx.make_pickdata(p, True)
        off = pdata.offered(PERIOD, ctx.market)
        offered_n[p["id"]] = len(off["coin"])
        raw = flip_offer(pdata, off, off["side"])
        for v in arms(ctx, "flip", p):
            c3a &= same_result(sim(ctx, pdata, v, 0.25), sim(ctx, pdata, v, 0.25, raw))
            n3a += 1
        acct = flip_id(p, 0)
        for c in off["close"]:
            c3b &= flip_side(acct, int(c)) == league_flip(acct, int(c))
            n3b += 1
        del pdata
    out["TW-C3"] = {"pass": bool(c3a and c3b), "accounts": n3a, "signals": n3b}
    removed, n2 = set(), 0
    for p in ctx.picks:                                # TW-C2 on the default combos
        if ctx.native_check is None:
            continue
        n2 += 1
        try:
            ok = bool(ctx.native_check(twin_pick(p, ctx.default_combo(p["kind"], p["name"]))))
        except Exception:  # noqa: BLE001  (a native guard: the strategy's own exit fails on the default combo)
            ok = False
        if not ok:
            removed.add(strategy(p))
    c1, n1, c5, n5 = True, 0, {"x": True, "house": True}, 0
    for p in ctx.picks:                                # TW-C1 and TW-C5
        ctx.removed = set(removed)
        try:
            xd, hd = unit_data(ctx, p)
        except Exception:  # noqa: BLE001  (a native guard while the unit is built: TW.2 removal)
            removed.add(strategy(p))
            ctx.removed = set(removed)
            xd, hd = unit_data(ctx, p)
        for pdata, ex in ((xd, p["exit_index"]), (hd, 0)):
            for s in SIZES:
                c1 &= e0_parity(ctx, pdata, ex, s)
                n1 += 1
        if p["name"] in F3_SAME_NAMES and strategy(p) not in removed:
            for kind, pdata in (("x", xd), ("house", hd)):
                for m in ("a", "b"):
                    c5[kind] &= same_result(sim(ctx, pdata, KX.variant_by_id(f"F11.{m}"), 0.25), sim(ctx, pdata, KX.variant_by_id(f"F3.{m}"), 0.25))
                    n5 += 1
        del xd, hd
    ctx.removed = set(removed)
    out["TW-C1"] = {"pass": bool(c1), "accounts": n1}
    out["TW-C2"] = {"pass": not removed, "units": n2, "removed": sorted(removed)}
    out["TW-C5"] = {"x": bool(c5["x"] and n5 > 0), "house": bool(c5["house"] and n5 > 0), "accounts": n5}
    if c4:
        t = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", os.path.join(HERE, "test_twins.py"), "-k",
                            "tw_t1_ or tw_t3_"], capture_output=True, text=True, cwd=ctx.tl.root,
                           env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        out["TW-C4"] = {"pass": t.returncode == 0}
    else:
        out["TW-C4"] = {"pass": True, "skipped": True}
    out["need_gb"] = disk_need(ctx, offered_n)
    out["removed"] = sorted(removed)
    out["f11_mark"] = {k: out["TW-C5"][k] for k in ("x", "house")}
    out["pass"] = bool(out["TW-C1"]["pass"] and out["TW-C3"]["pass"] and out["TW-C4"]["pass"])
    return out


def disk_need(ctx: Ctx, offered_n: dict) -> float:
    """TW.8: the compressed size of real result files of the two core picks with the most and the fewest offered signals (x twin E0 and
    F3.a at both sizes, flip E0 and F3.a), written to check_tmp/ and deleted; need = max(0.8 GB, 1.5 x (13,376 x single + 3,230 x flip)
    + 0.15 GB), rounded up to 0.1 GB."""
    core = sorted((p for p in ctx.picks if p["pool"] == "core"), key=lambda p: (offered_n[p["id"]], p["id"]))
    if not core:
        return NEED_FLOOR / 1e9
    tmp = ctx.paths.check_tmp
    shutil.rmtree(tmp, ignore_errors=True)
    single, flip = [], []
    vs = (KX.E0, KX.variant_by_id("F3.a"))
    try:
        for p in {core[0]["id"]: core[0], core[-1]["id"]: core[-1]}.values():
            xd, _hd = unit_data(ctx, p)
            for v in vs:
                for s in SIZES:
                    path = os.path.join(tmp, f"{x_id(p)}__{v.id}__{TAG[s]}.npz")
                    save(path, light(sim(ctx, xd, v, s), ctx.edges))
                    single.append(os.path.getsize(path))
            pdata = ctx.make_pickdata(p, True)
            off = pdata.offered(PERIOD, ctx.market)
            offs = [flipped(pdata, off, flip_id(p, s)) for s in range(N_SEEDS)]
            for v in vs:
                path = os.path.join(tmp, f"{flip_id(p, 0)}__{v.id}__{FLIP_TAG}.npz")
                save(path, stack([light(sim(ctx, pdata, v, 0.25, o), ctx.edges) for o in offs]))
                flip.append(os.path.getsize(path))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    need = max(NEED_FLOOR, 1.5 * (N_SINGLE_FILES * float(np.mean(single)) + N_FLIP_FILES * float(np.mean(flip))) + NEED_CACHE)
    return math.ceil(need / 1e8 - 1e-9) / 10.0


# ------------------------------------------------------------------ audits (TW-A1 .. TW-A9)
def same_arrays(a: dict, b: dict) -> bool:
    """Two loaded result files hold the same keys and arrays; NaN equals NaN in float arrays (the hold statistics of an account with
    no trade are NaN; DEVIATIONS.md, [extra/twins] 2026-10-12)."""
    return a.keys() == b.keys() and all(np.array_equal(a[k], b[k], equal_nan=np.asarray(a[k]).dtype.kind == "f") for k in a)


def run_audits(ctx: Ctx, sel: dict, a3=None) -> dict:
    """TW-A1 .. TW-A6 and TW-A8 on a finished run and report (A7 is the command's own listing; A9 is ``audit_private``)."""
    tl, sfx = ctx.tl, ("_r2" if ctx.rerun else "")
    res = {}
    files = expected(ctx)
    a1 = a2 = True
    for f in files:
        z = load(f)
        c = np.atleast_2d(z["counts"])
        a1 &= bool(np.all(c[:, 0] == c[:, 1] + c[:, 3] + c[:, 4] + c[:, 5] + c[:, 6]))
        w, s = np.atleast_1d(z["w_end"]), np.atleast_1d(z["pnl_sum"])
        a2 &= bool(np.all(np.abs(w - (float(z["w0"]) + s)) <= 1e-9 * np.maximum(1.0, np.abs(w))))
    res["TW-A1"], res["TW-A2"] = a1, a2
    try:
        (a3 or assert_select_only)(ctx.market)
        res["TW-A3"] = True
    except (AssertionError, DX.PinError):
        res["TW-A3"] = False
    a4 = True
    for p in ctx.picks:
        xd, hd = unit_data(ctx, p)
        for s in SIZES:
            a4 &= e0_parity(ctx, xd, p["exit_index"], s, True) and e0_parity(ctx, hd, 0, s, True)
        pdata = ctx.make_pickdata(p, True)
        for s in SIZES:
            mine = light(sim(ctx, pdata, KX.E0, s), ctx.edges)
            theirs = load(a_file(ctx, p, "E0", TAG[s]))
            keep = [i for i in range(len(MT.COUNT_NAMES)) if MT.COUNT_NAMES[i] != "entries_at_rule_minute"]
            a4 &= bool(mine["w_end"] == float(theirs["w_end"]) and np.array_equal(mine["counts"][keep], theirs["counts"][keep]))
        del xd, hd, pdata
    res["TW-A4"] = bool(a4)
    a5 = True
    for p in ctx.picks:
        hdir = os.path.dirname(twin_file(ctx, p, "house", "E0", "q25"))
        a5 &= not any(f.startswith(("F13.a__", "F13.b__")) for f in os.listdir(hdir))
        fdir = os.path.dirname(twin_file(ctx, p, "flip", "E0", FLIP_TAG))
        a5 &= not any(f.startswith(tuple(v + "__" for v in NO_FLIP)) for f in os.listdir(fdir))
        if strategy(p) in ctx.removed:
            for kind in ("x", "house"):
                d = os.path.dirname(twin_file(ctx, p, kind, "E0", "q25"))
                a5 &= not any(f.startswith(tuple(v + "__" for v in F1112)) for f in os.listdir(d))
        if K.exit_args(p["exit_index"])[0] == 2.0 and any(v.id == "F13.b" for v in ctx.variants):
            for s in SIZES:
                a, b = load(twin_file(ctx, p, "x", "F13.b", TAG[s])), load(twin_file(ctx, p, "house", "E0", TAG[s]))
                a5 &= same_arrays(a, b)
    doc_path = tl.out_file(f"twins{sfx}.json")
    doc = json.load(open(doc_path, encoding="utf-8")) if os.path.exists(doc_path) else None
    if doc:
        for pool in ("core", "ds"):
            P = doc["pools"][pool]
            I = _idx(P)
            for vid in P["eligible_ids"]:
                if vid in F13_IDS:
                    r, e = I[(vid, "house")], I[("E0", "house")]
                    a5 &= r["mark"] == MARK_HOUSE_F13 and all(r.get(k) == e.get(k) for k in ("entered", "hold", "skipped", "rejected"))
    res["TW-A5"] = bool(a5)
    res["TW-A6"] = bool(doc) and not a6_problems(ctx, doc)
    res["TW-A8"] = bool(doc) and not a8_problems(ctx, sel, doc)
    return res


def committed_outputs(tl: TLayout) -> list:
    return [os.path.join(tl.out, f) for f in sorted(os.listdir(tl.out)) if COMMITTED.match(f)] if os.path.isdir(tl.out) else []


def tracked(root: str) -> list:
    return git_out(root, "ls-files").splitlines()


def private_lines(text: str) -> list:
    return [ln.strip() for ln in text.splitlines() if len(ln.strip()) >= 20 and re.search(r"[0-9A-Za-z가-힣]", ln)]


def a6_problems(ctx: Ctx, doc: dict) -> list:
    """TW-A6 on the committed outputs: whitelist, DeepSeek sections, free text (what audit-file makes on these names), the private
    files outside the repository and untracked, their hashes, no private line in a committed output, the last line."""
    tl, P = ctx.tl, ctx.paths
    bad = []
    for path in committed_outputs(tl):
        bad += [f"{os.path.basename(path)}: {x}" for x in committed_problems(os.path.basename(path), open(path, encoding="utf-8").read())]
    for path in (P.ds_json, P.private_md):
        if not os.path.exists(path) or inside(path, tl.root):
            bad.append(f"private file missing or inside the repository: {path}")
            continue
        text = open(path, encoding="utf-8").read()
        if P_VALUE.search(text):
            bad.append(f"{os.path.basename(path)} holds a p value")
    if any(os.path.basename(x).startswith(("twins_ds", "owner_report_")) for x in tracked(tl.root)):
        bad.append("git tracks a private file")
    if os.path.exists(P.ds_json) and sha(P.ds_json) != doc["meta"].get("twins_ds_sha256"):
        bad.append("twins_ds.json sha256 differs from twins.json")
    if os.path.exists(P.private_md):
        if sha(P.private_md) != doc["meta"].get("private_section_sha256"):
            bad.append("private section sha256 differs from twins.json")
        committed = {ln.strip() for path in committed_outputs(tl) for ln in open(path, encoding="utf-8").read().splitlines()}
        if any(ln in committed for ln in private_lines(open(P.private_md, encoding="utf-8").read())):
            bad.append("a line of the private section is in a committed output")
    for path in committed_outputs(tl):
        if path.endswith(".md") and open(path, encoding="utf-8").read().rstrip("\n").splitlines()[-1] != LAST_LINE:
            bad.append(f"{os.path.basename(path)} does not end with the last line")
    return bad


def a8_problems(ctx: Ctx, sel: dict, doc: dict) -> list:
    """TW-A8: TWINS_KO.md is twins.json rendered; the pick column equals select.json; the core picks' M_p from A's files equal select.json's
    Mp to 1e-12; the DeepSeek picks' hold and entered from A's files equal select.json; every pooled figure recomputes from the files."""
    tl, sfx = ctx.tl, ("_r2" if ctx.rerun else "")
    bad = []
    md = tl.out_file(f"TWINS_KO{sfx}.md")
    if not os.path.exists(md) or open(md, encoding="utf-8").read() != render_md(doc):
        bad.append("TWINS_KO.md is not twins.json rendered")
    order = {v.id: i for i, v in enumerate(ctx.variants)}

    def close(a, b):
        if isinstance(a, dict):
            return isinstance(b, dict) and a.keys() == b.keys() and all(close(a[k], b[k]) for k in a)
        if isnan(a) or isnan(b):
            return isnan(a) and isnan(b)
        return abs(float(a) - float(b)) <= 1e-12 * max(1.0, abs(float(b)))
    for pool in ("core", "ds"):
        P = doc["pools"][pool]
        I = _idx(P)
        elig, srows = select_rows(sel, pool, order)
        e0 = sel["pools"][pool]["e0"]
        if not (close(I[("E0", "pick")]["hold"], e0["hold"]) and I[("E0", "pick")]["entered"] == e0["entered"]):
            bad.append(f"{pool}: the E0 pick column differs from select.json")
        picks = [p for p in ctx.picks if p["pool"] == pool]
        a_e0 = [adapt_a(load(a_file(ctx, p, "E0", "q25"))) for p in picks]
        for vid in elig:
            r, s = I[(vid, "pick")], srows[vid]
            if not (close(r["hold"], s["hold"]) and r["entered"] == s["entered"] and r["entered_e0"] == s["entered_e0"]):
                bad.append(f"{pool} {vid}: the pick column differs from select.json")
            a_v = [adapt_a(load(a_file(ctx, p, vid, "q25"))) for p in picks]
            fv = fig(a_v, a_e0)
            if pool == "core":
                if not all(abs(m - s["Mp"][p["id"]]) <= 1e-12 for m, p in zip(fv["_Mp"], picks)) or not close(r["M_pct_month"], s["M_pct_month"]):
                    bad.append(f"core {vid}: the picks' M_p differ from select.json")
            elif not (close(fv["hold"], s["hold"]) and fv["entered"] == s["entered"]):
                bad.append(f"ds {vid}: the picks' hold or entries differ from select.json")
    try:
        doc2, _md, ds_text, private = build_report(ctx, sel, {k: v for k, v in doc["meta"].items() if k not in (
            "accounts", "files", "removed", "f11_mark", "twins_ds_sha256", "private_section_sha256")})
    except SystemExit as exc:
        return bad + [f"recompute refused: {exc}"]
    if dumps(doc2["pools"]) != dumps(doc["pools"]) or doc2["meta"] != doc["meta"]:
        bad.append("a pooled figure does not recompute from the result files")
    if not os.path.exists(ctx.paths.ds_json) or open(ctx.paths.ds_json, encoding="utf-8").read() != ds_text:
        bad.append("twins_ds.json does not recompute")
    if not os.path.exists(ctx.paths.private_md) or open(ctx.paths.private_md, encoding="utf-8").read() != private:
        bad.append("the private section does not recompute")
    return bad


def audit_private(tl: TLayout, paths: Paths, rerun: bool) -> dict:
    """TW-A9 on $WORK/<pin8>/ds_private/owner_report_extra.md, after the single writer has assembled it and before it is shown."""
    sfx = "_r2" if rerun else ""
    rp = paths.owner_extra
    bad = []
    if not os.path.exists(rp) or inside(rp, tl.root):
        return {"TW-A9": False}
    if any("owner_report_" in os.path.basename(x) for x in tracked(tl.root)):
        bad.append("git tracks an owner report")
    text = open(rp, encoding="utf-8").read()
    doc = json.load(open(tl.out_file(f"twins{sfx}.json"), encoding="utf-8"))
    part = open(paths.private_md, encoding="utf-8").read() if os.path.exists(paths.private_md) else None
    if part is None or part not in text or sha_text(part) != doc["meta"].get("private_section_sha256"):
        bad.append("the twins' private section is not in it verbatim or its sha256 differs")
    if P_VALUE.search(text):
        bad.append("p value")
    if not text.strip() or text.strip().splitlines()[-1].strip() != RX.OWNER_REPORT_LAST_LINE:
        bad.append("last line")
    others = committed_outputs(tl) + [tl.a.out_file(n) for n in A8_SCOPE] + [tl.deviations]
    lines = {ln.strip() for p in others if os.path.exists(p) for ln in open(p, encoding="utf-8").read().splitlines()}
    if any(ln in lines for ln in private_lines(text)):
        bad.append("a line of it is in a committed file")
    h = sha(rp)
    if not any(h in open(p, encoding="utf-8", errors="ignore").read() for p in
               [os.path.join(tl.out, f) for f in (sorted(os.listdir(tl.out)) if os.path.isdir(tl.out) else [])] if os.path.isfile(p)):
        bad.append("its sha256 is not recorded in research/exitflex/extra/out/")
    return {"TW-A9": not bad}


# ------------------------------------------------------------------ commands
def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def file_meta(path: str) -> dict:
    return {"file": os.path.basename(path), "sha256": sha(path),
            "mtime_utc": dt.datetime.fromtimestamp(os.path.getmtime(path), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def cmd_check(tl: TLayout, procs: int = 3) -> bool:
    pin, ph = gate(tl)
    paths = Paths(pin["work"], ph)
    with isolated(tl, paths, "check"):
        ctx = real_ctx(tl, pin, ph, procs)
        res = run_checks(ctx)
        pins = RX.read_sha_file(tl.xlay())
        doc = {"section": "TW", "stage": "twins check", "commit": git_out(tl.root, "rev-parse", "HEAD"), **res,
               "hashes": {os.path.relpath(p, tl.root): h for p, h in pins.items() if not is_check_file(p)}}
        write_committed(tl, "twins_check.json", dumps(doc))
    for k in ("TW-C1", "TW-C2", "TW-C3", "TW-C4"):
        say(f"[twins check] {k} {'pass' if res[k]['pass'] else 'FAIL'}" + ("" if k != "TW-C2" else f" (strategies removed: {len(res['removed'])})"))
    say(f"[twins check] TW-C5 x {'pass' if res['TW-C5']['x'] else 'FAIL'} house {'pass' if res['TW-C5']['house'] else 'FAIL'}")
    say(f"[twins check] {'pass' if res['pass'] else 'FAIL'}: out/twins_check.json")
    return res["pass"]


def cmd_run(tl: TLayout, procs: int = 3, rerun: bool = False) -> None:
    pin, ph = gate(tl)
    require_select(tl, rerun)
    chk = require_check(tl)
    paths = Paths(pin["work"], ph, rerun)
    os.makedirs(paths.tw, exist_ok=True)
    require_disk(float(chk["need_gb"]), pin["work"])
    with isolated(tl, paths, "run"):
        ctx = real_ctx(tl, pin, ph, procs, rerun, chk.get("removed", ()), chk.get("f11_mark"))
        rec = json.load(open(paths.run_record)) if os.path.exists(paths.run_record) else {"start_utc": utc_now()}
        _write(paths.run_record, dumps(rec))
        run_all(ctx)
        rec["end_utc"] = utc_now()
        _write(paths.run_record, dumps(rec))
    say("[twins run] done")


def cmd_report(tl: TLayout, rerun: bool = False, o8: bool = False, fix: int | None = None, fix_note: str | None = None) -> None:
    pin, ph = gate(tl)
    sel = require_select(tl, rerun)
    chk = require_check(tl)
    ctx = report_ctx(tl, pin, ph, chk, rerun)
    with isolated(tl, ctx.paths, "report"):
        missing = [f for f in expected(ctx) if not os.path.exists(f)]
        if missing:
            refuse(f"{len(missing)} result files of TW.2 are missing")
        rec = json.load(open(ctx.paths.run_record)) if os.path.exists(ctx.paths.run_record) else {}
        sn, kn = select_names(rerun)
        meta = {"o7_commit": git_out(tl.root, "log", "--diff-filter=A", "-n", "1", "--format=%H", "--", tl.extra_md),
                "extra_pin_sha256": sha(tl.extra_sha), "select_json": file_meta(tl.a.out_file(sn)), "select_ko": file_meta(tl.a.out_file(kn)),
                "run_start_utc": rec.get("start_utc"), "run_end_utc": rec.get("end_utc"),
                "results_dir": os.path.basename(ctx.paths.results["core"]), "o8_breach": bool(o8),
                "fix": {"n": fix, "note": fix_note, "utc": utc_now()} if fix else None}
        sfx = f"_fix{fix}" if fix else ("_r2" if rerun else "")
        write_report(ctx, sel, meta, sfx)
    say(f"[twins report] written: out/twins{sfx}.json, out/TWINS_KO{sfx}.md and the private section")


def write_report(ctx: Ctx, sel: dict, meta: dict, sfx: str = "") -> dict:
    """The private section and twins_ds.json first (their sha256 go into twins.json), then twins.json and TWINS_KO.md."""
    doc, md, ds_text, private = build_report(ctx, sel, meta)
    write_private(ctx, ctx.paths.private_md, private)
    write_private(ctx, ctx.paths.ds_json, ds_text)
    write_committed(ctx.tl, f"twins{sfx}.json", dumps(doc))
    write_committed(ctx.tl, f"TWINS_KO{sfx}.md", md)
    return doc


def cmd_audit(tl: TLayout, rerun: bool = False, private: bool = False) -> bool:
    pin, ph = gate(tl)
    paths = Paths(pin["work"], ph, rerun)
    if private:
        res = audit_private(tl, paths, rerun)
    else:
        sel = require_select(tl, rerun)
        chk = require_check(tl)
        iso = {}
        with isolated(tl, paths, "audit", iso):
            sfx = None
            if rerun:
                sfx = "_r2" if os.path.isdir(paths.results["core"]) else ""
            ctx = real_ctx(tl, pin, ph, 1, rerun, chk.get("removed", ()), chk.get("f11_mark"), sfx)
            res = run_audits(ctx, sel, lambda m: (DX.open_cut(pin["work"], ph, DX.SELECT_CUT_MS), assert_select_only(m)))
        rec = json.load(open(paths.isolation)) if os.path.exists(paths.isolation) else {}
        res["TW-A7"] = bool(iso.get("ok")) and all(rec.get(c, False) for c in ("check", "run", "report", "audit"))
    for k in sorted(res):
        say(f"[twins audit] {k} {'pass' if res[k] else 'FAIL'}")
    return all(res.values())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    r = sub.add_parser("run")
    r.add_argument("--procs", type=int, default=3)
    r.add_argument("--rerun", action="store_true")
    rp = sub.add_parser("report")
    rp.add_argument("--rerun", action="store_true")
    rp.add_argument("--o8-breach", action="store_true", help="TW.7 step 2: the O8-breach line replaces the fourth fixed line")
    rp.add_argument("--fix", type=int, default=None, help="TW.10: write TWINS_KO_fix<N>.md / twins_fix<N>.json")
    rp.add_argument("--fix-note", default=None)
    au = sub.add_parser("audit")
    au.add_argument("--rerun", action="store_true")
    au.add_argument("--private", action="store_true")
    a = ap.parse_args(argv)
    tl = TLayout()
    if a.cmd == "check":
        return 0 if cmd_check(tl) else 1
    if a.cmd == "run":
        cmd_run(tl, a.procs, a.rerun)
    elif a.cmd == "report":
        if a.fix and not a.fix_note:
            refuse("--fix needs --fix-note")
        cmd_report(tl, a.rerun, a.o8_breach, a.fix, a.fix_note)
    elif a.cmd == "audit":
        return 0 if cmd_audit(tl, a.rerun, a.private) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
