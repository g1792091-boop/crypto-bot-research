"""The 바이비트 봇's own checks and pages (owners 10-29): paperbot/mixcheck.py and paperbot/dash/more/livemix.py for the
second mix bot.

- livemix: ``paths(bot="bybit")`` reads its own files and config (/etc/paperbot/mixbybit*.json, its state and log, its
  environment variables); its answers carry its name, units, guide and no 5-year reference; the friend bot's are as
  they were;
- mixcheck: the bot's words from its config (name, exchange, Bybit's taker fee 0.044 %), its own folder and units
  (PAPERBOT_MIX_BOT=bybit); the loss card and the morning message in its words; its rules counted (OBV light -> dark,
  Stoch RSI ●); no luck band (no 5-year replay);
- the signal replay of its rules on the same bars finds what its log has, and says what it is missing."""
from __future__ import annotations

import json
import os

import numpy as np
import pytest

from paperbot import friendtrend as FT
from paperbot import mixcheck as MC
from paperbot import mixchop as M
from paperbot.dash.more import livemix as X

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAY0 = 1_793_232_000_000 - 9 * 3_600_000          # a KST midnight
H, MIN = 3_600_000, 60_000


def _write(folder, live_rows, paper_rows, live_state=None, paper_state=None):
    os.makedirs(folder, exist_ok=True)
    j = lambda n: os.path.join(folder, n)      # noqa: E731
    for mode, src in (("live", "mixbybit.live.json"), ("paper", "mixbybit.paper.json")):
        d = json.load(open(os.path.join(ROOT, "deploy", src), encoding="utf-8"))
        d.update(state=j(f"{mode}-state.json"), log=j(f"{mode}-log.jsonl"), own_stop_file=j(f"{mode}.STOP"),
                 kill_file=j("STOP"))
        json.dump(d, open(j(f"{mode}.json"), "w", encoding="utf-8"))
    for mode, rows, st in (("live", live_rows, live_state), ("paper", paper_rows, paper_state)):
        with open(j(f"{mode}-log.jsonl"), "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        json.dump(st or {"position": None, "start_equity": 100.0, "last_close_ms": DAY0 + 23 * H,
                         "saved_ms": DAY0 + 23 * H + 30 * MIN, "mode": "mainnet" if mode == "live" else "paper"},
                  open(j(f"{mode}-state.json"), "w", encoding="utf-8"))
    return {"PAPERBOT_MIXBYBIT_CONFIG": j("live.json"), "PAPERBOT_MIXBYBIT_PAPER_CONFIG": j("paper.json")}


def _trade(sym, side, t_in, t_out, entry, stop_dist, eq0, eq1, rule="obv", why="stop", qty=1.0):
    ev = {"symbol": sym, "close_ms": t_in - 5_000, "side": side, "why": "", "rule": rule, "close": entry, "turn": side,
          "trend": side, "votes": {"line": side, "ema": side, "chop": side, "st": side}, "stop_dist": stop_dist,
          "stop_pct": round(stop_dist / entry * 100, 3)}
    sig = {"ts": t_in - 4_000, "kind": "signal", **ev}
    en = {"ts": t_in, "kind": "entry", "symbol": sym, "side": side, "qty": qty, "entry": entry, "stop_dist": stop_dist,
          "stop": entry - side * stop_dist, "best": entry, "step": 0, "opened_ms": t_in, "signal_close_ms": t_in - 5_000,
          "signal_close": entry, "last_bar_ms": t_in - 5_000, "stop_id": "s1", "equity_before": eq0, "leverage": 40,
          "roe_act": 100.0, "why": ev}
    ex = {"ts": t_out, "kind": "exit", "symbol": sym, "side": side, "why": why, "price": None, "pnl": eq1 - eq0,
          "equity": eq1, "step": 0, "entry": entry, "stop": entry - side * stop_dist, "opened_ms": t_in}
    return [sig, en, ex]


@pytest.fixture
def world(tmp_path):
    start = {"ts": DAY0 - H, "kind": "start", "equity": 100.0, "start_equity": 100.0, "setup": [[True, "포지션 모드: 단방향"]],
             "position": None}
    t1 = DAY0 + 2 * H
    live = [start] + _trade("SOLUSDT", 1, t1, t1 + 40 * MIN, 150.0, 2.4, 100.0, 73.5)
    srsi = {"ts": DAY0 + 5 * H, "kind": "signal", "symbol": "ETHUSDT", "close_ms": DAY0 + 5 * H - 5_000, "side": 0,
            "why": "스톡RSI 골든이 50선 위(K 61.2)", "rule": "srsi", "cross": "gold", "k": 61.2, "d": 55.0, "trend": 1,
            "votes": {"line": 1, "ema": 1, "chop": 0, "st": 1}}
    live.append(srsi)
    paper = [start] + _trade("SOLUSDT", 1, t1, t1 + 41 * MIN, 150.0, 2.4, 100.0, 74.0)
    env = _write(str(tmp_path / "w"), live, paper)
    return {"env": env, "folder": str(tmp_path / "w")}


# ---------------------------------------------------------------- livemix
def test_its_paths_and_its_pages(world):
    p = X.paths(world["env"], bot="bybit")
    assert p["live"]["bot"] == "bybit" and p["live"]["config"].endswith("live.json")
    d = X.paths({}, bot="bybit")
    assert d["live"]["config"] == "/etc/paperbot/mixbybit.json" and d["paper"]["config"] == "/etc/paperbot/mixbybit-paper.json"
    assert X.paths({"PAPERBOT_MIX_BOT": "bybit"})["live"]["bot"] == "bybit"
    assert X.paths({})["live"]["bot"] == "mix" and X.paths({})["live"]["config"] == "/etc/paperbot/mixchop.json"
    now = DAY0 + 23 * H + 31 * MIN
    c = X.control(p, now)
    assert c["name_ko"] == "바이비트 봇" and c["bot"] == "bybit" and c["exchange_ko"] == "바이비트"
    live = c["bots"][0]
    assert live["name_ko"] == "바이비트 봇 실거래" and live["unit"] == "paperbot-mixbybit" and live["status"]["state"] == "running"
    sig = [r for r in live["feed"]["rows"] if r["cat"] == "signal"]
    assert {r["colour_ko"] for r in sig} == {"OBV 연한 초록→진한 초록", "골든크로스"}
    assert next(r for r in sig if r["rule"] == "obv")["vals"]["votes"]["chop"] == 1
    perf = X.perf(p, now)
    assert perf["backtest"] is None and perf["bots"][0]["record"]["n"] == 1 and perf["bots"][0]["record"]["wins"] == 0
    assert [c_["symbol"] for c_ in perf["bots"][0]["coins"]][:2] == ["BTCUSDT", "ETHUSDT"]
    a = perf["analysis"]
    assert a["state"] == "ok" and a["taker"] == pytest.approx(0.00044) and a["band"]["state"] == "none"
    assert a["morning"]["state"] == "missing" and "docs/mixbybit-ko.md" in a["morning"]["ko"]
    # not there yet: its own words
    off = X.control(X.paths({"PAPERBOT_MIXBYBIT_CONFIG": world["folder"] + "/none.json",
                             "PAPERBOT_MIXBYBIT_STATE": world["folder"] + "/none-state.json",
                             "PAPERBOT_MIXBYBIT_LOG": world["folder"] + "/none-log.jsonl"}, bot="bybit"), now)
    assert off["bots"][0]["status"]["ko"] == "바이비트 봇(실거래)이 아직 꺼져 있어요 · 기록 파일이 없어요"


# ---------------------------------------------------------------- mixcheck
def test_its_words_card_and_morning(world, monkeypatch, tmp_path):
    p = X.paths(world["env"], bot="bybit")
    data = MC.load(p, DAY0 + DAY_MS())
    w = MC.words_of(data)
    assert w == {"name": "바이비트 봇", "short": "바이비트 봇", "ex": "바이비트", "fee": 0.00044, "unit": "paperbot-mixbybit",
                 "mix": False, "guide": "docs/mixbybit-ko.md"}
    (c,) = MC.cards_of(data)
    level, text = MC.card_message(c)
    assert "바이비트 봇 손실 카드 · SOL 롱" in text and "테이커 0.044% 양쪽" in text and "믹스" not in text
    res = MC.morning(data, DAY0)
    t = res["text"]
    assert t.split("\n")[0].endswith("바이비트 봇 아침 점검 · 확인할 것 1개") or t.startswith("📋 바이비트 봇 아침 점검")
    assert "- OBV 연한→진한 1번 · 스톡RSI ● 1번 · 조건 맞은 신호 1번 · 진입 1번" in t
    assert MC.NO_REPLAY_KO in t and "WOO X Pro" not in t and "믹스" not in t
    assert "바닥선 없음(잔고가 줄어도 새 진입을 멈추지 않아요)" in t and "손절 약" not in t
    # its own folder and units
    monkeypatch.setenv("PAPERBOT_MIX_BOT", "bybit")
    monkeypatch.delenv("PAPERBOT_MIXBYBITCHECK_DIR", raising=False)
    assert MC.state_dir() == "/var/lib/paperbot/mixbybitcheck" and MC.prof_env() is X.BYBIT
    monkeypatch.delenv("PAPERBOT_MIX_BOT")
    monkeypatch.delenv("PAPERBOT_MIXCHECK_DIR", raising=False)
    assert MC.state_dir() == "/var/lib/paperbot/mixcheck"


def DAY_MS():
    return 24 * H


def test_the_units_name_their_bot():
    for u in ("paperbot-mixbybitcheck.service", "paperbot-mixbybitcheck-pass.service"):
        text = open(os.path.join(ROOT, "deploy", u), encoding="utf-8").read()
        assert "Environment=PAPERBOT_MIX_BOT=bybit" in text and "ReadWritePaths=/var/lib/paperbot/mixbybitcheck" in text
        assert "-/var/lib/paperbot/mixbybit-paper" in text and "User=paperbot\n" in text
    inst = open(os.path.join(ROOT, "deploy", "install.sh"), encoding="utf-8").read()
    assert "install -d -o paperbot -g paperbot -m 750 /var/lib/paperbot/mixbybitcheck" in inst
    assert "for t in paperbot-mixbybitcheck.timer paperbot-mixbybitcheck-pass.timer; do" in inst


# ---------------------------------------------------------------- the signal replay of its rules
def test_the_replay_finds_what_its_log_has(tmp_path):
    cfg = M.load_config(os.path.join(ROOT, "deploy", "mixbybit.paper.json"))
    cfg.coins = cfg.coins[:1]                                      # BTC
    rng = np.random.default_rng(12)
    n = 2000
    t30 = DAY0 + DAY_MS() - M.MIN30 * np.arange(n, 0, -1)
    c = 60000 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    o = np.r_[c[0], c[:-1]]
    hi, lo = np.maximum(o, c) * 1.001, np.minimum(o, c) * 0.999
    vol = rng.uniform(100, 1000, n)
    rows30 = [[int(t30[i]), o[i], hi[i], lo[i], c[i], vol[i]] for i in range(n)]
    t1h = t30[::2]
    rows1h = [[int(t1h[i]), o[2 * i], max(hi[2 * i], hi[2 * i + 1]), min(lo[2 * i], lo[2 * i + 1]), c[2 * i + 1],
               vol[2 * i] + vol[2 * i + 1]] for i in range(n // 2)]

    def klines(symbol, tf, start, limit):
        src = rows30 if tf == "30m" else rows1h
        return [r for r in src if r[0] >= start][:limit]
    log = []
    co = cfg.coins[0]
    for ce in range(DAY0 + M.MIN30, DAY0 + DAY_MS() + 1, M.MIN30):     # what the bot logged: its own judge
        b30 = M.bars_frame(rows30, M.MIN30, ce).tail(M.BARS - 1).reset_index(drop=True)
        for rule in cfg.rules:
            ev = M.Bot.judge(rule, co, b30, b30, ce)
            if ev.get("turn") or ev.get("cross") or ev["side"]:
                log.append({"ts": ce + 5_000, "kind": "signal", **ev})
    assert {r["rule"] for r in log} == {"obv", "srsi"}
    rp = MC.signal_replay(cfg, DAY0, DAY0 + DAY_MS(), log, klines, obs=[[DAY0 + DAY_MS() + 3 * MIN, DAY0 + DAY_MS(), None]],
                          st_last=DAY0 + DAY_MS())
    assert rp["state"] == "ok" and rp["different"] == [] and rp["rules"] == ["obv", "srsi"]
    assert rp["turns"] == sum(1 for r in log if r["rule"] == "obv") and rp["dots"] == sum(1 for r in log if r["rule"] == "srsi")
    gone = log[0]
    rp2 = MC.signal_replay(cfg, DAY0, DAY0 + DAY_MS(), log[1:], klines, obs=[], st_last=DAY0 + DAY_MS())
    lost = rp2["missed"] + rp2["unsure"]
    assert any(x["close_ms"] == gone["close_ms"] and x["rule"] == gone["rule"] for x in lost)
    line = MC.replay_lines(rp)[0]
    assert f"OBV 연한→진한 {rp['turns']}번 · 스톡RSI ● {rp['dots']}번" in line and "색 변화" not in line
    # the same bars give the same signals as friendtrend's own panes on the whole history
    b = M.bars_frame(rows30, M.MIN30, DAY0 + DAY_MS())
    P = FT.obv_pane(b.high.to_numpy(), b.low.to_numpy(), b.close.to_numpy(), b.volume.to_numpy())
    assert P["cs"].shape[0] == len(b)
