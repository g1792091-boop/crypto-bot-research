"""The second paper bot MEXC follows (owners 10-19, final: "Mexc -35%로 가자"; docs/live15-mexc-ko.md):
deploy/combo.live15-mexc.json is 규칙봇 15 (deploy/combo.live15.json) with the stop at -35 % net ROE instead of -50 %, its
own database and name. Bybit follows the -50 % bot, MEXC this one (deploy/executor.live-*.json): the two-week A/B test of
the stop until the 11/3 review. MEXC switches over while flat (tests/test_executor_paper_switch.py proves the switch).

- the two configs differ only in the stop, the database and the name; both are clean and check-config says 준비됨;
- the -35 % net stop: its distance (fees and slippage of both sides in) and its realised ROE in the engine;
- a stop change on restart keeps the open position's stop and applies to the next entry;
- its systemd unit: paperbot-combo's sandbox and protection, its own config, never enabled by install.sh, not combo2."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperbot import combo as C
from tests.test_combo_live15 import BRACKETS, MIN, SPECS, T0, _bar, _sig

ROOT = Path(__file__).resolve().parent.parent
DEPLOY = ROOT / "deploy"
CFG15 = DEPLOY / "combo.live15.json"
CFG35 = DEPLOY / "combo.live15-mexc.json"


def _raw(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_only_the_stop_the_database_and_the_name_differ():
    a, b = _raw(CFG15), _raw(CFG35)
    assert {k for k in set(a) | set(b) if a.get(k) != b.get(k)} == {"stop", "db", "name"}
    assert b["stop"] == {"mode": "roe", "roe": 0.35, "net": True} and a["stop"] == {"mode": "roe", "roe": 0.5, "net": True}
    assert b["db"] == "/var/lib/paperbot/combo/live15-mexc.db" != a["db"]
    assert b["paper_db"] == a["paper_db"] == "/var/lib/paperbot/paper3.db"      # the same rule-bot bars and signals
    assert b["name"] == "규칙봇 15 −35%"
    # start and error lines still reach the owners; the coin-flip twin gives the -35 % bot its own yardstick
    assert b["telegram"] is True and b["flip_twin"] is True
    cfg = C.ComboConfig.from_dict(b)
    assert cfg.problems() == [] and cfg.stop_net and cfg.tag == "[합친 봇 페이퍼 규칙봇 15 −35%]"
    assert [m.label for m in C.resolve_members(cfg.members)] == [m.label for m in C.resolve_members(_raw(CFG15)["members"])]


def test_mexc_follows_it_and_bybit_the_minus_50_bot():
    by = _raw(DEPLOY / "executor.live-bybit.json")
    mx = _raw(DEPLOY / "executor.live-mexc.json")
    assert by["paper_db"] == _raw(CFG15)["db"] and mx["paper_db"] == _raw(CFG35)["db"] != by["paper_db"]
    assert by["account"] == mx["account"] == C.ACCOUNT          # the same account name in both paper databases


def test_check_config_says_ready_with_the_minus_35_stop(capsys):
    assert C.main(["check-config", "--config", str(CFG35)]) == 0
    out = capsys.readouterr().out
    # 0.35 / 40 - 0.14 % = 0.735 % (printed 0.73 %), 0.35 / 30 - 0.14 % = 1.027 %
    for want in ("자기 DB: /var/lib/paperbot/combo/live15-mexc.db", "순ROE -35%(수수료·슬리피지 포함: 40배 가격 0.73%, 30배 가격 1.03%)",
                 "15%에서 12%", "첫 잠금 +10% 전까지만", "추격 진입 막기: 4개 매매법", "동전 쌍둥이 계좌: 있음"):
        assert want in out, want
    assert out.strip().splitlines()[-1] == "준비됨"


def test_the_start_message_names_the_bot_and_its_stop():
    cfg = C.ComboConfig.from_file(str(CFG35))
    text = C.start_text(cfg, C.resolve_members(cfg.members, cfg.picks_file), 1000.0)
    assert text.startswith("[합친 봇 페이퍼 규칙봇 15 −35%] 시작: 매매법 15개, BTC 40배·나머지 30배, 증거금 잔고의 40%, "
                           "손절 순ROE -35%(수수료·슬리피지 포함: 40배 가격 0.73%, 30배 가격 1.03%), ")


def _engine(tmp_path):
    raw = _raw(CFG35)
    raw.update(paper_db=str(tmp_path / "paper3.db"), db=str(tmp_path / "combo.db"), telegram=False)
    cfg = C.ComboConfig.from_dict(raw)
    return C.ComboEngine(C.settings_of(cfg), BRACKETS, combo=cfg, symbol_specs=SPECS)


def test_net_minus_35_stop_distance_and_its_realised_roe(tmp_path):
    e = _engine(tmp_path)
    rt = e.s.round_trip_cost
    assert rt == pytest.approx(0.0014)
    s, why = e._with_stop(_sig("BTCUSDT"), _bar("BTCUSDT", T0, 60000.0))
    assert why is None and s.meta["stop_dist"] == pytest.approx(60000 * (0.35 / 40 - rt))
    assert s.meta["stop_dist"] / 60000 == pytest.approx(0.00735)                  # BTC 40x: 0.735 % of the price
    s, _ = e._with_stop(_sig("SOLUSDT"), _bar("SOLUSDT", T0, 150.0))
    assert s.meta["stop_dist"] == pytest.approx(150 * (0.35 / 30 - rt))
    assert s.meta["stop_dist"] / 150 == pytest.approx(0.0102667, rel=1e-4)        # alts 30x: 1.03 % of the price
    # the exchange's own ROE at that stop (price move x leverage, no costs): about -29 % (BTC) and -31 % (alts)
    assert 40 * (0.35 / 40 - rt) == pytest.approx(0.294) and 30 * (0.35 / 30 - rt) == pytest.approx(0.308)
    for sym, px, lev in (("BTCUSDT", 60000.0, 40), ("SOLUSDT", 150.0, 30)):
        e = _engine(tmp_path)
        e.submit(_sig(sym, ref=px))
        e.step({sym: _bar(sym, T0, px)})
        p = e.position
        assert p is not None and p.leverage == lev
        # the stop sits 0.35 / leverage - round trip below the signal's reference price (the fill pays the slippage)
        assert (px - p.stop_price) / px == pytest.approx(0.35 / lev - rt, rel=1e-6)
        e.step({sym: _bar(sym, T0 + MIN, px, l=px * 0.985, c=px * 0.988)})
        assert e.position is None
        t = e.trades[-1]
        assert t.exit_reason == "SL" and t.roe == pytest.approx(-0.35, abs=0.006), (sym, t.roe)
        # 30 % margin: one -35 % stop costs about 10.5 % of the account (-50 %: about 15 %)
        assert 0.13 < -t.pnl / 1000 < 0.15


def test_a_bar_that_stops_the_minus_35_bot_leaves_the_minus_50_bot_open(tmp_path):
    """The two bots part where the price goes between the two stops (the stops.py replay: 4 of 54 shared entries)."""
    from tests import test_combo_live15 as L15
    e35, e50 = _engine(tmp_path), L15._engine(L15._cfg(tmp_path))
    for e in (e35, e50):
        e.submit(_sig("BTCUSDT", ref=60000.0))
        e.step({"BTCUSDT": _bar("BTCUSDT", T0, 60000.0)})
    low = 60000.0 * (1 - 0.009)                                                     # -0.9 %: past 0.735 %, short of 1.11 %
    for e in (e35, e50):
        e.step({"BTCUSDT": _bar("BTCUSDT", T0 + MIN, 60000.0, l=low, c=low * 1.001)})
    assert e35.position is None and e35.trades[-1].exit_reason == "SL"
    assert e50.position is not None and not e50.trades


def _unit(name: str) -> dict:
    out: dict = {}
    sec = ""
    for ln in (DEPLOY / name).read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        if ln.startswith("["):
            sec = ln
            continue
        out.setdefault(sec, []).append(ln)
    return out


def test_its_unit_is_paperbot_combos_sandbox_with_its_own_config():
    main, mine = _unit("paperbot-combo.service"), _unit("paperbot-combo-mexc.service")
    exec_ = [ln for ln in mine["[Service]"] if ln.startswith("ExecStart=")]
    assert exec_ == ["ExecStart=/opt/paperbot/venv/bin/python -m paperbot.combo run --config /etc/paperbot/combo-mexc.json"]
    # everything else of [Service] is paperbot-combo's (user, sandbox, folders, memory, protection), plus the raw-line switch
    same = lambda lines: [ln for ln in lines if not ln.startswith(("ExecStart=", "Environment=PAPERBOT_COMBO_TRADE_MSGS"))]  # noqa: E731
    assert same(mine["[Service]"]) == same(main["[Service]"])
    assert "Environment=PAPERBOT_COMBO_TRADE_MSGS=0" in mine["[Service]"]
    assert "OOMScoreAdjust=-500" in mine["[Service]"] and "ReadWritePaths=/var/lib/paperbot/combo" in mine["[Service]"]
    assert mine["[Install]"] == main["[Install]"]
    inst = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert 'install -m 644 "$APP/deploy/paperbot-combo-mexc.service" /etc/systemd/system/paperbot-combo-mexc.service' in inst
    assert "enable --now paperbot-combo-mexc" not in inst and "start paperbot-combo-mexc" not in inst
    units = next(ln for ln in inst.splitlines() if ln.startswith("UNITS="))
    assert "paperbot-combo-mexc" in units.split('"')[1].split()                  # stopped for the code swap, started again
    # never the second combined bot's unit or config (it may run something else on the server)
    assert "combo2" not in (DEPLOY / "paperbot-combo-mexc.service").read_text(encoding="utf-8").split("[Unit]")[1]


def test_a_stop_change_keeps_the_open_position_and_applies_to_the_next_entry(tmp_path):
    """docs/live15-mexc-ko.md (changing the stop later): the stop is set at the entry only (ComboEngine._with_stop);
    after a restart with a new stop in the config the open position keeps its stop (restored from the database, only the
    ladder moves it), and the next entry takes the new one (here -35 % -> -50 %)."""
    import dataclasses as dc

    from paperbot.store3 import Store3
    from tests.test_combo_live15 import HOUR, World
    stop35 = {"mode": "roe", "roe": 0.35, "net": True}
    w = World(tmp_path, stop=stop35, name="규칙봇 15 −35%")
    w.now = T0 + 5_000
    w.run.poll()
    B = T0 + HOUR
    w.signal("V39_ALL@1h", "BTCUSDT", 1, B)
    w.step_to(B)
    w.step_to(B + MIN)
    p = w.book.engines[C.ACCOUNT].position
    assert p is not None and p.signal.meta.get("stop_rule") == "ROE -35% net at 40x"
    s35 = p.stop_price
    w.store.close()
    # a change: stop roe 0.35 -> 0.50 in combo-mexc.json, then a restart of the paper bot
    cfg50 = dc.replace(w.cfg, stop={"mode": "roe", "roe": 0.50, "net": True})
    store = Store3(cfg50.db)
    book = C.build_book(cfg50, C.settings_of(cfg50), BRACKETS, store, w.note, SPECS)
    q = book.engines[C.ACCOUNT].position
    assert q is not None and q.stop_price == s35 and q.entry_time == p.entry_time        # kept as it was
    w.store, w.book, w.cfg = store, book, cfg50
    w.run = C.ComboRunner(cfg50, w.members, book, store, w.note, None, now_ms=lambda: w.now, prices=lambda: {})
    # the price opens just under the -35 % stop: closed on that stop (not held to -50 %; the gap costs a little more)
    t_low = w.book.last_ts + MIN
    w.add_minutes(t_low, 1, px={"BTCUSDT": s35 * 0.999})
    w.now = t_low + 65_000
    w.run.poll()
    e = w.book.engines[C.ACCOUNT]
    t = e.trades[-1]
    assert e.position is None and t.exit_reason == "SL" and t.stop_price == s35 and -0.45 < t.roe < -0.35
    # the next entry takes the -50 % stop
    B2 = B + 2 * HOUR
    w.signal("V39_ALL@1h", "BTCUSDT", 1, B2)
    w.step_to(B2)
    w.step_to(B2 + MIN)
    p2 = w.book.engines[C.ACCOUNT].position
    assert p2 is not None and p2.signal.meta.get("stop_rule") == "ROE -50% net at 40x"
    ref = p2.signal.meta["ref_price"]
    assert (ref - p2.stop_price) / ref == pytest.approx(0.50 / 40 - 0.0014, rel=1e-6)    # 1.11 % of the price
    store.close()
