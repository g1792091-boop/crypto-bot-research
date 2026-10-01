"""머신러닝 · 딥러닝 방향 예측 — 캔들 → 특징 26개 → 모델 → 롤링 재학습(walk-forward) 확률.

다른 연구 세션(누리 AI 퀀트 연구소의 ml.js)을 파이썬(numpy)으로 옮기고 딥러닝 모델을 더했다.
- 모델: logreg(로지스틱 회귀) · mlp(신경망 1층) · gbs(부스팅 스텀프) · dnn(딥 신경망 3층) · cnn(1D 합성곱 시계열)
- 룩어헤드 방지: 봉 i 특징은 i 까지의 데이터만. 라벨은 i+horizon 종가 방향.
  학습 행은 시험 시작 봉 s 에서 이미 라벨이 확정된 것만(i + horizon ≤ s), 표준화도 학습 구간에서만 맞춘다.
- 판정: 표본 외 정확도가 다수 클래스 기준선보다 2σ 이상, AUC 도 0.5 보다 2σ 이상이면 'edge'(우위),
  하나만 유의하면 'weak', 둘 다 아니면 'none'. 우위가 없으면 없다고 말한다.
- 결과 확률은 전략 지표 'ml' (출력 prob · signal)로 백테스트·전략 시그널에 그대로 쓸 수 있다.
"""
from __future__ import annotations

import hashlib
import math
import threading
import time
from collections import OrderedDict

import numpy as np

from .. import indicators as ind

FEATURE_KO = {
    "ret_1": "1봉 수익률", "ret_3": "3봉 수익률", "ret_6": "6봉 수익률", "ret_12": "12봉 수익률", "ret_24": "24봉 수익률",
    "rsi": "RSI(14)", "macd_hist": "MACD 히스토그램/ATR", "bb_pctb": "볼린저 %B", "bb_width": "볼린저 밴드폭", "atr_pct": "ATR 변동성 %",
    "adx": "ADX 추세강도", "di_spread": "+DI − −DI", "stoch_k": "스토캐스틱 K", "cci": "CCI", "mfi": "MFI 자금흐름", "obv_slope": "OBV 10봉 기울기",
    "vol_z": "거래량 Z점수", "dist_ema20": "EMA20 이격도", "dist_ema50": "EMA50 이격도", "dist_ema200": "EMA200 이격도",
    "st_trend": "슈퍼트렌드 방향", "cloud_pos": "일목 구름 대비 위치", "hour_sin": "시각(sin)", "hour_cos": "시각(cos)",
    "dow_sin": "요일(sin)", "dow_cos": "요일(cos)",
}
MODEL_KO = {"logreg": "로지스틱 회귀", "mlp": "MLP 신경망", "gbs": "부스팅 스텀프", "dnn": "딥 신경망(3층)", "cnn": "1D 합성곱 신경망(시계열)"}
MODELS = list(MODEL_KO)
DEEP = {"mlp", "dnn", "cnn"}


def _arr(x) -> np.ndarray:
    return np.array([np.nan if v is None else float(v) for v in x], dtype=float)


def _sig(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -40, 40)))


# ------------------------------------------------------------------ 특징
def _roll_z(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    for i in range(n - 1, len(x)):
        w = x[i - n + 1:i + 1]
        if np.isnan(w).any():
            continue
        sd = w.std()
        out[i] = (x[i] - w.mean()) / sd if sd > 1e-12 else 0.0
    return out


def make_features(c: list[dict], horizon: int = 1, extra: dict | None = None) -> dict:
    """특징 행렬 X (n×d, 없는 값 NaN) · y(1 상승/0, 라벨 없으면 NaN) · fwd(로그수익률 %)."""
    n, h = len(c), max(1, int(horizon))
    cl = np.array([b["close"] for b in c], dtype=float)
    vol = np.array([b.get("volume", 0) or 0 for b in c], dtype=float)
    cols: dict[str, np.ndarray] = {}
    with np.errstate(divide="ignore", invalid="ignore"):
        for k in (1, 3, 6, 12, 24):
            r = np.full(n, np.nan)
            r[k:] = np.log(cl[k:] / cl[:-k]) * 100
            cols[f"ret_{k}"] = r
        atr = _arr(ind.atr(c, 14))
        cols["rsi"] = (_arr(ind.rsi(list(cl), 14)) - 50) / 50
        cols["macd_hist"] = _arr(ind.macd(list(cl))["hist"]) / atr
        bb = ind.bbands(list(cl), 20, 2.0)
        up, lo = _arr(bb["upper"]), _arr(bb["lower"])
        cols["bb_pctb"] = np.where(up != lo, (cl - lo) / (up - lo) - 0.5, np.nan)
        bw = _arr(bb["width"])
        cols["bb_width"] = np.where(bw > 0, np.log(bw), np.nan)
        cols["atr_pct"] = atr / cl * 100
        ax = ind.adx(c, 14)
        cols["adx"] = _arr(ax["adx"]) / 100
        cols["di_spread"] = (_arr(ax["plus_di"]) - _arr(ax["minus_di"])) / 100
        cols["stoch_k"] = (_arr(ind.stoch(c)["k"]) - 50) / 50
        cols["cci"] = np.clip(_arr(ind.cci(c, 20)) / 100, -5, 5)
        cols["mfi"] = (_arr(ind.mfi(c, 14)) - 50) / 50
        obv = _arr(ind.obv(c))
        os_ = np.full(n, np.nan)
        for i in range(10, n):
            s = vol[i - 9:i + 1].sum()
            os_[i] = (obv[i] - obv[i - 10]) / s if s > 0 else 0.0
        cols["obv_slope"] = os_
        cols["vol_z"] = _roll_z(np.log1p(np.maximum(0, vol)), 50)
        for L in (20, 50, 200):
            e = _arr(ind.ema(list(cl), L))
            cols[f"dist_ema{L}"] = (cl / e - 1) * 100
        cols["st_trend"] = _arr(ind.supertrend(c, 10, 3.0)["trend"])
        ich = ind.ichimoku(c)
        mid = (_arr(ich["span_a"]) + _arr(ich["span_b"])) / 2
        cols["cloud_pos"] = np.clip((cl - mid) / atr, -10, 10)
        t = np.array([b["time"] for b in c], dtype=float)
        step = float(np.median(np.diff(t[:200]))) if n > 2 else 0
        if 0 < step < 86400:
            hr = (t % 86400) / 86400 * 2 * math.pi
            dw = (((t // 86400) + 4) % 7) / 7 * 2 * math.pi       # 1970-01-01 은 목요일(UTC 요일 4)
            cols["hour_sin"], cols["hour_cos"], cols["dow_sin"], cols["dow_cos"] = np.sin(hr), np.cos(hr), np.sin(dw), np.cos(dw)
        ko = dict(FEATURE_KO)
        for k, arr in (extra or {}).items():
            cols["x_" + k] = _arr(arr)[:n] if len(arr) >= n else np.concatenate([_arr(arr), np.full(n - len(arr), np.nan)])
            ko["x_" + k] = "외부: " + k
        names = list(cols)
        X = np.column_stack([cols[k] for k in names])
        X[~np.isfinite(X)] = np.nan
        fwd = np.full(n, np.nan)
        fwd[:-h] = np.log(cl[h:] / cl[:-h]) * 100
    y = np.where(np.isnan(fwd), np.nan, (fwd > 0).astype(float))
    ok = ~np.isnan(X).any(axis=1)
    start = int(np.argmax(ok)) if ok.any() else -1
    return {"n": n, "d": len(names), "names": names, "ko": [ko.get(k, k) for k in names], "X": X, "ok": ok, "y": y,
            "fwd": fwd, "t": [b["time"] for b in c], "close": cl, "horizon": h, "start": start}


class Scaler:
    def __init__(self, X: np.ndarray):
        self.m = X.mean(axis=0)
        s = X.std(axis=0)
        self.s = np.where(s > 1e-12, s, 1.0)

    def __call__(self, X: np.ndarray) -> np.ndarray:
        return np.clip((X - self.m) / self.s, -8, 8)


# ------------------------------------------------------------------ 최적화
class Adam:
    def __init__(self, params: list[np.ndarray], lr=0.003, b1=0.9, b2=0.999):
        self.p, self.lr, self.b1, self.b2, self.t = params, lr, b1, b2, 0
        self.m = [np.zeros_like(a) for a in params]
        self.v = [np.zeros_like(a) for a in params]

    def step(self, grads):
        self.t += 1
        c1, c2 = 1 - self.b1 ** self.t, 1 - self.b2 ** self.t
        for p, g, m, v in zip(self.p, grads, self.m, self.v):
            m *= self.b1
            m += (1 - self.b1) * g
            v *= self.b2
            v += (1 - self.b2) * g * g
            p -= self.lr * (m / c1) / (np.sqrt(v / c2) + 1e-8)


def _logloss(p, y):
    q = np.clip(p, 1e-7, 1 - 1e-7)
    return float(-(y * np.log(q) + (1 - y) * np.log(1 - q)).mean())


# ------------------------------------------------------------------ 모델
class LogisticRegression:
    def __init__(self, l2=1e-3, lr=0.01, epochs=25, batch=64, seed=1, **_):
        self.l2, self.lr, self.epochs, self.batch, self.seed = l2, lr, epochs, batch, seed

    def fit(self, X, y, val=None):
        r = np.random.default_rng(self.seed)
        self.w, self.b = np.zeros(X.shape[1]), np.zeros(1)
        opt = Adam([self.w, self.b], self.lr)
        idx = np.arange(len(X))
        for _ in range(self.epochs):
            r.shuffle(idx)
            for s in range(0, len(idx), self.batch):
                j = idx[s:s + self.batch]
                g = _sig(X[j] @ self.w + self.b[0]) - y[j]
                opt.step([(X[j].T @ g) / len(j) + self.l2 * self.w, np.array([g.mean()])])
        self.epochs_run = self.epochs
        return self

    def predict(self, X):
        return _sig(X @ self.w + self.b[0])


class MLP:
    """완전연결 신경망. hidden=[16] 이면 MLP, [64,32,16] 이면 딥 신경망. ReLU · 드롭아웃 · Adam · 검증 손실 조기 종료."""

    def __init__(self, hidden=(16,), dropout=0.1, lr=0.003, epochs=40, batch=32, l2=1e-4, patience=6, seed=1, **_):
        self.hidden, self.dropout, self.lr, self.epochs = list(hidden), dropout, lr, epochs
        self.batch, self.l2, self.patience, self.seed = batch, l2, patience, seed

    def _init(self, d, r):
        sizes = [d, *self.hidden, 1]
        self.W = [r.normal(0, math.sqrt(2 / a), (a, b)) for a, b in zip(sizes, sizes[1:])]
        self.B = [np.zeros(b) for b in sizes[1:]]

    def _forward(self, X, r=None):
        acts, masks = [X], []
        a = X
        for li, (W, B) in enumerate(zip(self.W, self.B)):
            z = a @ W + B
            if li == len(self.W) - 1:
                return _sig(z[:, 0]), acts, masks
            a = np.maximum(z, 0)
            if r is not None and self.dropout > 0:
                m = (r.random(a.shape) >= self.dropout) / (1 - self.dropout)
                a = a * m
            else:
                m = None
            masks.append(m)
            acts.append(a)

    def _grads(self, X, y, r):
        p, acts, masks = self._forward(X, r)
        delta = ((p - y) / len(y))[:, None]
        gW, gB = [None] * len(self.W), [None] * len(self.W)
        for li in range(len(self.W) - 1, -1, -1):
            gW[li] = acts[li].T @ delta + self.l2 * self.W[li]
            gB[li] = delta.sum(axis=0)
            if li:
                delta = delta @ self.W[li].T
                delta = delta * (acts[li] > 0)
                if masks[li - 1] is not None:
                    delta = delta * (masks[li - 1] != 0) / (1 - self.dropout)
        return gW + gB

    def fit(self, X, y, val=None):
        r = np.random.default_rng(self.seed)
        self._init(X.shape[1], r)
        opt = Adam(self.W + self.B, self.lr)
        idx, best, bad = np.arange(len(X)), (math.inf, None), 0
        self.epochs_run = 0
        for ep in range(self.epochs):
            r.shuffle(idx)
            for s in range(0, len(idx), self.batch):
                j = idx[s:s + self.batch]
                opt.step(self._grads(X[j], y[j], r))
            self.epochs_run = ep + 1
            if val is not None and len(val[0]):
                loss = _logloss(self.predict(val[0]), val[1])
                if loss < best[0] - 1e-5:
                    best, bad = (loss, ([w.copy() for w in self.W], [b.copy() for b in self.B])), 0
                else:
                    bad += 1
                    if bad >= self.patience:
                        break
        if best[1] is not None:
            self.W, self.B = best[1]
        return self

    def predict(self, X):
        return self._forward(X)[0]


class CNN1D:
    """1D 합성곱 시계열 신경망: 최근 window 봉의 특징 → 합성곱(커널 k, 필터 F, ReLU) → 시간 평균 + 마지막 위치 → 은닉층 → 확률."""

    seq = True

    def __init__(self, window=16, kernel=3, filters=16, hidden=16, lr=0.003, epochs=30, batch=32, l2=1e-4, patience=5, seed=1, **_):
        self.window, self.k, self.F, self.H = window, kernel, filters, hidden
        self.lr, self.epochs, self.batch, self.l2, self.patience, self.seed = lr, epochs, batch, l2, patience, seed

    def _patches(self, S):                 # S: (N, T, d) → (N, T-k+1, k*d)
        N, T, d = S.shape
        return np.stack([S[:, t:t + self.k, :].reshape(N, -1) for t in range(T - self.k + 1)], axis=1)

    def _forward(self, S):
        P = self._patches(S)
        Z1 = P @ self.Wc + self.bc
        A1 = np.maximum(Z1, 0)
        pool = np.concatenate([A1.mean(axis=1), A1[:, -1, :]], axis=1)      # 시간 평균 + 가장 최근 위치
        Z2 = pool @ self.W2 + self.b2
        A2 = np.maximum(Z2, 0)
        p = _sig(A2 @ self.W3 + self.b3)[:, 0]
        return p, (P, Z1, A1, pool, Z2, A2)

    def fit(self, S, y, val=None):
        r = np.random.default_rng(self.seed)
        d = S.shape[2]
        kd = self.k * d
        self.Wc, self.bc = r.normal(0, math.sqrt(2 / kd), (kd, self.F)), np.zeros(self.F)
        self.W2, self.b2 = r.normal(0, math.sqrt(1 / self.F), (2 * self.F, self.H)), np.zeros(self.H)
        self.W3, self.b3 = r.normal(0, math.sqrt(2 / self.H), (self.H, 1)), np.zeros(1)
        params = [self.Wc, self.bc, self.W2, self.b2, self.W3, self.b3]
        opt = Adam(params, self.lr)
        idx, best, bad = np.arange(len(S)), (math.inf, None), 0
        self.epochs_run = 0
        for ep in range(self.epochs):
            r.shuffle(idx)
            for s in range(0, len(idx), self.batch):
                j = idx[s:s + self.batch]
                p, (P, Z1, A1, pool, Z2, A2) = self._forward(S[j])
                n = len(j)
                d3 = ((p - y[j]) / n)[:, None]
                gW3, gb3 = A2.T @ d3 + self.l2 * self.W3, d3.sum(0)
                d2 = (d3 @ self.W3.T) * (Z2 > 0)
                gW2, gb2 = pool.T @ d2 + self.l2 * self.W2, d2.sum(0)
                dpool = d2 @ self.W2.T                                   # (n, 2F)
                dA1 = np.repeat(dpool[:, None, :self.F], A1.shape[1], axis=1) / A1.shape[1]
                dA1[:, -1, :] += dpool[:, self.F:]
                dZ1 = dA1 * (Z1 > 0)
                gWc = np.einsum("ntk,ntf->kf", P, dZ1) + self.l2 * self.Wc
                gbc = dZ1.sum(axis=(0, 1))
                opt.step([gWc, gbc, gW2, gb2, gW3, gb3])
            self.epochs_run = ep + 1
            if val is not None and len(val[0]):
                loss = _logloss(self.predict(val[0]), val[1])
                if loss < best[0] - 1e-5:
                    best, bad = (loss, [a.copy() for a in params]), 0
                else:
                    bad += 1
                    if bad >= self.patience:
                        break
        if best[1] is not None:
            for a, b in zip(params, best[1]):
                a[...] = b
        return self

    def predict(self, S):
        return self._forward(S)[0]


class GradientBoostedStumps:
    def __init__(self, rounds=60, lr=0.1, bins=16, lam=1.0, min_leaf=20, **_):
        self.rounds, self.lr, self.bins, self.lam, self.min_leaf = rounds, lr, bins, lam, min_leaf

    def fit(self, X, y, val=None):
        N, d = X.shape
        self.thr, Bn = [], []
        for f in range(d):
            col = np.sort(X[:, f])
            t = np.unique(col[(np.arange(1, self.bins) / self.bins * (N - 1)).astype(int)])
            self.thr.append(t)
            Bn.append(np.searchsorted(t, X[:, f], side="left"))
        pm = min(0.99, max(0.01, y.mean()))
        self.base, self.stumps = math.log(pm / (1 - pm)), []
        F = np.full(N, self.base)
        for _ in range(self.rounds):
            p = _sig(F)
            g, h = p - y, np.maximum(1e-6, p * (1 - p))
            Gt, Ht, best = g.sum(), h.sum(), None
            for f in range(d):
                nb = len(self.thr[f]) + 1
                G = np.bincount(Bn[f], g, nb)
                H = np.bincount(Bn[f], h, nb)
                C = np.bincount(Bn[f], minlength=nb)
                GL, HL, CL = np.cumsum(G)[:-1], np.cumsum(H)[:-1], np.cumsum(C)[:-1]
                okm = (CL >= self.min_leaf) & (N - CL >= self.min_leaf)
                if not okm.any():
                    continue
                GR, HR = Gt - GL, Ht - HL
                gain = GL ** 2 / (HL + self.lam) + GR ** 2 / (HR + self.lam) - Gt ** 2 / (Ht + self.lam)
                gain[~okm] = -np.inf
                k = int(np.argmax(gain))
                if best is None or gain[k] > best[0]:
                    best = (gain[k], f, k, -GL[k] / (HL[k] + self.lam), -GR[k] / (HR[k] + self.lam))
            if best is None or best[0] <= 1e-9:
                break
            _, f, k, lv, rv = best
            st = (f, self.thr[f][k], self.lr * lv, self.lr * rv)
            self.stumps.append(st)
            F += np.where(Bn[f] <= k, st[2], st[3])
        self.epochs_run = len(self.stumps)
        return self

    def predict(self, X):
        s = np.full(len(X), self.base)
        for f, t, lv, rv in self.stumps:
            s += np.where(X[:, f] <= t, lv, rv)
        return _sig(s)


def make_model(name: str, seed: int, epochs: int | None = None):
    if name == "logreg":
        return LogisticRegression(seed=seed, epochs=epochs or 25)
    if name == "mlp":
        return MLP(hidden=[16], dropout=0.1, epochs=epochs or 40, seed=seed)
    if name == "dnn":
        return MLP(hidden=[64, 32, 16], dropout=0.2, lr=0.002, epochs=epochs or 60, patience=8, seed=seed)
    if name == "cnn":
        return CNN1D(epochs=epochs or 30, seed=seed)
    if name in ("gbs", "boost"):
        return GradientBoostedStumps(rounds=epochs or 60)
    raise ValueError(f"알 수 없는 모델: {name} ({' / '.join(MODELS)})")


# ------------------------------------------------------------------ 평가
def auc(p: np.ndarray, y: np.ndarray) -> float | None:
    order = np.argsort(p, kind="mergesort")
    ps = p[order]
    ranks = np.empty(len(p))
    i = 0
    while i < len(ps):
        j = i
        while j + 1 < len(ps) and ps[j + 1] == ps[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    n1 = y.sum()
    n0 = len(y) - n1
    if not n1 or not n0:
        return None
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def _r4(v):
    return None if v is None or not np.isfinite(v) else round(float(v), 4)


def class_metrics(p: np.ndarray, y: np.ndarray, hi: float, lo: float) -> dict:
    N = len(p)
    rate = float(y.mean())
    base = max(rate, 1 - rate)
    acc = float(((p >= 0.5) == (y == 1)).mean())
    A = auc(p, y)
    n1, n0 = y.sum(), N - y.sum()
    se = None
    if A is not None:
        q1, q2 = A / (2 - A), 2 * A * A / (1 + A)
        se = math.sqrt(max(0.0, (A * (1 - A) + (n1 - 1) * (q1 - A * A) + (n0 - 1) * (q2 - A * A)) / (n1 * n0)))
    hiM, loM = p > hi, p < lo
    edges = [0, .4, .45, .5, .55, .6, 1.0001]
    cal = []
    for a, b in zip(edges, edges[1:]):
        m = (p >= a) & (p < b)
        cal.append({"lo": a, "hi": min(1, b), "n": int(m.sum()), "meanP": _r4(p[m].mean()) if m.any() else None,
                    "rate": _r4(y[m].mean()) if m.any() else None})
    return {"N": N, "accuracy": _r4(acc), "baseline": _r4(base), "upRate": _r4(rate),
            "z": _r4((acc - base) / math.sqrt(max(1e-12, base * (1 - base) / N))) if N else 0,
            "auc": _r4(A), "aucSE": _r4(se), "logloss": _r4(_logloss(p, y)), "coinLogloss": _r4(math.log(2)),
            "baseLogloss": _r4(_logloss(np.full(N, rate), y)),
            "hitHigh": {"n": int(hiM.sum()), "rate": _r4((y[hiM] == 1).mean()) if hiM.any() else None},
            "hitLow": {"n": int(loM.sum()), "rate": _r4((y[loM] == 0).mean()) if loM.any() else None}, "calibration": cal}


def _windows(Xs: np.ndarray, rows: np.ndarray, w: int) -> np.ndarray:
    """rows 각각의 직전 w 봉(자기 포함) 특징 묶음. Xs 는 이미 표준화된 전체 행렬."""
    return np.stack([Xs[i - w + 1:i + 1] for i in rows])


# ------------------------------------------------------------------ 롤링 재학습
def walk_forward(c: list[dict], model: str = "logreg", horizon: int = 1, train_bars: int = 1500, test_bars: int = 250,
                 seed: int = 7, hi: float = 0.55, lo: float = 0.45, fee_pct: float = 0.04, max_folds: int = 20,
                 importance: bool = True, epochs: int | None = None, extra: dict | None = None, time_limit: float = 90) -> dict:
    t0 = time.time()
    if model not in MODELS and model != "boost":
        raise ValueError(f"알 수 없는 모델: {model}")
    h = max(1, min(100, int(horizon)))
    F = make_features(c, h, extra)
    n, X, y, ok = F["n"], F["X"], F["y"], F["ok"]
    capped: list[str] = []
    seq = model == "cnn"
    W = 16 if seq else 1
    start = F["start"] + (W - 1)
    if F["start"] < 0 or n - start < 300:
        raise ValueError(f"봉이 너무 적습니다: 특징(EMA200 등) 계산 뒤 300봉 이상 필요 (전체 {n}봉)")
    tb = max(150, min(int(train_bars), 3000, int((n - start) * 0.6)))
    if tb < train_bars:
        capped.append(f"학습 창 {tb}봉으로 축소")
    first = start + tb + h
    test_bars, step = max(1, int(test_bars)), max(1, int(test_bars))
    if math.ceil((n - first) / step) > max_folds:
        step = math.ceil((n - first) / max_folds)
        test_bars = max(test_bars, step)
        capped.append(f"재학습 {max_folds}회로 제한 (시험 창 {test_bars}봉)")
    if seq:                                      # 창 안에 빈 특징이 없는 봉만
        okw = np.array([i >= W - 1 and ok[i - W + 1:i + 1].all() for i in range(n)])
    else:
        okw = ok
    prob = np.full(n, np.nan)
    folds, store = [], []
    k = 0
    for s in range(first, n, step):
        if time.time() - t0 > time_limit:
            capped.append(f"시간 제한 {time_limit:.0f}초 — 재학습 {k}회에서 멈춤")
            break
        tr = np.array([i for i in range(max(start, s - h - tb + 1), s - h + 1) if okw[i] and not np.isnan(y[i])])
        if len(tr) < 100:
            k += 1
            continue
        sc = Scaler(X[tr])
        Xs = np.where(np.isnan(X), 0.0, X)
        Xs = sc(Xs)
        mk = make_model(model, seed + k * 7919, epochs)
        fx = (lambda rows: _windows(Xs, rows, W)) if seq else (lambda rows: Xs[rows])
        if model in DEEP:                        # 조기 종료 검증: 학습 창 뒤 20%, horizon 만큼 띄워 라벨 겹침 방지
            nv = max(20, len(tr) // 5)
            cut = len(tr) - nv
            a = tr[:max(1, cut - h)]
            mk.fit(fx(a), y[a], (fx(tr[cut:]), y[tr[cut:]]))
        else:
            mk.fit(fx(tr), y[tr])
        te = np.array([j for j in range(s, min(n, s + test_bars)) if okw[j]])
        if len(te):
            Xte = fx(te)
            prob[te] = mk.predict(Xte)
            store.append((mk, te, Xte))
        folds.append({"start": F["t"][s], "train": int(len(tr)), "test": int(len(te)), "epochs": getattr(mk, "epochs_run", epochs)})
        k += 1
    ev = np.where(~np.isnan(prob) & ~np.isnan(y))[0]
    if not len(ev):
        raise ValueError("표본 외 예측이 없습니다 (봉 수·학습 창을 확인하세요)")
    P, Y = prob[ev], y[ev]
    m = class_metrics(P, Y, hi, lo)
    # 단순 매매: p>hi 롱 · p<lo 숏 · 사이 관망 (봉 종가 판단 → 다음 봉 수익, 포지션 바뀔 때 편도 수수료)
    cl = F["close"]
    fp = int(np.argmax(~np.isnan(prob)))
    v, pos, trades, peak, mdd, inm, eq = 1.0, 0, 0, 1.0, 0.0, 0, []
    for j in range(fp, n - 1):
        p = prob[j]
        want = 0 if np.isnan(p) else 1 if p > hi else -1 if p < lo else 0
        if want != pos:
            v *= 1 - abs(want - pos) * fee_pct / 100
            trades += bool(want)
            pos = want
        v *= 1 + pos * (cl[j + 1] / cl[j] - 1)
        inm += bool(pos)
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak * 100)
        eq.append({"time": F["t"][j + 1], "value": round(v, 4)})
    span = max(1, n - 1 - fp)
    trading = {"return_pct": _r4((v - 1) * 100), "bh_pct": _r4((cl[-1] / cl[fp] - 1) * 100), "trades": trades,
               "max_dd_pct": _r4(mdd), "exposure_pct": _r4(inm / span * 100), "fee_pct": fee_pct}
    imp = []
    if importance and m["auc"] is not None and time.time() - t0 < time_limit:
        r = np.random.default_rng(seed + 999)
        lab = {int(j): y[j] for j in ev}
        for f in range(F["d"]):
            pp, yy = [], []
            for mk, te, Xte in store:
                Xp = Xte.copy()
                perm = r.permutation(len(te))
                if seq:
                    Xp[:, :, f] = Xte[perm][:, :, f]
                else:
                    Xp[:, f] = Xte[perm, f]
                pr = mk.predict(Xp)
                for q, j in enumerate(te):
                    if int(j) in lab:
                        pp.append(pr[q])
                        yy.append(lab[int(j)])
            a = auc(np.array(pp), np.array(yy)) if pp else None
            imp.append({"key": F["names"][f], "ko": F["ko"][f], "drop": _r4(m["auc"] - a) if a is not None else None})
        imp = sorted([x for x in imp if x["drop"] is not None], key=lambda x: -x["drop"])[:10]
    aucZ = (m["auc"] - 0.5) / m["aucSE"] if m["aucSE"] else 0
    edge = "edge" if m["z"] >= 2 and aucZ >= 2 else "weak" if (m["z"] >= 2 or aucZ >= 2) else "none"
    return {"model": model, "model_ko": MODEL_KO.get(model, model), "horizon": h, "n": n, "folds": len(folds), "fold_info": folds,
            "prob": [None if np.isnan(x) else round(float(x), 4) for x in prob], "time": F["t"],
            "metrics": {**m, "aucZ": _r4(aucZ)}, "trading": trading, "equity": eq[::max(1, len(eq) // 400)], "importance": imp,
            "edge": edge, "features": F["names"], "params": {"train_bars": tb, "test_bars": test_bars, "step": step, "hi": hi, "lo": lo, "seed": seed},
            "capped": capped, "elapsed_ms": int((time.time() - t0) * 1000)}


def series(res: dict) -> dict:
    """전략 지표용: prob(확률) · signal(+1 롱 / -1 숏 / 0 관망)."""
    hi, lo = res["params"]["hi"], res["params"]["lo"]
    return {"prob": res["prob"], "signal": [None if p is None else 1 if p > hi else -1 if p < lo else 0 for p in res["prob"]]}


def text(res: dict) -> str:
    """프롬프트·회의용 요약 (우위가 없으면 없다고 말한다)."""
    m, tr = res["metrics"], res["trading"]
    pc = lambda v: "?" if v is None else f"{v * 100:.1f}%"
    sg = lambda v: "?" if v is None else f"{v:+.1f}%"
    f3 = lambda v: "?" if v is None else f"{v:.3f}"
    verdict = {"edge": "판정: 기준선 대비 통계적으로 의미 있는 예측력 (정확도·AUC 모두 2σ 이상). 비용 반영 성과는 따로 확인할 것.",
               "weak": "판정: 약한 신호 — 정확도·AUC 중 하나만 유의. 기간을 늘려 재확인 전에는 우위로 보지 말 것.",
               "none": "판정: 우위 없음 — 동전 던지기(다수 클래스 기준선)와 통계적으로 구분되지 않는다. 이 확률로 매매하지 말 것."}[res["edge"]]
    cal = " · ".join(f"{b['lo']}~{b['hi']}: 예측 {pc(b['meanP'])}/실제 {pc(b['rate'])} ({b['n']})" for b in m["calibration"] if b["n"])
    lines = [f"ML 예측 ({res['model_ko']}, {res['horizon']}봉 뒤 방향 · 롤링 재학습 {res['folds']}회 · 표본 외 {m['N']}봉)",
             f"정확도 {pc(m['accuracy'])} vs 기준선 {pc(m['baseline'])} (z={m['z']}) · AUC {f3(m['auc'])} (±{f3(m['aucSE'])}) · 로그손실 {f3(m['logloss'])} (동전 {f3(m['coinLogloss'])})",
             f"확신 구간: p>{res['params']['hi']} 적중 {pc(m['hitHigh']['rate'])} ({m['hitHigh']['n']}봉) · p<{res['params']['lo']} 적중 {pc(m['hitLow']['rate'])} ({m['hitLow']['n']}봉)",
             f"보정: {cal}",
             f"단순 매매(편도 수수료 {tr['fee_pct']}%): {sg(tr['return_pct'])} vs 보유 {sg(tr['bh_pct'])} · 진입 {tr['trades']}회 · 최대낙폭 {tr['max_dd_pct']}%"]
    if res["importance"]:
        lines.append("중요 특징(AUC 하락): " + ", ".join(f"{x['ko']} {f3(x['drop'])}" for x in res["importance"][:6]))
    if res["capped"]:
        lines.append("축소: " + ", ".join(res["capped"]))
    lines.append(verdict)
    s = "\n".join(lines)
    return s[:1497] + "..." if len(s) > 1500 else s


# ------------------------------------------------------------------ 캐시 (전략 지표 'ml' 이 같은 계산을 반복하지 않게)
_cache: OrderedDict = OrderedDict()
_lock = threading.Lock()


def cached(c: list[dict], **kw) -> dict:
    key = hashlib.md5(repr((len(c), c[0]["time"] if c else 0, c[-1]["time"] if c else 0, c[-1]["close"] if c else 0,
                            sorted(kw.items()))).encode()).hexdigest()
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    res = walk_forward(c, **kw)
    with _lock:
        _cache[key] = res
        while len(_cache) > 24:
            _cache.popitem(last=False)
    return res
