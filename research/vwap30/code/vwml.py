"""PREREG9.md: a LightGBM model per exit reads every judge at once (round 8's 269 judges relative to the candidate's side,
the label, coin, hour, ATR, recent coin / BTC returns) and predicts R for each signal in its own direction and in the
opposite one; the account takes only candidates whose prediction is above a threshold, best prediction first.
Learn on 2020-03 .. 2023-06, choose (exit, threshold) on 2023-07 .. 2024-12, confirm once on 2025-01 .. 2026-09.

    python3 -I vwml.py build     features + targets -> OUT9/feat.npz
    python3 -I vwml.py train     4 models, predictions from 2023-07 on -> OUT9/pred.npz, OUT9/model_*.txt
    python3 -I vwml.py select    -> research/vwap30/finalists9.json (+ sha256)
    python3 -I vwml.py confirm   -> research/vwap30/results9.json"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python3 -I leaves the script's folder out
from vwgate import *
from vwgate import _ST, _GRID
from vwacct import trades
import lightgbm as lgb

OUT9 = OUT + "_r9"
EX9 = (1, 4, 8, 10)
TRAIN_END = ms("2023-07-01")
VALID = (TRAIN_END, SEL[1])
SEED9, SEED9T = 20261101, 20261102
N_TRAIN = 2_500_000
QS = (50, 60, 70, 80, 90, 95, 98, 99, 99.5)
FEAT_G = [i for i, g in enumerate(GATES) if not (g.startswith("L|") and g.endswith("|24h"))]     # 7-day label states
NUM = ("atrf", "r60", "r240", "r1440", "b60", "b240", "b1440")
CAT = ("label", "coin", "tf", "hour", "dow", "opp")
PARAMS = dict(objective="regression", learning_rate=0.05, num_leaves=63, min_data_in_leaf=1000, feature_fraction=0.5,
              bagging_fraction=0.5, bagging_freq=1, lambda_l2=10.0, verbose=-1, num_threads=4, seed=SEED9)


def build():
    os.makedirs(OUT9, exist_ok=True)
    load_ctx()
    closes = {}
    for coin in COINS:
        closes[coin] = grid(coin)["c"].astype(float).copy()
        _GRID.clear()
    btc = closes["BTCUSDT"]
    parts = {k: [] for k in ("entry", "coin", "side", "label", "tf", "G", "num") + tuple(
        f"{q}_{j}" for j in EX9 for q in ("net", "tx", "net_o", "tx_o", "D"))}
    for li, lab in enumerate(LABELS):
        T = Trig(lab)
        G = T.gates()[FEAT_G]
        self_rows = [r for r, i in enumerate(FEAT_G) if GATES[i].split("|")[1:2] == [lab]]
        G[self_rows] = 0
        s = T.side.astype(np.int8)
        e = (T.entry - T0) // MIN
        rel = (G * s[None, :]).T.astype(np.int8)                     # judges relative to the signal's side
        num = np.zeros((len(e), len(NUM)), np.float32)
        num[:, 0] = T.L.atrf[T.o]
        for ci, coin in enumerate(COINS):
            m = T.coin == ci
            if not m.any():
                continue
            c = closes[coin]
            for q, k in enumerate((60, 240, 1440)):
                with np.errstate(all="ignore"):
                    num[m, 1 + q] = (c[e[m] - 1] / c[np.maximum(e[m] - 1 - k, 0)] - 1) * s[m]
                    num[m, 4 + q] = (btc[e[m] - 1] / btc[np.maximum(e[m] - 1 - k, 0)] - 1) * s[m]
        parts["entry"].append(T.entry)
        parts["coin"].append(T.coin.astype(np.int8))
        parts["side"].append(s)
        parts["label"].append(np.full(len(e), li, np.int16))
        parts["tf"].append(np.full(len(e), 0 if "_at_30m" in lab else 1, np.int8))
        parts["G"].append(rel)
        parts["num"].append(num)
        Z = T.L
        for j in EX9:
            parts[f"net_{j}"].append(Z.ret[T.o][:, j].astype(np.float32))
            parts[f"tx_{j}"].append(Z.tx[T.o][:, j])
            parts[f"net_o_{j}"].append(Z.ret_o[T.o][:, j].astype(np.float32))
            parts[f"tx_o_{j}"].append(Z.tx_o[T.o][:, j])
            parts[f"D_{j}"].append(T.D[:, j].astype(np.float32))
        if li % 20 == 0:
            print("features", li, lab, len(e), flush=True)
    F = {k: np.concatenate(v) for k, v in parts.items()}
    np.save(os.path.join(OUT9, "G.npy"), F.pop("G"))
    np.savez(os.path.join(OUT9, "feat.npz"), **F)
    print("rows", len(F["entry"]), flush=True)


def load_feat():
    F = dict(np.load(os.path.join(OUT9, "feat.npz")))
    F["G"] = np.load(os.path.join(OUT9, "G.npy"))
    kst = pd.to_datetime(F["entry"] + KST, unit="ms")
    F["hour"] = np.asarray(kst.hour, np.int8)
    F["dow"] = np.asarray(kst.dayofweek, np.int8)
    return F


def matrix(F, rows, opp):
    """Feature rows for candidates (row, opposite?)."""
    sg = np.where(opp, -1, 1).astype(np.int8)
    X = np.empty((len(rows), len(FEAT_G) + len(NUM) + len(CAT)), np.float32)
    for a in range(0, len(rows), 500_000):
        r, o = rows[a:a + 500_000], sg[a:a + 500_000]
        X[a:a + len(r), :len(FEAT_G)] = F["G"][r] * o[:, None]
        num = F["num"][r].copy()
        num[:, 1:] *= o[:, None]
        X[a:a + len(r), len(FEAT_G):len(FEAT_G) + len(NUM)] = num
        k = len(FEAT_G) + len(NUM)
        X[a:a + len(r), k] = F["label"][r]
        X[a:a + len(r), k + 1] = F["coin"][r]
        X[a:a + len(r), k + 2] = F["tf"][r]
        X[a:a + len(r), k + 3] = F["hour"][r]
        X[a:a + len(r), k + 4] = F["dow"][r]
        X[a:a + len(r), k + 5] = opp[a:a + len(r)]
    return X


def target(F, rows, opp, j):
    net = np.where(opp, F[f"net_o_{j}"][rows], F[f"net_{j}"][rows])
    return np.clip(net / F[f"D_{j}"][rows], -3, 6).astype(np.float32)


def feat_names():
    return [f"g{q}" for q in range(len(FEAT_G))] + list(NUM) + list(CAT)


def train():
    F = load_feat()
    n = len(F["entry"])
    rng = np.random.default_rng(SEED9)
    tr = np.flatnonzero((F["entry"] >= SEL[0]) & (F["entry"] < TRAIN_END))
    va = np.flatnonzero((F["entry"] >= VALID[0]) & (F["entry"] < VALID[1]))
    ap = np.flatnonzero(F["entry"] >= VALID[0])                       # valid + confirm + live
    pick = rng.choice(2 * len(tr), size=min(N_TRAIN, 2 * len(tr)), replace=False)
    tr_r, tr_o = tr[pick % len(tr)], pick >= len(tr)
    vpick = rng.choice(2 * len(va), size=min(800_000, 2 * len(va)), replace=False)
    va_r, va_o = va[vpick % len(va)], vpick >= len(va)
    Xtr = matrix(F, tr_r, tr_o)
    Xva = matrix(F, va_r, va_o)
    names = feat_names()
    cat_idx = [names.index(c) for c in ("label", "coin")]
    pred = {"rows": ap}
    imp, models = {}, {}
    for j in EX9:
        t0 = time.time()
        dtr = lgb.Dataset(Xtr, target(F, tr_r, tr_o, j), feature_name=names, categorical_feature=cat_idx, free_raw_data=False)
        dva = lgb.Dataset(Xva, target(F, va_r, va_o, j), reference=dtr)
        mdl = lgb.train(PARAMS, dtr, num_boost_round=1500, valid_sets=[dva],
                        callbacks=[lgb.early_stopping(100, verbose=False)])
        mdl.save_model(os.path.join(OUT9, f"model_{j}.txt"))
        models[j] = mdl
        gain = mdl.feature_importance("gain")
        imp[j] = [(names[q], float(gain[q])) for q in np.argsort(-gain)[:30]]
        print("model", j, "rounds", mdl.best_iteration, "sec", round(time.time() - t0), flush=True)
    del Xtr, Xva
    for o in (False, True):
        ps = {j: [] for j in EX9}
        for a in range(0, len(ap), 400_000):
            X = matrix(F, ap[a:a + 400_000], np.full(len(ap[a:a + 400_000]), o))
            for j, mdl in models.items():
                ps[j].append(mdl.predict(X, num_iteration=mdl.best_iteration).astype(np.float32))
        for j in EX9:
            pred[f"p{j}_{int(o)}"] = np.concatenate(ps[j])
    np.savez(os.path.join(OUT9, "pred.npz"), **pred)
    json.dump({str(k): v for k, v in imp.items()}, open(os.path.join(OUT9, "importance.json"), "w"), indent=1)


def gate_name(q):
    return GATES[FEAT_G[q]]


def book(F, P, j, theta, per):
    """A One of the candidates (both sides) above theta in a period, best prediction first among ties."""
    a, z = PERIODS[per]
    rows = P["rows"]
    keep = (F["entry"][rows] >= a) & (F["entry"][rows] < z)
    parts = []
    for o in (0, 1):
        p = P[f"p{j}_{o}"]
        k = keep & (p > theta)
        r = rows[k]
        own, oth = ("net_o", "net") if o else ("net", "net_o")
        tx, txo = ("tx_o", "tx") if o else ("tx", "tx_o")
        parts.append((F["entry"][r], F["coin"][r].astype(np.int64), F[f"{own}_{j}"][r], F[f"{tx}_{j}"][r],
                      F[f"{oth}_{j}"][r], F[f"{txo}_{j}"][r], F[f"D_{j}"][r].astype(float), -p[k],
                      np.array([f"{LABELS[F['label'][x]]}{'~반대' if o else ''}" for x in r], object)))
    cat = [np.concatenate([p[q] for p in parts]) for q in range(9)]
    return One(*cat[:7], prio=cat[7], member=cat[8])


def thetas(P, F, j):
    rows = P["rows"]
    m = (F["entry"][rows] >= VALID[0]) & (F["entry"][rows] < VALID[1])
    allp = np.concatenate([P[f"p{j}_0"][m], P[f"p{j}_1"][m]])
    return {q: float(np.percentile(allp, q)) for q in QS}


def select():
    PERIODS["valid"] = VALID
    F = load_feat()
    P = dict(np.load(os.path.join(OUT9, "pred.npz")))
    rows = []
    for j in EX9:
        for q, th in thetas(P, F, j).items():
            o = book(F, P, j, th, "valid")
            x = metrics(o, wd_mask(o), 0, "valid", full=True)
            rows.append({"exit": j, "q": q, "theta": th, **pick(x)})
            print("valid exit", j, "q", q, "n", x["n"], "wd", round(x["per_weekday"], 2), "win", round(x["win"], 3),
                  "R", round(x["avgR"], 3), "growth", round(x["growth"], 2), flush=True)
    a = [r for r in rows if r["per_weekday"] >= 3.0]
    A = max(a, key=lambda r: r["growth"]) if a else None
    b = sorted([r for r in rows if r["per_weekday"] >= 1.0], key=lambda r: -r["growth"])
    B = next((r for r in b if A is None or (r["exit"], r["q"]) != (A["exit"], A["q"])), None)
    fin = [dict(name=nm, exit=r["exit"], q=r["q"], theta=r["theta"]) for nm, r in (("A 평일 3번 이상", A), ("B 평일 1번 이상", B)) if r]
    fp = os.path.join(RES_DIR, "finalists9.json")
    json.dump({"made": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + "Z", "finalists": fin, "valid_rows": rows},
              open(fp, "w"), ensure_ascii=False, indent=1, default=float)
    open(fp + ".sha256", "w").write(hashlib.sha256(open(fp, "rb").read()).hexdigest() + "  finalists9.json\n")
    for f in fin:
        print("finalist", f, flush=True)


def month_odds_v(o, m):
    """month_odds2 over valid + confirm."""
    from vwacct import trades
    a, z = VALID[0], CONF[1]
    idx, net, ext, D = trades(o, m & (o.entry >= a) & (o.entry < z), 0)
    kd = (o.entry[idx] + KST) // DAY
    d0, d1 = (a + KST) // DAY, (z + KST) // DAY
    out = {}
    for E in (9, 15, 20, 30):
        x = np.log1p(np.maximum(E * net, -1 + 1e-12))
        per = np.zeros(d1 - d0 + 1)
        np.add.at(per, kd - d0, x)
        cs = np.r_[0, np.cumsum(per)]
        mm = np.exp(cs[30:] - cs[:-30])
        out[str(E)] = {"x2": round(float((mm >= 2).mean()), 4), "x5": round(float((mm >= 5).mean()), 4),
                       "x10": round(float((mm >= 10).mean()), 4), "x20": round(float((mm >= 20).mean()), 4),
                       "lose90": round(float((mm <= 0.1).mean()), 4), "median": round(float(np.median(mm)), 4)}
    return out


def confirm():
    fp = os.path.join(RES_DIR, "finalists9.json")
    want = open(fp + ".sha256").read().split()[0]
    got = hashlib.sha256(open(fp, "rb").read()).hexdigest()
    assert want == got, "finalists9.json changed after it was frozen"
    PERIODS["valid"] = VALID
    PERIODS["c2025"] = (ms("2025-01-01"), ms("2026-01-01"))
    PERIODS["c2026"] = (ms("2026-01-01"), ms("2026-10-01"))
    PERIODS["vc"] = (VALID[0], CONF[1])
    F = load_feat()
    P = dict(np.load(os.path.join(OUT9, "pred.npz")))
    rng = np.random.default_rng(SEED9T)
    res = []
    for f in json.load(open(fp))["finalists"]:
        o = book(F, P, f["exit"], f["theta"], "confirm")
        full = book(F, P, f["exit"], f["theta"], "vc")
        row = dict(f)
        for per in ("valid", "confirm", "c2025", "c2026", "live"):
            b = book(F, P, f["exit"], f["theta"], per)
            row[per] = pick(metrics(b, wd_mask(b), 0, per))
        tw = np.array([metrics(o, wd_mask(o), 0, "confirm", flip=rng.random(len(o.entry)) < 0.5, full=False)["growth"]
                       for _ in range(2000)])
        q95 = float(np.percentile(tw, 95))
        g = row["confirm"]["growth"]
        row["twin"] = {"p50": round(float(np.median(tw)), 3), "p90": round(float(np.percentile(tw, 90)), 3),
                       "p95": round(q95, 3), "share_below": round(float((tw < g).mean()), 4)}
        row["verdict"] = "통함" if (row["confirm"]["avgR"] > 0 and g > q95) else "통하지 않음"
        row["month_odds"] = month_odds_v(full, wd_mask(full))
        mem = pd.Series(o.member[trades(o, wd_mask(o) & (o.entry >= CONF[0]) & (o.entry < CONF[1]), 0)[0]])
        row["confirm_members_top"] = mem.value_counts().head(10).to_dict()
        res.append(row)
        print(f["name"], "exit", f["exit"], "q", f["q"], "| valid wd", row["valid"]["per_weekday"], "R", row["valid"]["avgR"],
              "| confirm n", row["confirm"]["n"], "wd", row["confirm"]["per_weekday"], "win", row["confirm"]["win"], "R",
              row["confirm"]["avgR"], "g", g, "p95", round(q95, 2), "->", row["verdict"], "| live n", row["live"]["n"],
              "R", row["live"]["avgR"], flush=True)
    # 참고 after the verdicts: every (exit, theta) on confirm, and what the models leaned on
    ref = []
    for j in EX9:
        for q, th in thetas(P, F, j).items():
            b = book(F, P, j, th, "confirm")
            x = metrics(b, wd_mask(b), 0, "confirm", full=False)
            ref.append({"exit": j, "q": q, "n": x["n"], "per_weekday": round(x["per_weekday"], 3), "growth": round(x["growth"], 3)})
    imp = json.load(open(os.path.join(OUT9, "importance.json")))
    imp_ko = {j: [(gate_name(int(n[1:])) if n.startswith("g") and n[1:].isdigit() else n, round(v)) for n, v in lst[:20]]
              for j, lst in imp.items()}
    json.dump({"made": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + "Z", "finalists_sha256": got, "finalists": res,
               "after_confirm_grid": ref, "importance": imp_ko},
              open(os.path.join(RES_DIR, "results9.json"), "w"), ensure_ascii=False, indent=1, default=float)
    for r in ref:
        print("참고 confirm", r)
    print("written results9.json")


if __name__ == "__main__":
    os.makedirs(OUT9, exist_ok=True)
    {"build": build, "train": train, "select": select, "confirm": confirm}[sys.argv[1]]()
