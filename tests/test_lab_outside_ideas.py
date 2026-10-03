from paperbot.agents import newlab as NL
from paperbot.agents import rooms as R


def test_every_outside_idea_is_inside_the_grammar_on_every_timeframe():
    assert len(R.OUTSIDE_IDEAS) == 8
    hashes = set()
    for name, spec, how in R.OUTSIDE_IDEAS:
        assert "timeframe" not in spec and name and how
        for tf in NL.TFS:
            hashes.add(NL.spec_hash(NL.normalize_spec({**spec, "timeframe": tf})))
    assert len(hashes) == 8 * len(NL.TFS)                       # no two ideas are the same strategy


def test_outside_ideas_mark_the_timeframes_already_in_the_ledger():
    spec = R.OUTSIDE_IDEAS[3][1]
    index = [{"spec": {**spec, "timeframe": "1h"}}, {"spec": {"bad": 1}}]   # an old row outside the grammar is skipped
    got = {x["name_ko"]: x["tested_timeframes"] for x in R.outside_ideas(NL, index)}
    assert got[R.OUTSIDE_IDEAS[3][0]] == ["1h"] and sum(map(len, got.values())) == 1
    assert R.outside_ideas(None, index) == []
