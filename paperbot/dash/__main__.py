"""python -m paperbot.dash [--db paper3.db] [--agents-db agents3.db] [--inbox-db inbox.db] [--host 127.0.0.1] [--port 8080]
python -m paperbot.dash hash            # prints a DASH_PASSWORD_HASH for a password you type"""

import argparse
import getpass
import os
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="serve", choices=["serve", "hash"])
    ap.add_argument("--db", default="paper3.db")
    ap.add_argument("--agents-db", default=None, help="agents3.db written by the agents tick (read-only here)")
    ap.add_argument("--inbox-db", default=None,
                    help="inbox.db: owner posts and approve/reject clicks (the dashboard is its only writer)")
    ap.add_argument("--daily-db", default=None, help="daily3.db written by the nightly check (stop what-ifs)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args(argv)
    from .app import create_app, hash_password
    if args.cmd == "hash":
        pw = getpass.getpass("dashboard password: ")
        if len(pw) < 12:
            print("use at least 12 characters", file=sys.stderr)
            return 1
        if pw != getpass.getpass("again: "):
            print("passwords differ", file=sys.stderr)
            return 1
        print(hash_password(pw))
        return 0
    pw_hash = os.environ.get("DASH_PASSWORD_HASH")
    secret = os.environ.get("DASH_SECRET", "")
    if not pw_hash or len(secret) < 32:
        print("set DASH_PASSWORD_HASH (python -m paperbot.dash hash) and DASH_SECRET (32+ random chars)",
              file=sys.stderr)
        return 1
    import uvicorn
    try:
        app = create_app(args.db, pw_hash, secret.encode(), agents_db=args.agents_db, daily_db=args.daily_db,
                         inbox_db=args.inbox_db)
    except ValueError as exc:            # e.g. --inbox-db pointing at another process's database
        print(f"refusing to start: {exc}", file=sys.stderr)
        return 2
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", proxy_headers=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
