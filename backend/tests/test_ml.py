import numpy as np
import pytest

from app import backtest
from app import indicators as ind
from app.data import synthetic
from app.quant import ml
from app.strategy import StrategySpec


def _momentum(n=2400):
    cl, r = [100.0], 0.0
    for i in range(n - 1):
        r = 0.6 * r + np.random.default_rng(i).normal(0, 0.5)
        cl.append(cl[-1] * (1 + r / 100))
    return [{"time": 1_700_000_000 + 3600 * i, "open": p, "high": p * 1.002, "low": p * 0.998, "close": p, "volume": 1000}
            for i, p in enumerate(cl)]


def _noise(n=2400):
    r = np.random.default_rng(3)
    cl = 100 * np.exp(np.cumsum(r.normal(0, 0.005, n)))
    return [{"time": 1_700_000_000 + 3600 * i, "open": p, "high": p * 1.003, "low": p * 0.997, "close": p, "volume": 1000 + i % 7}
            for i, p in enumerate(cl)]


def test_gradients_match_numeric():
    r = np.random.default_rng(0)
    X, y = r.normal(size=(20, 5)), (r.random(20) > .5).astype(float)
    m = ml.MLP(hidden=[6, 4], dropout=0, l2=0)
    m._init(5, r)
    g = m._grads(X, y, None)
    W, e = m.W[0], 1e-6
    old = W[1, 2]
    W[1, 2] = old + e
    a = ml._logloss(m.predict(X), y)
    W[1, 2] = old - e
    b = ml._logloss(m.predict(X), y)
    W[1, 2] = old
    assert abs((a - b) / (2 * e) - g[0][1, 2]) < 1e-6


def test_features_have_no_lookahead():
    c = _momentum(600)
    a = ml.make_features(c)
    b = ml.make_features(c[:500])
    ok = a["ok"][:500] & b["ok"]
    assert np.allclose(a["X"][:500][ok], b["X"][ok])          # 미래 봉을 더해도 과거 특징은 그대로


@pytest.mark.parametrize("model", ml.MODELS)
def test_models_find_real_edge(model):
    res = ml.walk_forward(_momentum(), model=model, max_folds=4, importance=False)
    assert res["edge"] == "edge" and res["metrics"]["auc"] > 0.6, (model, res["metrics"])


def test_no_edge_on_random_walk_and_text_says_so():
    res = ml.walk_forward(_noise(), model="logreg", max_folds=4)
    assert res["edge"] in ("none", "weak")
    assert "판정" in ml.text(res) and res["importance"]


def test_ml_indicator_in_strategy_backtest():
    c = _momentum()
    out = ind.compute(c, "ml", {"model": "logreg", "horizon": 1})
    assert len(out["prob"]) == len(c) and out["prob"][-1] is not None and out["signal"][-1] in (-1, 0, 1)
    spec = StrategySpec.model_validate({"name": "ML", "symbol": "BTCUSDT", "interval": "1h",
                                        "indicators": [{"id": "ml", "type": "ml", "model": "logreg"}],
                                        "long_entry": {"logic": "all", "conditions": [{"left": "ml.prob", "op": ">", "right": "0.6"}]},
                                        "short_entry": {"logic": "all", "conditions": [{"left": "ml.prob", "op": "<", "right": "0.4"}]}})
    r = backtest.run(spec, c)
    assert r["metrics"]["trades"] > 0


def test_api_ml_run():
    from fastapi.testclient import TestClient
    from app.main import app
    d = TestClient(app).post("/api/ml/run", json={"symbol": "BTCUSDT", "interval": "1h", "model": "gbs", "bars": 1500}).json()
    assert d["edge"] in ("edge", "weak", "none") and d["summary"].startswith("ML 예측") and d["recent"]
