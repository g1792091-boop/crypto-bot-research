import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from paperbot import Bar, Brackets, Signal  # noqa: E402
from paperbot.accounts import AccountBook  # noqa: E402
from paperbot.config import V3_SYMBOLS, v3_settings  # noqa: E402
from paperbot.dash.app import check_password, create_app, hash_password, make_token, token_ok  # noqa: E402
from paperbot.store3 import Store3  # noqa: E402

MIN = 60_000
S = v3_settings()
SECRET = b"x" * 32


def _store(path):
    store = Store3(path)
    book = AccountBook(S, {s: Brackets.example() for s in V3_SYMBOLS}, store, equity_every_ms=MIN)
    book.open_accounts([{"strategy": "A", "timeframe": "15m", "kind": "strategy"},
                        {"strategy": "RANDOM_1", "timeframe": "15m", "kind": "random"}], 0)
    flat = lambda i, lo=99.95: {s: Bar(s, i * MIN, i * MIN + MIN - 1, 100.0, 100.05, lo, 100.0) for s in V3_SYMBOLS}
    book.step(0, flat(0))
    book.submit("A@15m", Signal(ts=MIN - 1, symbol="BTCUSDT", timeframe="15m", strategy_id="A", side=1,
                                stop_price=0.0, tier="best", atr=0.2, meta={"stop_dist": 0.4}))
    book.step(MIN, flat(1))
    book.step(2 * MIN, flat(2, lo=99.0))        # stop hit: one losing trade
    store.log_signals([{"bar_close": MIN, "timeframe": "15m", "strategy": "A", "symbol": "BTCUSDT", "side": 1,
                        "atr": 0.2, "ref_price": 100.0, "ref_time": MIN + 5000, "delay_ms": 5000,
                        "status": "SUBMITTED"}])
    store.put_state("heartbeat", 123, {"steps": 3})
    store.commit()
    return store


@pytest.fixture
def client(tmp_path):
    db = str(tmp_path / "p.db")
    _store(db).close()
    app = create_app(db, hash_password("correct horse battery"), SECRET,
                     candles=lambda s, i, n: [{"time": 1, "open": 1, "high": 1, "low": 1, "close": 1}])
    return TestClient(app)


def test_password_and_token():
    h = hash_password("abc")
    assert check_password("abc", h) and not check_password("abd", h)
    t = make_token(SECRET, now=1000)
    assert token_ok(SECRET, t, now=1001)
    assert not token_ok(SECRET, t, now=1000 + 8 * 86400)
    assert not token_ok(b"y" * 32, t, now=1001)
    assert not token_ok(SECRET, t[:-1] + ("0" if t[-1] != "0" else "1"), now=1001)


def test_login_required(client):
    assert client.get("/api/board").status_code == 401
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == "/login"
    assert client.post("/api/login", json={"password": "wrong"}).status_code == 401


def test_board_account_status(client):
    assert client.post("/api/login", json={"password": "correct horse battery"}).status_code == 200
    b = client.get("/api/board").json()
    by = {a["account_id"]: a for a in b["accounts"]}
    assert by["A@15m"]["trades"] == 1 and by["A@15m"]["wallet"] < 5000
    assert by["RANDOM_1@15m"]["wallet"] == 5000 == b["initial"]
    assert by["A@15m"]["beats_random"] is False
    a = client.get("/api/account/A@15m").json()
    assert a["trades"][0]["exit_reason"] == "SL" and a["signals"]["ENTERED"] == 1
    assert client.get("/api/account/nope").status_code == 404
    st = client.get("/api/status").json()
    assert st["heartbeat"][0] == 123
    assert client.get("/api/signals?tf=15m").json()[0]["strategy"] == "A"
    assert client.get("/api/candles?symbol=BTCUSDT&interval=15m").status_code == 200
    assert client.get("/api/candles?symbol=EVIL&interval=15m").status_code == 400
    assert "text/html" in client.get("/").headers["content-type"]


def test_login_rate_limit(client):
    for _ in range(10):
        client.post("/api/login", json={"password": "no"})
    assert client.post("/api/login", json={"password": "correct horse battery"}).status_code == 429


def test_loss_cards_and_profile(client):
    client.post("/api/login", json={"password": "correct horse battery"})
    assert client.get("/api/cards").json() == []                       # last 30 days: nothing (1970 data)
    cards = client.get("/api/cards", params={"days": 0}).json()
    assert len(cards) == 1
    c = cards[0]
    assert c["account_id"] == "A@15m" and c["reason_ko"] == "손절" and c["side_ko"] == "롱"
    assert c["if_stop"] == {} and isinstance(c["tags"], list)
    assert client.get("/api/cards", params={"days": 0, "strategy": "B"}).json() == []
    st = client.get("/api/cards/stats", params={"days": 0}).json()
    assert st["trades"] == 1 and st["losses"] == 1 and len(st["tags"]) >= 5
    p = client.get("/api/profile/N17_KC_RSI").json()
    assert p["name_ko"] == "켈트너·RSI" and len(p["rows"]) == 5
    assert client.get("/api/profile/NOPE").status_code == 404


def test_strategy_list(client):
    client.post("/api/login", json={"password": "correct horse battery"})
    lst = client.get("/api/strategies").json()
    assert len(lst) == 36 and {"strategy", "name_ko", "style", "hold", "rare"} <= set(lst[0])
    assert next(x for x in lst if x["strategy"] == "N17_KC_RSI")["style"] == "되돌림 노리기"
