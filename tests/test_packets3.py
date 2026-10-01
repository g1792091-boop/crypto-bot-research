import json

from paperbot.agents.packets3 import profile_card, specialist_packet


def test_specialist_packet_keeps_only_its_strategy(tmp_path):
    cards = tmp_path / "cards.json"
    cards.write_text(json.dumps({"meta": {}, "cards": [
        {"strategy": "N18_VWMA_MACD", "name_ko": "VWMA·MACD", "style": "추세 따라가기", "trend_share": 0.86371,
         "hold": "스윙 쪽", "least_bad_tf": "4h", "rare": False,
         "rows": [{"tf": "1h", "mean_roe": -0.037512345, "hold_verdict": "더 들고 갔으면 나았음"}]}]}))
    packet = {"meta": {"days_running": 3}, "league": {"1h": {}},
              "pass_check": {"N18_VWMA_MACD@1h": {"trades": 4}, "N17_KC_RSI@1h": {"trades": 9}},
              "by_strategy": {"N18_VWMA_MACD": {"1h": {"trades": 4}}, "N17_KC_RSI": {}}}
    sp = specialist_packet(packet, "N18_VWMA_MACD", str(cards))
    assert list(sp["pass_check"]) == ["N18_VWMA_MACD@1h"]
    assert sp["by_strategy"] == {"1h": {"trades": 4}}
    assert sp["profile"]["style"] == "추세 따라가기" and sp["profile"]["trend_share"] == 0.864
    assert sp["profile"]["rows"][0]["mean_roe"] == -0.0375
    assert profile_card("N17_KC_RSI", str(cards)) is None
    assert profile_card("N18_VWMA_MACD", str(tmp_path / "missing.json")) is None


def test_committed_cards_cover_all_36_strategies():
    from paperbot.agents.roster3 import STRATEGY_KO
    for name in STRATEGY_KO:
        c = profile_card(name)
        assert c is not None and len(c["rows"]) == 5, name


def test_default_cards_are_the_binance_futures_version():
    from paperbot.agents.packets3 import CARDS, CARDS_BINANCE
    assert CARDS == CARDS_BINANCE
    assert profile_card("N17_KC_RSI")["data_source"] == "binance_futures"


def test_parent_packet_labels_copy_trades(tmp_path):
    """Copy accounts (and new-strategy accounts) are reported in their own 'extras' section, labelled; every
    other section of the board is the 195's own numbers."""
    from paperbot.agents.packets3 import build
    from paperbot.store3 import Store3
    from test_rooms import rec
    S, now = "N17_KC_RSI", 1_790_000_000_000
    path = str(tmp_path / "paper3.db")
    st = Store3(path)
    st.add_account(f"{S}@15m", S, "15m", "strategy", now - 30 * 86_400_000, "paper-v3")
    st.add_account("RANDOM_1@15m", "RANDOM_1", "15m", "random", now - 30 * 86_400_000, "paper-v3")
    src = {"proposal_id": 12, "proposal_ts": 1, "trial_id": 42, "trial_ts": 1, "content": "copy:{}"}
    st.add_account(f"{S}@15m~c1", S, "15m", "copy", now - 86_400_000, "paper-v3", parent=f"{S}@15m",
                   data={"v": 1, "kind": "copy", "source": src, "rule": {"template": "stop_atr", "k": 2.5},
                         "label_ko": "켈트너·RSI 15분 복제 c1 · 손절 2.5 ATR"})
    st.add_account("NL1@1h", "NL1", "1h", "newlab", now - 86_400_000, "paper-v3",
                   data={"v": 1, "kind": "newlab", "source": {**src, "proposal_id": 13}, "spec": {"timeframe": "1h"},
                         "description_ko": "1시간 RSI 되돌림", "label_ko": "새 매매법 NL1 (장부 #57) · 1시간"})
    st.trade(f"{S}@15m", rec(S, "15m", 5.0, now - 3_600_000))
    for k in range(3):
        st.trade(f"{S}@15m~c1", rec(S, "15m", -4.0, now - 7_200_000 + k))
    st.trade("NL1@1h", rec("NL1", "1h", 2.0, now - 3_600_000))
    st.put_state("accounts", now, {"engines": {f"{S}@15m": {"wallet": 5005.0}, f"{S}@15m~c1": {"wallet": 4988.0},
                                               "NL1@1h": {"wallet": 5002.0, "bust": False}}})
    st.put_state("extras", now, {"v": 1, "accounts": {"NL1@1h": {"status": "suspended"}}})
    st.log_signals([{"bar_close": now - 900_000, "timeframe": "15m", "strategy": S, "symbol": "BTCUSDT", "side": 1,
                     "atr": 1.0, "ref_price": 100.0, "ref_time": now, "delay_ms": 5000, "status": "SUBMITTED"},
                    {"bar_close": now - 900_000, "timeframe": "1h", "strategy": "NL1", "symbol": "BTCUSDT", "side": 1,
                     "atr": 1.0, "ref_price": 100.0, "ref_time": now, "delay_ms": 5000, "status": "SUBMITTED"}])
    st.commit()
    b = build(path, None, now)
    assert b["meta"]["accounts"] == 2 and b["meta"]["extra_accounts"] == 2
    assert list(b["pass_check"]) == [f"{S}@15m"] and b["by_strategy"][S]["15m"]["trades"] == 1
    assert b["today"]["trades"] == 1 and b["execution"]["net_pnl_total"] == 5.0
    assert [s["timeframe"] for s in b["execution"]["signals"]] == ["15m"]          # the NL1 row is not the 195's
    ex = {e["account_id"]: e for e in b["extras"]}
    c = ex[f"{S}@15m~c1"]
    assert c["kind"] == "copy" and c["parent"] == f"{S}@15m" and c["trades"] == 3 and c["wallet"] == 4988.0
    assert c["label"] == f"copy: {S}@15m~c1, rule 손절 2.5 ATR" and c["rule_ko"] == "손절 2.5 ATR"
    assert c["proposal_id"] == 12 and c["status"] == "active" and c["trades_24h"] == 3
    n = ex["NL1@1h"]
    assert n["kind"] == "newlab" and n["status"] == "suspended" and n["description_ko"] == "1시간 RSI 되돌림"
    sp = specialist_packet(b, S, str(tmp_path / "missing.json"))
    assert [x["account_id"] for x in sp["copies"]] == [f"{S}@15m~c1"] and list(sp["pass_check"]) == [f"{S}@15m"]
    assert specialist_packet(b, "V45_AMB", str(tmp_path / "missing.json"))["copies"] == []
