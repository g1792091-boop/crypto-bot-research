import numpy as np
import pandas as pd
import pytest

import paperbot.strategy_views as sv


def _df(n=60):
    ts = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    c = np.linspace(100, 110, n)
    return pd.DataFrame({"ts": ts, "open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1.0})


def fake_view(df, tf):
    ma = df["close"].rolling(5).mean().to_numpy()
    up = df["close"].to_numpy() > ma
    return {"overlays": [{"name": "평균 5", "values": ma}],
            "panes": [{"name": "차이", "series": [{"name": "d", "values": df["close"].to_numpy() - ma}], "levels": [0]}],
            "long": [("종가가 평균 위", up), ("항상 꺼짐", np.zeros(len(df), bool))], "short": []}


def test_render_points_and_last_bar_conditions(monkeypatch):
    monkeypatch.setattr(sv, "_VIEWS", {"X": fake_view})
    r = sv.render("X", _df(), "1h", tail=20)
    assert len(r["overlays"][0]["data"]) == 20 and r["overlays"][0]["data"][-1]["value"] == pytest.approx(109.6610, abs=1e-3)
    assert r["panes"][0]["levels"] == [0] and len(r["panes"][0]["series"][0]["data"]) == 20
    assert r["conditions"]["long"] == [{"name": "종가가 평균 위", "on": True}, {"name": "항상 꺼짐", "on": False}]
    assert r["conditions"]["short"] == []
    last = pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(hours=60)
    assert r["bar_close"] == int(last.timestamp() * 1000)


def test_nan_warmup_points_are_dropped(monkeypatch):
    monkeypatch.setattr(sv, "_VIEWS", {"X": fake_view})
    r = sv.render("X", _df(8), "1h", tail=500)
    assert len(r["overlays"][0]["data"]) == 4           # rolling(5) is NaN for the first 4 bars


def test_endpoint(monkeypatch, tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from paperbot.dash.app import create_app, hash_password
    from paperbot.store3 import Store3
    Store3(str(tmp_path / "p.db")).close()
    monkeypatch.setattr(sv, "_VIEWS", {"X": fake_view})
    app = create_app(str(tmp_path / "p.db"), hash_password("correct horse battery"), b"x" * 32,
                     frames=lambda s, tf, n: _df())
    c = TestClient(app)
    c.post("/api/login", json={"password": "correct horse battery"})
    r = c.get("/api/strategy/X", params={"tf": "1h", "symbol": "BTCUSDT"})
    assert r.status_code == 200 and r.json()["conditions"]["long"][0]["on"] is True
    assert c.get("/api/strategy/NOPE").status_code == 404
    assert c.get("/api/strategy/X", params={"tf": "2h"}).status_code == 400
    assert c.get("/api/strategy/X", params={"symbol": "PEPEUSDT"}).status_code == 400
