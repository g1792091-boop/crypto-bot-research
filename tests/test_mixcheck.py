"""믹스 30분 봇 점검 (paperbot/mixcheck.py; owners 10-25 night "연구분석이나 손실 분석 … 전부 다 만들어줘"), on worlds made by
the bot's own code (paperbot/mixchop.py's Bot: tests/mix_site_world.py, the fake WOO X Pro account of tests/test_mixchop.py,
and the bot in paper mode over the real Binance DOGE bars of tests/data):

- B. the loss card: a normal stop-out as designed (the plan: one stop-out plus both fees; the paper twin on the same
  signal), an abnormal one (the stop placed again, a restart while holding, the exit far past the stop worked back from
  the equity change, entered just before the Nasdaq-open block and out inside it), a win as one line; the frequent pass
  sends each close once (the first pass marks the old ones), tries a refused one again, at most three times;
- C. the luck band: the windows of the replay (wins, R sum, the drawdown at a run's end against a brute force), the
  verdict words at 10 % / 2 %, the Bernoulli fallback without a summary, the committed 5-year summary;
- D. the signal replay: mixchop.evaluate on the same bars finds exactly what the bot logged; a close the bot did not
  handle, late bars, a close it handled without seeing the change, a signal without an entry and without a reason;
- A. the morning message of a quiet day and of a day with a stop placed again; Binance unreachable; sent once a day;
  the dry run writes nothing; nothing of the bot's is ever written;
- the 믹스 성적 screen's 손실 분석 (the answer and the view in node), the units and install.sh, the guide's section."""
from __future__ import annotations

import bisect
import json
import os
import re
import shutil
import subprocess
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from paperbot import events as EV  # noqa: E402
from paperbot import mixcheck as MC  # noqa: E402
from paperbot import mixchop as M  # noqa: E402
from paperbot.dash.app import json_finite  # noqa: E402
from paperbot.dash.more import livebots as L  # noqa: E402
from paperbot.dash.more import livemix as X  # noqa: E402
from tests import mix_site_world as W  # noqa: E402
from tests import test_dash_livebots_fees as FW  # noqa: E402
from tests.test_mixchop import FakeWoo  # noqa: E402

NOW, K, MIN, H, DAY = W.NOW, W.K, W.MIN, W.H, W.DAY
ROOT = W.ROOT
DEPLOY = os.path.join(ROOT, "deploy")


@pytest.fixture(scope="module")
def w(tmp_path_factory):
    return W.build(str(tmp_path_factory.mktemp("mixcheck") / "w"))


@pytest.fixture(autouse=True)
def _fresh(w, monkeypatch, tmp_path):
    """The world's calendar; no cache across tests; no summary unless a test names one; its own state folder."""
    monkeypatch.setattr(EV, "PATH", w["calendar"])
    EV.reset()
    monkeypatch.setenv(MC.SUMMARY_ENV, str(tmp_path / "no-summary.json"))
    monkeypatch.setenv(MC.DIR_ENV, str(tmp_path / "mixcheck"))
    MC._summary.clear()
    X._tails.clear()
    L._cache.clear()
    yield
    EV.reset()
    MC._summary.clear()


def _p(folder: str) -> dict:
    return X.paths(W.env_of(folder))


def _summary(path, rs, **v) -> str:
    """A replay summary with the R sequence ``rs`` (the shape research/mixchop5y/replay.py writes)."""
    wins = [r for r in rs if r > 0]
    loss = [r for r in rs if r <= 0]
    lr = {"trades": len(rs), "per_year": len(rs) / 5, "win_rate": len(wins) / len(rs), "avg_win_r": sum(wins) / len(wins),
          "avg_loss_r": sum(loss) / len(loss), "r_per_trade": sum(rs) / len(rs), "r_per_month": sum(rs) / 60, "max_losing_streak": 9,
          "max_dd_r": 20.0, "max_dd_equity": 0.08, "month_mean": 0.004, "neg_months": 22, "months": 60, "min_order": "$5",
          "band": {"r": rs, "monthly_r": {"p25": -2.0, "p50": 1.0, "p75": 4.0, "neg": 22}}, **v}
    d = {"period": {"from": "2021-10-01", "to": "2026-10-01"}, "made_utc": "2026-10-25T15:00Z", "not_modelled": ["funding"],
         "variants": {"live_rules": lr, "one_position": {"trades": 900, "per_year": 180, "win_rate": 0.3, "r_per_month": 2.0,
                                                         "month_mean": 0.005, "neg_months": 20, "max_dd_equity": 0.07},
                      "design": {"coins": {"SOLUSDT": {"month_mean": 0.0115, "win_rate": 0.32, "per_year": 175, "neg_months": 23,
                                                       "max_losing_streak": 16, "design_month_mean": 0.0117, "design_win_rate": 0.32}}},
                      "design_fee02": {"coins": {"SOLUSDT": {"month_mean": 0.0126}}}}}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(d, fh)
    return str(path)


PATTERN = [-1.05, -1.05, 2.4, -1.05, -1.05, -1.05, 3.3, -1.05, 1.2, -1.05]     # 30 % wins, +0.03R a trade


# ================================================================ B. the loss card
def test_a_normal_stop_out_and_a_win(w):
    data = MC.load(_p(w["folder"]), NOW)
    cards = MC.cards_of(data)
    assert [(c["coin"], c["verdict"]) for c in cards] == [("XRP", "normal"), ("SOL", "win")]       # newest first
    xrp, sol = cards
    # the plan: 0.25 % of 50.02 at the stop 2.02 for 6.25 XRP short, both taker fees
    assert xrp["risk_usd"] == pytest.approx(50.02 * 0.0025) and xrp["qty"] == pytest.approx(6.25)
    assert xrp["plan"] == pytest.approx(-(2.02 - 2.0) * 6.25 - 0.00042 * 6.25 * 4.02)
    assert xrp["r"] == pytest.approx(-0.13 / (50.02 * 0.0025)) and xrp["plan_r"] < xrp["r"] < 0
    # the bot logs no exit fill: worked back from the equity change (a short: (entry (1 - f) - pnl / qty) / (1 + f))
    assert xrp["exit_src"] == "equity" and xrp["exit"] == pytest.approx((2.0 * (1 - 0.00042) + 0.13 / 6.25) / 1.00042)
    assert xrp["exit_gap"] < 0 and xrp["causes"] == [] and xrp["ko"] == "설계대로 손절 (정상)"
    assert xrp["twin"]["state"] == "closed" and xrp["twin"]["r"] < -1.0 and "모의: 같은 신호에서" in xrp["twin"]["ko"]
    level, text = MC.card_message(xrp)
    assert level == "INFO" and text.startswith("❌ 믹스 손실 카드 · XRP 숏 · 설계대로 손절 (정상)")
    for word in ("10/26 11:00 → 10/26 11:20 (19분) · 손익 −$0.130 (−1.04R)", "계획: 손절 1번 = 잔고의 0.25% ($0.125)",
                 "이번 손절가에서 계획 손익 −$0.136 (−1.08R, 수수료 포함)", "진입 2 (신호 종가 2와 같음)", "청산 추정 2.01911",
                 "잔고 변화로 거꾸로 계산", "모의: 같은 신호에서 −1.1R (손절 2.02)"):
        assert word in text, word
    assert "지금 할 일" not in text and "이유 후보" not in text
    level, text = MC.card_message(sol)
    assert level == "INFO" and text == "✅ 믹스 SOL 롱 +$0.020 (+0.16R) · 계단 1단계 익절 · 49분 · 모의 +0.17R"


def _abnormal(folder: str) -> dict:
    """The bot's own run on the fake WOO X Pro account: SOL long at 21:30 KST (the Nasdaq-open block starts at 22:00), its
    stop gone and placed again at 21:40, a restart at 21:50 while holding, the stop fired and the account 0.30 lower
    (2.4 stop-outs) at 22:10."""
    os.makedirs(folder, exist_ok=True)
    cfg = M.load_config(W.config(folder, "mainnet"))
    fake, wo = FakeWoo(), W.World()
    keep = M.evaluate
    M.evaluate = wo.evaluate
    try:
        wo.t = K(26, 21, 0, 10)
        bot = M.Bot(cfg, M.WooBroker(fake, cfg.coins), wo.fetch, wo.now, sleep=lambda s: None)
        bot.start()
        wo.close(bot, K(26, 21, 30), W.ev("SOLUSDT", K(26, 21, 30), 1))
        fake.cancel_all_algo("SOLUSDT")
        wo.t = K(26, 21, 40)
        bot._last_stop_check = -1e9
        bot.poll()
        wo.t = K(26, 21, 50)
        bot = M.Bot(cfg, M.WooBroker(fake, cfg.coins), wo.fetch, wo.now, sleep=lambda s: None)
        bot.start()
        fake.fire("SOLUSDT")
        fake.eq = 50.0 - 0.30
        wo.t = K(26, 22, 10)
        bot.poll()
    finally:
        M.evaluate = keep
    return {"cfg": cfg, "folder": folder}


def test_an_abnormal_loss_says_why(tmp_path):
    a = _abnormal(str(tmp_path / "ab"))
    data = MC.load(_p(a["folder"]), K(26, 22, 15))
    (c,) = MC.cards_of(data)
    assert c["verdict"] == "very_abnormal" and c["ko"] == "설계보다 아주 큰 손실" and c["tone"] == "bad"
    assert c["r"] == pytest.approx(-0.30 / 0.125) and c["plan_r"] == pytest.approx((-0.12 - 0.00042 * 0.12 * 199) / 0.125)
    ids = [x["id"] for x in c["causes"]]
    assert ids == ["far", "stop", "restart", "block_near", "block_exit"], ids
    words = " / ".join(x["ko"] for x in c["causes"])
    for word in ("손절이 가격을 한참 지나서 체결됐어요: 손절 99, 청산 추정 97.58", "손절이 없거나 모자라 다시 걸었어요 (1번, 10/26 21:40부터)",
                 "보유 중에 봇이 다시 켜졌어요 (10/26 21:50)", "진입 30분 뒤 진입 금지 시간이 시작됐어요: 나스닥 개장 앞뒤 (변동이 큰 시간대)",
                 "청산이 진입 금지 시간 안에서 일어났어요: 나스닥 개장 앞뒤"):
        assert word in words, word
    assert c["exit"] == pytest.approx((-0.30 / 0.12 + 100 * 1.00042) / 0.99958) and c["exit_gap"] > MC.FAR_GAP_FRAC
    assert c["twin"] == {"state": "off", "ko": "모의 봇 기록이 없어 비교하지 못했어요"}       # the paper bot never ran here
    level, text = MC.card_message(c)
    assert level == "WARN" and text.startswith("⚠ 믹스 손실 카드 · SOL 롱 · 설계보다 아주 큰 손실") and "이유 후보:" in text
    assert text.rstrip().endswith("지금 할 일: WOO X Pro 앱의 체결 내역에서 청산 가격과 수수료를 확인해 주세요")
    assert "모의 봇 기록이 없어 비교하지 못했어요" in text


def test_the_implied_exit_round_trips():
    for side, e, q, x in ((1, 100.0, 0.12, 98.7), (-1, 2.0, 6.25, 2.03), (1, 0.2, 600.0, 0.2011)):
        pnl = side * (x - e) * q - MC.TAKER * q * (e + x)
        assert MC.implied_exit(side, e, q, pnl) == pytest.approx(x)
    assert MC.implied_exit(1, 100.0, 0.0, -1.0) is None and MC.implied_exit(1, 100.0, 1.0, None) is None


def test_the_pass_sends_each_close_once(tmp_path):
    a = _abnormal(str(tmp_path / "ab"))
    p = _p(a["folder"])
    sent = []

    def send(level, text):
        sent.append((level, text))
        return True
    state: dict = {}
    got = MC.run_pass(MC.load(p, K(26, 22, 15)), state, send)
    assert [c["verdict"] for c in got] == ["very_abnormal"] and sent[0][0] == "WARN" and state["started_ms"] == K(26, 22, 15)
    assert MC.run_pass(MC.load(p, K(26, 22, 20)), state, send) == [] and len(sent) == 1           # once
    assert [o[1] for o in state["obs"]] == [K(26, 21, 30), K(26, 21, 30)]                           # the bot's last close
    # a first pass hours later only marks it (no flood of old cards when the timer is first switched on)
    fresh: dict = {}
    assert MC.run_pass(MC.load(p, K(27, 9)), fresh, send) == [] and len(sent) == 1
    assert list(fresh["told"].values())[0]["skipped"] == "first pass"
    # Telegram refused: tried again on the next passes, at most three times
    late: dict = {}
    no = []
    for i in range(5):
        MC.run_pass(MC.load(p, K(26, 22, 15) + i * 5 * MIN), late, lambda lv, t: no.append(t) and False)
    assert len(no) == MC.SEND_TRIES and list(late["told"].values())[0]["tries"] == MC.SEND_TRIES


def test_the_pass_command_writes_only_its_own_folder(w, tmp_path, monkeypatch, capsys):
    for k, v in W.env_of(w["folder"]).items():
        monkeypatch.setenv(k, v)
    before = {n: open(os.path.join(w["folder"], n), "rb").read() for n in sorted(os.listdir(w["folder"]))}
    d = tmp_path / "mixcheck"
    assert MC.main(["pass", "--dry-run", "--now", str(NOW)]) == 0 and not d.exists()
    assert "dry run" in capsys.readouterr().out
    assert MC.main(["pass", "--now", str(NOW)]) == 0
    st = json.loads((d / "state.json").read_text(encoding="utf-8"))
    assert len(st["told"]) == 2 and all(v["skipped"] == "first pass" for v in st["told"].values())   # both closes are old
    after = {n: open(os.path.join(w["folder"], n), "rb").read() for n in sorted(os.listdir(w["folder"]))}
    assert after == before


# ================================================================ C. the luck band
def test_the_band_windows_and_verdicts(tmp_path):
    ref = MC.band_ref({"state": "ok", "d": json.load(open(_summary(tmp_path / "s.json", PATTERN * 100)))})
    assert len(ref["r"]) == 1000
    # a record like the replay: 정상 범위
    b = MC.band(PATTERN * 2, ref)
    assert b["state"] == "ok" and b["model"] == "replay" and b["worst"] == "ok" and b["ko"] == "정상 범위"
    rows = {x["id"]: x for x in b["rows"]}
    assert rows["wins"]["live"] == "6승 / 20번" and rows["wins"]["verdict"] == "ok" and rows["rsum"]["verdict"] == "ok"
    # 20 losses in a row: never in the replay (its longest run is 3)
    bad = MC.band([-1.05] * 20, ref)
    rows = {x["id"]: x for x in bad["rows"]}
    assert bad["worst"] == "very_rare" and bad["ko"] == "아주 드묾: 설계와 다르게 돌고 있을 수 있어요"
    assert rows["wins"]["p"] == 0.0 and rows["streak"]["p"] == 0.0 and rows["dd"]["live"] == "−21.0R" and rows["dd"]["p"] == 0.0
    assert "가장 길었던 연속 손절 3번" in rows["streak"]["range"]
    # three losses in a row: the replay is in such a run at 2 of each 10 trades (its first run is only 2 long): 정상 범위;
    # four: never in the replay
    three = {x["id"]: x for x in MC.band(PATTERN + [2.0] + [-1.05] * 3, ref)["rows"]}["streak"]
    assert three["p"] == pytest.approx(199 / 1000) and three["verdict"] == "ok" and three["live"] == "3번"
    four = {x["id"]: x for x in MC.band(PATTERN + [2.0] + [-1.05] * 4, ref)["rows"]}["streak"]
    assert four["p"] == 0.0 and four["verdict"] == "very_rare"
    assert MC.verdict_of(0.0999) == "rare" and MC.verdict_of(0.02) == "rare" and MC.verdict_of(0.0199) == "very_rare"
    # a small record says so; no trade: nothing judged
    assert MC.band([-1.0], ref)["small"] is True and "표본이 작아요" in MC.band([-1.0], ref)["ko"]
    assert MC.band([], ref)["state"] == "empty"
    # the month in progress: shown, never judged
    m = {x["id"]: x for x in MC.band(PATTERN, ref, month_r=-3.0)["rows"]}["month"]
    assert m["verdict"] is None and "마이너스 달 22번/60" in m["range"]


def test_window_drawdowns_match_a_brute_force():
    import random
    rnd = random.Random(3)
    seq = [rnd.choice((-1.05, -1.05, -1.05, 2.5, 0.4)) for _ in range(300)]
    c = [0.0]
    for x in seq:
        c.append(c[-1] + x)
    for m in (1, 2, 7, 50, 300):
        brute = []
        for i in range(len(seq) - m + 1):
            pk = max([0.0] + [c[j] - c[i] for j in range(i + 1, i + m + 1)])
            brute.append(pk - (c[i + m] - c[i]))
        assert MC.window_drawdowns(c, m) == pytest.approx(brute), m


def test_the_band_without_a_summary_is_a_labelled_model(w):
    data = MC.load(_p(w["folder"]), NOW)
    assert MC.load_summary()["state"] == "missing" and MC.band_ref() is None
    b = MC.live_band(data, None, NOW)
    assert b["model"] == "bernoulli" and "설계서 승률(코인 평균)로 만든 단순 모델" in b["model_ko"]
    assert [x["id"] for x in b["rows"]] == ["wins", "streak"]                       # no R sum, no drawdown
    p = MC.BERNOULLI_P
    assert p == pytest.approx((0.32 + 0.19 + 0.20 + 0.31 + 0.37 + 0.40) / 6)
    assert b["rows"][0]["p"] == pytest.approx((1 - p) ** 2 + 2 * p * (1 - p)) and b["rows"][1]["p"] == pytest.approx(1 - p)


def test_the_committed_replay_summary():
    """research/mixchop5y/summary.json: the 5-year replay of the bot's own code (research/mixchop5y/replay.py)."""
    s = MC.load_summary(MC.SUMMARY)
    assert s["state"] == "ok", s
    d = s["d"]
    assert d["period"]["months"] == 60 and set(d["variants"]) == {"design", "design_fee02", "one_position", "live_rules"}
    ds = d["variants"]["design"]["coins"]
    assert list(ds) == ["SOLUSDT", "ETHUSDT", "XRPUSDT", "BCHUSDT", "ZECUSDT", "DOGEUSDT"]
    for sym, v in ds.items():
        assert v["months"] == 60 and v["design_win_rate"] == dict((r["symbol"], r["win"]) for r in X.BACKTEST["rows"])[sym]
        assert abs(v["win_rate"] - v["design_win_rate"]) < 0.03, sym                     # the design's win rates come back
    lr = d["variants"]["live_rules"]
    assert len(lr["band"]["r"]) == lr["trades"] >= 500 and lr["fee"] == MC.TAKER and sum(y["trades"] for y in lr["band"]["yearly"].values()) == lr["trades"]
    assert d["not_modelled"] and d["code"]["config"] == "deploy/mixchop.live.json"
    for co in d["checks"].values():
        assert co["sampled_with_a_change"] == 0 and co["evaluate_disagrees"] <= 2
    ref = MC.band_ref(s)
    assert MC.band([-1.0] * 3, ref)["state"] == "ok"


# ================================================================ D. the signal replay (the real DOGE bars)
def _doge(tf: str) -> list:
    df = pd.read_csv(os.path.join(ROOT, "tests", "data", f"mixchop_doge_{tf}.csv.gz"))
    return [[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4])] for r in df.values.tolist()]


class Doge:
    """Binance as the bot and the replay read it, from the real DOGE bars: the last ``n`` rows up to now (the bot), the
    rows from a start (the replay's paged read)."""

    def __init__(self):
        self.rows = {"30m": _doge("30m"), "1h": _doge("1h")}
        self.opens = {k: [r[0] for r in v] for k, v in self.rows.items()}
        self.t = 0
        self.calls = 0

    def now(self) -> int:
        return self.t

    def fetch(self, symbol, tf, n):
        j = bisect.bisect_right(self.opens[tf], self.t)
        return self.rows[tf][max(0, j - n):j]

    def klines(self, symbol, tf, start_ms, limit):
        self.calls += 1
        i = bisect.bisect_left(self.opens[tf], start_ms)
        return self.rows[tf][i:i + limit]


@pytest.fixture(scope="module")
def doge_day(tmp_path_factory):
    """The bot in paper mode over KST 2026-10-23 on the real DOGE bars (its own config's blocks), its log."""
    folder = tmp_path_factory.mktemp("doge")
    raw = json.load(open(os.path.join(DEPLOY, "mixchop.paper.json"), encoding="utf-8"))
    for k in ("margin_frac", "ladder", "ladder_every_s"):            # the design's sizing and ladder (see mix_site_world)
        raw.pop(k, None)
    raw.update(state=str(folder / "state.json"), log=str(folder / "log.jsonl"), kill_file=str(folder / "STOP"),
               own_stop_file=str(folder / "own.STOP"), telegram=False, coins={"DOGEUSDT": raw["coins"]["DOGEUSDT"]})
    (folder / "cfg.json").write_text(json.dumps(raw), encoding="utf-8")
    cfg = M.load_config(str(folder / "cfg.json"))
    d = Doge()
    w0 = K(23)
    d.t = w0 + 1000
    bot = M.Bot(cfg, M.PaperBroker(50.0, cfg.taker_fee), d.fetch, d.now, sleep=lambda s: None)
    bot.start()
    for ce in range(w0 + M.MIN30, w0 + DAY + 1, M.MIN30):
        d.t = ce + 5000
        bot.on_close(ce)
    return {"cfg": cfg, "doge": d, "w0": w0, "rows": W.rows(str(folder / "log.jsonl"))}


def test_the_replay_finds_what_the_bot_logged(doge_day):
    cfg, d, w0, rows = doge_day["cfg"], doge_day["doge"], doge_day["w0"], doge_day["rows"]
    sigs = [r for r in rows if r["kind"] == "signal"]
    assert any(r["close_ms"] == K(23, 10) and r["side"] == 1 for r in sigs)           # the design table's 10/23 10:00 cyan
    assert any(r["kind"] == "entry" and r["signal_close_ms"] == K(23, 10) for r in rows)
    rp = MC.signal_replay(cfg, w0, w0 + DAY, rows, d.klines)
    assert rp["state"] == "ok" and rp["closes"] == 48 and rp["changes"] == len(sigs) and rp["signals"] == sum(1 for r in sigs if r["side"])
    assert rp["missed"] == [] and rp["different"] == [] and rp["unexplained"] == [] and rp["unsure"] == []
    assert MC.replay_lines(rp)[0].startswith("- 놓친 신호 0개 (봇 공식으로 바이낸스 봉을 다시 계산: 30분봉 48개 × 코인 1개")


def test_the_replay_names_each_kind_of_miss(doge_day):
    cfg, d, w0, rows = doge_day["cfg"], doge_day["doge"], doge_day["w0"], doge_day["rows"]
    ce = K(23, 10)
    after = [r for r in rows if not (ce <= r["ts"] < ce + M.MIN30)]                      # the bot's rows of that close gone
    seen_before = [[ce + 5 * MIN, ce - M.MIN30, None]]                                    # a pass saw the bot still at 09:30
    rp = MC.signal_replay(cfg, w0, w0 + DAY, after, d.klines, seen_before)
    (m,) = rp["missed"]
    assert (m["kind"], m["close_ms"], m["side"]) == ("down", ce, 1) and m["ko"] == "봇이 이 봉을 처리하지 않았어요 (꺼져 있었거나 늦었어요)"
    assert MC.signal_replay(cfg, w0, w0 + DAY, after, d.klines)["missed"][0]["kind"] == "unknown"    # no pass looked
    seen = [[ce + 5 * MIN, ce, None]]
    assert MC.signal_replay(cfg, w0, w0 + DAY, after, d.klines, seen)["missed"][0]["kind"] == "unseen"
    late = after + [{"ts": ce + 70_000, "kind": "bars_missing", "symbol": "DOGEUSDT", "close_ms": ce, "side": 0, "why": "캔들 읽기 실패: x"}]
    assert MC.signal_replay(cfg, w0, w0 + DAY, late, d.klines)["missed"][0]["kind"] == "late"
    # a signal logged without its entry or a skip: no reason recorded
    quiet = [r for r in rows if not (r["kind"] in ("entry", "skip") and ce <= r["ts"] < ce + M.MIN30)]
    rq = MC.signal_replay(cfg, w0, w0 + DAY, quiet, d.klines)
    assert [(x["close_ms"], x["ko"]) for x in rq["unexplained"]] == [(ce, "신호가 나왔는데 진입도, 건너뛴 이유도 기록에 없어요")]
    # the bot decided differently at a close
    other = [dict(r, side=-1) if r["kind"] == "signal" and r["close_ms"] == ce else r for r in rows]
    (x,) = MC.signal_replay(cfg, w0, w0 + DAY, other, d.klines)["different"]
    assert x["ko"] == "봇은 숏 신호, 다시 계산하면 롱 신호"
    lines = MC.replay_lines(rp)
    assert lines[0].startswith("- 놓친 신호 1개") and lines[1] == "  · 10/23 10:00 DOGE 롱: 봇이 이 봉을 처리하지 않았어요 (꺼져 있었거나 늦었어요)"
    # Binance unreachable: said, never "0 missed"
    def down(*a):
        raise OSError("no route")
    bad = MC.signal_replay(cfg, w0, w0 + DAY, rows, down)
    assert bad["state"] == "error" and MC.replay_lines(bad) == ["- 바이낸스 봉을 못 읽어 신호를 다시 계산하지 못했어요"]


# ================================================================ A. the morning check
def test_a_quiet_morning(w):
    data = MC.load(_p(w["folder"]), NOW)
    res = MC.morning(data, K(26))
    assert res["level"] == "INFO" and res["report"]["warn"] == []
    t = res["text"]
    for line in ("📋 믹스 30분 봇 아침 점검 · 이상 없음", "10/26(월) 00:00 ~ 24:00 (한국 시간)",
                 "- 색 변화 6번 · 조건 맞은 신호 6번 · 진입 2번",
                 "- 건너뜀 4번: 진입 금지 시간 1 (나스닥 개장 앞뒤 1) · 보유 중 1 · 같은 봉 다른 코인 먼저 1 · 정지 파일 1",
                 "- 모의와 같은 진입 2번 · 다른 것 없음", "- 다시 계산은 건너뛰었어요", "- 닫힌 거래 2번 · 1승 1패 · 손익 −$0.110 (−0.88R)",
                 "  · XRP 숏 −$0.130 (−1.04R): 설계대로 손절 (정상)",
                 "- 진입 체결: 신호 종가보다 평균 0.00% (같음) · 수수료 약 $0.02 (테이커 0.042% 양쪽, 추정)",
                 "- 손절: 기록상 보유 내내 걸려 있었어요 (실패·다시 걸기 없음)", "- 거래소·바이낸스 읽기 실패 0번 · 봇 시작 1번 · 모르는 포지션 없음",
                 "- 지금 보유: BCH 롱 · 손절 100.25", "- $49.95 (시작 $50.00, −0.1%) · 바닥선 $35.00까지 여유 $14.95 (손절 약 120번)",
                 "운이냐 고장이냐 (실거래 전체)"):
        assert line in t.split("\n"), line
    assert "\n- 이긴 횟수 1승 / 2번: 정상 범위 (이만큼 나쁘거나 더 나빴던 때 91%)" in t
    assert "지금 할 일" not in t and len(t) < 3900


def test_a_morning_with_something_to_check(w):
    data = MC.load(_p(w["folder"]), NOW)
    res = MC.morning(data, K(27), klines=lambda *a: (_ for _ in ()).throw(OSError("blocked")))
    assert res["level"] == "WARN"
    assert res["report"]["warn"] == ["실거래와 모의가 이유 없이 다른 진입 1개", "손절 주문 문제 1번 (다시 걸기·실패)", "신호 다시 계산을 못 했어요 (바이낸스)"]
    t = res["text"].split("\n")
    assert t[0] == "⚠ 믹스 30분 봇 아침 점검 · 확인할 것 3개"
    for line in ("  · BCH 롱 (10/27 09:00 봉): 실거래만 진입 · 다른 쪽 기록에 이유 없음", "- 바이낸스 봉을 못 읽어 신호를 다시 계산하지 못했어요",
                 "- 손절: 문제 1번 · 10/27 10:30 손절이 없거나 모자라 다시 걸었어요", "- 거래소·바이낸스 읽기 실패 3번 (거래소 읽기 3) · 봇 시작 0번 · 모르는 포지션 없음",
                 "- 닫힌 거래 없음"):
        assert line in t, line
    # a stopped bot is the first thing to check
    late = MC.morning(MC.load(_p(w["folder"]), NOW + 2 * H), K(27))
    assert late["report"]["warn"][0].startswith("실거래 봇이 지금 멈춘 것 같아요") and "지금 할 일: 서버에서 systemctl status paperbot-mixchop" in late["text"]


def test_the_morning_command_sends_once_and_the_site_shows_it(w, tmp_path, monkeypatch, capsys):
    for k, v in W.env_of(w["folder"]).items():
        monkeypatch.setenv(k, v)
    sent = []
    monkeypatch.setattr(MC, "notifier", lambda dry: None if dry else (lambda lv, t: sent.append((lv, t)) or True))
    d = tmp_path / "mixcheck"
    assert MC.main(["morning", "--day", "2026-10-26", "--no-replay", "--dry-run", "--now", str(NOW)]) == 0
    assert capsys.readouterr().out.startswith("[INFO]\n📋 믹스 30분 봇 아침 점검") and not d.exists() and sent == []
    assert MC.main(["morning", "--day", "2026-10-26", "--no-replay", "--now", str(NOW)]) == 0 and len(sent) == 1
    assert MC.main(["morning", "--day", "2026-10-26", "--no-replay", "--now", str(NOW)]) == 0 and len(sent) == 1   # once a day
    assert "already sent" in capsys.readouterr().out
    assert MC.main(["morning", "--day", "2026-10-26", "--no-replay", "--force", "--now", str(NOW)]) == 0 and len(sent) == 2
    st = json.loads((d / "state.json").read_text(encoding="utf-8"))
    assert st["mornings"]["2026-10-26"]["sent"] is True and st["mornings"]["2026-10-26"]["level"] == "INFO"
    lm = MC.last_morning()
    assert lm["state"] == "ok" and lm["d"]["day"] == "2026-10-26" and lm["d"]["signals"]["entries"] == 2
    assert MC.main(["show"]) == 0 and "📋 믹스 30분 봇 아침 점검" in capsys.readouterr().out
    # yesterday by default (KST): NOW is Tuesday 10/27 12:10 KST
    assert MC.kst_day_of(None, NOW) == K(26) and MC.kst_day_of("2026-10-26", NOW) == K(26)


def test_a_pass_during_the_morning_check_is_not_undone(w, tmp_path, monkeypatch):
    """The morning check runs for minutes (Binance bars); a 5-minute pass may write state.json meanwhile. The morning
    writes under the lock on a fresh read, so the pass's told cards stay (no card told twice)."""
    for k, v in W.env_of(w["folder"]).items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(MC, "notifier", lambda dry: None if dry else (lambda lv, t: True))
    d = tmp_path / "mixcheck"
    real = MC.morning

    def slow_morning(*a, **k):
        res = real(*a, **k)
        assert MC.main(["pass", "--now", str(NOW)]) == 0            # a pass in the middle of the morning check
        return res
    monkeypatch.setattr(MC, "morning", slow_morning)
    assert MC.main(["morning", "--day", "2026-10-26", "--no-replay", "--now", str(NOW)]) == 0
    st = json.loads((d / "state.json").read_text(encoding="utf-8"))
    assert len(st["told"]) == 2 and st["mornings"]["2026-10-26"]["sent"] is True and st["obs"]
    assert (d / "state.lock").exists()

def test_nothing_of_the_bots_is_written(w, tmp_path, monkeypatch):
    for k, v in W.env_of(w["folder"]).items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(MC, "notifier", lambda dry: (lambda lv, t: True))
    before = {n: (open(os.path.join(w["folder"], n), "rb").read(), os.stat(os.path.join(w["folder"], n)).st_mtime_ns)
              for n in sorted(os.listdir(w["folder"]))}
    MC.main(["morning", "--no-replay", "--now", str(NOW)])
    MC.main(["pass", "--now", str(NOW)])
    MC.site_view(None, NOW)
    after = {n: (open(os.path.join(w["folder"], n), "rb").read(), os.stat(os.path.join(w["folder"], n)).st_mtime_ns)
             for n in sorted(os.listdir(w["folder"]))}
    assert after == before
    assert sorted(os.listdir(tmp_path / "mixcheck")) == ["last-morning.json", "state.json", "state.lock"]
    src = FW._read(ROOT, "paperbot", "mixcheck.py")
    # read-only towards the bot and the exchange: one writer (its own folder), no order, no key, no env file opened
    assert src.count("open(tmp, \"w\"") == 1 and "write_state" not in src and "subprocess" not in src
    assert not re.search(r"\.(market|place_stop|close_market|move_stop|cancel)\(", src) and "WooBroker" not in src
    assert ".env\"" not in src and "load_dotenv" not in src and "live_broker" not in src


# ================================================================ the 믹스 성적 screen
def test_the_site_answer(w, tmp_path, monkeypatch):
    monkeypatch.setenv(MC.SUMMARY_ENV, _summary(tmp_path / "s.json", PATTERN * 100))
    MC._summary.clear()
    an = X.perf(_p(w["folder"]), NOW)["analysis"]
    assert an["state"] == "ok" and [c["coin"] for c in an["cards"]] == ["XRP", "SOL"]
    assert an["band"]["model"] == "replay" and an["band"]["n"] == 2 and an["summary"]["state"] == "ok"
    assert an["design"]["rows"][0] == {"symbol": "SOLUSDT", "coin": "SOL", "design_month": 0.0117, "design_win": 0.32, "month": 0.0115,
                                       "month_fee02": 0.0126, "win": 0.32, "trades_year": 175, "neg_months": 23, "max_losing_streak": 16}
    assert an["morning"]["state"] == "missing" and "docs/mixchop-ko.md 8장" in an["morning"]["ko"]
    # its own failure is said, never the page's
    monkeypatch.setattr(MC, "site_view", lambda *a: 1 / 0)
    bad = X.perf(_p(w["folder"]), NOW)
    assert bad["analysis"]["state"] == "error" and bad["bots"][0]["record"]["n"] == 2


def test_the_analysis_in_node(w, tmp_path, monkeypatch):
    node = shutil.which("node")
    if node is None:
        pytest.skip("needs node")
    monkeypatch.setenv(MC.SUMMARY_ENV, _summary(tmp_path / "s.json", PATTERN * 100))
    MC._summary.clear()
    for k, v in W.env_of(w["folder"]).items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(MC, "notifier", lambda dry: (lambda lv, t: True))
    MC.main(["morning", "--day", "2026-10-27", "--no-replay", "--now", str(NOW)])
    prf = json_finite(X.perf(_p(w["folder"]), NOW))
    ab = _abnormal(str(tmp_path / "ab"))
    abn = json_finite(MC.site_view(_p(ab["folder"]), K(26, 22, 15)))
    script = (f"const D = await import('file://{FW.DOM}'); const fs = await import('node:fs');\n"
              f"Date.now = () => {NOW};\n"
              f"const X = await import('file://{FW.SCREENS}/livebots-mix.js');\n"
              f"const P = JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / 'p.json'))}, 'utf8'));\n"
              f"const A = JSON.parse(fs.readFileSync({json.dumps(str(tmp_path / 'a.json'))}, 'utf8'));\n"
              "const tick = () => new Promise((r) => setTimeout(r, 5));\n"
              "const mkCtx = (a) => ({params: {query: {}}, alive: () => true, track() {}, listen() {}, on() {}, watch() {}, href: (n) => '#/' + n,"
              " every() {}, api: async () => JSON.parse(JSON.stringify(a))});\n"
              "const v = X.mixperfView(mkCtx(P)); await tick(); await tick();\n"
              "const text = D.walk(v.el).text.replace(/\\s+/g, ' ');\n"
              "const P2 = {...P, analysis: {...P.analysis, ...A}}; const v2 = X.mixperfView(mkCtx(P2)); await tick(); await tick();\n"
              "const text2 = D.walk(v2.el).text.replace(/\\s+/g, ' ');\n"
              "const P3 = {...P, analysis: {state: 'error', ko: '손실 분석을 만들지 못했어요', reason: 'ZeroDivisionError'}}; const v3 = X.mixperfView(mkCtx(P3));"
              " await tick(); await tick();\n"
              "console.log(JSON.stringify({text, text2, text3: D.walk(v3.el).text.replace(/\\s+/g, ' '),"
              " rows: P.analysis.band.rows.map((x) => X.bandRowKo(x)), cards: A.cards.map((c) => X.cardKo(c)),"
              " m: X.morningKo(P.analysis.morning), m0: X.morningKo({state: 'missing', ko: '아침 점검 기록이 아직 없어요'}), d: X.designRows(P.analysis.design)}));")
    (tmp_path / "p.json").write_text(json.dumps(prf, allow_nan=False, default=str), encoding="utf-8")
    (tmp_path / "a.json").write_text(json.dumps(abn, allow_nan=False, default=str), encoding="utf-8")
    r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    t = out["text"]
    for word in ("운이냐 고장이냐", "정상 범위 · 거래 2번은 아직 표본이 작아요 (대부분 운)", "실거래 2번", "이긴 횟수 1승 / 2번", "R 합 −0.9R",
                 "5년 재생 (봇 코드 그대로, 실거래 규칙", "설계서 숫자와 5년 재생", "+1.17% · 승률 32%", "+1.15% · 승률 32%", "+1.26%", "23/60",
                 "여섯 코인 한 번에 1포지션: 1년 약 180번", "실거래 규칙 그대로 (1포지션 · 진입 금지 시간 · 최소 주문 · $50)", "재생에 없는 것: funding",
                 "손실 카드", "XRP 숏", "설계대로", "계획: 손절 1번 = 잔고의 0.25% ($0.125)", "모의: 같은 신호에서 −1.1R (손절 2.02)",
                 "SOL 롱", "계단 1단계 익절", "거래 2번 · 설계보다 큰 손실 0번", "어제 아침 점검", "2026-10-27 (한국 시간 하루)", "확인할 것 2개",
                 "확인할 것: 손절 주문 문제 1번 (다시 걸기·실패)", "신호 다시 계산: 건너뜀", "모의와 같은 진입 0번 · 다른 것 1개",
                 "트레이딩뷰는 자동으로 읽을 수 없어요", "python -m paperbot.mixchop signals"):
        assert word in t, word
    assert not FW.BAD.search(t), FW.BAD.search(t)
    t2 = out["text2"]
    for word in ("설계보다 아주 큰 손실", "이유 후보", "손절이 가격을 한참 지나서 체결됐어요", "보유 중에 봇이 다시 켜졌어요", "거래 1번 · 설계보다 큰 손실 1번"):
        assert word in t2, word
    assert not FW.BAD.search(t2)
    assert "손실 분석을 만들지 못했어요" in out["text3"] and "닫힌 거래" in out["text3"]               # the rest of the page stays
    assert out["cards"][0]["tone"] == "bad" and out["cards"][0]["causesHead"] == "이유 후보" and out["cards"][0]["pill"] == "설계보다 아주 큰 손실"
    assert out["m"]["pill"] == "확인할 것 2개" and out["m0"] == {"pill": "아직 없음", "tone": "thin", "lines": ["아침 점검 기록이 아직 없어요"]}
    assert out["d"][0] == {"coin": "SOL", "design": "+1.17% · 승률 32%", "replay": "+1.15% · 승률 32%", "replay02": "+1.26%", "neg": "23/60"}
    assert all(not FW.BAD.search(json.dumps(x, ensure_ascii=False)) for x in out["rows"] + out["cards"])


def test_the_css_keeps_the_house_rules():
    FW.house_rules("livebots-mix", "lmx")


# ================================================================ deploy, install.sh, the guide
def _unit(name: str) -> dict:
    out: dict = {}
    sec = ""
    for ln in open(os.path.join(DEPLOY, name), encoding="utf-8").read().splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        if ln.startswith("["):
            sec = ln
            continue
        out.setdefault(sec, []).append(ln)
    return out


def test_the_units_are_read_only_analysis_jobs():
    for svc, cmd in (("paperbot-mixcheck.service", "morning"), ("paperbot-mixcheck-pass.service", "pass")):
        s = _unit(svc)["[Service]"]
        assert f"ExecStart=/opt/paperbot/venv/bin/python -m paperbot.mixcheck {cmd}" in s and "Type=oneshot" in s
        assert "User=paperbot" in s and "Group=paperbot" in s and "ProtectSystem=strict" in s and "NoNewPrivileges=yes" in s
        assert [x for x in s if x.startswith("EnvironmentFile")] == ["EnvironmentFile=-/etc/paperbot/live-telegram.env"]
        assert [x for x in s if x.startswith("ReadWritePaths")] == ["ReadWritePaths=/var/lib/paperbot/mixcheck"]
        hidden = next(x for x in s if x.startswith("InaccessiblePaths=")).split("=", 1)[1].split()
        assert "-/etc/paperbot/executor-wooxpro2.env" in hidden and "-/etc/paperbot/live.env" in hidden
        assert "-/etc/paperbot/executor-toobit.env" in hidden and "-/etc/paperbot/executor.env" in hidden
        assert "OnFailure=paperbot-failed@%n.service" in _unit(svc)["[Unit]"]
    assert "OnCalendar=*-*-* 00:05:00 UTC" in _unit("paperbot-mixcheck.timer")["[Timer]"]
    assert "OnCalendar=*:1/5" in _unit("paperbot-mixcheck-pass.timer")["[Timer]"]
    inst = open(os.path.join(DEPLOY, "install.sh"), encoding="utf-8").read()
    assert "install -d -o paperbot -g paperbot -m 750 /var/lib/paperbot/mixcheck" in inst
    assert "for u in paperbot-mixcheck.service paperbot-mixcheck.timer paperbot-mixcheck-pass.service paperbot-mixcheck-pass.timer; do" in inst
    assert "for t in paperbot-mixcheck.timer paperbot-mixcheck-pass.timer; do" in inst
    # the bot and its paper twin are never started, stopped, restarted or enabled by the install
    assert not re.search(r"systemctl\s+(start|stop|restart|enable|disable)[^\n]*paperbot-mixchop\b", inst)
    assert "paperbot-mixchop" not in re.search(r'^UNITS="[^"]*"', inst, re.M).group(0)


def test_the_guide_has_the_section():
    doc = open(os.path.join(ROOT, "docs", "mixchop-ko.md"), encoding="utf-8").read()
    sec = doc.split("## 8.")[1]
    for word in ("아침 점검", "손실 카드", "운이냐 고장이냐", "놓친 신호", "트레이딩뷰는 자동으로 읽을 수 없", "python -m paperbot.mixchop signals",
                 "sudo systemctl enable --now paperbot-mixcheck.timer paperbot-mixcheck-pass.timer",
                 "python -m paperbot.mixcheck morning --dry-run", "research/mixchop5y/replay.py", "정상 범위", "아주 드묾"):
        assert word in sec, word


# ================================================================ the 5-year replay's driver (research/mixchop5y/replay.py)
def _replay_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("mixchop5y_replay", os.path.join(ROOT, "research", "mixchop5y", "replay.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_replay_drives_the_bots_own_code(monkeypatch):
    """The replay's ReplayBot is mixchop.Bot itself (paper mode): a long at the signal close, the stop at the close minus
    the stop distance, out at the stop on the bar that reaches it, both fees; the live rules' weekend block skips a
    Saturday signal (and the design variant takes it)."""
    R = _replay_module()
    t0, t1 = K(26), K(28)                                         # Monday 10/26 .. Wednesday 10/28 KST
    monkeypatch.setattr(R, "T0", t0)
    monkeypatch.setattr(R, "T1", t1)
    bars = []
    for i in range(-200, 200):
        o = t0 + i * M.MIN30
        bars.append([o, 100.0, 100.4, 99.6, 100.0] if o != K(26, 12) else [o, 100.0, 100.2, 98.5, 98.8])     # the stop at 12:00
    import numpy as np
    b30 = {"SOLUSDT": np.array(bars, dtype=float)}
    co = M.Coin("SOLUSDT", 8.0, 2.0, 150.0, 40)
    no_spec = lambda s: {"qty_step": 0.0, "min_qty": 0.0, "tick": 0.0, "min_notional": 0.0}      # noqa: E731
    decided = {"SOLUSDT": {K(26, 10): W.ev("SOLUSDT", K(26, 10), 1, close=100.0, dist=1.0)}}
    res = R.run_bot([co], decided, b30, fee=R.TAKER, blocks=True, spec_fn=no_spec)
    (t,) = R.trades(res["rows"], 0.25)
    assert (t["symbol"], t["side"], t["why"], t["opened_ms"]) == ("SOLUSDT", 1, "stop", K(26, 10, 0, 5))
    loss = 0.125 * 1.0 + R.TAKER * 0.125 * (100.0 + 99.0)
    assert t["pnl"] == pytest.approx(-loss) and t["r"] == pytest.approx(-loss / 0.125)
    assert [m for m, _ in res["month_eq"]] == ["2026-10"] and res["end_eq"] == pytest.approx(50.0 - loss)
    # a Saturday signal (10/24 is outside this window: move the window to the weekend)
    monkeypatch.setattr(R, "T0", K(24))
    monkeypatch.setattr(R, "T1", K(25, 12))
    sat = {"SOLUSDT": {K(24, 10): W.ev("SOLUSDT", K(24, 10), 1, close=100.0, dist=1.0)}}
    blocked = R.run_bot([co], sat, b30, fee=R.TAKER, blocks=True, spec_fn=no_spec)
    assert R.trades(blocked["rows"], 0.25) == [] and R.skip_counts(blocked["rows"])["block_weekend"] == 1
    free = R.run_bot([co], sat, b30, fee=R.TAKER, blocks=False, spec_fn=no_spec)
    assert any(r["kind"] == "entry" for r in free["rows"])
    # the numbers the band reads
    rs = [-1.0, -1.0, 2.0, -1.0, -1.0, -1.0, 3.0]
    assert R.streak_runs(rs) == [2, 3] and R.drawdowns_r(rs)[1] == pytest.approx(3.0)
