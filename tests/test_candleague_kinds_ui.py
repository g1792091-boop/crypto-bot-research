"""candleague 메인 vs 대조 / 목표 진척도 / 청산 이유 (js/screens/versus.js, goal.js, reasons.js, static/scr/kinds.css) and the 찾기 entries.

The three screens are mounted for real under node on the DOM stand-in of test_candleague_rank_ui (text nodes only, like the
browser's) with hand-made snapshots whose ``kinds`` / ``pairs`` follow candleague.summary.kinds_summary / pairs_summary and whose
lineup labels are read from candleague/data/rules_owner_exits.json (counts of kinds and of 메인 kinds come from the data, none is
written here). The tests read what reached the page:
  (a) full data: the one-sentence verdict (and its 300-trade gate with the bar), the table with the best 메인 per column starred, the
      gap to the 대조 with ▲▼ words, the coin-flip row, the goal cards with their words and sample notes, the reason bars, the
      counts and mean ROE per reason, the pair sentence, the narrowed count; the card view;
  (b) kinds absent (the lineup is there): "데이터 준비 중";   (c) the old league (no lineup, no kinds): the note for the new league;
  (d) null ROE / money fields (DeepSeek money hidden) and a kind with no trade: "—", never 0, NaN or null;
  (e) equity0 1000: the text says $1,000 and never $5,000 (and no dollar figure is made up without equity0).
Plus the static rules (text only, tokens only, scoped css, the menu, the screens' files) and 찾기."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

import test_candleague_rank_ui as RANK  # noqa: E402  (its DOM stand-in)

STATIC = os.path.join(ROOT, "candleague", "static")
NEW_JS = ["screens/versus.js", "screens/goal.js", "screens/reasons.js"]
DAY = 86_400_000
NOW = 1_791_900_000_000
OWNER = json.load(open(os.path.join(ROOT, "candleague", "data", "rules_owner_exits.json"), encoding="utf-8"))["owner_exits"]
REASONS = ("SL", "LOCK", "RULE", "TP", "LIQ")
HOOKS = {"kd-root", "kd-row", "kd-read", "kd-rule", "kd-gcard", "kd-lcard", "kd-rcard"}       # class names with no rule of their own (tests, wrappers)


# ---------------------------------------------------------------- hand-made snapshots
def _group(label: str) -> str:
    return "main" if label.startswith("메인") else "control" if label.startswith("대조") else "research"


def _role(e: dict) -> str:
    own = not e.get("rule") and not e.get("exit") and not e.get("weekend_off") and not e.get("coin_of")
    return "cand" if own else e["suffix"][1:]


# numbers of the kinds the tests read (everything else gets a plain default). ROE values are fractions (0.1 = +10%).
STATS = {
    "fq": dict(accounts=38, trades=120, wins=80, win=0.12, loss=-0.08, mean=0.0467, hold=5.5, tpd=12.0, wr=0.05, dd=0.06,
               reasons=dict(SL=30, LOCK=40, RULE=35, TP=15, LIQ=0), rm=dict(SL=-0.09, LOCK=0.03, RULE=0.08, TP=0.15, LIQ=None), narrowed=0),
    "nv": dict(accounts=38, trades=100, wins=58, win=0.10, loss=-0.07, mean=0.031, hold=7.0, tpd=9.5, wr=0.03, dd=0.07,
               reasons=dict(SL=20, LOCK=30, RULE=40, TP=10, LIQ=0), rm=dict(SL=-0.08, LOCK=0.02, RULE=0.05, TP=0.14, LIQ=None), narrowed=0),
    "sw": dict(accounts=49, trades=210, wins=100, win=0.09, loss=-0.07, mean=0.012, hold=9.0, tpd=21.0, wr=0.01, dd=0.11,
               reasons=dict(SL=60, LOCK=50, RULE=80, TP=20, LIQ=0), rm=dict(SL=-0.07, LOCK=0.01, RULE=0.02, TP=0.12, LIQ=None), narrowed=0),
    "tg": dict(accounts=38, trades=90, wins=50, win=0.11, loss=-0.06, mean=0.02, hold=6.0, tpd=9.0, wr=0.02, dd=0.05,
               reasons=dict(SL=30, LOCK=25, RULE=20, TP=15, LIQ=0), rm=dict(SL=-0.06, LOCK=0.02, RULE=0.04, TP=0.13, LIQ=None), narrowed=17),
    "ld": dict(accounts=49, trades=140, wins=70, win=0.10, loss=-0.07, mean=0.021, hold=8.0, tpd=14.0, wr=0.02, dd=0.08,
               reasons=dict(SL=50, LOCK=60, RULE=0, TP=30, LIQ=0), rm=dict(SL=-0.07, LOCK=0.02, RULE=None, TP=0.11, LIQ=None), narrowed=0),
    "ldc": dict(accounts=49, trades=130, wins=60, win=0.09, loss=-0.07, mean=-0.004, hold=8.0, tpd=13.0, wr=-0.01, dd=0.1,
                reasons=dict(SL=50, LOCK=50, RULE=0, TP=30, LIQ=0), rm=dict(SL=-0.07, LOCK=0.01, RULE=None, TP=0.1, LIQ=None), narrowed=0),
}


def _kinds(scale: float = 1.0, equity_ok: bool = True) -> tuple[list, list]:
    """(lineup, kinds) of the owner-exit league's file, the way the engine writes them."""
    lineup, kinds = [], []
    for i, e in enumerate(OWNER):
        role, group = _role(e), _group(e["label_ko"])
        short = e["label_ko"].split("·", 1)[-1].strip() if i % 2 else None            # a short name for every other kind
        lineup.append({"role": role, "suffix": e["suffix"], "label_ko": e["label_ko"], "short_ko": short or e["label_ko"],
                       "desc_ko": "", "why_ko": "", "size": 1.0, "accounts": STATS.get(role, {}).get("accounts", 49)})
        s = STATS.get(role)
        if s is None:
            s = dict(accounts=49, trades=60 + i, wins=30, win=0.1, loss=-0.07, mean=0.005, hold=8.0, tpd=6.0, wr=0.0, dd=0.09,
                     reasons=dict(SL=30, LOCK=20, RULE=0, TP=10 + i, LIQ=0), rm=dict(SL=-0.07, LOCK=0.02, RULE=None, TP=0.1, LIQ=None), narrowed=0)
        n = int(s["trades"] * scale)
        mult = n / s["trades"]
        reasons = {k: int(v * mult) for k, v in s["reasons"].items()}
        kinds.append({
            "role": role, "suffix": e["suffix"], "label_ko": e["label_ko"], "short_ko": short, "group": group, "accounts": s["accounts"],
            "picks": s["accounts"], "trades": n, "wins": int(s["wins"] * mult), "win_rate": s["wins"] / s["trades"], "avg_win_roe": s["win"],
            "avg_loss_roe": s["loss"], "payoff": s["win"] / abs(s["loss"]), "mean_roe": s["mean"], "median_hold_h": s["hold"],
            "trades_per_day": s["tpd"] * mult, "reasons": reasons, "reason_mean_roe": dict(s["rm"]), "narrowed_n": int(s["narrowed"] * mult),
            "open_now": 3, "wallet_return_pct": s["wr"], "max_dd_mean": s["dd"], "best_pick": "core-X-1h-1", "worst_pick": "core-Y-1h-2",
            "ds_in_roe": False})
    return lineup, kinds


def _pairs() -> dict:
    return {"control": "-ld", "by_role": {
        "fq": {"n": 100, "n_shown": 100, "better": 55, "worse": 30, "same": 15, "mean_diff_roe": 0.0123, "sum_diff_pct_of_wallet": 0.4, "pct_better": 0.55},
        "sw": {"n": 40, "n_shown": 0, "better": None, "worse": None, "same": None, "mean_diff_roe": None, "sum_diff_pct_of_wallet": None, "pct_better": None}},
        "recent": [{"pick": "core-X-1h-1", "role": "fq", "a_reason": "RULE", "a_roe": 0.08, "b_reason": "SL", "b_roe": -0.05, "diff_roe": 0.13},
                   {"pick": "core-Y-1h-2", "role": "fq", "a_reason": "SL", "a_roe": -0.08, "b_reason": "SL", "b_roe": -0.08, "diff_roe": 0.0}]}


def _doc(scale: float = 1.0, days: float = 10.0, equity0=1000, kinds: bool = True, lineup: bool = True, pairs: bool = True) -> dict:
    lu, ks = _kinds(scale)
    accounts = [{"id": f"core-X-1h-1{k['suffix']}", "role": k["role"], "kind": "core", "name": "X", "tf": "1h", "trades": k["trades"],
                 "wins": k["wins"], "mean_ret": k["mean_roe"], "wallet": 1000.0, "max_dd": k["max_dd_mean"], "bust": False, "open": None}
                for k in ks]
    d = {"generated_ms": NOW - 60_000, "done_ms": NOW, "start_ms": NOW - int(days * DAY), "started_ms": NOW - int(days * DAY),
         "accounts": accounts, "judge": {}, "ds_money": False, "watch": {"checkpoints": [], "pools": {}}}
    if equity0 is not None:
        d["equity0"] = equity0
    if lineup:
        d["lineup"] = lu
    if kinds:
        d["kinds"] = ks
    if pairs and kinds:
        d["pairs"] = _pairs()
    return d


# ---------------------------------------------------------------- the node runner
RUNNER = r"""
import {readFileSync} from "node:fs";
import {install, txt} from "./shim.mjs";
const cfg = JSON.parse(readFileSync(process.argv[2], "utf8"));
install(cfg);
globalThis.location.hash = "";
const S = cfg.static;
const LK = await import(`file://${S}/js/lk.js`);
const doc = cfg.doc;
if (doc) LK.setLeague(doc);
const M = await import(`file://${S}/js/screens/${cfg.screen}.js`);
const el = document.createElement("div");
el.dataset.screen = cfg.screen;
document.body.appendChild(el);
const ctx = {params: {name: cfg.screen, arg: null, query: {}}, alive: () => true, signal: null,
  api: async (p) => (await globalThis.fetch(p)).json(), meta: () => LK.getMeta(),
  onLeague: (fn) => { if (doc) fn(doc); }, onLive: () => () => {}, onPositions: () => () => {},
  every: () => {}, css: async () => null, wide() {}, setTitle() {}, setQuery() {},
  href: (n, a) => `#/${n}${a ? "/" + a : ""}`};
await M.mount(el, ctx);
for (let i = 0; i < 4; i++) await new Promise((r) => setTimeout(r, 10));
const out = {text: txt(el), css: M.css, cls: el.className, sel: {}};
for (const [k, sel] of Object.entries(cfg.sels || {})) out.sel[k] = el.querySelectorAll(sel).map((n) => ({t: txt(n), d: {...n.dataset}, c: n.className}));
out.rows = el.querySelectorAll(".kd-row").map((r) => r.querySelectorAll("td").map(txt));
console.log(JSON.stringify(out));
process.exit(0);
"""


def _run(tmp_path, screen: str, doc, sels=None, local=None) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    (tmp_path / "shim.mjs").write_text(RANK.SHIM)
    (tmp_path / "run.mjs").write_text(RUNNER)
    cfg = {"static": STATIC, "routes": {}, "local": local or {}, "screen": screen, "doc": doc, "sels": sels or {}}
    (tmp_path / "cfg.json").write_text(json.dumps(cfg, ensure_ascii=False))
    r = subprocess.run([node, str(tmp_path / "run.mjs"), str(tmp_path / "cfg.json")], capture_output=True, text=True, timeout=120, cwd=str(tmp_path))
    assert r.returncode == 0, (r.stdout[-600:], r.stderr[-2000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


SCREENS = ("versus", "goal", "reasons")
BAD = ("NaN", "undefined", "null", "Infinity")


def _no_junk(text: str) -> None:
    for bad in BAD:
        assert bad not in text, bad


# ---------------------------------------------------------------- (a) full data
def test_versus_verdict_gate_table_and_best_marks(tmp_path):
    lu, ks = _kinds()
    main = [k for k in ks if k["group"] == "main"]
    ld = next(k for k in ks if k["role"] == "ld")
    up = sum(1 for k in main if k["mean_roe"] > ld["mean_roe"])
    n_min = min(k["trades"] for k in main + [ld])
    assert len(main) == 4 and sum(1 for k in ks if k["group"] == "research") >= 1            # the file's lineup: four 메인 kinds
    o = _run(tmp_path, "versus", _doc(), sels={"hero": ".kd-hero", "bestrow": "tr.kd-main td.kd-best", "best": "td.kd-best", "grp": "tr.kd-grp",
                                                "prog": ".kd-hero .dl-progbar", "coin": ".kd-coin", "live": "tr.kd-live"})
    page, hero = o["text"], o["sel"]["hero"][0]["t"]
    assert o["css"] == "scr/kinds.css" and "kd" in o["cls"].split()
    # the 300-trade gate says so clearly, with the smallest kind's count, and the progress bar
    assert f"아직 판정하기엔 거래가 적습니다 (종류마다 300건 필요, 지금 {n_min}건)" in hero
    assert f"참고로 지금까지는 메인 {len(main)}개 중 {up}개가 대조보다 거래당 순수익이 높습니다" in hero
    assert len(o["sel"]["prog"]) == 1 and f"{n_min} / 300건" in hero
    assert "방향 실력 확인" in hero and "동전 던지기" in hero
    # nothing hard-coded from the old lineup
    for stale in ("메인 5", "5가지", "906", "다섯 가지"):
        assert stale not in page, stale
    # the table: a row per kind in the lineup's order, three groups, the live candidate marked, the coin row labelled
    assert len(o["rows"]) == len(ks) and len(o["sel"]["grp"]) == 3
    names = [r[0] for r in o["rows"]]
    assert "실전 후보" in names[0] and "-fq" in names[0] and "38개 매매법" in names[0]
    coin_rows = [r[0] for r in o["rows"] if "-ldc" in r[0]]
    assert len(coin_rows) == 1 and "방향 실력 확인용: 진입 방향을 동전으로 정한 짝" in coin_rows[0]
    assert len(o["sel"]["live"]) == 1
    fq, tg = o["rows"][0], o["rows"][3]
    ldrow = next(r for r in o["rows"] if "-ld ·" in r[0])
    assert len(fq) == 11 and fq[1] == "120건" and fq[2].startswith("★ 66.7%")
    # the best 메인 per column is starred (only 메인 rows), with the gap to the 대조 as ▲▼ and a word
    assert fq[6].startswith("★ +4.7%") and "▲ +2.6%p 높음" in fq[6]
    assert len(o["sel"]["best"]) == len(o["sel"]["bestrow"]) >= 6
    assert tg[9].startswith("★ 5.0%") and "▼ −3.0%p 낮음" in tg[9] and not fq[9].startswith("★")      # 낙폭: the lowest is the best
    assert ldrow[6] == "+2.1%" and ldrow[1] == "140건"                                                   # the 대조 has no gap to itself
    assert "★" not in "".join(ldrow)
    assert "$1,000 대비" in page and "$5,000" not in page
    # the reading guide, the coin box and the decision rule
    for need in ("이렇게 읽으세요", "어떻게 고르나요", "300건", "거래당 순수익이 높은 것을 먼저", "낙폭이 낮은 것", "승률만 보고 고르지 않습니다", "동전 던지기 짝을 못 이기면"):
        assert need in page, need
    # kinds that exist for fewer picks than the 대조 are said so, from the data
    assert "같은 매매법끼리가 아닙니다" in page and "38개" in page and "49개" in page
    _no_junk(page)


def test_versus_enough_trades_gives_the_comparison_sentence_and_the_card_view(tmp_path):
    lu, ks = _kinds(scale=4.0)
    main = [k for k in ks if k["group"] == "main"]
    ld = next(k for k in ks if k["role"] == "ld")
    up = sum(1 for k in main if k["mean_roe"] > ld["mean_roe"])
    assert min(k["trades"] for k in main + [ld]) >= 300
    o = _run(tmp_path, "versus", _doc(scale=4.0), sels={"hero": ".kd-hero .dl-vbig"})
    big = o["sel"]["hero"][0]["t"]
    assert big == f"메인 {len(main)}개 중 {up}개가 대조보다 거래당 순수익이 높습니다"
    assert "아직 판정하기엔" not in o["text"] and "가장 높은 메인은" in o["text"]
    # the coin twin below the 대조 reads as a warning sentence
    d = _doc(scale=4.0)
    next(k for k in d["kinds"] if k["role"] == "ldc")["mean_roe"] = 0.03
    o = _run(tmp_path, "versus", d)
    assert "이기지 못했습니다" in o["text"] and "진입에 실력이 없다는 뜻" in o["text"]
    # the card view (a phone's default; remembered per device): one card per kind, the 연구용 ones behind a button
    o = _run(tmp_path, "versus", _doc(), local={"cl-versus-view": json.dumps("card")}, sels={"cards": ".kd-kcard", "rows": ".kd-row"})
    assert len(o["sel"]["cards"]) == len(ks) and not o["sel"]["rows"]
    assert "대조보다" in o["text"] and "더 좋음" in o["text"] and "연구용" in o["text"]
    _no_junk(o["text"])


def test_nothing_judged_before_the_first_trade(tmp_path):
    d = _doc()
    for k in d["kinds"]:
        k.update(trades=0, wins=0, win_rate=None, avg_win_roe=None, avg_loss_roe=None, payoff=None, mean_roe=None, median_hold_h=None,
                 trades_per_day=None, wallet_return_pct=None, max_dd_mean=None, reasons=dict.fromkeys(REASONS, 0),
                 reason_mean_roe=dict.fromkeys(REASONS), narrowed_n=0)
    for name in SCREENS:
        o = _run(tmp_path, name, d)
        assert "아직 거래가 없습니다" in o["text"], name
        _no_junk(o["text"])
    o = _run(tmp_path, "versus", d)
    assert "(종류마다 300건 필요, 지금 0건)" in o["text"] and all("거래 없음" in " ".join(r[2:7]) for r in o["rows"])


# ---------------------------------------------------------------- goal cards
def test_goal_cards_words_targets_and_sample_notes(tmp_path):
    o = _run(tmp_path, "goal", _doc(), sels={"cells": ".kd-gcell", "cards": ".kd-gcard", "bars": ".kd-gbar", "ticks": ".kd-tick"})
    cell = {(c["d"].get("goal"), c["d"].get("role")): c["t"] for c in o["sel"]["cells"] if c["d"].get("goal")}
    assert len(o["sel"]["cards"]) == 5 and len(cell) == 10                                   # five goals x (실전 후보, 대조)
    for need in ("승률", "70%", "하루 진입 수", "1번 이상", "3번", "거래당 순수익", "+10%", "한 달 환산 수익률", "x4 (+300%)", "낙폭", "대조보다 낮게"):
        assert need in o["text"], need
    win = cell[("win", "fq")]
    assert "66.7%" in win and "가까움" in win and "이긴 거래 80건 / 거래 120건" in win               # 60% to 70% = 가까움
    tpd = cell[("tpd", "fq")]
    assert "12.0번" in tpd and "달성" in tpd and "이상 목표 3번도 넘었습니다" in tpd
    assert "이 종류는 38개 매매법만 돌아서 대조(49개)보다 적게 나올 수 있습니다" in tpd
    roe = cell[("roe", "fq")]
    assert "+4.7%" in roe and "멀다" in roe
    month = cell[("month", "fq")]                                                            # 10 days, +5.0%: 1.05 ** 3 = x1.16
    assert "x1.16" in month and "+16%" in month and "멀다" in month and "$1,000 대비" in month
    dd = cell[("dd", "fq")]
    assert "6.0%" in dd and "대조는 8.0%" in dd and "달성" in dd
    assert "기준" in cell[("dd", "ld")] and "달성" not in cell[("dd", "ld")]
    assert "$5,000" not in o["text"] and "약속하지 않습니다" in o["text"]
    # 120 trades: no small-sample line; 20 trades: nothing is judged; 60: a line that says it may be luck
    assert "뿐이라" not in cell[("win", "fq")]
    d = _doc()
    fq = next(k for k in d["kinds"] if k["role"] == "fq")
    fq.update(trades=20, wins=18, win_rate=0.9)
    o = _run(tmp_path, "goal", d, sels={"cells": ".kd-gcell"})
    cell = {(c["d"].get("goal"), c["d"].get("role")): c["t"] for c in o["sel"]["cells"] if c["d"].get("goal")}
    assert "90.0%" in cell[("win", "fq")] and "아직 몰라요" in cell[("win", "fq")] and "거래가 20건뿐이라 아직 믿기 어렵습니다" in cell[("win", "fq")]
    assert "아직 판단하기 이릅니다" in o["text"]
    fq.update(trades=60, wins=45, win_rate=0.75)
    o = _run(tmp_path, "goal", d, sels={"cells": ".kd-gcell"})
    cell = {(c["d"].get("goal"), c["d"].get("role")): c["t"] for c in o["sel"]["cells"] if c["d"].get("goal")}
    assert "달성" in cell[("win", "fq")] and "거래가 60건뿐이라 운일 수 있습니다" in cell[("win", "fq")]


def test_goal_month_projection_waits_for_seven_days(tmp_path):
    o = _run(tmp_path, "goal", _doc(days=3.0), sels={"cells": ".kd-gcell"})
    cell = {(c["d"].get("goal"), c["d"].get("role")): c["t"] for c in o["sel"]["cells"] if c["d"].get("goal")}
    assert "7일 뒤부터" in cell[("month", "fq")] and "7일 뒤부터" in cell[("month", "ld")] and "x1." not in cell[("month", "fq")]
    assert "아직 몰라요" in cell[("month", "fq")]
    o = _run(tmp_path, "goal", _doc(days=7.0), sels={"cells": ".kd-gcell"})
    cell = {(c["d"].get("goal"), c["d"].get("role")): c["t"] for c in o["sel"]["cells"] if c["d"].get("goal")}
    assert "7일 뒤부터" not in cell[("month", "fq")] and "x1.23" in cell[("month", "fq")]         # 1.05 ** (30 / 7)
    # no 실전 후보 kind in the snapshot (it may not exist for every strategy): the 대조 still shows, the page says so
    d = _doc()
    d["kinds"] = [k for k in d["kinds"] if k["role"] != "fq"]
    o = _run(tmp_path, "goal", d, sels={"cells": ".kd-gcell"})
    assert "실전 후보 계좌가 아직 기록에 없습니다" in o["text"] and "이 종류 계좌가 기록에 없습니다" in o["text"]
    _no_junk(o["text"])


# ---------------------------------------------------------------- reasons
def test_reasons_bars_counts_means_pairs_and_narrowed(tmp_path):
    o = _run(tmp_path, "reasons", _doc(), sels={"blocks": ".kd-rblock", "segs": ".kd-rblock[data-role=\"fq\"] .kd-seg",
                                               "bars": ".kd-rbar", "legend": ".kd-lcard dt"})
    blocks = {b["d"]["role"]: b["t"] for b in o["sel"]["blocks"]}
    assert len(blocks) == len(_kinds()[1])
    fq = blocks["fq"]
    # 120 trades: 손절 30 (25%) · 계단 잠금 40 (33%) · 규칙 청산 35 (29%) · 익절 15 (13%) · 청산당함 0, each with its mean ROE
    for need in ("끝난 거래 120건", "손절", "30건", "25%", "평균 −9.0%", "계단 잠금", "40건", "33%", "평균 +3.0%", "규칙 청산", "35건", "29%", "평균 +8.0%",
                 "익절", "15건", "13%", "평균 +15.0%", "청산당함", "0건", "평균 —"):
        assert need in fq, need
    assert len(o["sel"]["segs"]) == 4                                                     # the zero-count 청산당함 has no segment
    # the pair sentence of a 메인 kind, only because doc.pairs has data for it
    assert "규칙 청산 35건의 평균은 +8.0%, 같은 신호의 대조는 −5.0% (최근 짝 1건 기준)." in fq
    assert "짝 100건" in fq and "더 나은 거래 55건" in fq and "못한 거래 30건" in fq and "같은 거래 15건" in fq and "+1.2%p" in fq
    assert "짝지어" not in blocks["nv"] and "짝지어" not in blocks["ld"]                    # no pairs row for these: no sentence
    assert "딥시크 금액이 숨김" in blocks["sw"]                                              # pairs counted but no ROE shown
    assert "손절을 중간에 좁힌 거래: 17건" in blocks["tg"] and "좁힌" not in blocks["fq"]
    # the legend explains each reason in plain words
    assert len(o["sel"]["legend"]) == 5
    for need in ("손절 (SL)", "계단 잠금 (LOCK)", "규칙 청산 (RULE)", "익절 (TP)", "청산당함 (LIQ)", "구조가 무너짐", "스위칭", "강제로 닫음", "잠가"):
        assert need in o["text"], need
    assert "청산당함 있음" not in o["text"]
    _no_junk(o["text"])
    # a 청산당함 anywhere is called out first
    d = _doc()
    next(k for k in d["kinds"] if k["role"] == "fq")["reasons"]["LIQ"] = 2
    o = _run(tmp_path, "reasons", d)
    assert "청산당함 있음" in o["text"] and "가장 먼저 확인하세요" in o["text"]
    # without doc.pairs there is no pair sentence anywhere
    o = _run(tmp_path, "reasons", _doc(pairs=False))
    assert "짝지어" not in o["text"] and "같은 신호의 대조는" not in o["text"]
    # a 손절 좁힘 kind with none narrowed says so
    d = _doc()
    next(k for k in d["kinds"] if k["role"] == "tg")["narrowed_n"] = 0
    o = _run(tmp_path, "reasons", d)
    assert "손절을 중간에 좁힌 거래가 아직 0건입니다" in o["text"]


# ---------------------------------------------------------------- (b) (c) the other states
def test_kinds_absent_and_old_league(tmp_path):
    for name in SCREENS:
        o = _run(tmp_path, name, _doc(kinds=False, pairs=False))                       # the new league, the engine has not written kinds yet
        assert "데이터 준비 중" in o["text"] and "아직 거래가 없습니다" in o["text"], name
        assert "새 리그용 화면" not in o["text"]
        o = _run(tmp_path, name, _doc(kinds=False, lineup=False, pairs=False))         # the old league
        assert "새 리그용 화면" in o["text"] and "새 리그" in o["text"] and "순위표" in o["text"], name
        assert "데이터 준비 중" not in o["text"]
        o = _run(tmp_path, name, None)                                                # no snapshot yet
        assert "준비 중" in o["text"], name
        d = _doc()
        d["kinds"] = []
        o = _run(tmp_path, name, d)                                                   # an empty list is the same as absent
        assert "데이터 준비 중" in o["text"], name
        for text in (o["text"],):
            _no_junk(text)


# ---------------------------------------------------------------- (d) null ROE fields
def test_null_fields_read_as_dashes_never_zero(tmp_path):
    d = _doc()
    for k in d["kinds"]:
        k.update(avg_win_roe=None, avg_loss_roe=None, payoff=None, mean_roe=None, wallet_return_pct=None, max_dd_mean=None,
                 reason_mean_roe=dict.fromkeys(REASONS), best_pick=None, worst_pick=None, ds_in_roe=False)
    d["kinds"][1].update(trades=0, wins=0, win_rate=None, median_hold_h=None, trades_per_day=None, reasons=dict.fromkeys(REASONS, 0))
    o = _run(tmp_path, "versus", d, sels={"cells": ".kd-row"})
    _no_junk(o["text"])
    fq, empty = o["rows"][0], o["rows"][1]
    assert fq[3] == fq[4] == fq[5] == fq[6] == fq[9] == fq[10] == "—"                    # avg win / loss, payoff, net per trade, 낙폭, 잔고: dashes
    assert fq[1] == "120건" and "66.7%" in fq[2]                                          # counts and the win rate stay
    assert all(c in ("—", "거래 없음") or c.startswith("0") for c in empty[2:9]) and "거래 없음" in empty[3]
    assert not any("%p" in c or "▲" in c or "▼" in c for c in fq[3:7] + fq[9:])           # no gap against nothing
    assert "0.0%" not in "".join(fq[3:7]) and "+0.0%" not in o["text"]
    assert "딥시크를 뺀 숫자" in o["text"]                                                  # the ROE figures say DeepSeek is left out
    assert "x" not in "".join(fq[3:7])
    # the hero does not call a comparison it cannot make
    assert "대조 계좌에 아직 거래가 없어" in o["text"] or "대조와 비교할 거래가 아직 없습니다" in o["text"]
    o = _run(tmp_path, "goal", d, sels={"cells": ".kd-gcell"})
    cell = {(c["d"].get("goal"), c["d"].get("role")): c["t"] for c in o["sel"]["cells"] if c["d"].get("goal")}
    _no_junk(o["text"])
    assert "—" in cell[("roe", "fq")] and "아직 몰라요" in cell[("roe", "fq")] and "아직 몰라요" in cell[("dd", "fq")] and "아직 몰라요" in cell[("month", "fq")]
    assert "잔고 수익률이 아직 없습니다" in cell[("month", "fq")]
    o = _run(tmp_path, "reasons", d, sels={"blocks": ".kd-rblock"})
    _no_junk(o["text"])
    fqb = next(b["t"] for b in o["sel"]["blocks"])
    assert "평균 —" in fqb and "평균 0" not in fqb and "평균 +0" not in fqb
    assert "규칙 청산 35건의 평균은" not in o["text"]                                       # no mean, no sentence about it


# ---------------------------------------------------------------- (e) the start wallet
def test_start_wallet_is_1000_never_5000(tmp_path):
    for name in SCREENS:
        o = _run(tmp_path, name, _doc(equity0=1000))
        assert "$5,000" not in o["text"] and "5,000" not in o["text"], name
    assert "$1,000" in _run(tmp_path, "versus", _doc(equity0=1000))["text"]
    assert "$1,000" in _run(tmp_path, "goal", _doc(equity0=1000))["text"]
    # a snapshot without equity0 never gets a made-up dollar figure
    for name in SCREENS:
        o = _run(tmp_path, name, _doc(equity0=None))
        assert "$" not in o["text"], name
    assert "시작 잔고 대비" in _run(tmp_path, "versus", _doc(equity0=None))["text"]


# ---------------------------------------------------------------- 찾기 and the shell
def test_find_knows_the_screens_and_the_kinds(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    (tmp_path / "shim.mjs").write_text(RANK.SHIM)
    (tmp_path / "run.mjs").write_text(r"""
import {readFileSync} from "node:fs";
import {install} from "./shim.mjs";
const cfg = JSON.parse(readFileSync(process.argv[2], "utf8"));
install(cfg);
const S = cfg.static;
const LK = await import(`file://${S}/js/lk.js`);
const F = await import(`file://${S}/js/find.js`);
LK.setLeague(cfg.doc);
F.setFindScreens([["check", "점검 진행"], ["versus", "메인 vs 대조"], ["goal", "목표 진척도"], ["reasons", "청산 이유"]]
  .map(([id, ko]) => ({id, ko, group: "home", groupKo: "홈", title: ko})));
const q = (s) => F.search(s).map((x) => [x.kind, x.id, x.href, x.label]);
console.log(JSON.stringify({all: q(""), goal: q("목표"), eng: q("versus"), reason: q("청산"), init: q("ㅁㅇ"), kind: q("스위칭"), loss: q("손절"), none: q("zzzz")}));
process.exit(0);
""")
    (tmp_path / "cfg.json").write_text(json.dumps({"static": STATIC, "routes": {}, "local": {}, "doc": _doc()}, ensure_ascii=False))
    r = subprocess.run([node, str(tmp_path / "run.mjs"), str(tmp_path / "cfg.json")], capture_output=True, text=True, timeout=60, cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr[-1500:]
    o = json.loads(r.stdout.strip().splitlines()[-1])
    ids = lambda key: [x[1] for x in o[key] if x[0] == "screen"]  # noqa: E731
    assert ids("all") == ["check", "versus", "goal", "reasons"]
    assert ids("goal") == ["goal"] and ids("eng") == ["versus"] and "reasons" in ids("reason") and "reasons" in ids("loss") and "versus" in ids("init")
    kinds = [x for x in o["kind"] if x[0] == "kind"]
    assert kinds and all(x[2] == "#/versus" for x in kinds) and any("스위칭" in x[3] for x in kinds)
    assert o["none"] == []


def test_menu_screens_files_and_static_rules():
    app = open(os.path.join(STATIC, "js", "app.js"), encoding="utf-8").read()
    menu = re.findall(r'\{id: "(\w+)", ko: "([^"]+)", group: "(\w+)"', re.search(r"const MENU = \[(.*?)\];", app, re.S).group(1))
    ids = [m[0] for m in menu]
    i = ids.index("check")
    assert ids[i + 1:i + 4] == ["versus", "goal", "reasons"]                                # right after 점검 진행, in the 홈 group
    assert [m[1] for m in menu[i + 1:i + 4]] == ["메인 vs 대조", "목표 진척도", "청산 이유"] and {m[2] for m in menu[i + 1:i + 4]} == {"home"}
    assert [m[2] for m in menu] == sorted([m[2] for m in menu], key=["trade", "home", "method", "info"].index)       # groups stay together
    screens = re.search(r"const SCREENS = \{([^}]*)\}", app).group(1)
    titles = re.search(r"const MENU_TITLE = \{(.*?)\};\s*const SCREENS", app, re.S).group(1)
    for name in SCREENS:
        assert f'{name}: "{name}"' in screens and re.search(rf"\b{name}: \"", titles), name
        assert os.path.exists(os.path.join(STATIC, "js", "screens", f"{name}.js"))
    # text only; every screen loads the one stylesheet, which is served and uses only the tokens, scoped to these screens
    from candleague import dash as D
    for f in NEW_JS:
        src = open(os.path.join(STATIC, "js", f), encoding="utf-8").read()
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "DOMParser", "document.write", "new Function", "eval(", "binance.com"):
            assert bad not in src, (f, bad)
        assert 'export const css = "scr/kinds.css"' in src, f
        assert f"js/{f}" in D.STATIC_FILES
    assert "scr/kinds.css" in D.STATIC_FILES
    css = open(os.path.join(STATIC, "scr", "kinds.css"), encoding="utf-8").read()
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", css)
    for m in re.finditer(r"font(?:-size)?:\s*([^;]+);", css):
        assert "var(--t-" in m.group(1), m.group(0)
    bare = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for rule in re.findall(r"(?m)(?:^|\})\s*([^@\s}][^{}]*)\{", bare):
        for sel in rule.split(","):
            assert sel.strip().startswith(".scr.kd"), sel
    for cls in set(re.findall(r'class: (?:\[)?"(kd-[\w-]+)', "".join(open(os.path.join(STATIC, "js", f), encoding="utf-8").read() for f in NEW_JS))):
        assert f".{cls}" in css or cls in HOOKS, cls
    node = shutil.which("node")
    if node:
        for f in NEW_JS + ["app.js", "find.js"]:
            with open(os.path.join(STATIC, "js", f), encoding="utf-8") as fh:
                r = subprocess.run([node, "--input-type=module", "--check"], stdin=fh, capture_output=True, text=True)
            assert r.returncode == 0, (f, r.stderr[:400])
