"""Entry signals of every candidate member over the whole history (bar closes 2020-01 .. the data end), computed ONCE per
coin and timeframe on the full series, as research/trendbot/fiveyear/code/signals5y.py does, for 30m and 1h, 6 coins:

- the 36 basic strategies, default numbers: recorder.build_frames -> sweep_lib.compute_signals (all locked names),
  DOGE_L / DOGE_S joined as DOGE with sigservice.doge_join (the rule bot's 36 accounts, sigservice.compute_last);
- the 44 DeepSeek definitions, default numbers: dssig.frame -> dssig.entries_frame with BTC's frame (F14_SMT); a bar
  with both sides is a long (dssig._job, signals5y);
- custom numbers: every candidate-league pick (paperbot/combo.py CANDIDATES_FILE = candleague/data/candidates_owner.json,
  the owner-exit league installed 2026-10-13, 49 picks) whose timeframe is 30m or 1h, resolved by combo.resolve_members
  and computed as combo.CustomSignals._one does: the 36 with paramshadow.param_module(name).signals on the same chart
  frame (side = long - short), DeepSeek with research/fullgrid/ds_defs.py signals on the DeepSeek frame with BTC's frame
  as ctx (coin != BTC), coin = symbol[:-1], cache {} (side = long, else short; ds_defs drops a bar with both).
  A pick whose numbers equal the defaults would be a default member in combo (none is: checked and recorded).

Per label one file signals/<label>.npz: t (bar close, ms), coin (index into COINS), side (+1 / -1), atr (ATR14 of the
signal frame at the signal bar: the rule bot's stop basis, stop_dist = 2 ATR), close (the signal bar's close), ref (the
1m open at the bar close: the engine's reference price; NaN past the data end), plus meta (JSON). signals/index.json:
labels, counts, the data end, the code hashes.
Labels: "<strategy>@<tf>" (default numbers), "<strategy>@<tf>#<pick id>" (custom numbers).
Run: python3 -I signals_all.py [--procs 3] [--coins BTCUSDT,...]"""
import os, sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nlcommon import *
import time, warnings
from multiprocessing import Pool

TFS = ("30m", "1h")


def pick_members():
    """The league's 30m / 1h picks as combo.resolve_members makes them (label = combo's label = the pick id)."""
    from paperbot import combo as C
    picks = C.load_picks(C.CANDIDATES_FILE)
    out = []
    for pid, c in picks.items():
        if c["tf"] not in TFS:
            continue
        m = C.resolve_members([{"pick": pid}])[0]
        out.append({"pick": pid, "kind": m.kind, "name": m.name, "tf": m.tf, "numbers": m.numbers,
                    "equals_default": m.numbers is None, "exit": c.get("exit"), "source": c.get("source", {})})
    return out


def five(coin):
    m = load_grid(coin)
    return m, agg(m, FIVE)


def emit(store, label, close_t, side, atr, close, o1):
    k = np.flatnonzero(side)
    if not len(k):
        store.setdefault(label, [])
        return
    t = close_t[k].astype(np.int64)
    i = (t - T0) // MIN
    ref = np.full(len(k), np.nan)
    ok = i < len(o1)
    ref[ok] = o1[i[ok]]
    store.setdefault(label, []).append(np.c_[t.astype(float), side[k].astype(float), atr[k], close[k], ref])


def job(args):
    coin, picks = args
    from paperbot import sweepsig, dssig, combo as C
    from paperbot.recorder import build_frames
    from paperbot.sigservice import strategy_names, doge_join
    from paperbot.entry_marks import _contained
    from paperbot.paramshadow import param_module
    lib = sweepsig.lib()
    dssig.verify()
    D = C.ds_defs()
    t0 = time.time()
    m, f = five(coin)
    o1 = m["o"]
    del m
    bf = f if coin == "BTCUSDT" else five("BTCUSDT")[1]
    store, log, warn = {}, [], []
    names = strategy_names(lib)
    for tf in TFS:
        t1 = time.time()
        df = build_frames(lib, df_of(f), [tf])[tf]
        close_t = (df["ts"].astype("int64") // 1_000_000).to_numpy() + TF_MS[tf]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            atr = lib.fg.atr(df, 14).to_numpy(float)
        close = df["close"].to_numpy(float)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            sigs = lib.compute_signals({coin: df}, tf, list(lib.NAMES), strict=False)
        warn += [f"{coin} {tf}: {str(w.message)[:200]}" for w in caught if str(w.message).split(" ", 1)[0] in lib.NAMES]
        for n in names:
            if n == "DOGE":
                a = doge_join(sigs["DOGE_L"].get(coin, np.zeros(len(df), np.int8)),
                              sigs["DOGE_S"].get(coin, np.zeros(len(df), np.int8)))
            else:
                a = sigs[n].get(coin)
                if a is None:
                    warn.append(f"{coin} {tf}: {n} gave no array (compute_signals failed)")
                    continue
            emit(store, label_of(n, tf), close_t, np.asarray(a, np.int8), atr, close, o1)
        t2 = time.time()
        # DeepSeek frames (zero-volume 5m bars dropped, dssig.frame)
        dfd = dssig.frame(f["ts"], f["o"], f["h"], f["l"], f["c"], f["v"], tf=tf, lib=lib)
        bdf = None if coin == "BTCUSDT" else dssig.frame(bf["ts"], bf["o"], bf["h"], bf["l"], bf["c"], bf["v"], tf=tf,
                                                         lib=lib)
        closed = (dfd["ts"].astype("int64") // 1_000_000).to_numpy() + TF_MS[tf]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            atr_d = lib.fg.atr(dfd, 14).to_numpy(float)
        close_d = dfd["close"].to_numpy(float)
        R, notes = dssig.entries_frame(dfd, tf, dssig.coin_key(coin), bdf)
        warn += [f"{coin} {tf}: {x}" for x in notes]
        for d in dssig.defs_for(tf):
            lg, sh = R[d]
            lg, sh = np.asarray(lg, bool), np.asarray(sh, bool)
            side = np.where(lg, 1, np.where(sh, -1, 0)).astype(np.int8)
            emit(store, label_of(d, tf), closed, side, atr_d, close_d, o1)
        t3 = time.time()
        # custom numbers (combo.CustomSignals._one on the full series)
        for p in picks:
            if p["tf"] != tf or p["numbers"] is None:
                continue
            numbers = {k: (tuple(v) if isinstance(v, list) else v) for k, v in p["numbers"].items()}
            with _contained(), warnings.catch_warnings():
                warnings.simplefilter("ignore")
                if p["kind"] == "core":
                    lo, sh = param_module(p["name"]).signals(df.copy(), tf, **numbers)
                    side = (np.asarray(lo).astype(bool).astype(np.int8) - np.asarray(sh).astype(bool).astype(np.int8))
                    emit(store, label_of(p["name"], tf, p["pick"]), close_t, side, atr, close, o1)
                else:
                    ctx = {"BTCUSD": bdf.copy()} if (bdf is not None and len(bdf)) else None
                    lo, sh = D.signals(dfd.copy(), tf, p["name"], ctx=ctx, coin=coin[:-1], cache={}, **numbers)
                    lo, sh = np.asarray(lo, bool), np.asarray(sh, bool)
                    side = np.where(lo, 1, np.where(sh, -1, 0)).astype(np.int8)
                    emit(store, label_of(p["name"], tf, p["pick"]), closed, side, atr_d, close_d, o1)
        log.append(f"{coin} {tf}: core {t2 - t1:.0f}s ds {t3 - t2:.0f}s custom {time.time() - t3:.0f}s "
                   f"bars {len(df)} / ds {len(dfd)}")
    out = {k: (np.concatenate(v) if v else np.zeros((0, 5))) for k, v in store.items()}
    return coin, out, log, warn, time.time() - t0


def code_hashes():
    from paperbot import sweepsig, dssig, paramshadow
    from paperbot import combo as C
    return {"sweep_prereg": sweepsig.verify()["prereg_sha256_file"], "dssig_pins": dssig.verify(),
            "param_defs_manifest": paramshadow.defs_manifest(),
            "ds_defs.py": sha256(C.DS_DEFS_FILE), "candidates_owner.json": sha256(C.CANDIDATES_FILE)}


def main():
    procs = int(sys.argv[sys.argv.index("--procs") + 1]) if "--procs" in sys.argv else 3
    coins = sys.argv[sys.argv.index("--coins") + 1].split(",") if "--coins" in sys.argv else COINS
    out_dir = SIG if coins == COINS else f"{NL}/signals_test"
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.time()
    picks = pick_members()
    print(f"{len(picks)} picks at 30m/1h; equal to defaults: {[p['pick'] for p in picks if p['equals_default']]}", flush=True)
    per = {}
    warns = []
    with Pool(procs) as pool:
        for coin, out, log, warn, dt in pool.imap_unordered(job, [(c, picks) for c in coins]):
            per[coin] = out
            warns += warn
            print("\n".join(log), f"| {coin} done {dt:.0f}s", flush=True)
    labels = sorted(set().union(*[set(v) for v in per.values()]))
    pk = {label_of(p["name"], p["tf"], p["pick"]): p for p in picks}
    from paperbot import config as CF
    ds_ids = set(CF.DS200_IDS)
    a21 = ms("2021-01-01")
    index = {"data": data_manifest(), "coins": COINS, "code": code_hashes(), "warnings": warns, "labels": {},
             "picks_file": "candleague/data/candidates_owner.json", "picks_30m_1h": picks,
             "built": str(pd.Timestamp.now(tz="UTC")), "elapsed_s": None}
    for lab in labels:
        name, tf, pick = parse_label(lab)
        parts = []
        for ci, c in enumerate(coins):
            a = per[c].get(lab)
            if a is not None and len(a):
                parts.append(np.c_[a, np.full(len(a), COINS.index(c))])
        A = np.concatenate(parts) if parts else np.zeros((0, 6))
        order = np.lexsort((A[:, 5], A[:, 0])) if len(A) else np.zeros(0, int)
        A = A[order]
        kind = "ds" if name in ds_ids else "core"
        meta = {"label": lab, "name": name, "tf": tf, "kind": kind, "pick": pick,
                "numbers": pk[lab]["numbers"] if pick else None, "default_numbers": pick is None,
                "data_end": DATA_END, "coins": coins}
        np.savez(sig_path(lab, out_dir), t=A[:, 0].astype(np.int64), side=A[:, 1].astype(np.int8), atr=A[:, 2], close=A[:, 3],
                 ref=A[:, 4], coin=A[:, 5].astype(np.int8), meta=np.array(json.dumps(meta)))
        t = A[:, 0]
        index["labels"][lab] = {**{k: meta[k] for k in ("name", "tf", "kind", "pick", "default_numbers")},
                                "n_all": int(len(A)), "n_2021_on": int((t >= a21).sum()),
                                "n_long_2021_on": int(((t >= a21) & (A[:, 1] > 0)).sum()),
                                "n_short_2021_on": int(((t >= a21) & (A[:, 1] < 0)).sum()),
                                "per_coin_2021_on": {c: int(((t >= a21) & (A[:, 5] == COINS.index(c))).sum())
                                                     for c in coins}}
    index["elapsed_s"] = round(time.time() - t0, 1)
    json.dump(index, open(f"{out_dir}/index.json", "w"), indent=1, default=str)
    print(f"{len(labels)} labels, {sum(v['n_all'] for v in index['labels'].values())} signals, "
          f"{len(warns)} warnings, {index['elapsed_s']}s", flush=True)
    for w in warns[:20]:
        print("  warn:", w)


if __name__ == "__main__":
    main()
