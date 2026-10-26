"""믹스 30분 봇, owners 10-26 ("시드비중 40%", "12%도달하면 10% 17%도달하면 15% 22%도달하면 20%"): the site
(paperbot/dash/more/livemix.py) and the morning check / loss cards (paperbot/mixcheck.py) read a config sized by margin
with the net-ROE ladder: R per trade is the entry's own loss at the stop, the ladder is shown on net ROE, and the
5-year luck band (made with the old sizing and ladder) is not given."""
from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from paperbot import mixcheck as K
from paperbot import mixchop as M
from paperbot.dash.more import livemix as X


def _cfg(tmp_path, **extra):
    raw = {"mode": "mainnet", "state": str(tmp_path / "s.json"), "log": str(tmp_path / "l.jsonl"), "start_equity": 50.0,
           "telegram": False, "coins": {"SOLUSDT": {}}, "max_notional_usd": 10000, "margin_frac": 0.4,
           "ladder": {"trigger": 12, "lock": 10, "step": 5}, "ladder_every_s": 60, **extra}
    p = tmp_path / "c.json"
    p.write_text(json.dumps(raw))
    return M.load_config(str(p))


def _rows():
    en = {"kind": "entry", "ts": 1000, "symbol": "SOLUSDT", "side": 1, "qty": 8.0, "entry": 100.0, "stop_dist": 1.0,
          "stop": 99.0, "best": 100.0, "step": 0, "opened_ms": 1000, "signal_close_ms": 900, "signal_close": 100.0,
          "last_bar_ms": 900, "equity_before": 50.0, "leverage": 40, "roe_act": 150.0,
          "why": {"stop_pct": 1.0, "close": 100.0, "close_ms": 900}}
    ex = {"kind": "exit", "ts": 5000, "symbol": "SOLUSDT", "side": 1, "why": "stop", "price": 99.0, "pnl": -8.3,
          "equity": 41.7, "step": 0, "entry": 100.0, "stop": 99.0, "opened_ms": 1000}
    return [en, ex]


def test_r_is_the_entrys_own_loss_at_the_stop(tmp_path):
    cfg = _cfg(tmp_path)
    t = X.trades_of(_rows(), cfg)[0]
    assert t["pnl"] == pytest.approx(-8.3) and t["r"] == pytest.approx(-8.3 / 8.0)      # not -8.3 / (50 x 0.25 %)
    old = _cfg(tmp_path, margin_frac=0, ladder=None)
    assert X.trades_of(_rows(), old)[0]["r"] == pytest.approx(-8.3 / (50 * 0.25 / 100))  # the design's sizing: as before


def test_position_and_rules_on_net_roe(tmp_path):
    cfg = _cfg(tmp_path)
    p = M.Position(symbol="SOLUSDT", side=1, qty=8.0, entry=100.0, stop_dist=1.0, stop=99.0, best=100.30, step=0,
                   opened_ms=1000, signal_close_ms=900, signal_close=100.0, last_bar_ms=900, leverage=40)
    v = X.position_view("live", {"position": asdict(p)}, 10_000, cfg)
    fee = cfg.taker_fee
    assert v["ladder_basis"] == "net" and v["roe_act"] == pytest.approx(0.12) and v["lock_roe"] == pytest.approx(0.10)
    assert v["first_lock_price"] == pytest.approx(100 * (1 + 0.10 / 40 + 2 * fee))
    n = v["next"]
    assert (n["step"], n["basis"], n["reached"]) == (1, "net", False)
    assert n["trigger"] == pytest.approx(100 * (1 + 0.12 / 40 + 2 * fee))
    p.step, p.stop = 2, 100 * (1 + 0.15 / 40 + 2 * fee)                                 # at the 17 -> 15 step
    n2 = X.position_view("live", {"position": asdict(p)}, 10_000, cfg)["next"]
    assert n2["trigger_roe"] == pytest.approx(0.22) and n2["stop_to_roe"] == pytest.approx(0.20) and n2["step"] == 3
    r = X.rules_view({"cfg": cfg, "source": "server"})
    assert r["margin_frac"] == 0.4 and r["ladder"] == {"trigger": 0.12, "lock": 0.10, "step": 0.05}
    assert r["plan_ko"].startswith("진입마다 증거금 = 잔고의 40% · 계단 순ROE +12%→+10%, +17%→+15%, +22%→+20%")
    assert M.plan_words(cfg, short=True) == "증거금 잔고의 40% · 계단 12→10·17→15…"


def test_morning_check_band_and_card(tmp_path):
    cfg = _cfg(tmp_path)
    data = {"live": {"lg": {"state": "ok", "rows": _rows()}, "conf": {"cfg": cfg}}, "now": 10_000}
    b = K.live_band(data, None, 10_000)
    assert b["state"] == "changed" and "5년 재생과 비교하지 않아요" in b["ko"]
    assert K.band_lines(b) == [f"- {K.PLAN_CHANGED_KO}"]
    rows = _rows()
    t = X.trades_of(rows, cfg)[0]
    c = K.card(t, rows[0], rows, cfg, 0.25)
    assert c["risk_usd"] == pytest.approx(8.0) and c["risk_pct"] == pytest.approx(16.0)
    assert any(x.startswith("계획: 진입마다 증거금 잔고의 40% · 이번 손절 1번 = 잔고의 16.0% ($8") for x in K.card_lines(c))
