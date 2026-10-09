"""python -m demobot {warm|run|tick|status|selfcheck}

  warm       first fill: 26 weeks of history, all signals and outcomes (~10-15 min, nice'd)
  run        the service loop (one tick after every 15-minute close)
  tick       one tick now (for a manual check), then exit
  rank       the hourly ranking (demobot-rank.timer): reads the database, writes the rank files, exits
  status     a short status from the database
  selfcheck  hash checks of the locked signal code and a memo-vs-plain signal check
"""
import argparse
import json
import os
import sys
import time


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m demobot")
    ap.add_argument("cmd", choices=["warm", "run", "tick", "rank", "status", "selfcheck"])
    ap.add_argument("--db", default=None)
    ap.add_argument("--snap", default=None)
    ap.add_argument("--weeks", type=int, default=26)
    args = ap.parse_args(argv)
    try:
        os.nice(5)
    except OSError:
        pass
    from . import store as ST
    if args.cmd == "selfcheck":
        import numpy as np
        from . import grid as G
        from . import locked as LK
        info = LK.verify()
        rng = np.random.default_rng(1)
        n = 1200
        c = 100 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))
        o = np.r_[c[0], c[:-1]]
        h = np.maximum(o, c) * (1 + rng.uniform(0, 0.002, n))
        lo = np.minimum(o, c) * (1 - rng.uniform(0, 0.002, n))
        v = rng.uniform(100, 1000, n)
        ts = (1_700_000_000_000 // 900_000) * 900_000 + np.arange(n) * 900_000
        df = LK.frame(ts, o, h, lo, c, v, "15m")
        ok = all(LK.selfcheck(df, "15m", s) for s in G.STRATS)
        print(json.dumps({"locked": info, "memo_equals_plain": ok}, ensure_ascii=False))
        return 0 if ok else 1
    if args.cmd in ("rank", "status", "run", "tick") and not os.path.exists(args.db or ST.default_db()):
        print("no database yet: run `python -m demobot warm` first", file=sys.stderr)
        return 2
    conn = ST.connect(args.db)
    if args.snap:
        os.environ["DEMOBOT_SNAP"] = args.snap
    if args.cmd == "status":
        print(json.dumps({"history_start_ms": ST.get_meta(conn, "history_start_ms"),
                          "warm_done_ms": ST.get_meta(conn, "warm_done_ms"),
                          "live_start_ms": ST.get_meta(conn, "live_start_ms"),
                          "last_rank_ms": ST.get_meta(conn, "last_rank_ms"),
                          "db_mb": round(ST.db_mb(args.db), 1)}, ensure_ascii=False))
        return 0
    if args.cmd == "rank":
        from . import rank as RK
        meta = RK.run_standalone(conn, args.snap or ST.default_snap(), int(time.time() * 1000))
        print(json.dumps({k: v for k, v in meta.items() if k == "files"}, ensure_ascii=False))
        return 0
    if args.cmd == "warm":
        from .engine import Engine
        eng = Engine(conn)
        out = eng.warm(weeks=args.weeks)
        print(json.dumps(out, ensure_ascii=False))
        return 0
    from .live import Runner
    r = Runner(conn, snap=args.snap)
    if args.cmd == "tick":
        r.start()
        r.tick()
        return 0
    r.loop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
