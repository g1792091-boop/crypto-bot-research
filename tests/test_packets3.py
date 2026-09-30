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
