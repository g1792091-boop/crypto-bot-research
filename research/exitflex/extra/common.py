"""Common part of the extra reads and twins (research/exitflex/PREREG_EXITFLEX_EXTRA.md, E.0-E.6; main file 3, 7, 8.2, 13, 16.7).

What lives here and nowhere else:
  load_ctx / Ctx      A's pin (runner_x.gate_pin), the extra pin, the select cut (data_x.open_cut, A5), the picks, the 88 variants with
                      the F11 provider registered as A's runner does, the month edges, the folders, and, only when asked for
                      (allow_select=True, after O8), A's pinned select.json and its choosable ids.
  account / placebo   A's step-1 result files and step-2 placebo blocks, read only, through runner_x.Store paths; every path is
                      checked against the files the extra file may read (E.1 item 9) and anything else is refused.
  money_allowed       the row rule (A 8.2 item 6, E.1 item 4); pooled_M refuses a money figure on any other row.
  ds_row_check        the extra file's own D11 check of A8 (1) on every DeepSeek row of a committed output (C8; alias ds_guard).
  write_out           the one writer of outputs: committed ones to research/exitflex/extra/out/, DeepSeek money only to ds_private.
  run_record          the E.5 run record and disk rules.
  C1-C17              constants and small helpers of the conventions of E.2.

Nothing here prints a figure. The only console line is the pin line of load_ctx.
"""

from __future__ import annotations

import contextlib
import csv
import datetime as dt
import functools
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from collections import OrderedDict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))            # research/exitflex/extra
XDIR = os.path.dirname(HERE)                                 # research/exitflex
ROOT = os.path.dirname(os.path.dirname(XDIR))
for _p in (XDIR, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import data_x as DX  # noqa: E402
import kernel_x as KX  # noqa: E402
import metrics as MT  # noqa: E402
import runner_x as RX  # noqa: E402


class Refused(RuntimeError):
    """A read, a write or a row that the extra file's rules do not allow."""


# ====================================================================================================== C1 scope
POOLS = ("core", "ds")
POOL_PICKS = {"core": 23, "ds": 15}
SIZE_Q, SIZE_LIVE = 0.25, 1.0
N_MONTHS, N_DAYS = 36, 1095
COINS = DX.SYMBOLS                                           # league order BTC, ETH, SOL, DOGE, LTC, BCH
COIN_SHORT = tuple(s[:-4] for s in DX.SYMBOLS)
TF_COUNTS = {"core": {"15m": 4, "30m": 7, "1h": 6, "4h": 6}, "ds": {"15m": 1, "30m": 1, "1h": 6, "4h": 7}}
HOUSE_ARMS = ("HOUSE", "H")                                  # the house exit of the twins (E.1 item 4: 'H')


def c1_check(picks: list) -> None:
    """C1: 23 core and 15 DeepSeek picks with the stated timeframe counts."""
    for pool in POOLS:
        ps = [p for p in picks if p["pool"] == pool]
        got = {tf: sum(p["tf"] == tf for p in ps) for tf in DX.TFS}
        if len(ps) != POOL_PICKS[pool] or got != TF_COUNTS[pool]:
            raise AssertionError(f"C1: {pool} picks {len(ps)} {got}")


# ====================================================================================================== C5 status, C10 time, C11 seeds
STATUS = ("skipped", "entered", "rejected", "no_fill", "after_bust")      # C5 codes 0-4
DAY_MS, HOUR_MS, WEEK_MS = 86_400_000, 3_600_000, 604_800_000
MON0_MS = 345_600_000                                        # Monday 1970-01-05 00:00 UTC
SELECT_LO, SELECT_HI = DX.PERIOD_MS["select"]
WEEK0 = (SELECT_LO - MON0_MS) // WEEK_MS
N_WEEKS = int((SELECT_HI - 1 - MON0_MS) // WEEK_MS - WEEK0 + 1)          # 157 Monday weeks, part-weeks kept
WEEKDAY_KO = ("월", "화", "수", "목", "금", "토", "일")
SESSIONS = ("Asia", "Europe", "US")                          # UTC [0,8), [8,16), [16,24)
SESSION_KO = ("아시아", "유럽", "미국")
CAL_WEEKEND_SHARE = 2 / 7
KST_H = 9


def dow(t_ms):
    """C10: weekday of a UTC time in ms, Monday = 0."""
    return ((np.asarray(t_ms, np.int64) // DAY_MS) + 3) % 7


def is_weekend(t_ms):
    """C10: Sat 00:00 <= t < Mon 00:00 UTC (apply it to t_sig)."""
    return dow(t_ms) >= 5


def hour_utc(t_ms):
    return (np.asarray(t_ms, np.int64) // HOUR_MS) % 24


def session_of(t_ms):
    """0 Asia [0,8), 1 Europe [8,16), 2 US [16,24) UTC; a time of 08:00:00 is Europe."""
    return hour_utc(t_ms) // 8


def block4(t_ms):
    return hour_utc(t_ms) // 4


def week_index(t_ms, merge_first: bool = False):
    """Monday-00:00-UTC week of the select period (0..156); ``merge_first`` folds the part-week 2021-01-01..03 into the first full
    week (156 blocks)."""
    w = (np.asarray(t_ms, np.int64) - MON0_MS) // WEEK_MS - WEEK0
    return np.maximum(w - 1, 0) if merge_first else w


def month_index(t_ms, edges: np.ndarray):
    """The select month (0..35) of a time, by the UTC month edges."""
    return np.searchsorted(edges, np.asarray(t_ms, np.int64), side="right") - 1


def utc_kst(t_ms: int) -> str:
    """'YYYY-MM-DD HH:MM UTC (KST HH:MM)' (C10: KST printed beside)."""
    d = dt.datetime.fromtimestamp(int(t_ms) / 1000, dt.timezone.utc)
    return f"{d:%Y-%m-%d %H:%M} UTC (KST {(d + dt.timedelta(hours=KST_H)):%H:%M})"


def seed_c11(read_id: str, pool: str, arm: str, *part) -> int:
    """C11: data_x.seed_of('exitflex-extra', read id, pool, arm id[, part])."""
    return DX.seed_of("exitflex-extra", read_id, pool, arm, *part)


# ====================================================================================================== C6, C7, C9, C12-C17
THIN_MIN = 100
THIN_KO = "건수 적음"
FEW_PICKS = 3
EMPTY = "-"
TAG_TABLE = "참고용 · 고르는 데 안 씀"
U_GROWTH, U_CONTRIB, U_MULT, U_ROE, U_WALLET = "%/월", "%/월 기여(근사)", "x", "%", "지갑 %"
CONTRIB_NOTE_KO = "'%/월 기여(근사)'는 한 달 로그 성장의 해당 부분에 100을 곱한 값입니다. 부분을 더하면 전체와 맞고, %/월과는 조금 다릅니다."
F7_RF_ONLY = "F7_RF_ONLY"
BUST_W = 10.0                                                 # w_end < $10 is a bust (A 7)
# warning sentences given verbatim in E.3 (W1, W2, W18 and W22-W24 have no verbatim text there; W8 holds a blank)
W = {"W0": "이 문서의 숫자는 모두 2021~2023년 백테스트입니다. 이 기간은 매매법의 숫자와 지금 청산(E0)을 고른 기간이라, 앞으로보다 좋게 나온 값입니다. "
           "고를 수 있는지는 고르기 표(SELECT_KO)의 기준으로만 정하고, 이 문서는 참고용입니다.",
     "W3": "코인별 차이는 대부분 그 기간 그 코인의 가격 흐름 때문입니다(예: 2021년 상반기 도지 급등). 코인을 빼거나 골라 쓰는 규칙은 이 시험으로 정할 수 없고, "
           "새 사전 등록이 필요합니다.",
     "W4": "요일·시간대·주말 규칙은 이 표로 정하지 않습니다. 정하려면 새 사전 등록이 필요하고, 이 표를 본 뒤에는 2021~2023년이 이미 본 기간이 됩니다.",
     "W5": "미래를 다 아는 사람만 낼 수 있는 숫자입니다. 이 값이 크다고 청산을 바꾸면 그만큼 벌 수 있다는 뜻은 아니며, 실제 청산은 이 값의 작은 부분만 얻는 것이 "
           "정상입니다. 반대로 이 값이 x5보다 작으면, 이 진입들로는 청산만 바꿔서 한 달 x5가 안 된다는 뜻입니다.",
     "W6": "'몇 달이면 x5'는 2021~2023의 보통 달이 앞으로 똑같이 반복된다고 가정한 산수이며 예측이 아닙니다.",
     "W7": "'x5에 닿음'은 그 달 안에 한 번이라도 계좌가 5배 이상이 된 것이며, 달 끝에 5배라는 뜻이 아닙니다.",
     "W8": "같은 기간에 88개를 돌려 좋은 것을 고르면 실력이 없어도 '세 해 모두 +'나 '같은 방향'이 나옵니다. 나오는 때만 무작위로 바꾼 가짜 청산에서도 보통 "
           "{n}개가 그렇게 나왔습니다. '0을 안 걸침'도 88개 중에서 고른 것이라 증거가 아닙니다.",
     "W9": "크게 걸면 좋은 달도 커지지만 파산도 함께 늘어납니다. 1/1 크기 숫자는 항상 옆의 파산 수와 같이 읽어 주세요. 연구와 리그는 1/4 크기로 판정하며, "
           "이 표로 실제 돈의 크기를 정하지 않습니다.",
     "W10": "이 범위는 성적을 맞춘 2021~2023에서 만든 참고 범위라 실제보다 좋게 나왔을 수 있습니다. 리그에서 아무것도 결정하지 않으며, 결정은 계약 11.5의 "
            "30일(C1)·61일(C2) 점검만 합니다.",
     "W11": "30일 점검(C1)은 계약대로 적용됩니다. C1을 통과해도 30일 결과만으로 더 나은지 판단하지 마세요.",
     "W11_X044": "30일 점검(C1)은 계약대로 적용됩니다. C1을 통과해도 30일·61일 결과만으로 더 나은지 판단하지 마세요. 새 청산이 정말 더 낫더라도 그 기간에는 "
                 "드러나지 않을 때가 많습니다. 이 확률은 리그에서 아무것도 결정하지 않습니다.",
     "W12": "지금 청산보다 덜 잃은 것이지 돈을 번 것은 아닙니다.",
     "W13": "숫자는 매매법마다 따로 5,000달러 지갑으로 돌린 결과입니다. 1,000달러 한 계좌로 여러 매매법을 같이 돌리면 증거금이 모자라 같은 결과가 나오지 않습니다.",
     "W14": "일찍 나오는 청산은 승률을 올리는 대신 이길 때 크기를 줄입니다. 승률만 보지 말고 손익비·본전 승률과 함께 보세요.",
     "W15": "이득이 작아(한 달 0.1% 미만) 나눈 비율은 표시하지 않고 금액만 적었습니다.",
     "W20": "기간 전체로 정한 매매법 성격(사후 분류)이며 규칙이 아닙니다. 성격별로 청산을 따로 고르지 않습니다.",
     "W21": "픽끼리 같은 코인을 거래하므로 3/4 같은 숫자는 설명이지 증거가 아닙니다."}


def k_of_n(k: int, n: int) -> str:
    """C6: 'k of N' always prints N."""
    return f"{int(k)}/{int(n)}"


def per_account_month(count: float, n_picks: int) -> float:
    """C6: a rate per account-month over the calendar denominator picks x 36."""
    return float(count) / (n_picks * N_MONTHS)


def alive_months(acc: dict) -> np.ndarray:
    """C6 (money samples only): for a busted account (w_end < $10) the months after its last month with g != 0 are dropped."""
    g = np.asarray(acc["g"])
    if float(acc["w_end"]) >= BUST_W:
        return np.ones(len(g), bool)
    nz = np.flatnonzero(g != 0)
    return np.arange(len(g)) <= (nz[-1] if len(nz) else -1)


def c7_mark(n, n_picks: int | None = None, min_n: int = THIN_MIN) -> str:
    """C7 / E.1 item 7: '-' for an empty cell; '건수 적음' under ``min_n`` of the read's unit; '픽 N개' under 3 picks. Nothing is hidden."""
    if not n:
        return EMPTY
    marks = [THIN_KO] if n < min_n else []
    if n_picks is not None and n_picks < FEW_PICKS:
        marks.append(f"픽 {int(n_picks)}개")
    return " · ".join(marks)


def se(x) -> float:
    """C9: sd / sqrt(n) (sample sd); nan under 2 values."""
    x = np.asarray(x, float)
    return float(np.std(x, ddof=1) / math.sqrt(len(x))) if len(x) > 1 else float("nan")


def c9_contrib(sums_by_pick) -> float:
    """C9: c(b) = 100 x mean over picks of (sum of l_i in b) / 36 ('%/월 기여(근사)')."""
    return 100.0 * float(np.mean(np.asarray(sums_by_pick, float))) / N_MONTHS


def pct_month(M):
    """C12: a growth level or difference per month in log units as '%/월' = 100 (e^M - 1)."""
    return 100.0 * np.expm1(M) if isinstance(M, np.ndarray) else 100.0 * math.expm1(M)


def contrib_pct(logpart):
    """C12: an additive contribution: 100 x the log part ('%/월 기여(근사)', with CONTRIB_NOTE_KO as its footnote)."""
    return 100.0 * logpart


def bust_cell(k: int, n: int) -> str:
    """C12: every live-size cell carries '파산 k/N'."""
    return f"파산 {k_of_n(k, n)}"


def c13_mark(pick: dict, arm: str) -> str:
    """C13: on F7_RF_ONLY picks F11.a = F3.a and F11.b = F3.b (Known limit 11)."""
    if pick.get("name") == F7_RF_ONLY and arm in ("F11.a", "F11.b"):
        return "= F3." + arm[-1]
    return ""


CHANCE_SHARE = 0.05


def c15_line(n_cells: int, n_thin: int, n_out: int | None = None) -> str:
    """C15: the chance-cell line under every split table (tables without a range print N and K only)."""
    head = f"이 표의 칸은 {n_cells}개, 그중 {THIN_KO} {n_thin}개입니다."
    if n_out is None:
        return head
    m = CHANCE_SHARE * n_cells
    return head + f" 실력 차이가 전혀 없어도 약 {m:.1f}개 칸은 우연 범위를 벗어나 보이고, 실제로 벗어난 칸은 {n_out}개입니다."


def own_growth_log(accs: list) -> float:
    """Own monthly growth in log units: mean over picks of ln(w_end / w0) / 36 (X-046, X-047)."""
    return float(np.mean([math.log(max(float(a["w_end"]), 1e-12) / float(a["w0"])) for a in accs])) / N_MONTHS


def c16_note(own_pct: float) -> str:
    """C16: W12 when a row's own growth is <= 0."""
    return W["W12"] if own_pct <= 0 else ""


C17_MIN_PCT, C17_MAX_SHARE = 0.1, 3.0


def c17_shares(parts, total):
    """C17: shares part/total, only when 100 x |total| >= 0.1 (%/월) and every share lies within +-300%; else None (print the amounts and
    W15). ``parts`` and ``total`` in the same log units per month."""
    total = float(total)
    if not 100.0 * abs(total) >= C17_MIN_PCT:
        return None
    sh = np.asarray(parts, float) / total
    return None if np.any(~np.isfinite(sh)) or np.any(np.abs(sh) > C17_MAX_SHARE) else sh


# ====================================================================================================== C8 classes: the DeepSeek row check
DS_MONEY_KEYS = {"M", "Mp", "D", "G", "g", "W", "c", "dc", "x", "l", "R", "ROE", "p", "lo", "hi", "w0", "w_end", "max_dd", "M_pct_month",
                 "median_Mp", "n_pos", "live", "placebo", "p95_gate", "qa", "offered_after_bust", "no_fill", "after_bust", "bust", "busts",
                 "final_multiple", "final_multiple_median", "max_dd_median", "same_side", "dir_growth", "share_pos", "interval95"}
DS_MONEY_TOKENS = {"pnl", "ret", "rets", "return", "returns", "growth", "wallet", "wend", "w0", "dd", "mdd", "drawdown", "bust", "busts",
                   "busted", "nofill", "after", "multiple", "mult", "lev", "leverage", "margin", "funding", "fund", "cost", "costs", "fee",
                   "fees", "roe", "r", "lam", "dlam", "ci", "interval", "range", "chance", "p", "pval", "pvalue", "rank", "sizeable",
                   "ceiling", "excursion", "mae", "mfe", "streak", "rsel", "character", "money", "profit", "usd", "pos", "m", "mp", "g",
                   "c", "dc", "x", "l", "lo", "hi", "gain", "giveback", "payoff", "breakeven", "alive"}
# labels and count-class names (C8) a DeepSeek row may hold, beside A's own whitelist (metrics.DS_ALLOWED)
DS_EXTRA_ALLOWED = (set(MT.DS_ALLOWED) | {
    "read", "table", "row", "pool", "arm", "pick", "pick_id", "coin", "side", "tf", "bucket", "key", "label", "labels", "flag", "flags",
    "few", "thin", "mark", "marks", "note", "tag", "kind", "part", "size", "session", "weekday", "dow", "block", "year", "week", "wk",
    "unit", "units", "n_units", "thin_ids", "dir_hold", "dir_entries", "seed_median", "seed_min", "seed_max", "picks", "cells",
    "offered", "n_off", "n_ent", "n_skip", "n_rej", "n", "wins", "losses", "f11_mark", "k_of_n"}) - DS_MONEY_KEYS
_DS_COUNT_KEY = re.compile(r"^(n|n_\w+|counts?(_\w+)?|entered\w*|skipped\w*|rejected\w*|closed\w*|offered\w*|wins?(_\w+)?|losses(_\w+)?|"
                           r"hold\w*|median_hold\w*|share(_\w+)?|reasons?(_\w+)?|comp_\w+|state\w*|dn(_\w+)?|label_\w+|flag_\w+|by_\w+)$")
_ARM_KEY = re.compile(r"^(E0|H|HOUSE|F\d+h?\.[\w.]+)$")
_PICK_KEY = re.compile(r"^(core|ds|base)-[\w.-]+$")
DS_BUCKET_LABELS = (set(DX.SYMBOLS) | set(COIN_SHORT) | set(MT.REASONS) | set(DX.STATE_KO.values()) | set(MT.COMP_LABELS) | set(DX.TFS)
                    | set(SESSIONS) | set(SESSION_KO) | set(WEEKDAY_KO) | set(MT.DS_NESTED_ALLOWED)
                    | {"long", "short", "all", "weekend", "weekday", "wk0", "wk1", "e0", "rows", "cells"})
_STR_FIGURE = re.compile(r"%/월|\d\s*%|\d\s*(?:x|배)\b|\$\s?\d")


def _money_key(k: str) -> bool:
    low = k.lower()
    return k in DS_MONEY_KEYS or "no_fill" in low or "after_bust" in low or any(t in DS_MONEY_TOKENS for t in low.split("_"))


def ds_key_ok(k, nested: bool = False) -> bool:
    """C8: a key a DeepSeek row of a committed output may hold (nested: also bucket labels, arm ids, pick ids and integer labels)."""
    if isinstance(k, (int, np.integer)):
        return nested
    k = str(k)
    if k in MT.DS_NESTED_ALLOWED or k in MT.REASONS:          # A's nested whitelist (hold statistics, reasons, states, gates, F12 parts)
        return nested or k in DS_EXTRA_ALLOWED
    if k in DS_EXTRA_ALLOWED:
        return True
    if _money_key(k):
        return False
    if _DS_COUNT_KEY.match(k.lower()):
        return True
    return nested and (k in DS_BUCKET_LABELS or bool(_ARM_KEY.match(k)) or bool(_PICK_KEY.match(k)) or k.isdigit())


def _ds_problems(v, where: str, nested: bool) -> list:
    bad = []
    if isinstance(v, dict):
        for k, x in v.items():
            if not ds_key_ok(k, nested):
                bad.append(f"{where}{k}")
            else:
                bad += _ds_problems(x, f"{where}{k}.", True)
    elif isinstance(v, (list, tuple)):
        for i, x in enumerate(v):
            bad += _ds_problems(x, f"{where}[{i}].", True)
    elif isinstance(v, str) and (_STR_FIGURE.search(v) or (MT._MONEY_WORD.search(v) and re.search(r"\d", v))):
        bad.append(f"{where}= {v[:40]!r}")
    return bad


def ds_row_check(row: dict) -> None:
    """C8 / A8 (1): raise ``Refused`` when a DeepSeek row of a committed output holds a field outside the allowed set (counts, win
    shares, hold times, exit reasons, F12 component counts, labels), at any depth, or a string that shows a figure with a unit."""
    if not isinstance(row, dict):
        raise Refused("a DeepSeek row must be a dict")
    bad = _ds_problems(row, "", False)
    if bad:
        raise Refused("DeepSeek row holds fields outside the D11 whitelist: " + ", ".join(bad[:8]))


ds_guard = ds_row_check                                      # the name C8 gives it


_DS_LINE = re.compile(r"ds-[A-Za-z0-9_]|딥시크|deepseek", re.I)
_DS_POOL_WORD = re.compile(r"딥시크|deepseek", re.I)


def c14_problems(md: str) -> list:
    """C14 on a committed Korean page: the pool name only in a heading; no ds- id or pool word on a line that holds a figure; inside a
    DeepSeek section no percent (shares print as k/n) and no money pattern (metrics.ds_text_problems). [] = pass."""
    bad = list(MT.ds_text_problems(md))
    inside = False
    for ln in md.splitlines():
        level = len(ln.lstrip()) - len(ln.lstrip().lstrip("#"))
        head = level > 0
        if head:                                             # a level 1-2 heading opens or closes a DeepSeek section; deeper ones stay in it
            inside = bool(_DS_POOL_WORD.search(ln)) or (inside and level > 2)
        rest = MT._COUNTED.sub(" ", MT._IDENT.sub(" ", ln.replace(MT.DS_MARKER, " ")))
        if _DS_POOL_WORD.search(ln) and not head:
            bad.append(ln.strip())
        elif _DS_LINE.search(ln) and re.search(r"\d", rest):
            bad.append(ln.strip())
        elif inside and not head and re.search(r"\d\s*%", ln):
            bad.append(ln.strip())
    return list(dict.fromkeys(bad))


# ====================================================================================================== context
SELECT_STAGE = {"extra": "select", "extra_r2": "select_r2"}
NEVER_READ = ("core_not_choosable.json", "select_ds.json", "select_ds_r2.json", "SELECT_TABLE.csv", "run_info.json")
NEVER_OUT = ("select", "confirm", "report_ko")                  # lower-case starts of names an output never has (SELECT_KO included)
PRIVATE_ROOT = ("extra_reads_ds.json", "owner_report_extra.md", "extra_reads_ds_r2.json", "owner_report_extra_r2.md")
CACHE_MAX = 512


class Ctx:
    """Everything the reads share. Build it with ``load_ctx``; tests may build it directly. ``market`` is built on first use (the cut's
    minute arrays, the A5 check, kernel_x.warm_up); a pure post-processing read never loads it."""

    def __init__(self, lay, pin: dict, pin_hash: str, stage: str = "extra", picks=None, variants=None, cut_dir=None, rprov=None):
        self.lay, self.pin, self.pin_hash, self.stage = lay, pin, pin_hash, stage
        self.pin8, self.work = DX.pin8(pin_hash), pin["work"]
        self.rerun = stage.endswith("_r2")
        self.sel_stage = SELECT_STAGE.get(stage, "select_r2" if self.rerun else "select")
        self.cut_dir, self.rprov = cut_dir, rprov
        self.picks = list(picks or [])
        self.by_id = {p["id"]: p for p in self.picks}
        self.variants = list(variants or [])
        self.vids = [v.id for v in self.variants]
        self.edges = MT.month_edges("select")
        self.pools = POOLS
        self.store = RX.Store(self.work, pin_hash, self.sel_stage)
        self.out_dir = os.path.join(lay.base, "extra", "out")
        self.work_extra = os.path.join(self.work, self.pin8, "extra")
        self.ds_private_root = os.path.join(self.work, self.pin8, "ds_private")
        self.private_dir = os.path.join(self.ds_private_root, "extra")
        self.select_path = lay.out_file(f"{self.sel_stage}.json")
        self.allow_select = False
        self.cache = OrderedDict()
        self.set_select(None)
        if _same(self.out_dir, lay.out):
            raise Refused("the extra outputs never go into research/exitflex/out/")

    def set_select(self, doc: dict | None) -> None:
        """The choosable ids (pools.<pool>.eligible_ids), defaults, seed count and row order from A's select.json (None: empty sets)."""
        self.select_doc = doc
        P = (doc or {}).get("pools") or {}
        self.choosable = {p: set((P.get(p) or {}).get("eligible_ids") or []) for p in POOLS}
        self.default_ids = {p: list((P.get(p) or {}).get("default_ids") or []) for p in POOLS}
        self.n_seeds = int(doc["n_seeds"]) if doc and doc.get("n_seeds") else None
        self.cache.clear()                                   # money_ok of cached accounts follows the choosable sets

    def pick(self, p) -> dict:
        return self.by_id[p] if isinstance(p, str) else p

    def pool_picks(self, pool: str) -> list:
        return [p for p in self.picks if p["pool"] == pool]

    @functools.cached_property
    def market(self):
        if not self.cut_dir:
            raise Refused("no verified cut folder in this context")
        mk = DX.Market(self.cut_dir)
        a5_check(mk)
        KX.warm_up(mk)
        return mk

    def pickdata(self, pick):
        return DX.PickData(self.market, self.pick(pick), self.rprov, f11=KX.F11_REGISTRY["provider"])


def _same(a: str, b: str) -> bool:
    return os.path.realpath(a) == os.path.realpath(b)


def _inside(path: str, folder: str) -> bool:
    p, f = os.path.realpath(path), os.path.realpath(folder)
    return os.path.commonpath([p, f]) == f


def a5_check(market) -> None:
    """A5: no array of the market holds a minute at or after 2024-01-01 00:00 UTC."""
    DX.assert_no_minute_at_or_after({s: {"ts": market.ts(i)} for i, s in enumerate(market.symbols)}, DX.SELECT_CUT_MS)


def extra_sha_file(lay) -> str:
    return os.path.join(lay.base, "PREREG_EXITFLEX_EXTRA.sha256")


def gate_extra(lay) -> str:
    """The extra pin (TW.3 gate): every file listed in PREREG_EXITFLEX_EXTRA.sha256 has its listed hash (a path listed twice: its last line)
    and every .py file under research/exitflex/extra/ (os.walk) is listed. Returns the sha256 of the pin file."""
    path = extra_sha_file(lay)
    pins = RX.read_sha_file(RX.Layout(base=lay.base, root=lay.root, out=lay.out, sha_file=path, pin_file=lay.pin_file, required=()))
    bad = [p for p, h in pins.items() if not os.path.exists(p) or RX.sha256_file(p) != h]
    if bad:
        RX.refuse("extra pin: hash mismatch: " + ", ".join(os.path.relpath(p, lay.root) for p in bad[:6]))
    code = [os.path.normpath(os.path.join(d, f)) for d, _dn, fs in os.walk(os.path.join(lay.base, "extra")) for f in sorted(fs) if f.endswith(".py")]
    loose = [os.path.relpath(c, lay.root) for c in code if c not in pins]
    if loose:
        RX.refuse("extra pin: not pinned (code of research/exitflex/extra): " + ", ".join(loose[:6]))
    return RX.sha256_file(path)


def load_ctx(lay=None, stage: str = "extra", allow_select: bool = False) -> Ctx:
    """A's pin (gate_pin, its console line replaced by one '[extra pin ok]' line), the extra pin, data_pin.json, the select cut through
    data_x.open_cut (digests, no minute at or after 2024-01-01; a missing cut is a refusal, it is never made here), the picks, the 88 variants
    with the F11 provider registered as runner_x does (refused without the native modules), and, only with ``allow_select`` (after O8),
    A's select.json, which must be listed in PREREG_EXITFLEX.sha256 with its present hash and carry this pin. The extra cache folder
    $WORK/<pin8>/extra/cache is emptied first."""
    lay = lay or RX.Layout()
    with contextlib.redirect_stdout(io.StringIO()):
        pin, ph = RX.gate_pin(lay)
    xsha = gate_extra(lay)
    symbols = tuple(s for s in DX.SYMBOLS if s in pin["coins"])
    try:
        cut = DX.open_cut(pin["work"], ph, DX.SELECT_CUT_MS, symbols)
    except DX.PinError as exc:
        RX.refuse(f"select cut: {exc}")
    ctx0 = Ctx(lay, pin, ph, stage)
    cache = os.path.join(ctx0.work_extra, "cache")
    shutil.rmtree(cache, ignore_errors=True)
    os.makedirs(cache, exist_ok=True)
    rprov = DX.RealProvider(cut, cache)
    prov11 = RX.f11_provider_from_modules(rprov, *RX.try_load_native())
    if prov11 is None:
        RX.refuse("native.py / native_ds.py (families F11 and F12) are not available: the pre-registered menu has 88 variants")
    KX.register_f11(prov11)
    vs = KX.variants()
    if len(vs) != 88:
        RX.refuse(f"the menu has {len(vs)} variants, not 88")
    ctx = Ctx(lay, pin, ph, stage, DX.picks(), vs, cut, rprov)
    if allow_select:
        ctx.allow_select = True
        path = check_read(ctx, ctx.select_path)
        RX.require_pinned_file(lay, ctx.select_path, os.path.basename(ctx.select_path))
        doc = json.load(open(path, encoding="utf-8"))
        if doc.get("pin") != ph:
            RX.refuse(f"{os.path.basename(path)} was made under another pin")
        ctx.set_select(doc)
        unknown = sorted(set().union(*ctx.choosable.values()) - set(ctx.vids))
        if unknown:
            RX.refuse(f"choosable ids not in the menu: {unknown[:4]}")
    print(f"[extra pin ok] commit {RX.git_head(lay.root)[:10]} pin {ctx.pin8} extra {xsha[:8]}", flush=True)
    return ctx


def rows_order(ctx: Ctx, pool: str) -> list:
    """E.1 item 8: E0 first, then the select table's order (choosable first, canonical inside each part; the canonical order without
    select.json)."""
    if ctx.select_doc:
        return ["E0"] + [r["id"] for r in ctx.select_doc["pools"][pool]["variants"]]
    return ["E0"] + list(ctx.vids)


# ====================================================================================================== reads of A's files
def check_read(ctx: Ctx, path: str) -> str:
    """E.1 item 9: the only files of A the extra code reads are result files (.npz) under results/<select stage>/ and
    ds_private/results/<select stage>/ of this pin, and A's select.json when the context allows it. Everything else (core_not_choosable.json,
    select_ds.json, owner reports, confirm files, other stages, research/exitflex/out/ otherwise) is refused. Returns the real path."""
    real = os.path.realpath(path)
    name = os.path.basename(real)
    if name in NEVER_READ or name.startswith("owner_report_"):
        raise Refused(f"never read: {name}")
    if ctx.allow_select and real == os.path.realpath(ctx.select_path):
        return real
    base = os.path.realpath(os.path.join(ctx.work, ctx.pin8))
    rel = os.path.relpath(real, base).split(os.sep)
    ok = real.endswith(".npz") and rel[0] != ".." and (rel[:2] == ["results", ctx.sel_stage] or rel[:3] == ["ds_private", "results", ctx.sel_stage])
    if not ok or any(x.lower().startswith("confirm") for x in rel):
        raise Refused(f"outside results/{ctx.sel_stage}/: {path}")
    return real


def _load(ctx: Ctx, path: str) -> dict:
    with np.load(check_read(ctx, path)) as z:
        return {k: z[k] for k in z.files}


def money_allowed(ctx: Ctx, pool: str, arm: str) -> bool:
    """A 8.2 item 6 / E.1 item 4: a money figure only for E0, the house exit and the pool's choosable ids (empty without select.json)."""
    return arm == "E0" or arm in HOUSE_ARMS or arm in ctx.choosable.get(pool, set())


def account(ctx: Ctx, pick, arm: str, size: float) -> dict:
    """A's step-1 result file of (pick, arm, size 0.25 or 1.0), read only (DeepSeek picks under ds_private/, as A's Store), with the summarize
    keys and, per entered trade in exit order (one position at a time): wallet_before (C4: cumsum of [w0, tr_pnl][:-1]), ret = x_i =
    tr_pnl / wallet_before, l = ln(max(W_b + pnl, 1e-12) / W_b) (sum asserted to ln(w_end / w0)), win (pnl > 0), entry_dt / exit_dt
    (datetime64[ms] UTC), weekday (of the fill, Monday 0), session (of the fill: 0 Asia, 1 Europe, 2 US), month (exit month, as g) and
    month_fill; plus pick, pool, arm, size and money_ok (the row rule). Arrays are read-only; the dict is a copy."""
    p = ctx.pick(pick)
    if size not in RX.SIZE_TAG:
        raise ValueError(f"size {size}: 0.25 or 1.0")
    key = (p["id"], arm, size)
    if key in ctx.cache:
        ctx.cache.move_to_end(key)
        return dict(ctx.cache[key])
    d = _load(ctx, ctx.store.path(p, arm, RX.SIZE_TAG[size]))
    fi, ex, pnl = d["tr_fill"].astype(np.int64), d["tr_exit"].astype(np.int64), d["tr_pnl"].astype(float)
    if len(ex):
        DX.assert_no_minute_at_or_after({"trades": {"ts": np.array([max(fi.max(), ex.max())])}}, DX.SELECT_CUT_MS)
        if np.any(fi[1:] < ex[:-1]):
            raise AssertionError(f"{p['id']} {arm}: positions overlap")
    w0, w_end = float(d["w0"]), float(d["w_end"])
    wb = np.cumsum(np.r_[w0, pnl])[:-1]
    l = np.log(np.maximum(wb + pnl, 1e-12) / wb)
    if abs(float(l.sum()) - math.log(max(w_end, 1e-12) / w0)) > 1e-9:
        raise AssertionError(f"{p['id']} {arm}: sum of l_i differs from ln(w_end / w0)")
    out = {**d, "wallet_before": wb, "ret": pnl / wb, "l": l, "win": pnl > 0, "entry_dt": fi.astype("datetime64[ms]"),
           "exit_dt": ex.astype("datetime64[ms]"), "weekday": dow(fi), "session": session_of(fi), "month": month_index(ex, ctx.edges),
           "month_fill": month_index(fi, ctx.edges)}
    for v in out.values():
        if isinstance(v, np.ndarray):
            v.flags.writeable = False
    out.update(pick=p["id"], pool=p["pool"], arm=arm, size=size, money_ok=money_allowed(ctx, p["pool"], arm))
    ctx.cache[key] = out
    if len(ctx.cache) > CACHE_MAX:
        ctx.cache.popitem(last=False)
    return dict(out)


PLC_KEYS = ("g", "w_end", "max_dd", "counts", "reasons", "hold", "seeds")


def placebo(ctx: Ctx, pick, vid: str) -> dict:
    """The step-2 placebo blocks of a choosable row on one pick (E.1 item 9), all seed blocks stacked in seed order: g (seeds x 36), w_end,
    max_dd, counts, reasons, hold, seeds, and num / den summed; n_seeds. The blocks are those of select.json's n_seeds (found on disk when
    the context has no select.json)."""
    p = ctx.pick(pick)
    if vid not in ctx.choosable.get(p["pool"], set()):
        raise Refused(f"placebo blocks are read for choosable rows only: {vid} in {p['pool']}")
    if not KX.has_placebo(KX.variant_by_id(vid)):
        raise Refused(f"{vid} has no placebo (A 6)")
    if ctx.n_seeds:
        tags = [RX.plc_tag(a, b) for a, b in RX.seed_blocks(ctx.n_seeds)]
    else:
        pre = f"{vid}__plc"
        tags = sorted(f[len(vid) + 2:-4] for f in ctx.store.files(p) if f.startswith(pre) and f.endswith(".npz"))
    if not tags:
        raise Refused(f"no placebo blocks for {vid} on {p['id']}")
    parts = [_load(ctx, ctx.store.path(p, vid, t)) for t in tags]
    out = {k: np.concatenate([x[k] for x in parts]) for k in PLC_KEYS}
    out["num"] = np.sum([x["num"] for x in parts], axis=0)
    out["den"] = np.sum([x["den"] for x in parts], axis=0)
    if not np.array_equal(out["seeds"], np.arange(len(out["seeds"]))):
        raise AssertionError(f"{p['id']} {vid}: placebo seeds are not 0..n-1")
    out["n_seeds"] = int(len(out["seeds"]))
    return out


def _g(ctx: Ctx, acc: dict, mask_fn) -> np.ndarray:
    if mask_fn is None:
        return np.asarray(acc["g"], float)
    m = np.asarray(mask_fn(acc), bool)
    return MT.monthly_g(acc["tr_exit"][m], acc["tr_pnl"][m], float(acc["w0"]), ctx.edges)[0]


def pooled_M(ctx: Ctx, pool: str, arm: str, size: float = SIZE_Q, mask_fn=None) -> float:
    """A's M_P: the mean over the pool's picks of the mean monthly [g(arm) - g(E0)] at ``size``. ``mask_fn(acc) -> bool array`` over an
    account's trades keeps only those trades, for the arm and for E0 alike, and g is recomputed by metrics.monthly_g. Refused on a row that
    may not carry money."""
    if not money_allowed(ctx, pool, arm):
        raise Refused(f"no money figure on {arm} in {pool} (선택 불가, A 8.2 item 6)")
    mps = [float(np.mean(_g(ctx, account(ctx, p, arm, size), mask_fn) - _g(ctx, account(ctx, p, "E0", size), mask_fn)))
           for p in ctx.pool_picks(pool)]
    return float(np.mean(mps))


# ====================================================================================================== week bootstrap (X-004, X-007)
class CI(tuple):
    """(lo, hi) with n_used and n_dropped (draws whose statistic is not finite, e.g. an empty bucket) and contains_zero."""

    def __new__(cls, lo: float, hi: float, n_used: int, n_dropped: int):
        t = super().__new__(cls, (lo, hi))
        t.n_used, t.n_dropped = n_used, n_dropped
        t.contains_zero = bool(lo <= 0 <= hi)
        return t


def lam_diff(draws: np.ndarray) -> np.ndarray:
    """The statistic of X-004 / X-007 on week aggregates laid out (week, bucket 0/1, [sum of l_i, count]): lam(1) - lam(0) with lam(b) =
    sum S / sum n; nan (dropped and counted) when a bucket is empty in a draw."""
    s = draws.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return s[:, 1, 0] / s[:, 1, 1] - s[:, 0, 0] / s[:, 0, 1]


def week_aggregates(t_ms, l, in_bucket, merge_first: bool = False) -> np.ndarray:
    """(N_WEEKS, 2, 2): per week of ``t_ms`` (t_sig) and bucket (in_bucket False / True) the sum of l_i and the count."""
    w = week_index(t_ms, merge_first)
    b = np.asarray(in_bucket, bool).astype(int)
    out = np.zeros((N_WEEKS, 2, 2))
    np.add.at(out, (w, b, 0), np.asarray(l, float))
    np.add.at(out, (w, b, 1), 1.0)
    return out


def week_bootstrap_ci(x_by_week, n: int = 2000, seed: int = 0, q=(0.025, 0.975), stat=None) -> CI:
    """Resample whole weeks with replacement ``n`` times (numpy default_rng(seed); seed by C11). ``x_by_week``: one row per week (any
    trailing shape). ``stat(draws)`` maps the (n, weeks, ...) resamples to n values (default: the mean over weeks of a 1-D x; for X-004's
    lam difference pass ``stat=lam_diff`` with week_aggregates). Returns CI(lo, hi) at the quantiles ``q`` (linear) of the finite values;
    the others are dropped and counted."""
    X = np.asarray(x_by_week, float)
    rng = np.random.default_rng(seed)
    draws = X[rng.integers(0, X.shape[0], size=(n, X.shape[0]))]
    v = draws.mean(axis=1) if stat is None else np.asarray(stat(draws), float)
    if v.shape != (n,):
        raise ValueError("the statistic must give one value per draw")
    ok = np.isfinite(v)
    lo, hi = (float(x) for x in np.quantile(v[ok], q)) if ok.any() else (float("nan"), float("nan"))
    return CI(lo, hi, int(ok.sum()), int((~ok).sum()))


# ====================================================================================================== C2 re-runs and reduced files
def mask_offered(off: dict, mask) -> dict:
    """C2: {k: v[mask] for k, v in off.items()}, every key, order kept; the cached table is not touched."""
    m = np.asarray(mask, bool)
    return {k: v[m] for k, v in off.items()}


def settings_copy(market, scale: float, changes: dict | None = None) -> np.ndarray:
    """C2: a copy of market.S(scale) with the stated entries {index: value} changed."""
    S = np.array(market.S(scale), dtype=float, copy=True)
    for i, v in (changes or {}).items():
        S[int(i)] = v
    return S


def rerun(ctx: Ctx, pdata, arm, scale: float = SIZE_Q, offered: dict | None = None, S: np.ndarray | None = None):
    """C2: only kernel_x.simulate(market, pdata, arm, scale, 'select', offered=..., S=...) of the pinned kernel (never real_config)."""
    v = KX.variant_by_id(arm) if isinstance(arm, str) else arm
    return KX.simulate(ctx.market, pdata, v, scale, "select", offered=offered, S=S)


def reduced_path(ctx: Ctx, pick, read: str, size: float, part: str | None = None) -> str:
    """C2: $WORK/<pin8>/extra/reduced/<read>/<pick>__<q25|q100>[__<part>].npz (DeepSeek under ds_private/extra/reduced/; reduced_r2 after an
    A select rerun)."""
    p = ctx.pick(pick)
    base = ctx.private_dir if p["pool"] == "ds" else ctx.work_extra
    name = f"{p['id']}__{RX.SIZE_TAG[size]}" + (f"__{part}" if part else "") + ".npz"
    path = os.path.join(base, "reduced_r2" if ctx.rerun else "reduced", read, name)
    if not _inside(path, base) or os.sep in read or read.startswith("."):
        raise Refused(f"reduced file outside its folder: {path}")
    return path


def save_reduced(ctx: Ctx, pick, read: str, size: float, doc: dict, part: str | None = None) -> str:
    path = reduced_path(ctx, pick, read, size, part)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part.npz"
    np.savez_compressed(tmp, **{k: np.asarray(v) for k, v in doc.items()})
    os.replace(tmp, path)
    return path


def load_reduced(ctx: Ctx, pick, read: str, size: float, part: str | None = None) -> dict:
    with np.load(reduced_path(ctx, pick, read, size, part)) as z:
        return {k: z[k] for k in z.files}


# ====================================================================================================== outputs
def _render(name: str, obj) -> str:
    if name.endswith(".json"):
        return json.dumps(obj, indent=1, ensure_ascii=False, default=RX._json_default) + "\n"
    if name.endswith(".csv") and not isinstance(obj, str):
        rows = list(obj)
        buf = io.StringIO()
        if rows and isinstance(rows[0], dict):
            cols = list(dict.fromkeys(k for r in rows for k in r))
            w = csv.DictWriter(buf, cols, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
        else:
            csv.writer(buf, lineterminator="\n").writerows(rows)
        return buf.getvalue()
    if name.endswith((".md", ".csv", ".svg", ".txt")) and isinstance(obj, str):
        return obj
    raise Refused(f"cannot write {name}: .json, .csv, .md, .svg or .txt (text as str)")


def _ds_rows(obj):
    """Every dict tagged pool == 'ds' (how the reads mark a DeepSeek row) anywhere in ``obj``."""
    if isinstance(obj, dict):
        if obj.get("pool") == "ds":
            yield obj
        for v in obj.values():
            yield from _ds_rows(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _ds_rows(v)


def committed_problems(name: str, obj, text: str) -> list:
    """What would stop a committed output: a DeepSeek row (pool == 'ds') outside the whitelist (C8), the A8 free-text tripwire (what
    runner_x.py audit-file checks), and on a Korean page C14."""
    bad = []
    for r in _ds_rows(obj if not isinstance(obj, str) else []):
        try:
            ds_row_check(r)
        except Refused as exc:
            bad.append(str(exc))
    free = "\n".join(MT.json_strings(obj)) if name.endswith(".json") else text
    bad += ["free text: " + ln[:60] for ln in MT.audit_text(free)]
    if name.endswith(".md"):
        bad += ["C14: " + ln[:60] for ln in c14_problems(text)]
    return bad


def _atomic(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(path + ".tmp", path)


def write_out(ctx: Ctx, name: str, obj, private: bool = False) -> str:
    """Write one output atomically and return its path. ``name`` is relative (e.g. 'extra_reads.json', 'figs/x.svg') and never starts with
    select, confirm, SELECT_KO or REPORT_KO. Committed (private False): to ctx.out_dir, after the checks of ``committed_problems``.
    Private (DeepSeek money): extra_reads_ds.json and owner_report_extra.md to $WORK/<pin8>/ds_private/, anything else to
    ctx.private_dir; never inside the repository."""
    parts = name.replace("\\", "/").split("/")
    if os.path.isabs(name) or ".." in parts or "" in parts:
        raise Refused(f"bad output name {name!r}")
    leaf = parts[-1]
    if leaf.lower().startswith(NEVER_OUT):
        raise Refused(f"an extra output is never named like a stage file: {leaf}")
    text = _render(leaf, obj)
    if private:
        path = os.path.join(ctx.ds_private_root if leaf in PRIVATE_ROOT else ctx.private_dir, *parts)
        if _inside(path, ctx.lay.root):
            raise Refused("a private file never lies inside the repository")
    else:
        path = os.path.join(ctx.out_dir, *parts)
        bad = committed_problems(leaf, obj, text)
        if bad:
            raise Refused(f"{name}: " + " | ".join(bad[:5]))
    _atomic(path, text)
    return path


_P_VALUE = re.compile(r"\bp\s*[=<>]|p값|p-value", re.I)


def private_report_problems(ctx: Ctx, path: str) -> list:
    """A8 (3) on the private extra report (made by the extra file's code, E.1 item 5): it exists outside the repository, git tracks no
    owner_report file, it holds no p value, its last line asks the owners to name variants by id, and no line of 20 or more characters
    with a letter, digit or Hangul equals a line of a committed extra output. [] = pass."""
    if not os.path.exists(path):
        return ["missing"]
    bad = []
    if _inside(path, ctx.lay.root):
        bad.append("inside the repository")
    text = open(path, encoding="utf-8").read()
    if _P_VALUE.search(text):
        bad.append("p value")
    if not text.strip() or text.strip().splitlines()[-1].strip() != RX.OWNER_REPORT_LAST_LINE:
        bad.append("last line")
    lines = set()
    for d, _dn, fs in os.walk(ctx.out_dir):
        for f in fs:
            try:
                lines |= {ln.strip() for ln in open(os.path.join(d, f), encoding="utf-8").read().splitlines()}
            except (UnicodeDecodeError, OSError):
                pass
    if any(len(ln.strip()) >= 20 and re.search(r"[0-9A-Za-z가-힣]", ln) and ln.strip() in lines for ln in text.splitlines()):
        bad.append("a line equals a line of a committed file")
    try:
        r = subprocess.run(["git", "-C", ctx.lay.root, "ls-files"], capture_output=True, text=True, timeout=60)
        if any("owner_report_" in t for t in r.stdout.splitlines()):
            bad.append("git tracks an owner_report file")
    except Exception:  # noqa: BLE001
        pass
    return bad


def write_owner_report_extra(ctx: Ctx, body_md: str, twins_md_path: str | None = None) -> str:
    """The single writer of $WORK/<pin8>/ds_private/owner_report_extra.md (E.1 item 5, TW.6): ``body_md`` (part 핵심 first, then 부록; E0,
    H and choosable rows only, committed row order, no p value), the twins' private section verbatim, and runner_x.OWNER_REPORT_LAST_LINE
    last. It must pass ``private_report_problems``. Returns its sha256, which the caller records in a committed file of extra/out/ (and the
    main session in sent.json) before the file is shown."""
    text = body_md.rstrip("\n") + "\n\n"
    if twins_md_path:
        text += open(twins_md_path, encoding="utf-8").read().rstrip("\n") + "\n\n"
    path = write_out(ctx, "owner_report_extra_r2.md" if ctx.rerun else "owner_report_extra.md", text + RX.OWNER_REPORT_LAST_LINE + "\n",
                     private=True)
    bad = private_report_problems(ctx, path)
    if bad:
        raise Refused("owner_report_extra.md fails A8 (3): " + ", ".join(bad))
    return RX.sha256_file(path)


# ====================================================================================================== E.5 run record, disk and cap
CAP_MINUTES = 45                        # E.5: projected wall time above which parts are dropped, in this order (never the twins or tier A)
CAP_DROP_ORDER = ("X-022 fixed leverage", "X-041 c = 1.5", "X-043 live size", "X-023 and X-044 on every second Monday (72 starts)", "X-002",
                  "X-022 entirely")
GB = 1_000_000_000
DISK_NEED_DEFAULT = 1.0 * GB            # E.5: the stage refuses to start with less than 1.5 GB free (need + 0.5 GB)
DISK_MARGIN = 0.5 * GB
DISK_STOP = 1.0 * GB                    # E.5: stop when the bytes about to be written would leave less than 1 GB


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class RunRecord(dict):
    """The E.5 run record (extra_reads.json, field run): stage, start and end UTC, HEAD, pin8, the extra pin, need and free bytes, and per
    read or twin {seconds, accounts, bytes, dropped}; ``dropped`` (cap drops) and ``dropped_at_o8``. Use as a context manager or call
    finish()."""

    def __init__(self, ctx: Ctx, **kw):
        super().__init__(**kw)
        self._ctx, self._t0 = ctx, time.time()

    def part(self, name: str, **fields) -> dict:
        self["parts"][name] = dict(fields)
        return self["parts"][name]

    def check_disk(self, bytes_next: float = 0.0) -> None:
        free = shutil.disk_usage(self._ctx.work).free
        if free - bytes_next < DISK_STOP:
            raise Refused(f"disk: writing {bytes_next / GB:.2f} GB would leave less than {DISK_STOP / GB:.1f} GB free under $WORK")

    def finish(self) -> "RunRecord":
        self["end_utc"] = _utc_now()
        self["seconds"] = round(time.time() - self._t0, 1)
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.finish()
        return False


def run_record(ctx: Ctx, stage: str, extra: dict) -> RunRecord:
    """Start the E.5 run record of ``stage``: refuse when the free disk under $WORK is less than need + 0.5 GB (need = extra['need_bytes'],
    default 1 GB, so 1.5 GB at the start), then record start UTC, HEAD, pin8 and the extra pin; ``extra``'s fields are kept."""
    need = float(extra.get("need_bytes", DISK_NEED_DEFAULT))
    free = shutil.disk_usage(ctx.work).free
    if free < need + DISK_MARGIN:
        raise Refused(f"disk: {free / GB:.2f} GB free under $WORK, need {need / GB:.2f} + {DISK_MARGIN / GB:.1f} GB")
    xs = extra_sha_file(ctx.lay)
    return RunRecord(ctx, **{"stage": stage, "start_utc": _utc_now(), "end_utc": None, "head": RX.git_head(ctx.lay.root), "pin8": ctx.pin8,
                             "extra_pin8": RX.sha256_file(xs)[:8] if os.path.exists(xs) else None, "need_bytes": need,
                             "free_bytes_start": int(free), "parts": {}, "dropped": [], "dropped_at_o8": [], **extra})
