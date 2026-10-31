"""게이트 봇 (owners 10-31): paperbot/gate.py and paperbot/gateguard.py against a fake Gate (HTTP level).

The owners' rules: the stop at the entry -/+ 15m ATR(14) x 3 (pulled inside the liquidation price when beyond it), the
net-ROE ladder 10 -> 8 then 2 % steps, the friend's own orders and actions first, each coin on its own, one-way mode."""

import hashlib
import hmac
import json
import os
import tempfile
import unittest
import urllib.parse

from paperbot import gate as G
from paperbot import gateguard as GG

SECRET = "s3cret"
KEY = "k3y"
ENV = {"GATE_LIVE_KEY": KEY, "GATE_LIVE_SECRET": SECRET, "GATE_LIVE_KEY_CHECKED": G.KEY_CHECKED_VALUE,
       "PAPERBOT_LIVE_MAINNET": "I_UNDERSTAND"}
T0 = 1_761_900_000                     # seconds, a whole 15 minutes


class FakeGate:
    """Gate's futures API as paperbot/gate.py calls it: positions, price orders, candles, closes."""

    def __init__(self) -> None:
        self.now = float(T0)
        self.last = {"BTC_USDT": 100.0}
        self.tick = {"BTC_USDT": "0.1"}
        self.positions = {}            # contract -> dict
        self.orders = {}               # id -> order dict (Gate's shape)
        self.next_id = 1000
        self.closes = []
        self.m1 = {"BTC_USDT": {}}     # minute (s) -> (o, h, l, c)
        self.dual = False
        self.ips = ["158.247.200.152"]
        self.calls = []
        self.fail_next_post = None     # an HTTP status for the next price-order POST (the order is still made)
        self.signed_ok = True

    # ------------------------------------------------------------------ helpers for the tests
    def open(self, c="BTC_USDT", size=10, entry=100.0, lev=20, liq=0.0, open_s=None, mode="single"):
        self.positions[c] = {"contract": c, "size": str(size), "entry_price": str(entry), "leverage": str(lev),
                             "cross_leverage_limit": "0", "liq_price": str(liq), "mode": mode,
                             "pos_margin_mode": "isolated", "open_time": int(self.now if open_s is None else open_s),
                             "margin": "5", "unrealised_pnl": "0"}

    def minute(self, c, hi, lo, close, at=None):
        t = int((self.now if at is None else at) // 60 * 60)
        self.m1[c][t] = (close, hi, lo, close)
        self.last[c] = close

    def resting(self, c="BTC_USDT"):
        return [o for o in self.orders.values() if o["status"] == "open" and o["initial"]["contract"] == c]

    def fire(self, c="BTC_USDT"):
        """Stops the last price crossed fire and close the position."""
        px = self.last[c]
        for o in self.resting(c):
            p, r = float(o["trigger"]["price"]), o["trigger"]["rule"]
            if (r == 2 and px <= p) or (r == 1 and px >= p):
                o.update(status="finished", finish_as="succeeded")
                self.flat(c, px, text="api")

    def flat(self, c, px, text="app"):
        pos = self.positions.pop(c, None)
        if pos is None:
            return
        size, entry = float(pos["size"]), float(pos["entry_price"])
        side = "long" if size > 0 else "short"
        pnl = (px - entry) * size * 0.01
        self.closes.append({"time": self.now, "contract": c, "side": side, "pnl": f"{pnl - 0.01:.4f}",
                            "pnl_fee": "-0.0100", "text": text,
                            "long_price": str(entry if side == "long" else px),
                            "short_price": str(px if side == "long" else entry),
                            "first_open_time": pos["open_time"]})

    # ------------------------------------------------------------------ HTTP
    def send(self, method, url, headers, body, timeout):
        u = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        path = u.path
        assert path.startswith("/api/v4/")
        if "SIGN" in headers:
            payload = hashlib.sha512((body or "").encode()).hexdigest()
            want = hmac.new(SECRET.encode(), f"{method}\n{path}\n{u.query}\n{payload}\n{headers['Timestamp']}".encode(),
                            hashlib.sha512).hexdigest()
            assert headers["KEY"] == KEY and headers["SIGN"] == want, "bad signature"
        self.calls.append((method, path[len("/api/v4"):], q, json.loads(body) if body else None))
        p = path[len("/api/v4"):]
        js = self.route(method, p, q, json.loads(body) if body else None)
        if isinstance(js, tuple):
            return js
        return 200, json.dumps(js)

    def route(self, method, p, q, body):
        if p == "/spot/time":
            return {"server_time": int(self.now * 1000)}
        if p.startswith("/futures/usdt/contracts/"):
            c = p.rsplit("/", 1)[1]
            return {"name": c, "order_price_round": self.tick[c], "quanto_multiplier": "0.01",
                    "taker_fee_rate": "0.00075", "status": "trading"}
        if p == "/futures/usdt/tickers":
            return [{"contract": q["contract"], "last": str(self.last[q["contract"]])}]
        if p == "/futures/usdt/accounts":
            return {"total": "100", "available": "60", "in_dual_mode": self.dual,
                    "position_mode": "dual" if self.dual else "single"}
        if p == "/account/detail":
            return {"ip_whitelist": self.ips}
        if p == "/futures/usdt/fee":
            return {q["contract"]: {"taker_fee": "0.0005", "maker_fee": "0.0002"}}
        if p == "/futures/usdt/positions":
            return list(self.positions.values())
        if p == "/futures/usdt/candlesticks":
            return self.candles(q)
        if p == "/futures/usdt/position_close":
            return [r for r in self.closes if r["contract"] == q["contract"] and r["time"] >= float(q["from"])]
        if p == "/futures/usdt/price_orders" and method == "GET":
            return [o for o in self.orders.values() if o["status"] == q["status"]
                    and (not q.get("contract") or o["initial"]["contract"] == q["contract"])]
        if p == "/futures/usdt/price_orders" and method == "POST":
            c, trg = body["initial"]["contract"], body["trigger"]
            px, last = float(trg["price"]), self.last[c]
            if (trg["rule"] == 2 and not px < last) or (trg["rule"] == 1 and not px > last):
                return 400, json.dumps({"label": "INVALID_PARAM_VALUE", "message": "trigger price vs last price"})
            oid = self.next_id
            self.next_id += 1
            self.orders[oid] = {"id": oid, "initial": {**body["initial"], "text": "api"}, "trigger": trg,
                                "status": "open", "finish_as": "", "create_time": self.now, "reason": ""}
            if self.fail_next_post:
                st, self.fail_next_post = self.fail_next_post, None
                return st, "<html>bad gateway</html>"
            return {"id": oid}
        if p.startswith("/futures/usdt/price_orders/"):
            oid = int(p.rsplit("/", 1)[1])
            o = self.orders.get(oid)
            if o is None:
                return 404, json.dumps({"label": "ORDER_NOT_FOUND", "message": "not found"})
            if method == "DELETE":
                if o["status"] != "open":
                    return 404, json.dumps({"label": "ORDER_NOT_FOUND", "message": "finished"})
                o.update(status="finished", finish_as="cancelled")
            return o
        if p == "/futures/usdt/orders" and method == "POST":
            assert body["size"] == 0 and body["close"] is True and body["price"] == "0" and body["tif"] == "ioc"
            assert body["text"].startswith("t-") and len(body["text"]) <= 30
            self.flat(body["contract"], self.last[body["contract"]], text=body["text"])
            return {"id": 1, "status": "finished", "finish_as": "filled"}
        raise AssertionError(f"unexpected {method} {p}")

    def candles(self, q):
        c, iv = q["contract"], q["interval"]
        if iv == "15m":                # 200 bars, each high 101 / low 99 / close 100: ATR 2 exactly
            n = int(q["limit"])
            start = int(self.now // 900 * 900) - (n - 1) * 900
            return [{"t": start + i * 900, "o": "100", "h": "101", "l": "99", "c": "100", "v": 1} for i in range(n)]
        assert iv == "1m" and "limit" not in q
        lo, hi = int(q["from"]), int(q["to"])
        return [{"t": t, "o": str(o), "h": str(h), "l": str(l), "c": str(cl)}
                for t, (o, h, l, cl) in sorted(self.m1[c].items()) if lo <= t <= hi]


def make(fake=None, cfg=None, state=None):
    fake = fake or FakeGate()
    d = tempfile.mkdtemp()
    cfg = cfg or GG.Config(state=state or os.path.join(d, "gateguard.json"))
    client = G.GateClient(KEY, SECRET, send=fake.send, clock=lambda: fake.now)
    client.sync_time()
    msgs = []
    g = GG.Guard(cfg, client, lambda level, text: msgs.append((level, text)))
    return fake, g, msgs


class SignAndClient(unittest.TestCase):
    def test_sign_is_gates_format(self):
        body = '{"a":1}'
        want = hmac.new(b"sec", ("POST\n/api/v4/futures/usdt/price_orders\nx=1\n"
                                 + hashlib.sha512(body.encode()).hexdigest() + "\n1700000000").encode(),
                        hashlib.sha512).hexdigest()
        self.assertEqual(G.sign("sec", "POST", "/api/v4/futures/usdt/price_orders", "x=1", body, "1700000000"), want)
        empty = hashlib.sha512(b"").hexdigest()
        self.assertIn(empty, "GET\n/p\n\n" + empty + "\n1")          # a GET hashes the empty body

    def test_host_allowlist_and_errors(self):
        with self.assertRaises(ValueError):
            G.GateClient(KEY, SECRET, base="https://api.gate-io.example")
        c = G.GateClient(KEY, SECRET, send=lambda *a: (400, '{"label":"INVALID_KEY","message":"x"}'))
        with self.assertRaises(G.GateRefused) as e:
            c.positions()
        self.assertEqual(e.exception.label, "INVALID_KEY")
        for st, text in ((502, "<html>"), (429, '{"label":"TOO_MANY_REQUESTS","message":"slow"}'), (200, "not json")):
            c = G.GateClient(KEY, SECRET, send=lambda *a, st=st, text=text: (st, text))
            with self.assertRaises(G.GateUnknown):
                c.positions()

    def test_price_text_and_rounding(self):
        self.assertEqual(G.price_text(94.0, "0.1"), "94.0")
        self.assertEqual(G.price_text(0.123456, "0.00001"), "0.12346")
        self.assertEqual(G.price_text(70123.0, "10"), "70123")
        self.assertEqual(GG.round_stop(95.75, 0.1, 1), 95.8)        # a long's stop rounds up (tighter)
        self.assertEqual(GG.round_stop(104.25, 0.1, -1), 104.2)     # a short's down

    def test_atr_is_pines(self):
        import numpy as np
        from paperbot import mixchop as MC
        rng = np.random.default_rng(3)
        c = 100 + np.cumsum(rng.normal(0, 1, 120))
        h, l = c + rng.uniform(0.1, 2, 120), c - rng.uniform(0.1, 2, 120)
        rows = [(i, c[i], h[i], l[i], c[i]) for i in range(120)]
        self.assertAlmostEqual(GG.wilder_atr(rows, 14), float(MC.atr(h, l, c, 14)[-1]), places=9)
        self.assertIsNone(GG.wilder_atr(rows[:14], 14))


class StartGates(unittest.TestCase):
    def cfg(self):
        return GG.Config(state=os.path.join(tempfile.mkdtemp(), "s.json"))

    def test_keys(self):
        cfg = self.cfg()
        self.assertEqual(GG.trading_keys(cfg, ENV), (KEY, SECRET))
        for bad, word in (({"PAPERBOT_LIVE_MAINNET": ""}, "실거래 스위치"), ({"GATE_LIVE_SECRET": ""}, "비어"),
                          ({"GATE_LIVE_KEY_CHECKED": "yes"}, "FUTURES_ONLY"), ({"BYBIT_LIVE_API_KEY": "x"}, "다른 거래소"),
                          ({"GATE_LIVE_SECRET": KEY}, "같습니다")):
            with self.assertRaises(GG.Refused) as e:
                GG.trading_keys(cfg, {**ENV, **bad})
            self.assertIn(word, str(e.exception))

    def test_dual_mode_and_unbound_key_refuse(self):
        fake, g, _ = make()
        g.start_checks()
        fake.dual = True
        with self.assertRaises(GG.Refused) as e:
            g.start_checks()
        self.assertIn("한 방향", str(e.exception))
        fake.dual, fake.ips = False, []
        with self.assertRaises(GG.Refused) as e:
            g.start_checks()
        self.assertIn("IP", str(e.exception))

    def test_repo_config(self):
        cfg = GG.load_config(os.path.join(os.path.dirname(__file__), "..", "deploy", "gateguard.json"))
        self.assertEqual((cfg.stop_atr, cfg.atr_tf, cfg.atr_n), (3.0, "15m", 14))
        lad = cfg.ladder
        self.assertEqual((lad.first_trigger, lad.first_lock, lad.step), (0.10, 0.08, 0.02))
        self.assertEqual(lad.lock_for(0.099), None)
        self.assertAlmostEqual(lad.lock_for(0.10), 0.08)
        self.assertAlmostEqual(lad.lock_for(0.12), 0.10)
        self.assertAlmostEqual(lad.lock_for(0.141), 0.12)
        self.assertIsNone(cfg.coins)
        self.assertEqual(cfg.mode, "mainnet")
        self.assertIn("순ROE 10%에서 8% 잠금, 이후 2%씩", cfg.words())

    def test_config_refusals(self):
        d = tempfile.mkdtemp()
        base = json.load(open(os.path.join(os.path.dirname(__file__), "..", "deploy", "gateguard.json")))
        for bad in ({"mode": "testnet"}, {"atr_tf": "2h"}, {"stop_atr": 50}, {"ladder": {"first_lock": 0.08}},
                    {"coins": ["BTCUSDT"]}, {"surprise": 1}):
            p = os.path.join(d, "c.json")
            json.dump({**base, **bad}, open(p, "w"))
            with self.assertRaises(GG.Refused):
                GG.load_config(p)


class Guarding(unittest.TestCase):
    def test_long_entry_gets_the_atr_stop(self):
        fake, g, msgs = make()
        fake.open(size=10, entry=100.0, lev=20)
        g.loop_once()
        [o] = fake.resting()
        self.assertEqual(o["trigger"], {"strategy_type": 0, "price_type": 0, "price": "94.0", "rule": 2, "expiration": 0})
        self.assertEqual(o["initial"]["size"], 0)
        self.assertTrue(o["initial"]["close"])
        self.assertEqual(g.coins["BTC_USDT"]["stop"], 94.0)
        self.assertEqual(g.coins["BTC_USDT"]["fee"], 0.0005)               # the account's own taker fee
        text = msgs[-1][1]
        self.assertIn("[게이트 봇] BTC 롱 진입 확인: 평단 100, 수량 10, 20배", text)
        self.assertIn("손절 94 (15분봉 ATR 2 × 3, 가격 -6.0% · 순ROE -122.0%)", text)
        g.loop_once()
        self.assertEqual(len(fake.resting()), 1)                            # nothing more on a quiet loop

    def test_short_entry(self):
        fake, g, msgs = make()
        fake.open(size=-4, entry=100.0, lev=10)
        g.loop_once()
        [o] = fake.resting()
        self.assertEqual((o["trigger"]["price"], o["trigger"]["rule"]), ("106.0", 1))
        self.assertIn("BTC 숏 진입 확인", msgs[-1][1])

    def test_stop_beyond_liquidation_is_pulled_inside(self):
        fake, g, msgs = make()
        fake.open(size=10, entry=100.0, lev=20, liq=95.0)
        g.loop_once()
        [o] = fake.resting()
        self.assertEqual(o["trigger"]["price"], "95.8")                     # 95 + 15 % of 5, up to the tick
        self.assertEqual(msgs[-1][0], "WARN")
        self.assertIn("청산가 95 너머라 청산가 안쪽으로 당김", msgs[-1][1])
        # the liquidation price moves later (cross margin used up): pulled in again, never loosened
        fake.positions["BTC_USDT"]["liq_price"] = "96"
        g.loop_once()
        [o] = fake.resting()
        self.assertEqual(o["trigger"]["price"], "96.6")
        self.assertIn("손절을 96.6로 당겼습니다", msgs[-1][1])

    def test_ladder_ten_locks_eight_then_steps_of_two(self):
        fake, g, msgs = make()
        fake.open(size=10, entry=100.0, lev=20)
        g.loop_once()
        first = fake.resting()[0]["id"]
        # net ROE = 20 x (move - 0.1 %): 100.55 -> +9 %: nothing yet
        fake.now += 60
        fake.minute("BTC_USDT", 100.55, 100.2, 100.5)
        g.loop_once()
        self.assertEqual(fake.resting()[0]["id"], first)
        # 100.62 reached (+10.4 %), now 100.58: the stop at the +8 % price 100 x (1 + 0.004 + 0.001) = 100.5
        fake.now += 60
        fake.minute("BTC_USDT", 100.62, 100.5, 100.58)
        g.loop_once()
        [o] = fake.resting()
        self.assertEqual(o["trigger"]["price"], "100.5")
        self.assertEqual(fake.orders[first]["finish_as"], "cancelled")      # the old one went after the new one
        posts = [i for i, c in enumerate(fake.calls) if c[0] == "POST"]
        dels = [i for i, c in enumerate(fake.calls) if c[0] == "DELETE"]
        self.assertLess(posts[-1], dels[-1])
        self.assertIn("잠금 순ROE +8%: 최고 100.62 (순ROE +10.4%) → 손절 94 → 100.5", msgs[-1][1])
        # +12 % (100.7) -> +10 % lock at 100.6
        fake.now += 60
        fake.minute("BTC_USDT", 100.71, 100.6, 100.68)
        g.loop_once()
        self.assertEqual(fake.resting()[0]["trigger"]["price"], "100.6")
        self.assertAlmostEqual(g.coins["BTC_USDT"]["lock"], 0.10)
        # a dip never loosens it
        fake.now += 60
        fake.minute("BTC_USDT", 100.66, 100.61, 100.62)
        g.loop_once()
        self.assertEqual(fake.resting()[0]["trigger"]["price"], "100.6")

    def test_spike_between_loops_is_seen_from_the_candles(self):
        fake, g, msgs = make()
        fake.open(size=10, entry=100.0, lev=20)
        g.loop_once()
        fake.now += 60
        fake.minute("BTC_USDT", 100.75, 100.6, 100.65)                      # the high is in a candle, not the last price
        g.loop_once()
        self.assertEqual(fake.resting()[0]["trigger"]["price"], "100.6")

    def test_lock_already_passed_closes_at_market(self):
        fake, g, msgs = make()
        fake.open(size=10, entry=100.0, lev=20)
        g.loop_once()
        fake.now += 60
        fake.minute("BTC_USDT", 100.62, 100.3, 100.4)                       # +10.4 % reached, now below the 100.5 lock
        g.loop_once()
        self.assertNotIn("BTC_USDT", fake.positions)
        self.assertIn("이미 잠금 +8% 자리 100.5를 지나 있어 시장가로 닫았습니다", msgs[-1][1])
        fake.now += 10
        g.loop_once()                                                       # flat: our stop cancelled, result told
        self.assertEqual(fake.resting(), [])
        self.assertIn("BTC 롱 종료: 봇 시장가 종료(잠금 +8% 자리를 지나서)", msgs[-1][1])
        self.assertIn("손익 +0.03 USDT (수수료 -0.01 포함)", msgs[-1][1])

    def test_bot_stop_fires(self):
        fake, g, msgs = make()
        fake.open(size=10, entry=100.0, lev=20)
        g.loop_once()
        fake.now += 60
        fake.minute("BTC_USDT", 100, 93.5, 93.8)
        fake.fire()
        g.loop_once()
        self.assertIn("BTC 롱 종료: 봇 손절(94)", msgs[-1][1])
        self.assertEqual(g.coins, {})

    def test_friend_closes_by_hand(self):
        fake, g, msgs = make()
        fake.open(size=10, entry=100.0, lev=20)
        g.loop_once()
        sid = fake.resting()[0]["id"]
        fake.now += 30
        fake.flat("BTC_USDT", 101.0)
        g.loop_once()
        self.assertEqual(fake.orders[sid]["finish_as"], "cancelled")       # our stop does not stay behind
        self.assertIn("BTC 롱 종료: 직접 종료", msgs[-1][1])
        self.assertIn("평단 100 → 종료 101, 손익 +0.09 USDT", msgs[-1][1])

    def test_friends_own_orders_are_never_touched(self):
        fake, g, msgs = make()
        fake.open(size=10, entry=100.0, lev=20)
        fake.orders[1] = {"id": 1, "initial": {"contract": "BTC_USDT", "size": 0, "price": "0", "close": True,
                                               "text": "app"},
                          "trigger": {"price": "97", "rule": 2}, "status": "open", "finish_as": "", "create_time": T0}
        g.loop_once()
        fake.flat("BTC_USDT", 99.0)
        fake.now += 30
        g.loop_once()
        self.assertEqual(fake.orders[1]["status"], "open")
        self.assertFalse([c for c in fake.calls if c[0] == "DELETE" and c[1].endswith("/1")])

    def test_friend_cancels_the_bots_stop_then_adds(self):
        fake, g, msgs = make()
        fake.open(size=10, entry=100.0, lev=20)
        g.loop_once()
        sid = fake.resting()[0]["id"]
        fake.orders[sid].update(status="finished", finish_as="cancelled")
        g.loop_once()
        self.assertTrue(g.coins["BTC_USDT"]["hands_off"])
        self.assertIn("직접 취소됐습니다. 이 포지션은 더 건드리지 않습니다", msgs[-1][1])
        g.loop_once()
        self.assertEqual(fake.resting(), [])                                # not placed again
        # an add: guarded again from the new average entry (a fresh ATR stop)
        fake.positions["BTC_USDT"].update(size="20", entry_price="99")
        fake.last["BTC_USDT"] = 98.0
        g.loop_once()
        [o] = fake.resting()
        self.assertEqual(o["trigger"]["price"], "93.0")
        self.assertFalse(g.coins["BTC_USDT"]["hands_off"])
        self.assertTrue(any("추가 진입 확인: 평단 100 → 99" in m for _, m in msgs))

    def test_add_recomputes_from_the_new_average(self):
        fake, g, msgs = make()
        fake.open(size=10, entry=100.0, lev=20)
        g.loop_once()
        fake.now += 60
        fake.minute("BTC_USDT", 100.62, 100.5, 100.58)
        g.loop_once()
        old = fake.resting()[0]["id"]                                       # the +8 % lock at 100.5
        fake.now += 60
        fake.positions["BTC_USDT"].update(size="20", entry_price="100.3")
        fake.minute("BTC_USDT", 100.6, 100.55, 100.6)
        g.loop_once()
        [o] = fake.resting()
        self.assertEqual(o["trigger"]["price"], "94.3")                     # 100.3 - 2 x 3: the ladder starts again
        self.assertEqual(fake.orders[old]["finish_as"], "cancelled")
        s = g.coins["BTC_USDT"]
        self.assertIsNone(s["lock"])
        self.assertEqual((s["entry"], s["size"], s["best"]), (100.3, 20.0, 100.3))

    def test_part_closed_keeps_the_stop(self):
        fake, g, msgs = make()
        fake.open(size=10, entry=100.0, lev=20)
        g.loop_once()
        sid = fake.resting()[0]["id"]
        fake.positions["BTC_USDT"]["size"] = "4"
        g.loop_once()
        self.assertEqual([o["id"] for o in fake.resting()], [sid])
        self.assertIn("일부 종료 확인: 수량 10 → 4", msgs[-1][1])

    def test_lost_answer_adopts_the_order_once(self):
        fake, g, msgs = make()
        fake.open(size=10, entry=100.0, lev=20)
        fake.fail_next_post = 502
        g.loop_once()
        self.assertEqual(len(fake.resting()), 1)
        self.assertEqual(g.coins["BTC_USDT"]["stop_id"], fake.resting()[0]["id"])
        g.loop_once()
        self.assertEqual(len(fake.resting()), 1)

    def test_refused_stop_is_tried_again(self):
        fake, g, msgs = make()
        fake.open(size=10, entry=100.0, lev=20)
        real = fake.route
        fake.route = lambda m, p, q, b: ((400, json.dumps({"label": "BALANCE_NOT_ENOUGH", "message": "x"}))
                                         if m == "POST" else real(m, p, q, b))
        g.loop_once()
        self.assertEqual(fake.resting(), [])
        self.assertEqual(msgs[-1][0], "CRITICAL")
        self.assertIn("거절", msgs[-1][1])
        fake.route = real
        g.loop_once()
        self.assertEqual(len(fake.resting()), 1)
        self.assertIn("진입 확인", msgs[-1][1])                              # told once the stop is really there

    def test_late_seen_position_past_its_stop_is_left_alone(self):
        fake, g, msgs = make()
        fake.open(size=10, entry=100.0, lev=20, open_s=T0 - 3600)
        fake.last["BTC_USDT"] = 93.0
        g.loop_once()
        self.assertIn("BTC_USDT", fake.positions)                           # not closed by the bot
        self.assertEqual(fake.resting(), [])
        self.assertEqual(msgs[-1][0], "CRITICAL")
        self.assertIn("직접 정리해 주세요", msgs[-1][1])

    def test_late_seen_position_counts_its_best_from_now(self):
        fake, g, msgs = make()
        fake.minute("BTC_USDT", 101.5, 100.0, 100.2, at=T0 - 1800)          # +28 % an hour ago, before the bot
        fake.last["BTC_USDT"] = 100.2
        fake.open(size=10, entry=100.0, lev=20, open_s=T0 - 3600)
        g.loop_once()
        g.loop_once()
        self.assertIn("BTC_USDT", fake.positions)
        self.assertEqual(fake.resting()[0]["trigger"]["price"], "94.0")
        self.assertIn("늦게 본 포지션", msgs[0][1])

    def test_each_coin_on_its_own_and_hedge_positions_skipped(self):
        fake, g, msgs = make()
        fake.last["ETH_USDT"], fake.tick["ETH_USDT"], fake.m1["ETH_USDT"] = 50.0, "0.01", {}
        fake.open(size=10, entry=100.0, lev=20)
        fake.open(c="ETH_USDT", size=-3, entry=50.0, lev=10)
        g.loop_once()
        self.assertEqual(fake.resting("ETH_USDT")[0]["trigger"]["price"], "56.00")
        self.assertEqual(fake.resting("BTC_USDT")[0]["trigger"]["price"], "94.0")
        fake.flat("ETH_USDT", 49.0)
        g.loop_once()
        self.assertEqual(len(fake.resting("BTC_USDT")), 1)
        fake2, g2, msgs2 = make()
        fake2.open(size=10, entry=100.0, lev=20, mode="dual_long")
        g2.loop_once()
        self.assertEqual(fake2.resting(), [])
        self.assertIn("양방향 모드", msgs2[-1][1])

    def test_stop_ended_by_gate_is_placed_again(self):
        fake, g, msgs = make()
        fake.open(size=10, entry=100.0, lev=20)
        g.loop_once()
        sid = fake.resting()[0]["id"]
        fake.orders[sid].update(status="finished", finish_as="failed", reason="risk limit")
        g.loop_once()
        [o] = fake.resting()
        self.assertNotEqual(o["id"], sid)
        self.assertEqual(o["trigger"]["price"], "94.0")
        self.assertIn("게이트에서 끝났습니다(failed: risk limit). 같은 자리 94에 다시 겁니다", msgs[-1][1])

    def test_fired_but_position_still_there_starts_again(self):
        fake, g, msgs = make()
        fake.open(size=10, entry=100.0, lev=20)
        g.loop_once()
        sid = fake.resting()[0]["id"]
        fake.orders[sid].update(status="finished", finish_as="succeeded")   # fired, the friend re-entered at once
        fake.positions["BTC_USDT"].update(entry_price="98", open_time=int(fake.now))
        fake.last["BTC_USDT"] = 98.0
        g.loop_once()
        [o] = fake.resting()
        self.assertEqual(o["trigger"]["price"], "92.0")
        self.assertTrue(any("포지션이 남아 있습니다" in m for _, m in msgs))

    def test_cross_margin_uses_its_leverage(self):
        fake, g, msgs = make()
        fake.open(size=10, entry=100.0, lev=0)
        fake.positions["BTC_USDT"].update(cross_leverage_limit="20", pos_margin_mode="cross")
        g.loop_once()
        self.assertEqual(g.coins["BTC_USDT"]["lev"], 20.0)
        self.assertIn("20배 (교차)", msgs[-1][1])
        fake.now += 60
        fake.minute("BTC_USDT", 100.62, 100.5, 100.58)
        g.loop_once()
        self.assertEqual(fake.resting()[0]["trigger"]["price"], "100.5")

    def test_unreadable_gate_is_told_after_three_loops(self):
        fake, g, msgs = make()
        real = fake.route
        fake.route = lambda m, p, q, b: (503, "down") if p == "/futures/usdt/positions" else real(m, p, q, b)
        g.run(loops=3, sleep=lambda s: None)
        self.assertEqual(len(msgs), 1)
        self.assertIn("게이트를 3번 연속 못 읽었습니다(걸린 손절은 게이트에 그대로 있음)", msgs[0][1])
        fake.route = real
        g.run(loops=1, sleep=lambda s: None)
        self.assertIn("다시 됩니다", msgs[-1][1])

    def test_a_bug_is_told_once_and_the_loop_goes_on(self):
        fake, g, msgs = make()
        g.loop_once = lambda: (_ for _ in ()).throw(KeyError("side"))
        g.run(loops=3, sleep=lambda s: None)
        self.assertEqual(len(msgs), 1)
        self.assertIn("봇 내부 오류(걸린 손절은 게이트에 그대로 있음): KeyError", msgs[0][1])

    def test_state_survives_a_restart(self):
        fake, g, msgs = make()
        fake.open(size=10, entry=100.0, lev=20)
        g.loop_once()
        sid = fake.resting()[0]["id"]
        _, g2, msgs2 = make(fake=fake, state=g.cfg.state)
        g2.loop_once()
        self.assertEqual([o["id"] for o in fake.resting()], [sid])          # the same stop, not a second one
        self.assertEqual(msgs2, [])

    def test_a_lost_state_file_never_leaves_an_old_stop_behind(self):
        fake, g, msgs = make()
        fake.open(size=10, entry=100.0, lev=20)
        g.loop_once()
        old = fake.resting()[0]["id"]
        os.remove(g.cfg.state)                                              # the state is gone; the stop rests on Gate
        _, g2, msgs2 = make(fake=fake, state=g.cfg.state)
        g2.loop_once()
        [o] = fake.resting()
        self.assertNotEqual(o["id"], old)                                   # one stop, the new one
        self.assertEqual(fake.orders[old]["finish_as"], "cancelled")
        # a stop of ours resting on a coin with no position is swept (it would close the next one at an old price)
        fake.orders[5] = {"id": 5, "initial": {"contract": "ETH_USDT", "size": 0, "price": "0", "close": True,
                                               "text": "api"},
                          "trigger": {"price": "40", "rule": 2}, "status": "open", "finish_as": "", "create_time": T0}
        fake.orders[6] = {"id": 6, "initial": {"contract": "ETH_USDT", "size": 0, "price": "0", "close": True,
                                               "text": "app"},
                          "trigger": {"price": "41", "rule": 2}, "status": "open", "finish_as": "", "create_time": T0}
        g2.loop_once()
        self.assertEqual(fake.orders[5]["finish_as"], "cancelled")
        self.assertEqual(fake.orders[6]["status"], "open")                  # the friend's own: never touched
        self.assertIn("남아 있던 봇 손절(40)을 지웠습니다", msgs2[-1][1])

    def test_wrapper_and_install(self):
        import subprocess
        root = os.path.join(os.path.dirname(__file__), "..")
        sh = open(os.path.join(root, "deploy", "paperbot-exec.sh"), encoding="utf-8").read()
        self.assertIn('gate) keys=EnvironmentFile=/etc/paperbot/executor-gate.env; hide=" -/etc/paperbot/executor.env"', sh)
        self.assertIn('[ "$keys" = EnvironmentFile=/etc/paperbot/executor-gate.env ] || { echo "gateguard: use --keys gate"; exit 1; }', sh)
        inst = open(os.path.join(root, "deploy", "install.sh"), encoding="utf-8").read()
        self.assertIn('install -o root -g root -m 600 "$APP/deploy/executor-gate.env.example" /etc/paperbot/executor-gate.env', inst)
        self.assertIn('install -m 644 "$APP/deploy/paperbot-gateguard.service" /etc/systemd/system/paperbot-gateguard.service', inst)
        for line in inst.splitlines():                                      # installed only: never started here
            if "paperbot-gateguard" in line and "systemctl" in line and not line.strip().startswith("echo"):
                self.assertIn("is-active", line)
        env = open(os.path.join(root, "deploy", "executor-gate.env.example"), encoding="utf-8").read()
        for line in env.splitlines():
            if line and not line.startswith("#"):
                self.assertTrue(line.endswith("="), line)                  # no value, no secret in the repository
        for name in ("GATE_LIVE_KEY", "GATE_LIVE_SECRET", "GATE_LIVE_KEY_CHECKED", "PAPERBOT_LIVE_MAINNET"):
            self.assertIn(f"\n{name}=\n", env)
        self.assertEqual(subprocess.run(["sh", "-n", os.path.join(root, "deploy", "paperbot-exec.sh")]).returncode, 0)

    def test_check_reads_only(self):
        fake, g, msgs = make()
        g.save_on = False
        fake.open(size=10, entry=100.0, lev=20)
        lines = g.plan_lines()
        self.assertIn("새로 걸 손절 94 (15분봉 ATR 2 × 3)", lines[0])
        self.assertFalse([c for c in fake.calls if c[0] in ("POST", "DELETE")])


if __name__ == "__main__":
    unittest.main()
